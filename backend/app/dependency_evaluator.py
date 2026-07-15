from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .project_registry import ProjectRegistrySnapshot
from .work_domain import NormalizedWorkItem, WorkDependency, WorkStatus


class DependencyEvaluationState(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    NEEDS_REVIEW = "needs_review"


class DependencyWorkEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_record_id: str
    provider_identifier: str | None = None
    title: str | None = None
    status: WorkStatus | None = None
    provider_status: str | None = None
    provider_url: str | None = None
    canonical_project_id: str | None = None
    provider_project_id: str | None = None


class EvaluatedDependencyEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_provider: str
    relationship_id: str | None = None
    dependency_type: Literal["blocked_by"] = "blocked_by"
    canonical_project_id: str | None = None
    blocked_work: DependencyWorkEvidence
    blocking_work: DependencyWorkEvidence
    evaluation_state: DependencyEvaluationState
    explanation: str


class DependencySummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    active_dependency_count: int = 0
    active_blocked_work_count: int = 0
    needs_review_dependency_count: int = 0
    needs_review_blocked_work_count: int = 0
    resolved_dependency_count: int = 0


@dataclass(frozen=True)
class DependencyEvaluationResult:
    work_items: tuple[NormalizedWorkItem, ...]
    evidence: tuple[EvaluatedDependencyEvidence, ...]


class DependencyEvaluator:
    def evaluate(
        self,
        work_items: list[NormalizedWorkItem],
        *,
        registry: ProjectRegistrySnapshot | None = None,
    ) -> DependencyEvaluationResult:
        lookup = {
            (item.provider, item.provider_record_id): item for item in work_items
        }
        evidence: list[EvaluatedDependencyEvidence] = []
        evaluated_items: list[NormalizedWorkItem] = []

        for item in work_items:
            item_evidence = _dedupe_evidence([
                self._evaluate_dependency(
                    item,
                    dependency,
                    lookup=lookup,
                    registry=registry,
                )
                for dependency in item.dependencies
                if dependency.dependency_type == "blocked_by"
            ])
            evidence.extend(item_evidence)
            prevents_execution = any(
                relationship.evaluation_state
                in {
                    DependencyEvaluationState.ACTIVE,
                    DependencyEvaluationState.NEEDS_REVIEW,
                }
                for relationship in item_evidence
            )
            is_blocked = item.status == WorkStatus.OPEN and prevents_execution
            evaluated_items.append(
                item.model_copy(
                    update={
                        "is_blocked": is_blocked,
                        "is_executable": (
                            item.status == WorkStatus.OPEN
                            and not item.is_container
                            and not prevents_execution
                        ),
                    }
                )
            )

        evidence = _dedupe_evidence(evidence)
        evidence.sort(key=_evidence_sort_key)
        return DependencyEvaluationResult(
            work_items=tuple(evaluated_items),
            evidence=tuple(evidence),
        )

    def _evaluate_dependency(
        self,
        blocked_item: NormalizedWorkItem,
        dependency: WorkDependency,
        *,
        lookup: dict[tuple[str, str], NormalizedWorkItem],
        registry: ProjectRegistrySnapshot | None,
    ) -> EvaluatedDependencyEvidence:
        relation = _find_inverse_relation(blocked_item, dependency)
        blocking_item = lookup.get(
            (dependency.provider, dependency.provider_record_id)
        )
        blocking_work = _blocking_work_evidence(
            dependency,
            blocking_item=blocking_item,
            relation=relation,
            registry=registry,
        )
        state = _evaluation_state(blocking_work.status)
        blocked_work = _work_evidence(blocked_item)
        return EvaluatedDependencyEvidence(
            relationship_provider=blocked_item.provider,
            relationship_id=(
                str(relation["id"])
                if isinstance(relation, dict) and relation.get("id")
                else None
            ),
            canonical_project_id=blocked_item.canonical_project_id,
            blocked_work=blocked_work,
            blocking_work=blocking_work,
            evaluation_state=state,
            explanation=_explanation(
                blocked_work=blocked_work,
                blocking_work=blocking_work,
                state=state,
            ),
        )


def _blocking_work_evidence(
    dependency: WorkDependency,
    *,
    blocking_item: NormalizedWorkItem | None,
    relation: dict[str, Any] | None,
    registry: ProjectRegistrySnapshot | None,
) -> DependencyWorkEvidence:
    if blocking_item is not None:
        return _work_evidence(blocking_item)

    source = relation.get("issue") if isinstance(relation, dict) else None
    if not isinstance(source, dict):
        source = {}
    project = source.get("project") if isinstance(source.get("project"), dict) else None
    provider_project_id = (
        str(project["id"]) if project and project.get("id") else None
    )
    canonical_project_id = (
        registry.resolve_provider_project_id(
            provider=dependency.provider,
            resource_type="project",
            provider_ref=provider_project_id,
        )
        if registry is not None and provider_project_id
        else None
    )
    state = source.get("state") if isinstance(source.get("state"), dict) else None
    return DependencyWorkEvidence(
        provider=dependency.provider,
        provider_record_id=dependency.provider_record_id,
        provider_identifier=_optional_string(source.get("identifier")),
        title=_optional_string(source.get("title")),
        status=_structured_linear_status(state),
        provider_status=(
            _optional_string(state.get("name")) if state is not None else None
        ),
        provider_url=_optional_string(source.get("url")),
        canonical_project_id=canonical_project_id,
        provider_project_id=provider_project_id,
    )


def _work_evidence(item: NormalizedWorkItem) -> DependencyWorkEvidence:
    return DependencyWorkEvidence(
        provider=item.provider,
        provider_record_id=item.provider_record_id,
        provider_identifier=_provider_identifier(item),
        title=item.title,
        status=item.status,
        provider_status=item.original_provider_status,
        provider_url=item.provider_url,
        canonical_project_id=item.canonical_project_id,
        provider_project_id=_optional_string(
            item.provider_metadata.get("provider_project_id")
        ),
    )


def _find_inverse_relation(
    item: NormalizedWorkItem,
    dependency: WorkDependency,
) -> dict[str, Any] | None:
    relations = item.provider_metadata.get("inverse_relations")
    if not isinstance(relations, list):
        return None
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        source = relation.get("issue")
        if (
            str(relation.get("type") or "").lower() == "blocks"
            and isinstance(source, dict)
            and str(source.get("id") or "") == dependency.provider_record_id
        ):
            return relation
    return None


def _structured_linear_status(state: dict[str, Any] | None) -> WorkStatus | None:
    if state is None:
        return None
    state_type = str(state.get("type") or "").strip().lower()
    if state_type == "completed":
        return WorkStatus.COMPLETED
    if state_type in {"canceled", "cancelled"}:
        return WorkStatus.CANCELED
    if state_type in {"backlog", "unstarted", "started", "triage"}:
        return WorkStatus.OPEN
    return None


def _evaluation_state(status: WorkStatus | None) -> DependencyEvaluationState:
    if status == WorkStatus.OPEN:
        return DependencyEvaluationState.ACTIVE
    if status == WorkStatus.COMPLETED:
        return DependencyEvaluationState.RESOLVED
    return DependencyEvaluationState.NEEDS_REVIEW


def _explanation(
    *,
    blocked_work: DependencyWorkEvidence,
    blocking_work: DependencyWorkEvidence,
    state: DependencyEvaluationState,
) -> str:
    blocked = _evidence_label(blocked_work)
    blocker = _evidence_label(blocking_work)
    if state == DependencyEvaluationState.ACTIVE:
        return f"{blocked} is blocked by open {blocker}."
    if state == DependencyEvaluationState.RESOLVED:
        return f"{blocker} is completed, so it no longer blocks {blocked}."
    if blocking_work.status == WorkStatus.CANCELED:
        return f"{blocker} was canceled; review whether {blocked} can proceed."
    return f"The blocker for {blocked} could not be evaluated; review the dependency."


def _provider_identifier(item: NormalizedWorkItem) -> str | None:
    return _optional_string(item.provider_metadata.get("issue_identifier"))


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    parsed = str(value).strip()
    return parsed or None


def _evidence_label(work: DependencyWorkEvidence) -> str:
    return work.provider_identifier or work.title or work.provider_record_id


def _evidence_sort_key(evidence: EvaluatedDependencyEvidence) -> tuple[str, ...]:
    return (
        evidence.blocked_work.provider,
        evidence.blocked_work.provider_record_id,
        evidence.blocking_work.provider,
        evidence.blocking_work.provider_record_id,
    )


def summarize_dependency_evidence(
    evidence: tuple[EvaluatedDependencyEvidence, ...],
    *,
    canonical_project_id: str | None = None,
) -> DependencySummary:
    scoped = _dedupe_evidence(
        [
            relationship
            for relationship in evidence
            if canonical_project_id is None
            or relationship.canonical_project_id == canonical_project_id
        ]
    )
    active = [
        relationship
        for relationship in scoped
        if relationship.evaluation_state == DependencyEvaluationState.ACTIVE
        and relationship.blocked_work.status == WorkStatus.OPEN
    ]
    needs_review = [
        relationship
        for relationship in scoped
        if relationship.evaluation_state == DependencyEvaluationState.NEEDS_REVIEW
        and relationship.blocked_work.status == WorkStatus.OPEN
    ]
    return DependencySummary(
        active_dependency_count=len(active),
        active_blocked_work_count=len({_blocked_work_identity(item) for item in active}),
        needs_review_dependency_count=len(needs_review),
        needs_review_blocked_work_count=len(
            {_blocked_work_identity(item) for item in needs_review}
        ),
        resolved_dependency_count=sum(
            relationship.evaluation_state == DependencyEvaluationState.RESOLVED
            for relationship in scoped
        ),
    )


def _dedupe_evidence(
    evidence: list[EvaluatedDependencyEvidence],
) -> list[EvaluatedDependencyEvidence]:
    deduped: dict[tuple[str, ...], EvaluatedDependencyEvidence] = {}
    for relationship in evidence:
        deduped.setdefault(_dependency_edge_identity(relationship), relationship)
    return list(deduped.values())


def _dependency_edge_identity(
    evidence: EvaluatedDependencyEvidence,
) -> tuple[str, ...]:
    return (
        evidence.relationship_provider,
        evidence.dependency_type,
        evidence.blocked_work.provider,
        evidence.blocked_work.provider_record_id,
        evidence.blocking_work.provider,
        evidence.blocking_work.provider_record_id,
    )


def _blocked_work_identity(
    evidence: EvaluatedDependencyEvidence,
) -> tuple[str, str]:
    return (
        evidence.blocked_work.provider,
        evidence.blocked_work.provider_record_id,
    )


dependency_evaluator = DependencyEvaluator()
