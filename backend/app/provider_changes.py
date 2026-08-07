from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .activity_domain import (
    ActivityFreshness,
    MeaningfulActivityCategory,
    MeaningfulActivityEvent,
    activity_event_payload,
)
from .storage import database_connection


PROVIDER_OBSERVATION_SCHEMA_VERSION = 1
PROVIDER_CHANGE_SCHEMA_VERSION = 1
CHANGE_RETENTION_DAYS = 365
MAX_RETAINED_EVENTS_PER_SCOPE = 10_000
MAX_CHECKPOINT_BYTES = 30_000
FUTURE_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)
CHANGE_CHECKPOINT_STALE_AFTER = timedelta(hours=24)


class ObservationFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class ObservationAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    NOT_APPLICABLE = "not_applicable"


class CompletionState(StrEnum):
    UNKNOWN = "unknown"
    INCOMPLETE = "incomplete"
    COMPLETED = "completed"


class RelationshipKind(StrEnum):
    BLOCKER = "blocker"
    WAITING = "waiting"


class ChangeCategory(StrEnum):
    RECORD_CREATED = "record_created"
    WORK_STARTED = "work_started"
    STATUS_CHANGED = "status_changed"
    WORK_COMPLETED = "work_completed"
    WORK_REOPENED = "work_reopened"
    PRIORITY_CHANGED = "priority_changed"
    BLOCKER_ADDED = "blocker_added"
    BLOCKER_CHANGED = "blocker_changed"
    BLOCKER_REMOVED = "blocker_removed"
    WAITING_STARTED = "waiting_started"
    WAITING_CHANGED = "waiting_changed"
    WAITING_RESOLVED = "waiting_resolved"
    MILESTONE_PROGRESSED = "milestone_progressed"
    MILESTONE_COMPLETED = "milestone_completed"
    LINKED_COMMUNICATION_CHANGED = "linked_communication_changed"


class ChangeComparisonState(StrEnum):
    COMPLETE_WITH_CHANGES = "complete_with_changes"
    COMPLETE_NO_CHANGES = "complete_no_changes"
    BASELINE_ESTABLISHED = "baseline_established"
    STALE_HISTORY = "stale_history"
    INCOMPLETE_HISTORY = "incomplete_history"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    PROVIDER_NOT_APPLICABLE = "provider_not_applicable"


class ChangeTimeBasis(StrEnum):
    SOURCE_EVENT = "source_event"
    SOURCE_UPDATED = "source_updated"
    OBSERVED_FALLBACK = "observed_fallback"


class ProviderEvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_reference: str | None = Field(default=None, max_length=500)
    provider_url: str | None = Field(default=None, max_length=2000)
    provider_identifier: str | None = Field(default=None, max_length=240)


class ObservedRelationship(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RelationshipKind
    relationship_id: str | None = Field(default=None, max_length=240)
    related_provider_record_id: str = Field(..., min_length=1, max_length=240)
    direction: str | None = Field(default=None, max_length=80)
    external: bool | None = None


class ObservedMilestone(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    milestone_id: str = Field(..., min_length=1, max_length=240)
    name: str | None = Field(default=None, max_length=500)
    progress: float | None = Field(default=None, ge=0)
    completed: bool | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_time(self) -> "ObservedMilestone":
        if self.updated_at is not None:
            _require_aware(self.updated_at, "milestone.updated_at")
        return self


class LinkedCommunicationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    communication_id: str = Field(..., min_length=1, max_length=240)
    outcome: str | None = Field(default=None, max_length=240)
    occurred_at: datetime | None = None
    trustworthy: bool = False

    @model_validator(mode="after")
    def validate_time(self) -> "LinkedCommunicationOutcome":
        if self.occurred_at is not None:
            _require_aware(self.occurred_at, "linked_communication.occurred_at")
        return self


class ProviderObservation(BaseModel):
    """Provider-neutral, comparison-only state. Unknown fields stay absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = PROVIDER_OBSERVATION_SCHEMA_VERSION
    canonical_project_id: str | None = Field(default=None, max_length=128)
    provider: str = Field(..., min_length=1, max_length=80)
    scope_id: str = Field(..., min_length=1, max_length=240)
    provider_record_type: str = Field(..., min_length=1, max_length=80)
    provider_record_id: str = Field(..., min_length=1, max_length=240)
    provider_revision: str | None = Field(default=None, max_length=500)
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    source_started_at: datetime | None = None
    source_completed_at: datetime | None = None
    observed_at: datetime
    normalized_status: str | None = Field(default=None, max_length=120)
    completion_state: CompletionState = CompletionState.UNKNOWN
    priority: int | str | None = None
    relationships: tuple[ObservedRelationship, ...] | None = None
    milestone: ObservedMilestone | None = None
    linked_communication: LinkedCommunicationOutcome | None = None
    freshness: ObservationFreshness = ObservationFreshness.FRESH
    availability: ObservationAvailability = ObservationAvailability.AVAILABLE
    diagnostic: str | None = Field(default=None, max_length=1000)
    evidence: ProviderEvidenceReference

    @model_validator(mode="after")
    def validate_contract(self) -> "ProviderObservation":
        for name in (
            "source_created_at",
            "source_updated_at",
            "source_started_at",
            "source_completed_at",
            "observed_at",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_aware(value, name)
        if self.availability != ObservationAvailability.AVAILABLE:
            raise ValueError("record observations require an available provider")
        encoded = _canonical_json(_comparison_state(self)).encode("utf-8")
        if len(encoded) > MAX_CHECKPOINT_BYTES:
            raise ValueError("provider observation exceeds the bounded checkpoint limit")
        return self


class ProviderChangeEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = PROVIDER_CHANGE_SCHEMA_VERSION
    event_position: int | None = None
    id: str
    deduplication_key: str
    category: ChangeCategory
    canonical_project_id: str | None = None
    provider: str
    scope_id: str
    provider_record_type: str
    provider_record_id: str
    source_event_at: datetime | None = None
    source_updated_at: datetime | None = None
    observed_at: datetime
    effective_at: datetime
    time_basis: ChangeTimeBasis
    before: Any = None
    after: Any = None
    evidence: ProviderEvidenceReference
    activity_id: str


class ChangeCoverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    scope_id: str
    canonical_project_id: str | None = None
    state: ChangeComparisonState
    observed_at: datetime
    historical_coverage_start: datetime | None = None
    retained_from: datetime | None = None
    last_success_at: datetime | None = None
    observation_count: int = 0
    diagnostic: str | None = None


class ObservationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: ChangeComparisonState
    baseline_records: int = 0
    unchanged_records: int = 0
    out_of_order_records: int = 0
    changes: tuple[ProviderChangeEvent, ...] = ()
    coverage: ChangeCoverage


class ChangeQueryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluated_at: datetime
    since: datetime | None = None
    days: Literal[7, 14, 30] | None = None
    changes: tuple[ProviderChangeEvent, ...] = ()
    total_count: int = 0
    returned_count: int = 0
    limit: int = 100
    next_cursor: str | None = None
    coverage: tuple[ChangeCoverage, ...] = ()
    conclusion: ChangeComparisonState


class ConsumerChangeCheckpoint(BaseModel):
    """A durable, explicitly acknowledged provider-change position."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = PROVIDER_CHANGE_SCHEMA_VERSION
    consumer_id: str
    provider: str
    scope_id: str
    canonical_project_id: str | None = None
    acknowledged_effective_at: datetime
    acknowledged_event_position: int
    acknowledged_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> "ConsumerChangeCheckpoint":
        _require_aware(self.acknowledged_effective_at, "acknowledged_effective_at")
        _require_aware(self.acknowledged_at, "acknowledged_at")
        return self


class ProviderChangeService:
    def observe_scope(
        self,
        *,
        provider: str,
        scope_id: str,
        canonical_project_id: str | None,
        observations: Iterable[ProviderObservation],
        observed_at: datetime,
        historical_coverage_start: datetime | None = None,
        freshness: ObservationFreshness = ObservationFreshness.FRESH,
        diagnostic: str | None = None,
    ) -> ObservationResult:
        _require_aware(observed_at, "observed_at")
        if historical_coverage_start is not None:
            _require_aware(historical_coverage_start, "historical_coverage_start")
        records = tuple(observations)
        for record in records:
            if record.provider != provider or record.scope_id != scope_id:
                raise ValueError("observation identity does not match its provider scope")
            if record.canonical_project_id != canonical_project_id:
                raise ValueError("observation canonical project does not match its scope")

        with database_connection() as connection:
            scope = _scope_row(connection, provider, scope_id)
            if freshness != ObservationFreshness.FRESH:
                comparison_state = (
                    ChangeComparisonState.STALE_HISTORY
                    if freshness == ObservationFreshness.STALE
                    else ChangeComparisonState.INCOMPLETE_HISTORY
                )
                _upsert_scope(
                    connection,
                    provider=provider,
                    scope_id=scope_id,
                    canonical_project_id=canonical_project_id,
                    state=comparison_state,
                    diagnostic=diagnostic,
                    historical_coverage_start=historical_coverage_start,
                    observed_at=observed_at,
                    successful=False,
                )
                coverage = _coverage_from_row(
                    _scope_row(connection, provider, scope_id)
                )
                return ObservationResult(
                    state=comparison_state,
                    coverage=coverage,
                )
            first_scope_observation = scope is None or int(scope["observation_count"]) == 0
            baseline_count = unchanged_count = out_of_order_count = 0
            changes: list[ProviderChangeEvent] = []
            for observation in _dedupe_observations(records):
                previous = _checkpoint_row(connection, observation)
                current_state = _comparison_state(observation)
                current_hash = _state_hash(current_state)
                if previous is None:
                    if first_scope_observation:
                        baseline_count += 1
                    elif _trustworthy_new_record(observation, scope, observed_at):
                        event = _make_change_event(
                            observation,
                            ChangeCategory.RECORD_CREATED,
                            before=None,
                            after={"record": "created"},
                            source_event_at=observation.source_created_at,
                        )
                        changes.extend(_persist_changes(connection, [event]))
                    else:
                        baseline_count += 1
                    _upsert_checkpoint(connection, observation, current_state, current_hash)
                    continue

                previous_updated = _parse_datetime(previous["source_updated_at"])
                if (
                    previous_updated is not None
                    and observation.source_updated_at is not None
                    and observation.source_updated_at < previous_updated
                ):
                    out_of_order_count += 1
                    continue
                if previous["state_hash"] == current_hash:
                    unchanged_count += 1
                    _upsert_checkpoint(connection, observation, current_state, current_hash)
                    continue

                previous_state = json.loads(previous["state_json"])
                detected = _detect_changes(previous_state, observation)
                changes.extend(_persist_changes(connection, detected))
                _upsert_checkpoint(connection, observation, current_state, current_hash)

            scope_state = (
                ChangeComparisonState.BASELINE_ESTABLISHED
                if first_scope_observation
                else (
                    ChangeComparisonState.COMPLETE_WITH_CHANGES
                    if changes
                    else ChangeComparisonState.COMPLETE_NO_CHANGES
                )
            )
            _upsert_scope(
                connection,
                provider=provider,
                scope_id=scope_id,
                canonical_project_id=canonical_project_id,
                state=scope_state,
                diagnostic=diagnostic,
                historical_coverage_start=historical_coverage_start,
                observed_at=observed_at,
                successful=True,
            )
            _prune_events(connection, provider, scope_id, observed_at)
            coverage = _coverage_from_row(_scope_row(connection, provider, scope_id))
        return ObservationResult(
            state=scope_state,
            baseline_records=baseline_count,
            unchanged_records=unchanged_count,
            out_of_order_records=out_of_order_count,
            changes=tuple(changes),
            coverage=coverage,
        )

    def record_coverage(
        self,
        *,
        provider: str,
        scope_id: str,
        canonical_project_id: str | None,
        availability: ObservationAvailability,
        observed_at: datetime,
        diagnostic: str | None = None,
    ) -> ChangeCoverage:
        _require_aware(observed_at, "observed_at")
        state = {
            ObservationAvailability.UNAVAILABLE: ChangeComparisonState.PROVIDER_UNAVAILABLE,
            ObservationAvailability.NOT_CONFIGURED: ChangeComparisonState.PROVIDER_NOT_CONFIGURED,
            ObservationAvailability.NOT_APPLICABLE: ChangeComparisonState.PROVIDER_NOT_APPLICABLE,
        }.get(availability)
        if state is None:
            raise ValueError("available coverage must be recorded through observe_scope")
        with database_connection() as connection:
            _upsert_scope(
                connection,
                provider=provider,
                scope_id=scope_id,
                canonical_project_id=canonical_project_id,
                state=state,
                diagnostic=diagnostic,
                historical_coverage_start=None,
                observed_at=observed_at,
                successful=False,
            )
            return _coverage_from_row(_scope_row(connection, provider, scope_id))

    def query_changes(
        self,
        *,
        canonical_project_id: str | None = None,
        provider: str | None = None,
        scope_id: str | None = None,
        since: datetime | None = None,
        days: Literal[7, 14, 30] | None = None,
        evaluated_at: datetime,
        limit: int = 100,
        cursor: str | None = None,
    ) -> ChangeQueryResult:
        _require_aware(evaluated_at, "evaluated_at")
        if since is not None:
            _require_aware(since, "since")
        if days is not None and days not in {7, 14, 30}:
            raise ValueError("days must be 7, 14, or 30")
        window_start = since or (
            evaluated_at - timedelta(days=days) if days is not None else None
        )
        bounded_limit = max(1, min(limit, 500))
        clauses = ["effective_at <= ?"]
        values: list[Any] = [evaluated_at.isoformat()]
        if window_start is not None:
            clauses.append("effective_at > ?")
            values.append(window_start.isoformat())
        if canonical_project_id is not None:
            clauses.append("canonical_project_id = ?")
            values.append(canonical_project_id)
        if provider is not None:
            clauses.append("provider = ?")
            values.append(provider)
        if scope_id is not None:
            clauses.append("scope_id = ?")
            values.append(scope_id)
        total_where = " AND ".join(clauses)
        total_values = list(values)
        if cursor:
            cursor_time, cursor_position = _decode_cursor(cursor)
            clauses.append("(effective_at < ? OR (effective_at = ? AND event_position < ?))")
            values.extend([cursor_time, cursor_time, cursor_position])
        where = " AND ".join(clauses)
        with database_connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS count FROM provider_change_events WHERE {total_where}",
                total_values,
            ).fetchone()["count"]
            rows = connection.execute(
                f"""
                SELECT * FROM provider_change_events
                WHERE {where}
                ORDER BY effective_at DESC, event_position DESC
                LIMIT ?
                """,
                [*values, bounded_limit + 1],
            ).fetchall()
            coverage_rows = connection.execute(
                """
                SELECT * FROM provider_change_scopes
                WHERE (? IS NULL OR canonical_project_id = ?)
                  AND (? IS NULL OR provider = ?)
                  AND (? IS NULL OR scope_id = ?)
                ORDER BY provider, scope_id
                """,
                (
                    canonical_project_id,
                    canonical_project_id,
                    provider,
                    provider,
                    scope_id,
                    scope_id,
                ),
            ).fetchall()
        has_more = len(rows) > bounded_limit
        selected = rows[:bounded_limit]
        changes = tuple(_event_from_row(row) for row in selected)
        coverage = tuple(
            _coverage_at(_coverage_from_row(row), evaluated_at) for row in coverage_rows
        )
        conclusion = _query_conclusion(coverage, bool(total), window_start)
        next_cursor = (
            _encode_cursor(selected[-1]["effective_at"], selected[-1]["event_position"])
            if has_more and selected
            else None
        )
        return ChangeQueryResult(
            evaluated_at=evaluated_at,
            since=since,
            days=days,
            changes=changes,
            total_count=int(total),
            returned_count=len(changes),
            limit=bounded_limit,
            next_cursor=next_cursor,
            coverage=coverage,
            conclusion=conclusion,
        )

    def acknowledge(
        self,
        *,
        consumer_id: str,
        provider: str,
        scope_id: str,
        through_cursor: str,
        acknowledged_at: datetime,
    ) -> None:
        _require_aware(acknowledged_at, "acknowledged_at")
        effective_at, position = _decode_cursor(through_cursor)
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO provider_change_consumers
                    (consumer_id, provider, scope_id, acknowledged_effective_at,
                     acknowledged_event_position, acknowledged_at, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(consumer_id, provider, scope_id) DO UPDATE SET
                    acknowledged_effective_at = excluded.acknowledged_effective_at,
                    acknowledged_event_position = excluded.acknowledged_event_position,
                    acknowledged_at = excluded.acknowledged_at,
                    schema_version = excluded.schema_version
                """,
                (
                    consumer_id,
                    provider,
                    scope_id,
                    effective_at,
                    position,
                    acknowledged_at.isoformat(),
                    PROVIDER_CHANGE_SCHEMA_VERSION,
                ),
            )

    def consumer_checkpoints(
        self,
        *,
        consumer_id: str,
        canonical_project_id: str | None = None,
    ) -> tuple[ConsumerChangeCheckpoint, ...]:
        """Read explicit acknowledgement positions without advancing them."""

        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT consumers.*, scopes.canonical_project_id
                FROM provider_change_consumers AS consumers
                LEFT JOIN provider_change_scopes AS scopes
                  ON scopes.provider = consumers.provider
                 AND scopes.scope_id = consumers.scope_id
                WHERE consumers.consumer_id = ?
                  AND (? IS NULL OR scopes.canonical_project_id = ?)
                ORDER BY consumers.provider, consumers.scope_id
                """,
                (consumer_id, canonical_project_id, canonical_project_id),
            ).fetchall()
        return tuple(
            ConsumerChangeCheckpoint(
                consumer_id=row["consumer_id"],
                provider=row["provider"],
                scope_id=row["scope_id"],
                canonical_project_id=row["canonical_project_id"],
                acknowledged_effective_at=_parse_datetime(
                    row["acknowledged_effective_at"]
                ),
                acknowledged_event_position=int(
                    row["acknowledged_event_position"]
                ),
                acknowledged_at=_parse_datetime(row["acknowledged_at"]),
                schema_version=int(row["schema_version"]),
            )
            for row in rows
        )


provider_change_service = ProviderChangeService()


def _comparison_state(observation: ProviderObservation) -> dict[str, Any]:
    return {
        "normalized_status": observation.normalized_status,
        "completion_state": observation.completion_state.value,
        "priority": observation.priority,
        "relationships": (
            sorted(
                [item.model_dump(mode="json") for item in observation.relationships],
                key=lambda item: _canonical_json(item),
            )
            if observation.relationships is not None
            else None
        ),
        "milestone": (
            observation.milestone.model_dump(mode="json")
            if observation.milestone is not None
            else None
        ),
        "linked_communication": (
            observation.linked_communication.model_dump(mode="json")
            if observation.linked_communication is not None
            else None
        ),
    }


def _detect_changes(
    previous: dict[str, Any],
    observation: ProviderObservation,
) -> list[ProviderChangeEvent]:
    current = _comparison_state(observation)
    changes: list[ProviderChangeEvent] = []
    before_completion = previous.get("completion_state")
    after_completion = current.get("completion_state")
    work_record = observation.provider_record_type in {"issue", "task", "work_item"}
    if work_record and before_completion != CompletionState.COMPLETED.value and after_completion == CompletionState.COMPLETED.value:
        changes.append(
            _make_change_event(
                observation,
                ChangeCategory.WORK_COMPLETED,
                before=before_completion,
                after=after_completion,
                source_event_at=observation.source_completed_at,
            )
        )
    elif work_record and before_completion == CompletionState.COMPLETED.value and after_completion != CompletionState.COMPLETED.value:
        changes.append(
            _make_change_event(
                observation,
                ChangeCategory.WORK_REOPENED,
                before=before_completion,
                after=after_completion,
            )
        )
    elif work_record and previous.get("normalized_status") != current.get("normalized_status"):
        category = (
            ChangeCategory.WORK_STARTED
            if current.get("normalized_status") == "started"
            else ChangeCategory.STATUS_CHANGED
        )
        changes.append(
            _make_change_event(
                observation,
                category,
                before=previous.get("normalized_status"),
                after=current.get("normalized_status"),
                source_event_at=(
                    observation.source_started_at
                    if category == ChangeCategory.WORK_STARTED
                    else None
                ),
            )
        )
    if previous.get("priority") != current.get("priority"):
        changes.append(
            _make_change_event(
                observation,
                ChangeCategory.PRIORITY_CHANGED,
                before=previous.get("priority"),
                after=current.get("priority"),
            )
        )
    changes.extend(_relationship_changes(previous, current, observation, RelationshipKind.BLOCKER))
    changes.extend(_relationship_changes(previous, current, observation, RelationshipKind.WAITING))
    before_milestone = previous.get("milestone")
    after_milestone = current.get("milestone")
    if before_milestone != after_milestone:
        completed_before = bool(before_milestone and before_milestone.get("completed"))
        completed_after = bool(after_milestone and after_milestone.get("completed"))
        category = (
            ChangeCategory.MILESTONE_COMPLETED
            if completed_after and not completed_before
            else ChangeCategory.MILESTONE_PROGRESSED
        )
        source_event_at = (
            observation.milestone.updated_at if observation.milestone else None
        )
        changes.append(
            _make_change_event(
                observation,
                category,
                before=before_milestone,
                after=after_milestone,
                source_event_at=source_event_at,
            )
        )
    before_comm = previous.get("linked_communication")
    after_comm = current.get("linked_communication")
    if (
        before_comm != after_comm
        and after_comm is not None
        and bool(after_comm.get("trustworthy"))
    ):
        changes.append(
            _make_change_event(
                observation,
                ChangeCategory.LINKED_COMMUNICATION_CHANGED,
                before=before_comm,
                after=after_comm,
                source_event_at=observation.linked_communication.occurred_at,
            )
        )
    return changes


def _relationship_changes(
    previous: dict[str, Any],
    current: dict[str, Any],
    observation: ProviderObservation,
    kind: RelationshipKind,
) -> list[ProviderChangeEvent]:
    previous_all = previous.get("relationships")
    current_all = current.get("relationships")
    if previous_all is None or current_all is None:
        return []
    before = [item for item in previous_all if item.get("kind") == kind.value]
    after = [item for item in current_all if item.get("kind") == kind.value]
    if before == after:
        return []
    if kind == RelationshipKind.BLOCKER:
        category = (
            ChangeCategory.BLOCKER_ADDED
            if not before and after
            else ChangeCategory.BLOCKER_REMOVED
            if before and not after
            else ChangeCategory.BLOCKER_CHANGED
        )
    else:
        category = (
            ChangeCategory.WAITING_STARTED
            if not before and after
            else ChangeCategory.WAITING_RESOLVED
            if before and not after
            else ChangeCategory.WAITING_CHANGED
        )
    return [_make_change_event(observation, category, before=before, after=after)]


def _make_change_event(
    observation: ProviderObservation,
    category: ChangeCategory,
    *,
    before: Any,
    after: Any,
    source_event_at: datetime | None = None,
) -> ProviderChangeEvent:
    effective_at, basis = _effective_time(
        source_event_at=source_event_at,
        source_updated_at=observation.source_updated_at,
        observed_at=observation.observed_at,
    )
    identity = {
        "provider": observation.provider,
        "record_type": observation.provider_record_type,
        "record_id": observation.provider_record_id,
        "category": category.value,
        "before": before,
        "after": after,
        "source_anchor": (
            source_event_at or observation.source_updated_at or observation.observed_at
        ).isoformat(),
    }
    deduplication_key = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"pcos-change:{deduplication_key}"))
    activity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"pcos-change-activity:{event_id}"))
    return ProviderChangeEvent(
        id=event_id,
        deduplication_key=deduplication_key,
        category=category,
        canonical_project_id=observation.canonical_project_id,
        provider=observation.provider,
        scope_id=observation.scope_id,
        provider_record_type=observation.provider_record_type,
        provider_record_id=observation.provider_record_id,
        source_event_at=source_event_at,
        source_updated_at=observation.source_updated_at,
        observed_at=observation.observed_at,
        effective_at=effective_at,
        time_basis=basis,
        before=before,
        after=after,
        evidence=observation.evidence,
        activity_id=activity_id,
    )


def _persist_changes(connection, events: Iterable[ProviderChangeEvent]) -> list[ProviderChangeEvent]:
    persisted: list[ProviderChangeEvent] = []
    for event in events:
        inserted = connection.execute(
            """
            INSERT OR IGNORE INTO provider_change_events
                (id, deduplication_key, transition_category, canonical_project_id,
                 provider, scope_id, provider_record_type, provider_record_id,
                 source_event_at, source_updated_at, observed_at, effective_at,
                 time_basis, before_json, after_json, evidence_json, activity_id,
                 schema_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.deduplication_key,
                event.category.value,
                event.canonical_project_id,
                event.provider,
                event.scope_id,
                event.provider_record_type,
                event.provider_record_id,
                event.source_event_at.isoformat() if event.source_event_at else None,
                event.source_updated_at.isoformat() if event.source_updated_at else None,
                event.observed_at.isoformat(),
                event.effective_at.isoformat(),
                event.time_basis.value,
                _canonical_json(event.before) if event.before is not None else None,
                _canonical_json(event.after) if event.after is not None else None,
                _canonical_json(event.evidence.model_dump(mode="json")),
                event.activity_id,
                PROVIDER_CHANGE_SCHEMA_VERSION,
                event.observed_at.isoformat(),
            ),
        ).rowcount
        activity = _activity_for_change(event)
        connection.execute(
            """
            INSERT OR IGNORE INTO activity_logs
                (id, action_type, title, detail, payload, source, created_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                event.activity_id,
                activity.category.value,
                activity.summary,
                _canonical_json(activity_event_payload(activity)),
                activity.source_provider,
                event.observed_at.isoformat(),
            ),
        )
        if inserted:
            row = connection.execute(
                "SELECT * FROM provider_change_events WHERE id = ?", (event.id,)
            ).fetchone()
            persisted.append(_event_from_row(row))
    return persisted


def _activity_for_change(event: ProviderChangeEvent) -> MeaningfulActivityEvent:
    category_map = {
        ChangeCategory.RECORD_CREATED: MeaningfulActivityCategory.WORK_CREATED,
        ChangeCategory.WORK_STARTED: MeaningfulActivityCategory.WORK_STARTED,
        ChangeCategory.STATUS_CHANGED: MeaningfulActivityCategory.STATUS_CHANGED,
        ChangeCategory.WORK_COMPLETED: MeaningfulActivityCategory.WORK_COMPLETED,
        ChangeCategory.WORK_REOPENED: MeaningfulActivityCategory.WORK_REOPENED,
        ChangeCategory.PRIORITY_CHANGED: MeaningfulActivityCategory.PRIORITY_CHANGED,
        ChangeCategory.BLOCKER_ADDED: MeaningfulActivityCategory.BLOCKER_ADDED,
        ChangeCategory.BLOCKER_CHANGED: MeaningfulActivityCategory.BLOCKER_CHANGED,
        ChangeCategory.BLOCKER_REMOVED: MeaningfulActivityCategory.BLOCKER_REMOVED,
        ChangeCategory.WAITING_STARTED: MeaningfulActivityCategory.WAITING_STARTED,
        ChangeCategory.WAITING_CHANGED: MeaningfulActivityCategory.WAITING_CHANGED,
        ChangeCategory.WAITING_RESOLVED: MeaningfulActivityCategory.WAITING_RESOLVED,
        ChangeCategory.MILESTONE_PROGRESSED: MeaningfulActivityCategory.MILESTONE_PROGRESS,
        ChangeCategory.MILESTONE_COMPLETED: MeaningfulActivityCategory.MILESTONE_COMPLETED,
        ChangeCategory.LINKED_COMMUNICATION_CHANGED: MeaningfulActivityCategory.LINKED_COMMUNICATION_CHANGED,
    }
    provider_identifier = event.evidence.provider_identifier or event.provider_record_id
    summary = f"{event.category.value.replace('_', ' ').capitalize()}: {provider_identifier}"
    return MeaningfulActivityEvent(
        category=category_map[event.category],
        canonical_project_id=event.canonical_project_id,
        source_provider=event.provider,
        provider_record_type=event.provider_record_type,
        provider_record_id=event.provider_record_id,
        source_timestamp=event.effective_at,
        observed_at=event.observed_at,
        freshness=ActivityFreshness.FRESH,
        evidence_key=f"provider_change:{event.id}",
        summary=summary,
        attributable_payload={
            "change_event_id": event.id,
            "transition_category": event.category.value,
            "time_basis": event.time_basis.value,
            "before": event.before,
            "after": event.after,
            "provider_reference": event.evidence.provider_reference,
            "provider_url": event.evidence.provider_url,
        },
    )


def _trustworthy_new_record(observation, scope, observed_at: datetime) -> bool:
    created = observation.source_created_at
    last_success = _parse_datetime(scope["last_success_at"]) if scope else None
    return bool(
        created is not None
        and last_success is not None
        and last_success < created <= observed_at + FUTURE_CLOCK_SKEW_TOLERANCE
    )


def _effective_time(*, source_event_at, source_updated_at, observed_at):
    candidate = source_event_at or source_updated_at
    if candidate is not None and candidate <= observed_at:
        return candidate, (
            ChangeTimeBasis.SOURCE_EVENT
            if source_event_at is not None
            else ChangeTimeBasis.SOURCE_UPDATED
        )
    return observed_at, ChangeTimeBasis.OBSERVED_FALLBACK


def _dedupe_observations(records):
    unique = {}
    for record in records:
        key = (record.provider_record_type, record.provider_record_id)
        current = unique.get(key)
        if current is None or _observation_order(record) > _observation_order(current):
            unique[key] = record
    return tuple(unique.values())


def _observation_order(record):
    return (record.source_updated_at or datetime.min.replace(tzinfo=timezone.utc), record.observed_at)


def _scope_row(connection, provider, scope_id):
    return connection.execute(
        "SELECT * FROM provider_change_scopes WHERE provider = ? AND scope_id = ?",
        (provider, scope_id),
    ).fetchone()


def _checkpoint_row(connection, observation):
    return connection.execute(
        """
        SELECT * FROM provider_record_checkpoints
        WHERE provider = ? AND scope_id = ? AND provider_record_type = ?
          AND provider_record_id = ?
        """,
        (
            observation.provider,
            observation.scope_id,
            observation.provider_record_type,
            observation.provider_record_id,
        ),
    ).fetchone()


def _upsert_checkpoint(connection, observation, state, state_hash):
    now = observation.observed_at.isoformat()
    ordered_source_updated = (
        observation.source_updated_at
        if observation.source_updated_at is not None
        and observation.source_updated_at
        <= observation.observed_at + FUTURE_CLOCK_SKEW_TOLERANCE
        else None
    )
    connection.execute(
        """
        INSERT INTO provider_record_checkpoints
            (provider, scope_id, provider_record_type, provider_record_id,
             canonical_project_id, source_revision, source_updated_at, observed_at,
             state_hash, state_json, schema_version, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, scope_id, provider_record_type, provider_record_id)
        DO UPDATE SET
            canonical_project_id = excluded.canonical_project_id,
            source_revision = excluded.source_revision,
            source_updated_at = excluded.source_updated_at,
            observed_at = CASE
                WHEN excluded.observed_at > provider_record_checkpoints.observed_at
                THEN excluded.observed_at ELSE provider_record_checkpoints.observed_at END,
            state_hash = excluded.state_hash,
            state_json = excluded.state_json,
            schema_version = excluded.schema_version,
            updated_at = excluded.updated_at
        """,
        (
            observation.provider,
            observation.scope_id,
            observation.provider_record_type,
            observation.provider_record_id,
            observation.canonical_project_id,
            observation.provider_revision,
            ordered_source_updated.isoformat() if ordered_source_updated else None,
            now,
            state_hash,
            _canonical_json(state),
            PROVIDER_OBSERVATION_SCHEMA_VERSION,
            now,
            now,
        ),
    )


def _upsert_scope(
    connection,
    *,
    provider,
    scope_id,
    canonical_project_id,
    state,
    diagnostic,
    historical_coverage_start,
    observed_at,
    successful,
):
    now = observed_at.isoformat()
    connection.execute(
        """
        INSERT INTO provider_change_scopes
            (provider, scope_id, canonical_project_id, coverage_state, diagnostic,
             historical_coverage_start, retained_from, last_success_at, observed_at,
             observation_count, schema_version, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, scope_id) DO UPDATE SET
            canonical_project_id = excluded.canonical_project_id,
            coverage_state = excluded.coverage_state,
            diagnostic = excluded.diagnostic,
            historical_coverage_start = COALESCE(
                provider_change_scopes.historical_coverage_start,
                excluded.historical_coverage_start
            ),
            last_success_at = COALESCE(excluded.last_success_at, provider_change_scopes.last_success_at),
            observed_at = excluded.observed_at,
            observation_count = provider_change_scopes.observation_count + excluded.observation_count,
            schema_version = excluded.schema_version,
            updated_at = excluded.updated_at
        """,
        (
            provider,
            scope_id,
            canonical_project_id,
            state.value,
            diagnostic,
            historical_coverage_start.isoformat() if historical_coverage_start else None,
            None,
            now if successful else None,
            now,
            1 if successful else 0,
            PROVIDER_CHANGE_SCHEMA_VERSION,
            now,
            now,
        ),
    )


def _prune_events(connection, provider, scope_id, now):
    cutoff = (now - timedelta(days=CHANGE_RETENTION_DAYS)).isoformat()
    connection.execute(
        "DELETE FROM provider_change_events WHERE provider = ? AND scope_id = ? AND effective_at < ?",
        (provider, scope_id, cutoff),
    )
    connection.execute(
        """
        DELETE FROM provider_change_events
        WHERE event_position IN (
            SELECT event_position FROM provider_change_events
            WHERE provider = ? AND scope_id = ?
            ORDER BY effective_at DESC, event_position DESC
            LIMIT -1 OFFSET ?
        )
        """,
        (provider, scope_id, MAX_RETAINED_EVENTS_PER_SCOPE),
    )
    scope = _scope_row(connection, provider, scope_id)
    history_start = scope["historical_coverage_start"] if scope else None
    retained_from = max(value for value in (history_start, cutoff) if value is not None)
    connection.execute(
        "UPDATE provider_change_scopes SET retained_from = ? WHERE provider = ? AND scope_id = ?",
        (retained_from, provider, scope_id),
    )


def _coverage_from_row(row):
    return ChangeCoverage(
        provider=row["provider"],
        scope_id=row["scope_id"],
        canonical_project_id=row["canonical_project_id"],
        state=row["coverage_state"],
        observed_at=row["observed_at"],
        historical_coverage_start=row["historical_coverage_start"],
        retained_from=row["retained_from"],
        last_success_at=row["last_success_at"],
        observation_count=int(row["observation_count"]),
        diagnostic=row["diagnostic"],
    )


def _event_from_row(row):
    return ProviderChangeEvent(
        event_position=int(row["event_position"]),
        id=row["id"],
        deduplication_key=row["deduplication_key"],
        category=row["transition_category"],
        canonical_project_id=row["canonical_project_id"],
        provider=row["provider"],
        scope_id=row["scope_id"],
        provider_record_type=row["provider_record_type"],
        provider_record_id=row["provider_record_id"],
        source_event_at=row["source_event_at"],
        source_updated_at=row["source_updated_at"],
        observed_at=row["observed_at"],
        effective_at=row["effective_at"],
        time_basis=row["time_basis"],
        before=json.loads(row["before_json"]) if row["before_json"] else None,
        after=json.loads(row["after_json"]) if row["after_json"] else None,
        evidence=json.loads(row["evidence_json"]),
        activity_id=row["activity_id"],
    )


def _coverage_at(coverage: ChangeCoverage, evaluated_at: datetime) -> ChangeCoverage:
    if (
        coverage.state in {
            ChangeComparisonState.COMPLETE_WITH_CHANGES,
            ChangeComparisonState.COMPLETE_NO_CHANGES,
        }
        and coverage.last_success_at is not None
        and evaluated_at - coverage.last_success_at > CHANGE_CHECKPOINT_STALE_AFTER
    ):
        return coverage.model_copy(update={"state": ChangeComparisonState.STALE_HISTORY})
    return coverage


def _query_conclusion(coverage, has_changes, window_start):
    if not coverage:
        return ChangeComparisonState.INCOMPLETE_HISTORY
    states = {item.state for item in coverage}
    if ChangeComparisonState.PROVIDER_UNAVAILABLE in states:
        return ChangeComparisonState.PROVIDER_UNAVAILABLE
    if ChangeComparisonState.PROVIDER_NOT_CONFIGURED in states:
        return ChangeComparisonState.PROVIDER_NOT_CONFIGURED
    if states and states <= {ChangeComparisonState.PROVIDER_NOT_APPLICABLE}:
        return ChangeComparisonState.PROVIDER_NOT_APPLICABLE
    if ChangeComparisonState.STALE_HISTORY in states:
        return ChangeComparisonState.STALE_HISTORY
    if ChangeComparisonState.INCOMPLETE_HISTORY in states:
        return ChangeComparisonState.INCOMPLETE_HISTORY
    if ChangeComparisonState.BASELINE_ESTABLISHED in states:
        return ChangeComparisonState.INCOMPLETE_HISTORY
    if window_start is not None and any(
        item.historical_coverage_start is None
        or item.historical_coverage_start > window_start
        or (item.retained_from is not None and item.retained_from > window_start)
        for item in coverage
        if item.state != ChangeComparisonState.PROVIDER_NOT_APPLICABLE
    ):
        return ChangeComparisonState.INCOMPLETE_HISTORY
    return (
        ChangeComparisonState.COMPLETE_WITH_CHANGES
        if has_changes
        else ChangeComparisonState.COMPLETE_NO_CHANGES
    )


def _state_hash(state):
    return hashlib.sha256(_canonical_json(state).encode("utf-8")).hexdigest()


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _parse_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _encode_cursor(effective_at, position):
    raw = _canonical_json({"effective_at": effective_at, "position": int(position)})
    return urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor):
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(urlsafe_b64decode(cursor + padding).decode("utf-8"))
        return str(payload["effective_at"]), int(payload["position"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid change cursor") from exc


def _require_aware(value, name):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
