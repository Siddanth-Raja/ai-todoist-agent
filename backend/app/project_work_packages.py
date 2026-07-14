from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .dependency_evaluator import (
    DependencyEvaluationState,
    EvaluatedDependencyEvidence,
)
from .recommendation_service import (
    RecommendationAction,
    WorkRecommendation,
    recommendation_service,
)
from .work_domain import NormalizedWorkItem, WorkDependency, WorkStatus


class WorkPackageAvailability(StrEnum):
    AVAILABLE = "available"
    NEEDS_REVIEW = "needs_review"
    EXPLICITLY_BLOCKED = "explicitly_blocked"
    NO_EXECUTABLE_ACTION = "no_executable_action"


class LinearProjectDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["linear"] = "linear"
    status: Literal[
        "connected",
        "not_mapped",
        "not_configured",
        "authentication_failure",
        "provider_failure",
        "malformed_response",
    ]
    provider_ref: str | None = None
    issue_count: int = 0
    message: str


class ProjectWorkPackageItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_record_id: str
    provider_identifier: str | None = None
    title: str
    status: str
    provider_status: str | None = None
    priority: int
    provider_priority: int | str | None = None
    is_executable: bool
    is_container: bool
    is_blocked: bool
    dependency_evaluation_states: tuple[DependencyEvaluationState, ...] = ()
    explicit_dependencies: tuple[WorkDependency, ...] = ()
    parent_provider_record_id: str | None = None
    provider_url: str | None = None


class ProjectWorkPackageAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_record_id: str
    provider_identifier: str | None = None
    title: str
    provider_url: str | None = None
    explanation: str


class ProjectWorkPackageAlternative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_record_id: str
    title: str


class ProjectWorkPackage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    package_id: str
    canonical_project_id: str
    canonical_project_key: str
    title: str
    context: str
    provider: Literal["linear"] = "linear"
    provider_reference_id: str
    provider_url: str | None = None
    open_action_count: int
    executable_action_count: int
    explicitly_blocked_action_count: int
    needs_review_action_count: int = 0
    availability_state: WorkPackageAvailability
    work_items: tuple[ProjectWorkPackageItem, ...]
    next_action: ProjectWorkPackageAction | None = None
    considered_alternatives: tuple[ProjectWorkPackageAlternative, ...] = ()


@dataclass(frozen=True)
class _RankedPackage:
    package: ProjectWorkPackage
    recommendation_score: float | None


class ProjectWorkPackageService:
    def build_current_packages(
        self,
        work_items: list[NormalizedWorkItem],
        *,
        canonical_project_id: str,
        canonical_project_key: str,
        current_time: datetime,
        dependency_evidence: tuple[EvaluatedDependencyEvidence, ...] = (),
        limit: int = 3,
    ) -> list[ProjectWorkPackage]:
        mapped_open = [
            item
            for item in work_items
            if item.provider == "linear"
            and item.canonical_project_id == canonical_project_id
            and item.status == WorkStatus.OPEN
        ]
        milestone_groups: dict[str, list[NormalizedWorkItem]] = {}
        milestone_metadata: dict[str, dict[str, Any]] = {}
        unmilestoned: list[NormalizedWorkItem] = []
        for item in mapped_open:
            milestone = item.provider_metadata.get("project_milestone")
            if isinstance(milestone, dict) and milestone.get("id"):
                milestone_id = str(milestone["id"])
                milestone_groups.setdefault(milestone_id, []).append(item)
                milestone_metadata[milestone_id] = milestone
            else:
                unmilestoned.append(item)

        ranked: list[_RankedPackage] = []
        for milestone_id, grouped_items in milestone_groups.items():
            milestone = milestone_metadata[milestone_id]
            ranked.append(
                self._build_package(
                    grouped_items,
                    package_id=f"linear:milestone:{milestone_id}",
                    title=str(milestone.get("name") or "Linear milestone"),
                    context="Linear milestone",
                    provider_reference_id=milestone_id,
                    canonical_project_id=canonical_project_id,
                    canonical_project_key=canonical_project_key,
                    current_time=current_time,
                    dependency_evidence=_package_evidence(
                        grouped_items,
                        dependency_evidence,
                    ),
                )
            )
        for item in unmilestoned:
            ranked.append(
                self._build_package(
                    [item],
                    package_id=f"linear:issue:{item.provider_record_id}",
                    title=item.title,
                    context="Unmilestoned Linear issue",
                    provider_reference_id=item.provider_record_id,
                    canonical_project_id=canonical_project_id,
                    canonical_project_key=canonical_project_key,
                    current_time=current_time,
                    dependency_evidence=_package_evidence(
                        [item],
                        dependency_evidence,
                    ),
                )
            )

        ranked.sort(key=_package_ranking_key)
        return [candidate.package for candidate in ranked[: max(0, limit)]]

    def _build_package(
        self,
        items: list[NormalizedWorkItem],
        *,
        package_id: str,
        title: str,
        context: str,
        provider_reference_id: str,
        canonical_project_id: str,
        canonical_project_key: str,
        current_time: datetime,
        dependency_evidence: tuple[EvaluatedDependencyEvidence, ...],
    ) -> _RankedPackage:
        ordered_items = sorted(items, key=_work_item_key)
        recommendation = recommendation_service.recommend_project_next_move(
            ordered_items,
            current_time=current_time,
        )
        executable_count = sum(
            item.is_executable and not item.is_container and not item.is_blocked
            for item in ordered_items
        )
        action_ids = {
            item.provider_record_id for item in ordered_items if not item.is_container
        }
        active_ids = {
            evidence.blocked_work.provider_record_id
            for evidence in dependency_evidence
            if evidence.evaluation_state == DependencyEvaluationState.ACTIVE
            and evidence.blocked_work.provider_record_id in action_ids
        }
        needs_review_ids = {
            evidence.blocked_work.provider_record_id
            for evidence in dependency_evidence
            if evidence.evaluation_state == DependencyEvaluationState.NEEDS_REVIEW
            and evidence.blocked_work.provider_record_id in action_ids
        }
        evidenced_ids = active_ids | needs_review_ids | {
            evidence.blocked_work.provider_record_id
            for evidence in dependency_evidence
        }
        active_ids.update(
            item.provider_record_id
            for item in ordered_items
            if item.is_blocked
            and not item.is_container
            and item.provider_record_id not in evidenced_ids
        )
        blocked_count = len(active_ids)
        needs_review_count = len(needs_review_ids)
        next_action = _next_action(recommendation, ordered_items)
        if next_action is not None:
            availability = WorkPackageAvailability.AVAILABLE
        elif blocked_count:
            availability = WorkPackageAvailability.EXPLICITLY_BLOCKED
        elif needs_review_count:
            availability = WorkPackageAvailability.NEEDS_REVIEW
        else:
            availability = WorkPackageAvailability.NO_EXECUTABLE_ACTION

        provider_url = (
            next_action.provider_url
            if next_action is not None
            else next((item.provider_url for item in ordered_items if item.provider_url), None)
        )
        return _RankedPackage(
            package=ProjectWorkPackage(
                package_id=package_id,
                canonical_project_id=canonical_project_id,
                canonical_project_key=canonical_project_key,
                title=title,
                context=context,
                provider_reference_id=provider_reference_id,
                provider_url=provider_url,
                open_action_count=sum(not item.is_container for item in ordered_items),
                executable_action_count=executable_count,
                explicitly_blocked_action_count=blocked_count,
                needs_review_action_count=needs_review_count,
                availability_state=availability,
                work_items=tuple(
                    _package_item(
                        item,
                        _item_evidence(item, dependency_evidence),
                    )
                    for item in ordered_items
                ),
                next_action=next_action,
                considered_alternatives=_alternatives(recommendation),
            ),
            recommendation_score=(
                recommendation.score
                if recommendation is not None
                and recommendation.action == RecommendationAction.DO_WORK
                else None
            ),
        )


def _next_action(
    recommendation: WorkRecommendation | None,
    items: list[NormalizedWorkItem],
) -> ProjectWorkPackageAction | None:
    if recommendation is None or recommendation.action != RecommendationAction.DO_WORK:
        return None
    selected = next(
        (
            item
            for item in items
            if item.provider == recommendation.selected_work.provider
            and item.provider_record_id
            == recommendation.selected_work.provider_record_id
        ),
        None,
    )
    if selected is None:
        return None
    return ProjectWorkPackageAction(
        provider=selected.provider,
        provider_record_id=selected.provider_record_id,
        provider_identifier=_provider_identifier(selected),
        title=selected.title,
        provider_url=selected.provider_url,
        explanation=recommendation.explanation,
    )


def _alternatives(
    recommendation: WorkRecommendation | None,
) -> tuple[ProjectWorkPackageAlternative, ...]:
    if recommendation is None or recommendation.action != RecommendationAction.DO_WORK:
        return ()
    return tuple(
        ProjectWorkPackageAlternative(
            provider=alternative.work.provider,
            provider_record_id=alternative.work.provider_record_id,
            title=alternative.work.title,
        )
        for alternative in recommendation.considered_alternatives
        if alternative.action == RecommendationAction.DO_WORK
    )


def _package_item(
    item: NormalizedWorkItem,
    dependency_evidence: tuple[EvaluatedDependencyEvidence, ...],
) -> ProjectWorkPackageItem:
    return ProjectWorkPackageItem(
        provider=item.provider,
        provider_record_id=item.provider_record_id,
        provider_identifier=_provider_identifier(item),
        title=item.title,
        status=item.status.value,
        provider_status=item.original_provider_status,
        priority=int(item.priority),
        provider_priority=item.original_provider_priority,
        is_executable=item.is_executable,
        is_container=item.is_container,
        is_blocked=item.is_blocked,
        dependency_evaluation_states=tuple(
            evidence.evaluation_state for evidence in dependency_evidence
        ),
        explicit_dependencies=item.dependencies,
        parent_provider_record_id=item.parent_provider_record_id,
        provider_url=item.provider_url,
    )


def _provider_identifier(item: NormalizedWorkItem) -> str | None:
    value = item.provider_metadata.get("issue_identifier")
    return str(value) if value else None


def _package_ranking_key(candidate: _RankedPackage) -> tuple:
    availability_order = {
        WorkPackageAvailability.AVAILABLE: 0,
        WorkPackageAvailability.NEEDS_REVIEW: 1,
        WorkPackageAvailability.EXPLICITLY_BLOCKED: 2,
        WorkPackageAvailability.NO_EXECUTABLE_ACTION: 3,
    }
    score = candidate.recommendation_score
    return (
        availability_order[candidate.package.availability_state],
        -score if score is not None else float("inf"),
        candidate.package.package_id,
    )


def _work_item_key(item: NormalizedWorkItem) -> tuple:
    return (
        item.due_date.isoformat() if item.due_date else "9999-12-31",
        -int(item.priority),
        item.created_at.isoformat() if item.created_at else "9999",
        item.provider,
        item.provider_record_id,
    )


def _package_evidence(
    items: list[NormalizedWorkItem],
    evidence: tuple[EvaluatedDependencyEvidence, ...],
) -> tuple[EvaluatedDependencyEvidence, ...]:
    identities = {(item.provider, item.provider_record_id) for item in items}
    return tuple(
        relationship
        for relationship in evidence
        if (
            relationship.blocked_work.provider,
            relationship.blocked_work.provider_record_id,
        )
        in identities
    )


def _item_evidence(
    item: NormalizedWorkItem,
    evidence: tuple[EvaluatedDependencyEvidence, ...],
) -> tuple[EvaluatedDependencyEvidence, ...]:
    return tuple(
        relationship
        for relationship in evidence
        if relationship.blocked_work.provider == item.provider
        and relationship.blocked_work.provider_record_id == item.provider_record_id
    )


project_work_package_service = ProjectWorkPackageService()
