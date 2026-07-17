"""Durable pending-action repository and confirmation service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
import json
import logging
import sqlite3
import uuid
from typing import Any

from .action_domain import (
    ACTION_PAYLOAD_ADAPTER,
    ACTION_SCHEMA_VERSION,
    ActionEvidence,
    ActionPayload,
    PendingActionLifecycle,
    PendingActionRecord,
    PendingActionType,
    ProviderTargetReference,
    StoredActionFailure,
    StoredActionResult,
    legacy_client_payload,
    parse_legacy_pending_action,
    payload_fingerprint,
    payload_provider,
    payload_target_references,
)
from .action_executors import (
    ActionExecutionContext,
    ActionExecutionResult,
    ActionExecutorRegistry,
    UncertainProviderOutcome,
    default_action_executor_registry,
)
from .project_registry import ProjectRegistryService, project_registry_service
from .storage import database_connection


logger = logging.getLogger(__name__)


class PendingActionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PendingActionExecution:
    record: PendingActionRecord
    actions_taken: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()


class PendingActionRepository:
    """SQLite repository with immutable payloads and atomic state transitions."""

    def create(
        self,
        *,
        action_id: str,
        payload: ActionPayload,
        canonical_project_id: str | None,
        confirmation_prompt: str,
        evidence: tuple[ActionEvidence, ...],
        idempotency_key: str,
        session_id: str | None,
        source: str,
        source_ref: str | None,
        expires_at: datetime | None,
        proposed_at: datetime,
    ) -> PendingActionRecord:
        fingerprint = payload_fingerprint(payload)
        provider = payload_provider(payload)
        targets = payload_target_references(payload)
        timestamp = proposed_at.isoformat()
        values = (
            action_id,
            payload.action_type.value,
            payload.schema_version,
            _json(payload.model_dump(mode="json")),
            canonical_project_id,
            provider,
            _json([item.model_dump(mode="json") for item in targets]),
            confirmation_prompt,
            _json([item.model_dump(mode="json") for item in evidence]),
            fingerprint,
            idempotency_key,
            session_id,
            source,
            source_ref,
            PendingActionLifecycle.PENDING.value,
            1,
            timestamp,
            timestamp,
            expires_at.isoformat() if expires_at else None,
        )
        with database_connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO pending_actions (
                        id, action_type, schema_version, payload, canonical_project_id,
                        provider, target_references, confirmation_prompt, evidence,
                        payload_fingerprint, idempotency_key, session_id, source,
                        source_ref, lifecycle, version, proposed_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError as exc:
                row = connection.execute(
                    "SELECT * FROM pending_actions WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    raise
                existing = _record_from_row(row)
                if existing.payload_fingerprint != fingerprint:
                    raise PendingActionError(
                        "idempotency_conflict",
                        "Idempotency key is already bound to a different action payload.",
                    ) from exc
                return existing
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        assert row is not None
        return _record_from_row(row)

    def get(self, action_id: str) -> PendingActionRecord | None:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def current_pending(self, session_id: str | None) -> PendingActionRecord | None:
        with database_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM pending_actions
                WHERE session_id IS ? AND lifecycle = 'pending'
                ORDER BY proposed_at DESC, id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        record = _record_from_row(row) if row else None
        if record and record.expires_at and record.expires_at <= _utc_now():
            return self.expire(record.action_id, expected_version=record.version)
        return record

    def claim(
        self,
        action_id: str,
        *,
        expected_version: int,
        expected_fingerprint: str,
        now: datetime,
    ) -> PendingActionRecord:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            record = _required_record(row)
            _validate_expected(record, expected_version, expected_fingerprint)
            if record.expires_at and record.expires_at <= now:
                connection.execute(
                    """
                    UPDATE pending_actions
                    SET lifecycle = 'expired', version = version + 1,
                        updated_at = ?, completed_at = ?
                    WHERE id = ? AND lifecycle = 'pending' AND version = ?
                    """,
                    (now.isoformat(), now.isoformat(), action_id, record.version),
                )
                connection.commit()
                raise PendingActionError("expired", "Pending action has expired.")
            if record.lifecycle != PendingActionLifecycle.PENDING:
                raise PendingActionError(
                    "terminal_or_claimed",
                    "Pending action is no longer available for execution.",
                )
            cursor = connection.execute(
                """
                UPDATE pending_actions
                SET lifecycle = 'executing', version = version + 1,
                    confirmed_at = ?, execution_started_at = ?, updated_at = ?
                WHERE id = ? AND lifecycle = 'pending' AND version = ?
                    AND payload_fingerprint = ?
                """,
                (
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                    action_id,
                    record.version,
                    record.payload_fingerprint,
                ),
            )
            if cursor.rowcount != 1:
                raise PendingActionError(
                    "claim_conflict",
                    "Pending action was claimed by another confirmation.",
                )
            claimed = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        return _required_record(claimed)

    def cancel(
        self,
        action_id: str,
        *,
        expected_version: int,
        expected_fingerprint: str,
        now: datetime,
    ) -> PendingActionRecord:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            record = _required_record(row)
            _validate_expected(record, expected_version, expected_fingerprint)
            if record.lifecycle != PendingActionLifecycle.PENDING:
                raise PendingActionError(
                    "terminal_or_claimed",
                    "Pending action is no longer available for cancellation.",
                )
            cursor = connection.execute(
                """
                UPDATE pending_actions
                SET lifecycle = 'cancelled', version = version + 1,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND lifecycle = 'pending' AND version = ?
                    AND payload_fingerprint = ?
                """,
                (
                    now.isoformat(),
                    now.isoformat(),
                    action_id,
                    record.version,
                    record.payload_fingerprint,
                ),
            )
            if cursor.rowcount != 1:
                raise PendingActionError(
                    "cancel_conflict",
                    "Pending action changed before cancellation completed.",
                )
            updated = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        return _required_record(updated)

    def finish(
        self,
        action_id: str,
        *,
        expected_version: int,
        lifecycle: PendingActionLifecycle,
        result: StoredActionResult,
        failure: StoredActionFailure | None,
        now: datetime,
    ) -> PendingActionRecord:
        if lifecycle not in {
            PendingActionLifecycle.SUCCEEDED,
            PendingActionLifecycle.FAILED,
            PendingActionLifecycle.OUTCOME_UNKNOWN,
        }:
            raise ValueError("Execution can finish only in an execution terminal state.")
        with database_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE pending_actions
                SET lifecycle = ?, version = version + 1, updated_at = ?, completed_at = ?,
                    result = ?, failure = ?
                WHERE id = ? AND lifecycle = 'executing' AND version = ?
                """,
                (
                    lifecycle.value,
                    now.isoformat(),
                    now.isoformat(),
                    _json(result.model_dump(mode="json")),
                    _json(failure.model_dump(mode="json")) if failure else None,
                    action_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise PendingActionError(
                    "finish_conflict",
                    "Pending action execution state changed before completion was stored.",
                )
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        return _required_record(row)

    def expire(self, action_id: str, *, expected_version: int) -> PendingActionRecord:
        now = _utc_now()
        with database_connection() as connection:
            connection.execute(
                """
                UPDATE pending_actions
                SET lifecycle = 'expired', version = version + 1,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND lifecycle = 'pending' AND version = ?
                """,
                (now.isoformat(), now.isoformat(), action_id, expected_version),
            )
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        return _required_record(row)


class PendingActionService:
    def __init__(
        self,
        *,
        repository: PendingActionRepository | None = None,
        executor_registry: ActionExecutorRegistry = default_action_executor_registry,
        registry_service: ProjectRegistryService = project_registry_service,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository or PendingActionRepository()
        self.executor_registry = executor_registry
        self.registry_service = registry_service
        self.clock = clock

    def propose_legacy(
        self,
        pending_action: dict[str, Any],
        *,
        session_id: str | None,
        source: str = "chat",
        source_ref: str | None = None,
        idempotency_key: str | None = None,
        expires_at: datetime | None = None,
    ) -> PendingActionRecord:
        try:
            payload = parse_legacy_pending_action(pending_action)
        except (ValueError, TypeError) as exc:
            raise PendingActionError("invalid_payload", str(exc)) from exc
        prompt = str(pending_action.get("confirmation_prompt") or "").strip()
        if not prompt:
            raise PendingActionError(
                "invalid_confirmation_prompt",
                "Executable pending action requires a confirmation prompt.",
            )
        now = self.clock()
        action_id = str(uuid.uuid4())
        fingerprint = payload_fingerprint(payload)
        resolved_id = _canonical_project_id(
            pending_action,
            payload,
            self.registry_service,
        )
        key = idempotency_key or f"{source}:{action_id}:{fingerprint[:16]}"
        evidence = (
            ActionEvidence(
                kind="proposal_reason",
                source=source,
                summary=prompt,
                source_ref=source_ref,
            ),
        )
        return self.repository.create(
            action_id=action_id,
            payload=payload,
            canonical_project_id=resolved_id,
            confirmation_prompt=prompt,
            evidence=evidence,
            idempotency_key=key,
            session_id=session_id,
            source=source,
            source_ref=source_ref,
            expires_at=expires_at,
            proposed_at=now,
        )

    def confirm(
        self,
        action_id: str,
        *,
        expected_version: int,
        expected_fingerprint: str,
        context: ActionExecutionContext,
    ) -> PendingActionExecution:
        claimed = self.repository.claim(
            action_id,
            expected_version=expected_version,
            expected_fingerprint=expected_fingerprint,
            now=self.clock(),
        )
        try:
            execution = self.executor_registry.execute(claimed.payload, context)
        except UncertainProviderOutcome:
            logger.warning(
                "pending_action_outcome_unknown action_id=%s action_type=%s",
                claimed.action_id,
                claimed.action_type.value,
            )
            return self._unknown(claimed)
        except BaseException:  # noqa: BLE001 - provider mutation outcome cannot be assumed safe.
            logger.error(
                "pending_action_executor_interrupted action_id=%s action_type=%s",
                claimed.action_id,
                claimed.action_type.value,
            )
            return self._unknown(claimed)

        if execution.errors:
            result = StoredActionResult(
                status="failed",
                provider_references=execution.provider_references,
                action_count=len(execution.actions_taken),
            )
            failure = StoredActionFailure(
                code=("partial_provider_failure" if execution.partial_mutation else "provider_failure"),
                message=(
                    "A provider mutation completed only partially. Reconfirmation is blocked."
                    if execution.partial_mutation
                    else "The provider action did not complete. Reconfirmation is blocked."
                ),
            )
            record = self.repository.finish(
                claimed.action_id,
                expected_version=claimed.version,
                lifecycle=PendingActionLifecycle.FAILED,
                result=result,
                failure=failure,
                now=self.clock(),
            )
            return PendingActionExecution(
                record=record,
                actions_taken=execution.actions_taken,
                errors=execution.errors,
            )

        result = StoredActionResult(
            status="succeeded",
            provider_references=execution.provider_references,
            action_count=len(execution.actions_taken),
        )
        record = self.repository.finish(
            claimed.action_id,
            expected_version=claimed.version,
            lifecycle=PendingActionLifecycle.SUCCEEDED,
            result=result,
            failure=None,
            now=self.clock(),
        )
        return PendingActionExecution(
            record=record,
            actions_taken=execution.actions_taken,
        )

    def cancel(
        self,
        action_id: str,
        *,
        expected_version: int,
        expected_fingerprint: str,
    ) -> PendingActionRecord:
        return self.repository.cancel(
            action_id,
            expected_version=expected_version,
            expected_fingerprint=expected_fingerprint,
            now=self.clock(),
        )

    def get(self, action_id: str) -> PendingActionRecord:
        record = self.repository.get(action_id)
        if record is None:
            raise PendingActionError("not_found", "Pending action was not found.")
        return record

    def current(self, session_id: str | None) -> PendingActionRecord | None:
        record = self.repository.current_pending(session_id)
        if record and record.lifecycle == PendingActionLifecycle.EXPIRED:
            return None
        return record

    @staticmethod
    def public_payload(record: PendingActionRecord) -> dict[str, Any]:
        return legacy_client_payload(record)

    def _unknown(self, claimed: PendingActionRecord) -> PendingActionExecution:
        record = self.repository.finish(
            claimed.action_id,
            expected_version=claimed.version,
            lifecycle=PendingActionLifecycle.OUTCOME_UNKNOWN,
            result=StoredActionResult(status="outcome_unknown"),
            failure=StoredActionFailure(
                code="provider_outcome_unknown",
                message=(
                    "The provider outcome is unknown. Automatic retry and reconfirmation are blocked."
                ),
            ),
            now=self.clock(),
        )
        return PendingActionExecution(
            record=record,
            errors=(
                "The provider outcome is unknown. Review the provider before taking another action.",
            ),
        )


def _canonical_project_id(
    legacy: dict[str, Any],
    payload: ActionPayload,
    registry_service: ProjectRegistryService,
) -> str | None:
    explicit = str(legacy.get("canonical_project_id") or "").strip()
    if explicit:
        return explicit
    reference = str(legacy.get("resolved_project") or "").strip()
    if not reference:
        task = getattr(payload, "task", None)
        reference = str(getattr(task, "project_category", None) or "").strip()
    if not reference:
        reference = str(getattr(payload, "project_category", None) or "").strip()
    if not reference:
        return None
    project = registry_service.snapshot().get_project_definition(reference)
    return str(project.get("canonical_project_id")) if project and project.get("canonical_project_id") else None


def _validate_expected(
    record: PendingActionRecord,
    expected_version: int,
    expected_fingerprint: str,
) -> None:
    if record.version != expected_version:
        raise PendingActionError("stale_version", "Pending action version is stale.")
    if not hmac.compare_digest(record.payload_fingerprint, expected_fingerprint):
        raise PendingActionError("fingerprint_mismatch", "Pending action fingerprint does not match.")


def _required_record(row: sqlite3.Row | None) -> PendingActionRecord:
    if row is None:
        raise PendingActionError("not_found", "Pending action was not found.")
    return _record_from_row(row)


def _record_from_row(row: sqlite3.Row) -> PendingActionRecord:
    item = dict(row)
    payload = ACTION_PAYLOAD_ADAPTER.validate_python(json.loads(item["payload"]))
    if payload.action_type.value != item["action_type"] or payload.schema_version != item["schema_version"]:
        raise PendingActionError(
            "stored_contract_mismatch",
            "Stored pending action contract does not match its typed payload.",
        )
    if payload_provider(payload) != item["provider"]:
        raise PendingActionError(
            "stored_provider_mismatch",
            "Stored pending action provider does not match its typed payload.",
        )
    if not hmac.compare_digest(payload_fingerprint(payload), item["payload_fingerprint"]):
        raise PendingActionError(
            "stored_payload_tampered",
            "Stored pending action payload fingerprint does not match.",
        )
    return PendingActionRecord(
        action_id=item["id"],
        action_type=item["action_type"],
        schema_version=item["schema_version"],
        payload=payload,
        canonical_project_id=item["canonical_project_id"],
        provider=item["provider"],
        target_references=tuple(
            ProviderTargetReference.model_validate(value)
            for value in json.loads(item["target_references"])
        ),
        confirmation_prompt=item["confirmation_prompt"],
        evidence=tuple(
            ActionEvidence.model_validate(value)
            for value in json.loads(item["evidence"])
        ),
        payload_fingerprint=item["payload_fingerprint"],
        idempotency_key=item["idempotency_key"],
        session_id=item["session_id"],
        source=item["source"],
        source_ref=item["source_ref"],
        lifecycle=item["lifecycle"],
        version=item["version"],
        proposed_at=_datetime(item["proposed_at"]),
        updated_at=_datetime(item["updated_at"]),
        confirmed_at=_optional_datetime(item["confirmed_at"]),
        execution_started_at=_optional_datetime(item["execution_started_at"]),
        completed_at=_optional_datetime(item["completed_at"]),
        expires_at=_optional_datetime(item["expires_at"]),
        result=(StoredActionResult.model_validate(json.loads(item["result"])) if item["result"] else None),
        failure=(StoredActionFailure.model_validate(json.loads(item["failure"])) if item["failure"] else None),
    )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _optional_datetime(value: str | None) -> datetime | None:
    return _datetime(value) if value else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


pending_action_service = PendingActionService()
