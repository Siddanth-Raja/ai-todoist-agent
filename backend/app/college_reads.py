"""SID-260 least-privilege, side-effect-free College read service.

The service opens the existing application SQLite database in read-only mode.  It
does not initialize storage, run migrations, refresh providers, produce an
assessment, advance a baseline, or acknowledge a receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .storage import _database_path


COLLEGE_STATE_READ_VERSION = "college-state-read/1.0"
COLLEGE_STATUS_READ_VERSION = "college-update-status/1.0"
MAX_PAGE_SIZE = 50
MAX_CURSOR_BYTES = 2_048
MAX_COURSE_IDS = 16
MAX_HORIZON_DAYS = 31
MAX_AUTHORIZED_IDENTITIES = 5_000
MAX_COLLECTION_SCAN = 5_000
MAX_OUTPUT_STRING_CHARS = 1_000
MAX_EVIDENCE_REFERENCES = 16
MAX_EVIDENCE_REFERENCE_CHARS = 256
MAX_RECEIPT_TRANSITIONS = 50
MAX_RECEIPT_IDS = 32
MAX_DIAGNOSTICS = 50
MAX_RECORD_BYTES = 16_000
MAX_PAGE_BYTES = 256_000
REQUIRED_TABLES = {
    "college_metadata",
    "college_store_metadata",
    "college_identities",
    "college_provider_links",
    "college_events",
    "college_receipts",
    "college_receipt_transitions",
    "college_receipt_aliases",
    "college_claims",
    "college_field_revisions",
    "college_conflicts",
    "college_coverage",
    "college_assessments",
    "college_assessment_transitions",
    "college_assessment_dependencies",
    "college_lifecycle_tombstones",
}
FORBIDDEN_OUTPUT_KEYS = {
    "raw",
    "raw_body",
    "body",
    "transcript",
    "email_body",
    "provider_payload",
    "document_text",
    "conversation_text",
    "content",
    "excerpt",
    "full_text",
    "message",
    "note",
    "notes",
    "raw_text",
    "text",
}
SAFE_IDENTITY_ATTRIBUTE_KEYS = {
    "academic_period",
    "academic_year",
    "campus",
    "catalog_code",
    "code",
    "end",
    "kind",
    "label",
    "name",
    "normalized_name",
    "official_name",
    "organizer",
    "scope",
    "section_code",
    "skill",
    "start",
    "subject_code",
    "system",
    "temporal_identity",
    "title",
    "topic",
}
RECORD_ORDER = {
    "identity": 0,
    "claim": 1,
    "conflict": 2,
    "coverage": 3,
    "assessment": 4,
}


class CollegeReadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TrustedCollegeContext:
    """Server-created authentication and authorization context."""

    actor_id: str
    workspace_id: str
    allowed_course_ids: frozenset[str] | None = None
    allow_cross_course: bool = True

    def __post_init__(self) -> None:
        if not self.actor_id.strip() or not self.workspace_id.strip():
            raise CollegeReadError("invalid_auth_context", "Trusted College identity is incomplete.")


@dataclass(frozen=True)
class CollegeStateReadRequest:
    scope: Literal["course", "cross_course"]
    horizon_start: datetime
    horizon_end: datetime
    timezone_name: str
    course_ids: tuple[str, ...] = ()
    limit: int = 25
    cursor: str | None = None


@dataclass(frozen=True)
class CollegeStatusReadRequest:
    command_id: str | None = None
    idempotency_key: str | None = None
    receipt_id: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise CollegeReadError("stored_state_invalid", "Stored College state is malformed.") from exc


def _bounded_text(value: Any, *, maximum: int = MAX_OUTPUT_STRING_CHARS) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= maximum else text[:maximum]


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return None
    if isinstance(value, dict):
        result = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            name = str(key)
            lowered = name.lower()
            if (
                lowered in FORBIDDEN_OUTPUT_KEYS
                or lowered.startswith("raw_")
                or lowered.endswith("_body")
                or lowered.endswith("_transcript")
            ):
                continue
            result[name] = _safe_value(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_safe_value(item, depth=depth + 1) for item in value[:MAX_RECEIPT_IDS]]
    if isinstance(value, str):
        return _bounded_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bounded_text(value)


def _evidence_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item)[:MAX_EVIDENCE_REFERENCE_CHARS]
        for item in value[:MAX_EVIDENCE_REFERENCES]
    ]


def _safe_identity_attributes(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _safe_value(item)
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        if str(key).lower() in SAFE_IDENTITY_ATTRIBUTE_KEYS
    }


class CollegeReadService:
    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.database_path = str(database_path or _database_path())
        self.clock = clock

    def get_college_state(
        self,
        auth: TrustedCollegeContext,
        request: CollegeStateReadRequest,
    ) -> dict[str, Any]:
        normalized = self._validate_state_request(auth, request)
        connection = self._open_read_only()
        if connection is None:
            return self._empty_state("uninitialized", normalized)
        try:
            connection.execute("BEGIN")
            if not self._schema_ready(connection):
                return self._empty_state("uninitialized", normalized)
            key = self._cursor_key(connection)
            snapshot_id = self._snapshot_id(connection, auth, key)
            canonical_version = self._canonical_version(connection, auth)
            requested_ids, authorized_subjects = self._authorized_subjects(
                connection, auth, normalized["scope"], normalized["course_ids"]
            )
            if requested_ids is None:
                return self._empty_state(
                    "not_found", normalized, snapshot_id=snapshot_id,
                    canonical_version=canonical_version,
                )
            query_fingerprint = self._query_fingerprint(normalized, auth)
            offset = self._decode_cursor(
                request.cursor, key=key, snapshot_id=snapshot_id,
                query_fingerprint=query_fingerprint,
            )
            records, diagnostics = self._state_records(
                connection, auth, normalized, authorized_subjects
            )
            records.sort(key=lambda item: (
                RECORD_ORDER[item["record_type"]], item["record_id"]
            ))
            page = records[offset:offset + normalized["limit"]]
            if len(_json({"records": page, "diagnostics": diagnostics}).encode()) > MAX_PAGE_BYTES:
                raise CollegeReadError("response_too_large", "College read page exceeds the fixed output bound.")
            next_offset = offset + len(page)
            next_cursor = None
            if next_offset < len(records):
                next_cursor = self._encode_cursor(
                    key=key, snapshot_id=snapshot_id,
                    query_fingerprint=query_fingerprint,
                    offset=next_offset,
                )
            state_status = "missing" if not records else "ready"
            assessment_states = [
                item["assessment_status"] for item in records
                if item["record_type"] == "assessment"
            ]
            return {
                "schema_version": COLLEGE_STATE_READ_VERSION,
                "status": state_status,
                "snapshot": {
                    "snapshot_id": snapshot_id,
                    "canonical_version": canonical_version,
                },
                "scope": self._public_scope(normalized),
                "assessment_status": assessment_states[-1] if assessment_states else "missing",
                "records": page,
                "diagnostics": diagnostics,
                "pagination": {
                    "limit": normalized["limit"],
                    "returned": len(page),
                    "next_cursor": next_cursor,
                },
                "coverage_expectations": [self._blinn_expectation(records)],
            }
        finally:
            connection.rollback()
            connection.close()

    def get_update_status(
        self,
        auth: TrustedCollegeContext,
        request: CollegeStatusReadRequest,
    ) -> dict[str, Any]:
        lookup_kind, lookup_value = self._validate_status_request(request)
        connection = self._open_read_only()
        if connection is None:
            return self._empty_status("uninitialized")
        try:
            connection.execute("BEGIN")
            if not self._schema_ready(connection):
                return self._empty_status("uninitialized")
            key = self._cursor_key(connection)
            snapshot_id = self._snapshot_id(connection, auth, key)
            canonical_version = self._canonical_version(connection, auth)
            row = self._receipt_lookup(
                connection, auth, lookup_kind=lookup_kind, lookup_value=lookup_value
            )
            if row is None or not self._receipt_authorized(connection, auth, row):
                return self._empty_status(
                    "not_found", snapshot_id=snapshot_id,
                    canonical_version=canonical_version,
                )
            receipt = self._public_receipt(connection, auth, row)
            return {
                "schema_version": COLLEGE_STATUS_READ_VERSION,
                "status": "found",
                "snapshot": {
                    "snapshot_id": snapshot_id,
                    "canonical_version": canonical_version,
                },
                "receipt": receipt,
            }
        finally:
            connection.rollback()
            connection.close()

    def _open_read_only(self) -> sqlite3.Connection | None:
        if self.database_path in {"", ":memory:"}:
            raise CollegeReadError(
                "read_only_database_required",
                "College reads require an existing file-backed SQLite database.",
            )
        path = Path(self.database_path).expanduser()
        if not path.is_file():
            return None
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5
            )
        except sqlite3.OperationalError as exc:
            raise CollegeReadError("store_unavailable", "College state is unavailable.") from exc
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA temp_store = MEMORY")
        return connection

    @staticmethod
    def _schema_ready(connection: sqlite3.Connection) -> bool:
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        return REQUIRED_TABLES <= tables

    @staticmethod
    def _cursor_key(connection: sqlite3.Connection) -> bytes:
        row = connection.execute(
            "SELECT value FROM college_store_metadata WHERE key='hmac_key'"
        ).fetchone()
        if row is None or len(bytes(row["value"])) != 32:
            raise CollegeReadError("uninitialized", "College read key is unavailable.")
        return bytes(row["value"])

    @staticmethod
    def _canonical_version(connection: sqlite3.Connection, auth: TrustedCollegeContext) -> int:
        row = connection.execute(
            "SELECT canonical_version FROM college_metadata WHERE actor_id=? AND workspace_id=?",
            (auth.actor_id, auth.workspace_id),
        ).fetchone()
        return int(row["canonical_version"]) if row is not None else 0

    @staticmethod
    def _snapshot_id(
        connection: sqlite3.Connection,
        auth: TrustedCollegeContext,
        key: bytes,
    ) -> str:
        tables = sorted(REQUIRED_TABLES - {"college_store_metadata"})
        markers: list[tuple[str, int, int]] = []
        for table in tables:
            columns = {
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if {"actor_id", "workspace_id"} <= columns:
                row = connection.execute(
                    f"SELECT COUNT(*) AS count, COALESCE(MAX(rowid), 0) AS maximum "
                    f"FROM {table} WHERE actor_id=? AND workspace_id=?",
                    (auth.actor_id, auth.workspace_id),
                ).fetchone()
                markers.append((table, int(row["count"]), int(row["maximum"])))
        context_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_assessment_generations'"
        ).fetchone()
        if context_table is not None:
            row = connection.execute(
                """SELECT generation FROM context_assessment_generations
                   WHERE actor_id=? AND workspace_id=?""",
                (auth.actor_id, auth.workspace_id),
            ).fetchone()
            markers.append(("context_assessment_generation", int(row["generation"]) if row else 0, 0))
        payload = _json(markers).encode()
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    def _validate_state_request(
        self, auth: TrustedCollegeContext, request: CollegeStateReadRequest,
    ) -> dict[str, Any]:
        if request.scope not in {"course", "cross_course"}:
            raise CollegeReadError("invalid_scope", "Scope must be course or cross_course.")
        course_ids = tuple(dict.fromkeys(self._bounded_id(value, "course_id") for value in request.course_ids))
        if len(course_ids) > MAX_COURSE_IDS:
            raise CollegeReadError("request_too_large", "Too many course IDs were requested.")
        if request.scope == "course" and not course_ids:
            raise CollegeReadError("course_scope_required", "Course scope requires a course ID.")
        if request.scope == "cross_course" and course_ids:
            raise CollegeReadError("invalid_scope", "Cross-course scope cannot select course IDs.")
        if request.scope == "cross_course" and not auth.allow_cross_course:
            raise CollegeReadError("scope_not_authorized", "Cross-course College reads are not authorized.")
        try:
            zone = ZoneInfo(request.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise CollegeReadError("invalid_timezone", "A valid IANA timezone is required.") from exc
        start = self._aware_datetime(request.horizon_start, "horizon_start")
        end = self._aware_datetime(request.horizon_end, "horizon_end")
        if end <= start:
            raise CollegeReadError("invalid_horizon", "Horizon end must be after its start.")
        if (end - start).total_seconds() > MAX_HORIZON_DAYS * 86_400:
            raise CollegeReadError("horizon_too_large", "College reads are limited to 31 days.")
        if request.limit < 1 or request.limit > MAX_PAGE_SIZE:
            raise CollegeReadError("invalid_limit", f"Result limit must be between 1 and {MAX_PAGE_SIZE}.")
        if request.cursor is not None and len(request.cursor.encode()) > MAX_CURSOR_BYTES:
            raise CollegeReadError("cursor_too_large", "Pagination cursor is too large.")
        return {
            "scope": request.scope,
            "course_ids": course_ids,
            "horizon_start": start.astimezone(timezone.utc).isoformat(),
            "horizon_end": end.astimezone(timezone.utc).isoformat(),
            "timezone": zone.key,
            "limit": request.limit,
        }

    @staticmethod
    def _validate_status_request(request: CollegeStatusReadRequest) -> tuple[str, str]:
        values = {
            "command_id": request.command_id,
            "idempotency_key": request.idempotency_key,
            "receipt_id": request.receipt_id,
        }
        supplied = [(key, value.strip()) for key, value in values.items() if value and value.strip()]
        if len(supplied) != 1:
            raise CollegeReadError(
                "invalid_lookup", "Exactly one command ID, idempotency key, or receipt ID is required."
            )
        kind, value = supplied[0]
        if len(value) > 128:
            raise CollegeReadError("request_too_large", "Receipt lookup identity is too large.")
        return kind, value

    @staticmethod
    def _bounded_id(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
            raise CollegeReadError("invalid_identifier", f"{field} is invalid.")
        return value.strip()

    @staticmethod
    def _aware_datetime(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise CollegeReadError("invalid_horizon", f"{field} must include a timezone.")
        return value

    def _authorized_subjects(
        self,
        connection: sqlite3.Connection,
        auth: TrustedCollegeContext,
        scope: str,
        course_ids: tuple[str, ...],
    ) -> tuple[tuple[str, ...] | None, frozenset[str] | None]:
        rows = connection.execute(
            """SELECT canonical_id, identity_kind, parent_ids_json
               FROM college_identities WHERE actor_id=? AND workspace_id=?
               ORDER BY canonical_id LIMIT ?""",
            (auth.actor_id, auth.workspace_id, MAX_AUTHORIZED_IDENTITIES + 1),
        ).fetchall()
        if len(rows) > MAX_AUTHORIZED_IDENTITIES:
            raise CollegeReadError("authorized_scope_too_large", "Authorized College scope is too large.")
        identities = {row["canonical_id"]: row for row in rows}
        selected_courses = course_ids
        if scope == "cross_course" and auth.allowed_course_ids is not None:
            selected_courses = tuple(sorted(auth.allowed_course_ids))
            if not selected_courses:
                return tuple(), frozenset()
        if selected_courses:
            for course_id in selected_courses:
                row = identities.get(course_id)
                if row is None or row["identity_kind"] != "course":
                    return None, frozenset()
            if auth.allowed_course_ids is not None and not set(selected_courses) <= set(auth.allowed_course_ids):
                return None, frozenset()
            authorized = set(selected_courses)
            changed = True
            while changed:
                changed = False
                for subject_id, row in identities.items():
                    if subject_id in authorized:
                        continue
                    parents = _loads(row["parent_ids_json"], [])
                    if any(parent in authorized for parent in parents):
                        authorized.add(subject_id)
                        changed = True
            return tuple(selected_courses), frozenset(authorized)
        return tuple(), None

    def _state_records(
        self,
        connection: sqlite3.Connection,
        auth: TrustedCollegeContext,
        request: dict[str, Any],
        authorized_subjects: frozenset[str] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        records: list[dict[str, Any]] = []
        diagnostics: list[dict[str, str]] = []
        identities = self._bounded_rows(
            connection,
            """SELECT canonical_id, identity_kind, identity_status, parent_ids_json,
                      attributes_json, created_at, retired_at
               FROM college_identities WHERE actor_id=? AND workspace_id=?
               ORDER BY identity_kind, canonical_id""",
            (auth.actor_id, auth.workspace_id),
        )
        for row in identities:
            if authorized_subjects is not None and row["canonical_id"] not in authorized_subjects:
                continue
            records.append({
                "record_type": "identity",
                "record_id": row["canonical_id"],
                "canonical_id": row["canonical_id"],
                "identity_kind": row["identity_kind"],
                "identity_status": row["identity_status"],
                "parent_ids": _safe_value(_loads(row["parent_ids_json"], [])),
                "attributes": _safe_identity_attributes(_loads(row["attributes_json"], {})),
                "created_at": row["created_at"],
                "retired_at": row["retired_at"],
            })
        claims = self._bounded_rows(
            connection,
            """SELECT c.claim_id, c.subject_id, c.field, c.value_json,
                      c.claim_status, c.source_class, c.source_actor,
                      c.evidence_refs_json, c.asserted_at, c.observed_at,
                      c.recorded_at, c.freshness_json, c.certainty,
                      c.schema_version, r.revision, r.disposition
               FROM college_claims c JOIN college_field_revisions r
                 ON r.actor_id=c.actor_id AND r.workspace_id=c.workspace_id
                AND r.claim_id=c.claim_id
               WHERE c.actor_id=? AND c.workspace_id=?
                 AND c.claim_status IN ('active','tentative','conflicted')
               ORDER BY c.subject_id, c.field, r.revision, c.claim_id""",
            (auth.actor_id, auth.workspace_id),
        )
        for row in claims:
            if authorized_subjects is not None and row["subject_id"] not in authorized_subjects:
                continue
            records.append({
                "record_type": "claim",
                "record_id": row["claim_id"],
                "claim_id": row["claim_id"],
                "subject_id": row["subject_id"],
                "field": row["field"],
                "revision": int(row["revision"]),
                "revision_disposition": row["disposition"],
                "value": _safe_value(_loads(row["value_json"], None)),
                "claim_status": row["claim_status"],
                "source_class": row["source_class"],
                "source_actor": _bounded_text(row["source_actor"], maximum=128),
                "evidence_refs": _evidence_refs(_loads(row["evidence_refs_json"], [])),
                "asserted_at": row["asserted_at"],
                "observed_at": row["observed_at"],
                "recorded_at": row["recorded_at"],
                "freshness": _safe_value(_loads(row["freshness_json"], {})),
                "certainty": row["certainty"],
                "schema_version": row["schema_version"],
            })
        conflicts = self._bounded_rows(
            connection,
            """SELECT conflict_id, subject_id, field, claim_ids_json, reason,
                      review_status, created_at FROM college_conflicts
               WHERE actor_id=? AND workspace_id=? AND review_status='open'
               ORDER BY created_at, conflict_id""",
            (auth.actor_id, auth.workspace_id),
        )
        for row in conflicts:
            if authorized_subjects is not None and row["subject_id"] not in authorized_subjects:
                continue
            records.append({
                "record_type": "conflict",
                "record_id": row["conflict_id"],
                "conflict_id": row["conflict_id"],
                "subject_id": row["subject_id"],
                "field": row["field"],
                "claim_ids": _safe_value(_loads(row["claim_ids_json"], [])),
                "reason": _bounded_text(row["reason"]),
                "review_status": row["review_status"],
                "created_at": row["created_at"],
            })
        coverage_rows = self._latest_coverage(connection, auth)
        for row in coverage_rows:
            declared_scope = _loads(row["scope_json"], {})
            if not self._stored_scope_authorized(declared_scope, authorized_subjects, request["course_ids"]):
                continue
            coverage, diagnostic = self._honest_coverage_item({
                "record_type": "coverage",
                "record_id": row["coverage_id"],
                "coverage_id": row["coverage_id"],
                "provider": row["provider"],
                "account_id": _bounded_text(row["account_id"], maximum=128),
                "declared_scope": _safe_value(declared_scope),
                "availability": row["availability"],
                "completeness": row["completeness"],
                "freshness": row["freshness"],
                "reason": _bounded_text(row["reason"]),
                "assessed_at": row["assessed_at"],
                "observed_through": row["observed_through"],
                "bounds": _safe_value(_loads(row["bounds_json"], {})),
                "omission_reason": _bounded_text(row["omission_reason"]),
                "freshness_policy": _safe_value(_loads(row["freshness_policy_json"], {})),
                "recorded_at": row["recorded_at"],
            })
            if coverage is not None:
                records.append(coverage)
            if diagnostic is not None and len(diagnostics) < MAX_DIAGNOSTICS:
                diagnostics.append(diagnostic)
        for row in self._bounded_rows(
            connection,
            "SELECT * FROM college_assessments WHERE actor_id=? AND workspace_id=? ORDER BY assessed_at, assessment_id",
            (auth.actor_id, auth.workspace_id),
        ):
            assessment = self._public_assessment(connection, auth, row)
            if not self._stored_scope_authorized(
                assessment["authorized_scope"], authorized_subjects, request["course_ids"]
            ):
                continue
            assessment = self._filter_assessment_scope(
                connection, auth, assessment, authorized_subjects, request["course_ids"]
            )
            if assessment["timezone"] != request["timezone"]:
                continue
            if not self._horizons_overlap(assessment["horizon"], request):
                continue
            records.append(assessment)
        for record in records:
            if len(_json(record).encode()) > MAX_RECORD_BYTES:
                raise CollegeReadError(
                    "stored_record_too_large", "A stored College record exceeds the fixed read bound."
                )
        return records, diagnostics

    def _filter_assessment_scope(
        self,
        connection: sqlite3.Connection,
        auth: TrustedCollegeContext,
        assessment: dict[str, Any],
        authorized_subjects: frozenset[str] | None,
        requested_course_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        if authorized_subjects is None:
            return assessment
        result = dict(assessment)
        retained_coverage = []
        retained_coverage_ids: set[str] = set()
        retained_accounts: set[tuple[str, str]] = set()
        for item in assessment["coverage"] if isinstance(assessment["coverage"], list) else []:
            if not isinstance(item, dict):
                continue
            declared = item.get("scope") or item.get("declared_scope") or {}
            if self._stored_scope_authorized(declared, authorized_subjects, requested_course_ids):
                retained_coverage.append(item)
                if item.get("coverage_id"):
                    retained_coverage_ids.add(str(item["coverage_id"]))
                retained_accounts.add((str(item.get("provider")), str(item.get("account_id"))))
        expected_accounts = {
            (str(item.get("provider")), str(item.get("account_id")))
            for item in assessment["authorized_scope"].get("expected_coverage", [])
            if isinstance(item, dict)
        }
        result["coverage"] = retained_coverage
        result["omissions"] = [
            item for item in assessment["omissions"]
            if isinstance(item, dict)
            and (str(item.get("provider")), str(item.get("account_id")))
            in retained_accounts | expected_accounts
        ]
        result["attention_items"] = [
            item for item in assessment["attention_items"]
            if isinstance(item, dict)
            and (
                str(item.get("subject_id")) in authorized_subjects
                or (
                    str(item.get("subject_id", "")).startswith("coverage:")
                    and tuple(str(item.get("subject_id")).split(":", 2)[1:])
                    in retained_accounts | expected_accounts
                )
            )
        ]
        result["evidence_refs"] = _evidence_refs(sorted({
            str(ref)
            for item in result["attention_items"]
            for ref in item.get("evidence_refs", [])
        }))
        filtered_dependencies = []
        for dependency in assessment["dependencies"]:
            kind = dependency.get("dependency_kind")
            identifier = str(dependency.get("dependency_id"))
            if kind == "subject" and identifier in authorized_subjects:
                filtered_dependencies.append(dependency)
            elif kind == "claim":
                subject = self._target_subject(connection, auth, identifier)
                if subject in authorized_subjects:
                    filtered_dependencies.append(dependency)
            elif kind == "coverage" and identifier in retained_coverage_ids:
                filtered_dependencies.append(dependency)
            elif kind in {"context_snapshot", "context_generation"}:
                filtered_dependencies.append(dependency)
        result["dependencies"] = filtered_dependencies
        if not self._value_scope_authorized(
            result.get("baseline"), authorized_subjects, requested_course_ids
        ):
            result["baseline"] = None
        if not self._value_scope_authorized(
            result.get("window"), authorized_subjects, requested_course_ids
        ):
            result["window"] = None
        return result

    @staticmethod
    def _value_scope_authorized(
        value: Any,
        authorized_subjects: frozenset[str],
        requested_course_ids: tuple[str, ...],
    ) -> bool:
        allowed = set(authorized_subjects) | set(requested_course_ids)
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"subject_id", "course_id", "section_id", "target_id"}:
                    if str(item) not in allowed:
                        return False
                elif key in {"subject_ids", "course_ids", "section_ids", "target_ids"}:
                    if not isinstance(item, list) or not {str(entry) for entry in item} <= allowed:
                        return False
                elif not CollegeReadService._value_scope_authorized(
                    item, authorized_subjects, requested_course_ids
                ):
                    return False
        elif isinstance(value, list):
            return all(
                CollegeReadService._value_scope_authorized(
                    item, authorized_subjects, requested_course_ids
                )
                for item in value
            )
        return True

    @staticmethod
    def _bounded_rows(
        connection: sqlite3.Connection, query: str, params: Iterable[Any],
    ) -> list[sqlite3.Row]:
        rows = connection.execute(f"SELECT * FROM ({query}) LIMIT ?", (*params, MAX_COLLECTION_SCAN + 1)).fetchall()
        if len(rows) > MAX_COLLECTION_SCAN:
            raise CollegeReadError("stored_collection_too_large", "Stored College collection exceeds the read bound.")
        return rows

    @staticmethod
    def _latest_coverage(
        connection: sqlite3.Connection, auth: TrustedCollegeContext,
    ) -> list[sqlite3.Row]:
        rows = connection.execute(
            """SELECT c.* FROM college_coverage c
               WHERE c.actor_id=? AND c.workspace_id=?
                 AND NOT EXISTS (
                   SELECT 1 FROM college_coverage newer
                   WHERE newer.actor_id=c.actor_id AND newer.workspace_id=c.workspace_id
                     AND newer.provider=c.provider AND newer.account_id=c.account_id
                     AND newer.scope_json=c.scope_json
                     AND (newer.recorded_at > c.recorded_at OR
                          (newer.recorded_at=c.recorded_at AND newer.coverage_id>c.coverage_id))
                 ) ORDER BY c.provider, c.account_id LIMIT ?""",
            (auth.actor_id, auth.workspace_id, MAX_COLLECTION_SCAN + 1),
        ).fetchall()
        if len(rows) > MAX_COLLECTION_SCAN:
            raise CollegeReadError("stored_collection_too_large", "Stored College coverage exceeds the read bound.")
        return rows

    @staticmethod
    def _honest_coverage_item(
        item: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        result = dict(item)
        allowed_dimensions = {
            "availability": {"healthy", "unavailable", "pending", "unknown"},
            "completeness": {"complete", "partial", "truncated", "unknown"},
            "freshness": {"fresh", "stale", "unknown"},
        }
        dimensions_valid = all(
            result.get(name) in allowed
            for name, allowed in allowed_dimensions.items()
        )
        is_blinn = str(result.get("provider", "")).lower() == "blinn"
        if not is_blinn and dimensions_valid:
            return result, None
        honest = (
            result.get("availability") in {"pending", "unavailable"}
            and result.get("completeness") == "unknown"
            and result.get("freshness") == "unknown"
            and result.get("reason") == "administrator_approval"
            and result.get("assessed_at") is None
            and result.get("observed_through") is None
        )
        if is_blinn and dimensions_valid and honest:
            return result, None
        return None, {
            "code": "invalid_stored_coverage",
            "provider": _bounded_text(result.get("provider"), maximum=128) or "unknown",
            "coverage_id": _bounded_text(result.get("coverage_id"), maximum=128) or "unknown",
        }

    @staticmethod
    def _stored_scope_authorized(
        stored_scope: Any,
        authorized_subjects: frozenset[str] | None,
        requested_course_ids: tuple[str, ...],
    ) -> bool:
        if authorized_subjects is None:
            return True
        if not isinstance(stored_scope, dict):
            return False
        referenced: set[str] = set()
        for key in ("subject_ids", "course_ids", "section_ids", "target_ids"):
            values = stored_scope.get(key, [])
            if isinstance(values, list):
                referenced.update(str(value) for value in values)
        single = stored_scope.get("subject_id") or stored_scope.get("course_id")
        if single:
            referenced.add(str(single))
        if not referenced:
            return False
        allowed = set(authorized_subjects) | set(requested_course_ids)
        return referenced <= allowed

    def _public_assessment(
        self, connection: sqlite3.Connection, auth: TrustedCollegeContext, row: sqlite3.Row,
    ) -> dict[str, Any]:
        lifecycle = row["lifecycle"]
        invalidated = row["invalidated_at"] is not None
        expired = row["valid_through"] <= self.clock().astimezone(timezone.utc).isoformat()
        status = lifecycle
        if lifecycle == "ready" and invalidated:
            status = "invalidated"
        elif lifecycle == "ready" and expired:
            status = "expired"
        dependencies = connection.execute(
            """SELECT dependency_kind, dependency_id, dependency_version
               FROM college_assessment_dependencies
               WHERE actor_id=? AND workspace_id=? AND assessment_id=?
               ORDER BY dependency_kind, dependency_id LIMIT ?""",
            (auth.actor_id, auth.workspace_id, row["assessment_id"], MAX_RECEIPT_IDS),
        ).fetchall()
        context_dependency = next(
            (
                item for item in dependencies
                if item["dependency_kind"] == "context_generation"
                and item["dependency_id"] == "sid151"
            ),
            None,
        )
        if lifecycle == "ready" and not invalidated and not expired and context_dependency is not None:
            try:
                current_generation = connection.execute(
                    """SELECT generation FROM context_assessment_generations
                       WHERE actor_id=? AND workspace_id=?""",
                    (auth.actor_id, auth.workspace_id),
                ).fetchone()
            except sqlite3.OperationalError:
                current_generation = None
            current_value = int(current_generation["generation"]) if current_generation else 0
            if str(current_value) != str(context_dependency["dependency_version"]):
                status = "invalidated"
        transitions = connection.execute(
            """SELECT sequence, lifecycle, recorded_at FROM college_assessment_transitions
               WHERE actor_id=? AND workspace_id=? AND assessment_id=?
               ORDER BY sequence LIMIT ?""",
            (auth.actor_id, auth.workspace_id, row["assessment_id"], MAX_RECEIPT_TRANSITIONS),
        ).fetchall()
        items = _loads(row["items_json"], [])
        return {
            "record_type": "assessment",
            "record_id": row["assessment_id"],
            "assessment_id": row["assessment_id"],
            "receipt_id": row["receipt_id"],
            "schema_version": row["schema_version"],
            "rule_version": row["rule_version"],
            "lifecycle": lifecycle,
            "assessment_status": status,
            "canonical_input_version": int(row["canonical_input_version"]),
            "context_snapshot_id": row["context_snapshot_id"],
            "context_snapshot_version": row["context_snapshot_version"],
            "authorized_scope": _safe_value(_loads(row["authorized_scope_json"], {})),
            "assessed_at": row["assessed_at"],
            "valid_through": row["valid_through"],
            "timezone": row["timezone"],
            "horizon": _safe_value(_loads(row["horizon_json"], {})),
            "coverage": [
                coverage
                for item in _safe_value(_loads(row["coverage_json"], []))
                if isinstance(item, dict)
                for coverage, _diagnostic in [self._honest_coverage_item(item)]
                if coverage is not None
            ],
            "omissions": _safe_value(_loads(row["omissions_json"], [])),
            "baseline": _safe_value(_loads(row["baseline_json"], None)),
            "window": _safe_value(_loads(row["window_json"], None)),
            "evidence_refs": _evidence_refs(_loads(row["evidence_refs_json"], [])),
            "transient_context_refs": _evidence_refs(_loads(row["transient_context_refs_json"], [])),
            "attention_items": _safe_value(items),
            "result_kind": (
                "attention_items_available" if lifecycle == "ready" and items
                else "insufficient_evidence" if lifecycle == "ready" else None
            ),
            "invalidated_at": row["invalidated_at"],
            "invalidation_reason": _bounded_text(row["invalidation_reason"]),
            "failure": _safe_value(_loads(row["failure_json"], None)),
            "dependencies": [dict(item) for item in dependencies],
            "transitions": [dict(item) for item in transitions],
        }

    @staticmethod
    def _horizons_overlap(stored_horizon: Any, request: dict[str, Any]) -> bool:
        if not isinstance(stored_horizon, dict):
            return False
        start = stored_horizon.get("start")
        end = stored_horizon.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            return False
        try:
            stored_start = datetime.fromisoformat(start).astimezone(timezone.utc)
            stored_end = datetime.fromisoformat(end).astimezone(timezone.utc)
            request_start = datetime.fromisoformat(request["horizon_start"])
            request_end = datetime.fromisoformat(request["horizon_end"])
        except (TypeError, ValueError):
            return False
        return stored_start < request_end and request_start < stored_end

    @staticmethod
    def _blinn_expectation(records: list[dict[str, Any]]) -> dict[str, Any]:
        blinn = [record for record in records if record["record_type"] == "coverage" and record["provider"].lower() == "blinn"]
        if blinn:
            record = blinn[-1]
            return {
                "provider": "blinn",
                "record_status": "recorded",
                "availability": record["availability"],
                "completeness": record["completeness"],
                "freshness": record["freshness"],
                "reason": record["reason"],
                "assessed_at": record["assessed_at"],
                "observed_through": record["observed_through"],
            }
        return {
            "provider": "blinn",
            "record_status": "missing",
            "availability": "pending",
            "completeness": "unknown",
            "freshness": "unknown",
            "reason": "administrator_approval",
            "assessed_at": None,
            "observed_through": None,
        }

    @staticmethod
    def _receipt_lookup(
        connection: sqlite3.Connection,
        auth: TrustedCollegeContext,
        *,
        lookup_kind: str,
        lookup_value: str,
    ) -> sqlite3.Row | None:
        if lookup_kind == "receipt_id":
            return connection.execute(
                "SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=? AND receipt_id=?",
                (auth.actor_id, auth.workspace_id, lookup_value),
            ).fetchone()
        column = "command_id" if lookup_kind == "command_id" else "idempotency_key"
        row = connection.execute(
            f"SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=? AND {column}=?",
            (auth.actor_id, auth.workspace_id, lookup_value),
        ).fetchone()
        if row is not None:
            return row
        return connection.execute(
            f"""SELECT r.* FROM college_receipt_aliases a JOIN college_receipts r
                   ON r.actor_id=a.actor_id AND r.workspace_id=a.workspace_id
                  AND r.receipt_id=a.receipt_id
                 WHERE a.actor_id=? AND a.workspace_id=? AND a.{column}=?""",
            (auth.actor_id, auth.workspace_id, lookup_value),
        ).fetchone()

    def _receipt_authorized(
        self, connection: sqlite3.Connection, auth: TrustedCollegeContext, row: sqlite3.Row,
    ) -> bool:
        if auth.allowed_course_ids is None:
            return True
        requested, authorized = self._authorized_subjects(
            connection, auth, "cross_course", tuple()
        )
        if requested is None or authorized is None:
            return False
        assessment = connection.execute(
            "SELECT authorized_scope_json FROM college_assessments WHERE actor_id=? AND workspace_id=? AND receipt_id=?",
            (auth.actor_id, auth.workspace_id, row["receipt_id"]),
        ).fetchone()
        if assessment is not None:
            return self._stored_scope_authorized(
                _loads(assessment["authorized_scope_json"], {}), authorized, requested
            )
        targets = [
            *(_loads(row["affected_ids_json"], [])),
            *(_loads(row["event_ids_json"], [])),
        ]
        if not targets:
            return False
        for target_id in targets:
            if not self._target_authorized(
                connection, auth, str(target_id), authorized, requested
            ):
                return False
        return True

    def _target_authorized(
        self,
        connection: sqlite3.Connection,
        auth: TrustedCollegeContext,
        target_id: str,
        authorized_subjects: frozenset[str],
        requested_course_ids: tuple[str, ...],
    ) -> bool:
        subject = self._target_subject(connection, auth, target_id)
        if subject is not None:
            return subject in authorized_subjects
        coverage = connection.execute(
            """SELECT scope_json FROM college_coverage
               WHERE actor_id=? AND workspace_id=? AND coverage_id=?""",
            (auth.actor_id, auth.workspace_id, target_id),
        ).fetchone()
        if coverage is not None:
            return self._stored_scope_authorized(
                _loads(coverage["scope_json"], {}),
                authorized_subjects,
                requested_course_ids,
            )
        tombstone = connection.execute(
            """SELECT target_id FROM college_lifecycle_tombstones
               WHERE actor_id=? AND workspace_id=? AND tombstone_id=?""",
            (auth.actor_id, auth.workspace_id, target_id),
        ).fetchone()
        if tombstone is not None and str(tombstone["target_id"]) != target_id:
            return self._target_authorized(
                connection,
                auth,
                str(tombstone["target_id"]),
                authorized_subjects,
                requested_course_ids,
            )
        return False

    @staticmethod
    def _target_subject(
        connection: sqlite3.Connection, auth: TrustedCollegeContext, target_id: str,
    ) -> str | None:
        queries = (
            ("college_identities", "canonical_id", "canonical_id"),
            ("college_claims", "claim_id", "subject_id"),
            ("college_conflicts", "conflict_id", "subject_id"),
            ("college_events", "event_id", "subject_id"),
            ("college_provider_links", "provider_link_id", "canonical_target_id"),
        )
        for table, id_column, subject_column in queries:
            row = connection.execute(
                f"SELECT {subject_column} AS subject_id FROM {table} WHERE actor_id=? AND workspace_id=? AND {id_column}=?",
                (auth.actor_id, auth.workspace_id, target_id),
            ).fetchone()
            if row is not None:
                return str(row["subject_id"])
        return None

    def _public_receipt(
        self, connection: sqlite3.Connection, auth: TrustedCollegeContext, row: sqlite3.Row,
    ) -> dict[str, Any]:
        transitions = connection.execute(
            """SELECT sequence, state, recorded_at FROM college_receipt_transitions
               WHERE actor_id=? AND workspace_id=? AND receipt_id=?
               ORDER BY sequence LIMIT ?""",
            (auth.actor_id, auth.workspace_id, row["receipt_id"], MAX_RECEIPT_TRANSITIONS + 1),
        ).fetchall()
        assessment_row = connection.execute(
            "SELECT * FROM college_assessments WHERE actor_id=? AND workspace_id=? AND receipt_id=?",
            (auth.actor_id, auth.workspace_id, row["receipt_id"]),
        ).fetchone()
        result = {
            "receipt_id": row["receipt_id"],
            "command_id": row["command_id"],
            "idempotency_key": row["idempotency_key"],
            "operation": row["operation"],
            "state": row["state"],
            "canonical_version": row["canonical_version"],
            "event_ids": _safe_value(_loads(row["event_ids_json"], [])[:MAX_RECEIPT_IDS]),
            "affected_ids": _safe_value(_loads(row["affected_ids_json"], [])[:MAX_RECEIPT_IDS]),
            "review_refs": _evidence_refs(_loads(row["review_refs_json"], [])),
            "error_code": row["error_code"],
            "retryable": row["state"] == "retryable_failure",
            "recorded_at": row["recorded_at"],
            "transitions": [dict(item) for item in transitions[:MAX_RECEIPT_TRANSITIONS]],
            "transitions_truncated": len(transitions) > MAX_RECEIPT_TRANSITIONS,
            "assessment": (
                self._public_assessment(connection, auth, assessment_row)
                if assessment_row is not None else None
            ),
        }
        if result["assessment"] is not None and auth.allowed_course_ids is not None:
            requested, authorized = self._authorized_subjects(
                connection, auth, "cross_course", tuple()
            )
            if requested is None or authorized is None:
                result["assessment"] = None
            else:
                result["assessment"] = self._filter_assessment_scope(
                    connection, auth, result["assessment"], authorized, requested
                )
        return result

    @staticmethod
    def _query_fingerprint(
        request: dict[str, Any], auth: TrustedCollegeContext,
    ) -> str:
        stable = {key: value for key, value in request.items() if key != "limit"}
        authorization = {
            "actor_id": auth.actor_id,
            "workspace_id": auth.workspace_id,
            "allowed_course_ids": (
                sorted(auth.allowed_course_ids)
                if auth.allowed_course_ids is not None else None
            ),
            "allow_cross_course": auth.allow_cross_course,
        }
        return hashlib.sha256(
            _json({"request": stable, "authorization": authorization}).encode()
        ).hexdigest()

    @staticmethod
    def _encode_cursor(
        *, key: bytes, snapshot_id: str, query_fingerprint: str, offset: int,
    ) -> str:
        payload = _json({"snapshot": snapshot_id, "query": query_fingerprint, "offset": offset}).encode()
        signature = hmac.new(key, payload, hashlib.sha256).digest()
        encoded_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
        return f"{encoded_payload}.{encoded_signature}"

    @staticmethod
    def _decode_cursor(
        cursor: str | None, *, key: bytes, snapshot_id: str, query_fingerprint: str,
    ) -> int:
        if cursor is None:
            return 0
        try:
            encoded_payload, encoded_signature = cursor.split(".", 1)
            payload_bytes = encoded_payload.encode()
            signature_bytes = encoded_signature.encode()
            payload = base64.urlsafe_b64decode(
                payload_bytes + b"=" * (-len(payload_bytes) % 4)
            )
            signature = base64.urlsafe_b64decode(
                signature_bytes + b"=" * (-len(signature_bytes) % 4)
            )
            if (
                base64.urlsafe_b64encode(payload).decode().rstrip("=") != encoded_payload
                or base64.urlsafe_b64encode(signature).decode().rstrip("=")
                != encoded_signature
            ):
                raise ValueError
            if not hmac.compare_digest(signature, hmac.new(key, payload, hashlib.sha256).digest()):
                raise ValueError
            data = json.loads(payload)
            offset = int(data["offset"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CollegeReadError("invalid_cursor", "Pagination cursor is invalid.") from exc
        if data.get("query") != query_fingerprint or offset < 0:
            raise CollegeReadError("invalid_cursor", "Pagination cursor does not match this request.")
        if data.get("snapshot") != snapshot_id:
            raise CollegeReadError("snapshot_changed", "The requested College snapshot has changed.")
        return offset

    @staticmethod
    def _public_scope(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": request["scope"],
            "course_ids": list(request["course_ids"]),
            "horizon": {
                "start": request["horizon_start"],
                "end": request["horizon_end"],
            },
            "timezone": request["timezone"],
        }

    def _empty_state(
        self,
        status: str,
        request: dict[str, Any],
        *,
        snapshot_id: str | None = None,
        canonical_version: int = 0,
    ) -> dict[str, Any]:
        return {
            "schema_version": COLLEGE_STATE_READ_VERSION,
            "status": status,
            "snapshot": {"snapshot_id": snapshot_id, "canonical_version": canonical_version},
            "scope": self._public_scope(request),
            "assessment_status": "uninitialized" if status == "uninitialized" else "missing",
            "records": [],
            "diagnostics": [],
            "pagination": {"limit": request["limit"], "returned": 0, "next_cursor": None},
            "coverage_expectations": [self._blinn_expectation([])],
        }

    @staticmethod
    def _empty_status(
        status: str, *, snapshot_id: str | None = None, canonical_version: int = 0,
    ) -> dict[str, Any]:
        return {
            "schema_version": COLLEGE_STATUS_READ_VERSION,
            "status": status,
            "snapshot": {"snapshot_id": snapshot_id, "canonical_version": canonical_version},
            "receipt": None,
        }


__all__ = [
    "COLLEGE_STATE_READ_VERSION",
    "COLLEGE_STATUS_READ_VERSION",
    "CollegeReadError",
    "CollegeReadService",
    "CollegeStateReadRequest",
    "CollegeStatusReadRequest",
    "TrustedCollegeContext",
]
