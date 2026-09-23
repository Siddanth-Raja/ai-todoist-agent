"""SID-250 canonical College state, event application, and attention assessment.

This is an internal application service.  It deliberately exposes no HTTP, MCP,
provider, background-job, or UI boundary.  Callers construct :class:`CollegeScope`
from trusted authentication and may pass a bounded SID-151 context snapshot to an
explicit assessment command.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import sqlite3
from typing import Any, Callable, Iterable, Literal
import uuid

from .storage import _connect as database_connection
from .storage import database_connection as migration_database_connection


COLLEGE_EVENT_VERSION = "college-event/1.0"
COLLEGE_CLAIM_VERSION = "college-claim/1.0"
COLLEGE_ASSESSMENT_VERSION = "college-assessment/1.0"
COLLEGE_RULE_VERSION = "college-attention/1.0"
MAX_EVENT_PAYLOAD_BYTES = 16_000
MAX_EVIDENCE_REFERENCE_BYTES = 2_000
MAX_EVIDENCE_REFERENCES = 16
MAX_EVIDENCE_EXCERPT_CHARS = 500
COLLEGE_KEY_CHECK_MESSAGE = b"sid-250-fingerprint-key-check-v1"
FORBIDDEN_EVIDENCE_KEYS = {
    "raw", "raw_body", "body", "transcript", "document", "email", "conversation",
}

IDENTITY_KINDS = {
    "institution", "term", "course", "section", "work_item", "learning_need",
    "commitment", "opportunity", "provider_purpose_link",
}
IDENTITY_STATUSES = {"resolved", "provisional", "needs_review", "retired"}
EVENT_TYPES = {
    "deadline_confirmed", "deadline_corrected", "completion_submission_recorded",
    "course_progress_recorded", "study_need_recorded",
    "recurring_commitment_recorded", "opportunity_recorded", "conflict_recorded",
}
SOURCE_CLASSES = {
    "user_confirmed", "user_relayed_instructor", "provider_observation",
    "email_evidence", "document_evidence", "inferred_interpretation",
    "assistant_suggestion",
}
RECEIPT_STATES = {
    "received", "applied", "needs_review", "rejected", "retryable_failure"
}
DIMENSION_VALUES = {
    "completion": {"not_started", "in_progress", "finished", "unknown"},
    "submission": {"not_submitted", "submitted", "accepted", "returned", "unknown"},
    "understanding": {"needs_learning", "learning", "understood", "mastered", "unknown"},
    "attendance": {"planned", "attended", "missed", "excused", "unknown"},
    "scheduling": {"unscheduled", "proposed", "scheduled", "changed", "canceled", "unknown"},
    "requirement": {"required", "optional", "recommended", "waived", "canceled", "unknown"},
    "attendance_intent": {"selected", "unselected", "undecided", "unknown"},
    "provider_free_busy": {"free", "busy", "unknown"},
    "provider_record_existence": {
        "observed_present", "observed_absent_in_bounded_read", "not_checked", "unknown"
    },
}
OBSERVATION_KINDS = {
    "topic_covered", "assessment_observed", "announcement_reported",
    "attendance_reported", "coordination_blocker",
}
ATTENTION_CATEGORIES = {
    "relevant_changes", "current_conflicts_blockers", "required_obligations",
    "preparation_pressure", "material_unknowns", "learning_needs",
    "coordination_blockers", "optional_recommended_opportunities",
}
PRIORITY_BANDS = {
    "current_conflicts_blockers": 10,
    "required_obligations": 20,
    "preparation_pressure": 20,
    "material_unknowns": 30,
    "learning_needs": 40,
    "coordination_blockers": 40,
    "relevant_changes": 50,
    "optional_recommended_opportunities": 50,
}


class CollegeDomainError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CollegeScope:
    actor_id: str
    workspace_id: str

    def __post_init__(self) -> None:
        if not self.actor_id.strip() or not self.workspace_id.strip():
            raise CollegeDomainError("invalid_scope", "Actor and workspace are required.")


@dataclass(frozen=True)
class CollegeCommandIdentity:
    command_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.command_id.strip() or not self.idempotency_key.strip():
            raise CollegeDomainError(
                "invalid_command_identity", "Command ID and idempotency key are required."
            )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None:
        raise CollegeDomainError("timezone_required", "Timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value is not None else default


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CollegeDomainError("invalid_payload", f"{field} is required.")
    return value.strip()


def _reject_server_identity(payload: Any) -> None:
    if isinstance(payload, dict):
        forbidden = {"actor_id", "workspace_id", "recorded_at", "assessed_at"} & payload.keys()
        if forbidden:
            raise CollegeDomainError(
                "server_identity_supplied",
                f"Server-owned fields are forbidden: {', '.join(sorted(forbidden))}.",
            )
        for value in payload.values():
            _reject_server_identity(value)
    elif isinstance(payload, list):
        for value in payload:
            _reject_server_identity(value)


class CollegeDomainService:
    """Transactional SID-250 service over the shared application SQLite store."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _now,
        failure_injector: Callable[[str], None] | None = None,
        context_version_reader: Callable[[CollegeScope, str], int | str | None] | None = None,
    ) -> None:
        self.clock = clock
        self.failure_injector = failure_injector
        self.context_version_reader = context_version_reader
        self._verify_ready()

    @classmethod
    def initialize_schema(cls) -> None:
        with migration_database_connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS college_metadata (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    canonical_version INTEGER NOT NULL,
                    schema_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id)
                );
                CREATE TABLE IF NOT EXISTS college_store_metadata (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS college_identities (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    identity_kind TEXT NOT NULL,
                    identity_status TEXT NOT NULL,
                    parent_ids_json TEXT NOT NULL,
                    attributes_json TEXT NOT NULL,
                    stable_provider_ref_json TEXT,
                    reviewed_composite_json TEXT,
                    supersedes_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    retired_at TEXT,
                    PRIMARY KEY(actor_id, workspace_id, canonical_id)
                );
                CREATE INDEX IF NOT EXISTS idx_college_identity_kind
                    ON college_identities(actor_id, workspace_id, identity_kind, identity_status);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_college_identity_provider_ref
                    ON college_identities(actor_id, workspace_id, stable_provider_ref_json)
                    WHERE stable_provider_ref_json IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_college_identity_reviewed_composite
                    ON college_identities(actor_id, workspace_id, identity_kind, reviewed_composite_json)
                    WHERE reviewed_composite_json IS NOT NULL;
                CREATE TABLE IF NOT EXISTS college_provider_links (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    provider_link_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    record_kind TEXT NOT NULL,
                    provider_record_id TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    canonical_target_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, provider_link_id),
                    UNIQUE(actor_id, workspace_id, provider, account_id, record_kind,
                           provider_record_id, purpose, canonical_target_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_college_provider_purpose_target
                    ON college_provider_links(
                        actor_id, workspace_id, provider, account_id, record_kind,
                        provider_record_id, purpose
                    );
                CREATE TABLE IF NOT EXISTS college_events (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    schema_version TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    expected_revisions_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    source_class TEXT NOT NULL,
                    source_actor TEXT NOT NULL,
                    source_surface_hint TEXT,
                    asserted_at TEXT,
                    observed_at TEXT,
                    certainty TEXT NOT NULL,
                    date_precision TEXT,
                    supersedes_event_ids_json TEXT NOT NULL,
                    action_intent TEXT NOT NULL,
                    semantic_payload_hash TEXT NOT NULL,
                    semantic_claim_hash TEXT NOT NULL,
                    source_independence_key TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS college_receipts (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    canonical_version INTEGER,
                    event_ids_json TEXT NOT NULL,
                    affected_ids_json TEXT NOT NULL,
                    review_refs_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, receipt_id),
                    UNIQUE(actor_id, workspace_id, command_id),
                    UNIQUE(actor_id, workspace_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS college_receipt_transitions (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, receipt_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS college_receipt_aliases (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, command_id),
                    UNIQUE(actor_id, workspace_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS college_claims (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    claim_status TEXT NOT NULL,
                    source_class TEXT NOT NULL,
                    source_actor TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    asserted_at TEXT,
                    observed_at TEXT,
                    recorded_at TEXT NOT NULL,
                    freshness_json TEXT NOT NULL,
                    certainty TEXT NOT NULL,
                    supersedes_claim_ids_json TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    semantic_claim_hash TEXT NOT NULL,
                    source_independence_key TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, claim_id)
                );
                CREATE INDEX IF NOT EXISTS idx_college_claim_field
                    ON college_claims(actor_id, workspace_id, subject_id, field, recorded_at);
                CREATE TABLE IF NOT EXISTS college_field_revisions (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    claim_id TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, subject_id, field, revision)
                );
                CREATE TABLE IF NOT EXISTS college_conflicts (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    conflict_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    claim_ids_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, conflict_id)
                );
                CREATE TABLE IF NOT EXISTS college_coverage (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    coverage_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    availability TEXT NOT NULL,
                    completeness TEXT NOT NULL,
                    freshness TEXT NOT NULL,
                    reason TEXT,
                    assessed_at TEXT,
                    observed_through TEXT,
                    bounds_json TEXT NOT NULL,
                    omission_reason TEXT,
                    freshness_policy_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, coverage_id)
                );
                CREATE INDEX IF NOT EXISTS idx_college_coverage_scope
                    ON college_coverage(actor_id, workspace_id, provider, account_id,
                                        scope_json, recorded_at DESC);
                CREATE TABLE IF NOT EXISTS college_assessments (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    assessment_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    lifecycle TEXT NOT NULL,
                    canonical_input_version INTEGER NOT NULL,
                    context_snapshot_id TEXT,
                    context_snapshot_version TEXT,
                    authorized_scope_json TEXT NOT NULL,
                    assessed_at TEXT NOT NULL,
                    valid_through TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    horizon_json TEXT NOT NULL,
                    coverage_json TEXT NOT NULL,
                    omissions_json TEXT NOT NULL,
                    baseline_json TEXT,
                    window_json TEXT,
                    evidence_refs_json TEXT NOT NULL,
                    transient_context_refs_json TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    invalidated_at TEXT,
                    invalidation_reason TEXT,
                    failure_json TEXT,
                    PRIMARY KEY(actor_id, workspace_id, assessment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_college_assessment_current
                    ON college_assessments(actor_id, workspace_id, lifecycle, valid_through);
                CREATE TABLE IF NOT EXISTS college_assessment_transitions (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    assessment_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    lifecycle TEXT NOT NULL CHECK(lifecycle IN ('queued','running','ready','failed')),
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, assessment_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS college_assessment_dependencies (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    assessment_id TEXT NOT NULL,
                    dependency_kind TEXT NOT NULL,
                    dependency_id TEXT NOT NULL,
                    dependency_version TEXT,
                    PRIMARY KEY(actor_id, workspace_id, assessment_id,
                                dependency_kind, dependency_id)
                );
                CREATE TABLE IF NOT EXISTS college_claim_dependencies (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    source_claim_id TEXT NOT NULL,
                    dependent_claim_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, source_claim_id, dependent_claim_id)
                );
                CREATE TABLE IF NOT EXISTS college_lifecycle_tombstones (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    tombstone_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, tombstone_id)
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            key_row = connection.execute(
                "SELECT value FROM college_store_metadata WHERE key='hmac_key'"
            ).fetchone()
            if key_row is None:
                key = secrets.token_bytes(32)
                connection.execute(
                    "INSERT INTO college_store_metadata(key, value) VALUES ('hmac_key', ?)",
                    (key,),
                )
            else:
                key = bytes(key_row["value"])
            if len(key) != 32:
                raise CollegeDomainError("fingerprint_key_invalid", "College fingerprint key is invalid.")
            expected = hmac.new(key, COLLEGE_KEY_CHECK_MESSAGE, hashlib.sha256).digest()
            check = connection.execute(
                "SELECT value FROM college_store_metadata WHERE key='hmac_key_check'"
            ).fetchone()
            if check is None:
                connection.execute(
                    "INSERT INTO college_store_metadata(key, value) VALUES ('hmac_key_check', ?)",
                    (expected,),
                )
            elif not hmac.compare_digest(bytes(check["value"]), expected):
                raise CollegeDomainError(
                    "fingerprint_key_mismatch", "College fingerprint key verifier failed."
                )

    def _verify_ready(self) -> None:
        try:
            with database_connection() as connection:
                connection.execute("SELECT 1 FROM college_metadata LIMIT 1").fetchone()
                key = connection.execute(
                    "SELECT value FROM college_store_metadata WHERE key='hmac_key'"
                ).fetchone()
                check = connection.execute(
                    "SELECT value FROM college_store_metadata WHERE key='hmac_key_check'"
                ).fetchone()
                if key is None or check is None:
                    raise CollegeDomainError(
                        "fingerprint_key_unavailable", "College fingerprint key is unavailable."
                    )
                self._fingerprint_key = bytes(key["value"])
                expected = hmac.new(
                    self._fingerprint_key, COLLEGE_KEY_CHECK_MESSAGE, hashlib.sha256
                ).digest()
                if len(self._fingerprint_key) != 32 or not hmac.compare_digest(
                    bytes(check["value"]), expected
                ):
                    raise CollegeDomainError(
                        "fingerprint_key_mismatch", "College fingerprint key verifier failed."
                    )
        except sqlite3.OperationalError as exc:
            raise CollegeDomainError(
                "college_schema_uninitialized",
                "Initialize the SID-250 schema before constructing the service.",
            ) from exc

    def _fingerprint(self, value: Any) -> str:
        return hmac.new(
            self._fingerprint_key, _json(value).encode(), hashlib.sha256
        ).hexdigest()

    def _fail(self, point: str) -> None:
        if self.failure_injector:
            self.failure_injector(point)

    def context_snapshot_from_sid151(
        self,
        scope: CollegeScope,
        context_service: Any,
        context_scope: Any,
        *,
        snapshot_id: str,
        limit: int = 25,
        conversation_id: str | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        """Read an authorized bounded SID-151 snapshot without copying its store."""
        if (
            getattr(context_scope, "actor_id", None) != scope.actor_id
            or getattr(context_scope, "workspace_id", None) != scope.workspace_id
        ):
            raise CollegeDomainError(
                "context_scope_mismatch", "SID-151 context must use the same trusted scope."
            )
        items = context_service.retrieve_context(
            context_scope, limit=limit, conversation_id=conversation_id, at=at
        )
        version = self._fingerprint([
            {
                "item_id": item.get("item_id"), "revision": item.get("revision"),
                "status": item.get("status"), "expires_at": item.get("expires_at"),
                "raw_source_available": item.get("raw_source_available"),
            }
            for item in items
        ])
        generation = context_service.get_assessment_generation(context_scope)
        return {
            "snapshot_id": snapshot_id,
            "version": version,
            "assessment_generation": generation,
            "items": items,
        }

    @staticmethod
    def _sid151_generation(connection: sqlite3.Connection, scope: CollegeScope) -> int:
        try:
            row = connection.execute(
                """SELECT generation FROM context_assessment_generations
                   WHERE actor_id=? AND workspace_id=?""",
                (scope.actor_id, scope.workspace_id),
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row["generation"]) if row is not None else 0

    def _metadata(self, connection: sqlite3.Connection, scope: CollegeScope) -> int:
        row = connection.execute(
            "SELECT canonical_version FROM college_metadata WHERE actor_id=? AND workspace_id=?",
            (scope.actor_id, scope.workspace_id),
        ).fetchone()
        if row:
            return int(row["canonical_version"])
        now = _iso(self.clock())
        connection.execute(
            "INSERT INTO college_metadata VALUES (?, ?, 0, ?, ?)",
            (scope.actor_id, scope.workspace_id, COLLEGE_CLAIM_VERSION, now),
        )
        return 0

    def _receipt_lookup(
        self, connection: sqlite3.Connection, scope: CollegeScope,
        identity: CollegeCommandIdentity, payload_hash: str,
    ) -> dict[str, Any] | None:
        rows = connection.execute(
            """SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=?
               AND (command_id=? OR idempotency_key=?)""",
            (scope.actor_id, scope.workspace_id, identity.command_id, identity.idempotency_key),
        ).fetchall()
        alias_rows = connection.execute(
            """SELECT r.* FROM college_receipt_aliases a
               JOIN college_receipts r ON r.actor_id=a.actor_id
                AND r.workspace_id=a.workspace_id AND r.receipt_id=a.receipt_id
               WHERE a.actor_id=? AND a.workspace_id=?
                 AND (a.command_id=? OR a.idempotency_key=?)""",
            (scope.actor_id, scope.workspace_id, identity.command_id, identity.idempotency_key),
        ).fetchall()
        rows = [*rows, *alias_rows]
        if not rows:
            return None
        if len({row["receipt_id"] for row in rows}) != 1:
            raise CollegeDomainError(
                "command_identity_conflict",
                "Command ID and idempotency key belong to different receipts.",
            )
        row = rows[0]
        if row["payload_hash"] != payload_hash:
            raise CollegeDomainError(
                "idempotency_payload_conflict",
                "The command identity is bound to changed semantic content.",
            )
        return self._receipt(row, duplicate=True)

    @staticmethod
    def _receipt(row: sqlite3.Row, *, duplicate: bool = False) -> dict[str, Any]:
        item = dict(row)
        for field in ("event_ids_json", "affected_ids_json", "review_refs_json"):
            item[field.removesuffix("_json")] = _loads(item.pop(field), [])
        item["duplicate"] = duplicate
        return item

    def _insert_receipt(
        self, connection: sqlite3.Connection, scope: CollegeScope,
        identity: CollegeCommandIdentity, *, operation: str, payload_hash: str,
        state: str, canonical_version: int | None, event_ids: list[str],
        affected_ids: list[str], review_refs: list[str], error_code: str | None = None,
        error_message: str | None = None, receipt_id: str | None = None,
    ) -> dict[str, Any]:
        if state not in RECEIPT_STATES:
            raise AssertionError(state)
        receipt_id = receipt_id or str(uuid.uuid4())
        recorded_at = _iso(self.clock())
        connection.execute(
            """INSERT INTO college_receipts VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (scope.actor_id, scope.workspace_id, receipt_id, identity.command_id,
             identity.idempotency_key, operation, payload_hash, state, canonical_version,
             _json(event_ids), _json(sorted(set(affected_ids))), _json(review_refs),
             error_code, None, recorded_at),
        )
        connection.execute(
            "INSERT INTO college_receipt_transitions VALUES (?, ?, ?, 1, ?, ?)",
            (scope.actor_id, scope.workspace_id, receipt_id, state, recorded_at),
        )
        row = connection.execute(
            "SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=? AND receipt_id=?",
            (scope.actor_id, scope.workspace_id, receipt_id),
        ).fetchone()
        return self._receipt(row)

    def _transition_receipt(
        self, connection: sqlite3.Connection, scope: CollegeScope, receipt_id: str, *,
        state: str, canonical_version: int | None, affected_ids: list[str],
        review_refs: list[str], error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        recorded_at = _iso(self.clock())
        connection.execute(
            """UPDATE college_receipts SET state=?, canonical_version=?,
                 affected_ids_json=?, review_refs_json=?, error_code=?, error_message=?,
                 recorded_at=?
               WHERE actor_id=? AND workspace_id=? AND receipt_id=?""",
            (state, canonical_version, _json(sorted(set(affected_ids))), _json(review_refs),
             error_code, None, recorded_at, scope.actor_id, scope.workspace_id,
             receipt_id),
        )
        sequence = connection.execute(
            """SELECT COALESCE(MAX(sequence), 0) + 1 FROM college_receipt_transitions
               WHERE actor_id=? AND workspace_id=? AND receipt_id=?""",
            (scope.actor_id, scope.workspace_id, receipt_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO college_receipt_transitions VALUES (?, ?, ?, ?, ?, ?)",
            (scope.actor_id, scope.workspace_id, receipt_id, sequence, state, recorded_at),
        )
        row = connection.execute(
            "SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=? AND receipt_id=?",
            (scope.actor_id, scope.workspace_id, receipt_id),
        ).fetchone()
        return self._receipt(row)

    # -- identity and provider/account coverage -------------------------

    def create_identity(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *, canonical_id: str,
        identity_kind: str, identity_status: str, attributes: dict[str, Any],
        parent_ids: Iterable[str] = (), stable_provider_ref: dict[str, Any] | None = None,
        reviewed_composite: dict[str, Any] | None = None,
        supersedes_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        parent_ids = list(parent_ids)
        supersedes_ids = list(supersedes_ids)
        payload = {
            "canonical_id": canonical_id, "identity_kind": identity_kind,
            "identity_status": identity_status, "attributes": attributes,
            "parent_ids": parent_ids, "stable_provider_ref": stable_provider_ref,
            "reviewed_composite": reviewed_composite, "supersedes_ids": supersedes_ids,
        }
        _reject_server_identity(payload)
        if identity_kind not in IDENTITY_KINDS or identity_status not in IDENTITY_STATUSES:
            raise CollegeDomainError("invalid_identity", "Unsupported identity kind or status.")
        if not stable_provider_ref and not reviewed_composite:
            raise CollegeDomainError(
                "unsafe_identity_match",
                "A stable provider reference or reviewed composite identity is required.",
            )
        if stable_provider_ref and not {
            "provider", "account_id", "record_id"
        }.issubset(stable_provider_ref):
            raise CollegeDomainError(
                "unsafe_identity_match", "Stable provider identity requires provider, account_id, and record_id."
            )
        if reviewed_composite and not (
            set(reviewed_composite) - {"title", "display_name", "subject"}
        ):
            raise CollegeDomainError(
                "title_only_identity_forbidden", "A title or display name alone cannot establish identity."
            )
        payload_hash = self._fingerprint(payload)
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._receipt_lookup(connection, scope, identity, payload_hash)
            if prior:
                return prior
            existing = connection.execute(
                "SELECT attributes_json FROM college_identities WHERE actor_id=? AND workspace_id=? AND canonical_id=?",
                (scope.actor_id, scope.workspace_id, canonical_id),
            ).fetchone()
            if existing:
                raise CollegeDomainError("identity_exists", "Canonical identity already exists.")
            now = _iso(self.clock())
            try:
                connection.execute(
                    """INSERT INTO college_identities VALUES
                       (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (scope.actor_id, scope.workspace_id, canonical_id, identity_kind,
                     identity_status, _json(parent_ids), _json(attributes),
                     _json(stable_provider_ref) if stable_provider_ref else None,
                     _json(reviewed_composite) if reviewed_composite else None,
                     _json(supersedes_ids), now),
                )
            except sqlite3.IntegrityError as exc:
                raise CollegeDomainError(
                    "identity_key_conflict",
                    "The trusted identity key is already bound and requires review.",
                ) from exc
            for superseded_id in supersedes_ids:
                cursor = connection.execute(
                    """UPDATE college_identities SET identity_status='retired', retired_at=?
                       WHERE actor_id=? AND workspace_id=? AND canonical_id=?
                         AND identity_status='provisional'""",
                    (now, scope.actor_id, scope.workspace_id, superseded_id),
                )
                if cursor.rowcount != 1:
                    raise CollegeDomainError(
                        "identity_resolution_conflict",
                        "A provisional identity was already resolved or is unavailable.",
                    )
            version = self._metadata(connection, scope) + 1
            connection.execute(
                "UPDATE college_metadata SET canonical_version=?, updated_at=? WHERE actor_id=? AND workspace_id=?",
                (version, now, scope.actor_id, scope.workspace_id),
            )
            self._invalidate_assessments(
                connection, scope, "identity_changed",
                [canonical_id, *supersedes_ids], now,
            )
            return self._insert_receipt(
                connection, scope, identity, operation="create_identity",
                payload_hash=payload_hash, state="applied", canonical_version=version,
                event_ids=[], affected_ids=[canonical_id], review_refs=[],
            )

    def create_provider_link(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *, provider_link_id: str,
        provider: str, account_id: str, record_kind: str, provider_record_id: str,
        purpose: str, canonical_target_id: str,
    ) -> dict[str, Any]:
        payload = locals().copy()
        payload.pop("self"); payload.pop("scope"); payload.pop("identity")
        _reject_server_identity(payload)
        payload_hash = self._fingerprint(payload)
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._receipt_lookup(connection, scope, identity, payload_hash)
            if prior:
                return prior
            target = connection.execute(
                "SELECT 1 FROM college_identities WHERE actor_id=? AND workspace_id=? AND canonical_id=?",
                (scope.actor_id, scope.workspace_id, canonical_target_id),
            ).fetchone()
            if not target:
                raise CollegeDomainError("unknown_identity", "Canonical target is unresolved.")
            try:
                connection.execute(
                    "INSERT INTO college_provider_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (scope.actor_id, scope.workspace_id, provider_link_id, provider, account_id,
                     record_kind, provider_record_id, purpose, canonical_target_id,
                     _iso(self.clock())),
                )
            except sqlite3.IntegrityError as exc:
                raise CollegeDomainError(
                    "provider_link_conflict",
                    "The provider-purpose link is already bound and requires review.",
                ) from exc
            now = _iso(self.clock())
            version = self._metadata(connection, scope) + 1
            connection.execute(
                "UPDATE college_metadata SET canonical_version=?, updated_at=? WHERE actor_id=? AND workspace_id=?",
                (version, now, scope.actor_id, scope.workspace_id),
            )
            self._invalidate_assessments(
                connection, scope, "provider_link_changed", [canonical_target_id], now
            )
            return self._insert_receipt(
                connection, scope, identity, operation="create_provider_link",
                payload_hash=payload_hash, state="applied",
                canonical_version=version, event_ids=[],
                affected_ids=[provider_link_id, canonical_target_id], review_refs=[],
            )

    def record_coverage(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *, coverage_id: str,
        provider: str, account_id: str, declared_scope: dict[str, Any], availability: str,
        completeness: str, freshness: str, reason: str | None = None,
        assessed_at: datetime | None = None, observed_through: datetime | None = None,
        bounds: dict[str, Any] | None = None, omission_reason: str | None = None,
        freshness_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = _require_text(provider, "provider")
        account_id = _require_text(account_id, "account_id")
        if not isinstance(declared_scope, dict) or not declared_scope:
            raise CollegeDomainError(
                "invalid_coverage", "A non-empty declared coverage scope is required."
            )
        if availability not in {"healthy", "unavailable", "pending", "unknown"}:
            raise CollegeDomainError("invalid_coverage", "Invalid availability.")
        if completeness not in {"complete", "partial", "truncated", "unknown"}:
            raise CollegeDomainError("invalid_coverage", "Invalid completeness.")
        if freshness not in {"fresh", "stale", "unknown"}:
            raise CollegeDomainError("invalid_coverage", "Invalid freshness.")
        if provider.lower() == "blinn" and reason == "administrator_approval":
            if availability != "pending" or completeness != "unknown" or freshness != "unknown":
                raise CollegeDomainError("dishonest_blinn_coverage", "Blinn approval coverage must remain pending/unknown/unknown.")
            if assessed_at is not None or observed_through is not None:
                raise CollegeDomainError("fabricated_blinn_check", "No Blinn mailbox check time may be recorded.")
        payload = {
            "coverage_id": coverage_id, "provider": provider, "account_id": account_id,
            "declared_scope": declared_scope, "availability": availability,
            "completeness": completeness, "freshness": freshness, "reason": reason,
            "assessed_at": _iso(assessed_at), "observed_through": _iso(observed_through),
            "bounds": bounds or {}, "omission_reason": omission_reason,
            "freshness_policy": freshness_policy or {},
        }
        payload_hash = self._fingerprint(payload)
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._receipt_lookup(connection, scope, identity, payload_hash)
            if prior:
                return prior
            now = _iso(self.clock())
            prior_coverage_ids = [
                str(row["coverage_id"])
                for row in connection.execute(
                    """SELECT coverage_id FROM college_coverage
                       WHERE actor_id=? AND workspace_id=? AND provider=? AND account_id=?
                         AND scope_json=?""",
                    (
                        scope.actor_id, scope.workspace_id, provider, account_id,
                        _json(declared_scope),
                    ),
                ).fetchall()
            ]
            connection.execute(
                """INSERT INTO college_coverage VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (scope.actor_id, scope.workspace_id, coverage_id, provider, account_id,
                 _json(declared_scope), availability, completeness, freshness, reason,
                 _iso(assessed_at), _iso(observed_through), _json(bounds or {}),
                 omission_reason, _json(freshness_policy or {}), now),
            )
            version = self._metadata(connection, scope) + 1
            connection.execute(
                "UPDATE college_metadata SET canonical_version=?, updated_at=? WHERE actor_id=? AND workspace_id=?",
                (version, now, scope.actor_id, scope.workspace_id),
            )
            self._invalidate_assessments(
                connection, scope, "coverage_changed",
                [coverage_id, *prior_coverage_ids], now,
            )
            return self._insert_receipt(
                connection, scope, identity, operation="record_coverage",
                payload_hash=payload_hash, state="applied", canonical_version=version,
                event_ids=[], affected_ids=[coverage_id], review_refs=[],
            )

    # -- immutable fact event application -------------------------------

    def receive_update(
        self, scope: CollegeScope, identity: CollegeCommandIdentity,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Durably accept a validated delivery before application begins."""
        _reject_server_identity(events)
        try:
            if not events:
                raise CollegeDomainError("empty_batch", "At least one fact event is required.")
            normalized = [self._normalize_event(event) for event in events]
            event_ids = [event["event_id"] for event in normalized]
            if len(set(event_ids)) != len(event_ids):
                raise CollegeDomainError("duplicate_batch_member", "Batch event IDs must be unique.")
            payload_hash = self._fingerprint({"operation": "record_facts", "events": normalized})
        except CollegeDomainError as exc:
            serialized = json.dumps(
                {"operation": "record_facts", "events": events}, sort_keys=True,
                separators=(",", ":"), default=str,
            )
            payload_hash = hmac.new(
                self._fingerprint_key, serialized.encode(), hashlib.sha256
            ).hexdigest()
            with database_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                prior = self._receipt_lookup(connection, scope, identity, payload_hash)
                if prior:
                    return prior
                return self._insert_receipt(
                    connection, scope, identity, operation="record_facts",
                    payload_hash=payload_hash, state="rejected", canonical_version=None,
                    event_ids=[], affected_ids=[], review_refs=[],
                    error_code=exc.code, error_message=str(exc),
                )
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._receipt_lookup(connection, scope, identity, payload_hash)
            if prior:
                return prior
            return self._insert_receipt(
                connection,
                scope,
                identity,
                operation="record_facts",
                payload_hash=payload_hash,
                state="received",
                canonical_version=None,
                event_ids=event_ids,
                affected_ids=[],
                review_refs=[],
            )

    def record_update(
        self, scope: CollegeScope, identity: CollegeCommandIdentity,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        acceptance = self.receive_update(scope, identity, events)
        if acceptance["state"] == "rejected":
            return acceptance
        normalized = [self._normalize_event(event) for event in events]
        event_ids = [event["event_id"] for event in normalized]
        if len(set(event_ids)) != len(event_ids):
            raise CollegeDomainError("duplicate_batch_member", "Batch event IDs must be unique.")
        payload_hash = self._fingerprint({"operation": "record_facts", "events": normalized})
        try:
            with database_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                prior = self._receipt_lookup(connection, scope, identity, payload_hash)
                retry_receipt_id = None
                if prior and prior["state"] not in {"received", "retryable_failure"}:
                    return prior
                if prior:
                    retry_receipt_id = prior["receipt_id"]
                event_retry = self._existing_event_batch(
                    connection, scope, identity, normalized, payload_hash
                )
                if event_retry:
                    return event_retry
                self._validate_event_identity_reuse(connection, scope, normalized)
                self._fail("after_validation")
                version = self._metadata(connection, scope)
                affected: list[str] = []
                review_refs: list[str] = []
                outcome = "applied"
                now = _iso(self.clock())
                for ordinal, event in enumerate(normalized):
                    result = self._apply_event(connection, scope, identity, event, ordinal, now)
                    affected.extend(result["affected"])
                    review_refs.extend(result["review_refs"])
                    if result["needs_review"]:
                        outcome = "needs_review"
                self._fail("after_claims_before_receipt")
                self._fail("after_domain_mutation")
                version += 1
                connection.execute(
                    "UPDATE college_metadata SET canonical_version=?, updated_at=? WHERE actor_id=? AND workspace_id=?",
                    (version, now, scope.actor_id, scope.workspace_id),
                )
                self._fail("before_assessment_invalidation")
                self._invalidate_assessments(connection, scope, "facts_changed", affected, now)
                self._fail("after_assessment_invalidation")
                if retry_receipt_id:
                    receipt = self._transition_receipt(
                        connection, scope, retry_receipt_id, state=outcome,
                        canonical_version=version, affected_ids=affected,
                        review_refs=review_refs,
                    )
                else:
                    receipt = self._insert_receipt(
                        connection, scope, identity, operation="record_facts",
                        payload_hash=payload_hash, state=outcome, canonical_version=version,
                        event_ids=event_ids, affected_ids=affected, review_refs=review_refs,
                    )
                self._fail("after_receipt")
                return receipt
        except CollegeDomainError as exc:
            return self._record_rejection(
                scope, identity, "record_facts", payload_hash, event_ids,
                exc.code, str(exc),
            )
        except Exception as exc:
            return self._record_retryable_failure(
                scope, identity, "record_facts", payload_hash, event_ids,
                "transaction_failure", str(exc),
            )

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "schema_version", "event_id", "event_type", "subject_ref", "payload",
            "expected_revisions", "source_class", "source_actor", "source_surface_hint",
            "asserted_at", "observed_at", "evidence", "certainty", "freshness",
            "date_precision", "supersedes_event_ids", "action_intent",
            "source_independence_key",
        }
        extra = set(event) - allowed
        if extra:
            raise CollegeDomainError("unexpected_event_field", f"Unexpected event fields: {sorted(extra)}")
        result = {key: event.get(key) for key in allowed}
        result["schema_version"] = event.get("schema_version")
        if result["schema_version"] != COLLEGE_EVENT_VERSION:
            raise CollegeDomainError("unsupported_event_version", "college-event/1.0 is required.")
        result["event_id"] = _require_text(result["event_id"], "event_id")
        result["event_type"] = _require_text(result["event_type"], "event_type")
        if result["event_type"] not in EVENT_TYPES:
            raise CollegeDomainError("unsupported_event_type", "Unsupported frozen fact variant.")
        result["subject_ref"] = _require_text(result["subject_ref"], "subject_ref")
        result["payload"] = result["payload"] or {}
        if not isinstance(result["payload"], dict):
            raise CollegeDomainError("invalid_payload", "Event payload must be an object.")
        if len(_json(result["payload"]).encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
            raise CollegeDomainError("content_too_large", "Event payload exceeds its bounded size.")
        result["expected_revisions"] = result["expected_revisions"] or []
        if not isinstance(result["expected_revisions"], list):
            raise CollegeDomainError("invalid_expected_revisions", "Expected revisions must be a list.")
        result["source_class"] = _require_text(result["source_class"], "source_class")
        if result["source_class"] not in SOURCE_CLASSES:
            raise CollegeDomainError("unsupported_source_class", "Unsupported source class.")
        result["source_actor"] = _require_text(result["source_actor"], "source_actor")
        result["asserted_at"] = _iso(result["asserted_at"])
        result["observed_at"] = _iso(result["observed_at"])
        if not result["asserted_at"] and not result["observed_at"]:
            raise CollegeDomainError("source_time_required", "A source time is required.")
        result["evidence"] = result["evidence"] or []
        if not isinstance(result["evidence"], list) or len(result["evidence"]) > MAX_EVIDENCE_REFERENCES:
            raise CollegeDomainError("invalid_evidence", "Evidence references must be a bounded list.")
        for reference in result["evidence"]:
            if not isinstance(reference, dict):
                raise CollegeDomainError("invalid_evidence", "Evidence references must be objects.")
            if FORBIDDEN_EVIDENCE_KEYS & set(reference):
                raise CollegeDomainError(
                    "raw_evidence_forbidden",
                    "College stores references and bounded excerpts, not raw source content.",
                )
            excerpt = reference.get("excerpt")
            if excerpt is not None and (
                not isinstance(excerpt, str) or len(excerpt) > MAX_EVIDENCE_EXCERPT_CHARS
            ):
                raise CollegeDomainError("invalid_evidence", "Evidence excerpt is too large.")
            if len(_json(reference).encode("utf-8")) > MAX_EVIDENCE_REFERENCE_BYTES:
                raise CollegeDomainError("content_too_large", "Evidence reference exceeds its bounded size.")
        if result["source_class"] in {
            "provider_observation", "email_evidence", "document_evidence",
            "inferred_interpretation", "assistant_suggestion",
        } and not result["evidence"]:
            raise CollegeDomainError(
                "evidence_required", "This source class requires attributable evidence."
            )
        result["certainty"] = result["certainty"] or "unknown"
        if result["certainty"] not in {"confirmed", "probable", "possible", "unknown"}:
            raise CollegeDomainError("invalid_certainty", "Invalid certainty.")
        result["freshness"] = result["freshness"] or {"state": "unknown"}
        result["supersedes_event_ids"] = result["supersedes_event_ids"] or []
        result["action_intent"] = result["action_intent"] or "record_fact"
        if result["action_intent"] not in {"record_fact", "propose_provider_action", "no_provider_action"}:
            raise CollegeDomainError("invalid_action_intent", "Invalid action intent.")
        result["source_independence_key"] = result["source_independence_key"] or self._source_key(result)
        return result

    def _source_key(self, event: dict[str, Any]) -> str:
        if str(event.get("source_class", "")).startswith("user_"):
            return self._fingerprint({
                "source_class": event.get("source_class"),
                "source_actor": event.get("source_actor"),
            })
        refs = []
        for evidence in event.get("evidence") or []:
            if isinstance(evidence, dict):
                normalized = {
                    k: v for k, v in evidence.items()
                    if k not in {
                        "conversation_id", "transport_id", "copy_id", "forward_id",
                        "excerpt", "raw_available",
                    }
                }
                if {
                    "provider", "account_id", "record_id"
                }.issubset(normalized):
                    normalized.pop("evidence_id", None)
                    normalized.pop("id", None)
                refs.append(normalized)
            else:
                refs.append(evidence)
        return self._fingerprint({"source_class": event.get("source_class"), "source_actor": event.get("source_actor"), "evidence": refs})

    def _validate_event_identity_reuse(
        self, connection: sqlite3.Connection, scope: CollegeScope,
        events: list[dict[str, Any]],
    ) -> None:
        for event in events:
            row = connection.execute(
                "SELECT semantic_payload_hash FROM college_events WHERE actor_id=? AND workspace_id=? AND event_id=?",
                (scope.actor_id, scope.workspace_id, event["event_id"]),
            ).fetchone()
            if row:
                semantic_hash = self._event_payload_hash(event)
                if row["semantic_payload_hash"] != semantic_hash:
                    raise CollegeDomainError("event_payload_conflict", "Event ID is bound to changed content.")
                raise CollegeDomainError(
                    "event_identity_requires_original_command",
                    "An existing event must be retried with its original command identity.",
                )

    def _existing_event_batch(
        self, connection: sqlite3.Connection, scope: CollegeScope,
        identity: CollegeCommandIdentity, events: list[dict[str, Any]], payload_hash: str,
    ) -> dict[str, Any] | None:
        rows = []
        for event in events:
            row = connection.execute(
                """SELECT event_id, command_id, ordinal, semantic_payload_hash
                   FROM college_events WHERE actor_id=? AND workspace_id=? AND event_id=?""",
                (scope.actor_id, scope.workspace_id, event["event_id"]),
            ).fetchone()
            if not row:
                if rows:
                    raise CollegeDomainError(
                        "partial_batch_replay", "A retry cannot change batch membership."
                    )
                return None
            if row["semantic_payload_hash"] != self._event_payload_hash(event):
                raise CollegeDomainError("event_payload_conflict", "Event ID is bound to changed content.")
            rows.append(row)
        command_ids = {str(row["command_id"]) for row in rows}
        if len(command_ids) != 1 or [int(row["ordinal"]) for row in rows] != list(range(len(rows))):
            raise CollegeDomainError("batch_membership_conflict", "Batch membership or ordering changed.")
        original = connection.execute(
            """SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=?
               AND command_id=?""",
            (scope.actor_id, scope.workspace_id, next(iter(command_ids))),
        ).fetchone()
        if not original or _loads(original["event_ids_json"], []) != [event["event_id"] for event in events]:
            raise CollegeDomainError("batch_membership_conflict", "Batch membership or ordering changed.")
        accepted_delivery = connection.execute(
            """SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=?
               AND command_id=? AND idempotency_key=?""",
            (
                scope.actor_id, scope.workspace_id, identity.command_id,
                identity.idempotency_key,
            ),
        ).fetchone()
        if accepted_delivery is not None:
            receipt = self._transition_receipt(
                connection, scope, accepted_delivery["receipt_id"],
                state=original["state"],
                canonical_version=original["canonical_version"],
                affected_ids=_loads(original["affected_ids_json"], []),
                review_refs=_loads(original["review_refs_json"], []),
            )
            receipt["duplicate"] = True
            return receipt
        connection.execute(
            "INSERT INTO college_receipt_aliases VALUES (?, ?, ?, ?, ?, ?, ?)",
            (scope.actor_id, scope.workspace_id, identity.command_id, identity.idempotency_key,
             original["receipt_id"], payload_hash, _iso(self.clock())),
        )
        return self._receipt(original, duplicate=True)

    def _event_payload_hash(self, event: dict[str, Any]) -> str:
        semantic = {k: v for k, v in event.items() if k not in {"event_id", "source_surface_hint"}}
        return self._fingerprint(semantic)

    def _identity_status(
        self, connection: sqlite3.Connection, scope: CollegeScope, subject_id: str,
    ) -> str | None:
        row = connection.execute(
            "SELECT identity_status FROM college_identities WHERE actor_id=? AND workspace_id=? AND canonical_id=?",
            (scope.actor_id, scope.workspace_id, subject_id),
        ).fetchone()
        return str(row["identity_status"]) if row else None

    def _apply_event(
        self, connection: sqlite3.Connection, scope: CollegeScope,
        command: CollegeCommandIdentity, event: dict[str, Any], ordinal: int, now: str,
    ) -> dict[str, Any]:
        subject_id = event["subject_ref"]
        identity_status = self._identity_status(connection, scope, subject_id)
        needs_review = identity_status not in {"resolved", "provisional"}
        if event["action_intent"] == "propose_provider_action" and identity_status != "resolved":
            raise CollegeDomainError(
                "unresolved_identity_provider_proposal",
                "Provider proposals require a resolved canonical identity.",
            )
        fields = self._claims_for_event(event)
        expected = {(x.get("subject_id"), x.get("field")): x.get("revision") for x in event["expected_revisions"] if isinstance(x, dict)}
        missing = [(subject_id, field) for field, _ in fields if (subject_id, field) not in expected]
        if missing:
            raise CollegeDomainError("expected_revision_required", f"Expected revisions required for {missing}.")
        semantic_event_hash = self._event_payload_hash(event)
        semantic_claim_hash = self._fingerprint({
            "subject": subject_id, "fields": fields, "source_class": event["source_class"],
            "source_actor": event["source_actor"], "evidence": event["evidence"],
        })
        connection.execute(
            """INSERT INTO college_events VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (scope.actor_id, scope.workspace_id, event["event_id"], command.command_id,
             ordinal, event["schema_version"], event["event_type"], subject_id,
             _json(event["payload"]), _json(event["expected_revisions"]),
             _json(event["evidence"]), event["source_class"], event["source_actor"],
             event.get("source_surface_hint"), event["asserted_at"], event["observed_at"],
             event["certainty"], event.get("date_precision"),
             _json(event["supersedes_event_ids"]), event["action_intent"],
             semantic_event_hash, semantic_claim_hash, event["source_independence_key"], now),
        )
        self._fail("after_events_before_claims")
        affected = [subject_id]
        review_refs: list[str] = []
        for field, value in fields:
            current_revision = self._field_revision(connection, scope, subject_id, field)
            expected_revision = expected[(subject_id, field)]
            expected_number = None if expected_revision == "absent" else expected_revision
            if expected_number != current_revision:
                conflict_id = self._record_conflict(
                    connection, scope, subject_id, field, [], "stale_expected_revision", now
                )
                review_refs.append(conflict_id)
                needs_review = True
                continue
            status, effective_certainty = self._authority(event, field)
            if identity_status != "resolved":
                status = "tentative"
                needs_review = True
            duplicate = connection.execute(
                """SELECT claim_id FROM college_claims WHERE actor_id=? AND workspace_id=?
                   AND subject_id=? AND field=? AND value_json=?
                   AND source_independence_key=? AND claim_status IN ('active','tentative','conflicted')
                   ORDER BY recorded_at LIMIT 1""",
                (scope.actor_id, scope.workspace_id, subject_id, field, _json(value),
                 event["source_independence_key"]),
            ).fetchone()
            if duplicate:
                affected.append(str(duplicate["claim_id"]))
                continue
            incompatible = connection.execute(
                """SELECT claim_id, value_json, asserted_at, observed_at FROM college_claims
                   WHERE actor_id=? AND workspace_id=? AND subject_id=? AND field=?
                     AND claim_status='active' ORDER BY recorded_at DESC""",
                (scope.actor_id, scope.workspace_id, subject_id, field),
            ).fetchall()
            incompatible = [row for row in incompatible if row["value_json"] != _json(value)]
            explicit_supersession = bool(event["supersedes_event_ids"])
            incoming_time = event["observed_at"] or event["asserted_at"]
            stale_incoming = False
            if explicit_supersession and incompatible and incoming_time:
                existing_times = [
                    row["observed_at"] or row["asserted_at"] for row in incompatible
                    if row["observed_at"] or row["asserted_at"]
                ]
                if existing_times and incoming_time < max(existing_times):
                    explicit_supersession = False
                    stale_incoming = True
            elif incompatible and incoming_time:
                existing_times = [
                    row["observed_at"] or row["asserted_at"] for row in incompatible
                    if row["observed_at"] or row["asserted_at"]
                ]
                stale_incoming = bool(existing_times and incoming_time < max(existing_times))
            if stale_incoming and status == "active":
                status = "tentative"
                conflict_id = self._record_conflict(
                    connection, scope, subject_id, field,
                    [str(row["claim_id"]) for row in incompatible],
                    "stale_evidence_requires_review", now,
                )
                review_refs.append(conflict_id)
                needs_review = True
            if incompatible and not explicit_supersession and status == "active":
                claim_id = str(uuid.uuid4())
                connection.execute(
                    """UPDATE college_claims SET claim_status='conflicted'
                       WHERE actor_id=? AND workspace_id=? AND subject_id=? AND field=?
                         AND claim_status='active'""",
                    (scope.actor_id, scope.workspace_id, subject_id, field),
                )
                status = "conflicted"
                conflict_id = self._record_conflict(
                    connection, scope, subject_id, field,
                    [str(row["claim_id"]) for row in incompatible] + [claim_id],
                    "credible_incompatible_claims", now,
                )
                review_refs.append(conflict_id)
                needs_review = True
            else:
                claim_id = str(uuid.uuid4())
            claim_hash = self._fingerprint({"subject": subject_id, "field": field, "value": value,
                                "source_independence_key": event["source_independence_key"]})
            supersedes_claims: list[str] = []
            if explicit_supersession and status == "active":
                supersedes_claims = [str(row["claim_id"]) for row in incompatible]
                if supersedes_claims:
                    placeholders = ",".join("?" for _ in supersedes_claims)
                    connection.execute(
                        f"UPDATE college_claims SET claim_status='superseded' WHERE actor_id=? AND workspace_id=? AND claim_id IN ({placeholders})",
                        (scope.actor_id, scope.workspace_id, *supersedes_claims),
                    )
            connection.execute(
                """INSERT INTO college_claims VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (scope.actor_id, scope.workspace_id, claim_id, subject_id, field,
                 _json(value), status, event["source_class"], event["source_actor"],
                 _json({"event_id": event["event_id"], "surface": event.get("source_surface_hint")}),
                 _json(event["evidence"]), event["asserted_at"], event["observed_at"], now,
                 _json(event["freshness"]), effective_certainty, _json(supersedes_claims),
                 COLLEGE_CLAIM_VERSION, claim_hash, event["source_independence_key"],
                 event["event_id"]),
            )
            for reference in event["evidence"]:
                source_claim_id = reference.get("claim_id")
                if source_claim_id:
                    source = connection.execute(
                        """SELECT 1 FROM college_claims
                           WHERE actor_id=? AND workspace_id=? AND claim_id=?""",
                        (scope.actor_id, scope.workspace_id, source_claim_id),
                    ).fetchone()
                    if source is None:
                        raise CollegeDomainError(
                            "unknown_claim_dependency",
                            "A derived claim references an unavailable supporting claim.",
                        )
                    connection.execute(
                        "INSERT OR IGNORE INTO college_claim_dependencies VALUES (?, ?, ?, ?, ?)",
                        (
                            scope.actor_id, scope.workspace_id, source_claim_id,
                            claim_id, now,
                        ),
                    )
            new_revision = (current_revision or 0) + 1
            connection.execute(
                "INSERT INTO college_field_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (scope.actor_id, scope.workspace_id, subject_id, field, new_revision,
                 claim_id, status, now),
            )
            affected.append(claim_id)
            if status != "active":
                needs_review = True
        if event["event_type"] == "conflict_recorded":
            conflict_id = self._record_conflict(
                connection, scope, subject_id,
                str(event["payload"].get("field", "unspecified")),
                list(event["payload"].get("claim_ids", [])),
                str(event["payload"].get("reason", "reported_conflict")), now,
            )
            review_refs.append(conflict_id)
            needs_review = True
        return {"affected": affected, "review_refs": review_refs, "needs_review": needs_review}

    def _claims_for_event(self, event: dict[str, Any]) -> list[tuple[str, Any]]:
        payload = event["payload"]
        event_type = event["event_type"]
        if event_type in {"deadline_confirmed", "deadline_corrected"}:
            deadline = payload.get("deadline") or payload.get("replacement")
            if not isinstance(deadline, dict):
                raise CollegeDomainError("invalid_deadline", "Deadline temporal value is required.")
            required = {"value", "timezone", "precision", "kind"}
            if not required.issubset(deadline):
                raise CollegeDomainError("invalid_deadline", "Deadline value, timezone, precision, and kind are required.")
            return [("deadline", deadline)]
        if event_type == "completion_submission_recorded":
            result = [(field, payload[field]) for field in ("completion", "submission") if field in payload]
            if not result:
                raise CollegeDomainError("empty_dimensions", "Completion or submission must be explicit.")
            self._validate_dimensions(result)
            return result
        if event_type == "course_progress_recorded":
            if payload.get("payload_kind") == "session_observation":
                session_id = _require_text(payload.get("session_id"), "session_id")
                if not payload.get("session_date") and not payload.get("session_interval"):
                    raise CollegeDomainError("session_time_required", "Session date or interval is required.")
                if not payload.get("timezone") or not payload.get("date_precision"):
                    raise CollegeDomainError("session_time_required", "Session timezone and precision are required.")
                entries = payload.get("entries") or []
                result: list[tuple[str, Any]] = []
                for entry in entries:
                    obs_id = _require_text(entry.get("observation_id"), "observation_id")
                    kind = entry.get("kind")
                    if kind not in OBSERVATION_KINDS:
                        raise CollegeDomainError("invalid_observation_kind", "Unsupported session observation kind.")
                    if not entry.get("asserted_at") and not entry.get("observed_at"):
                        raise CollegeDomainError("source_time_required", "Observation entry source time is required.")
                    result.append((f"session:{session_id}:{obs_id}:{kind}", entry))
                if "understanding" in payload:
                    result.append(("understanding", payload["understanding"]))
                self._validate_dimensions(result)
                return result
            result = []
            if "progress" in payload:
                result.append(("course_progress", payload["progress"]))
            if "understanding" in payload:
                result.append(("understanding", payload["understanding"]))
            self._validate_dimensions(result)
            return result
        if event_type == "study_need_recorded":
            return [("learning_need", payload)]
        if event_type == "recurring_commitment_recorded":
            result = [("recurrence", payload.get("recurrence") or payload.get("natural_pattern"))]
            for field in ("scheduling", "requirement", "attendance_intent", "provider_free_busy"):
                if field in payload:
                    result.append((field, payload[field]))
            self._validate_dimensions(result)
            return result
        if event_type == "opportunity_recorded":
            result = [("opportunity", payload)]
            for field in ("scheduling", "requirement", "attendance_intent"):
                if field in payload:
                    result.append((field, payload[field]))
            self._validate_dimensions(result)
            return result
        if event_type == "conflict_recorded":
            return [("conflict", payload)]
        raise AssertionError(event_type)

    @staticmethod
    def _validate_dimensions(fields: list[tuple[str, Any]]) -> None:
        for field, value in fields:
            if field in DIMENSION_VALUES and value not in DIMENSION_VALUES[field]:
                raise CollegeDomainError(
                    "invalid_dimension_value", f"Unsupported {field} value: {value}."
                )

    @staticmethod
    def _authority(event: dict[str, Any], field: str) -> tuple[str, str]:
        source = event["source_class"]
        certainty = event["certainty"]
        if source == "assistant_suggestion":
            return "tentative", "unknown"
        if field == "deadline":
            if source in {"provider_observation", "document_evidence", "email_evidence"}:
                return "active", certainty
            return "tentative", certainty
        if field == "submission" and source == "user_confirmed":
            return "tentative", certainty  # report of an attempt, not provider verification
        if field in {"completion", "understanding", "attendance", "attendance_intent"}:
            return ("active", certainty) if source in {"user_confirmed", "user_relayed_instructor"} else ("tentative", certainty)
        if field == "requirement" and source not in {"provider_observation", "document_evidence", "email_evidence"}:
            return "tentative", certainty
        if source == "inferred_interpretation":
            return "tentative", certainty
        return "active", certainty

    @staticmethod
    def _field_revision(
        connection: sqlite3.Connection, scope: CollegeScope, subject_id: str, field: str,
    ) -> int | None:
        row = connection.execute(
            """SELECT MAX(revision) revision FROM college_field_revisions
               WHERE actor_id=? AND workspace_id=? AND subject_id=? AND field=?""",
            (scope.actor_id, scope.workspace_id, subject_id, field),
        ).fetchone()
        return int(row["revision"]) if row and row["revision"] is not None else None

    @staticmethod
    def _record_conflict(
        connection: sqlite3.Connection, scope: CollegeScope, subject_id: str,
        field: str, claim_ids: list[str], reason: str, now: str,
    ) -> str:
        conflict_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO college_conflicts VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            (scope.actor_id, scope.workspace_id, conflict_id, subject_id, field,
             _json(claim_ids), reason, now),
        )
        return conflict_id

    def _apply_lifecycle(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *,
        operation: str, payload: dict[str, Any], mutation: Callable[
            [sqlite3.Connection, str], tuple[str, list[str], list[str]]
        ],
    ) -> dict[str, Any]:
        _reject_server_identity(payload)
        payload_hash = self._fingerprint({"operation": operation, **payload})
        try:
            with database_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                prior = self._receipt_lookup(connection, scope, identity, payload_hash)
                retry_receipt_id = None
                if prior and prior["state"] not in {"received", "retryable_failure"}:
                    return prior
                if prior:
                    retry_receipt_id = prior["receipt_id"]
                now = _iso(self.clock())
                state, affected, review_refs = mutation(connection, now)
                self._fail("after_domain_mutation")
                version = self._metadata(connection, scope) + 1
                connection.execute(
                    """UPDATE college_metadata SET canonical_version=?, updated_at=?
                       WHERE actor_id=? AND workspace_id=?""",
                    (version, now, scope.actor_id, scope.workspace_id),
                )
                self._fail("before_assessment_invalidation")
                self._invalidate_assessments(
                    connection, scope, f"{operation}_changed", affected, now
                )
                self._fail("after_assessment_invalidation")
                if retry_receipt_id:
                    receipt = self._transition_receipt(
                        connection, scope, retry_receipt_id, state=state,
                        canonical_version=version, affected_ids=affected,
                        review_refs=review_refs,
                    )
                else:
                    receipt = self._insert_receipt(
                        connection, scope, identity, operation=operation,
                        payload_hash=payload_hash, state=state,
                        canonical_version=version, event_ids=[],
                        affected_ids=affected, review_refs=review_refs,
                    )
                self._fail("after_receipt")
                return receipt
        except CollegeDomainError:
            raise
        except Exception as exc:
            return self._record_retryable_failure(
                scope, identity, operation, payload_hash, [],
                "transaction_failure", str(exc),
            )

    @staticmethod
    def _claim_row(
        connection: sqlite3.Connection, scope: CollegeScope, claim_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """SELECT c.*, r.revision FROM college_claims c
               JOIN college_field_revisions r ON r.actor_id=c.actor_id
                AND r.workspace_id=c.workspace_id AND r.claim_id=c.claim_id
               WHERE c.actor_id=? AND c.workspace_id=? AND c.claim_id=?""",
            (scope.actor_id, scope.workspace_id, claim_id),
        ).fetchone()
        if row is None:
            raise CollegeDomainError("claim_not_found", "Claim is unavailable.")
        return row

    def _insert_lifecycle_claim(
        self,
        connection: sqlite3.Connection, scope: CollegeScope, source: sqlite3.Row, *,
        claim_id: str, value_json: str, status: str, certainty: str,
        supersedes: list[str], revision: int, provenance: dict[str, Any], now: str,
        evidence_refs_json: str | None = None,
    ) -> None:
        source_key = f"lifecycle:{claim_id}"
        connection.execute(
            """INSERT INTO college_claims(
                   actor_id, workspace_id, claim_id, subject_id, field, value_json,
                   claim_status, source_class, source_actor, provenance_json,
                   evidence_refs_json, asserted_at, observed_at, recorded_at,
                   freshness_json, certainty, supersedes_claim_ids_json,
                   schema_version, semantic_claim_hash, source_independence_key, event_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scope.actor_id, scope.workspace_id, claim_id, source["subject_id"],
                source["field"], value_json, status, source["source_class"],
                source["source_actor"], _json(provenance),
                evidence_refs_json if evidence_refs_json is not None else source["evidence_refs_json"],
                source["asserted_at"], source["observed_at"], now,
                source["freshness_json"], certainty, _json(supersedes),
                COLLEGE_CLAIM_VERSION,
                self._fingerprint({"claim_id": claim_id, "value": _loads(value_json)}),
                source_key, source["event_id"],
            ),
        )
        connection.execute(
            "INSERT INTO college_field_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scope.actor_id, scope.workspace_id, source["subject_id"], source["field"],
                revision, claim_id, status, now,
            ),
        )

    def correct_claim(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *, claim_id: str,
        expected_revision: int, value: Any, reason: str,
    ) -> dict[str, Any]:
        payload = {
            "claim_id": claim_id, "expected_revision": expected_revision,
            "value": value, "reason": reason,
        }

        def mutation(connection: sqlite3.Connection, now: str):
            target = self._claim_row(connection, scope, claim_id)
            current = self._field_revision(
                connection, scope, target["subject_id"], target["field"]
            )
            current_claim = connection.execute(
                """SELECT claim_id FROM college_field_revisions
                   WHERE actor_id=? AND workspace_id=? AND subject_id=? AND field=?
                     AND revision=?""",
                (
                    scope.actor_id, scope.workspace_id, target["subject_id"],
                    target["field"], current,
                ),
            ).fetchone()
            if current != expected_revision or current_claim["claim_id"] != claim_id:
                raise CollegeDomainError(
                    "revision_conflict", "Correction target is no longer current."
                )
            synthetic = {
                "source_class": "user_relayed_instructor"
                if target["field"] == "deadline" else "user_confirmed",
                "certainty": "confirmed",
            }
            status, certainty = self._authority(synthetic, target["field"])
            new_id = str(uuid.uuid4())
            connection.execute(
                """UPDATE college_claims SET claim_status='superseded'
                   WHERE actor_id=? AND workspace_id=? AND claim_id=?""",
                (scope.actor_id, scope.workspace_id, claim_id),
            )
            self._insert_lifecycle_claim(
                connection, scope, target, claim_id=new_id, value_json=_json(value),
                status=status, certainty=certainty, supersedes=[claim_id],
                revision=expected_revision + 1,
                provenance={"lifecycle": "correct_claim", "reason_code": "user_correction"}, now=now,
            )
            return ("needs_review" if status != "active" else "applied",
                    [target["subject_id"], claim_id, new_id], [])

        return self._apply_lifecycle(
            scope, identity, operation="correct_claim", payload=payload, mutation=mutation
        )

    def undo_update(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *, claim_id: str,
        expected_revision: int, reason: str,
    ) -> dict[str, Any]:
        payload = {
            "claim_id": claim_id, "expected_revision": expected_revision, "reason": reason,
        }

        def mutation(connection: sqlite3.Connection, now: str):
            target = self._claim_row(connection, scope, claim_id)
            if int(target["revision"]) != expected_revision or self._field_revision(
                connection, scope, target["subject_id"], target["field"]
            ) != expected_revision:
                raise CollegeDomainError(
                    "revision_conflict", "Undo cannot overwrite a later field revision."
                )
            supersedes = _loads(target["supersedes_claim_ids_json"], [])
            if not supersedes:
                raise CollegeDomainError("undo_target_missing", "The exact prior value is unavailable.")
            previous = self._claim_row(connection, scope, supersedes[0])
            new_id = str(uuid.uuid4())
            connection.execute(
                """UPDATE college_claims SET claim_status='superseded'
                   WHERE actor_id=? AND workspace_id=? AND claim_id=?""",
                (scope.actor_id, scope.workspace_id, claim_id),
            )
            self._insert_lifecycle_claim(
                connection, scope, previous, claim_id=new_id,
                value_json=previous["value_json"], status="active",
                certainty=previous["certainty"], supersedes=[claim_id],
                revision=expected_revision + 1,
                provenance={"lifecycle": "undo_update", "reason_code": "user_requested_undo"}, now=now,
            )
            return "applied", [target["subject_id"], claim_id, new_id], []

        return self._apply_lifecycle(
            scope, identity, operation="undo_update", payload=payload, mutation=mutation
        )

    def forget_claim(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *, claim_id: str,
        reason: str = "user_requested_forgetting",
    ) -> dict[str, Any]:
        payload = {"claim_id": claim_id, "reason": reason}

        def mutation(connection: sqlite3.Connection, now: str):
            self._claim_row(connection, scope, claim_id)
            forgotten: set[str] = {claim_id}
            changed = True
            while changed:
                changed = False
                lineage = connection.execute(
                    """SELECT claim_id, supersedes_claim_ids_json FROM college_claims
                       WHERE actor_id=? AND workspace_id=?""",
                    (scope.actor_id, scope.workspace_id),
                ).fetchall()
                for lineage_claim in lineage:
                    supersedes = set(_loads(lineage_claim["supersedes_claim_ids_json"], []))
                    lineage_id = str(lineage_claim["claim_id"])
                    if lineage_id in forgotten:
                        additions = supersedes - forgotten
                    elif supersedes & forgotten:
                        additions = {lineage_id}
                    else:
                        additions = set()
                    if additions:
                        forgotten.update(additions)
                        changed = True
                dependents = connection.execute(
                    f"""SELECT DISTINCT dependent_claim_id FROM college_claim_dependencies
                         WHERE actor_id=? AND workspace_id=? AND source_claim_id IN
                         ({','.join('?' for _ in forgotten)})""",
                    (scope.actor_id, scope.workspace_id, *sorted(forgotten)),
                ).fetchall()
                for dependent in dependents:
                    dependent_id = str(dependent["dependent_claim_id"])
                    supports = connection.execute(
                        """SELECT source_claim_id FROM college_claim_dependencies
                           WHERE actor_id=? AND workspace_id=? AND dependent_claim_id=?""",
                        (scope.actor_id, scope.workspace_id, dependent_id),
                    ).fetchall()
                    if all(str(row["source_claim_id"]) in forgotten for row in supports):
                        if dependent_id not in forgotten:
                            forgotten.add(dependent_id)
                            changed = True
            subjects: set[str] = set()
            event_ids: set[str] = set()
            event_fields: dict[str, set[str]] = {}
            for target_id in sorted(forgotten):
                row = self._claim_row(connection, scope, target_id)
                subjects.add(str(row["subject_id"]))
                event_ids.add(str(row["event_id"]))
                event_fields.setdefault(str(row["event_id"]), set()).add(str(row["field"]))
                marker = f"forgotten:{uuid.uuid4()}"
                connection.execute(
                    """UPDATE college_claims SET value_json='null', claim_status='retracted',
                           source_actor='forgotten', provenance_json='{}', evidence_refs_json='[]',
                           freshness_json='{}', certainty='unknown',
                           supersedes_claim_ids_json='[]', semantic_claim_hash=?,
                           source_independence_key=?
                       WHERE actor_id=? AND workspace_id=? AND claim_id=?""",
                    (marker, marker, scope.actor_id, scope.workspace_id, target_id),
                )
                connection.execute(
                    "INSERT INTO college_lifecycle_tombstones VALUES (?, ?, ?, ?, 'claim', 'forgotten', ?)",
                    (
                        scope.actor_id, scope.workspace_id, str(uuid.uuid4()),
                        target_id, now,
                    ),
                )
            for event_id in sorted(event_ids):
                event = connection.execute(
                    """SELECT payload_json FROM college_events
                       WHERE actor_id=? AND workspace_id=? AND event_id=?""",
                    (scope.actor_id, scope.workspace_id, event_id),
                ).fetchone()
                payload_json = "{}"
                if event is not None:
                    event_payload = _loads(event["payload_json"], {})
                    for field in event_fields[event_id]:
                        if field == "deadline":
                            event_payload.pop("deadline", None)
                            event_payload.pop("replacement", None)
                        elif field == "learning_need":
                            event_payload = {}
                        elif field.startswith("session:"):
                            parts = field.split(":", 3)
                            observation_id = parts[2] if len(parts) > 2 else None
                            event_payload["entries"] = [
                                entry for entry in event_payload.get("entries", [])
                                if entry.get("observation_id") != observation_id
                            ]
                        else:
                            event_payload.pop(field, None)
                    payload_json = _json(event_payload)
                remaining = connection.execute(
                    """SELECT 1 FROM college_claims
                       WHERE actor_id=? AND workspace_id=? AND event_id=?
                         AND claim_status!='retracted' LIMIT 1""",
                    (scope.actor_id, scope.workspace_id, event_id),
                ).fetchone()
                marker = f"forgotten:{uuid.uuid4()}"
                connection.execute(
                    """UPDATE college_events SET payload_json=?, evidence_json='[]',
                           source_actor=CASE WHEN ? THEN 'forgotten' ELSE source_actor END,
                           source_surface_hint=NULL, semantic_payload_hash=?,
                           semantic_claim_hash=?, source_independence_key=?
                       WHERE actor_id=? AND workspace_id=? AND event_id=?""",
                    (
                        "{}" if remaining is None else payload_json,
                        remaining is None, marker, marker, marker,
                        scope.actor_id, scope.workspace_id, event_id,
                    ),
                )
            placeholders = ",".join("?" for _ in forgotten)
            connection.execute(
                f"""UPDATE college_conflicts SET reason='forgotten_dependency',
                       claim_ids_json='[]', review_status='retracted'
                   WHERE actor_id=? AND workspace_id=? AND EXISTS (
                       SELECT 1 FROM json_each(college_conflicts.claim_ids_json)
                       WHERE value IN ({placeholders})
                   )""",
                (scope.actor_id, scope.workspace_id, *sorted(forgotten)),
            )
            assessments = connection.execute(
                """SELECT assessment_id, items_json, evidence_refs_json
                   FROM college_assessments WHERE actor_id=? AND workspace_id=?""",
                (scope.actor_id, scope.workspace_id),
            ).fetchall()
            for assessment in assessments:
                items = [
                    item for item in _loads(assessment["items_json"], [])
                    if not (set(map(str, item.get("evidence_refs", []))) & forgotten)
                ]
                refs = [
                    ref for ref in _loads(assessment["evidence_refs_json"], [])
                    if str(ref) not in forgotten
                ]
                connection.execute(
                    """UPDATE college_assessments SET items_json=?, evidence_refs_json=?
                       WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                    (
                        _json(items), _json(refs), scope.actor_id, scope.workspace_id,
                        assessment["assessment_id"],
                    ),
                )
            return "applied", [*sorted(subjects), *sorted(forgotten)], []

        return self._apply_lifecycle(
            scope, identity, operation="forget_claim", payload=payload, mutation=mutation
        )

    def remove_raw_evidence(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *, evidence_id: str,
        reason: str = "raw_only_removal",
    ) -> dict[str, Any]:
        payload = {"evidence_id": evidence_id, "reason": reason}

        def mutation(connection: sqlite3.Connection, now: str):
            rows = connection.execute(
                """SELECT c.*, r.revision FROM college_claims c
                   JOIN college_field_revisions r ON r.actor_id=c.actor_id
                    AND r.workspace_id=c.workspace_id AND r.claim_id=c.claim_id
                   WHERE c.actor_id=? AND c.workspace_id=?""",
                (scope.actor_id, scope.workspace_id),
            ).fetchall()
            affected: list[str] = []
            for row in rows:
                refs = _loads(row["evidence_refs_json"], [])
                matching = [
                    ref for ref in refs
                    if isinstance(ref, dict)
                    and str(ref.get("evidence_id") or ref.get("id")) == evidence_id
                ]
                if not matching:
                    continue
                retained_support = any(
                    bool(ref.get("retained_attestation")) for ref in matching
                ) or any(
                    isinstance(ref, dict) and bool(ref.get("retained_attestation"))
                    for ref in refs if ref not in matching
                )
                retained_refs = [ref for ref in refs if ref not in matching]
                for ref in matching:
                    if ref.get("retained_attestation"):
                        retained_refs.append({
                            key: value for key, value in ref.items()
                            if key not in {"excerpt", "raw_locator", "content_locator"}
                        } | {"raw_available": False})
                connection.execute(
                    """UPDATE college_claims SET evidence_refs_json=?
                       WHERE actor_id=? AND workspace_id=? AND claim_id=?""",
                    (_json(retained_refs), scope.actor_id, scope.workspace_id, row["claim_id"]),
                )
                affected.extend([str(row["subject_id"]), str(row["claim_id"])])
                is_current = self._field_revision(
                    connection, scope, row["subject_id"], row["field"]
                ) == int(row["revision"])
                interpretation = row["source_class"] in {
                    "inferred_interpretation", "assistant_suggestion"
                }
                if is_current and interpretation and not retained_support:
                    new_id = str(uuid.uuid4())
                    connection.execute(
                        """UPDATE college_claims SET claim_status='superseded'
                           WHERE actor_id=? AND workspace_id=? AND claim_id=?""",
                        (scope.actor_id, scope.workspace_id, row["claim_id"]),
                    )
                    self._insert_lifecycle_claim(
                        connection, scope, row, claim_id=new_id,
                        value_json=row["value_json"], status="tentative",
                        certainty="unknown", supersedes=[str(row["claim_id"])],
                        revision=int(row["revision"]) + 1,
                        provenance={
                            "lifecycle": "remove_raw_evidence",
                            "reason_code": "raw_evidence_removed",
                        },
                        now=now, evidence_refs_json=_json(retained_refs),
                    )
                    affected.append(new_id)
            if not affected:
                raise CollegeDomainError(
                    "evidence_not_found", "Evidence is unavailable in this scope."
                )
            return "applied", affected, []

        return self._apply_lifecycle(
            scope, identity, operation="remove_raw_evidence",
            payload=payload, mutation=mutation,
        )

    def _record_retryable_failure(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, operation: str,
        payload_hash: str, event_ids: list[str], code: str, message: str,
    ) -> dict[str, Any]:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._receipt_lookup(connection, scope, identity, payload_hash)
            if prior:
                if prior["state"] in {"received", "retryable_failure"}:
                    return self._transition_receipt(
                        connection,
                        scope,
                        prior["receipt_id"],
                        state="retryable_failure",
                        canonical_version=None,
                        affected_ids=[],
                        review_refs=[],
                        error_code=code,
                        error_message=message,
                    )
                return prior
            return self._insert_receipt(
                connection, scope, identity, operation=operation, payload_hash=payload_hash,
                state="retryable_failure", canonical_version=None, event_ids=event_ids,
                affected_ids=[], review_refs=[], error_code=code, error_message=message,
            )

    def _record_rejection(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, operation: str,
        payload_hash: str, event_ids: list[str], code: str, message: str,
    ) -> dict[str, Any]:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._receipt_lookup(connection, scope, identity, payload_hash)
            if prior and prior["state"] == "received":
                return self._transition_receipt(
                    connection, scope, prior["receipt_id"], state="rejected",
                    canonical_version=None, affected_ids=[], review_refs=[],
                    error_code=code, error_message=message,
                )
            if prior:
                return prior
            return self._insert_receipt(
                connection, scope, identity, operation=operation,
                payload_hash=payload_hash, state="rejected", canonical_version=None,
                event_ids=event_ids, affected_ids=[], review_refs=[],
                error_code=code, error_message=message,
            )

    @staticmethod
    def _invalidate_assessments(
        connection: sqlite3.Connection, scope: CollegeScope, reason: str,
        affected_ids: list[str], now: str,
    ) -> None:
        if not affected_ids:
            return
        placeholders = ",".join("?" for _ in affected_ids)
        rows = connection.execute(
            f"""SELECT DISTINCT a.assessment_id FROM college_assessments a
                JOIN college_assessment_dependencies d
                  ON d.actor_id=a.actor_id AND d.workspace_id=a.workspace_id
                 AND d.assessment_id=a.assessment_id
                WHERE a.actor_id=? AND a.workspace_id=? AND a.lifecycle='ready'
                  AND a.invalidated_at IS NULL AND d.dependency_id IN ({placeholders})""",
            (scope.actor_id, scope.workspace_id, *affected_ids),
        ).fetchall()
        for row in rows:
            connection.execute(
                """UPDATE college_assessments SET invalidated_at=?, invalidation_reason=?
                   WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                (now, f"{reason}:{','.join(sorted(set(affected_ids)))}",
                 scope.actor_id, scope.workspace_id, row["assessment_id"]),
            )

    # -- explicit assessment production --------------------------------

    @staticmethod
    def _assessment_request_payload(
        *, authorized_scope: dict[str, Any], horizon: dict[str, Any],
        timezone_name: str, valid_through: datetime, baseline: dict[str, Any] | None,
        window: dict[str, Any] | None, context_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "authorized_scope": authorized_scope,
            "horizon": horizon,
            "timezone": timezone_name,
            "valid_through": _iso(valid_through),
            "baseline": baseline,
            "window": window,
            "context_snapshot_id": (context_snapshot or {}).get("snapshot_id"),
            "context_snapshot_version": (context_snapshot or {}).get("version"),
            "context_assessment_generation": (
                context_snapshot or {}
            ).get("assessment_generation"),
        }

    def queue_assessment(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *,
        authorized_scope: dict[str, Any], horizon: dict[str, Any], timezone_name: str,
        valid_through: datetime, baseline: dict[str, Any] | None = None,
        window: dict[str, Any] | None = None,
        context_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Durably accept an assessment request and persist its queued state."""
        payload = self._assessment_request_payload(
            authorized_scope=authorized_scope, horizon=horizon,
            timezone_name=timezone_name, valid_through=valid_through,
            baseline=baseline, window=window, context_snapshot=context_snapshot,
        )
        _reject_server_identity(payload)
        payload_hash = self._fingerprint({"operation": "request_assessment", **payload})
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._receipt_lookup(connection, scope, identity, payload_hash)
            if prior:
                if prior["state"] == "retryable_failure":
                    assessment = connection.execute(
                        """SELECT assessment_id, lifecycle FROM college_assessments
                           WHERE actor_id=? AND workspace_id=? AND receipt_id=?""",
                        (scope.actor_id, scope.workspace_id, prior["receipt_id"]),
                    ).fetchone()
                    if assessment is not None and assessment["lifecycle"] == "failed":
                        now = _iso(self.clock())
                        connection.execute(
                            """UPDATE college_assessments SET lifecycle='queued', failure_json=NULL
                               WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                            (scope.actor_id, scope.workspace_id, assessment["assessment_id"]),
                        )
                        sequence = connection.execute(
                            """SELECT MAX(sequence)+1 FROM college_assessment_transitions
                               WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                            (scope.actor_id, scope.workspace_id, assessment["assessment_id"]),
                        ).fetchone()[0]
                        connection.execute(
                            "INSERT INTO college_assessment_transitions VALUES (?, ?, ?, ?, 'queued', ?)",
                            (
                                scope.actor_id, scope.workspace_id,
                                assessment["assessment_id"], sequence, now,
                            ),
                        )
                        return self._transition_receipt(
                            connection, scope, prior["receipt_id"], state="received",
                            canonical_version=None,
                            affected_ids=[assessment["assessment_id"]], review_refs=[],
                        )
                return prior
            now = _iso(self.clock())
            assessment_id = str(uuid.uuid4())
            receipt_id = str(uuid.uuid4())
            version = self._metadata(connection, scope)
            connection.execute(
                """INSERT INTO college_assessments VALUES
                   (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', ?, ?, '[]', '[]', '[]', NULL, NULL, NULL)""",
                (
                    scope.actor_id, scope.workspace_id, assessment_id, receipt_id,
                    COLLEGE_ASSESSMENT_VERSION, COLLEGE_RULE_VERSION, version,
                    payload["context_snapshot_id"],
                    str(payload["context_snapshot_version"])
                    if payload["context_snapshot_version"] is not None else None,
                    _json(authorized_scope), now, payload["valid_through"], timezone_name,
                    _json(horizon), _json(baseline) if baseline is not None else None,
                    _json(window) if window is not None else None,
                ),
            )
            connection.execute(
                "INSERT INTO college_assessment_transitions VALUES (?, ?, ?, 1, 'queued', ?)",
                (scope.actor_id, scope.workspace_id, assessment_id, now),
            )
            return self._insert_receipt(
                connection, scope, identity, operation="request_assessment",
                payload_hash=payload_hash, state="received", canonical_version=None,
                event_ids=[], affected_ids=[assessment_id], review_refs=[],
                receipt_id=receipt_id,
            )

    def start_assessment(
        self, scope: CollegeScope, *, assessment_id: str,
    ) -> dict[str, Any]:
        """Persist the running boundary without computing or publishing a result."""
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM college_assessments
                   WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                (scope.actor_id, scope.workspace_id, assessment_id),
            ).fetchone()
            if row is None:
                raise CollegeDomainError("assessment_not_found", "Assessment is unavailable.")
            if row["lifecycle"] == "running":
                return self._assessment(row)
            if row["lifecycle"] != "queued":
                raise CollegeDomainError(
                    "assessment_transition_conflict",
                    "Only a queued assessment can start.",
                )
            now = _iso(self.clock())
            connection.execute(
                """UPDATE college_assessments SET lifecycle='running', assessed_at=?
                   WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                (now, scope.actor_id, scope.workspace_id, assessment_id),
            )
            sequence = connection.execute(
                """SELECT MAX(sequence)+1 FROM college_assessment_transitions
                   WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                (scope.actor_id, scope.workspace_id, assessment_id),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO college_assessment_transitions VALUES (?, ?, ?, ?, 'running', ?)",
                (scope.actor_id, scope.workspace_id, assessment_id, sequence, now),
            )
            return self._assessment(connection.execute(
                """SELECT * FROM college_assessments
                   WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                (scope.actor_id, scope.workspace_id, assessment_id),
            ).fetchone())

    def fail_assessment(
        self, scope: CollegeScope, *, assessment_id: str, code: str,
        message: str, retryable: bool,
    ) -> dict[str, Any]:
        """Persist a known no-result assessment failure and its retry semantics."""
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT receipt_id, lifecycle FROM college_assessments
                   WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                (scope.actor_id, scope.workspace_id, assessment_id),
            ).fetchone()
            if row is None:
                raise CollegeDomainError("assessment_not_found", "Assessment is unavailable.")
            if row["lifecycle"] == "ready":
                raise CollegeDomainError(
                    "assessment_transition_conflict", "A ready assessment cannot fail.",
                )
            now = _iso(self.clock())
            failure = {"code": code, "retryable": retryable}
            connection.execute(
                """UPDATE college_assessments SET lifecycle='failed', failure_json=?
                   WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                (_json(failure), scope.actor_id, scope.workspace_id, assessment_id),
            )
            if row["lifecycle"] != "failed":
                sequence = connection.execute(
                    """SELECT MAX(sequence)+1 FROM college_assessment_transitions
                       WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                    (scope.actor_id, scope.workspace_id, assessment_id),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO college_assessment_transitions VALUES (?, ?, ?, ?, 'failed', ?)",
                    (scope.actor_id, scope.workspace_id, assessment_id, sequence, now),
                )
            return self._transition_receipt(
                connection, scope, row["receipt_id"],
                state="retryable_failure" if retryable else "rejected",
                canonical_version=None, affected_ids=[assessment_id], review_refs=[],
                error_code=code, error_message=message,
            )

    def request_assessment(
        self, scope: CollegeScope, identity: CollegeCommandIdentity, *,
        authorized_scope: dict[str, Any], horizon: dict[str, Any], timezone_name: str,
        valid_through: datetime, baseline: dict[str, Any] | None = None,
        window: dict[str, Any] | None = None,
        context_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._assessment_request_payload(
            authorized_scope=authorized_scope, horizon=horizon,
            timezone_name=timezone_name, valid_through=valid_through,
            baseline=baseline, window=window, context_snapshot=context_snapshot,
        )
        _reject_server_identity(payload)
        payload_hash = self._fingerprint({"operation": "request_assessment", **payload})
        context_id = payload["context_snapshot_id"]
        initial_context_version = payload["context_snapshot_version"]
        initial_context_generation = payload["context_assessment_generation"]
        if context_id and self.context_version_reader:
            live = self.context_version_reader(scope, context_id)
            if str(live) != str(initial_context_version):
                return self._record_retryable_failure(
                    scope, identity, "request_assessment", payload_hash, [],
                    "context_snapshot_stale", "SID-151 context snapshot changed before assessment.",
                )
        queued = self.queue_assessment(
            scope, identity, authorized_scope=authorized_scope, horizon=horizon,
            timezone_name=timezone_name, valid_through=valid_through,
            baseline=baseline, window=window, context_snapshot=context_snapshot,
        )
        if queued["state"] not in {"received", "retryable_failure"}:
            return queued
        assessment_id = queued["affected_ids"][0]
        self.start_assessment(scope, assessment_id=assessment_id)
        try:
            with database_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                prior = self._receipt_lookup(connection, scope, identity, payload_hash)
                retry_receipt_id = None
                if prior and prior["state"] not in {"received", "retryable_failure"}:
                    return prior
                if prior:
                    retry_receipt_id = prior["receipt_id"]
                version = self._metadata(connection, scope)
                if (
                    initial_context_generation is not None
                    and self._sid151_generation(connection, scope)
                    != int(initial_context_generation)
                ):
                    raise CollegeDomainError(
                        "assessment_input_race",
                        "SID-151 context generation changed before assessment.",
                    )
                receipt_id = retry_receipt_id or str(uuid.uuid4())
                assessed_at = _iso(self.clock())
                coverage = self._coverage_snapshot(connection, scope)
                claims = self._claim_snapshot(connection, scope, authorized_scope)
                conflicts = self._conflict_snapshot(connection, scope, authorized_scope)
                context_items = self._active_context_items(context_snapshot, assessed_at)
                self._fail("assessment_running")
                items = self._build_attention(
                    claims, conflicts, coverage, context_items,
                    assessed_at=assessed_at, horizon=horizon,
                )
                current_version = self._metadata(connection, scope)
                if current_version != version:
                    raise CollegeDomainError("assessment_input_race", "Canonical input changed during assessment.")
                if context_id and self.context_version_reader:
                    live = self.context_version_reader(scope, context_id)
                    if str(live) != str(initial_context_version):
                        raise CollegeDomainError("assessment_input_race", "Context input changed during assessment.")
                omissions = [
                    {"provider": item["provider"], "account_id": item["account_id"],
                     "reason": item["reason"] or item["omission_reason"] or
                               f"{item['availability']}/{item['completeness']}/{item['freshness']}"}
                    for item in coverage
                    if item["availability"] != "healthy"
                    or item["completeness"] != "complete"
                    or item["freshness"] != "fresh"
                ]
                present_coverage = {
                    (item["provider"], item["account_id"])
                    for item in coverage
                }
                for expected in authorized_scope.get("expected_coverage", []):
                    key = (expected.get("provider"), expected.get("account_id"))
                    if key not in present_coverage:
                        omissions.append({
                            "provider": expected.get("provider"),
                            "account_id": expected.get("account_id"),
                            "reason": "no_coverage_record",
                        })
                evidence_refs = sorted({ref for item in items for ref in item["evidence_refs"]})
                transient_refs = [str(item.get("item_id")) for item in context_items if item.get("item_id")]
                connection.execute(
                    """UPDATE college_assessments SET lifecycle='ready',
                           canonical_input_version=?, context_snapshot_id=?,
                           context_snapshot_version=?, authorized_scope_json=?,
                           assessed_at=?, valid_through=?, timezone=?, horizon_json=?,
                           coverage_json=?, omissions_json=?, baseline_json=?, window_json=?,
                           evidence_refs_json=?, transient_context_refs_json=?, items_json=?,
                           invalidated_at=NULL, invalidation_reason=NULL, failure_json=NULL
                       WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                    (
                        version, context_id,
                        str(initial_context_version) if initial_context_version is not None else None,
                        _json(authorized_scope), assessed_at, _iso(valid_through), timezone_name,
                        _json(horizon), _json(coverage), _json(omissions),
                        _json(baseline) if baseline is not None else None,
                        _json(window) if window is not None else None,
                        _json(evidence_refs), _json(transient_refs), _json(items),
                        scope.actor_id, scope.workspace_id, assessment_id,
                    ),
                )
                sequence = connection.execute(
                    """SELECT MAX(sequence)+1 FROM college_assessment_transitions
                       WHERE actor_id=? AND workspace_id=? AND assessment_id=?""",
                    (scope.actor_id, scope.workspace_id, assessment_id),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO college_assessment_transitions VALUES (?, ?, ?, ?, 'ready', ?)",
                    (scope.actor_id, scope.workspace_id, assessment_id, sequence, assessed_at),
                )
                for claim in claims:
                    connection.execute(
                        "INSERT OR IGNORE INTO college_assessment_dependencies VALUES (?, ?, ?, 'claim', ?, ?)",
                        (scope.actor_id, scope.workspace_id, assessment_id, claim["claim_id"],
                         str(claim["revision"])),
                    )
                for subject_id in sorted({claim["subject_id"] for claim in claims} | set(authorized_scope.get("subject_ids") or [])):
                    connection.execute(
                        "INSERT OR IGNORE INTO college_assessment_dependencies VALUES (?, ?, ?, 'subject', ?, NULL)",
                        (scope.actor_id, scope.workspace_id, assessment_id, subject_id),
                    )
                for coverage_item in coverage:
                    connection.execute(
                        "INSERT OR IGNORE INTO college_assessment_dependencies VALUES (?, ?, ?, 'coverage', ?, NULL)",
                        (scope.actor_id, scope.workspace_id, assessment_id,
                         coverage_item["coverage_id"]),
                    )
                if context_id:
                    connection.execute(
                        "INSERT INTO college_assessment_dependencies VALUES (?, ?, ?, 'context_snapshot', ?, ?)",
                        (scope.actor_id, scope.workspace_id, assessment_id, context_id,
                        str(initial_context_version)),
                    )
                if initial_context_generation is not None:
                    connection.execute(
                        "INSERT INTO college_assessment_dependencies VALUES (?, ?, ?, 'context_generation', 'sid151', ?)",
                        (
                            scope.actor_id,
                            scope.workspace_id,
                            assessment_id,
                            str(initial_context_generation),
                        ),
                    )
                self._fail("before_assessment_publication")
                if retry_receipt_id:
                    return self._transition_receipt(
                        connection, scope, retry_receipt_id, state="applied",
                        canonical_version=version, affected_ids=[assessment_id],
                        review_refs=[],
                    )
                return self._insert_receipt(
                    connection, scope, identity, operation="request_assessment",
                    payload_hash=payload_hash, state="applied", canonical_version=version,
                    event_ids=[], affected_ids=[assessment_id], review_refs=[],
                    receipt_id=receipt_id,
                )
        except CollegeDomainError as exc:
            if exc.code != "assessment_input_race":
                raise
            return self.fail_assessment(
                scope, assessment_id=assessment_id, code=exc.code,
                message=str(exc), retryable=True,
            )
        except Exception as exc:
            return self.fail_assessment(
                scope, assessment_id=assessment_id, code="assessment_failure",
                message=str(exc), retryable=True,
            )

    @staticmethod
    def _active_context_items(snapshot: dict[str, Any] | None, assessed_at: str) -> list[dict[str, Any]]:
        result = []
        for item in (snapshot or {}).get("items", []):
            expires_at = item.get("expires_at")
            if expires_at and _iso(expires_at) <= assessed_at:
                continue
            if item.get("status", "active") == "active":
                result.append(item)
        return result

    @staticmethod
    def _coverage_snapshot(connection: sqlite3.Connection, scope: CollegeScope) -> list[dict[str, Any]]:
        rows = connection.execute(
            """SELECT c.* FROM college_coverage c
               WHERE c.actor_id=? AND c.workspace_id=?
                 AND NOT EXISTS (
                   SELECT 1 FROM college_coverage newer
                   WHERE newer.actor_id=c.actor_id AND newer.workspace_id=c.workspace_id
                     AND newer.provider=c.provider AND newer.account_id=c.account_id
                     AND newer.scope_json=c.scope_json
                     AND (newer.recorded_at > c.recorded_at OR
                          (newer.recorded_at = c.recorded_at AND newer.coverage_id > c.coverage_id))
                 )
               ORDER BY c.provider, c.account_id""",
            (scope.actor_id, scope.workspace_id),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for name in ("scope_json", "bounds_json", "freshness_policy_json"):
                item[name.removesuffix("_json")] = _loads(item.pop(name), {})
            result.append(item)
        return result

    @staticmethod
    def _claim_snapshot(
        connection: sqlite3.Connection, scope: CollegeScope, authorized_scope: dict[str, Any],
    ) -> list[dict[str, Any]]:
        subject_ids = authorized_scope.get("subject_ids") or []
        params: list[Any] = [scope.actor_id, scope.workspace_id]
        clause = ""
        if subject_ids:
            clause = f" AND c.subject_id IN ({','.join('?' for _ in subject_ids)})"
            params.extend(subject_ids)
        rows = connection.execute(
            f"""SELECT c.*, r.revision FROM college_claims c
                JOIN college_field_revisions r ON r.actor_id=c.actor_id
                 AND r.workspace_id=c.workspace_id AND r.claim_id=c.claim_id
                WHERE c.actor_id=? AND c.workspace_id=?
                  AND c.claim_status IN ('active','tentative','conflicted') {clause}
                ORDER BY c.subject_id, c.field, r.revision, c.claim_id""",
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["value"] = _loads(item.pop("value_json"))
            item["evidence_refs"] = _loads(item.pop("evidence_refs_json"), [])
            result.append(item)
        return result

    @staticmethod
    def _conflict_snapshot(
        connection: sqlite3.Connection, scope: CollegeScope, authorized_scope: dict[str, Any],
    ) -> list[dict[str, Any]]:
        subject_ids = authorized_scope.get("subject_ids") or []
        params: list[Any] = [scope.actor_id, scope.workspace_id]
        clause = ""
        if subject_ids:
            clause = f" AND subject_id IN ({','.join('?' for _ in subject_ids)})"
            params.extend(subject_ids)
        rows = connection.execute(
            f"SELECT * FROM college_conflicts WHERE actor_id=? AND workspace_id=? AND review_status='open' {clause} ORDER BY created_at, conflict_id",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def _build_attention(
        self,
        claims: list[dict[str, Any]], conflicts: list[dict[str, Any]],
        coverage: list[dict[str, Any]], context_items: list[dict[str, Any]], *,
        assessed_at: str, horizon: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        by_subject: dict[str, dict[str, Any]] = {}
        for claim in claims:
            by_subject.setdefault(claim["subject_id"], {})[claim["field"]] = claim["value"]
        horizon_end = str(horizon.get("end") or "")
        for conflict in conflicts:
            candidates.append({
                "category": "current_conflicts_blockers", "subject_id": conflict["subject_id"],
                "summary": f"Review conflicting {conflict['field']} evidence.",
                "evidence_refs": [conflict["conflict_id"]], "certainty": "confirmed",
            })
        for claim in claims:
            field, value = claim["field"], claim["value"]
            subject_facts = by_subject[claim["subject_id"]]
            requirement = subject_facts.get("requirement")
            completion = subject_facts.get("completion")
            deadline = subject_facts.get("deadline")
            due_lower = deadline.get("value") if isinstance(deadline, dict) else None
            if isinstance(due_lower, dict):
                due_lower = due_lower.get("lower") or due_lower.get("start")
            if due_lower is not None and not isinstance(due_lower, str):
                due_lower = None
            category = "relevant_changes"
            if claim["claim_status"] in {"tentative", "conflicted"}:
                category = "material_unknowns"
            elif field == "requirement" and value == "required":
                if completion == "finished":
                    category = "relevant_changes"
                elif due_lower and due_lower < assessed_at[:len(due_lower)]:
                    category = "current_conflicts_blockers"
                elif not due_lower or not horizon_end or due_lower <= horizon_end[:len(due_lower)]:
                    category = "required_obligations"
            elif field == "deadline":
                if completion == "finished" or requirement in {"waived", "canceled"}:
                    category = "relevant_changes"
                elif requirement in {"optional", "recommended"}:
                    category = "optional_recommended_opportunities"
                elif requirement == "required":
                    category = (
                        "current_conflicts_blockers"
                        if due_lower and due_lower < assessed_at[:len(due_lower)]
                        else "required_obligations"
                    )
                else:
                    category = "material_unknowns"
            elif field == "learning_need" or (
                field == "understanding" and value not in {"understood", "mastered"}
            ):
                category = (
                    "preparation_pressure"
                    if requirement == "required" and due_lower
                    and (not horizon_end or due_lower <= horizon_end[:len(due_lower)])
                    else "learning_needs"
                )
            elif field.endswith(":coordination_blocker") or field == "coordination_blocker":
                category = "coordination_blockers"
            elif field in {"opportunity", "requirement"} and (
                field == "opportunity" or value in {"optional", "recommended"}
            ):
                category = "optional_recommended_opportunities"
            evidence_refs = [claim["claim_id"]]
            for ref in claim.get("evidence_refs", []):
                if isinstance(ref, dict):
                    evidence_refs.append(str(ref.get("evidence_id") or ref.get("id") or self._fingerprint(ref)))
                else:
                    evidence_refs.append(str(ref))
            candidates.append({
                "category": category, "subject_id": claim["subject_id"],
                "summary": f"{field}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}",
                "evidence_refs": sorted(set(evidence_refs)), "certainty": claim["certainty"],
                "semantic_key": claim["semantic_claim_hash"],
                "due_lower_bound": due_lower,
                "field": field,
                "revision": claim["revision"],
            })
        selected_subjects = {
            claim["subject_id"] for claim in claims
            if claim["field"] == "attendance_intent" and claim["value"] == "selected"
        }
        for subject_id in selected_subjects:
            candidates.append({
                "category": "relevant_changes", "subject_id": subject_id,
                "summary": "Selected commitment consumes capacity regardless of provider free/busy.",
                "evidence_refs": [
                    claim["claim_id"] for claim in claims
                    if claim["subject_id"] == subject_id
                    and claim["field"] in {"attendance_intent", "provider_free_busy"}
                ],
                "certainty": "confirmed",
                "force_summary": True,
            })
        for item in context_items:
            if item.get("context_kind") == "situational" and item.get("resolution_state") != "resolved":
                candidates.append({
                    "category": "current_conflicts_blockers",
                    "subject_id": str(item.get("scope", "context")),
                    "summary": "A current situational limitation affects feasibility.",
                    "evidence_refs": [str(item.get("item_id", "context"))],
                    "certainty": item.get("certainty", "unknown"),
                })
        for item in coverage:
            material = bool(item.get("bounds", {}).get("material_to_scope", False))
            if material and (item["availability"] != "healthy" or item["completeness"] != "complete"):
                candidates.append({
                    "category": "material_unknowns",
                    "subject_id": f"coverage:{item['provider']}:{item['account_id']}",
                    "summary": f"{item['provider']} coverage is {item['availability']}/{item['completeness']}/{item['freshness']}.",
                    "evidence_refs": [item["coverage_id"]], "certainty": "unknown",
                })
        deduped: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            key = candidate.get("semantic_key") or self._fingerprint({
                "category": candidate["category"], "subject": candidate["subject_id"],
                "summary": candidate["summary"],
            })
            if key not in deduped:
                deduped[key] = candidate
        one_per_subject: dict[str, dict[str, Any]] = {}
        for candidate in deduped.values():
            subject = candidate["subject_id"]
            current = one_per_subject.get(subject)
            if current is None:
                candidate = dict(candidate)
                candidate["categories"] = [candidate["category"]]
                one_per_subject[subject] = candidate
            elif (
                PRIORITY_BANDS[candidate["category"]] < PRIORITY_BANDS[current["category"]]
                or candidate.get("force_summary")
            ):
                replacement = dict(candidate)
                replacement["categories"] = sorted(
                    set(current.get("categories", [])) | {candidate["category"]}
                )
                replacement["evidence_refs"] = sorted(
                    set(current["evidence_refs"]) | set(candidate["evidence_refs"])
                )
                one_per_subject[subject] = replacement
            else:
                current["categories"] = sorted(set(current.get("categories", [])) | {candidate["category"]})
                current["evidence_refs"] = sorted(set(current["evidence_refs"]) | set(candidate["evidence_refs"]))
        return sorted(
            one_per_subject.values(),
            key=lambda item: (
                PRIORITY_BANDS[item["category"]],
                item.get("due_lower_bound") is None,
                item.get("due_lower_bound") or "",
                item["subject_id"], item.get("field", ""), item.get("revision", 0),
                item["summary"], item["evidence_refs"][0] if item["evidence_refs"] else "",
            ),
        )

    # -- side-effect-free internal inspection ---------------------------

    def get_receipt(self, scope: CollegeScope, *, command_id: str) -> dict[str, Any] | None:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=? AND command_id=?",
                (scope.actor_id, scope.workspace_id, command_id),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """SELECT r.* FROM college_receipt_aliases a JOIN college_receipts r
                         ON r.actor_id=a.actor_id AND r.workspace_id=a.workspace_id
                        AND r.receipt_id=a.receipt_id
                       WHERE a.actor_id=? AND a.workspace_id=? AND a.command_id=?""",
                    (scope.actor_id, scope.workspace_id, command_id),
                ).fetchone()
        return self._receipt(row) if row else None

    def inspect_state(self, scope: CollegeScope) -> dict[str, Any]:
        with database_connection() as connection:
            version = self._metadata_read_only(connection, scope)
            identities = [dict(row) for row in connection.execute(
                "SELECT * FROM college_identities WHERE actor_id=? AND workspace_id=? ORDER BY identity_kind, canonical_id",
                (scope.actor_id, scope.workspace_id),
            ).fetchall()]
            claims = self._claim_snapshot(connection, scope, {})
            conflicts = self._conflict_snapshot(connection, scope, {})
            coverage = self._coverage_snapshot(connection, scope)
            assessments = [
                self._assessment_with_validity(connection, scope, row)
                for row in connection.execute(
                    "SELECT * FROM college_assessments WHERE actor_id=? AND workspace_id=? ORDER BY assessed_at, assessment_id",
                    (scope.actor_id, scope.workspace_id),
                ).fetchall()
            ]
        return {"canonical_version": version, "identities": identities, "claims": claims,
                "conflicts": conflicts, "coverage": coverage, "assessments": assessments}

    @staticmethod
    def _metadata_read_only(connection: sqlite3.Connection, scope: CollegeScope) -> int:
        row = connection.execute(
            "SELECT canonical_version FROM college_metadata WHERE actor_id=? AND workspace_id=?",
            (scope.actor_id, scope.workspace_id),
        ).fetchone()
        return int(row["canonical_version"]) if row else 0

    @staticmethod
    def _assessment(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for name in (
            "authorized_scope_json", "horizon_json", "coverage_json", "omissions_json",
            "baseline_json", "window_json", "evidence_refs_json",
            "transient_context_refs_json", "items_json", "failure_json",
        ):
            item[name.removesuffix("_json")] = _loads(item.pop(name))
        if item["lifecycle"] == "ready":
            item["result_kind"] = (
                "attention_items_available" if item["items"] else "insufficient_evidence"
            )
        return item

    def _assessment_with_validity(
        self, connection: sqlite3.Connection, scope: CollegeScope, row: sqlite3.Row,
    ) -> dict[str, Any]:
        item = self._assessment(row)
        reason = None
        if item["lifecycle"] != "ready":
            reason = f"lifecycle_{item['lifecycle']}"
        elif item["invalidated_at"] is not None:
            reason = "invalidated"
        elif item["valid_through"] <= _iso(self.clock()):
            reason = "expired"
        dependency = connection.execute(
            """SELECT dependency_version FROM college_assessment_dependencies
               WHERE actor_id=? AND workspace_id=? AND assessment_id=?
                 AND dependency_kind='context_generation' AND dependency_id='sid151'""",
            (scope.actor_id, scope.workspace_id, item["assessment_id"]),
        ).fetchone()
        if (
            reason is None
            and dependency is not None
            and int(dependency["dependency_version"]) != self._sid151_generation(connection, scope)
        ):
            reason = "stale_context_generation"
        item["current"] = reason is None
        item["validity"] = "current" if reason is None else "historical"
        item["unusable_reason"] = reason
        item["transitions"] = [
            dict(transition)
            for transition in connection.execute(
                """SELECT sequence, lifecycle, recorded_at
                   FROM college_assessment_transitions
                   WHERE actor_id=? AND workspace_id=? AND assessment_id=?
                   ORDER BY sequence""",
                (scope.actor_id, scope.workspace_id, item["assessment_id"]),
            ).fetchall()
        ]
        return item


__all__ = [
    "COLLEGE_ASSESSMENT_VERSION", "COLLEGE_EVENT_VERSION", "COLLEGE_RULE_VERSION",
    "CollegeCommandIdentity", "CollegeDomainError", "CollegeDomainService", "CollegeScope",
]
