from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .activity_domain import ActivityFreshness
from .calendar_time import (
    CalendarTimeState,
    event_end,
    event_start,
    normalize_calendar_time,
)
from .calendar_tools import CalendarReadResult, list_remaining_today_events
from .project_activity_focus import (
    ProjectActivityFocus,
    ProjectFocusState,
    ProviderCoverageState,
)
from .project_brain import ProjectBrainProjectSnapshot, project_brain_service
from .provider_changes import (
    ChangeCategory,
    ChangeComparisonState,
    ChangeCoverage,
    ConsumerChangeCheckpoint,
    ProviderChangeEvent,
    provider_change_service,
)
from .reality_reconciliation import (
    ProviderRecordIdentity,
    RealityAvailability,
    RealityClassification,
    RealityConfidence,
    RealityEvidence,
    RealityEvidenceType,
    RealityFreshness,
    RealityItem,
    SafeResolution,
    TemporalActionability,
    WorkIdentity,
)


MORNING_STATE_SCHEMA_VERSION = 1
MORNING_CHANGE_FALLBACK_DAYS = 30
DEFAULT_SECTION_LIMIT = 12
FUTURE_CHECKPOINT_TOLERANCE = timedelta(minutes=5)


class MorningSectionId(StrEnum):
    CHANGES_SINCE_CHECK = "changes_since_meaningful_check"
    ATTENTION_TODAY = "attention_today"
    HANDLED_PAUSED_WAITING = "handled_paused_waiting"
    PROJECT_MOMENTUM_CONSTRAINTS = "project_momentum_constraints"
    REALISTIC_DAY_SHAPE = "realistic_day_shape"


class MorningFactType(StrEnum):
    EXPLICIT_FACT = "explicit_fact"
    DETERMINISTIC_CONCLUSION = "deterministic_conclusion"
    INFERENCE = "inference"


class MorningFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MIXED = "mixed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class MorningAvailability(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class MorningConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class MorningCheckpointMode(StrEnum):
    ACKNOWLEDGED_CHECKPOINT = "acknowledged_checkpoint"
    RETAINED_HISTORY_FALLBACK = "retained_history_fallback"
    MIXED = "mixed"


class MorningSuggestedAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(..., min_length=1, max_length=120)
    summary: str = Field(..., min_length=1, max_length=500)
    target_work_identity: WorkIdentity | None = None
    requires_user_confirmation: bool = True
    performs_provider_mutation: Literal[False] = False


class MorningStatement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = MORNING_STATE_SCHEMA_VERSION
    statement_id: str = Field(..., min_length=1, max_length=240)
    section: MorningSectionId
    classification: RealityClassification
    status: str = Field(..., min_length=1, max_length=120)
    summary: str = Field(..., min_length=1, max_length=500)
    reason: str = Field(..., min_length=1, max_length=1000)
    canonical_project_id: str | None = Field(default=None, max_length=128)
    canonical_project_key: str | None = Field(default=None, max_length=128)
    life_area_id: str | None = Field(default=None, max_length=128)
    linked_work_identity: WorkIdentity | None = None
    provider_identities: tuple[ProviderRecordIdentity, ...] = ()
    source_evidence_references: tuple[str, ...]
    source_evidence_summaries: tuple[str, ...] = ()
    source_timestamps: tuple[datetime, ...] = ()
    observed_at: datetime
    freshness: MorningFreshness
    availability: MorningAvailability
    fact_type: MorningFactType
    confidence: MorningConfidence
    uncertainty: tuple[str, ...] = ()
    temporal: TemporalActionability | None = None
    suggested_action: MorningSuggestedAction | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "MorningStatement":
        _require_aware(self.observed_at, "observed_at")
        for timestamp in self.source_timestamps:
            _require_aware(timestamp, "source_timestamps")
        if not self.source_evidence_references:
            raise ValueError("morning statements require attributable evidence references")
        return self


class MorningSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = MORNING_STATE_SCHEMA_VERSION
    section_id: MorningSectionId
    heading: str
    statements: tuple[MorningStatement, ...] = ()
    total_count: int = 0
    returned_count: int = 0
    item_limit: int = DEFAULT_SECTION_LIMIT
    truncated: bool = False

    @model_validator(mode="after")
    def validate_counts(self) -> "MorningSection":
        if self.returned_count != len(self.statements):
            raise ValueError("returned_count must match returned morning statements")
        if self.total_count < self.returned_count:
            raise ValueError("total_count cannot be smaller than returned_count")
        if self.truncated != (self.total_count > self.returned_count):
            raise ValueError("truncated must reflect the complete statement count")
        return self


class MorningCheckpointSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = MORNING_STATE_SCHEMA_VERSION
    consumer_id: str
    mode: MorningCheckpointMode
    selected_since: datetime
    fallback_days: Literal[30] = MORNING_CHANGE_FALLBACK_DAYS
    checkpoints: tuple[ConsumerChangeCheckpoint, ...] = ()
    fallback_scopes: tuple[str, ...] = ()
    coverage_complete: bool
    retained_boundaries: tuple[datetime, ...] = ()
    diagnostics: tuple[str, ...] = ()
    ordinary_read_acknowledges: Literal[False] = False

    @model_validator(mode="after")
    def validate_times(self) -> "MorningCheckpointSelection":
        _require_aware(self.selected_since, "selected_since")
        for timestamp in self.retained_boundaries:
            _require_aware(timestamp, "retained_boundaries")
        return self


class MorningChangeWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint: MorningCheckpointSelection
    changes: tuple[ProviderChangeEvent, ...] = ()
    coverage: tuple[ChangeCoverage, ...] = ()
    total_count: int = 0

    @model_validator(mode="after")
    def validate_count(self) -> "MorningChangeWindow":
        if self.total_count != len(self.changes):
            raise ValueError("change window total_count must describe the complete set")
        return self


class MorningStateSynthesis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = MORNING_STATE_SCHEMA_VERSION
    synthesis_id: str
    evaluated_at: datetime
    overall_classification: RealityClassification
    complete_evidence: bool
    no_urgent_attention: bool
    urgent_attention_count: int
    changes_since_meaningful_check: MorningSection
    attention_today: MorningSection
    handled_paused_waiting: MorningSection
    project_momentum_constraints: MorningSection
    realistic_day_shape: MorningSection
    checkpoint: MorningCheckpointSelection
    provider_diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_time(self) -> "MorningStateSynthesis":
        _require_aware(self.evaluated_at, "evaluated_at")
        return self


@dataclass(frozen=True)
class MorningProjectState:
    canonical_project_id: str
    canonical_project_key: str
    name: str
    focus: ProjectActivityFocus
    reality_items: tuple[RealityItem, ...]
    reality_complete: bool
    reality_total_count: int
    provider_diagnostics: tuple[str, ...]


class MorningStateService:
    def __init__(
        self,
        *,
        project_service=project_brain_service,
        change_service=provider_change_service,
        calendar_reader=list_remaining_today_events,
    ):
        self.project_service = project_service
        self.change_service = change_service
        self.calendar_reader = calendar_reader

    def build(
        self,
        *,
        settings: Any,
        current_time: datetime | None = None,
        consumer_id: str = "morning-state",
        section_limit: int = DEFAULT_SECTION_LIMIT,
    ) -> MorningStateSynthesis:
        evaluated_at = current_time or datetime.now(settings.local_tz)
        _require_aware(evaluated_at, "current_time")
        evaluated_at = evaluated_at.astimezone(settings.local_tz)
        snapshot = self.project_service.snapshot(
            settings=settings,
            current_time=evaluated_at,
        )
        calendar_result = self.calendar_reader(settings, now=evaluated_at)
        calendar_state = normalize_calendar_time(
            calendar_result.events,
            now=evaluated_at,
            local_tz=settings.local_tz,
        )
        projects = tuple(_project_state(item) for item in snapshot.projects)
        change_window = self._change_window(
            consumer_id=consumer_id,
            evaluated_at=evaluated_at,
        )
        return self.synthesize(
            projects=projects,
            change_window=change_window,
            calendar_state=calendar_state,
            calendar_result=calendar_result,
            evaluated_at=evaluated_at,
            section_limit=section_limit,
        )

    def synthesize(
        self,
        *,
        projects: Iterable[MorningProjectState],
        change_window: MorningChangeWindow,
        calendar_state: CalendarTimeState,
        calendar_result: CalendarReadResult,
        evaluated_at: datetime,
        section_limit: int = DEFAULT_SECTION_LIMIT,
    ) -> MorningStateSynthesis:
        _require_aware(evaluated_at, "evaluated_at")
        project_states = tuple(projects)
        project_by_id = {item.canonical_project_id: item for item in project_states}
        changes = _change_statements(
            change_window,
            project_by_id=project_by_id,
            evaluated_at=evaluated_at,
        )

        all_reality_items = tuple(
            item for project in project_states for item in project.reality_items
        )
        attention_items = tuple(
            item
            for item in all_reality_items
            if item.classification
            in {
                RealityClassification.NEEDS_ACTION,
                RealityClassification.POTENTIAL_MISMATCH,
            }
        )
        reality_complete = bool(project_states) and all(
            item.reality_complete for item in project_states
        )
        attention = tuple(
            _statement_from_reality(
                item,
                section=MorningSectionId.ATTENTION_TODAY,
                observed_at=evaluated_at,
            )
            for item in attention_items
        )
        if not attention:
            attention = (
                _empty_attention_statement(
                    projects=project_states,
                    complete=reality_complete,
                    evaluated_at=evaluated_at,
                ),
            )

        handled = [
            _statement_from_reality(
                item,
                section=MorningSectionId.HANDLED_PAUSED_WAITING,
                observed_at=evaluated_at,
            )
            for item in all_reality_items
            if item.classification
            in {
                RealityClassification.ALREADY_HANDLED,
                RealityClassification.WAITING,
                RealityClassification.UPCOMING_NOT_ACTIONABLE,
            }
        ]
        handled.extend(
            _pause_statement(project, evaluated_at)
            for project in project_states
            if project.focus.primary_state == ProjectFocusState.INTENTIONALLY_PAUSED
        )
        if not handled:
            handled.append(
                _empty_support_statement(project_states, reality_complete, evaluated_at)
            )

        momentum = tuple(
            _focus_statement(project, evaluated_at) for project in project_states
        ) or (
            _no_projects_statement(evaluated_at),
        )
        day_shape = _day_shape_statements(
            calendar_state,
            calendar_result=calendar_result,
            evaluated_at=evaluated_at,
        )

        urgent_count = len(attention_items)
        complete = (
            reality_complete
            and change_window.checkpoint.coverage_complete
            and calendar_result.error is None
        )
        if any(
            item.classification == RealityClassification.NEEDS_ACTION
            for item in attention_items
        ):
            overall = RealityClassification.NEEDS_ACTION
        elif attention_items:
            overall = RealityClassification.POTENTIAL_MISMATCH
        elif not complete:
            overall = RealityClassification.UNKNOWN
        else:
            overall = RealityClassification.NO_MEANINGFUL_CHANGE

        sections = (
            _bounded_section(
                MorningSectionId.CHANGES_SINCE_CHECK,
                "Changes since last meaningful check",
                changes,
                section_limit,
            ),
            _bounded_section(
                MorningSectionId.ATTENTION_TODAY,
                "Attention today",
                attention,
                section_limit,
            ),
            _bounded_section(
                MorningSectionId.HANDLED_PAUSED_WAITING,
                "Handled, paused, and waiting",
                tuple(handled),
                section_limit,
            ),
            _bounded_section(
                MorningSectionId.PROJECT_MOMENTUM_CONSTRAINTS,
                "Project momentum and constraints",
                momentum,
                section_limit,
            ),
            _bounded_section(
                MorningSectionId.REALISTIC_DAY_SHAPE,
                "Realistic day shape",
                day_shape,
                section_limit,
            ),
        )
        diagnostics = tuple(
            dict.fromkeys(
                [
                    *change_window.checkpoint.diagnostics,
                    *(item for project in project_states for item in project.provider_diagnostics),
                    *([calendar_result.error] if calendar_result.error else []),
                ]
            )
        )
        statement_ids = [
            statement.statement_id
            for section in sections
            for statement in section.statements
        ]
        synthesis_id = _stable_id(
            "synthesis",
            evaluated_at.isoformat(),
            *statement_ids,
        )
        return MorningStateSynthesis(
            synthesis_id=synthesis_id,
            evaluated_at=evaluated_at,
            overall_classification=overall,
            complete_evidence=complete,
            no_urgent_attention=urgent_count == 0 and complete,
            urgent_attention_count=urgent_count,
            changes_since_meaningful_check=sections[0],
            attention_today=sections[1],
            handled_paused_waiting=sections[2],
            project_momentum_constraints=sections[3],
            realistic_day_shape=sections[4],
            checkpoint=change_window.checkpoint,
            provider_diagnostics=diagnostics,
        )

    def _change_window(
        self,
        *,
        consumer_id: str,
        evaluated_at: datetime,
    ) -> MorningChangeWindow:
        fallback_since = evaluated_at - timedelta(days=MORNING_CHANGE_FALLBACK_DAYS)
        probe = self.change_service.query_changes(
            evaluated_at=evaluated_at,
            days=MORNING_CHANGE_FALLBACK_DAYS,
            limit=1,
        )
        coverage = probe.coverage
        checkpoints = self.change_service.consumer_checkpoints(
            consumer_id=consumer_id
        )
        checkpoint_by_scope = {
            (item.provider, item.scope_id): item for item in checkpoints
        }
        applicable = tuple(
            item
            for item in coverage
            if item.state != ChangeComparisonState.PROVIDER_NOT_APPLICABLE
        )
        valid_checkpoints: dict[tuple[str, str], ConsumerChangeCheckpoint] = {}
        fallback_scopes: list[str] = []
        diagnostics: list[str] = []
        boundaries: dict[tuple[str, str], datetime] = {}
        for item in applicable:
            key = (item.provider, item.scope_id)
            checkpoint = checkpoint_by_scope.get(key)
            if (
                checkpoint is not None
                and checkpoint.acknowledged_effective_at
                <= evaluated_at + FUTURE_CHECKPOINT_TOLERANCE
            ):
                valid_checkpoints[key] = checkpoint
                boundaries[key] = checkpoint.acknowledged_effective_at
            else:
                boundaries[key] = fallback_since
                fallback_scopes.append(f"{item.provider}:{item.scope_id}")
                if checkpoint is not None:
                    diagnostics.append(
                        f"{item.provider}:{item.scope_id} has a future-skewed acknowledgement; the retained-history fallback was used."
                    )

        selected_since = min(boundaries.values(), default=fallback_since)
        query_since = selected_since - timedelta(microseconds=1)
        first = self.change_service.query_changes(
            since=query_since,
            evaluated_at=evaluated_at,
            limit=500,
        )
        events = list(first.changes)
        cursor = first.next_cursor
        while cursor is not None:
            page = self.change_service.query_changes(
                since=query_since,
                evaluated_at=evaluated_at,
                limit=500,
                cursor=cursor,
            )
            events.extend(page.changes)
            cursor = page.next_cursor

        selected: list[ProviderChangeEvent] = []
        for event in events:
            key = (event.provider, event.scope_id)
            checkpoint = valid_checkpoints.get(key)
            if checkpoint is None:
                if event.effective_at > fallback_since:
                    selected.append(event)
                continue
            event_position = event.event_position or 0
            if (
                event.effective_at > checkpoint.acknowledged_effective_at
                or (
                    event.effective_at == checkpoint.acknowledged_effective_at
                    and event_position > checkpoint.acknowledged_event_position
                )
            ):
                selected.append(event)
        selected = sorted(
            {item.id: item for item in selected}.values(),
            key=lambda item: (
                item.effective_at,
                item.event_position or 0,
                item.id,
            ),
            reverse=True,
        )

        complete = bool(applicable)
        for item in applicable:
            key = (item.provider, item.scope_id)
            boundary = boundaries[key]
            state_complete = item.state in {
                ChangeComparisonState.COMPLETE_WITH_CHANGES,
                ChangeComparisonState.COMPLETE_NO_CHANGES,
            }
            boundary_covered = (
                item.historical_coverage_start is not None
                and item.historical_coverage_start <= boundary
                and (item.retained_from is None or item.retained_from <= boundary)
            )
            if not state_complete or not boundary_covered:
                complete = False
                diagnostics.append(
                    f"{item.provider}:{item.scope_id} does not completely cover the selected meaningful-check boundary."
                )
            if item.diagnostic:
                diagnostics.append(f"{item.provider}:{item.scope_id} — {item.diagnostic}")

        if valid_checkpoints and fallback_scopes:
            mode = MorningCheckpointMode.MIXED
        elif valid_checkpoints and not fallback_scopes:
            mode = MorningCheckpointMode.ACKNOWLEDGED_CHECKPOINT
        else:
            mode = MorningCheckpointMode.RETAINED_HISTORY_FALLBACK
        checkpoint = MorningCheckpointSelection(
            consumer_id=consumer_id,
            mode=mode,
            selected_since=selected_since,
            checkpoints=tuple(
                sorted(
                    valid_checkpoints.values(),
                    key=lambda item: (item.provider, item.scope_id),
                )
            ),
            fallback_scopes=tuple(sorted(fallback_scopes)),
            coverage_complete=complete,
            retained_boundaries=tuple(
                sorted(
                    {
                        item.retained_from
                        for item in applicable
                        if item.retained_from is not None
                    }
                )
            ),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )
        return MorningChangeWindow(
            checkpoint=checkpoint,
            changes=tuple(selected),
            coverage=coverage,
            total_count=len(selected),
        )


morning_state_service = MorningStateService()


def _project_state(item: ProjectBrainProjectSnapshot) -> MorningProjectState:
    definition = item.definition
    if item.activity_focus is None or item.reality is None:
        raise ValueError("Project Brain snapshot is missing shared morning intelligence")
    canonical_project_id = str(
        definition.get("canonical_project_id") or f"system:{definition['key']}"
    )
    return MorningProjectState(
        canonical_project_id=canonical_project_id,
        canonical_project_key=str(definition["key"]),
        name=str(definition["name"]),
        focus=item.activity_focus,
        reality_items=item.reality.items,
        reality_complete=item.reality.complete_evidence,
        reality_total_count=item.reality.total_count,
        provider_diagnostics=item.reality.provider_diagnostics,
    )


def _change_statements(
    window: MorningChangeWindow,
    *,
    project_by_id: dict[str, MorningProjectState],
    evaluated_at: datetime,
) -> tuple[MorningStatement, ...]:
    statements = tuple(
        _statement_from_change(
            item,
            project=project_by_id.get(str(item.canonical_project_id or "")),
            coverage=window.coverage,
            evaluated_at=evaluated_at,
        )
        for item in window.changes
    )
    if statements:
        return statements
    complete = window.checkpoint.coverage_complete
    return (
        MorningStatement(
            statement_id=_stable_id(
                "changes-empty",
                window.checkpoint.consumer_id,
                window.checkpoint.selected_since.isoformat(),
                str(complete),
            ),
            section=MorningSectionId.CHANGES_SINCE_CHECK,
            classification=(
                RealityClassification.NO_MEANINGFUL_CHANGE
                if complete
                else RealityClassification.UNKNOWN
            ),
            status="no_meaningful_change" if complete else "incomplete_change_coverage",
            summary=(
                "No meaningful provider change was recorded since the selected check boundary."
                if complete
                else "Change history is incomplete, so no-change cannot be concluded."
            ),
            reason=(
                "Every applicable provider scope completely covers the deterministic checkpoint or fallback boundary."
                if complete
                else "At least one applicable provider scope is missing, stale, unavailable, baseline-only, or retained after the selected boundary."
            ),
            source_evidence_references=tuple(
                f"provider-change-coverage:{item.provider}:{item.scope_id}"
                for item in window.coverage
            )
            or ("provider-change-coverage:none",),
            source_timestamps=tuple(item.observed_at for item in window.coverage),
            observed_at=evaluated_at,
            freshness=MorningFreshness.FRESH if complete else MorningFreshness.UNKNOWN,
            availability=MorningAvailability.COMPLETE if complete else MorningAvailability.PARTIAL,
            fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
            confidence=MorningConfidence.HIGH if complete else MorningConfidence.UNKNOWN,
            uncertainty=() if complete else window.checkpoint.diagnostics,
        ),
    )


def _statement_from_change(
    event: ProviderChangeEvent,
    *,
    project: MorningProjectState | None,
    coverage: tuple[ChangeCoverage, ...],
    evaluated_at: datetime,
) -> MorningStatement:
    classification = _change_classification(event.category)
    matching_coverage = next(
        (
            item
            for item in coverage
            if item.provider == event.provider and item.scope_id == event.scope_id
        ),
        None,
    )
    freshness, availability = _change_coverage_state(matching_coverage)
    project_key = project.canonical_project_key if project else None
    project_name = project.name if project else "the linked project"
    summary = (
        f"{project_name}: {event.category.value.replace('_', ' ')} was observed for "
        f"{event.provider} {event.provider_record_type} {event.provider_record_id}."
    )
    source_times = tuple(
        dict.fromkeys(
            timestamp
            for timestamp in (
                event.source_event_at,
                event.source_updated_at,
                event.effective_at,
            )
            if timestamp is not None
        )
    )
    return MorningStatement(
        statement_id=_stable_id("change", event.id),
        section=MorningSectionId.CHANGES_SINCE_CHECK,
        classification=classification,
        status=event.category.value,
        summary=summary,
        reason=(
            "SID-139 compared normalized provider state and retained the attributable before/after transition; the transition is not treated as proof of user intent."
        ),
        canonical_project_id=event.canonical_project_id,
        canonical_project_key=project_key,
        life_area_id=project_key,
        provider_identities=(
            ProviderRecordIdentity(
                provider=event.provider,
                provider_record_type=event.provider_record_type,
                provider_record_id=event.provider_record_id,
                provider_reference=event.evidence.provider_reference,
                provider_url=event.evidence.provider_url,
            ),
        ),
        source_evidence_references=(event.evidence.provider_identifier or event.id,),
        source_evidence_summaries=(
            f"Normalized {event.category.value} transition from {event.before!r} to {event.after!r}.",
        ),
        source_timestamps=source_times,
        observed_at=event.observed_at,
        freshness=freshness,
        availability=availability,
        fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
        confidence=(
            MorningConfidence.HIGH
            if freshness == MorningFreshness.FRESH
            else MorningConfidence.LOW
        ),
        uncertainty=(
            ()
            if freshness == MorningFreshness.FRESH
            else ("Provider change coverage is not fresh and complete.",)
        ),
    )


def _statement_from_reality(
    item: RealityItem,
    *,
    section: MorningSectionId,
    observed_at: datetime,
) -> MorningStatement:
    identities = _unique_provider_identities(
        evidence.provider_identity for evidence in item.evidence
    )
    if item.provider_identity is not None:
        identities = _unique_provider_identities((*identities, item.provider_identity))
    refs = tuple(dict.fromkeys(evidence.evidence_id for evidence in item.evidence))
    timestamps = tuple(
        dict.fromkeys(
            timestamp
            for evidence in item.evidence
            for timestamp in (evidence.source_timestamp, evidence.observed_at)
            if timestamp is not None
        )
    )
    fact_type = (
        MorningFactType.EXPLICIT_FACT
        if any(
            evidence.evidence_type == RealityEvidenceType.USER_CONFIRMATION
            for evidence in item.evidence
        )
        else MorningFactType.DETERMINISTIC_CONCLUSION
    )
    label = item.title or (
        item.normalized_work_identity.provider_record_id
        if item.normalized_work_identity
        else item.reconciliation_id
    )
    uncertainty = []
    if item.confidence in {RealityConfidence.LOW, RealityConfidence.UNKNOWN}:
        uncertainty.append(item.classification_reason)
    if item.identity_state.value != "exact":
        uncertainty.append("Canonical work identity is not exact.")
    return MorningStatement(
        statement_id=_stable_id(section.value, item.reality_item_id),
        section=section,
        classification=item.classification,
        status=item.classification.value,
        summary=f"{label} — {item.classification.value.replace('_', ' ')}.",
        reason=item.classification_reason,
        canonical_project_id=item.canonical_project_id,
        canonical_project_key=item.canonical_project_key,
        life_area_id=item.canonical_project_key,
        linked_work_identity=item.normalized_work_identity,
        provider_identities=identities,
        source_evidence_references=refs or (f"reality:{item.reality_item_id}",),
        source_evidence_summaries=tuple(
            dict.fromkeys(evidence.summary for evidence in item.evidence)
        ),
        source_timestamps=timestamps,
        observed_at=observed_at,
        freshness=_reality_freshness(item.evidence),
        availability=_reality_availability(item.evidence),
        fact_type=fact_type,
        confidence=MorningConfidence(item.confidence.value),
        uncertainty=tuple(dict.fromkeys(uncertainty)),
        temporal=item.temporal,
        suggested_action=_suggested_action(item.proposed_safe_resolution),
    )


def _focus_statement(
    project: MorningProjectState,
    evaluated_at: datetime,
) -> MorningStatement:
    focus = project.focus
    state = focus.primary_state
    classification = {
        ProjectFocusState.ACTIVE_MOMENTUM: RealityClassification.NO_MEANINGFUL_CHANGE,
        ProjectFocusState.WAITING_EXTERNAL: RealityClassification.WAITING,
        ProjectFocusState.INTENTIONALLY_PAUSED: RealityClassification.WAITING,
        ProjectFocusState.DEDICATED_SESSION_NEEDED: RealityClassification.UPCOMING_NOT_ACTIONABLE,
        ProjectFocusState.QUIET_POSSIBLE_DRIFT: RealityClassification.UNKNOWN,
        ProjectFocusState.RECENTLY_COMPLETED: RealityClassification.ALREADY_HANDLED,
        ProjectFocusState.INSUFFICIENT_EVIDENCE: RealityClassification.UNKNOWN,
    }[state]
    descriptions = {
        ProjectFocusState.ACTIVE_MOMENTUM: "has supported recent momentum",
        ProjectFocusState.WAITING_EXTERNAL: "has an attributable external wait or constraint",
        ProjectFocusState.INTENTIONALLY_PAUSED: "is intentionally paused under reviewed explicit intent",
        ProjectFocusState.DEDICATED_SESSION_NEEDED: "has a supported next step that needs a dedicated context or session",
        ProjectFocusState.QUIET_POSSIBLE_DRIFT: "may be quiet or drifting, but that remains a conservative inference",
        ProjectFocusState.RECENTLY_COMPLETED: "has supported recent completion evidence",
        ProjectFocusState.INSUFFICIENT_EVIDENCE: "does not have enough trustworthy evidence for a stronger focus conclusion",
    }
    identities = _unique_provider_identities(
        ProviderRecordIdentity(
            provider=evidence.provider,
            provider_record_type=evidence.provider_record_type or "project_evidence",
            provider_record_id=evidence.provider_record_id or evidence.evidence_key,
        )
        for evidence in focus.evidence
    )
    uncertainty = []
    if focus.confirmation_reason:
        uncertainty.append(focus.confirmation_reason)
    if focus.freshness != ActivityFreshness.FRESH:
        uncertainty.append(f"Overall focus evidence freshness is {focus.freshness.value}.")
    if any(
        item.state
        not in {ProviderCoverageState.FRESH, ProviderCoverageState.NOT_APPLICABLE}
        for item in focus.provider_coverage
    ):
        uncertainty.append("At least one provider has incomplete or unavailable focus coverage.")
    suggestion = None
    if focus.user_confirmation_recommended and focus.confirmation_question:
        suggestion = MorningSuggestedAction(
            code="confirm_project_focus",
            summary=focus.confirmation_question,
        )
    return MorningStatement(
        statement_id=_stable_id("focus", project.canonical_project_id),
        section=MorningSectionId.PROJECT_MOMENTUM_CONSTRAINTS,
        classification=classification,
        status=state.value,
        summary=f"{project.name} {descriptions[state]}.",
        reason=(
            f"SID-138 evaluated {focus.evidence_total_count} deduplicated evidence records before returning {focus.evidence_returned_count}; silence alone is not treated as intent or adverse project meaning."
        ),
        canonical_project_id=project.canonical_project_id,
        canonical_project_key=project.canonical_project_key,
        life_area_id=project.canonical_project_key,
        provider_identities=identities,
        source_evidence_references=tuple(
            evidence.evidence_key for evidence in focus.evidence
        )
        or (f"project-focus:{project.canonical_project_id}",),
        source_evidence_summaries=tuple(
            dict.fromkeys(evidence.summary for evidence in focus.evidence)
        ),
        source_timestamps=tuple(
            dict.fromkeys(
                timestamp
                for evidence in focus.evidence
                for timestamp in (evidence.source_timestamp, evidence.observed_at)
                if timestamp is not None
            )
        ),
        observed_at=evaluated_at,
        freshness=_activity_freshness(focus.freshness),
        availability=_focus_availability(focus),
        fact_type=(
            MorningFactType.EXPLICIT_FACT
            if focus.explicitly_confirmed
            else MorningFactType.INFERENCE
        ),
        confidence=MorningConfidence(focus.confidence.value),
        uncertainty=tuple(dict.fromkeys(uncertainty)),
        suggested_action=suggestion,
    )


def _pause_statement(
    project: MorningProjectState,
    evaluated_at: datetime,
) -> MorningStatement:
    focus = project.focus
    intent = focus.explicit_intent
    refs = tuple(evidence.evidence_key for evidence in focus.evidence)
    timestamps = tuple(
        timestamp
        for timestamp in (
            intent.confirmed_at if intent else None,
            intent.review_after if intent else None,
            intent.expires_at if intent else None,
        )
        if timestamp is not None
    )
    return MorningStatement(
        statement_id=_stable_id("pause", project.canonical_project_id),
        section=MorningSectionId.HANDLED_PAUSED_WAITING,
        classification=RealityClassification.WAITING,
        status="intentionally_paused",
        summary=f"{project.name} is intentionally paused.",
        reason=(
            intent.reason
            if intent and intent.reason
            else "The pause comes from reviewed explicit intent, not from inactivity."
        ),
        canonical_project_id=project.canonical_project_id,
        canonical_project_key=project.canonical_project_key,
        life_area_id=project.canonical_project_key,
        source_evidence_references=refs or (f"project-focus-intent:{project.canonical_project_id}",),
        source_timestamps=timestamps,
        observed_at=evaluated_at,
        freshness=_activity_freshness(focus.freshness),
        availability=_focus_availability(focus),
        fact_type=MorningFactType.EXPLICIT_FACT,
        confidence=MorningConfidence(focus.confidence.value),
        uncertainty=(focus.confirmation_reason,) if focus.confirmation_reason else (),
        suggested_action=(
            MorningSuggestedAction(
                code="review_project_pause",
                summary=focus.confirmation_question,
            )
            if focus.user_confirmation_recommended and focus.confirmation_question
            else None
        ),
    )


def _day_shape_statements(
    state: CalendarTimeState,
    *,
    calendar_result: CalendarReadResult,
    evaluated_at: datetime,
) -> tuple[MorningStatement, ...]:
    if calendar_result.error:
        return (
            MorningStatement(
                statement_id=_stable_id("calendar-error", calendar_result.error),
                section=MorningSectionId.REALISTIC_DAY_SHAPE,
                classification=RealityClassification.UNKNOWN,
                status="calendar_unavailable",
                summary="Calendar coverage is unavailable, so the shape of the day is incomplete.",
                reason=calendar_result.error,
                provider_identities=(
                    ProviderRecordIdentity(
                        provider="google_calendar",
                        provider_record_type="calendar_scope",
                        provider_record_id="configured-calendar",
                    ),
                ),
                source_evidence_references=("calendar-read:error",),
                observed_at=evaluated_at,
                freshness=MorningFreshness.UNAVAILABLE,
                availability=MorningAvailability.UNAVAILABLE,
                fact_type=MorningFactType.EXPLICIT_FACT,
                confidence=MorningConfidence.UNKNOWN,
                uncertainty=(calendar_result.error,),
            ),
        )

    statements: list[MorningStatement] = []
    for event in state.blocking_events:
        start = event_start(event, evaluated_at.tzinfo)
        end = event_end(event, evaluated_at.tzinfo)
        event_id = str(event.get("id") or _stable_id("calendar-event", start.isoformat(), end.isoformat()))
        title = str(event.get("title") or "Scheduled commitment")
        statements.append(
            MorningStatement(
                statement_id=_stable_id("calendar-commitment", event_id),
                section=MorningSectionId.REALISTIC_DAY_SHAPE,
                classification=RealityClassification.UPCOMING_NOT_ACTIONABLE,
                status="fixed_commitment",
                summary=f"{title} is scheduled from {start.isoformat()} to {end.isoformat()}.",
                reason="This is a blocking calendar commitment. Scheduling proves reserved time, not attendance or completion.",
                provider_identities=(
                    ProviderRecordIdentity(
                        provider="google_calendar",
                        provider_record_type="event",
                        provider_record_id=event_id,
                        provider_url=event.get("html_link"),
                    ),
                ),
                source_evidence_references=(f"calendar-event:{event_id}",),
                source_timestamps=(start, end),
                observed_at=evaluated_at,
                freshness=MorningFreshness.FRESH,
                availability=MorningAvailability.COMPLETE,
                fact_type=MorningFactType.EXPLICIT_FACT,
                confidence=MorningConfidence.HIGH,
            )
        )

    block = state.current_or_next_free_block
    if block is not None:
        start = event_start(block, evaluated_at.tzinfo)
        end = event_end(block, evaluated_at.tzinfo)
        duration = int(block["duration_minutes"])
        statements.append(
            MorningStatement(
                statement_id=_stable_id("calendar-free-block", start.isoformat(), end.isoformat()),
                section=MorningSectionId.REALISTIC_DAY_SHAPE,
                classification=RealityClassification.NO_MEANINGFUL_CHANGE,
                status="usable_free_block",
                summary=f"A {duration}-minute {'current' if block.get('is_current') else 'upcoming'} free block is available.",
                reason="The shared calendar-time contract identifies available capacity; free time is context and does not manufacture work.",
                provider_identities=(
                    ProviderRecordIdentity(
                        provider="google_calendar",
                        provider_record_type="computed_free_block",
                        provider_record_id=_stable_id("free-block", start.isoformat(), end.isoformat()),
                    ),
                ),
                source_evidence_references=(f"calendar-free-block:{start.isoformat()}:{end.isoformat()}",),
                source_timestamps=(start, end),
                observed_at=evaluated_at,
                freshness=MorningFreshness.FRESH,
                availability=MorningAvailability.COMPLETE,
                fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
                confidence=MorningConfidence.HIGH,
            )
        )
    if not statements:
        statements.append(
            MorningStatement(
                statement_id=_stable_id("calendar-empty", evaluated_at.date().isoformat()),
                section=MorningSectionId.REALISTIC_DAY_SHAPE,
                classification=RealityClassification.NO_MEANINGFUL_CHANGE,
                status="no_remaining_fixed_commitments",
                summary="No blocking calendar commitments remain today.",
                reason="The successful Calendar read returned no remaining blocking events; this does not imply that the day should be filled with work.",
                provider_identities=(
                    ProviderRecordIdentity(
                        provider="google_calendar",
                        provider_record_type="calendar_scope",
                        provider_record_id="configured-calendar",
                    ),
                ),
                source_evidence_references=(f"calendar-day:{evaluated_at.date().isoformat()}",),
                observed_at=evaluated_at,
                freshness=MorningFreshness.FRESH,
                availability=MorningAvailability.COMPLETE,
                fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
                confidence=MorningConfidence.HIGH,
            )
        )
    return tuple(statements)


def _empty_attention_statement(
    *,
    projects: tuple[MorningProjectState, ...],
    complete: bool,
    evaluated_at: datetime,
) -> MorningStatement:
    return MorningStatement(
        statement_id=_stable_id("attention-empty", str(complete), evaluated_at.date().isoformat()),
        section=MorningSectionId.ATTENTION_TODAY,
        classification=(
            RealityClassification.NO_MEANINGFUL_CHANGE
            if complete
            else RealityClassification.UNKNOWN
        ),
        status="no_urgent_attention" if complete else "attention_coverage_incomplete",
        summary=(
            "Nothing urgent needs attention from the complete eligible reality evidence."
            if complete
            else "No urgent item is supported by the available evidence, but coverage is incomplete."
        ),
        reason=(
            "Every project reality projection was complete and produced no needs-action or mismatch item."
            if complete
            else "At least one project has incomplete, stale, missing, or failed evidence, so absence of an urgent item is not a complete no-action conclusion."
        ),
        source_evidence_references=tuple(
            f"reality-projection:{item.canonical_project_id}" for item in projects
        )
        or ("reality-projection:none",),
        observed_at=evaluated_at,
        freshness=MorningFreshness.FRESH if complete else MorningFreshness.UNKNOWN,
        availability=MorningAvailability.COMPLETE if complete else MorningAvailability.PARTIAL,
        fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
        confidence=MorningConfidence.HIGH if complete else MorningConfidence.UNKNOWN,
        uncertainty=() if complete else ("Reality evidence is incomplete.",),
    )


def _empty_support_statement(
    projects: tuple[MorningProjectState, ...],
    complete: bool,
    evaluated_at: datetime,
) -> MorningStatement:
    return MorningStatement(
        statement_id=_stable_id("support-empty", str(complete)),
        section=MorningSectionId.HANDLED_PAUSED_WAITING,
        classification=(
            RealityClassification.NO_MEANINGFUL_CHANGE
            if complete
            else RealityClassification.UNKNOWN
        ),
        status="no_supporting_state" if complete else "supporting_state_unknown",
        summary=(
            "No handled, paused, waiting, or protected-upcoming item needs reassurance."
            if complete
            else "Handled, paused, and waiting coverage is incomplete."
        ),
        reason="This section is derived only from attributable SID-138 and SID-243 state.",
        source_evidence_references=tuple(
            f"reality-projection:{item.canonical_project_id}" for item in projects
        )
        or ("reality-projection:none",),
        observed_at=evaluated_at,
        freshness=MorningFreshness.FRESH if complete else MorningFreshness.UNKNOWN,
        availability=MorningAvailability.COMPLETE if complete else MorningAvailability.PARTIAL,
        fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
        confidence=MorningConfidence.HIGH if complete else MorningConfidence.UNKNOWN,
    )


def _no_projects_statement(evaluated_at: datetime) -> MorningStatement:
    return MorningStatement(
        statement_id=_stable_id("projects-none"),
        section=MorningSectionId.PROJECT_MOMENTUM_CONSTRAINTS,
        classification=RealityClassification.UNKNOWN,
        status="project_state_unavailable",
        summary="No canonical project state was available for synthesis.",
        reason="Project momentum cannot be inferred without canonical Project Brain state.",
        source_evidence_references=("project-brain:none",),
        observed_at=evaluated_at,
        freshness=MorningFreshness.UNKNOWN,
        availability=MorningAvailability.UNAVAILABLE,
        fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
        confidence=MorningConfidence.UNKNOWN,
        uncertainty=("Canonical Project Brain state is unavailable.",),
    )


def _bounded_section(
    section_id: MorningSectionId,
    heading: str,
    statements: tuple[MorningStatement, ...],
    limit: int,
) -> MorningSection:
    bound = max(1, min(limit, 50))
    ordered = tuple(sorted(statements, key=_statement_order_key))
    returned = ordered[:bound]
    return MorningSection(
        section_id=section_id,
        heading=heading,
        statements=returned,
        total_count=len(ordered),
        returned_count=len(returned),
        item_limit=bound,
        truncated=len(ordered) > len(returned),
    )


def _statement_order_key(item: MorningStatement) -> tuple[Any, ...]:
    rank = {
        RealityClassification.NEEDS_ACTION: 0,
        RealityClassification.POTENTIAL_MISMATCH: 1,
        RealityClassification.WAITING: 2,
        RealityClassification.UNKNOWN: 3,
        RealityClassification.UPCOMING_NOT_ACTIONABLE: 4,
        RealityClassification.ALREADY_HANDLED: 5,
        RealityClassification.NO_MEANINGFUL_CHANGE: 6,
    }
    due = item.temporal.due_at if item.temporal else None
    return (
        rank[item.classification],
        due.isoformat() if due else "9999",
        item.canonical_project_id or "",
        item.linked_work_identity.provider if item.linked_work_identity else "",
        item.linked_work_identity.provider_record_id if item.linked_work_identity else "",
        item.statement_id,
    )


def _change_classification(category: ChangeCategory) -> RealityClassification:
    if category in {ChangeCategory.WORK_COMPLETED, ChangeCategory.MILESTONE_COMPLETED}:
        return RealityClassification.ALREADY_HANDLED
    if category in {
        ChangeCategory.BLOCKER_ADDED,
        ChangeCategory.BLOCKER_CHANGED,
        ChangeCategory.WAITING_STARTED,
        ChangeCategory.WAITING_CHANGED,
    }:
        return RealityClassification.WAITING
    return RealityClassification.UNKNOWN


def _change_coverage_state(
    coverage: ChangeCoverage | None,
) -> tuple[MorningFreshness, MorningAvailability]:
    if coverage is None:
        return MorningFreshness.UNKNOWN, MorningAvailability.UNKNOWN
    if coverage.state in {
        ChangeComparisonState.COMPLETE_WITH_CHANGES,
        ChangeComparisonState.COMPLETE_NO_CHANGES,
    }:
        return MorningFreshness.FRESH, MorningAvailability.COMPLETE
    if coverage.state == ChangeComparisonState.STALE_HISTORY:
        return MorningFreshness.STALE, MorningAvailability.PARTIAL
    if coverage.state in {
        ChangeComparisonState.PROVIDER_UNAVAILABLE,
        ChangeComparisonState.PROVIDER_NOT_CONFIGURED,
    }:
        return MorningFreshness.UNAVAILABLE, MorningAvailability.UNAVAILABLE
    if coverage.state == ChangeComparisonState.PROVIDER_NOT_APPLICABLE:
        return MorningFreshness.UNKNOWN, MorningAvailability.NOT_APPLICABLE
    return MorningFreshness.UNKNOWN, MorningAvailability.PARTIAL


def _reality_freshness(evidence: tuple[RealityEvidence, ...]) -> MorningFreshness:
    states = {item.freshness for item in evidence}
    if not states:
        return MorningFreshness.UNKNOWN
    if states == {RealityFreshness.FRESH}:
        return MorningFreshness.FRESH
    if states == {RealityFreshness.STALE}:
        return MorningFreshness.STALE
    if RealityFreshness.UNKNOWN in states and len(states) == 1:
        return MorningFreshness.UNKNOWN
    return MorningFreshness.MIXED


def _reality_availability(evidence: tuple[RealityEvidence, ...]) -> MorningAvailability:
    states = {item.availability for item in evidence}
    if not states:
        return MorningAvailability.UNKNOWN
    unavailable = {
        RealityAvailability.UNAVAILABLE,
        RealityAvailability.NOT_CONFIGURED,
    }
    if states & unavailable:
        return (
            MorningAvailability.UNAVAILABLE
            if states <= unavailable
            else MorningAvailability.PARTIAL
        )
    if states == {RealityAvailability.NOT_APPLICABLE}:
        return MorningAvailability.NOT_APPLICABLE
    if states <= {RealityAvailability.AVAILABLE, RealityAvailability.NOT_APPLICABLE}:
        return MorningAvailability.COMPLETE
    return MorningAvailability.UNKNOWN


def _activity_freshness(value: ActivityFreshness) -> MorningFreshness:
    return {
        ActivityFreshness.FRESH: MorningFreshness.FRESH,
        ActivityFreshness.STALE: MorningFreshness.STALE,
        ActivityFreshness.UNAVAILABLE: MorningFreshness.UNAVAILABLE,
        ActivityFreshness.UNKNOWN: MorningFreshness.UNKNOWN,
    }[value]


def _focus_availability(focus: ProjectActivityFocus) -> MorningAvailability:
    applicable = tuple(
        item
        for item in focus.provider_coverage
        if item.state != ProviderCoverageState.NOT_APPLICABLE
    )
    if not applicable:
        return MorningAvailability.UNKNOWN
    complete = all(item.state == ProviderCoverageState.FRESH for item in applicable)
    if complete:
        return MorningAvailability.COMPLETE
    unavailable = all(
        item.state in {
            ProviderCoverageState.UNAVAILABLE,
            ProviderCoverageState.NOT_CONFIGURED,
        }
        for item in applicable
    )
    return MorningAvailability.UNAVAILABLE if unavailable else MorningAvailability.PARTIAL


def _suggested_action(
    resolution: SafeResolution | None,
) -> MorningSuggestedAction | None:
    if resolution is None:
        return None
    return MorningSuggestedAction(
        code=resolution.code,
        summary=resolution.summary,
        target_work_identity=resolution.target_work_identity,
        requires_user_confirmation=resolution.requires_user_confirmation,
    )


def _unique_provider_identities(
    identities: Iterable[ProviderRecordIdentity],
) -> tuple[ProviderRecordIdentity, ...]:
    selected: dict[tuple[str, str, str], ProviderRecordIdentity] = {}
    for item in identities:
        selected[(item.provider, item.provider_record_type, item.provider_record_id)] = item
    return tuple(selected[key] for key in sorted(selected))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"morning:{prefix}:{digest[:32]}"


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
