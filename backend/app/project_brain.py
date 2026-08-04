from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from .activity_domain import activity_event_from_record
from .calendar_tools import list_upcoming_events
from .dependency_evaluator import (
    DependencyEvaluationState,
    EvaluatedDependencyEvidence,
    dependency_evaluator,
    summarize_dependency_evidence,
)
from .linear_client import LinearClient, LinearProviderError
from .linear_work_adapter import linear_work_adapter
from .recommendation_service import (
    RecommendationAction,
    WorkRecommendation,
    recommendation_service,
)
from .project_registry import (
    ProjectRegistrySnapshot,
    project_registry_service,
)
from .project_activity_focus import (
    ExplicitProjectIntent,
    ProviderCoverage,
    ProviderCoverageState,
    project_activity_focus_service,
)
from .project_work_packages import (
    LinearProjectDiagnostic,
    project_work_package_service,
)
from .provider_changes import (
    ObservationAvailability,
    ObservationFreshness,
    provider_change_service,
)
from .storage import (
    get_latest_project_focus_intent,
    list_activity,
    list_memory_entries,
)
from .todoist_work_adapter import todoist_work_adapter
from .todoist_tools import (
    LIFE_AREA_TO_TODOIST_SECTION,
    TODOIST_SECTION_TO_LIFE_AREA,
    life_area_for_todoist_section,
    list_active_tasks,
)
from .work_domain import NormalizedWorkItem, WorkProviderReadState, WorkStatus


BLOCKER_WORDS = ("blocked", "blocking", "waiting", "review", "feedback")
FOLLOW_UP_WORDS = ("follow up", "follow-up", "waiting", "pending", "review", "feedback")


@dataclass(frozen=True)
class ProjectBrainProjectSnapshot:
    definition: dict[str, Any]
    summary: dict[str, Any]
    work_items: tuple[NormalizedWorkItem, ...]
    recommendation_candidates: tuple[NormalizedWorkItem, ...]
    canonical_recommendation: WorkRecommendation | None


@dataclass(frozen=True)
class ProjectBrainSnapshot:
    now: datetime
    projects: tuple[ProjectBrainProjectSnapshot, ...]
    normalized_work: tuple[NormalizedWorkItem, ...]
    warnings: tuple[str, ...] = ()
    work_provider_states: tuple[WorkProviderReadState, ...] = ()

    def project_for_key(self, key: str) -> ProjectBrainProjectSnapshot | None:
        return next(
            (project for project in self.projects if project.definition["key"] == key),
            None,
        )

    def project_for_canonical_id(
        self,
        canonical_project_id: str | None,
    ) -> ProjectBrainProjectSnapshot | None:
        if not canonical_project_id:
            return None
        return next(
            (
                project
                for project in self.projects
                if project.definition.get("canonical_project_id")
                == canonical_project_id
            ),
            None,
        )


class ProjectBrainService:
    def __init__(self, registry_service=project_registry_service):
        self.registry_service = registry_service

    def list_projects(self, *, settings: Any, current_time: datetime | None = None) -> list[dict[str, Any]]:
        return [
            project.summary
            for project in self.snapshot(
                settings=settings,
                current_time=current_time,
            ).projects
        ]

    def snapshot(
        self,
        *,
        settings: Any,
        current_time: datetime | None = None,
    ) -> ProjectBrainSnapshot:
        registry = self.registry_service.snapshot()
        local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)
        todoist_result = list_active_tasks(settings)
        todoist_tasks = todoist_work_adapter.adapt_many(
            todoist_result.tasks,
            registry=registry,
            today=local_now.date(),
        )
        calendar_result = list_upcoming_events(settings, now=current_time, days=14)
        events = _future_events(calendar_result.events, local_now)
        memories = [memory for memory in list_memory_entries() if memory.get("enabled")]
        activity = list_activity(limit=None)
        todoist_coverage = _todoist_coverage(todoist_result.error, local_now)
        project_snapshots: list[ProjectBrainProjectSnapshot] = []
        linear_work: list[NormalizedWorkItem] = []
        work_provider_states = [
            WorkProviderReadState(
                provider="todoist",
                available=todoist_result.error is None,
                error=todoist_result.error,
            )
        ]
        warnings = [
            error
            for error in (todoist_result.error, calendar_result.error)
            if error
        ]

        for project in registry.projects:
            linear_tasks, dependency_evidence, linear_diagnostic = _read_mapped_linear_work(
                project=project,
                registry=registry,
                settings=settings,
                observed_at=local_now,
            )
            linear_work.extend(linear_tasks)
            project_snapshots.append(
                self.build_project_snapshot(
                    project=project,
                    tasks=[*todoist_tasks, *linear_tasks],
                    events=events,
                    memories=memories,
                    activity=activity,
                    now=local_now,
                    registry=registry,
                    linear_diagnostic=linear_diagnostic,
                    dependency_evidence=dependency_evidence,
                    provider_coverage=(
                        todoist_coverage,
                        _linear_coverage(linear_diagnostic, linear_tasks, local_now),
                    ),
                )
            )
            if linear_diagnostic.status not in {"connected", "not_mapped"}:
                warnings.append(linear_diagnostic.message)
            if linear_diagnostic.status != "not_mapped":
                work_provider_states.append(
                    WorkProviderReadState(
                        provider="linear",
                        provider_reference=linear_diagnostic.provider_ref,
                        available=linear_diagnostic.status == "connected",
                        error=(
                            None
                            if linear_diagnostic.status == "connected"
                            else linear_diagnostic.message
                        ),
                    )
                )

        return ProjectBrainSnapshot(
            now=local_now,
            projects=tuple(project_snapshots),
            normalized_work=tuple([*todoist_tasks, *linear_work]),
            warnings=tuple(dict.fromkeys(warnings)),
            work_provider_states=tuple(work_provider_states),
        )

    def get_project(
        self,
        project_key: str,
        *,
        settings: Any,
        current_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        registry = self.registry_service.snapshot()
        canonical_key = registry.resolve_key(project_key)
        local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)
        todoist_result = list_active_tasks(settings)
        tasks = todoist_work_adapter.adapt_many(
            todoist_result.tasks,
            registry=registry,
            today=local_now.date(),
        )
        calendar_result = list_upcoming_events(settings, now=current_time, days=14)
        events = _future_events(calendar_result.events, local_now)
        memories = [memory for memory in list_memory_entries() if memory.get("enabled")]
        activity = list_activity(limit=None)
        todoist_coverage = _todoist_coverage(todoist_result.error, local_now)
        return next(
            (
                self._build_project_with_linear(
                    project=project,
                    todoist_tasks=tasks,
                    events=events,
                    memories=memories,
                    activity=activity,
                    now=local_now,
                    registry=registry,
                    settings=settings,
                    todoist_coverage=todoist_coverage,
                )
                for project in registry.projects
                if project["key"] == canonical_key
            ),
            None,
        )

    def canonical_project_key(self, project_key: str) -> str:
        return self.registry_service.snapshot().resolve_key(project_key)

    def _build_project_with_linear(
        self,
        *,
        project: dict[str, Any],
        todoist_tasks: list[NormalizedWorkItem],
        events: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        activity: list[dict[str, Any]],
        now: datetime,
        registry: ProjectRegistrySnapshot,
        settings: Any,
        todoist_coverage: ProviderCoverage,
    ) -> dict[str, Any]:
        linear_tasks, dependency_evidence, linear_diagnostic = _read_mapped_linear_work(
            project=project,
            registry=registry,
            settings=settings,
            observed_at=now,
        )
        return self.build_project(
            project=project,
            tasks=[*todoist_tasks, *linear_tasks],
            events=events,
            memories=memories,
            activity=activity,
            now=now,
            registry=registry,
            linear_diagnostic=linear_diagnostic,
            dependency_evidence=dependency_evidence,
            provider_coverage=(
                todoist_coverage,
                _linear_coverage(linear_diagnostic, linear_tasks, now),
            ),
        )

    def build_project(
        self,
        *,
        project: dict[str, Any],
        tasks: list[NormalizedWorkItem],
        events: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        activity: list[dict[str, Any]],
        now: datetime,
        registry: ProjectRegistrySnapshot | None = None,
        linear_diagnostic: LinearProjectDiagnostic | None = None,
        dependency_evidence: tuple[EvaluatedDependencyEvidence, ...] = (),
        provider_coverage: tuple[ProviderCoverage, ...] = (),
    ) -> dict[str, Any]:
        return self.build_project_snapshot(
            project=project,
            tasks=tasks,
            events=events,
            memories=memories,
            activity=activity,
            now=now,
            registry=registry,
            linear_diagnostic=linear_diagnostic,
            dependency_evidence=dependency_evidence,
            provider_coverage=provider_coverage,
        ).summary

    def build_project_snapshot(
        self,
        *,
        project: dict[str, Any],
        tasks: list[NormalizedWorkItem],
        events: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        activity: list[dict[str, Any]],
        now: datetime,
        registry: ProjectRegistrySnapshot | None = None,
        linear_diagnostic: LinearProjectDiagnostic | None = None,
        dependency_evidence: tuple[EvaluatedDependencyEvidence, ...] = (),
        provider_coverage: tuple[ProviderCoverage, ...] = (),
    ) -> ProjectBrainProjectSnapshot:
        registry = registry or self.registry_service.snapshot()
        todoist_tasks = [task for task in tasks if task.provider == "todoist"]
        task_lookup = {
            str(task.get("id")): task for task in todoist_tasks if task.get("id")
        }
        active_tasks = [task for task in todoist_tasks if not _task_completed(task)]
        active_children_by_parent = _children_by_parent(active_tasks)
        project_todoist_tasks = [
            task
            for task in active_tasks
            if _task_matches_project(task, project, registry, task_lookup)
        ]
        project_linear_tasks = [
            task
            for task in tasks
            if task.provider == "linear"
            and task.canonical_project_id == project.get("canonical_project_id")
        ]
        project_work = [*project_todoist_tasks, *project_linear_tasks]
        current_project_work = [
            item for item in project_work if item.status == WorkStatus.OPEN
        ]
        project_events = [
            event for event in events if _event_matches_project(event, project, registry)
        ]
        project_memories = [
            memory for memory in memories if _memory_matches_project(memory, project, registry)
        ]
        project_activity = [
            entry for entry in activity if _activity_matches_project(entry, project, registry)
        ]
        people = _project_people(project, project_memories)
        task_groups = _project_task_groups(
            project_todoist_tasks,
            task_lookup,
            active_children_by_parent,
        )
        recommendation_candidates = _project_leaf_tasks(
            project_work,
            active_children_by_parent,
        )
        recommendation = recommendation_service.recommend_project_next_move(
            recommendation_candidates,
            current_time=now,
        )
        ranked_tasks = _project_ranked_tasks(recommendation, recommendation_candidates)
        sorted_tasks = _sort_project_tasks(project_todoist_tasks)
        sorted_events = sorted(project_events, key=_event_start)
        project_dependency_evidence = tuple(
            evidence
            for evidence in dependency_evidence
            if evidence.canonical_project_id == project.get("canonical_project_id")
        )
        current_dependency_evidence = tuple(
            evidence
            for evidence in project_dependency_evidence
            if evidence.blocked_work.status == WorkStatus.OPEN
        )
        attention_signals = _project_attention_signals(
            project=project,
            tasks=sorted_tasks,
            events=sorted_events,
            ranked_tasks=ranked_tasks,
            now=now,
        )
        blockers = _project_dependency_blockers(current_dependency_evidence)
        dependency_summary = summarize_dependency_evidence(
            project_dependency_evidence,
            canonical_project_id=str(project.get("canonical_project_id") or ""),
        )
        work_packages = project_work_package_service.build_current_packages(
            project_linear_tasks,
            canonical_project_id=str(project.get("canonical_project_id") or ""),
            canonical_project_key=str(project["key"]),
            current_time=now,
            dependency_evidence=project_dependency_evidence,
        )
        has_executable_action = bool(
            recommendation
            and recommendation.action == RecommendationAction.DO_WORK
        )
        selected_next_step = _selected_work_item(recommendation, recommendation_candidates)
        canonical_project_id = str(
            project.get("canonical_project_id") or f"system:{project['key']}"
        )
        activity_focus = project_activity_focus_service.evaluate(
            canonical_project_id=canonical_project_id,
            canonical_project_key=str(project["key"]),
            work_items=project_work,
            activity_records=project_activity,
            dependency_evidence=project_dependency_evidence,
            provider_coverage=provider_coverage,
            evaluated_at=now,
            explicit_intent=_latest_explicit_intent(canonical_project_id),
            next_step=selected_next_step,
        )
        recent_changes = provider_change_service.query_changes(
            canonical_project_id=canonical_project_id,
            days=30,
            evaluated_at=now,
            limit=12,
        )

        summary = {
            "key": project["key"],
            "name": project["name"],
            "description": project["description"],
            "task_count": len(sorted_tasks),
            "status": _project_status(
                dependency_evidence=current_dependency_evidence,
                attention_signals=attention_signals,
                has_executable_action=has_executable_action,
                tasks=current_project_work,
                events=sorted_events,
            ),
            "next_recommendation": _project_next_recommendation(
                recommendation=recommendation,
                ranked_tasks=ranked_tasks,
                events=sorted_events,
                memories=project_memories,
            ),
            "blockers": blockers[:8],
            "attention_signals": attention_signals[:8],
            "dependency_summary": dependency_summary,
            "dependency_evidence": project_dependency_evidence,
            "tasks": [_task_item(task, _todoist_task_section_for(task)) for task in sorted_tasks[:12]],
            "task_groups": task_groups[:12],
            "classification_diagnostics": _project_task_diagnostics(
                project=project,
                tasks=todoist_tasks,
                task_lookup=task_lookup,
                active_children_by_parent=active_children_by_parent,
                registry=registry,
            ),
            "upcoming_events": [_project_event_item(event) for event in sorted_events[:8]],
            "people": people,
            "memories": project_memories[:8],
            "recent_activity": project_activity[:8],
            "work_packages": work_packages,
            "linear_diagnostic": linear_diagnostic,
            "activity_focus": activity_focus,
            "recent_changes": recent_changes,
        }
        return ProjectBrainProjectSnapshot(
            definition=project,
            summary=summary,
            work_items=tuple(project_work),
            recommendation_candidates=tuple(recommendation_candidates),
            canonical_recommendation=recommendation,
        )


project_brain_service = ProjectBrainService()


def _selected_work_item(
    recommendation: WorkRecommendation | None,
    candidates: list[NormalizedWorkItem],
) -> NormalizedWorkItem | None:
    if recommendation is None:
        return None
    identity = (
        recommendation.selected_work.provider,
        recommendation.selected_work.provider_record_id,
    )
    return next(
        (
            item
            for item in candidates
            if (item.provider, item.provider_record_id) == identity
        ),
        None,
    )


def _todoist_coverage(error: str | None, observed_at: datetime) -> ProviderCoverage:
    if error is None:
        return ProviderCoverage(
            provider="todoist",
            state=ProviderCoverageState.MISSING_HISTORY,
            observed_at=observed_at,
            detail="Todoist active-task data is current, but completed-work history is not available through this read path.",
        )
    state = (
        ProviderCoverageState.NOT_CONFIGURED
        if "missing" in error.lower()
        else ProviderCoverageState.UNAVAILABLE
    )
    return ProviderCoverage(
        provider="todoist",
        state=state,
        observed_at=observed_at,
        detail=error,
    )


def _linear_coverage(
    diagnostic: LinearProjectDiagnostic,
    work_items: list[NormalizedWorkItem],
    observed_at: datetime,
) -> ProviderCoverage:
    state_map = {
        "not_mapped": ProviderCoverageState.NOT_APPLICABLE,
        "not_configured": ProviderCoverageState.NOT_CONFIGURED,
        "authentication_failure": ProviderCoverageState.UNAVAILABLE,
        "provider_failure": ProviderCoverageState.UNAVAILABLE,
        "malformed_response": ProviderCoverageState.UNAVAILABLE,
    }
    if diagnostic.status != "connected":
        return ProviderCoverage(
            provider="linear",
            provider_reference=diagnostic.provider_ref,
            state=state_map.get(diagnostic.status, ProviderCoverageState.UNKNOWN),
            observed_at=observed_at,
            detail=diagnostic.message,
        )
    history_start = min(
        (
            timestamp
            for item in work_items
            for timestamp in (item.created_at, item.updated_at)
            if timestamp is not None
            and timestamp.tzinfo is not None
            and timestamp.utcoffset() is not None
        ),
        default=None,
    )
    return ProviderCoverage(
        provider="linear",
        provider_reference=diagnostic.provider_ref,
        state=(
            ProviderCoverageState.FRESH
            if history_start is not None
            else ProviderCoverageState.MISSING_HISTORY
        ),
        observed_at=observed_at,
        historical_coverage_start=history_start,
        detail=diagnostic.message,
    )


def _latest_explicit_intent(
    canonical_project_id: str,
) -> ExplicitProjectIntent | None:
    raw = get_latest_project_focus_intent(canonical_project_id)
    if raw is None:
        return None
    return ExplicitProjectIntent.model_validate(
        {
            key: raw.get(key)
            for key in (
                "id",
                "canonical_project_id",
                "confirmed_state",
                "reason",
                "confirmed_at",
                "expires_at",
                "review_after",
                "review_trigger",
            )
        }
    )


def _read_mapped_linear_work(
    *,
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
    settings: Any,
    observed_at: datetime,
) -> tuple[
    list[NormalizedWorkItem],
    tuple[EvaluatedDependencyEvidence, ...],
    LinearProjectDiagnostic,
]:
    canonical_project_id = str(
        project.get("canonical_project_id") or f"system:{project['key']}"
    )
    mapping = registry.diagnose_canonical_project_mapping(
        str(project["key"]),
        provider="linear",
        resource_type="project",
    )
    if mapping.status != "mapped" or not mapping.provider_ref:
        provider_change_service.record_coverage(
            provider="linear",
            scope_id=f"canonical:{canonical_project_id}",
            canonical_project_id=canonical_project_id,
            availability=ObservationAvailability.NOT_APPLICABLE,
            observed_at=observed_at,
            diagnostic="This canonical project has no Linear project mapping.",
        )
        return [], (), LinearProjectDiagnostic(
            status="not_mapped",
            message="This canonical project has no Linear project mapping.",
        )

    project_id = mapping.provider_ref
    try:
        result = LinearClient(settings).list_issues(project_id=project_id)
    except Exception:
        provider_change_service.record_coverage(
            provider="linear",
            scope_id=project_id,
            canonical_project_id=canonical_project_id,
            availability=ObservationAvailability.UNAVAILABLE,
            observed_at=observed_at,
            diagnostic="Linear could not be reached.",
        )
        return [], (), LinearProjectDiagnostic(
            status="provider_failure",
            provider_ref=project_id,
            message="Linear could not be reached; existing Project Brain sources remain available.",
        )
    if result.error:
        provider_change_service.record_coverage(
            provider="linear",
            scope_id=project_id,
            canonical_project_id=canonical_project_id,
            availability=(
                ObservationAvailability.NOT_CONFIGURED
                if result.error.code == "not_configured"
                else ObservationAvailability.UNAVAILABLE
            ),
            observed_at=observed_at,
            diagnostic=result.error.message,
        )
        return [], (), _linear_failure_diagnostic(project_id, result.error)

    for record in result.records:
        provider_project = record.get("project") if isinstance(record, dict) else None
        if not isinstance(provider_project, dict) or str(provider_project.get("id") or "") != project_id:
            provider_change_service.record_coverage(
                provider="linear",
                scope_id=project_id,
                canonical_project_id=canonical_project_id,
                availability=ObservationAvailability.UNAVAILABLE,
                observed_at=observed_at,
                diagnostic="Linear returned an issue outside the mapped project boundary.",
            )
            return [], (), LinearProjectDiagnostic(
                status="malformed_response",
                provider_ref=project_id,
                message="Linear returned an issue outside the mapped project boundary.",
            )
    try:
        adapted = linear_work_adapter.adapt_many(result.records)
    except (TypeError, ValueError):
        provider_change_service.record_coverage(
            provider="linear",
            scope_id=project_id,
            canonical_project_id=canonical_project_id,
            availability=ObservationAvailability.UNAVAILABLE,
            observed_at=observed_at,
            diagnostic="Linear returned issue data that could not be normalized.",
        )
        return [], (), LinearProjectDiagnostic(
            status="malformed_response",
            provider_ref=project_id,
            message="Linear returned issue data that could not be normalized.",
        )

    mapped_items = [
        item.model_copy(update={"canonical_project_id": canonical_project_id})
        for item in adapted
    ]
    if len(mapped_items) != len(result.records):
        provider_change_service.record_coverage(
            provider="linear",
            scope_id=project_id,
            canonical_project_id=canonical_project_id,
            availability=ObservationAvailability.UNAVAILABLE,
            observed_at=observed_at,
            diagnostic="Linear returned incomplete issue data for the mapped project.",
        )
        return [], (), LinearProjectDiagnostic(
            status="malformed_response",
            provider_ref=project_id,
            message="Linear returned incomplete issue data for the mapped project.",
        )
    evaluated = dependency_evaluator.evaluate(mapped_items, registry=registry)
    try:
        issue_observations = tuple(
            linear_work_adapter.change_observation(
                item,
                scope_id=project_id,
                observed_at=observed_at,
            )
            for item in mapped_items
        )
        milestone_observations = linear_work_adapter.milestone_change_observations(
            mapped_items,
            scope_id=project_id,
            observed_at=observed_at,
        )
        provider_change_service.observe_scope(
            provider="linear",
            scope_id=project_id,
            canonical_project_id=canonical_project_id,
            observations=(*issue_observations, *milestone_observations),
            observed_at=observed_at,
            # Linear exposes current state here, not a revision log. Comparison
            # coverage therefore begins with PCOS's first successful observation.
            historical_coverage_start=observed_at,
            freshness=ObservationFreshness.FRESH,
            diagnostic="Mapped Linear comparison state loaded successfully.",
        )
    except (TypeError, ValueError) as exc:
        provider_change_service.record_coverage(
            provider="linear",
            scope_id=project_id,
            canonical_project_id=canonical_project_id,
            availability=ObservationAvailability.UNAVAILABLE,
            observed_at=observed_at,
            diagnostic=f"Linear comparison state could not be normalized: {exc}",
        )
    return list(evaluated.work_items), evaluated.evidence, LinearProjectDiagnostic(
        status="connected",
        provider_ref=project_id,
        issue_count=len(mapped_items),
        message="Mapped Linear work loaded successfully.",
    )


def _linear_failure_diagnostic(
    project_id: str,
    error: LinearProviderError,
) -> LinearProjectDiagnostic:
    status_by_code = {
        "not_configured": "not_configured",
        "authentication": "authentication_failure",
        "provider": "provider_failure",
        "malformed_response": "malformed_response",
    }
    message_by_code = {
        "not_configured": "Linear is not configured; existing Project Brain sources remain available.",
        "authentication": "Linear authentication or permission failed; existing Project Brain sources remain available.",
        "provider": "Linear could not be reached; existing Project Brain sources remain available.",
        "malformed_response": "Linear returned an incompatible response; existing Project Brain sources remain available.",
    }
    return LinearProjectDiagnostic(
        status=status_by_code[error.code],
        provider_ref=project_id,
        message=message_by_code[error.code],
    )


def _task_matches_project(
    task: NormalizedWorkItem,
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
    task_lookup: dict[str, NormalizedWorkItem] | None = None,
) -> bool:
    if task.provider == "linear":
        return bool(
            task.canonical_project_id
            and task.canonical_project_id == project.get("canonical_project_id")
        )
    parent = _parent_task(task, task_lookup or {})
    if project.get("classification_bucket"):
        return _task_needs_classification(task, parent=parent, registry=registry)
    if (
        task.canonical_project_id
        and task.canonical_project_id == project.get("canonical_project_id")
    ):
        return True
    life_area = project.get("life_area")
    if life_area and _task_section_for(task) == life_area:
        return True
    if parent and life_area and _task_section_for(parent) == life_area:
        return True
    if parent and _text_matches_project(_task_match_text(parent), project):
        return True
    return _text_matches_project(_task_match_text(task), project)


def _event_matches_project(
    event: dict[str, Any],
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
) -> bool:
    explicit_project = event.get("resolved_project") or event.get("project") or event.get("project_key")
    if explicit_project:
        explicit = registry.resolve_key(str(explicit_project))
        if explicit == project["key"] or _slug_text(str(explicit_project)) == _slug_text(project["name"]):
            return True
    title = str(event.get("title") or "")
    prefix_match = re.match(r"^(.+?)\s+[\u2014-]\s+", title)
    if prefix_match and registry.resolve_key(prefix_match.group(1)) == project["key"]:
        return True
    return _text_matches_project(_event_match_text(event), project)


def _memory_matches_project(
    memory: dict[str, Any],
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
) -> bool:
    memory_type = str(memory.get("type") or "").lower()
    title = str(memory.get("title") or "")
    if memory_type == "project" and _same_project_name(title, project, registry):
        return True
    if memory_type in {"person", "group"} and _slug_text(title) in {
        _slug_text(person) for person in project.get("people", ())
    }:
        return True
    return _text_matches_project(_memory_match_text(memory), project)


def _activity_matches_project(
    entry: dict[str, Any],
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
) -> bool:
    event = activity_event_from_record(entry)
    if event is not None and event.canonical_project_id:
        return event.canonical_project_id == project.get("canonical_project_id")
    payload = entry.get("payload") or entry.get("metadata") or {}
    if isinstance(payload, dict):
        payload_project = payload.get("resolved_project") or payload.get("project") or payload.get("project_key") or payload.get("project_context")
        task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
        event_payload = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        section_name = task_payload.get("section_name") or task_payload.get("todoist_section_name") or payload.get("section_name")
        if payload_project and registry.resolve_key(str(payload_project)) == project["key"]:
            return True
        if section_name and project.get("life_area") == life_area_for_todoist_section(str(section_name)):
            return True
        if event_payload and _text_matches_project(_event_match_text(event_payload), project):
            return True
    return _text_matches_project(_activity_match_text(entry), project)


def _text_matches_project(text: str, project: dict[str, Any]) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if _contains_phrase(normalized, str(project.get("name") or "")):
        return True
    return any(_contains_phrase(normalized, str(value)) for value in (*project.get("keywords", ()), *project.get("people", ())))


def _same_project_name(
    value: str,
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
) -> bool:
    return registry.resolve_key(value) == project["key"] or _slug_text(value) == _slug_text(project["name"])


def _project_people(project: dict[str, Any], memories: list[dict[str, Any]]) -> list[str]:
    people = {str(person) for person in project.get("people", ())}
    people.update(
        str(memory.get("title") or "").strip()
        for memory in memories
        if str(memory.get("type") or "").lower() == "person" and str(memory.get("title") or "").strip()
    )
    return sorted(people)


def _children_by_parent(
    tasks: list[NormalizedWorkItem],
) -> dict[str, list[NormalizedWorkItem]]:
    children: dict[str, list[NormalizedWorkItem]] = {}
    for task in tasks:
        parent_id = str(task.get("parent_id") or "").strip()
        if parent_id:
            children.setdefault(parent_id, []).append(task)
    return children


def _parent_task(
    task: NormalizedWorkItem,
    task_lookup: dict[str, NormalizedWorkItem],
) -> NormalizedWorkItem | None:
    parent_id = str(task.get("parent_id") or "").strip()
    return task_lookup.get(parent_id) if parent_id else None


def _task_completed(task: NormalizedWorkItem) -> bool:
    return task.status == WorkStatus.COMPLETED


def _task_is_container(
    task: NormalizedWorkItem,
    active_children_by_parent: dict[str, list[NormalizedWorkItem]],
) -> bool:
    return task.is_container


def _project_leaf_tasks(
    tasks: list[NormalizedWorkItem],
    active_children_by_parent: dict[str, list[NormalizedWorkItem]],
) -> list[NormalizedWorkItem]:
    return [
        task
        for task in tasks
        if task.is_executable
        or (
            task.status == WorkStatus.OPEN
            and task.is_blocked
            and not task.is_container
        )
    ]


def _project_rankable_task(task: NormalizedWorkItem) -> dict[str, Any]:
    rankable = task.to_legacy_task()
    try:
        todoist_priority = int(task.get("todoist_priority") or 0)
    except (TypeError, ValueError):
        todoist_priority = 0
    try:
        priority = int(task.get("priority") or 0)
    except (TypeError, ValueError):
        priority = 0
    rankable["priority"] = max(priority, todoist_priority)
    return rankable


def _project_ranked_tasks(recommendation, tasks: list[NormalizedWorkItem]) -> list[dict[str, Any]]:
    if recommendation is None:
        return []
    by_identity = {
        (task.provider, task.provider_record_id): task for task in tasks
    }
    ordered_identities = [
        (
            recommendation.selected_work.provider,
            recommendation.selected_work.provider_record_id,
        ),
        *(
            (alternative.work.provider, alternative.work.provider_record_id)
            for alternative in recommendation.considered_alternatives
        ),
    ]
    return [
        _project_rankable_task(by_identity[identity])
        for identity in ordered_identities
        if identity in by_identity
    ]


def _project_task_groups(
    tasks: list[NormalizedWorkItem],
    task_lookup: dict[str, NormalizedWorkItem],
    active_children_by_parent: dict[str, list[NormalizedWorkItem]],
) -> list[dict[str, Any]]:
    tasks_by_id = {str(task.get("id")): task for task in tasks if task.get("id")}
    grouped_parent_ids = {str(task.get("parent_id")) for task in tasks if task.get("parent_id") and str(task.get("parent_id")) in task_lookup}
    roots = [task for task in tasks if not task.get("parent_id") or str(task.get("id")) in grouped_parent_ids]
    for parent_id in grouped_parent_ids:
        parent = task_lookup.get(parent_id)
        if parent and parent_id not in tasks_by_id:
            roots.append(parent)
    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for parent in _sort_project_tasks(roots):
        parent_id = str(parent.get("id") or "")
        if parent_id in seen:
            continue
        seen.add(parent_id)
        subtasks = [task for task in active_children_by_parent.get(parent_id, []) if str(task.get("id") or "") in tasks_by_id]
        groups.append({
            "parent_task": _task_item(parent, _todoist_task_section_for(parent)),
            "subtasks": [_task_item(task, _todoist_task_section_for(task)) for task in _sort_project_tasks(subtasks)],
            "is_container": _task_is_container(parent, active_children_by_parent),
        })
    return groups


def _project_task_diagnostics(
    *,
    project: dict[str, Any],
    tasks: list[NormalizedWorkItem],
    task_lookup: dict[str, NormalizedWorkItem],
    active_children_by_parent: dict[str, list[NormalizedWorkItem]],
    registry: ProjectRegistrySnapshot,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for task in _sort_project_tasks(tasks):
        parent = _parent_task(task, task_lookup)
        included = _task_matches_project(task, project, registry, task_lookup) and not _task_completed(task)
        diagnostics.append({
            "task_title": str(task.get("content") or "Untitled task"),
            "parent_title": str(parent.get("content")) if parent else None,
            "todoist_section": task.get("todoist_section_name") or task.get("section_name"),
            "resolved_project": _resolved_project_name_for_task(task, task_lookup, registry),
            "priority": task.get("todoist_priority") or task.get("priority"),
            "included": included,
            "reason": _task_diagnostic_reason(
                task=task,
                project=project,
                parent=parent,
                included=included,
                active_children_by_parent=active_children_by_parent,
                registry=registry,
            ),
        })
    return diagnostics


def _task_diagnostic_reason(
    *,
    task: NormalizedWorkItem,
    project: dict[str, Any],
    parent: NormalizedWorkItem | None,
    included: bool,
    active_children_by_parent: dict[str, list[NormalizedWorkItem]],
    registry: ProjectRegistrySnapshot,
) -> str:
    if _task_completed(task):
        return "excluded: completed"
    if included and task.get("parent_id"):
        return "included: subtask inherited project from parent or section"
    if included and _task_is_container(task, active_children_by_parent):
        return "included: parent container with active children"
    if included:
        return "included: standalone task matched project"
    if project.get("classification_bucket"):
        return "excluded: task already has a resolved project"
    if parent and _task_needs_classification(task, parent=parent, registry=registry):
        return "excluded: needs classification"
    return "excluded: matched another project or no project signal"


def _resolved_project_name_for_task(
    task: NormalizedWorkItem,
    task_lookup: dict[str, NormalizedWorkItem],
    registry: ProjectRegistrySnapshot,
) -> str:
    parent = _parent_task(task, task_lookup)
    for project in registry.projects:
        if not project.get("classification_bucket") and _task_matches_project(
            task,
            project,
            registry,
            task_lookup,
        ):
            return str(project["name"])
    return (
        "Needs Classification"
        if _task_needs_classification(task, parent=parent, registry=registry)
        else "Uncategorized"
    )


def _task_needs_classification(
    task: NormalizedWorkItem,
    *,
    parent: NormalizedWorkItem | None,
    registry: ProjectRegistrySnapshot,
) -> bool:
    if parent:
        for project in registry.projects:
            if not project.get("classification_bucket") and _task_matches_project(
                parent,
                project,
                registry,
                {},
            ):
                return False
    if _task_section_for(task) != "Misc":
        return False
    return not any(
        not project.get("classification_bucket") and _text_matches_project(_task_match_text(task), project)
        for project in registry.projects
    )


def _project_attention_signals(
    *,
    project: dict[str, Any],
    tasks: list[NormalizedWorkItem],
    events: list[dict[str, Any]],
    ranked_tasks: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for task in tasks:
        content = str(task.get("content") or "Untitled task")
        if task.get("due_status") == "overdue":
            signals.append({"type": "overdue_task", "title": content, "detail": "Overdue Todoist task", "severity": "critical", "source_id": task.get("id")})
        if _is_stale_high_priority_task(task, now):
            signals.append({"type": "stale_high_priority_task", "title": content, "detail": "High-priority task has been open for more than 7 days", "severity": "warning", "source_id": task.get("id")})
        blocker_word = _first_matching_phrase(_task_match_text(task), BLOCKER_WORDS)
        if blocker_word:
            signals.append({"type": "keyword_attention", "title": content, "detail": f"Todoist text mentions {blocker_word}; this is not provider-backed dependency evidence", "severity": "warning", "source_id": task.get("id")})
    for event in events:
        follow_up_word = _first_matching_phrase(_event_match_text(event), FOLLOW_UP_WORDS)
        if follow_up_word:
            signals.append({"type": "pending_meeting_follow_up", "title": str(event.get("title") or "Calendar event"), "detail": f"Upcoming event mentions {follow_up_word}", "severity": "warning", "source_id": event.get("id")})
    if events and not ranked_tasks:
        signals.append({"type": "empty_next_step", "title": "No next task before upcoming event", "detail": f"{project['name']} has calendar context but no executable project next step", "severity": "warning", "source_id": None})
    return _dedupe_blockers(signals)


def _project_dependency_blockers(
    evidence: tuple[EvaluatedDependencyEvidence, ...],
) -> list[dict[str, Any]]:
    state_order = {
        DependencyEvaluationState.ACTIVE: 0,
        DependencyEvaluationState.NEEDS_REVIEW: 1,
        DependencyEvaluationState.RESOLVED: 2,
    }
    current = sorted(
        (
            relationship
            for relationship in evidence
            if relationship.evaluation_state
            in {
                DependencyEvaluationState.ACTIVE,
                DependencyEvaluationState.NEEDS_REVIEW,
            }
        ),
        key=lambda relationship: (
            state_order[relationship.evaluation_state],
            relationship.blocked_work.provider_record_id,
            relationship.blocking_work.provider_record_id,
        ),
    )
    return [
        {
            "type": f"explicit_dependency_{relationship.evaluation_state.value}",
            "title": relationship.blocked_work.title
            or relationship.blocked_work.provider_identifier
            or "Blocked Linear work",
            "detail": relationship.explanation,
            "severity": (
                "critical"
                if relationship.evaluation_state == DependencyEvaluationState.ACTIVE
                else "warning"
            ),
            "source_id": relationship.blocked_work.provider_record_id,
        }
        for relationship in current
    ]


def _project_status(
    *,
    dependency_evidence: tuple[EvaluatedDependencyEvidence, ...],
    attention_signals: list[dict[str, Any]],
    has_executable_action: bool,
    tasks: list[NormalizedWorkItem],
    events: list[dict[str, Any]],
) -> str:
    has_active_dependency = any(
        evidence.evaluation_state == DependencyEvaluationState.ACTIVE
        for evidence in dependency_evidence
    )
    has_needs_review = any(
        evidence.evaluation_state == DependencyEvaluationState.NEEDS_REVIEW
        for evidence in dependency_evidence
    )
    if not has_executable_action and has_active_dependency:
        return "Blocked"
    if has_active_dependency or has_needs_review or attention_signals:
        return "Needs attention"
    if tasks or events:
        return "Active"
    return "Quiet"


def _project_next_recommendation(
    *,
    recommendation: WorkRecommendation | None,
    ranked_tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> str:
    if recommendation and recommendation.action == RecommendationAction.RESOLVE_BLOCKER:
        return f"Resolve blocker: {recommendation.selected_work.title}"
    if ranked_tasks:
        return f"Work next: {ranked_tasks[0].get('content')}"
    if events:
        return f"Prepare for: {events[0].get('title') or 'upcoming event'}"
    if memories:
        return "Add a concrete next task from the saved context."
    return "Add a concrete next task."


def _future_events(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    future = [event for event in events if _event_end(event) >= now]
    future.sort(key=_event_start)
    return future


def _sort_project_tasks(
    tasks: list[NormalizedWorkItem],
) -> list[NormalizedWorkItem]:
    due_order = {"overdue": 0, "today": 1, "tomorrow": 2, "this_week": 3, "later": 4}
    return sorted(tasks, key=lambda task: (due_order.get(str(task.get("due_status") or ""), 5), -int(task.get("todoist_priority") or task.get("priority") or 0), str(task.get("due_date") or "9999-12-31"), str(task.get("content") or "").lower()))


def _project_event_item(event: dict[str, Any]) -> dict[str, Any]:
    start = _event_start(event)
    end = _event_end(event)
    return {
        "id": event.get("id"), "title": event.get("title") or "(No title)", "start": start.isoformat(), "end": end.isoformat(),
        "duration_minutes": int(event.get("duration_minutes") or _ceil_minutes_between(start, end)), "all_day": bool(event.get("all_day")),
        "busy": bool(event.get("busy")), "event_type": event.get("event_type") or _calendar_event_category(event),
        "event_category": _calendar_event_category(event), "status": event.get("status"), "transparency": event.get("transparency"),
        "attendees_count": event.get("attendees_count"), "location": event.get("location"), "html_link": event.get("html_link"),
    }


def _is_stale_high_priority_task(task: NormalizedWorkItem, now: datetime) -> bool:
    if not _is_high_priority_task(task):
        return False
    created_at = _parse_datetime(task.get("created_at"))
    if not created_at:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=now.tzinfo)
    return (now - created_at.astimezone(now.tzinfo)).days >= 7


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _dedupe_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str | None]] = set()
    deduped: list[dict[str, Any]] = []
    for blocker in blockers:
        key = (str(blocker.get("type")), str(blocker.get("title")), blocker.get("source_id"))
        if key not in seen:
            seen.add(key)
            deduped.append(blocker)
    return deduped


def _task_match_text(task: NormalizedWorkItem) -> str:
    return " ".join(str(part or "") for part in (task.get("content"), task.get("description"), task.get("project_name"), task.get("section_name"), task.get("todoist_section_name"), task.get("category"), " ".join(str(label) for label in task.get("labels") or [])))


def _event_match_text(event: dict[str, Any]) -> str:
    return " ".join(str(part or "") for part in (event.get("title"), event.get("summary"), event.get("description"), event.get("location"), event.get("resolved_project"), event.get("project"), event.get("project_key")))


def _memory_match_text(memory: dict[str, Any]) -> str:
    return " ".join(str(memory.get(part) or "") for part in ("type", "title", "content"))


def _activity_match_text(entry: dict[str, Any]) -> str:
    return " ".join(str(part or "") for part in (entry.get("type"), entry.get("action_type"), entry.get("title"), entry.get("description"), entry.get("detail"), entry.get("source"), _flatten_text(entry.get("payload") or entry.get("metadata"))))


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return "" if value is None else str(value)


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").replace("-", " ").split())


def _slug_text(value: str) -> str:
    text = value.lower().replace("&", " and ").replace("_", " ").replace("-", " ")
    return "-".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    if len(normalized_phrase) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])", text) is not None
    return normalized_phrase in text


def _first_matching_phrase(text: str, phrases: tuple[str, ...]) -> str | None:
    normalized = _normalize_text(text)
    return next((phrase for phrase in phrases if _contains_phrase(normalized, phrase)), None)


def _task_section_for(task: NormalizedWorkItem) -> str:
    category = str(task.get("category") or task.get("project_category") or "").strip()
    if category in {"A&M", "XO", "Freelance", "Nebulo", "Personal", "Misc"}:
        return category
    section_category = life_area_for_todoist_section(str(task.get("section_name") or "").strip())
    if section_category:
        return section_category
    todoist_section_category = life_area_for_todoist_section(str(task.get("todoist_section_name") or "").strip())
    return todoist_section_category or "Misc"


def _todoist_task_section_for(task: NormalizedWorkItem) -> str:
    section_name = str(task.get("todoist_section_name") or task.get("section_name") or "").strip()
    canonical_section = LIFE_AREA_TO_TODOIST_SECTION.get(_task_section_for(task), LIFE_AREA_TO_TODOIST_SECTION["Misc"])
    return section_name if section_name in TODOIST_SECTION_TO_LIFE_AREA else canonical_section


def _task_item(task: NormalizedWorkItem, section: str) -> dict[str, Any]:
    return {
        "id": task.get("id"), "content": str(task.get("content") or ""), "description": task.get("description"), "section": section,
        "parent_id": task.get("parent_id"), "project_name": task.get("project_name"), "section_name": task.get("section_name"),
        "category": task.get("category") or task.get("project_category") or _task_section_for(task),
        "todoist_section_name": task.get("todoist_section_name") or task.get("section_name"),
        "todoist_section_id": task.get("todoist_section_id") or task.get("section_id"),
        "classification_source": task.get("classification_source") or "fallback", "due": task.get("due"), "due_date": task.get("due_date"),
        "due_status": task.get("due_status"), "priority": task.get("priority"), "todoist_priority": task.get("todoist_priority"),
        "completed": _task_completed(task), "labels": task.get("labels") or [], "url": task.get("url"),
    }


def _is_high_priority_task(task: NormalizedWorkItem) -> bool:
    raw_priority = task.get("todoist_priority")
    try:
        return int(raw_priority if raw_priority is not None else task.get("priority")) >= 4
    except (TypeError, ValueError):
        return False


def _event_start(event: dict[str, Any]) -> datetime:
    value = event.get("start")
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _event_end(event: dict[str, Any]) -> datetime:
    value = event.get("end")
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _ceil_minutes_between(start: datetime, end: datetime) -> int:
    seconds = (end - start).total_seconds()
    return max(0, int(seconds // 60 + (1 if seconds % 60 else 0)))


def _calendar_event_category(event: dict[str, Any]) -> str:
    category = event.get("event_category") or event.get("event_type")
    if category == "soft":
        return "informational"
    return str(category) if category in {"hard", "flexible", "informational"} else "flexible"
