"""SID-151 durable shared conversation context and capture lifecycle.

This module deliberately exposes an application-service boundary rather than HTTP or
MCP endpoints.  Callers must construct :class:`ContextScope` from trusted
authentication; actor/workspace identifiers are never accepted inside command
payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from typing import Any, Callable, Literal

from .storage import database_connection


RAW_RETENTION_DAYS = 7
MAX_CONTEXT_BYTES = 16_000
MAX_STATE_BYTES = 24_000
MAX_RAW_BYTES = 64_000
MAX_MINIMAL_ATTESTATION_BYTES = 2_000
MAX_RETRIEVAL_LIMIT = 100
SCHEMA_VERSION = 1
KEY_CHECK_MESSAGE = b"sid-151-fingerprint-key-check-v1"
MINIMAL_ATTESTATION_KEYS = {
    "subject_ref", "field", "normalized_value", "source_verified"
}


class ContextStoreError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ContextScope:
    """Server-derived authorization scope."""

    actor_id: str
    workspace_id: str

    def __post_init__(self) -> None:
        if not self.actor_id.strip() or not self.workspace_id.strip():
            raise ContextStoreError("invalid_scope", "Actor and workspace are required.")


@dataclass(frozen=True)
class CommandIdentity:
    command_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.command_id.strip() or not self.idempotency_key.strip():
            raise ContextStoreError(
                "invalid_command_identity", "Command ID and idempotency key are required."
            )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ContextStoreError("timezone_required", "Timestamps must include a timezone.")
    return value.astimezone(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _bounded_json(value: Any, maximum: int, field: str) -> str:
    serialized = _json(value)
    if len(serialized.encode("utf-8")) > maximum:
        raise ContextStoreError("content_too_large", f"{field} exceeds its bounded size.")
    return serialized


class SharedConversationContextService:
    """Transactional SID-151 persistence, lifecycle, and bounded retrieval."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _now,
        pending_action_authorizer: Callable[[ContextScope, str, str], bool] | None = None,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.clock = clock
        self.pending_action_authorizer = pending_action_authorizer
        self.failure_injector = failure_injector
        self._verify_ready()

    # -- schema -----------------------------------------------------------

    @classmethod
    def initialize_schema(cls) -> None:
        """Create or migrate SID-151 storage at an explicit startup boundary."""
        with database_connection() as connection:
            journal_mode = str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0])
            if journal_mode.lower() != "delete":
                raise ContextStoreError(
                    "unsafe_journal_mode",
                    "SID-151 requires SQLite DELETE journaling for bounded local erasure.",
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS context_store_metadata (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_capture_consents (
                    consent_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_version TEXT NOT NULL,
                    capture_enabled INTEGER NOT NULL,
                    sensitive_retention INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    granted_at TEXT NOT NULL,
                    revoked_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(actor_id, workspace_id, scope, scope_version)
                );
                CREATE INDEX IF NOT EXISTS idx_context_consents_scope
                    ON context_capture_consents(actor_id, workspace_id, scope, updated_at DESC);

                CREATE TABLE IF NOT EXISTS context_command_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    command_kind TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('applied', 'needs_review', 'rejected')),
                    target_ids_json TEXT NOT NULL,
                    target_revisions_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(actor_id, workspace_id, command_id),
                    UNIQUE(actor_id, workspace_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS conversation_states (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    pending_action_id TEXT,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, conversation_id)
                );

                CREATE TABLE IF NOT EXISTS context_questions (
                    question_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    disposition TEXT NOT NULL CHECK(disposition IN ('asked', 'answered', 'deferred')),
                    prompt_key TEXT NOT NULL,
                    answer_summary TEXT,
                    conversation_id TEXT,
                    revision INTEGER NOT NULL,
                    asked_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, question_id)
                );
                CREATE INDEX IF NOT EXISTS idx_context_questions_disposition
                    ON context_questions(actor_id, workspace_id, disposition, updated_at DESC);

                CREATE TABLE IF NOT EXISTS course_context_bindings (
                    binding_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    term_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    binding_scope TEXT NOT NULL,
                    conversation_id TEXT,
                    attested_surface_id TEXT,
                    review_provenance TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    revoked_at TEXT,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, binding_id)
                );
                CREATE INDEX IF NOT EXISTS idx_course_context_binding_lookup
                    ON course_context_bindings(actor_id, workspace_id, conversation_id, valid_until);

                CREATE TABLE IF NOT EXISTS raw_conversation_evidence (
                    evidence_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    source_identity TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    asserted_at TEXT NOT NULL,
                    content TEXT,
                    sensitive INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    removed_at TEXT,
                    removal_reason TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, evidence_id)
                );

                CREATE TABLE IF NOT EXISTS shared_context_items (
                    item_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    context_kind TEXT NOT NULL CHECK(context_kind IN (
                        'narrative', 'preference', 'learning_reference', 'summary',
                        'operational_attestation', 'situational'
                    )),
                    scope TEXT NOT NULL,
                    scope_version TEXT NOT NULL,
                    conversation_id TEXT,
                    binding_id TEXT,
                    content_json TEXT,
                    attestation_json TEXT,
                    raw_evidence_id TEXT,
                    source_identity TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    asserted_at TEXT NOT NULL,
                    certainty TEXT NOT NULL CHECK(certainty IN ('confirmed', 'probable', 'possible', 'unknown')),
                    status TEXT NOT NULL CHECK(status IN (
                        'active', 'needs_review', 'superseded', 'resolved', 'retracted', 'forgotten'
                    )),
                    sensitive INTEGER NOT NULL,
                    requires_raw_context INTEGER NOT NULL,
                    expires_at TEXT,
                    expiry_basis TEXT,
                    resolution_state TEXT CHECK(resolution_state IN ('unresolved', 'resolved', 'unknown') OR resolution_state IS NULL),
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, item_id)
                );
                CREATE INDEX IF NOT EXISTS idx_shared_context_retrieval
                    ON shared_context_items(actor_id, workspace_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS shared_context_revisions (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    content_json TEXT,
                    attestation_json TEXT,
                    certainty TEXT NOT NULL,
                    status TEXT NOT NULL,
                    lifecycle_kind TEXT NOT NULL,
                    reason TEXT,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, item_id, revision)
                );

                CREATE TABLE IF NOT EXISTS context_dependencies (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    source_item_id TEXT NOT NULL,
                    dependent_item_id TEXT NOT NULL,
                    dependency_kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, source_item_id, dependent_item_id)
                );

                CREATE TABLE IF NOT EXISTS context_caches (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    content_json TEXT,
                    status TEXT NOT NULL CHECK(status IN ('current', 'invalidated')),
                    created_at TEXT NOT NULL,
                    invalidated_at TEXT,
                    PRIMARY KEY(actor_id, workspace_id, cache_key)
                );

                CREATE TABLE IF NOT EXISTS context_cache_dependencies (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    source_item_id TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, cache_key, source_item_id)
                );

                CREATE TABLE IF NOT EXISTS context_tombstones (
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    lifecycle_marker TEXT NOT NULL,
                    dependency_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, target_id)
                );

                CREATE TABLE IF NOT EXISTS interaction_baselines (
                    baseline_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    consumer TEXT NOT NULL,
                    cursor_json TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    advanced_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id, workspace_id, baseline_id)
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            key_row = connection.execute(
                "SELECT value FROM context_store_metadata WHERE key='hmac_key'"
            ).fetchone()
            protected_state = connection.execute(
                """SELECT EXISTS(
                       SELECT 1 FROM context_command_receipts
                       UNION ALL SELECT 1 FROM context_tombstones
                       UNION ALL SELECT 1 FROM shared_context_items
                   )"""
            ).fetchone()[0]
            if key_row is None:
                if protected_state:
                    raise ContextStoreError(
                        "fingerprint_key_unavailable",
                        "The command fingerprint key is missing from a populated context store.",
                    )
                key = secrets.token_bytes(32)
                connection.execute(
                    "INSERT INTO context_store_metadata(key, value) VALUES ('hmac_key', ?)",
                    (key,),
                )
            else:
                key = bytes(key_row["value"])
            if len(key) != 32:
                raise ContextStoreError(
                    "fingerprint_key_invalid", "The command fingerprint key is invalid."
                )
            expected_check = cls._key_check(key)
            check_row = connection.execute(
                "SELECT value FROM context_store_metadata WHERE key='hmac_key_check'"
            ).fetchone()
            if check_row is None:
                connection.execute(
                    "INSERT INTO context_store_metadata(key, value) VALUES ('hmac_key_check', ?)",
                    (expected_check,),
                )
            elif not hmac.compare_digest(bytes(check_row["value"]), expected_check):
                raise ContextStoreError(
                    "fingerprint_key_mismatch",
                    "The command fingerprint key does not match its durable verifier.",
                )
            connection.execute(
                """INSERT INTO context_store_metadata(key, value) VALUES ('schema_version', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (str(SCHEMA_VERSION).encode(),),
            )

    def _verify_ready(self) -> None:
        try:
            with database_connection() as connection:
                journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
                if journal_mode.lower() != "delete":
                    raise ContextStoreError(
                        "unsafe_journal_mode",
                        "SID-151 storage must be initialized with DELETE journaling.",
                    )
                if not int(connection.execute("PRAGMA secure_delete").fetchone()[0]):
                    raise ContextStoreError(
                        "secure_delete_disabled", "SQLite secure deletion is required."
                    )
                self._validated_key(connection)
        except sqlite3.OperationalError as exc:
            raise ContextStoreError(
                "context_schema_uninitialized",
                "Initialize the SID-151 schema before constructing the service.",
            ) from exc

    @staticmethod
    def _key_check(key: bytes) -> bytes:
        return hmac.new(key, KEY_CHECK_MESSAGE, hashlib.sha256).digest()

    @classmethod
    def _validated_key(cls, connection: sqlite3.Connection) -> bytes:
        key_row = connection.execute(
            "SELECT value FROM context_store_metadata WHERE key='hmac_key'"
        ).fetchone()
        check_row = connection.execute(
            "SELECT value FROM context_store_metadata WHERE key='hmac_key_check'"
        ).fetchone()
        if key_row is None or check_row is None:
            raise ContextStoreError(
                "fingerprint_key_unavailable", "The command fingerprint key is unavailable."
            )
        key = bytes(key_row["value"])
        if len(key) != 32:
            raise ContextStoreError(
                "fingerprint_key_invalid", "The command fingerprint key is invalid."
            )
        if not hmac.compare_digest(bytes(check_row["value"]), cls._key_check(key)):
            raise ContextStoreError(
                "fingerprint_key_mismatch",
                "The command fingerprint key does not match its durable verifier.",
            )
        return key

    # -- command receipt boundary ---------------------------------------

    def _fingerprint(self, connection: sqlite3.Connection, payload: Any) -> str:
        key = self._validated_key(connection)
        return hmac.new(key, _json(payload).encode(), hashlib.sha256).hexdigest()

    def _existing_receipt(
        self,
        connection: sqlite3.Connection,
        scope: ContextScope,
        identity: CommandIdentity,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        rows = connection.execute(
            """
            SELECT * FROM context_command_receipts
            WHERE actor_id = ? AND workspace_id = ?
              AND (command_id = ? OR idempotency_key = ?)
            """,
            (scope.actor_id, scope.workspace_id, identity.command_id, identity.idempotency_key),
        ).fetchall()
        if not rows:
            return None
        if len({row["receipt_id"] for row in rows}) != 1:
            raise ContextStoreError(
                "command_identity_conflict",
                "Command ID and idempotency key are bound to different receipts.",
            )
        row = rows[0]
        if not hmac.compare_digest(str(row["payload_fingerprint"]), fingerprint):
            raise ContextStoreError(
                "idempotency_payload_conflict",
                "The command identity is already bound to different semantic content.",
            )
        return self._receipt(row, duplicate=True)

    def _execute(
        self,
        scope: ContextScope,
        identity: CommandIdentity,
        kind: str,
        payload: Any,
        mutation: Callable[[sqlite3.Connection, datetime], tuple[str, list[str], dict[str, int]]],
    ) -> dict[str, Any]:
        now = self.clock()
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            fingerprint = self._fingerprint(connection, payload)
            existing = self._existing_receipt(connection, scope, identity, fingerprint)
            if existing is not None:
                return existing
            state, target_ids, revisions = mutation(connection, now)
            self._inject_failure("after_domain_mutation")
            receipt_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO context_command_receipts(
                    receipt_id, actor_id, workspace_id, command_id, idempotency_key,
                    command_kind, payload_fingerprint, state, target_ids_json,
                    target_revisions_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id, scope.actor_id, scope.workspace_id,
                    identity.command_id, identity.idempotency_key, kind, fingerprint,
                    state, _json(target_ids), _json(revisions), _iso(now),
                ),
            )
            row = connection.execute(
                """SELECT * FROM context_command_receipts
                   WHERE actor_id=? AND workspace_id=? AND receipt_id=?""",
                (scope.actor_id, scope.workspace_id, receipt_id),
            ).fetchone()
            self._inject_failure("after_receipt_insert")
            return self._receipt(row, duplicate=False)

    def _inject_failure(self, point: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(point)

    @staticmethod
    def _receipt(row: sqlite3.Row, *, duplicate: bool) -> dict[str, Any]:
        return {
            "receipt_id": row["receipt_id"],
            "command_id": row["command_id"],
            "idempotency_key": row["idempotency_key"],
            "command_kind": row["command_kind"],
            "state": row["state"],
            "target_ids": _json_value(row["target_ids_json"]),
            "target_revisions": _json_value(row["target_revisions_json"]),
            "recorded_at": row["recorded_at"],
            "delivery_disposition": "duplicate" if duplicate else "newly_applied",
        }

    def get_receipt(
        self, scope: ContextScope, *, command_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not command_id and not idempotency_key:
            raise ContextStoreError("identity_required", "A command identity is required.")
        with database_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM context_command_receipts
                WHERE actor_id = ? AND workspace_id = ?
                  AND ((? IS NOT NULL AND command_id = ?)
                    OR (? IS NOT NULL AND idempotency_key = ?))
                """,
                (
                    scope.actor_id, scope.workspace_id,
                    command_id, command_id, idempotency_key, idempotency_key,
                ),
            ).fetchone()
        return {"state": "not_found"} if row is None else self._receipt(row, duplicate=False)

    # -- consent ---------------------------------------------------------

    def grant_capture_consent(
        self, scope: ContextScope, identity: CommandIdentity, *, capture_scope: str,
        scope_version: str, retain_sensitive: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "capture_scope": capture_scope,
            "scope_version": scope_version,
            "retain_sensitive": retain_sensitive,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            existing = connection.execute(
                """SELECT * FROM context_capture_consents
                   WHERE actor_id=? AND workspace_id=? AND scope=? AND scope_version=?""",
                (scope.actor_id, scope.workspace_id, capture_scope, scope_version),
            ).fetchone()
            if existing and existing["capture_enabled"]:
                raise ContextStoreError("consent_already_active", "This consent version is active.")
            consent_id = str(existing["consent_id"]) if existing else str(uuid.uuid4())
            revision = int(existing["revision"]) + 1 if existing else 1
            connection.execute(
                """
                INSERT INTO context_capture_consents(
                    consent_id, actor_id, workspace_id, scope, scope_version,
                    capture_enabled, sensitive_retention, revision, granted_at,
                    revoked_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, NULL, ?)
                ON CONFLICT(actor_id, workspace_id, scope, scope_version) DO UPDATE SET
                    capture_enabled=1, sensitive_retention=excluded.sensitive_retention,
                    revision=excluded.revision, granted_at=excluded.granted_at,
                    revoked_at=NULL, updated_at=excluded.updated_at
                """,
                (
                    consent_id, scope.actor_id, scope.workspace_id, capture_scope,
                    scope_version, int(retain_sensitive), revision, _iso(now), _iso(now),
                ),
            )
            return "applied", [consent_id], {consent_id: revision}

        return self._execute(scope, identity, "grant_capture_consent", payload, mutation)

    def revoke_capture_consent(
        self, scope: ContextScope, identity: CommandIdentity, *, capture_scope: str,
        scope_version: str, expected_revision: int,
    ) -> dict[str, Any]:
        payload = {
            "capture_scope": capture_scope, "scope_version": scope_version,
            "expected_revision": expected_revision,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            cursor = connection.execute(
                """
                UPDATE context_capture_consents
                SET capture_enabled=0, revision=revision+1, revoked_at=?, updated_at=?
                WHERE actor_id=? AND workspace_id=? AND scope=? AND scope_version=?
                  AND capture_enabled=1 AND revision=?
                """,
                (
                    _iso(now), _iso(now), scope.actor_id, scope.workspace_id,
                    capture_scope, scope_version, expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ContextStoreError("revision_conflict", "Consent revision is stale or absent.")
            row = connection.execute(
                """SELECT consent_id, revision FROM context_capture_consents
                   WHERE actor_id=? AND workspace_id=? AND scope=? AND scope_version=?""",
                (scope.actor_id, scope.workspace_id, capture_scope, scope_version),
            ).fetchone()
            return "applied", [row["consent_id"]], {row["consent_id"]: row["revision"]}

        return self._execute(scope, identity, "revoke_capture_consent", payload, mutation)

    def inspect_consents(self, scope: ContextScope) -> list[dict[str, Any]]:
        with database_connection() as connection:
            rows = connection.execute(
                """SELECT consent_id, scope, scope_version, capture_enabled,
                          sensitive_retention, revision, granted_at, revoked_at, updated_at
                   FROM context_capture_consents
                   WHERE actor_id=? AND workspace_id=? ORDER BY updated_at DESC""",
                (scope.actor_id, scope.workspace_id),
            ).fetchall()
        return [
            {**dict(row), "capture_enabled": bool(row["capture_enabled"]),
             "sensitive_retention": bool(row["sensitive_retention"])}
            for row in rows
        ]

    @staticmethod
    def _require_consent(
        connection: sqlite3.Connection, scope: ContextScope, capture_scope: str,
        scope_version: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """SELECT * FROM context_capture_consents
               WHERE actor_id=? AND workspace_id=? AND scope=? AND scope_version=?
                 AND capture_enabled=1 AND revoked_at IS NULL""",
            (scope.actor_id, scope.workspace_id, capture_scope, scope_version),
        ).fetchone()
        if row is None:
            raise ContextStoreError("capture_not_authorized", "Exact-scope capture consent is required.")
        return row

    # -- capture and durable conversation state -------------------------

    def capture_context(
        self,
        scope: ContextScope,
        identity: CommandIdentity,
        *,
        item_id: str,
        capture_scope: str,
        scope_version: str,
        context_kind: Literal[
            "narrative", "preference", "learning_reference", "summary",
            "operational_attestation", "situational"
        ],
        content: dict[str, Any],
        source_identity: str,
        source_authority: str,
        asserted_at: datetime,
        conversation_id: str | None = None,
        binding_id: str | None = None,
        raw_content: str | None = None,
        sensitive: bool = False,
        retain_raw: bool = True,
        requires_raw_context: bool = False,
        certainty: Literal["confirmed", "probable", "possible", "unknown"] = "confirmed",
        attestation: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        expiry_basis: str | None = None,
        resolution_state: Literal["unresolved", "resolved", "unknown"] | None = None,
        dependencies: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        content_json = _bounded_json(content, MAX_CONTEXT_BYTES, "context")
        attestation_json = (
            _bounded_json(attestation, MAX_CONTEXT_BYTES, "attestation")
            if attestation is not None else None
        )
        if context_kind == "situational" and expires_at is None:
            raise ContextStoreError("expiry_required", "Durable situational context needs bounded expiry.")
        if raw_content is not None and len(raw_content.encode("utf-8")) > MAX_RAW_BYTES:
            raise ContextStoreError("content_too_large", "raw evidence exceeds its bounded size.")
        if not source_identity.strip() or not source_authority.strip():
            raise ContextStoreError(
                "source_required", "Source identity and authority are required."
            )
        payload = {
            "item_id": item_id, "capture_scope": capture_scope,
            "scope_version": scope_version, "context_kind": context_kind,
            "content": content, "source_identity": source_identity,
            "source_authority": source_authority, "asserted_at": _iso(asserted_at),
            "conversation_id": conversation_id, "binding_id": binding_id,
            "raw_content": raw_content, "sensitive": sensitive,
            "retain_raw": retain_raw, "requires_raw_context": requires_raw_context,
            "certainty": certainty, "attestation": attestation,
            "expires_at": _iso(expires_at), "expiry_basis": expiry_basis,
            "resolution_state": resolution_state, "dependencies": sorted(dependencies),
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            consent = self._require_consent(
                connection, scope, capture_scope, scope_version
            )
            sensitive_retention = not sensitive or bool(consent["sensitive_retention"])
            if sensitive and not sensitive_retention and (
                context_kind != "operational_attestation"
                or attestation_json is None
                or requires_raw_context
            ):
                raise ContextStoreError(
                    "sensitive_attestation_required",
                    "Without sensitive-retention consent, only a minimal independent attestation may persist.",
                )
            if sensitive and not sensitive_retention:
                if set(attestation or {}) - MINIMAL_ATTESTATION_KEYS:
                    raise ContextStoreError(
                        "sensitive_attestation_not_minimal",
                        "The structured attestation contains non-minimal fields.",
                    )
                stored_attestation_json = _bounded_json(
                    attestation, MAX_MINIMAL_ATTESTATION_BYTES, "minimal attestation"
                )
            else:
                stored_attestation_json = attestation_json
            stored_content_json = content_json if sensitive_retention else None
            stored_raw_content = raw_content if sensitive_retention else None
            if connection.execute(
                "SELECT 1 FROM context_tombstones WHERE actor_id=? AND workspace_id=? AND target_id=?",
                (scope.actor_id, scope.workspace_id, item_id),
            ).fetchone():
                raise ContextStoreError("forgotten_target", "Forgotten content cannot be reseeded.")
            if connection.execute(
                "SELECT 1 FROM shared_context_items WHERE actor_id=? AND workspace_id=? AND item_id=?",
                (scope.actor_id, scope.workspace_id, item_id),
            ).fetchone():
                raise ContextStoreError("target_exists", "Context item already exists.")
            if binding_id and not self._binding_valid(connection, scope, binding_id, now):
                raise ContextStoreError("invalid_binding", "Course binding is absent, expired, or revoked.")
            for dependency in dependencies:
                if not connection.execute(
                    """SELECT 1 FROM shared_context_items
                       WHERE actor_id=? AND workspace_id=? AND item_id=?
                         AND status IN ('active','needs_review')""",
                    (scope.actor_id, scope.workspace_id, dependency),
                ).fetchone():
                    raise ContextStoreError("invalid_dependency", "A context dependency is unavailable.")

            evidence_id = None
            if stored_raw_content is not None and retain_raw:
                evidence_id = str(uuid.uuid4())
                expires = now + timedelta(days=RAW_RETENTION_DAYS)
                connection.execute(
                    """INSERT INTO raw_conversation_evidence(
                           evidence_id, actor_id, workspace_id, source_identity,
                           source_authority, asserted_at, content, sensitive,
                           expires_at, removed_at, removal_reason, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
                    (
                        evidence_id, scope.actor_id, scope.workspace_id,
                        source_identity, source_authority, _iso(asserted_at), stored_raw_content,
                        int(sensitive), _iso(expires), _iso(now),
                    ),
                )
            status = "needs_review" if certainty == "unknown" else "active"
            connection.execute(
                """INSERT INTO shared_context_items(
                       item_id, actor_id, workspace_id, context_kind, scope,
                       scope_version, conversation_id, binding_id, content_json,
                       attestation_json, raw_evidence_id, source_identity,
                       source_authority, asserted_at, certainty, status, sensitive,
                       requires_raw_context, expires_at, expiry_basis, resolution_state,
                       revision, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    item_id, scope.actor_id, scope.workspace_id, context_kind,
                    capture_scope, scope_version, conversation_id, binding_id,
                    stored_content_json, stored_attestation_json, evidence_id, source_identity,
                    source_authority, _iso(asserted_at), certainty, status,
                    int(sensitive), int(requires_raw_context), _iso(expires_at),
                    expiry_basis, resolution_state, _iso(now), _iso(now),
                ),
            )
            self._insert_revision(
                connection, scope, item_id, 1, stored_content_json, stored_attestation_json,
                certainty, status, "capture", None, now,
            )
            for dependency in dependencies:
                connection.execute(
                    """INSERT INTO context_dependencies(
                           actor_id, workspace_id, source_item_id, dependent_item_id,
                           dependency_kind, created_at
                       ) VALUES (?, ?, ?, ?, 'derived_from', ?)""",
                    (scope.actor_id, scope.workspace_id, dependency, item_id, _iso(now)),
                )
            return status if status == "needs_review" else "applied", [item_id], {item_id: 1}

        return self._execute(scope, identity, "capture_context", payload, mutation)

    def save_conversation_state(
        self, scope: ContextScope, identity: CommandIdentity, *, conversation_id: str,
        state: dict[str, Any], expected_revision: int | None,
        pending_action_id: str | None = None,
    ) -> dict[str, Any]:
        state_json = _bounded_json(state, MAX_STATE_BYTES, "conversation state")
        payload = {
            "conversation_id": conversation_id, "state": state,
            "expected_revision": expected_revision, "pending_action_id": pending_action_id,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            if pending_action_id is not None:
                if self.pending_action_authorizer is None:
                    raise ContextStoreError(
                        "pending_action_scope_unverified",
                        "A trusted SID-150 scope authorizer is required for pending-action references.",
                    )
                try:
                    authorized = self.pending_action_authorizer(
                        scope, pending_action_id, conversation_id
                    )
                except Exception as exc:
                    raise ContextStoreError(
                        "pending_action_scope_unverified",
                        "The pending-action scope could not be verified.",
                    ) from exc
                if not authorized:
                    raise ContextStoreError(
                        "pending_action_scope_unverified",
                        "The pending action is absent or outside this actor/workspace conversation scope.",
                    )
            row = connection.execute(
                """SELECT revision FROM conversation_states
                   WHERE actor_id=? AND workspace_id=? AND conversation_id=?""",
                (scope.actor_id, scope.workspace_id, conversation_id),
            ).fetchone()
            if row is None:
                if expected_revision not in (None, 0):
                    raise ContextStoreError("revision_conflict", "Conversation state does not exist.")
                revision = 1
                connection.execute(
                    """INSERT INTO conversation_states(
                           actor_id, workspace_id, conversation_id, state_json,
                           pending_action_id, revision, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        scope.actor_id, scope.workspace_id, conversation_id,
                        state_json, pending_action_id, _iso(now), _iso(now),
                    ),
                )
            else:
                if expected_revision != int(row["revision"]):
                    raise ContextStoreError("revision_conflict", "Conversation state revision is stale.")
                revision = int(row["revision"]) + 1
                connection.execute(
                    """UPDATE conversation_states
                       SET state_json=?, pending_action_id=?, revision=?, updated_at=?
                       WHERE actor_id=? AND workspace_id=? AND conversation_id=?""",
                    (
                        state_json, pending_action_id, revision, _iso(now),
                        scope.actor_id, scope.workspace_id, conversation_id,
                    ),
                )
            return "applied", [conversation_id], {conversation_id: revision}

        return self._execute(scope, identity, "save_conversation_state", payload, mutation)

    def get_conversation_state(
        self, scope: ContextScope, conversation_id: str
    ) -> dict[str, Any] | None:
        with database_connection() as connection:
            row = connection.execute(
                """SELECT conversation_id, state_json, pending_action_id, revision,
                          created_at, updated_at FROM conversation_states
                   WHERE actor_id=? AND workspace_id=? AND conversation_id=?""",
                (scope.actor_id, scope.workspace_id, conversation_id),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["state"] = _json_value(item.pop("state_json"))
        return item

    # -- questions and course bindings ----------------------------------

    def set_question_disposition(
        self, scope: ContextScope, identity: CommandIdentity, *, question_id: str,
        prompt_key: str, disposition: Literal["asked", "answered", "deferred"],
        expected_revision: int | None, answer_summary: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "question_id": question_id, "prompt_key": prompt_key,
            "disposition": disposition, "expected_revision": expected_revision,
            "answer_summary": answer_summary, "conversation_id": conversation_id,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            row = connection.execute(
                """SELECT revision, asked_at FROM context_questions
                   WHERE actor_id=? AND workspace_id=? AND question_id=?""",
                (scope.actor_id, scope.workspace_id, question_id),
            ).fetchone()
            if row is None:
                if expected_revision not in (None, 0):
                    raise ContextStoreError("revision_conflict", "Question does not exist.")
                revision, asked_at = 1, _iso(now)
                connection.execute(
                    """INSERT INTO context_questions(
                           question_id, actor_id, workspace_id, disposition, prompt_key,
                           answer_summary, conversation_id, revision, asked_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        question_id, scope.actor_id, scope.workspace_id, disposition,
                        prompt_key, answer_summary, conversation_id, asked_at, _iso(now),
                    ),
                )
            else:
                if expected_revision != int(row["revision"]):
                    raise ContextStoreError("revision_conflict", "Question revision is stale.")
                revision, asked_at = int(row["revision"]) + 1, row["asked_at"]
                connection.execute(
                    """UPDATE context_questions SET disposition=?, prompt_key=?,
                           answer_summary=?, conversation_id=?, revision=?, updated_at=?
                       WHERE actor_id=? AND workspace_id=? AND question_id=?""",
                    (
                        disposition, prompt_key, answer_summary, conversation_id,
                        revision, _iso(now), scope.actor_id, scope.workspace_id, question_id,
                    ),
                )
            return "applied", [question_id], {question_id: revision}

        return self._execute(scope, identity, "set_question_disposition", payload, mutation)

    def list_questions(self, scope: ContextScope, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = self._limit(limit)
        with database_connection() as connection:
            rows = connection.execute(
                """SELECT question_id, disposition, prompt_key, answer_summary,
                          conversation_id, revision, asked_at, updated_at
                   FROM context_questions WHERE actor_id=? AND workspace_id=?
                   ORDER BY updated_at DESC LIMIT ?""",
                (scope.actor_id, scope.workspace_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_course_binding(
        self, scope: ContextScope, identity: CommandIdentity, *, binding_id: str,
        term_id: str, section_id: str, binding_scope: str, review_provenance: str,
        reviewed_at: datetime, valid_from: datetime, valid_until: datetime | None,
        conversation_id: str | None = None, attested_surface_id: str | None = None,
        explicitly_selected: bool = False,
    ) -> dict[str, Any]:
        if conversation_id and not (attested_surface_id or explicitly_selected):
            raise ContextStoreError(
                "untrusted_surface_binding",
                "A title or client hint cannot create a course binding.",
            )
        payload = {
            "binding_id": binding_id, "term_id": term_id, "section_id": section_id,
            "binding_scope": binding_scope, "review_provenance": review_provenance,
            "reviewed_at": _iso(reviewed_at), "valid_from": _iso(valid_from),
            "valid_until": _iso(valid_until), "conversation_id": conversation_id,
            "attested_surface_id": attested_surface_id,
            "explicitly_selected": explicitly_selected,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            if valid_until and valid_until <= valid_from:
                raise ContextStoreError("invalid_validity", "Binding validity must be positive.")
            if connection.execute(
                """SELECT 1 FROM course_context_bindings
                   WHERE actor_id=? AND workspace_id=? AND binding_id=?""",
                (scope.actor_id, scope.workspace_id, binding_id),
            ).fetchone():
                raise ContextStoreError("target_exists", "Course binding already exists.")
            connection.execute(
                """INSERT INTO course_context_bindings(
                       binding_id, actor_id, workspace_id, term_id, section_id,
                       binding_scope, conversation_id, attested_surface_id,
                       review_provenance, reviewed_at, valid_from, valid_until,
                       revoked_at, revision, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?, ?)""",
                (
                    binding_id, scope.actor_id, scope.workspace_id, term_id, section_id,
                    binding_scope, conversation_id, attested_surface_id,
                    review_provenance, _iso(reviewed_at), _iso(valid_from),
                    _iso(valid_until), _iso(now), _iso(now),
                ),
            )
            return "applied", [binding_id], {binding_id: 1}

        return self._execute(scope, identity, "create_course_binding", payload, mutation)

    def revoke_course_binding(
        self, scope: ContextScope, identity: CommandIdentity, *, binding_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        payload = {"binding_id": binding_id, "expected_revision": expected_revision}

        def mutation(connection: sqlite3.Connection, now: datetime):
            cursor = connection.execute(
                """UPDATE course_context_bindings
                   SET revoked_at=?, revision=revision+1, updated_at=?
                   WHERE actor_id=? AND workspace_id=? AND binding_id=?
                     AND revoked_at IS NULL AND revision=?""",
                (
                    _iso(now), _iso(now), scope.actor_id, scope.workspace_id,
                    binding_id, expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ContextStoreError("revision_conflict", "Binding revision is stale or absent.")
            return "applied", [binding_id], {binding_id: expected_revision + 1}

        return self._execute(scope, identity, "revoke_course_binding", payload, mutation)

    def get_course_binding(
        self, scope: ContextScope, binding_id: str, *, at: datetime | None = None
    ) -> dict[str, Any] | None:
        instant = at or self.clock()
        with database_connection() as connection:
            row = connection.execute(
                """SELECT binding_id, term_id, section_id, binding_scope,
                          conversation_id, attested_surface_id, review_provenance,
                          reviewed_at, valid_from, valid_until, revoked_at, revision
                   FROM course_context_bindings
                   WHERE actor_id=? AND workspace_id=? AND binding_id=?""",
                (scope.actor_id, scope.workspace_id, binding_id),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["valid"] = (
            item["revoked_at"] is None
            and item["valid_from"] <= _iso(instant)
            and (item["valid_until"] is None or item["valid_until"] > _iso(instant))
        )
        return item

    @staticmethod
    def _binding_valid(
        connection: sqlite3.Connection, scope: ContextScope, binding_id: str, now: datetime
    ) -> bool:
        row = connection.execute(
            """SELECT valid_from, valid_until, revoked_at FROM course_context_bindings
               WHERE actor_id=? AND workspace_id=? AND binding_id=?""",
            (scope.actor_id, scope.workspace_id, binding_id),
        ).fetchone()
        instant = _iso(now)
        return bool(
            row and row["revoked_at"] is None and row["valid_from"] <= instant
            and (row["valid_until"] is None or row["valid_until"] > instant)
        )

    # -- lifecycle, dependencies, caches --------------------------------

    def correct_context(
        self, scope: ContextScope, identity: CommandIdentity, *, item_id: str,
        expected_revision: int, content: dict[str, Any], reason: str,
        certainty: Literal["confirmed", "probable", "possible", "unknown"] = "confirmed",
    ) -> dict[str, Any]:
        content_json = _bounded_json(content, MAX_CONTEXT_BYTES, "context")
        payload = {
            "item_id": item_id, "expected_revision": expected_revision,
            "content": content, "reason": reason, "certainty": certainty,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            row = self._item(connection, scope, item_id)
            if int(row["revision"]) != expected_revision or row["status"] in ("forgotten", "retracted"):
                raise ContextStoreError("revision_conflict", "Context revision is stale.")
            revision = expected_revision + 1
            status = "needs_review" if certainty == "unknown" else "active"
            connection.execute(
                """UPDATE shared_context_items SET content_json=?, certainty=?, status=?,
                       revision=?, updated_at=? WHERE actor_id=? AND workspace_id=? AND item_id=?""",
                (
                    content_json, certainty, status, revision, _iso(now),
                    scope.actor_id, scope.workspace_id, item_id,
                ),
            )
            self._insert_revision(
                connection, scope, item_id, revision, content_json,
                row["attestation_json"], certainty, status, "correction", reason, now,
            )
            affected = self._degrade_dependents(connection, scope, item_id, now)
            self._invalidate_caches(connection, scope, {item_id, *affected}, now)
            revisions = {item_id: revision, **affected}
            return ("needs_review" if affected or status == "needs_review" else "applied",
                    [item_id, *affected], revisions)

        return self._execute(scope, identity, "correct_context", payload, mutation)

    def undo_context_correction(
        self, scope: ContextScope, identity: CommandIdentity, *, item_id: str,
        expected_revision: int, correction_revision: int, reason: str,
    ) -> dict[str, Any]:
        payload = {
            "item_id": item_id, "expected_revision": expected_revision,
            "correction_revision": correction_revision, "reason": reason,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            current = self._item(connection, scope, item_id)
            if int(current["revision"]) != expected_revision or correction_revision != expected_revision:
                raise ContextStoreError(
                    "revision_conflict", "Undo cannot silently overwrite subsequent revisions."
                )
            previous = connection.execute(
                """SELECT * FROM shared_context_revisions
                   WHERE actor_id=? AND workspace_id=? AND item_id=? AND revision=?""",
                (scope.actor_id, scope.workspace_id, item_id, correction_revision - 1),
            ).fetchone()
            if previous is None:
                raise ContextStoreError("undo_target_missing", "Prior revision is unavailable.")
            revision = expected_revision + 1
            connection.execute(
                """UPDATE shared_context_items SET content_json=?, attestation_json=?,
                       certainty=?, status=?, revision=?, updated_at=?
                   WHERE actor_id=? AND workspace_id=? AND item_id=?""",
                (
                    previous["content_json"], previous["attestation_json"],
                    previous["certainty"], previous["status"], revision, _iso(now),
                    scope.actor_id, scope.workspace_id, item_id,
                ),
            )
            self._insert_revision(
                connection, scope, item_id, revision, previous["content_json"],
                previous["attestation_json"], previous["certainty"], previous["status"],
                "undo", reason, now,
            )
            affected = self._degrade_dependents(connection, scope, item_id, now)
            self._invalidate_caches(connection, scope, {item_id, *affected}, now)
            return "needs_review" if affected else "applied", [item_id, *affected], {
                item_id: revision, **affected
            }

        return self._execute(scope, identity, "undo_context_correction", payload, mutation)

    def remove_raw_evidence(
        self, scope: ContextScope, identity: CommandIdentity, *, item_id: str,
        expected_revision: int, reason: str = "raw_only_removal",
    ) -> dict[str, Any]:
        payload = {
            "item_id": item_id, "expected_revision": expected_revision, "reason": reason
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            row = self._item(connection, scope, item_id)
            if int(row["revision"]) != expected_revision:
                raise ContextStoreError("revision_conflict", "Context revision is stale.")
            evidence_id = row["raw_evidence_id"]
            if evidence_id:
                connection.execute(
                    """UPDATE raw_conversation_evidence SET content=NULL, removed_at=?, removal_reason=?
                       WHERE actor_id=? AND workspace_id=? AND evidence_id=?""",
                    (_iso(now), reason, scope.actor_id, scope.workspace_id, evidence_id),
                )
            revision = expected_revision + 1
            status = "needs_review" if row["requires_raw_context"] else row["status"]
            certainty = "unknown" if row["requires_raw_context"] else row["certainty"]
            connection.execute(
                """UPDATE shared_context_items SET raw_evidence_id=NULL, status=?, certainty=?,
                       revision=?, updated_at=? WHERE actor_id=? AND workspace_id=? AND item_id=?""",
                (
                    status, certainty, revision, _iso(now),
                    scope.actor_id, scope.workspace_id, item_id,
                ),
            )
            self._insert_revision(
                connection, scope, item_id, revision, row["content_json"],
                row["attestation_json"], certainty, status, "remove_raw_evidence", reason, now,
            )
            affected = (
                self._degrade_dependents(connection, scope, item_id, now)
                if row["requires_raw_context"] else {}
            )
            self._invalidate_caches(connection, scope, {item_id, *affected}, now)
            return ("needs_review" if status == "needs_review" else "applied",
                    [item_id, *affected], {item_id: revision, **affected})

        return self._execute(scope, identity, "remove_raw_evidence", payload, mutation)

    def forget_context(
        self, scope: ContextScope, identity: CommandIdentity, *, item_id: str,
        expected_revision: int, reason: str = "user_requested_forgetting",
    ) -> dict[str, Any]:
        payload = {
            "item_id": item_id, "expected_revision": expected_revision, "reason": reason
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            row = self._item(connection, scope, item_id)
            if int(row["revision"]) != expected_revision:
                raise ContextStoreError("revision_conflict", "Context revision is stale.")
            forgotten = self._forget_recursive(connection, scope, item_id, now, set())
            self._invalidate_caches(connection, scope, set(forgotten), now)
            return "applied", list(forgotten), forgotten

        return self._execute(scope, identity, "forget_context", payload, mutation)

    def expire_raw_evidence(
        self, scope: ContextScope, identity: CommandIdentity, *, through: datetime
    ) -> dict[str, Any]:
        payload = {"through": _iso(through)}

        def mutation(connection: sqlite3.Connection, now: datetime):
            rows = connection.execute(
                """SELECT e.evidence_id, i.item_id, i.revision, i.requires_raw_context
                   FROM raw_conversation_evidence e
                   LEFT JOIN shared_context_items i
                     ON i.actor_id=e.actor_id AND i.workspace_id=e.workspace_id
                    AND i.raw_evidence_id=e.evidence_id
                   WHERE e.actor_id=? AND e.workspace_id=? AND e.content IS NOT NULL
                     AND e.expires_at<=?""",
                (scope.actor_id, scope.workspace_id, _iso(through)),
            ).fetchall()
            revisions: dict[str, int] = {}
            targets: list[str] = []
            for evidence in rows:
                connection.execute(
                    """UPDATE raw_conversation_evidence SET content=NULL, removed_at=?,
                           removal_reason='routine_expiry'
                       WHERE actor_id=? AND workspace_id=? AND evidence_id=?""",
                    (_iso(now), scope.actor_id, scope.workspace_id, evidence["evidence_id"]),
                )
                if evidence["item_id"]:
                    item = self._item(connection, scope, evidence["item_id"])
                    revision = int(item["revision"]) + 1
                    status = "needs_review" if item["requires_raw_context"] else item["status"]
                    certainty = "unknown" if item["requires_raw_context"] else item["certainty"]
                    connection.execute(
                        """UPDATE shared_context_items SET raw_evidence_id=NULL, status=?,
                               certainty=?, revision=?, updated_at=?
                           WHERE actor_id=? AND workspace_id=? AND item_id=?""",
                        (
                            status, certainty, revision, _iso(now), scope.actor_id,
                            scope.workspace_id, item["item_id"],
                        ),
                    )
                    self._insert_revision(
                        connection, scope, item["item_id"], revision, item["content_json"],
                        item["attestation_json"], certainty, status, "raw_expiry",
                        "seven_day_policy", now,
                    )
                    revisions[item["item_id"]] = revision
                    targets.append(item["item_id"])
                    if item["requires_raw_context"]:
                        affected = self._degrade_dependents(
                            connection, scope, item["item_id"], now
                        )
                        revisions.update(affected)
                        targets.extend(affected)
            self._invalidate_caches(connection, scope, set(targets), now)
            return "needs_review" if any(
                self._item(connection, scope, target)["status"] == "needs_review"
                for target in targets
            ) else "applied", list(dict.fromkeys(targets)), revisions

        return self._execute(scope, identity, "expire_raw_evidence", payload, mutation)

    def resolve_situational_context(
        self, scope: ContextScope, identity: CommandIdentity, *, item_id: str,
        expected_revision: int,
        resolution_state: Literal["resolved", "unknown"],
    ) -> dict[str, Any]:
        payload = {
            "item_id": item_id, "expected_revision": expected_revision,
            "resolution_state": resolution_state,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            row = self._item(connection, scope, item_id)
            if row["context_kind"] != "situational":
                raise ContextStoreError("wrong_context_kind", "Target is not situational context.")
            if int(row["revision"]) != expected_revision:
                raise ContextStoreError("revision_conflict", "Context revision is stale.")
            revision = expected_revision + 1
            connection.execute(
                """UPDATE shared_context_items SET resolution_state=?, revision=?, updated_at=?
                   WHERE actor_id=? AND workspace_id=? AND item_id=?""",
                (
                    resolution_state, revision, _iso(now), scope.actor_id,
                    scope.workspace_id, item_id,
                ),
            )
            self._insert_revision(
                connection, scope, item_id, revision, row["content_json"],
                row["attestation_json"], row["certainty"], row["status"],
                "resolve_situational", resolution_state, now,
            )
            self._invalidate_caches(connection, scope, {item_id}, now)
            return "applied", [item_id], {item_id: revision}

        return self._execute(scope, identity, "resolve_situational_context", payload, mutation)

    def put_cache(
        self, scope: ContextScope, identity: CommandIdentity, *, cache_key: str,
        content: dict[str, Any], source_item_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        content_json = _bounded_json(content, MAX_CONTEXT_BYTES, "cache")
        payload = {
            "cache_key": cache_key, "content": content,
            "source_item_ids": sorted(source_item_ids),
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            for source_id in source_item_ids:
                self._item(connection, scope, source_id)
            row = connection.execute(
                """SELECT generation FROM context_caches
                   WHERE actor_id=? AND workspace_id=? AND cache_key=?""",
                (scope.actor_id, scope.workspace_id, cache_key),
            ).fetchone()
            generation = int(row["generation"]) + 1 if row else 1
            connection.execute(
                """INSERT INTO context_caches(
                       actor_id, workspace_id, cache_key, generation, content_json,
                       status, created_at, invalidated_at
                   ) VALUES (?, ?, ?, ?, ?, 'current', ?, NULL)
                   ON CONFLICT(actor_id, workspace_id, cache_key) DO UPDATE SET
                       generation=excluded.generation, content_json=excluded.content_json,
                       status='current', created_at=excluded.created_at, invalidated_at=NULL""",
                (
                    scope.actor_id, scope.workspace_id, cache_key, generation,
                    content_json, _iso(now),
                ),
            )
            connection.execute(
                "DELETE FROM context_cache_dependencies WHERE actor_id=? AND workspace_id=? AND cache_key=?",
                (scope.actor_id, scope.workspace_id, cache_key),
            )
            for source_id in source_item_ids:
                connection.execute(
                    """INSERT INTO context_cache_dependencies(
                           actor_id, workspace_id, cache_key, source_item_id
                       ) VALUES (?, ?, ?, ?)""",
                    (scope.actor_id, scope.workspace_id, cache_key, source_id),
                )
            return "applied", [cache_key], {cache_key: generation}

        return self._execute(scope, identity, "put_context_cache", payload, mutation)

    def get_cache(self, scope: ContextScope, cache_key: str) -> dict[str, Any] | None:
        with database_connection() as connection:
            row = connection.execute(
                """SELECT cache_key, generation, content_json, status, created_at, invalidated_at
                   FROM context_caches WHERE actor_id=? AND workspace_id=? AND cache_key=?
                     AND status='current'""",
                (scope.actor_id, scope.workspace_id, cache_key),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["content"] = _json_value(item.pop("content_json"))
        return item

    # -- baselines and reads --------------------------------------------

    def advance_baseline(
        self, scope: ContextScope, identity: CommandIdentity, *, baseline_id: str,
        consumer: str, cursor: dict[str, Any], expected_revision: int | None,
    ) -> dict[str, Any]:
        cursor_json = _bounded_json(cursor, MAX_CONTEXT_BYTES, "baseline cursor")
        payload = {
            "baseline_id": baseline_id, "consumer": consumer, "cursor": cursor,
            "expected_revision": expected_revision,
        }

        def mutation(connection: sqlite3.Connection, now: datetime):
            row = connection.execute(
                """SELECT revision FROM interaction_baselines
                   WHERE actor_id=? AND workspace_id=? AND baseline_id=?""",
                (scope.actor_id, scope.workspace_id, baseline_id),
            ).fetchone()
            if row is None:
                if expected_revision not in (None, 0):
                    raise ContextStoreError("revision_conflict", "Baseline does not exist.")
                revision = 1
                connection.execute(
                    """INSERT INTO interaction_baselines(
                           baseline_id, actor_id, workspace_id, consumer, cursor_json,
                           revision, created_at, advanced_at
                       ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        baseline_id, scope.actor_id, scope.workspace_id, consumer,
                        cursor_json, _iso(now), _iso(now),
                    ),
                )
            else:
                if expected_revision != int(row["revision"]):
                    raise ContextStoreError("revision_conflict", "Baseline revision is stale.")
                revision = int(row["revision"]) + 1
                connection.execute(
                    """UPDATE interaction_baselines SET consumer=?, cursor_json=?,
                           revision=?, advanced_at=?
                       WHERE actor_id=? AND workspace_id=? AND baseline_id=?""",
                    (
                        consumer, cursor_json, revision, _iso(now), scope.actor_id,
                        scope.workspace_id, baseline_id,
                    ),
                )
            return "applied", [baseline_id], {baseline_id: revision}

        return self._execute(scope, identity, "advance_interaction_baseline", payload, mutation)

    def get_baseline(self, scope: ContextScope, baseline_id: str) -> dict[str, Any] | None:
        with database_connection() as connection:
            row = connection.execute(
                """SELECT baseline_id, consumer, cursor_json, revision, created_at, advanced_at
                   FROM interaction_baselines
                   WHERE actor_id=? AND workspace_id=? AND baseline_id=?""",
                (scope.actor_id, scope.workspace_id, baseline_id),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["cursor"] = _json_value(item.pop("cursor_json"))
        return item

    def retrieve_context(
        self, scope: ContextScope, *, limit: int = 25,
        conversation_id: str | None = None, include_historical: bool = False,
        at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        limit = self._limit(limit)
        instant = _iso(at or self.clock())
        status_clause = "" if include_historical else "AND i.status IN ('active','needs_review')"
        expiry_clause = "" if include_historical else "AND (i.expires_at IS NULL OR i.expires_at > ?)"
        params: list[Any] = [scope.actor_id, scope.workspace_id]
        if not include_historical:
            params.append(instant)
        conversation_clause = ""
        if conversation_id:
            conversation_clause = "AND (i.conversation_id IS NULL OR i.conversation_id = ?)"
            params.append(conversation_id)
        params.append(limit)
        with database_connection() as connection:
            rows = connection.execute(
                f"""SELECT i.item_id, i.context_kind, i.scope, i.scope_version,
                            i.conversation_id, i.binding_id, i.content_json, i.attestation_json,
                            i.raw_evidence_id, i.source_identity, i.source_authority, i.asserted_at,
                            i.certainty, i.status, i.sensitive, i.requires_raw_context, i.expires_at,
                            i.expiry_basis, i.resolution_state, i.revision, i.created_at, i.updated_at,
                            CASE WHEN e.content IS NOT NULL AND e.expires_at > ?
                                 THEN 1 ELSE 0 END AS raw_source_available
                     FROM shared_context_items i
                     LEFT JOIN raw_conversation_evidence e
                       ON e.actor_id=i.actor_id AND e.workspace_id=i.workspace_id
                      AND e.evidence_id=i.raw_evidence_id
                     WHERE i.actor_id=? AND i.workspace_id=? {status_clause}
                       {expiry_clause} {conversation_clause}
                     ORDER BY i.updated_at DESC, i.item_id LIMIT ?""",
                [instant, *params],
            ).fetchall()
        return [self._public_item(row, instant=instant) for row in rows]

    def inspect_item(self, scope: ContextScope, item_id: str) -> dict[str, Any] | None:
        instant = _iso(self.clock())
        with database_connection() as connection:
            row = connection.execute(
                """SELECT i.*,
                          CASE WHEN e.content IS NOT NULL AND e.expires_at > ?
                               THEN 1 ELSE 0 END AS raw_source_available
                   FROM shared_context_items i
                   LEFT JOIN raw_conversation_evidence e
                     ON e.actor_id=i.actor_id AND e.workspace_id=i.workspace_id
                    AND e.evidence_id=i.raw_evidence_id
                   WHERE i.actor_id=? AND i.workspace_id=? AND i.item_id=?""",
                (instant, scope.actor_id, scope.workspace_id, item_id),
            ).fetchone()
        return self._public_item(row, instant=instant) if row else None

    # -- internal helpers ------------------------------------------------

    @staticmethod
    def _limit(limit: int) -> int:
        if limit < 1 or limit > MAX_RETRIEVAL_LIMIT:
            raise ContextStoreError("invalid_limit", "Retrieval limit must be between 1 and 100.")
        return limit

    @staticmethod
    def _public_item(row: sqlite3.Row, *, instant: str) -> dict[str, Any]:
        item = dict(row)
        item.pop("actor_id", None)
        item.pop("workspace_id", None)
        item["content"] = _json_value(item.pop("content_json"))
        item["attestation"] = _json_value(item.pop("attestation_json"))
        item["sensitive"] = bool(item["sensitive"])
        item["requires_raw_context"] = bool(item["requires_raw_context"])
        item["within_validity"] = item["expires_at"] is None or item["expires_at"] > instant
        item["raw_source_available"] = bool(item.get("raw_source_available", False))
        return item

    @staticmethod
    def _item(
        connection: sqlite3.Connection, scope: ContextScope, item_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            """SELECT * FROM shared_context_items
               WHERE actor_id=? AND workspace_id=? AND item_id=?""",
            (scope.actor_id, scope.workspace_id, item_id),
        ).fetchone()
        if row is None:
            raise ContextStoreError("not_found", "Context item was not found in this scope.")
        return row

    @staticmethod
    def _insert_revision(
        connection: sqlite3.Connection, scope: ContextScope, item_id: str, revision: int,
        content_json: str | None, attestation_json: str | None, certainty: str,
        status: str, lifecycle_kind: str, reason: str | None, now: datetime,
    ) -> None:
        connection.execute(
            """INSERT INTO shared_context_revisions(
                   actor_id, workspace_id, item_id, revision, content_json,
                   attestation_json, certainty, status, lifecycle_kind, reason, recorded_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scope.actor_id, scope.workspace_id, item_id, revision, content_json,
                attestation_json, certainty, status, lifecycle_kind, reason, _iso(now),
            ),
        )

    def _degrade_dependents(
        self, connection: sqlite3.Connection, scope: ContextScope, source_id: str,
        now: datetime,
    ) -> dict[str, int]:
        affected: dict[str, int] = {}
        queue = [source_id]
        visited: set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            rows = connection.execute(
                """SELECT dependent_item_id FROM context_dependencies
                   WHERE actor_id=? AND workspace_id=? AND source_item_id=?""",
                (scope.actor_id, scope.workspace_id, current),
            ).fetchall()
            for dependency in rows:
                dependent_id = dependency["dependent_item_id"]
                item = self._item(connection, scope, dependent_id)
                if item["status"] not in ("active", "needs_review"):
                    continue
                independent = connection.execute(
                    """SELECT 1 FROM context_dependencies d
                       JOIN shared_context_items s
                         ON s.actor_id=d.actor_id AND s.workspace_id=d.workspace_id
                        AND s.item_id=d.source_item_id
                       WHERE d.actor_id=? AND d.workspace_id=? AND d.dependent_item_id=?
                         AND d.source_item_id<>? AND s.status IN ('active','needs_review')
                       LIMIT 1""",
                    (scope.actor_id, scope.workspace_id, dependent_id, current),
                ).fetchone()
                if independent is not None:
                    continue
                revision = int(item["revision"]) + 1
                connection.execute(
                    """UPDATE shared_context_items SET status='needs_review', certainty='unknown',
                           revision=?, updated_at=?
                       WHERE actor_id=? AND workspace_id=? AND item_id=?""",
                    (
                        revision, _iso(now), scope.actor_id, scope.workspace_id, dependent_id,
                    ),
                )
                self._insert_revision(
                    connection, scope, dependent_id, revision, item["content_json"],
                    item["attestation_json"], "unknown", "needs_review",
                    "dependency_changed", None, now,
                )
                affected[dependent_id] = revision
                queue.append(dependent_id)
        return affected

    def _forget_recursive(
        self, connection: sqlite3.Connection, scope: ContextScope, item_id: str,
        now: datetime, visited: set[str],
    ) -> dict[str, int]:
        if item_id in visited:
            return {}
        visited.add(item_id)
        item = self._item(connection, scope, item_id)
        if item["status"] == "forgotten":
            return {item_id: int(item["revision"])}
        forgotten: dict[str, int] = {}
        dependents = connection.execute(
            """SELECT dependent_item_id FROM context_dependencies
               WHERE actor_id=? AND workspace_id=? AND source_item_id=?""",
            (scope.actor_id, scope.workspace_id, item_id),
        ).fetchall()
        for edge in dependents:
            dependent_id = edge["dependent_item_id"]
            independent = connection.execute(
                """SELECT 1 FROM context_dependencies d
                   JOIN shared_context_items s
                     ON s.actor_id=d.actor_id AND s.workspace_id=d.workspace_id
                    AND s.item_id=d.source_item_id
                   WHERE d.actor_id=? AND d.workspace_id=? AND d.dependent_item_id=?
                     AND d.source_item_id<>? AND s.status IN ('active','needs_review') LIMIT 1""",
                (scope.actor_id, scope.workspace_id, dependent_id, item_id),
            ).fetchone()
            if independent is None:
                forgotten.update(
                    self._forget_recursive(connection, scope, dependent_id, now, visited)
                )
        if item["raw_evidence_id"]:
            connection.execute(
                """UPDATE raw_conversation_evidence SET content=NULL, removed_at=?,
                       removal_reason='forgotten'
                   WHERE actor_id=? AND workspace_id=? AND evidence_id=?""",
                (
                    _iso(now), scope.actor_id, scope.workspace_id, item["raw_evidence_id"],
                ),
            )
        revision = int(item["revision"]) + 1
        connection.execute(
            """UPDATE shared_context_items SET content_json=NULL, attestation_json=NULL,
                   raw_evidence_id=NULL, certainty='unknown', status='forgotten',
                   revision=?, updated_at=?
               WHERE actor_id=? AND workspace_id=? AND item_id=?""",
            (revision, _iso(now), scope.actor_id, scope.workspace_id, item_id),
        )
        connection.execute(
            """UPDATE shared_context_revisions SET content_json=NULL, attestation_json=NULL,
                   reason=NULL WHERE actor_id=? AND workspace_id=? AND item_id=?""",
            (scope.actor_id, scope.workspace_id, item_id),
        )
        connection.execute(
            """INSERT OR IGNORE INTO context_tombstones(
                   actor_id, workspace_id, target_id, target_kind, lifecycle_marker,
                   dependency_ids_json, created_at
               ) VALUES (?, ?, ?, 'context_item', 'forgotten', ?, ?)""",
            (
                scope.actor_id, scope.workspace_id, item_id,
                _json(sorted(value["dependent_item_id"] for value in dependents)), _iso(now),
            ),
        )
        forgotten[item_id] = revision
        return forgotten

    @staticmethod
    def _invalidate_caches(
        connection: sqlite3.Connection, scope: ContextScope, item_ids: set[str], now: datetime
    ) -> None:
        if not item_ids:
            return
        placeholders = ",".join("?" for _ in item_ids)
        rows = connection.execute(
            f"""SELECT DISTINCT cache_key FROM context_cache_dependencies
                WHERE actor_id=? AND workspace_id=? AND source_item_id IN ({placeholders})""",
            (scope.actor_id, scope.workspace_id, *sorted(item_ids)),
        ).fetchall()
        for row in rows:
            connection.execute(
                """UPDATE context_caches SET content_json=NULL, status='invalidated',
                       generation=generation+1, invalidated_at=?
                   WHERE actor_id=? AND workspace_id=? AND cache_key=?""",
                (_iso(now), scope.actor_id, scope.workspace_id, row["cache_key"]),
            )


__all__ = [
    "CommandIdentity",
    "ContextScope",
    "ContextStoreError",
    "RAW_RETENTION_DAYS",
    "SharedConversationContextService",
]
