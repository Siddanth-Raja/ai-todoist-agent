from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import json
from typing import Any, Iterable, Literal, Protocol
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .reality_reconciliation import (
    ConfirmationOutcome,
    EffectiveRealityCorrection,
    ProviderRecordIdentity,
    RealityClassification,
    RealityConfidence,
    RealityEvidence,
    RealityEvidenceType,
    RealityFactType,
    RealityFreshness,
    RealityItem,
    TemporalActionability,
    reality_confirmation_repository,
)
from .storage import database_connection


MORNING_CORRECTION_SCHEMA_VERSION = 1
PREVIEW_TTL = timedelta(minutes=10)
SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "raw_payload",
    "email_body",
}


class MorningCorrectionType(StrEnum):
    ALREADY_DONE = "already_done"
    NOT_TODAY = "not_today"
    WRONG_CONTEXT = "wrong_context"
    WAITING_ON_SOMEONE = "waiting_on_someone"
    SNOOZE = "snooze"


class MorningCorrectionStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVERSED = "reversed"


class ProviderPreviewStatus(StrEnum):
    READY = "ready"
    UNSUPPORTED = "unsupported"
    CONFIRMED = "confirmed"
    STALE = "stale"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class MorningCorrectionParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    note: str | None = Field(default=None, max_length=1000)
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    review_at: datetime | None = None
    waiting_until: datetime | None = None
    snooze_until: datetime | None = None
    disputed_context: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_times(self) -> "MorningCorrectionParameters":
        for name in (
            "effective_at",
            "expires_at",
            "review_at",
            "waiting_until",
            "snooze_until",
        ):
            value = getattr(self, name)
            if value is not None and value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        return self


class MorningCorrectionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    synthesis_id: str = Field(..., min_length=1, max_length=240)
    evaluated_at: datetime
    statement_id: str = Field(..., min_length=1, max_length=240)
    evidence_version: str = Field(..., min_length=1, max_length=128)
    correction_type: MorningCorrectionType
    parameters: MorningCorrectionParameters = Field(
        default_factory=MorningCorrectionParameters
    )
    correcting_actor: str = Field(..., min_length=1, max_length=240)
    idempotency_key: str = Field(..., min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_actor(self) -> "MorningCorrectionRequest":
        _require_aware(self.evaluated_at, "evaluated_at")
        if "@" in self.correcting_actor:
            raise ValueError("correcting_actor must be a stable actor identity, not a raw email")
        _validate_safe_value(self.parameters.model_dump(mode="json"))
        return self


class MorningCorrection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = MORNING_CORRECTION_SCHEMA_VERSION
    correction_id: str
    correction_type: MorningCorrectionType
    statement_id: str
    reconciliation_id: str | None
    reality_item_id: str | None
    synthesis_id: str
    canonical_project_id: str | None
    canonical_project_key: str | None
    work_provider: str | None
    work_provider_record_id: str | None
    source_provider: str | None
    source_provider_record_type: str | None
    source_provider_record_id: str | None
    evidence_references: tuple[str, ...]
    evidence_version: str
    prior_classification: RealityClassification
    parameters: MorningCorrectionParameters
    correcting_actor: str
    attribution: Literal["morning_brief_user_correction"] = (
        "morning_brief_user_correction"
    )
    created_at: datetime
    effective_at: datetime
    expires_at: datetime | None
    review_at: datetime | None
    status: MorningCorrectionStatus
    supersedes_correction_id: str | None
    reversed_at: datetime | None
    reversed_by_actor: str | None
    idempotency_key: str


class MorningCorrectionUndoRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reversing_actor: str = Field(..., min_length=1, max_length=240)
    idempotency_key: str = Field(..., min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_actor(self) -> "MorningCorrectionUndoRequest":
        if "@" in self.reversing_actor:
            raise ValueError("reversing_actor must be a stable actor identity, not a raw email")
        return self


class ProviderTargetSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any
    revision: str | None = Field(default=None, max_length=500)


class ProviderMutationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["succeeded", "failed", "uncertain"]
    confirmed_value: Any = None
    result_reference: str | None = Field(default=None, max_length=1000)
    diagnostic: str | None = Field(default=None, max_length=1000)


class MorningProviderAdapter(Protocol):
    def inspect(
        self,
        *,
        provider_record_type: str,
        provider_record_id: str,
        field_name: str,
    ) -> ProviderTargetSnapshot: ...

    def mutate(
        self,
        *,
        provider_record_type: str,
        provider_record_id: str,
        field_name: str,
        previous_value: Any,
        proposed_value: Any,
        provider_revision: str | None,
        idempotency_key: str,
    ) -> ProviderMutationResult: ...


class ProviderPreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    synthesis_id: str = Field(..., min_length=1, max_length=240)
    evaluated_at: datetime
    statement_id: str = Field(..., min_length=1, max_length=240)
    evidence_version: str = Field(..., min_length=1, max_length=128)
    requested_by_actor: str = Field(..., min_length=1, max_length=240)
    idempotency_key: str = Field(..., min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_actor(self) -> "ProviderPreviewRequest":
        _require_aware(self.evaluated_at, "evaluated_at")
        if "@" in self.requested_by_actor:
            raise ValueError("requested_by_actor must be a stable actor identity")
        return self


class ProviderPreviewConfirmationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    preview_id: str = Field(..., min_length=1, max_length=128)
    evidence_version: str = Field(..., min_length=1, max_length=128)
    provider: str = Field(..., min_length=1, max_length=80)
    provider_record_type: str = Field(..., min_length=1, max_length=80)
    provider_record_id: str = Field(..., min_length=1, max_length=240)
    field_name: str = Field(..., min_length=1, max_length=120)
    previous_value: Any
    proposed_value: Any
    confirming_actor: str = Field(..., min_length=1, max_length=240)
    idempotency_key: str = Field(..., min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_contract(self) -> "ProviderPreviewConfirmationRequest":
        if "@" in self.confirming_actor:
            raise ValueError("confirming_actor must be a stable actor identity")
        _validate_safe_value(self.previous_value)
        _validate_safe_value(self.proposed_value)
        return self


class ProviderMutationPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = MORNING_CORRECTION_SCHEMA_VERSION
    preview_id: str
    statement_id: str
    synthesis_id: str
    evidence_version: str
    provider: str
    provider_record_type: str
    provider_record_id: str
    field_name: str
    previous_value: Any = None
    proposed_value: Any
    provider_revision: str | None
    requested_by_actor: str
    created_at: datetime
    expires_at: datetime
    status: ProviderPreviewStatus
    diagnostic: str | None
    confirmed_by_actor: str | None
    confirmed_at: datetime | None
    result_reference: str | None
    request_idempotency_key: str


class MorningCorrectionRepository:
    def create(
        self,
        request: MorningCorrectionRequest,
        *,
        statement: Any,
        created_at: datetime,
    ) -> MorningCorrection:
        _require_aware(created_at, "created_at")
        parameters, effective_at, expires_at, review_at = _normalized_parameters(
            request.correction_type,
            request.parameters,
            created_at,
        )
        correction_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"pcos-morning-correction:{request.idempotency_key}",
            )
        )
        provider_identity = _primary_provider_identity(statement)
        work_identity = getattr(statement, "linked_work_identity", None)
        candidate = MorningCorrection(
            correction_id=correction_id,
            correction_type=request.correction_type,
            statement_id=request.statement_id,
            reconciliation_id=getattr(statement, "source_reconciliation_id", None),
            reality_item_id=getattr(statement, "source_reality_item_id", None),
            synthesis_id=request.synthesis_id,
            canonical_project_id=getattr(statement, "canonical_project_id", None),
            canonical_project_key=getattr(statement, "canonical_project_key", None),
            work_provider=getattr(work_identity, "provider", None),
            work_provider_record_id=getattr(work_identity, "provider_record_id", None),
            source_provider=getattr(provider_identity, "provider", None),
            source_provider_record_type=getattr(
                provider_identity, "provider_record_type", None
            ),
            source_provider_record_id=getattr(
                provider_identity, "provider_record_id", None
            ),
            evidence_references=tuple(statement.source_evidence_references),
            evidence_version=request.evidence_version,
            prior_classification=statement.classification,
            parameters=parameters,
            correcting_actor=request.correcting_actor,
            created_at=created_at,
            effective_at=effective_at,
            expires_at=expires_at,
            review_at=review_at,
            status=MorningCorrectionStatus.ACTIVE,
            supersedes_correction_id=None,
            reversed_at=None,
            reversed_by_actor=None,
            idempotency_key=request.idempotency_key,
        )
        with database_connection() as connection:
            existing = connection.execute(
                "SELECT * FROM morning_corrections WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = _correction_from_row(existing)
                if not _correction_request_matches_stored(
                    request,
                    statement=statement,
                    stored=stored,
                ):
                    raise ValueError("idempotency key already belongs to another correction")
                return stored
            identity_clause = (
                "reconciliation_id = ?"
                if candidate.reconciliation_id
                else "statement_id = ?"
            )
            identity_value = candidate.reconciliation_id or candidate.statement_id
            previous = connection.execute(
                f"""
                SELECT id FROM morning_corrections
                WHERE {identity_clause} AND status = 'active'
                ORDER BY created_at DESC, id ASC LIMIT 1
                """,
                (identity_value,),
            ).fetchone()
            supersedes = previous["id"] if previous else None
            if supersedes:
                connection.execute(
                    "UPDATE morning_corrections SET status = 'superseded' WHERE id = ?",
                    (supersedes,),
                )
            candidate = candidate.model_copy(
                update={"supersedes_correction_id": supersedes}
            )
            connection.execute(
                """
                INSERT INTO morning_corrections (
                    id, correction_type, statement_id, reconciliation_id,
                    reality_item_id, synthesis_id, canonical_project_id,
                    canonical_project_key, work_provider, work_provider_record_id,
                    source_provider, source_provider_record_type,
                    source_provider_record_id, evidence_references_json,
                    evidence_version, prior_classification, parameters_json,
                    correcting_actor, attribution, created_at, effective_at,
                    expires_at, review_at, status, supersedes_correction_id,
                    reversed_at, reversed_by_actor, reversal_idempotency_key,
                    idempotency_key, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    candidate.correction_id,
                    candidate.correction_type.value,
                    candidate.statement_id,
                    candidate.reconciliation_id,
                    candidate.reality_item_id,
                    candidate.synthesis_id,
                    candidate.canonical_project_id,
                    candidate.canonical_project_key,
                    candidate.work_provider,
                    candidate.work_provider_record_id,
                    candidate.source_provider,
                    candidate.source_provider_record_type,
                    candidate.source_provider_record_id,
                    _canonical_json(list(candidate.evidence_references)),
                    candidate.evidence_version,
                    candidate.prior_classification.value,
                    _canonical_json(candidate.parameters.model_dump(mode="json")),
                    candidate.correcting_actor,
                    candidate.attribution,
                    candidate.created_at.isoformat(),
                    candidate.effective_at.isoformat(),
                    candidate.expires_at.isoformat() if candidate.expires_at else None,
                    candidate.review_at.isoformat() if candidate.review_at else None,
                    candidate.status.value,
                    candidate.supersedes_correction_id,
                    candidate.idempotency_key,
                    MORNING_CORRECTION_SCHEMA_VERSION,
                ),
            )
        return candidate

    def list(
        self,
        *,
        statement_id: str | None = None,
        canonical_project_id: str | None = None,
    ) -> tuple[MorningCorrection, ...]:
        clauses: list[str] = []
        values: list[Any] = []
        if statement_id:
            clauses.append("statement_id = ?")
            values.append(statement_id)
        if canonical_project_id:
            clauses.append("canonical_project_id = ?")
            values.append(canonical_project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with database_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM morning_corrections {where}
                ORDER BY created_at DESC, id ASC
                LIMIT 200
                """,
                tuple(values),
            ).fetchall()
        return tuple(_correction_from_row(row) for row in rows)

    def get(self, correction_id: str) -> MorningCorrection | None:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT * FROM morning_corrections WHERE id = ?",
                (correction_id,),
            ).fetchone()
        return _correction_from_row(row) if row is not None else None

    def list_active_for_reconciliations(
        self,
        reconciliation_ids: Iterable[str],
        *,
        evaluated_at: datetime,
    ) -> tuple[MorningCorrection, ...]:
        ids = tuple(dict.fromkeys(item for item in reconciliation_ids if item))
        if not ids:
            return ()
        placeholders = ",".join("?" for _ in ids)
        with database_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM morning_corrections
                WHERE reconciliation_id IN ({placeholders})
                  AND status = 'active'
                  AND effective_at <= ?
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC, id ASC
                """,
                (*ids, evaluated_at.isoformat(), evaluated_at.isoformat()),
            ).fetchall()
        return tuple(_correction_from_row(row) for row in rows)

    def reverse(
        self,
        correction_id: str,
        request: MorningCorrectionUndoRequest,
        *,
        reversed_at: datetime,
    ) -> MorningCorrection:
        _require_aware(reversed_at, "reversed_at")
        with database_connection() as connection:
            row = connection.execute(
                "SELECT * FROM morning_corrections WHERE id = ?",
                (correction_id,),
            ).fetchone()
            if row is None:
                raise ValueError("morning correction not found")
            stored = _correction_from_row(row)
            if stored.status == MorningCorrectionStatus.REVERSED:
                if (
                    row["reversal_idempotency_key"] != request.idempotency_key
                    or stored.reversed_by_actor != request.reversing_actor
                ):
                    raise ValueError("correction was already reversed by another request")
                return stored
            if stored.status != MorningCorrectionStatus.ACTIVE:
                raise ValueError("only an active PCOS correction can be reversed")
            connection.execute(
                """
                UPDATE morning_corrections
                SET status = 'reversed', reversed_at = ?, reversed_by_actor = ?,
                    reversal_idempotency_key = ?
                WHERE id = ? AND status = 'active'
                """,
                (
                    reversed_at.isoformat(),
                    request.reversing_actor,
                    request.idempotency_key,
                    correction_id,
                ),
            )
        if stored.correction_type == MorningCorrectionType.ALREADY_DONE:
            _reverse_reality_confirmation(
                stored,
                reversed_at=reversed_at,
                reversed_by_actor=request.reversing_actor,
                idempotency_key=f"morning-correction-undo:{request.idempotency_key}",
            )
        return self.list(statement_id=stored.statement_id)[0]


class MorningCorrectionService:
    def __init__(self, repository: MorningCorrectionRepository | None = None):
        self.repository = repository or MorningCorrectionRepository()

    def create(
        self,
        request: MorningCorrectionRequest,
        *,
        synthesis: Any,
        created_at: datetime,
    ) -> MorningCorrection:
        if synthesis.synthesis_id != request.synthesis_id:
            raise ValueError("morning synthesis changed; refresh before correcting")
        statement = _find_statement(synthesis, request.statement_id)
        if statement is None:
            raise ValueError("morning statement not found")
        if statement.evidence_version != request.evidence_version:
            raise ValueError("morning statement evidence changed; refresh before correcting")
        if statement.source_reconciliation_id is None:
            raise ValueError("this statement does not support a durable correction")
        record = self.repository.create(request, statement=statement, created_at=created_at)
        if record.supersedes_correction_id:
            superseded = self.repository.get(record.supersedes_correction_id)
            if (
                superseded is not None
                and superseded.correction_type == MorningCorrectionType.ALREADY_DONE
            ):
                _reverse_reality_confirmation(
                    superseded,
                    reversed_at=record.effective_at,
                    reversed_by_actor=request.correcting_actor,
                    idempotency_key=f"morning-correction-superseded:{record.idempotency_key}",
                )
        if request.correction_type == MorningCorrectionType.ALREADY_DONE:
            reality_confirmation_repository.confirm(
                reconciliation_id=statement.source_reconciliation_id,
                canonical_project_id=statement.canonical_project_id,
                selected_resolution_code="morning_already_done",
                outcome=ConfirmationOutcome.HANDLED,
                confirming_actor=request.correcting_actor,
                confirmed_at=record.effective_at,
                evidence_references=record.evidence_references,
                evidence_version=record.evidence_version,
                idempotency_key=f"morning-correction:{record.idempotency_key}",
            )
        return record

    def apply_to_reality_items(
        self,
        items: Iterable[RealityItem],
        *,
        evaluated_at: datetime,
        include_snoozed: bool = False,
    ) -> tuple[RealityItem, ...]:
        source = tuple(items)
        corrections = self.repository.list_active_for_reconciliations(
            (item.reconciliation_id for item in source),
            evaluated_at=evaluated_at,
        )
        latest = {
            item.reconciliation_id: item
            for item in reversed(corrections)
            if item.reconciliation_id
        }
        result: list[RealityItem] = []
        for item in source:
            correction = latest.get(item.reconciliation_id)
            if correction is None or correction.evidence_version != item.evidence_version:
                result.append(item)
                continue
            if (
                item.effective_correction is not None
                and item.effective_correction.correction_id == correction.correction_id
            ):
                if (
                    correction.correction_type == MorningCorrectionType.SNOOZE
                    and not include_snoozed
                ):
                    continue
                result.append(item)
                continue
            if (
                correction.correction_type == MorningCorrectionType.SNOOZE
                and not include_snoozed
            ):
                continue
            result.append(_apply_correction(item, correction, evaluated_at))
        return tuple(result)


class MorningProviderReconciliationService:
    def __init__(
        self,
        *,
        adapters: dict[str, MorningProviderAdapter] | None = None,
    ) -> None:
        self.adapters = dict(adapters or {})

    def preview(
        self,
        request: ProviderPreviewRequest,
        *,
        synthesis: Any,
        created_at: datetime,
    ) -> ProviderMutationPreview:
        if synthesis.synthesis_id != request.synthesis_id:
            raise ValueError("morning synthesis changed; refresh before previewing")
        statement = _find_statement(synthesis, request.statement_id)
        if statement is None:
            raise ValueError("morning statement not found")
        if statement.evidence_version != request.evidence_version:
            raise ValueError("morning statement evidence changed; refresh before previewing")
        target = _mutation_target(statement)
        if target is None:
            raise ValueError("this statement has no exact provider work target")
        provider, record_type, record_id = target
        adapter = self.adapters.get(provider)
        status = ProviderPreviewStatus.UNSUPPORTED
        diagnostic = (
            f"{provider} completion is not registered for Morning Brief; no provider mutation is available."
        )
        previous_value: Any = None
        revision = None
        if adapter is not None:
            try:
                snapshot = adapter.inspect(
                    provider_record_type=record_type,
                    provider_record_id=record_id,
                    field_name="status",
                )
            except Exception:
                status = ProviderPreviewStatus.FAILED
                diagnostic = "The exact provider target could not be inspected; no mutation occurred."
            else:
                previous_value = snapshot.value
                revision = snapshot.revision
                status = ProviderPreviewStatus.READY
                diagnostic = None
        preview = ProviderMutationPreview(
            preview_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"pcos-morning-provider-preview:{request.idempotency_key}",
                )
            ),
            statement_id=request.statement_id,
            synthesis_id=request.synthesis_id,
            evidence_version=request.evidence_version,
            provider=provider,
            provider_record_type=record_type,
            provider_record_id=record_id,
            field_name="status",
            previous_value=previous_value,
            proposed_value="completed",
            provider_revision=revision,
            requested_by_actor=request.requested_by_actor,
            created_at=created_at,
            expires_at=created_at + PREVIEW_TTL,
            status=status,
            diagnostic=diagnostic,
            confirmed_by_actor=None,
            confirmed_at=None,
            result_reference=None,
            request_idempotency_key=request.idempotency_key,
        )
        return self._store_preview(preview)

    def confirm(
        self,
        request: ProviderPreviewConfirmationRequest,
        *,
        confirmed_at: datetime,
    ) -> ProviderMutationPreview:
        prior = self._get_preview_by_confirmation_key(request.idempotency_key)
        if prior is not None:
            if not _confirmation_matches_preview(request, prior):
                raise ValueError(
                    "confirmation idempotency key belongs to another exact confirmation"
                )
            return prior
        preview = self._get_preview(request.preview_id)
        if preview is None:
            raise ValueError("provider mutation preview not found")
        if preview.status != ProviderPreviewStatus.READY:
            raise ValueError("provider mutation preview is not ready for confirmation")
        if confirmed_at >= preview.expires_at:
            return self._finish(
                preview,
                status=ProviderPreviewStatus.STALE,
                confirmed_at=confirmed_at,
                idempotency_key=request.idempotency_key,
                confirmed_by_actor=request.confirming_actor,
                diagnostic="The exact provider preview expired; request a new preview.",
            )
        exact = (
            request.evidence_version == preview.evidence_version
            and request.provider == preview.provider
            and request.provider_record_type == preview.provider_record_type
            and request.provider_record_id == preview.provider_record_id
            and request.field_name == preview.field_name
            and _canonical_json(request.previous_value)
            == _canonical_json(preview.previous_value)
            and _canonical_json(request.proposed_value)
            == _canonical_json(preview.proposed_value)
        )
        if not exact:
            raise ValueError("confirmation does not match the exact provider preview")
        adapter = self.adapters.get(preview.provider)
        if adapter is None:
            raise ValueError("provider completion adapter is unavailable")
        try:
            current = adapter.inspect(
                provider_record_type=preview.provider_record_type,
                provider_record_id=preview.provider_record_id,
                field_name=preview.field_name,
            )
        except Exception:
            return self._finish(
                preview,
                status=ProviderPreviewStatus.FAILED,
                confirmed_at=confirmed_at,
                idempotency_key=request.idempotency_key,
                confirmed_by_actor=request.confirming_actor,
                diagnostic="Provider revalidation failed before mutation; no mutation was attempted.",
            )
        if (
            _canonical_json(current.value) != _canonical_json(preview.previous_value)
            or current.revision != preview.provider_revision
        ):
            return self._finish(
                preview,
                status=ProviderPreviewStatus.STALE,
                confirmed_at=confirmed_at,
                idempotency_key=request.idempotency_key,
                confirmed_by_actor=request.confirming_actor,
                diagnostic="Provider state changed after preview; request a new exact preview.",
            )
        try:
            result = adapter.mutate(
                provider_record_type=preview.provider_record_type,
                provider_record_id=preview.provider_record_id,
                field_name=preview.field_name,
                previous_value=preview.previous_value,
                proposed_value=preview.proposed_value,
                provider_revision=preview.provider_revision,
                idempotency_key=request.idempotency_key,
            )
        except Exception:
            return self._finish(
                preview,
                status=ProviderPreviewStatus.UNCERTAIN,
                confirmed_at=confirmed_at,
                idempotency_key=request.idempotency_key,
                confirmed_by_actor=request.confirming_actor,
                diagnostic="The provider mutation call did not return a trustworthy result; provider state must be re-read before retrying.",
            )
        status = ProviderPreviewStatus(result.status)
        if status == ProviderPreviewStatus.SUCCEEDED:
            try:
                verified = adapter.inspect(
                    provider_record_type=preview.provider_record_type,
                    provider_record_id=preview.provider_record_id,
                    field_name=preview.field_name,
                )
            except Exception:
                status = ProviderPreviewStatus.UNCERTAIN
                result = result.model_copy(
                    update={
                        "diagnostic": "Provider returned success but exact post-state verification failed."
                    }
                )
            else:
                if _canonical_json(verified.value) != _canonical_json(
                    preview.proposed_value
                ):
                    status = ProviderPreviewStatus.UNCERTAIN
                    result = result.model_copy(
                        update={
                            "diagnostic": "Provider returned success but exact post-state could not be verified."
                        }
                    )
        return self._finish(
            preview,
            status=status,
            confirmed_at=confirmed_at,
            idempotency_key=request.idempotency_key,
            confirmed_by_actor=request.confirming_actor,
            diagnostic=result.diagnostic,
            result_reference=result.result_reference,
        )

    def _store_preview(self, candidate: ProviderMutationPreview) -> ProviderMutationPreview:
        with database_connection() as connection:
            existing = connection.execute(
                "SELECT * FROM morning_provider_previews WHERE request_idempotency_key = ?",
                (candidate.request_idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = _preview_from_row(existing)
                if not _preview_request_matches_stored(candidate, stored):
                    raise ValueError("idempotency key already belongs to another preview")
                return stored
            connection.execute(
                """
                INSERT INTO morning_provider_previews (
                    id, statement_id, synthesis_id, evidence_version, provider,
                    provider_record_type, provider_record_id, field_name,
                    previous_value_json, proposed_value_json, provider_revision,
                    requested_by_actor, created_at, expires_at, status, diagnostic,
                    confirmation_idempotency_key, confirmed_by_actor,
                    confirmed_at, result_reference,
                    request_idempotency_key, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (
                    candidate.preview_id,
                    candidate.statement_id,
                    candidate.synthesis_id,
                    candidate.evidence_version,
                    candidate.provider,
                    candidate.provider_record_type,
                    candidate.provider_record_id,
                    candidate.field_name,
                    _canonical_json(candidate.previous_value),
                    _canonical_json(candidate.proposed_value),
                    candidate.provider_revision,
                    candidate.requested_by_actor,
                    candidate.created_at.isoformat(),
                    candidate.expires_at.isoformat(),
                    candidate.status.value,
                    candidate.diagnostic,
                    candidate.request_idempotency_key,
                    MORNING_CORRECTION_SCHEMA_VERSION,
                ),
            )
        return candidate

    def _get_preview(self, preview_id: str) -> ProviderMutationPreview | None:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT * FROM morning_provider_previews WHERE id = ?",
                (preview_id,),
            ).fetchone()
        return _preview_from_row(row) if row is not None else None

    def _get_preview_by_confirmation_key(
        self, idempotency_key: str
    ) -> ProviderMutationPreview | None:
        with database_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM morning_provider_previews
                WHERE confirmation_idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        return _preview_from_row(row) if row is not None else None

    def _finish(
        self,
        preview: ProviderMutationPreview,
        *,
        status: ProviderPreviewStatus,
        confirmed_at: datetime,
        idempotency_key: str,
        confirmed_by_actor: str,
        diagnostic: str | None,
        result_reference: str | None = None,
    ) -> ProviderMutationPreview:
        with database_connection() as connection:
            existing = connection.execute(
                """
                SELECT * FROM morning_provider_previews
                WHERE confirmation_idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return _preview_from_row(existing)
            connection.execute(
                """
                UPDATE morning_provider_previews
                SET status = ?, diagnostic = ?, confirmation_idempotency_key = ?,
                    confirmed_by_actor = ?, confirmed_at = ?, result_reference = ?
                WHERE id = ? AND status = 'ready'
                """,
                (
                    status.value,
                    diagnostic,
                    idempotency_key,
                    confirmed_by_actor,
                    confirmed_at.isoformat(),
                    result_reference,
                    preview.preview_id,
                ),
            )
        updated = self._get_preview(preview.preview_id)
        if updated is None:
            raise ValueError("provider mutation preview disappeared")
        return updated


def _apply_correction(
    item: RealityItem,
    correction: MorningCorrection,
    evaluated_at: datetime,
) -> RealityItem:
    classification = item.classification
    reason = item.classification_reason
    temporal = item.temporal
    confidence = item.confidence
    if correction.correction_type == MorningCorrectionType.ALREADY_DONE:
        classification = RealityClassification.ALREADY_HANDLED
        reason = "An attributable PCOS correction records that the item was already handled; provider evidence remains preserved."
    elif correction.correction_type == MorningCorrectionType.NOT_TODAY:
        classification = RealityClassification.UPCOMING_NOT_ACTIONABLE
        reason = "An attributable temporal choice protects this item until its review boundary; it is not proof of completion or irrelevance."
        temporal = temporal.model_copy(
            update={
                "earliest_useful_action_at": correction.review_at
                or correction.expires_at,
                "action_useful_now": False,
            }
        )
    elif correction.correction_type == MorningCorrectionType.WAITING_ON_SOMEONE:
        classification = RealityClassification.WAITING
        reason = "An attributable PCOS correction records a waiting state without changing provider fields or inventing a deadline."
        temporal = temporal.model_copy(
            update={
                "waiting_until": correction.parameters.waiting_until,
                "action_useful_now": False,
            }
        )
    elif correction.correction_type == MorningCorrectionType.WRONG_CONTEXT:
        classification = RealityClassification.UNKNOWN
        reason = "The presented association or interpretation is explicitly disputed; original evidence remains available for review."
        confidence = RealityConfidence.UNKNOWN
    elif correction.correction_type == MorningCorrectionType.SNOOZE:
        classification = RealityClassification.UPCOMING_NOT_ACTIONABLE
        reason = "An attributable PCOS snooze temporarily suppresses this item until its wake boundary without changing provider truth."
        temporal = temporal.model_copy(
            update={
                "earliest_useful_action_at": correction.expires_at,
                "action_useful_now": False,
            }
        )
    evidence = RealityEvidence(
        evidence_id=f"morning_correction:{correction.correction_id}",
        evidence_type=RealityEvidenceType.USER_CONFIRMATION,
        canonical_project_id=item.canonical_project_id,
        normalized_work_identity=item.normalized_work_identity,
        provider_identity=ProviderRecordIdentity(
            provider="pcos",
            provider_record_type="morning_correction",
            provider_record_id=correction.correction_id,
        ),
        linked_work_identity=item.normalized_work_identity,
        claim=correction.correction_type.value,
        observed_state=classification.value,
        source_timestamp=correction.effective_at,
        observed_at=correction.created_at,
        freshness=RealityFreshness.FRESH,
        summary=(
            f"Explicit {correction.correction_type.value.replace('_', ' ')} correction by "
            f"{correction.correcting_actor}."
        ),
        metadata={
            "correction_id": correction.correction_id,
            "evidence_version": correction.evidence_version,
            "attribution": correction.attribution,
            "review_at": correction.review_at.isoformat()
            if correction.review_at
            else None,
            "expires_at": correction.expires_at.isoformat()
            if correction.expires_at
            else None,
        },
    )
    return item.model_copy(
        update={
            "classification": classification,
            "classification_reason": reason,
            "temporal": temporal,
            "confidence": confidence,
            "fact_type": RealityFactType.EXPLICIT_FACT,
            "evidence": tuple((*item.evidence, evidence)),
            "effective_correction": EffectiveRealityCorrection(
                correction_id=correction.correction_id,
                correction_type=correction.correction_type.value,
                attribution=correction.attribution,
                effective_at=correction.effective_at,
                expires_at=correction.expires_at,
                review_at=correction.review_at,
            ),
        }
    )


def _normalized_parameters(
    correction_type: MorningCorrectionType,
    parameters: MorningCorrectionParameters,
    created_at: datetime,
) -> tuple[MorningCorrectionParameters, datetime, datetime | None, datetime | None]:
    effective_at = parameters.effective_at or created_at
    expires_at = parameters.expires_at
    review_at = parameters.review_at
    if correction_type == MorningCorrectionType.NOT_TODAY:
        boundary = review_at or expires_at
        if boundary is None:
            local = created_at.astimezone(created_at.tzinfo)
            tomorrow = local.date() + timedelta(days=1)
            boundary = datetime.combine(tomorrow, datetime.min.time(), tzinfo=local.tzinfo)
        if boundary <= effective_at:
            raise ValueError("not-today review boundary must be in the future")
        review_at = boundary
        expires_at = boundary
    elif correction_type == MorningCorrectionType.SNOOZE:
        boundary = parameters.snooze_until
        if boundary is None or boundary <= effective_at:
            raise ValueError("snooze requires a future timezone-aware wake time")
        review_at = boundary
        expires_at = boundary
    elif correction_type == MorningCorrectionType.WAITING_ON_SOMEONE:
        boundary = parameters.waiting_until or review_at
        if boundary is not None and boundary <= effective_at:
            raise ValueError("waiting review boundary must be in the future")
        review_at = boundary
        expires_at = boundary
    return (
        parameters.model_copy(
            update={
                "effective_at": effective_at,
                "expires_at": expires_at,
                "review_at": review_at,
            }
        ),
        effective_at,
        expires_at,
        review_at,
    )


def _find_statement(synthesis: Any, statement_id: str) -> Any | None:
    for name in (
        "changes_since_meaningful_check",
        "attention_today",
        "handled_paused_waiting",
        "project_momentum_constraints",
        "realistic_day_shape",
    ):
        for statement in getattr(synthesis, name).statements:
            if statement.statement_id == statement_id:
                return statement
    return None


def _primary_provider_identity(statement: Any) -> Any | None:
    work = getattr(statement, "linked_work_identity", None)
    if work is not None:
        for identity in statement.provider_identities:
            if identity.provider == work.provider:
                return identity
    return statement.provider_identities[0] if statement.provider_identities else None


def _mutation_target(statement: Any) -> tuple[str, str, str] | None:
    work = getattr(statement, "linked_work_identity", None)
    if work is None:
        return None
    matching = next(
        (
            item
            for item in statement.provider_identities
            if item.provider == work.provider
            and item.provider_record_id == work.provider_record_id
        ),
        None,
    )
    record_type = matching.provider_record_type if matching else "work_item"
    return work.provider, record_type, work.provider_record_id


def _correction_from_row(row: Any) -> MorningCorrection:
    return MorningCorrection(
        correction_id=row["id"],
        correction_type=MorningCorrectionType(row["correction_type"]),
        statement_id=row["statement_id"],
        reconciliation_id=row["reconciliation_id"],
        reality_item_id=row["reality_item_id"],
        synthesis_id=row["synthesis_id"],
        canonical_project_id=row["canonical_project_id"],
        canonical_project_key=row["canonical_project_key"],
        work_provider=row["work_provider"],
        work_provider_record_id=row["work_provider_record_id"],
        source_provider=row["source_provider"],
        source_provider_record_type=row["source_provider_record_type"],
        source_provider_record_id=row["source_provider_record_id"],
        evidence_references=tuple(json.loads(row["evidence_references_json"])),
        evidence_version=row["evidence_version"],
        prior_classification=RealityClassification(row["prior_classification"]),
        parameters=MorningCorrectionParameters.model_validate_json(
            row["parameters_json"]
        ),
        correcting_actor=row["correcting_actor"],
        attribution=row["attribution"],
        created_at=datetime.fromisoformat(row["created_at"]),
        effective_at=datetime.fromisoformat(row["effective_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"])
        if row["expires_at"]
        else None,
        review_at=datetime.fromisoformat(row["review_at"])
        if row["review_at"]
        else None,
        status=MorningCorrectionStatus(row["status"]),
        supersedes_correction_id=row["supersedes_correction_id"],
        reversed_at=datetime.fromisoformat(row["reversed_at"])
        if row["reversed_at"]
        else None,
        reversed_by_actor=row["reversed_by_actor"],
        idempotency_key=row["idempotency_key"],
    )


def _preview_from_row(row: Any) -> ProviderMutationPreview:
    return ProviderMutationPreview(
        preview_id=row["id"],
        statement_id=row["statement_id"],
        synthesis_id=row["synthesis_id"],
        evidence_version=row["evidence_version"],
        provider=row["provider"],
        provider_record_type=row["provider_record_type"],
        provider_record_id=row["provider_record_id"],
        field_name=row["field_name"],
        previous_value=json.loads(row["previous_value_json"]),
        proposed_value=json.loads(row["proposed_value_json"]),
        provider_revision=row["provider_revision"],
        requested_by_actor=row["requested_by_actor"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        status=ProviderPreviewStatus(row["status"]),
        diagnostic=row["diagnostic"],
        confirmed_by_actor=row["confirmed_by_actor"],
        confirmed_at=datetime.fromisoformat(row["confirmed_at"])
        if row["confirmed_at"]
        else None,
        result_reference=row["result_reference"],
        request_idempotency_key=row["request_idempotency_key"],
    )


def _canonical_json(value: Any) -> str:
    _validate_safe_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _confirmation_matches_preview(
    request: ProviderPreviewConfirmationRequest,
    preview: ProviderMutationPreview,
) -> bool:
    return (
        request.preview_id == preview.preview_id
        and request.evidence_version == preview.evidence_version
        and request.provider == preview.provider
        and request.provider_record_type == preview.provider_record_type
        and request.provider_record_id == preview.provider_record_id
        and request.field_name == preview.field_name
        and _canonical_json(request.previous_value)
        == _canonical_json(preview.previous_value)
        and _canonical_json(request.proposed_value)
        == _canonical_json(preview.proposed_value)
        and (
            preview.confirmed_by_actor is None
            or request.confirming_actor == preview.confirmed_by_actor
        )
    )


def _correction_request_matches_stored(
    request: MorningCorrectionRequest,
    *,
    statement: Any,
    stored: MorningCorrection,
) -> bool:
    requested_parameters = request.parameters.model_dump(
        mode="json",
        include=request.parameters.model_fields_set,
    )
    stored_parameters = stored.parameters.model_dump(
        mode="json",
        include=request.parameters.model_fields_set,
    )
    return (
        stored.correction_type == request.correction_type
        and stored.statement_id == request.statement_id
        and stored.reconciliation_id
        == getattr(statement, "source_reconciliation_id", None)
        and stored.synthesis_id == request.synthesis_id
        and stored.evidence_version == request.evidence_version
        and stored.correcting_actor == request.correcting_actor
        and _canonical_json(requested_parameters)
        == _canonical_json(stored_parameters)
    )


def _preview_request_matches_stored(
    candidate: ProviderMutationPreview,
    stored: ProviderMutationPreview,
) -> bool:
    return (
        candidate.preview_id == stored.preview_id
        and candidate.statement_id == stored.statement_id
        and candidate.synthesis_id == stored.synthesis_id
        and candidate.evidence_version == stored.evidence_version
        and candidate.provider == stored.provider
        and candidate.provider_record_type == stored.provider_record_type
        and candidate.provider_record_id == stored.provider_record_id
        and candidate.field_name == stored.field_name
        and _canonical_json(candidate.proposed_value)
        == _canonical_json(stored.proposed_value)
        and candidate.requested_by_actor == stored.requested_by_actor
    )


def _validate_safe_value(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in SENSITIVE_KEYS or any(
                token in normalized for token in ("password", "secret", "token")
            ):
                raise ValueError("sensitive provider payloads cannot be retained")
            _validate_safe_value(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_safe_value(item)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _reverse_reality_confirmation(
    correction: MorningCorrection,
    *,
    reversed_at: datetime,
    reversed_by_actor: str,
    idempotency_key: str,
) -> None:
    confirmation_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "pcos-reality-confirmation:"
            f"morning-correction:{correction.idempotency_key}",
        )
    )
    reality_confirmation_repository.reverse(
        confirmation_id=confirmation_id,
        reversed_at=reversed_at,
        reversed_by_actor=reversed_by_actor,
        idempotency_key=idempotency_key,
    )


morning_correction_repository = MorningCorrectionRepository()
morning_correction_service = MorningCorrectionService(morning_correction_repository)
morning_provider_reconciliation_service = MorningProviderReconciliationService()
