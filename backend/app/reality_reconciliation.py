from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .dependency_evaluator import (
    DependencyEvaluationState,
    EvaluatedDependencyEvidence,
)
from .project_activity_focus import ProviderCoverage, ProviderCoverageState
from .provider_changes import ChangeQueryResult, ProviderChangeEvent
from .storage import database_connection
from .work_domain import NormalizedWorkItem, WorkStatus


REALITY_SCHEMA_VERSION = 1
FUTURE_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)
HANDLED_CLAIMS = {"completed", "handled", "resolved", "sent"}
OPEN_CLAIMS = {"incomplete", "in_progress", "open", "pending", "started"}


class RealityClassification(StrEnum):
    NEEDS_ACTION = "needs_action"
    POTENTIAL_MISMATCH = "potential_mismatch"
    WAITING = "waiting"
    ALREADY_HANDLED = "already_handled"
    UPCOMING_NOT_ACTIONABLE = "upcoming_not_actionable"
    NO_MEANINGFUL_CHANGE = "no_meaningful_change"
    UNKNOWN = "unknown"


class RealityEvidenceType(StrEnum):
    WORK_STATE = "work_state"
    COMMUNICATION_OUTCOME = "communication_outcome"
    PROVIDER_CHANGE = "provider_change"
    WAITING_STATE = "waiting_state"
    USER_CONFIRMATION = "user_confirmation"
    TEMPORAL_BOUNDARY = "temporal_boundary"
    PROVIDER_COVERAGE = "provider_coverage"


CURRENT_STATE_EVIDENCE_TYPES = {
    RealityEvidenceType.WORK_STATE,
    RealityEvidenceType.COMMUNICATION_OUTCOME,
    RealityEvidenceType.WAITING_STATE,
    RealityEvidenceType.USER_CONFIRMATION,
}


class RealityFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class RealityAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    NOT_APPLICABLE = "not_applicable"


class RealityIdentityState(StrEnum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class RealityConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ConfirmationOutcome(StrEnum):
    HANDLED = "handled"
    NOT_HANDLED = "not_handled"
    WAITING = "waiting"
    REVIEW_ONLY = "review_only"


class WorkIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(..., min_length=1, max_length=80)
    provider_record_id: str = Field(..., min_length=1, max_length=240)


class ProviderRecordIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(..., min_length=1, max_length=80)
    provider_record_type: str = Field(..., min_length=1, max_length=80)
    provider_record_id: str = Field(..., min_length=1, max_length=240)
    provider_reference: str | None = Field(default=None, max_length=500)
    provider_url: str | None = Field(default=None, max_length=2000)


class RealityEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = REALITY_SCHEMA_VERSION
    evidence_id: str = Field(..., min_length=1, max_length=500)
    evidence_type: RealityEvidenceType
    canonical_project_id: str | None = Field(default=None, max_length=128)
    normalized_work_identity: WorkIdentity | None = None
    provider_identity: ProviderRecordIdentity
    linked_work_identity: WorkIdentity | None = None
    claim: str | None = Field(default=None, max_length=240)
    observed_state: str | None = Field(default=None, max_length=240)
    source_timestamp: datetime | None = None
    observed_at: datetime
    freshness: RealityFreshness = RealityFreshness.FRESH
    availability: RealityAvailability = RealityAvailability.AVAILABLE
    trustworthy: bool = True
    summary: str = Field(..., min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> "RealityEvidence":
        _require_aware(self.observed_at, "observed_at")
        if self.source_timestamp is not None:
            _require_aware(self.source_timestamp, "source_timestamp")
        _validate_safe_metadata(self.metadata)
        return self


class TemporalActionability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    due_date: date | None = None
    due_at: datetime | None = None
    earliest_useful_action_at: datetime | None = None
    waiting_until: datetime | None = None
    preparation_window_start: datetime | None = None
    hard_deadline: datetime | None = None
    action_possible_now: bool | None = None
    action_useful_now: bool | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> "TemporalActionability":
        for name in (
            "due_at",
            "earliest_useful_action_at",
            "waiting_until",
            "preparation_window_start",
            "hard_deadline",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_aware(value, name)
        return self


class SafeResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(..., min_length=1, max_length=120)
    summary: str = Field(..., min_length=1, max_length=500)
    target_work_identity: WorkIdentity | None = None
    requires_user_confirmation: bool = True
    performs_provider_mutation: Literal[False] = False


class RealityCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = REALITY_SCHEMA_VERSION
    reconciliation_id: str = Field(..., min_length=1, max_length=240)
    canonical_project_id: str = Field(..., min_length=1, max_length=128)
    canonical_project_key: str = Field(..., min_length=1, max_length=128)
    normalized_work_identity: WorkIdentity | None = None
    title: str | None = Field(default=None, max_length=500)
    provider_identity: ProviderRecordIdentity | None = None
    evidence: tuple[RealityEvidence, ...] = ()
    temporal: TemporalActionability = Field(default_factory=TemporalActionability)
    identity_state: RealityIdentityState = RealityIdentityState.EXACT
    possible_work_matches: tuple[WorkIdentity, ...] = ()


class RealityItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = REALITY_SCHEMA_VERSION
    reality_item_id: str
    reconciliation_id: str
    canonical_project_id: str
    canonical_project_key: str
    normalized_work_identity: WorkIdentity | None
    provider_identity: ProviderRecordIdentity | None
    title: str | None
    classification: RealityClassification
    classification_reason: str
    temporal: TemporalActionability
    identity_state: RealityIdentityState
    ambiguity_candidates: tuple[WorkIdentity, ...] = ()
    confidence: RealityConfidence
    evidence: tuple[RealityEvidence, ...]
    evidence_version: str
    proposed_safe_resolution: SafeResolution | None = None


class RealityProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = REALITY_SCHEMA_VERSION
    canonical_project_id: str
    canonical_project_key: str
    evaluated_at: datetime
    overall_classification: RealityClassification
    items: tuple[RealityItem, ...] = ()
    total_count: int = 0
    returned_count: int = 0
    item_limit: int = 12
    classification_counts: dict[str, int] = Field(default_factory=dict)
    complete_evidence: bool = False
    provider_diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_time_and_counts(self) -> "RealityProjection":
        _require_aware(self.evaluated_at, "evaluated_at")
        if self.returned_count != len(self.items):
            raise ValueError("returned_count must match the returned reality items")
        if self.total_count < self.returned_count:
            raise ValueError("total_count cannot be smaller than returned_count")
        return self


class RealityConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = REALITY_SCHEMA_VERSION
    confirmation_id: str = Field(..., min_length=1, max_length=128)
    reconciliation_id: str = Field(..., min_length=1, max_length=240)
    canonical_project_id: str = Field(..., min_length=1, max_length=128)
    selected_resolution_code: str = Field(..., min_length=1, max_length=120)
    outcome: ConfirmationOutcome
    confirming_actor: str = Field(..., min_length=1, max_length=240)
    confirmed_at: datetime
    evidence_references: tuple[str, ...] = ()
    evidence_version: str = Field(..., min_length=1, max_length=128)
    idempotency_key: str = Field(..., min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_time(self) -> "RealityConfirmation":
        _require_aware(self.confirmed_at, "confirmed_at")
        if "@" in self.confirming_actor:
            raise ValueError("confirming_actor must be a stable actor identity, not a raw email")
        return self


class RealityConfirmationRepository:
    def confirm(
        self,
        *,
        reconciliation_id: str,
        canonical_project_id: str,
        selected_resolution_code: str,
        outcome: ConfirmationOutcome,
        confirming_actor: str,
        confirmed_at: datetime,
        evidence_references: Iterable[str],
        evidence_version: str,
        idempotency_key: str,
    ) -> RealityConfirmation:
        _require_aware(confirmed_at, "confirmed_at")
        references = tuple(dict.fromkeys(str(item) for item in evidence_references))
        confirmation_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"pcos-reality-confirmation:{idempotency_key}")
        )
        candidate = RealityConfirmation(
            confirmation_id=confirmation_id,
            reconciliation_id=reconciliation_id,
            canonical_project_id=canonical_project_id,
            selected_resolution_code=selected_resolution_code,
            outcome=outcome,
            confirming_actor=confirming_actor,
            confirmed_at=confirmed_at,
            evidence_references=references,
            evidence_version=evidence_version,
            idempotency_key=idempotency_key,
        )
        with database_connection() as connection:
            existing = connection.execute(
                "SELECT * FROM reality_confirmations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = _confirmation_from_row(existing)
                if stored != candidate:
                    raise ValueError("idempotency key already belongs to another confirmation")
                return stored
            connection.execute(
                """
                INSERT INTO reality_confirmations
                    (id, reconciliation_id, canonical_project_id,
                     selected_resolution_code, outcome, confirming_actor,
                     confirmed_at, evidence_references_json, evidence_version,
                     idempotency_key, schema_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.confirmation_id,
                    candidate.reconciliation_id,
                    candidate.canonical_project_id,
                    candidate.selected_resolution_code,
                    candidate.outcome.value,
                    candidate.confirming_actor,
                    candidate.confirmed_at.isoformat(),
                    _canonical_json(list(candidate.evidence_references)),
                    candidate.evidence_version,
                    candidate.idempotency_key,
                    REALITY_SCHEMA_VERSION,
                    candidate.confirmed_at.isoformat(),
                ),
            )
        return candidate

    def list_for_project(self, canonical_project_id: str) -> tuple[RealityConfirmation, ...]:
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM reality_confirmations
                WHERE canonical_project_id = ?
                ORDER BY confirmed_at DESC, id ASC
                """,
                (canonical_project_id,),
            ).fetchall()
        return tuple(_confirmation_from_row(row) for row in rows)


class RealityReconciliationService:
    def evaluate(
        self,
        *,
        canonical_project_id: str,
        canonical_project_key: str,
        candidates: Iterable[RealityCandidate],
        evaluated_at: datetime,
        confirmations: Iterable[RealityConfirmation] = (),
        complete_evidence: bool,
        provider_diagnostics: Iterable[str] = (),
        item_limit: int = 12,
    ) -> RealityProjection:
        _require_aware(evaluated_at, "evaluated_at")
        confirmations_by_reconciliation: dict[str, list[RealityConfirmation]] = {}
        for confirmation in confirmations:
            confirmations_by_reconciliation.setdefault(
                confirmation.reconciliation_id, []
            ).append(confirmation)
        items = [
            self._classify(
                candidate,
                evaluated_at=evaluated_at,
                confirmations=confirmations_by_reconciliation.get(
                    candidate.reconciliation_id, []
                ),
            )
            for candidate in candidates
        ]
        ordered = sorted(items, key=_item_order_key)
        bound = max(0, item_limit)
        returned = tuple(ordered[:bound])
        counts = Counter(item.classification.value for item in ordered)
        overall = _overall_classification(ordered, complete_evidence=complete_evidence)
        return RealityProjection(
            canonical_project_id=canonical_project_id,
            canonical_project_key=canonical_project_key,
            evaluated_at=evaluated_at,
            overall_classification=overall,
            items=returned,
            total_count=len(ordered),
            returned_count=len(returned),
            item_limit=bound,
            classification_counts=dict(sorted(counts.items())),
            complete_evidence=complete_evidence,
            provider_diagnostics=tuple(dict.fromkeys(provider_diagnostics)),
        )

    def project_from_work(
        self,
        *,
        canonical_project_id: str,
        canonical_project_key: str,
        work_items: Iterable[NormalizedWorkItem],
        dependency_evidence: Iterable[EvaluatedDependencyEvidence],
        provider_coverage: Iterable[ProviderCoverage],
        recent_changes: ChangeQueryResult,
        evaluated_at: datetime,
        item_limit: int = 12,
    ) -> RealityProjection:
        _require_aware(evaluated_at, "evaluated_at")
        coverage = tuple(provider_coverage)
        dependencies = tuple(dependency_evidence)
        changes_by_identity: dict[tuple[str, str], list[ProviderChangeEvent]] = {}
        for change in recent_changes.changes:
            changes_by_identity.setdefault(
                (change.provider, change.provider_record_id), []
            ).append(change)
        candidates = [
            _candidate_from_work(
                item,
                canonical_project_id=canonical_project_id,
                canonical_project_key=canonical_project_key,
                dependency_evidence=dependencies,
                changes=changes_by_identity.get(
                    (item.provider, item.provider_record_id), []
                ),
                evaluated_at=evaluated_at,
            )
            for item in work_items
        ]
        diagnostics = [
            f"{item.provider}: {item.state.value}"
            + (f" — {item.detail}" if item.detail else "")
            for item in coverage
            if item.state
            not in {ProviderCoverageState.FRESH, ProviderCoverageState.NOT_APPLICABLE}
        ]
        complete = bool(coverage) and all(
            item.state in {ProviderCoverageState.FRESH, ProviderCoverageState.NOT_APPLICABLE}
            for item in coverage
        )
        confirmations = reality_confirmation_repository.list_for_project(
            canonical_project_id
        )
        return self.evaluate(
            canonical_project_id=canonical_project_id,
            canonical_project_key=canonical_project_key,
            candidates=candidates,
            evaluated_at=evaluated_at,
            confirmations=confirmations,
            complete_evidence=complete,
            provider_diagnostics=diagnostics,
            item_limit=item_limit,
        )

    def _classify(
        self,
        candidate: RealityCandidate,
        *,
        evaluated_at: datetime,
        confirmations: Iterable[RealityConfirmation],
    ) -> RealityItem:
        base_evidence = tuple(
            sorted(
                (*candidate.evidence, *_temporal_evidence(candidate, evaluated_at)),
                key=_evidence_order_key,
            )
        )
        evidence_version = _evidence_version(base_evidence)
        current_confirmations = [
            item
            for item in confirmations
            if item.evidence_version == evidence_version
        ]
        handled_confirmation = next(
            (
                item
                for item in current_confirmations
                if item.outcome == ConfirmationOutcome.HANDLED
            ),
            None,
        )
        waiting_confirmation = next(
            (
                item
                for item in current_confirmations
                if item.outcome == ConfirmationOutcome.WAITING
            ),
            None,
        )
        evidence = base_evidence
        attributable_confirmation = handled_confirmation or waiting_confirmation
        if attributable_confirmation is not None:
            confirmation_evidence = RealityEvidence(
                evidence_id=f"reality_confirmation:{attributable_confirmation.confirmation_id}",
                evidence_type=RealityEvidenceType.USER_CONFIRMATION,
                canonical_project_id=candidate.canonical_project_id,
                normalized_work_identity=candidate.normalized_work_identity,
                provider_identity=ProviderRecordIdentity(
                    provider="pcos",
                    provider_record_type="reality_confirmation",
                    provider_record_id=attributable_confirmation.confirmation_id,
                ),
                linked_work_identity=candidate.normalized_work_identity,
                claim=attributable_confirmation.outcome.value,
                observed_state=attributable_confirmation.outcome.value,
                source_timestamp=attributable_confirmation.confirmed_at,
                observed_at=attributable_confirmation.confirmed_at,
                summary=(
                    "Explicit confirmation by "
                    f"{attributable_confirmation.confirming_actor}."
                ),
                metadata={
                    "selected_resolution_code": attributable_confirmation.selected_resolution_code,
                    "evidence_version": attributable_confirmation.evidence_version,
                    "evidence_references": list(
                        attributable_confirmation.evidence_references
                    ),
                },
            )
            evidence = tuple(
                sorted((*base_evidence, confirmation_evidence), key=_evidence_order_key)
            )

        classification: RealityClassification
        reason: str
        confidence = RealityConfidence.HIGH
        resolution: SafeResolution | None = None

        if handled_confirmation is not None:
            classification = RealityClassification.ALREADY_HANDLED
            reason = (
                "An attributable user confirmation marks this reconciliation handled "
                f"for evidence version {evidence_version[:12]}."
            )
        elif candidate.identity_state != RealityIdentityState.EXACT:
            classification = RealityClassification.UNKNOWN
            reason = "Canonical identity is ambiguous or unsupported; no records were reconciled by title."
            confidence = RealityConfidence.UNKNOWN
            resolution = SafeResolution(
                code="review_identity_link",
                summary="Review and confirm an exact canonical provider link before reconciling these records.",
                target_work_identity=candidate.normalized_work_identity,
            )
        elif _has_inconsistent_evidence_identity(candidate):
            classification = RealityClassification.UNKNOWN
            reason = "Attributable evidence points to a different canonical or normalized work identity."
            confidence = RealityConfidence.UNKNOWN
            resolution = SafeResolution(
                code="review_identity_link",
                summary="Review the conflicting stable identities before reconciliation.",
                target_work_identity=candidate.normalized_work_identity,
            )
        elif _has_unlinked_cross_provider_evidence(candidate):
            classification = RealityClassification.UNKNOWN
            reason = "Cross-provider evidence lacks an exact link to the normalized work identity."
            confidence = RealityConfidence.UNKNOWN
            resolution = SafeResolution(
                code="review_identity_link",
                summary="Confirm the exact provider-to-work link; similar titles are not sufficient.",
                target_work_identity=candidate.normalized_work_identity,
            )
        elif _unreliable_evidence(evidence, evaluated_at):
            classification = RealityClassification.UNKNOWN
            reason = "Required evidence is missing, stale, unavailable, untrustworthy, or affected by clock skew."
            confidence = RealityConfidence.LOW
            resolution = SafeResolution(
                code="refresh_or_review_evidence",
                summary="Refresh or review the attributable evidence before drawing a conclusion.",
                target_work_identity=candidate.normalized_work_identity,
            )
        elif _has_conflicting_claims(evidence):
            classification = RealityClassification.POTENTIAL_MISMATCH
            reason = "Trustworthy, exactly linked providers report conflicting handled and open states."
            confidence = RealityConfidence.MEDIUM
            resolution = SafeResolution(
                code="review_mark_work_handled",
                summary="Review the preserved claims and, with a separate confirmation, propose marking the linked work handled.",
                target_work_identity=candidate.normalized_work_identity,
            )
        elif _handled_evidence(evidence):
            classification = RealityClassification.ALREADY_HANDLED
            reason = "Trustworthy attributable evidence reports that the work is already handled."
        elif waiting_confirmation is not None:
            classification = RealityClassification.WAITING
            reason = "An attributable user confirmation marks this reconciliation as waiting."
        else:
            classification, reason, confidence = _classify_temporal(
                candidate.temporal,
                evidence=evidence,
                evaluated_at=evaluated_at,
            )
            if classification == RealityClassification.UNKNOWN:
                resolution = SafeResolution(
                    code="review_missing_actionability",
                    summary="Review the missing timing or actionability evidence without inventing a date.",
                    target_work_identity=candidate.normalized_work_identity,
                )

        return RealityItem(
            reality_item_id=candidate.reconciliation_id,
            reconciliation_id=candidate.reconciliation_id,
            canonical_project_id=candidate.canonical_project_id,
            canonical_project_key=candidate.canonical_project_key,
            normalized_work_identity=candidate.normalized_work_identity,
            provider_identity=candidate.provider_identity,
            title=candidate.title,
            classification=classification,
            classification_reason=reason,
            temporal=candidate.temporal,
            identity_state=candidate.identity_state,
            ambiguity_candidates=candidate.possible_work_matches,
            confidence=confidence,
            evidence=evidence,
            evidence_version=evidence_version,
            proposed_safe_resolution=resolution,
        )


def _candidate_from_work(
    item: NormalizedWorkItem,
    *,
    canonical_project_id: str,
    canonical_project_key: str,
    dependency_evidence: Iterable[EvaluatedDependencyEvidence],
    changes: Iterable[ProviderChangeEvent],
    evaluated_at: datetime,
) -> RealityCandidate:
    work_identity = WorkIdentity(
        provider=item.provider,
        provider_record_id=item.provider_record_id,
    )
    provider_identity = ProviderRecordIdentity(
        provider=item.provider,
        provider_record_type="work_item",
        provider_record_id=item.provider_record_id,
        provider_reference=item.provider_reference,
        provider_url=item.provider_url,
    )
    raw_source_timestamp = item.updated_at or item.created_at
    source_timestamp = _aware_or_none(raw_source_timestamp)
    invalid_source_timestamp = (
        raw_source_timestamp is not None and source_timestamp is None
    )
    observed_state = item.status.value
    evidence: list[RealityEvidence] = [
        RealityEvidence(
            evidence_id=_stable_evidence_id(
                "work_state", item.provider, item.provider_record_id, observed_state,
                source_timestamp.isoformat() if source_timestamp else "observed"
            ),
            evidence_type=RealityEvidenceType.WORK_STATE,
            canonical_project_id=canonical_project_id,
            normalized_work_identity=work_identity,
            provider_identity=provider_identity,
            claim=observed_state,
            observed_state=observed_state,
            source_timestamp=source_timestamp,
            observed_at=evaluated_at,
            freshness=(
                RealityFreshness.UNKNOWN
                if invalid_source_timestamp
                else RealityFreshness.FRESH
            ),
            summary=f"{item.provider} reports this work as {observed_state}.",
            metadata={
                "original_provider_status": item.original_provider_status,
                "is_executable": item.is_executable,
                "is_blocked": item.is_blocked,
                "source_timestamp_invalid": invalid_source_timestamp,
            },
        )
    ]
    matching_dependencies = [
        dependency
        for dependency in dependency_evidence
        if dependency.blocked_work.provider == item.provider
        and dependency.blocked_work.provider_record_id == item.provider_record_id
        and dependency.evaluation_state == DependencyEvaluationState.ACTIVE
    ]
    for dependency in matching_dependencies:
        evidence.append(
            RealityEvidence(
                evidence_id=_stable_evidence_id(
                    "waiting", item.provider, item.provider_record_id,
                    dependency.blocking_work.provider_record_id
                ),
                evidence_type=RealityEvidenceType.WAITING_STATE,
                canonical_project_id=canonical_project_id,
                normalized_work_identity=work_identity,
                provider_identity=provider_identity,
                claim="waiting",
                observed_state="waiting",
                observed_at=evaluated_at,
                summary=dependency.explanation,
                metadata={
                    "blocking_provider": dependency.blocking_work.provider,
                    "blocking_provider_record_id": dependency.blocking_work.provider_record_id,
                },
            )
        )
    for change in changes:
        evidence.append(
            RealityEvidence(
                evidence_id=f"provider_change:{change.id}",
                evidence_type=RealityEvidenceType.PROVIDER_CHANGE,
                canonical_project_id=canonical_project_id,
                normalized_work_identity=work_identity,
                provider_identity=provider_identity,
                claim=str(change.after) if change.after is not None else None,
                observed_state=change.category.value,
                source_timestamp=change.effective_at,
                observed_at=change.observed_at,
                summary=f"Provider change: {change.category.value.replace('_', ' ')}.",
                metadata={
                    "change_event_id": change.id,
                    "before": change.before,
                    "after": change.after,
                    "time_basis": change.time_basis.value,
                },
            )
        )

    is_open = item.status == WorkStatus.OPEN
    action_possible = is_open and item.is_executable and not item.is_blocked and not matching_dependencies
    due_at = _aware_or_none(item.due_at)
    action_useful: bool | None = None
    if item.status != WorkStatus.OPEN:
        action_useful = False
    elif due_at is not None:
        action_useful = due_at <= evaluated_at
    elif item.due_date is not None:
        action_useful = item.due_date <= evaluated_at.date()
    if item.due_at is not None and due_at is None:
        evidence.append(
            RealityEvidence(
                evidence_id=_stable_evidence_id(
                    "invalid_due_time", item.provider, item.provider_record_id
                ),
                evidence_type=RealityEvidenceType.TEMPORAL_BOUNDARY,
                canonical_project_id=canonical_project_id,
                normalized_work_identity=work_identity,
                provider_identity=provider_identity,
                claim="unknown",
                observed_state="invalid_due_time",
                observed_at=evaluated_at,
                freshness=RealityFreshness.UNKNOWN,
                trustworthy=False,
                summary="The provider supplied a due timestamp without timezone information.",
            )
        )
    temporal = TemporalActionability(
        due_date=item.due_date,
        due_at=due_at,
        action_possible_now=action_possible,
        action_useful_now=action_useful,
    )
    reconciliation_id = _stable_reconciliation_id(
        canonical_project_id, item.provider, item.provider_record_id
    )
    return RealityCandidate(
        reconciliation_id=reconciliation_id,
        canonical_project_id=canonical_project_id,
        canonical_project_key=canonical_project_key,
        normalized_work_identity=work_identity,
        title=item.title,
        provider_identity=provider_identity,
        evidence=tuple(evidence),
        temporal=temporal,
    )


def _classify_temporal(
    temporal: TemporalActionability,
    *,
    evidence: tuple[RealityEvidence, ...],
    evaluated_at: datetime,
) -> tuple[RealityClassification, str, RealityConfidence]:
    waiting_claim = any(
        item.evidence_type in CURRENT_STATE_EVIDENCE_TYPES
        and _claim_value(item) == "waiting"
        for item in evidence
    )
    overdue = bool(
        (temporal.hard_deadline is not None and temporal.hard_deadline < evaluated_at)
        or (temporal.due_at is not None and temporal.due_at < evaluated_at)
        or (temporal.due_date is not None and temporal.due_date < evaluated_at.date())
    )
    due_today = bool(
        (temporal.due_at is not None and temporal.due_at.date() == evaluated_at.date())
        or temporal.due_date == evaluated_at.date()
    )
    preparation_now = bool(
        temporal.preparation_window_start is not None
        and temporal.preparation_window_start <= evaluated_at
        and (
            temporal.hard_deadline is None
            or temporal.hard_deadline > evaluated_at
        )
    )
    if (
        temporal.action_possible_now is True
        and temporal.action_useful_now is not False
        and (overdue or due_today)
    ):
        return (
            RealityClassification.NEEDS_ACTION,
            "An open executable obligation is overdue or due today and remains actionable now.",
            RealityConfidence.HIGH,
        )
    if (
        preparation_now
        and temporal.action_possible_now is not False
        and temporal.action_useful_now is not False
    ):
        return (
            RealityClassification.NEEDS_ACTION,
            "The explicit preparation window has begun, so preparation is useful now while the future deadline remains separate.",
            RealityConfidence.HIGH,
        )
    if temporal.waiting_until is not None and temporal.waiting_until > evaluated_at:
        return (
            RealityClassification.WAITING,
            "The explicit waiting boundary has not passed.",
            RealityConfidence.HIGH,
        )
    if waiting_claim and temporal.action_possible_now is not True:
        return (
            RealityClassification.WAITING,
            "Trustworthy evidence says the work is waiting and no independent actionable condition exists.",
            RealityConfidence.HIGH,
        )
    upcoming_boundary = next(
        (
            value
            for value in (
                temporal.earliest_useful_action_at,
                temporal.preparation_window_start,
            )
            if value is not None and value > evaluated_at
        ),
        None,
    )
    if upcoming_boundary is not None:
        return (
            RealityClassification.UPCOMING_NOT_ACTIONABLE,
            "The earliest explicit useful-action or preparation boundary is still in the future.",
            RealityConfidence.HIGH,
        )
    if temporal.action_possible_now is False and temporal.action_useful_now is False:
        return (
            RealityClassification.NO_MEANINGFUL_CHANGE,
            "Complete explicit actionability evidence says no action is possible or useful now.",
            RealityConfidence.HIGH,
        )
    return (
        RealityClassification.UNKNOWN,
        "The available evidence does not establish when action is useful; no date or negative conclusion was invented.",
        RealityConfidence.UNKNOWN,
    )


def _overall_classification(
    items: list[RealityItem], *, complete_evidence: bool
) -> RealityClassification:
    priority = (
        RealityClassification.NEEDS_ACTION,
        RealityClassification.POTENTIAL_MISMATCH,
        RealityClassification.WAITING,
        RealityClassification.UNKNOWN,
        RealityClassification.UPCOMING_NOT_ACTIONABLE,
    )
    for classification in priority:
        if any(item.classification == classification for item in items):
            return classification
    if complete_evidence:
        return RealityClassification.NO_MEANINGFUL_CHANGE
    return RealityClassification.UNKNOWN


def _has_conflicting_claims(evidence: Iterable[RealityEvidence]) -> bool:
    claims = {
        _claim_value(item)
        for item in evidence
        if item.evidence_type in CURRENT_STATE_EVIDENCE_TYPES
    }
    return bool(claims & HANDLED_CLAIMS and claims & OPEN_CLAIMS)


def _handled_evidence(evidence: Iterable[RealityEvidence]) -> bool:
    claims = {
        _claim_value(item)
        for item in evidence
        if item.evidence_type in CURRENT_STATE_EVIDENCE_TYPES
    }
    return bool(claims & HANDLED_CLAIMS) and not bool(claims & OPEN_CLAIMS)


def _claim_value(evidence: RealityEvidence) -> str:
    return str(evidence.claim or evidence.observed_state or "").strip().lower()


def _has_unlinked_cross_provider_evidence(candidate: RealityCandidate) -> bool:
    work = candidate.normalized_work_identity
    if work is None:
        return False
    for evidence in candidate.evidence:
        if evidence.provider_identity.provider == work.provider:
            continue
        if evidence.linked_work_identity != work:
            return True
    return False


def _has_inconsistent_evidence_identity(candidate: RealityCandidate) -> bool:
    work = candidate.normalized_work_identity
    for evidence in candidate.evidence:
        if (
            evidence.canonical_project_id is not None
            and evidence.canonical_project_id != candidate.canonical_project_id
        ):
            return True
        if (
            work is not None
            and evidence.normalized_work_identity is not None
            and evidence.normalized_work_identity != work
        ):
            return True
        if (
            work is not None
            and evidence.linked_work_identity is not None
            and evidence.linked_work_identity != work
        ):
            return True
    return False


def _unreliable_evidence(
    evidence: Iterable[RealityEvidence], evaluated_at: datetime
) -> bool:
    for item in evidence:
        if (
            item.availability
            not in {RealityAvailability.AVAILABLE, RealityAvailability.NOT_APPLICABLE}
            or item.freshness != RealityFreshness.FRESH
            or not item.trustworthy
            or item.observed_at > evaluated_at + FUTURE_CLOCK_SKEW_TOLERANCE
            or (
                item.source_timestamp is not None
                and item.evidence_type != RealityEvidenceType.TEMPORAL_BOUNDARY
                and item.source_timestamp
                > evaluated_at + FUTURE_CLOCK_SKEW_TOLERANCE
            )
        ):
            return True
    return False


def _item_order_key(item: RealityItem) -> tuple[Any, ...]:
    rank = {
        RealityClassification.NEEDS_ACTION: 0,
        RealityClassification.POTENTIAL_MISMATCH: 1,
        RealityClassification.WAITING: 2,
        RealityClassification.UNKNOWN: 3,
        RealityClassification.UPCOMING_NOT_ACTIONABLE: 4,
        RealityClassification.ALREADY_HANDLED: 5,
        RealityClassification.NO_MEANINGFUL_CHANGE: 6,
    }
    due = item.temporal.due_at or item.temporal.hard_deadline
    return (
        rank[item.classification],
        due.isoformat() if due is not None else "9999",
        item.normalized_work_identity.provider if item.normalized_work_identity else "",
        item.normalized_work_identity.provider_record_id if item.normalized_work_identity else "",
        item.reality_item_id,
    )


def _temporal_evidence(
    candidate: RealityCandidate, evaluated_at: datetime
) -> tuple[RealityEvidence, ...]:
    temporal = candidate.temporal
    identity = candidate.provider_identity or ProviderRecordIdentity(
        provider="pcos",
        provider_record_type="reconciliation",
        provider_record_id=candidate.reconciliation_id,
    )
    fields = (
        ("due_at", temporal.due_at),
        ("earliest_useful_action_at", temporal.earliest_useful_action_at),
        ("waiting_until", temporal.waiting_until),
        ("preparation_window_start", temporal.preparation_window_start),
        ("hard_deadline", temporal.hard_deadline),
    )
    result: list[RealityEvidence] = []
    for name, value in fields:
        if value is None:
            continue
        result.append(
            RealityEvidence(
                evidence_id=_stable_evidence_id(
                    "temporal", candidate.reconciliation_id, name, value.isoformat()
                ),
                evidence_type=RealityEvidenceType.TEMPORAL_BOUNDARY,
                canonical_project_id=candidate.canonical_project_id,
                normalized_work_identity=candidate.normalized_work_identity,
                provider_identity=identity,
                linked_work_identity=(
                    candidate.normalized_work_identity
                    if identity.provider
                    != (
                        candidate.normalized_work_identity.provider
                        if candidate.normalized_work_identity
                        else identity.provider
                    )
                    else None
                ),
                claim=name,
                observed_state=value.isoformat(),
                source_timestamp=value,
                observed_at=evaluated_at,
                summary=f"Explicit temporal boundary: {name}.",
                metadata={"field": name, "value": value.isoformat()},
            )
        )
    if temporal.due_date is not None:
        result.append(
            RealityEvidence(
                evidence_id=_stable_evidence_id(
                    "temporal",
                    candidate.reconciliation_id,
                    "due_date",
                    temporal.due_date.isoformat(),
                ),
                evidence_type=RealityEvidenceType.TEMPORAL_BOUNDARY,
                canonical_project_id=candidate.canonical_project_id,
                normalized_work_identity=candidate.normalized_work_identity,
                provider_identity=identity,
                claim="due_date",
                observed_state=temporal.due_date.isoformat(),
                observed_at=evaluated_at,
                summary="Explicit date-only due boundary.",
                metadata={"field": "due_date", "value": temporal.due_date.isoformat()},
            )
        )
    if (
        temporal.action_possible_now is not None
        or temporal.action_useful_now is not None
    ):
        result.append(
            RealityEvidence(
                evidence_id=_stable_evidence_id(
                    "temporal",
                    candidate.reconciliation_id,
                    "actionability_flags",
                    str(temporal.action_possible_now),
                    str(temporal.action_useful_now),
                ),
                evidence_type=RealityEvidenceType.TEMPORAL_BOUNDARY,
                canonical_project_id=candidate.canonical_project_id,
                normalized_work_identity=candidate.normalized_work_identity,
                provider_identity=identity,
                claim="actionability_flags",
                observed_state="explicit",
                observed_at=evaluated_at,
                summary="Explicit current actionability flags.",
                metadata={
                    "action_possible_now": temporal.action_possible_now,
                    "action_useful_now": temporal.action_useful_now,
                },
            )
        )
    return tuple(result)


def _evidence_order_key(item: RealityEvidence) -> tuple[Any, ...]:
    timestamp = item.source_timestamp or item.observed_at
    return (-timestamp.timestamp(), item.evidence_id)


def _evidence_version(evidence: Iterable[RealityEvidence]) -> str:
    payload = [
        {
            "schema_version": item.schema_version,
            "evidence_id": item.evidence_id,
            "evidence_type": item.evidence_type.value,
            "canonical_project_id": item.canonical_project_id,
            "normalized_work_identity": (
                item.normalized_work_identity.model_dump(mode="json")
                if item.normalized_work_identity
                else None
            ),
            "provider_identity": item.provider_identity.model_dump(mode="json"),
            "linked_work_identity": (
                item.linked_work_identity.model_dump(mode="json")
                if item.linked_work_identity
                else None
            ),
            "claim": item.claim,
            "observed_state": item.observed_state,
            "source_timestamp": (
                item.source_timestamp.isoformat() if item.source_timestamp else None
            ),
            "freshness": item.freshness.value,
            "availability": item.availability.value,
            "trustworthy": item.trustworthy,
            "metadata": item.metadata,
        }
        for item in sorted(evidence, key=lambda value: value.evidence_id)
    ]
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _stable_reconciliation_id(
    canonical_project_id: str, provider: str, provider_record_id: str
) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"pcos-reality:{canonical_project_id}:{provider}:{provider_record_id}",
        )
    )


def _stable_evidence_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"reality-evidence:{digest}"


def _confirmation_from_row(row) -> RealityConfirmation:
    return RealityConfirmation(
        confirmation_id=row["id"],
        reconciliation_id=row["reconciliation_id"],
        canonical_project_id=row["canonical_project_id"],
        selected_resolution_code=row["selected_resolution_code"],
        outcome=row["outcome"],
        confirming_actor=row["confirming_actor"],
        confirmed_at=datetime.fromisoformat(row["confirmed_at"]),
        evidence_references=tuple(json.loads(row["evidence_references_json"])),
        evidence_version=row["evidence_version"],
        idempotency_key=row["idempotency_key"],
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _validate_safe_metadata(metadata: dict[str, Any]) -> None:
    forbidden = {
        "access_token",
        "authorization",
        "email_body",
        "password",
        "raw_email",
        "raw_payload",
        "refresh_token",
        "secret",
        "token",
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).strip().lower()
                if normalized in forbidden:
                    raise ValueError(
                        f"reality evidence cannot store sensitive field {normalized}"
                    )
                walk(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                walk(nested)

    walk(metadata)


def _aware_or_none(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


reality_confirmation_repository = RealityConfirmationRepository()
reality_reconciliation_service = RealityReconciliationService()
