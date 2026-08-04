from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .activity_domain import (
    ActivityFreshness,
    MeaningfulActivityCategory,
    activity_event_from_record,
)
from .dependency_evaluator import DependencyEvaluationState, EvaluatedDependencyEvidence
from .work_domain import NormalizedWorkItem, WorkEffortSize, WorkStatus


class ProjectFocusState(StrEnum):
    ACTIVE_MOMENTUM = "active_momentum"
    WAITING_EXTERNAL = "waiting_external"
    INTENTIONALLY_PAUSED = "intentionally_paused"
    DEDICATED_SESSION_NEEDED = "dedicated_session_needed"
    QUIET_POSSIBLE_DRIFT = "quiet_possible_drift"
    RECENTLY_COMPLETED = "recently_completed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ProjectFocusConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProviderCoverageState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    NOT_APPLICABLE = "not_applicable"
    MISSING_HISTORY = "missing_history"
    UNKNOWN = "unknown"


class ProviderCoverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_reference: str | None = None
    state: ProviderCoverageState
    observed_at: datetime
    historical_coverage_start: datetime | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> "ProviderCoverage":
        _require_aware(self.observed_at, "observed_at")
        if self.historical_coverage_start is not None:
            _require_aware(self.historical_coverage_start, "historical_coverage_start")
        return self

    @property
    def has_reliable_history(self) -> bool:
        return (
            self.state == ProviderCoverageState.FRESH
            and self.historical_coverage_start is not None
        )


class ExplicitProjectIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(..., min_length=1, max_length=128)
    canonical_project_id: str = Field(..., min_length=1, max_length=128)
    confirmed_state: ProjectFocusState
    reason: str | None = Field(default=None, max_length=2000)
    confirmed_at: datetime
    expires_at: datetime | None = None
    review_after: datetime | None = None
    review_trigger: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_review_semantics(self) -> "ExplicitProjectIntent":
        _require_aware(self.confirmed_at, "confirmed_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        if self.review_after is not None:
            _require_aware(self.review_after, "review_after")
        if (
            self.confirmed_state == ProjectFocusState.INTENTIONALLY_PAUSED
            and self.expires_at is None
            and self.review_after is None
        ):
            raise ValueError("an explicit pause requires expiry or review semantics")
        return self

    def is_active(self, now: datetime) -> bool:
        return self.expires_at is None or self.expires_at > now

    def review_due(self, now: datetime) -> bool:
        return self.review_after is not None and self.review_after <= now


class ProjectFocusEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_key: str
    category: str
    canonical_project_id: str
    source_kind: str
    provider: str
    provider_record_type: str | None = None
    provider_record_id: str | None = None
    source_timestamp: datetime | None = None
    observed_at: datetime
    freshness: ActivityFreshness
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_timestamps(self) -> "ProjectFocusEvidence":
        _require_aware(self.observed_at, "observed_at")
        if self.source_timestamp is not None:
            _require_aware(self.source_timestamp, "source_timestamp")
        return self


class ProjectActivityWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    days: int
    starts_at: datetime
    ends_at: datetime
    evidence_count: int
    categories: tuple[str, ...] = ()


class ProjectActivityFocus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_project_id: str
    canonical_project_key: str
    evaluated_at: datetime
    primary_state: ProjectFocusState
    supporting_states: tuple[ProjectFocusState, ...] = ()
    conflicting_states: tuple[ProjectFocusState, ...] = ()
    evidence: tuple[ProjectFocusEvidence, ...] = ()
    evidence_total_count: int = 0
    evidence_returned_count: int = 0
    evidence_limit: int = 12
    evaluated_windows: tuple[ProjectActivityWindow, ...]
    confidence: ProjectFocusConfidence
    freshness: ActivityFreshness
    provider_coverage: tuple[ProviderCoverage, ...] = ()
    explicit_intent: ExplicitProjectIntent | None = None
    explicitly_confirmed: bool = False
    inferred: bool = True
    user_confirmation_recommended: bool = False
    confirmation_question: str | None = None
    confirmation_reason: str | None = None


class ProjectActivityFocusService:
    def evaluate(
        self,
        *,
        canonical_project_id: str,
        canonical_project_key: str,
        work_items: Iterable[NormalizedWorkItem],
        activity_records: Iterable[dict[str, Any]],
        dependency_evidence: Iterable[EvaluatedDependencyEvidence],
        provider_coverage: Iterable[ProviderCoverage],
        evaluated_at: datetime,
        explicit_intent: ExplicitProjectIntent | None = None,
        next_step: NormalizedWorkItem | None = None,
        evidence_limit: int = 12,
    ) -> ProjectActivityFocus:
        _require_aware(evaluated_at, "evaluated_at")
        coverage = tuple(provider_coverage)
        evidence = _dedupe_evidence(
            [
                *_work_evidence(canonical_project_id, work_items, evaluated_at),
                *_activity_evidence(canonical_project_id, activity_records),
                *_dependency_focus_evidence(
                    canonical_project_id,
                    dependency_evidence,
                    evaluated_at,
                ),
                *_next_step_evidence(canonical_project_id, next_step, evaluated_at),
            ]
        )
        windows = tuple(
            _window(days, evidence, evaluated_at) for days in (7, 14, 30)
        )
        freshness = _overall_freshness(coverage, evidence)
        signals = _signals(evidence, evaluated_at)
        primary, supporting, conflicts, explicit = _interpret(
            signals=signals,
            evidence=evidence,
            coverage=coverage,
            freshness=freshness,
            explicit_intent=explicit_intent,
            evaluated_at=evaluated_at,
        )
        confirmation, question, reason = _confirmation(
            primary=primary,
            conflicts=conflicts,
            freshness=freshness,
            explicit_intent=explicit_intent,
            evaluated_at=evaluated_at,
        )
        ordered = sorted(evidence, key=_evidence_order_key)
        bounded = tuple(ordered[: max(0, evidence_limit)])
        confidence = _confidence(primary, freshness, explicit)
        return ProjectActivityFocus(
            canonical_project_id=canonical_project_id,
            canonical_project_key=canonical_project_key,
            evaluated_at=evaluated_at,
            primary_state=primary,
            supporting_states=tuple(supporting),
            conflicting_states=tuple(conflicts),
            evidence=bounded,
            evidence_total_count=len(ordered),
            evidence_returned_count=len(bounded),
            evidence_limit=max(0, evidence_limit),
            evaluated_windows=windows,
            confidence=confidence,
            freshness=freshness,
            provider_coverage=coverage,
            explicit_intent=explicit_intent,
            explicitly_confirmed=explicit,
            inferred=not explicit,
            user_confirmation_recommended=confirmation,
            confirmation_question=question,
            confirmation_reason=reason,
        )


project_activity_focus_service = ProjectActivityFocusService()


def _work_evidence(
    canonical_project_id: str,
    work_items: Iterable[NormalizedWorkItem],
    observed_at: datetime,
) -> list[ProjectFocusEvidence]:
    evidence: list[ProjectFocusEvidence] = []
    for item in work_items:
        if item.canonical_project_id != canonical_project_id:
            continue
        provider_identifier = item.provider_metadata.get("issue_identifier")
        if item.status == WorkStatus.COMPLETED:
            category = MeaningfulActivityCategory.WORK_COMPLETED.value
            timestamp = _metadata_datetime(item.provider_metadata, "completed_at") or item.updated_at
            summary = f"Completed {provider_identifier or item.title}"
        elif item.status == WorkStatus.OPEN and item.updated_at is not None:
            workflow = item.provider_metadata.get("workflow_state")
            workflow_type = (
                str(workflow.get("type") or "").lower()
                if isinstance(workflow, dict)
                else ""
            )
            category = (
                MeaningfulActivityCategory.WORK_STARTED.value
                if workflow_type == "started"
                else MeaningfulActivityCategory.WORK_UPDATED.value
            )
            timestamp = item.updated_at
            summary = f"Updated {provider_identifier or item.title}"
        else:
            continue
        evidence.append(
            ProjectFocusEvidence(
                evidence_key=f"work:{item.provider}:{item.provider_record_id}:{category}:{_timestamp_key(timestamp)}",
                category=category,
                canonical_project_id=canonical_project_id,
                source_kind="normalized_work",
                provider=item.provider,
                provider_record_type="work_item",
                provider_record_id=item.provider_record_id,
                source_timestamp=timestamp,
                observed_at=observed_at,
                freshness=(
                    ActivityFreshness.UNKNOWN
                    if timestamp is not None and timestamp > observed_at
                    else ActivityFreshness.FRESH
                ),
                summary=summary,
                metadata={
                    "provider_identifier": provider_identifier,
                    "provider_url": item.provider_url,
                    "status": item.status.value,
                },
            )
        )
    return evidence


def _activity_evidence(
    canonical_project_id: str,
    activity_records: Iterable[dict[str, Any]],
) -> list[ProjectFocusEvidence]:
    evidence: list[ProjectFocusEvidence] = []
    for record in activity_records:
        event = activity_event_from_record(record)
        if event is None or event.canonical_project_id != canonical_project_id:
            continue
        evidence.append(
            ProjectFocusEvidence(
                evidence_key=event.evidence_key,
                category=event.category.value,
                canonical_project_id=canonical_project_id,
                source_kind="activity",
                provider=event.source_provider,
                provider_record_type=event.provider_record_type,
                provider_record_id=event.provider_record_id,
                source_timestamp=event.source_timestamp,
                observed_at=event.observed_at,
                freshness=(
                    ActivityFreshness.UNKNOWN
                    if event.source_timestamp > event.observed_at
                    else event.freshness
                ),
                summary=event.summary,
                metadata={
                    **event.attributable_payload,
                    **(
                        {"future_source_timestamp": True}
                        if event.source_timestamp > event.observed_at
                        else {}
                    ),
                },
            )
        )
    return evidence


def _dependency_focus_evidence(
    canonical_project_id: str,
    relationships: Iterable[EvaluatedDependencyEvidence],
    observed_at: datetime,
) -> list[ProjectFocusEvidence]:
    evidence: list[ProjectFocusEvidence] = []
    for relationship in relationships:
        if relationship.canonical_project_id != canonical_project_id:
            continue
        if relationship.evaluation_state not in {
            DependencyEvaluationState.ACTIVE,
            DependencyEvaluationState.NEEDS_REVIEW,
        }:
            continue
        evidence.append(
            ProjectFocusEvidence(
                evidence_key=(
                    f"dependency:{relationship.relationship_provider}:"
                    f"{relationship.relationship_id or relationship.blocked_work.provider_record_id}:"
                    f"{relationship.blocking_work.provider_record_id}:"
                    f"{relationship.evaluation_state.value}"
                ),
                category=(
                    "waiting_external"
                    if relationship.evaluation_state == DependencyEvaluationState.ACTIVE
                    else "blocker_needs_review"
                ),
                canonical_project_id=canonical_project_id,
                source_kind="dependency",
                provider=relationship.relationship_provider,
                provider_record_type="dependency",
                provider_record_id=relationship.relationship_id,
                source_timestamp=None,
                observed_at=observed_at,
                freshness=ActivityFreshness.FRESH,
                summary=relationship.explanation,
                metadata={
                    "blocked_work_id": relationship.blocked_work.provider_record_id,
                    "blocking_work_id": relationship.blocking_work.provider_record_id,
                    "evaluation_state": relationship.evaluation_state.value,
                },
            )
        )
    return evidence


def _next_step_evidence(
    canonical_project_id: str,
    next_step: NormalizedWorkItem | None,
    observed_at: datetime,
) -> list[ProjectFocusEvidence]:
    if next_step is None or next_step.canonical_project_id != canonical_project_id:
        return []
    contexts = tuple(next_step.context_requirements)
    large = next_step.effort_size == WorkEffortSize.LARGE
    if not contexts and not large:
        return []
    return [
        ProjectFocusEvidence(
            evidence_key=f"next-step:{next_step.provider}:{next_step.provider_record_id}",
            category="dedicated_session_needed",
            canonical_project_id=canonical_project_id,
            source_kind="normalized_work",
            provider=next_step.provider,
            provider_record_type="work_item",
            provider_record_id=next_step.provider_record_id,
            source_timestamp=next_step.updated_at or next_step.created_at,
            observed_at=observed_at,
            freshness=ActivityFreshness.FRESH,
            summary=f"Next step requires {', '.join(contexts) if contexts else 'a substantial work session'}",
            metadata={
                "context_requirements": list(contexts),
                "effort_size": next_step.effort_size.value if next_step.effort_size else None,
                "provider_url": next_step.provider_url,
            },
        )
    ]


def _signals(
    evidence: list[ProjectFocusEvidence],
    now: datetime,
) -> set[ProjectFocusState]:
    recent_7 = [item for item in evidence if _within_days(item, now, 7)]
    recent_categories = {item.category for item in recent_7}
    signals: set[ProjectFocusState] = set()
    if {
        MeaningfulActivityCategory.WORK_STARTED.value,
        MeaningfulActivityCategory.WORK_UPDATED.value,
        MeaningfulActivityCategory.MILESTONE_PROGRESS.value,
        MeaningfulActivityCategory.PROJECT_RESUMED.value,
        MeaningfulActivityCategory.REPOSITORY_CATCH_UP.value,
    } & recent_categories:
        signals.add(ProjectFocusState.ACTIVE_MOMENTUM)
    if {
        MeaningfulActivityCategory.WORK_COMPLETED.value,
        MeaningfulActivityCategory.MILESTONE_COMPLETED.value,
    } & recent_categories:
        signals.add(ProjectFocusState.RECENTLY_COMPLETED)
    if _has_current_waiting_signal(evidence, now):
        signals.add(ProjectFocusState.WAITING_EXTERNAL)
    if any(item.category == "dedicated_session_needed" for item in evidence):
        signals.add(ProjectFocusState.DEDICATED_SESSION_NEEDED)
    return signals


def _interpret(
    *,
    signals: set[ProjectFocusState],
    evidence: list[ProjectFocusEvidence],
    coverage: tuple[ProviderCoverage, ...],
    freshness: ActivityFreshness,
    explicit_intent: ExplicitProjectIntent | None,
    evaluated_at: datetime,
) -> tuple[ProjectFocusState, list[ProjectFocusState], list[ProjectFocusState], bool]:
    if explicit_intent is not None and explicit_intent.is_active(evaluated_at):
        new_signals = _signals(
            [
                item
                for item in evidence
                if _source_time(item) is not None
                and _source_time(item) >= explicit_intent.confirmed_at
            ],
            evaluated_at,
        )
        conflicts = sorted(
            (
                signal
                for signal in new_signals
                if signal != explicit_intent.confirmed_state
            ),
            key=lambda item: item.value,
        )
        return (
            explicit_intent.confirmed_state,
            [],
            conflicts,
            True,
        )

    if (
        ProjectFocusState.WAITING_EXTERNAL in signals
        and not _category_has_usable_current_coverage(
            {
                MeaningfulActivityCategory.BLOCKER_ADDED.value,
                MeaningfulActivityCategory.BLOCKER_CHANGED.value,
                MeaningfulActivityCategory.WAITING_EXTERNAL.value,
            },
            evidence,
            coverage,
        )
    ):
        return (
            ProjectFocusState.INSUFFICIENT_EVIDENCE,
            [ProjectFocusState.WAITING_EXTERNAL],
            [],
            False,
        )

    precedence = (
        ProjectFocusState.ACTIVE_MOMENTUM,
        ProjectFocusState.WAITING_EXTERNAL,
        ProjectFocusState.DEDICATED_SESSION_NEEDED,
        ProjectFocusState.RECENTLY_COMPLETED,
    )
    primary = next((state for state in precedence if state in signals), None)
    if primary is not None:
        supporting = [state for state in precedence if state in signals and state != primary]
        if (
            primary == ProjectFocusState.DEDICATED_SESSION_NEEDED
            and _has_reliable_30_day_coverage(coverage, evaluated_at)
            and not any(
                _within_days(item, evaluated_at, 30)
                for item in evidence
                if item.category != "dedicated_session_needed"
            )
        ):
            supporting.append(ProjectFocusState.QUIET_POSSIBLE_DRIFT)
        conflicts: list[ProjectFocusState] = []
        return primary, _unique_states(supporting), conflicts, False

    reliable_history = _has_reliable_30_day_coverage(coverage, evaluated_at)
    has_recent_30 = any(_within_days(item, evaluated_at, 30) for item in evidence)
    has_older_history = any(
        _source_time(item) is not None and _source_time(item) < evaluated_at - timedelta(days=30)
        for item in evidence
    )
    if reliable_history and not has_recent_30 and has_older_history:
        return ProjectFocusState.QUIET_POSSIBLE_DRIFT, [], [], False
    return ProjectFocusState.INSUFFICIENT_EVIDENCE, [], [], False


def _confirmation(
    *,
    primary: ProjectFocusState,
    conflicts: list[ProjectFocusState],
    freshness: ActivityFreshness,
    explicit_intent: ExplicitProjectIntent | None,
    evaluated_at: datetime,
) -> tuple[bool, str | None, str | None]:
    review_due = explicit_intent is not None and explicit_intent.review_due(evaluated_at)
    expired = explicit_intent is not None and not explicit_intent.is_active(evaluated_at)
    needed = bool(conflicts) or review_due or expired or primary in {
        ProjectFocusState.QUIET_POSSIBLE_DRIFT,
        ProjectFocusState.DEDICATED_SESSION_NEEDED,
        ProjectFocusState.INSUFFICIENT_EVIDENCE,
    } or freshness != ActivityFreshness.FRESH
    if not needed:
        return False, None, None
    if conflicts:
        return True, "Has this project's confirmed focus changed?", "Strong new evidence conflicts with reviewed intent."
    if review_due or expired:
        return True, "Should this reviewed project state be renewed or changed?", "The explicit intent reached its review or expiry boundary."
    if freshness != ActivityFreshness.FRESH:
        return True, "Can you confirm the project's current state?", "Provider coverage is stale, unavailable, or historically incomplete."
    if primary == ProjectFocusState.QUIET_POSSIBLE_DRIFT:
        return True, "Is this project intentionally quiet, waiting, or ready for renewed focus?", "Reliable coverage is quiet, but inactivity alone cannot explain intent."
    if primary == ProjectFocusState.DEDICATED_SESSION_NEEDED:
        return True, "Is a dedicated session still the right next step?", "The next step has structured size or environment requirements but intent is not confirmed."
    return True, "What is the project's current operating state?", "Available evidence is not sufficient for a stronger conclusion."


def _window(
    days: int,
    evidence: list[ProjectFocusEvidence],
    now: datetime,
) -> ProjectActivityWindow:
    matching = [item for item in evidence if _within_days(item, now, days)]
    return ProjectActivityWindow(
        days=days,
        starts_at=now - timedelta(days=days),
        ends_at=now,
        evidence_count=len(matching),
        categories=tuple(sorted({item.category for item in matching})),
    )


def _within_days(item: ProjectFocusEvidence, now: datetime, days: int) -> bool:
    timestamp = _source_time(item)
    return bool(timestamp is not None and now - timedelta(days=days) <= timestamp <= now)


def _source_time(item: ProjectFocusEvidence) -> datetime | None:
    value = item.source_timestamp or item.observed_at
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value


def _dedupe_evidence(items: list[ProjectFocusEvidence]) -> list[ProjectFocusEvidence]:
    deduped: dict[tuple[str, ...], ProjectFocusEvidence] = {}
    for item in items:
        identity = (
            item.category,
            item.provider,
            item.provider_record_id or "",
            _timestamp_key(item.source_timestamp),
        )
        if not item.provider_record_id:
            identity = (*identity, item.evidence_key)
        existing = deduped.get(identity)
        if existing is None or _evidence_order_key(item) < _evidence_order_key(existing):
            deduped[identity] = item
    return list(deduped.values())


def _evidence_order_key(item: ProjectFocusEvidence) -> tuple[Any, ...]:
    timestamp = _source_time(item)
    epoch = timestamp.timestamp() if timestamp is not None else float("-inf")
    return (-epoch, item.category, item.provider, item.provider_record_id or "", item.evidence_key)


def _overall_freshness(
    coverage: tuple[ProviderCoverage, ...],
    evidence: list[ProjectFocusEvidence],
) -> ActivityFreshness:
    applicable = [item for item in coverage if item.state != ProviderCoverageState.NOT_APPLICABLE]
    if any(item.state == ProviderCoverageState.UNAVAILABLE for item in applicable):
        return ActivityFreshness.UNAVAILABLE
    if any(item.state == ProviderCoverageState.STALE for item in applicable):
        return ActivityFreshness.STALE
    if any(
        item.state in {
            ProviderCoverageState.NOT_CONFIGURED,
            ProviderCoverageState.MISSING_HISTORY,
            ProviderCoverageState.UNKNOWN,
        }
        for item in applicable
    ):
        return ActivityFreshness.UNKNOWN
    if applicable and all(item.state == ProviderCoverageState.FRESH for item in applicable):
        return ActivityFreshness.FRESH
    if evidence and all(item.freshness == ActivityFreshness.FRESH for item in evidence):
        return ActivityFreshness.FRESH
    return ActivityFreshness.UNKNOWN


def _category_has_usable_current_coverage(
    categories: set[str],
    evidence: list[ProjectFocusEvidence],
    coverage: tuple[ProviderCoverage, ...],
) -> bool:
    coverage_by_provider = {item.provider: item.state for item in coverage}
    return any(
        item.category in categories
        and item.freshness == ActivityFreshness.FRESH
        and (
            item.source_kind == "activity"
            or coverage_by_provider.get(item.provider)
            in {ProviderCoverageState.FRESH, ProviderCoverageState.MISSING_HISTORY}
        )
        for item in evidence
    )


def _has_current_waiting_signal(
    evidence: list[ProjectFocusEvidence],
    now: datetime,
) -> bool:
    waiting_categories = {
        MeaningfulActivityCategory.BLOCKER_ADDED.value,
        MeaningfulActivityCategory.BLOCKER_CHANGED.value,
        MeaningfulActivityCategory.WAITING_EXTERNAL.value,
    }
    state_categories = {
        *waiting_categories,
        MeaningfulActivityCategory.BLOCKER_REMOVED.value,
    }
    current_dependencies = any(
        item.source_kind == "dependency"
        and item.category == MeaningfulActivityCategory.WAITING_EXTERNAL.value
        for item in evidence
    )
    if current_dependencies:
        return True

    latest_by_record: dict[tuple[str, str], ProjectFocusEvidence] = {}
    for item in evidence:
        if (
            item.source_kind != "activity"
            or item.category not in state_categories
            or not item.provider_record_id
            or not _within_days(item, now, 30)
        ):
            continue
        identity = (item.provider, item.provider_record_id)
        existing = latest_by_record.get(identity)
        if existing is None or _evidence_order_key(item) < _evidence_order_key(existing):
            latest_by_record[identity] = item
    return any(item.category in waiting_categories for item in latest_by_record.values())


def _has_reliable_30_day_coverage(
    coverage: tuple[ProviderCoverage, ...],
    evaluated_at: datetime,
) -> bool:
    return bool(coverage) and all(
        item.state == ProviderCoverageState.NOT_APPLICABLE or item.has_reliable_history
        for item in coverage
    ) and any(
        item.has_reliable_history
        and item.historical_coverage_start <= evaluated_at - timedelta(days=30)
        for item in coverage
    )


def _confidence(
    primary: ProjectFocusState,
    freshness: ActivityFreshness,
    explicit: bool,
) -> ProjectFocusConfidence:
    if explicit:
        return ProjectFocusConfidence.HIGH
    if freshness == ActivityFreshness.FRESH and primary != ProjectFocusState.INSUFFICIENT_EVIDENCE:
        return ProjectFocusConfidence.MEDIUM
    return ProjectFocusConfidence.LOW


def _metadata_datetime(metadata: dict[str, Any], key: str) -> datetime | None:
    value = metadata.get(key)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None and value.utcoffset() is not None else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _timestamp_key(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "unknown"


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _unique_states(states: list[ProjectFocusState]) -> list[ProjectFocusState]:
    return list(dict.fromkeys(states))
