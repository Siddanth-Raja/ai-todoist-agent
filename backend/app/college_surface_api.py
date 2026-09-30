"""Local app entrypoint composing the existing College read and capture services.

This is a transport for the app surface, not another College state owner.
Ordinary reads do not initialize storage or access providers. Mutations use
the existing SID-151/SID-250 application services. Runtime hosting remains a
separate decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from datetime import datetime, timezone
from contextlib import closing
import hmac
import json
import sqlite3
import os

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .college_capture_api import CollegeCaptureAuthenticator, create_college_capture_app
from .college_read_api import CollegeReadAuthenticator, create_college_read_app
from .college_reads import CollegeReadService, CollegeStatusReadRequest
from .conversation_context import (
    CommandIdentity,
    ContextScope,
    ContextStoreError,
    SharedConversationContextService,
)
from .storage import _database_path


CAPTURE_SCOPE = "college-operational"
CAPTURE_VERSION = "1"
LOCAL_ORIGINS = ("http://127.0.0.1:3010", "http://localhost:3010")


def _context_error(exc: ContextStoreError) -> HTTPException:
    status = 409 if exc.code in {"revision_conflict", "idempotency_payload_conflict"} else 400
    if exc.code == "not_found":
        status = 404
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _identity(payload: dict[str, Any]) -> CommandIdentity:
    command_id = payload.get("command_id")
    key = payload.get("idempotency_key")
    if not isinstance(command_id, str) or not isinstance(key, str) or not command_id or not key:
        raise HTTPException(status_code=400, detail="A stable request identity is required")
    return CommandIdentity(command_id, key)


def create_college_surface_app(
    *,
    read_app: FastAPI | None = None,
    capture_app: FastAPI | None = None,
    read_auth: CollegeReadAuthenticator | None = None,
    capture_auth: CollegeCaptureAuthenticator | None = None,
    read_service: CollegeReadService | None = None,
    context_service: SharedConversationContextService | None = None,
) -> FastAPI:
    reader_auth = read_auth or CollegeReadAuthenticator.from_environment()
    writer_auth = capture_auth or CollegeCaptureAuthenticator.from_environment()
    reader = read_service or CollegeReadService()
    application = FastAPI(title="PCOS College app surface", version="1.0.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOCAL_ORIGINS),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Keep the published operation handlers and their request validation intact.
    for source in (
        read_app or create_college_read_app(service=reader, authenticator=reader_auth),
        capture_app or create_college_capture_app(authenticator=writer_auth),
    ):
        for route in source.routes:
            if getattr(route, "path", "").startswith("/college/"):
                application.router.routes.append(route)

    def trusted_scope(authorization: Annotated[str | None, Header()] = None) -> ContextScope:
        read_context = reader_auth.authenticate(authorization)
        capture_context = writer_auth.authenticate(authorization)
        if not (
            hmac.compare_digest(read_context.actor_id, capture_context.actor_id)
            and hmac.compare_digest(read_context.workspace_id, capture_context.workspace_id)
        ):
            raise HTTPException(status_code=403, detail="College scope is inconsistent")
        return ContextScope(read_context.actor_id, read_context.workspace_id)

    def read_connection() -> sqlite3.Connection:
        path = Path(_database_path()).expanduser()
        if not path.is_file():
            raise HTTPException(status_code=503, detail="College context is not initialized")
        try:
            connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            required = {
                "context_capture_consents", "shared_context_items", "context_command_receipts",
                "raw_conversation_evidence", "course_context_bindings", "college_identities",
            }
            found = {row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not required <= found:
                connection.close()
                raise HTTPException(status_code=503, detail="College context is not initialized")
            return connection
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="College context is unavailable") from exc

    def write_context_store() -> SharedConversationContextService:
        try:
            return context_service or SharedConversationContextService()
        except ContextStoreError as exc:
            raise HTTPException(status_code=503, detail="College context is unavailable") from exc

    def unrestricted_context() -> None:
        if not (
            reader_auth.allow_cross_course and writer_auth.allow_cross_course
            and reader_auth.allowed_course_ids is None
            and writer_auth.allowed_section_ids is None
        ):
            raise HTTPException(status_code=403, detail="Broad College context review is unavailable")

    @application.get("/college/surface/consent")
    def inspect_consent(scope: ContextScope = Depends(trusted_scope)) -> dict[str, Any]:
        with closing(read_connection()) as connection:
            row = connection.execute(
                """SELECT revision, capture_enabled, sensitive_retention, granted_at, revoked_at
                   FROM context_capture_consents WHERE actor_id=? AND workspace_id=?
                     AND scope=? AND scope_version=?""",
                (scope.actor_id, scope.workspace_id, CAPTURE_SCOPE, CAPTURE_VERSION),
            ).fetchone()
        current = dict(row) if row else None
        return {
            "scope": CAPTURE_SCOPE,
            "version": CAPTURE_VERSION,
            "active": bool(current and current["capture_enabled"] and not current["revoked_at"]),
            "sensitive_retention": bool(current and current["sensitive_retention"]),
            "revision": current["revision"] if current else None,
            "granted_at": current["granted_at"] if current else None,
            "revoked_at": current["revoked_at"] if current else None,
        }

    @application.post("/college/surface/consent")
    def change_consent(
        payload: Annotated[dict[str, Any], Body()],
        scope: ContextScope = Depends(trusted_scope),
    ) -> dict[str, Any]:
        if set(payload) - {"operation", "command_id", "idempotency_key", "expected_revision"}:
            raise HTTPException(status_code=400, detail="Unexpected consent fields")
        store = write_context_store()
        try:
            if payload.get("operation") == "grant":
                receipt = store.grant_capture_consent(
                    scope, _identity(payload), capture_scope=CAPTURE_SCOPE,
                    scope_version=CAPTURE_VERSION, retain_sensitive=False,
                )
            elif payload.get("operation") == "revoke":
                revision = payload.get("expected_revision")
                if not isinstance(revision, int) or isinstance(revision, bool):
                    raise HTTPException(status_code=400, detail="Consent revision is required")
                receipt = store.revoke_capture_consent(
                    scope, _identity(payload), capture_scope=CAPTURE_SCOPE,
                    scope_version=CAPTURE_VERSION, expected_revision=revision,
                )
            else:
                raise HTTPException(status_code=400, detail="Unsupported consent operation")
        except ContextStoreError as exc:
            raise _context_error(exc) from exc
        return {"state": receipt["state"], "receipt_id": receipt["receipt_id"]}

    @application.get("/college/surface/context")
    def review_context(
        limit: Annotated[int, Query(ge=1, le=25)] = 12,
        scope: ContextScope = Depends(trusted_scope),
    ) -> dict[str, Any]:
        unrestricted_context()
        with closing(read_connection()) as connection:
            rows = connection.execute(
                """SELECT i.item_id, i.content_json, i.status, i.certainty, i.revision,
                          i.asserted_at,
                          CASE WHEN e.content IS NOT NULL AND e.expires_at > ?
                               THEN 1 ELSE 0 END AS raw_source_available
                   FROM shared_context_items i
                   LEFT JOIN raw_conversation_evidence e
                     ON e.actor_id=i.actor_id AND e.workspace_id=i.workspace_id
                    AND e.evidence_id=i.raw_evidence_id
                   WHERE i.actor_id=? AND i.workspace_id=? AND i.scope=?
                     AND i.status IN ('active','needs_review')
                     AND (i.expires_at IS NULL OR i.expires_at > ?)
                   ORDER BY i.updated_at DESC, i.item_id LIMIT ?""",
                (datetime.now(timezone.utc).isoformat(), scope.actor_id, scope.workspace_id,
                 CAPTURE_SCOPE, datetime.now(timezone.utc).isoformat(), limit),
            ).fetchall()
        items = [dict(row) for row in rows]
        return {
            "status": "ready",
            "items": [
                {
                    "item_id": item["item_id"],
                    "summary": str((json.loads(item["content_json"] or "{}") or {}).get("reported_update") or "Review saved update")[:500],
                    "status": item["status"],
                    "certainty": item["certainty"],
                    "revision": item["revision"],
                    "raw_source_available": bool(item["raw_source_available"]),
                    "asserted_at": item["asserted_at"],
                }
                for item in items
            ],
        }

    @application.get("/college/surface/bindings")
    def reviewed_bindings(scope: ContextScope = Depends(trusted_scope)) -> dict[str, Any]:
        with closing(read_connection()) as connection:
            rows = connection.execute(
                """SELECT binding_id, section_id, term_id FROM course_context_bindings
                   WHERE actor_id=? AND workspace_id=? AND revoked_at IS NULL
                     AND valid_from<=? AND (valid_until IS NULL OR valid_until>?)
                   ORDER BY reviewed_at DESC, binding_id LIMIT 25""",
                (scope.actor_id, scope.workspace_id, datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat()),
            ).fetchall()
            result = []
            for row in rows:
                if writer_auth.allowed_section_ids is not None and row["section_id"] not in writer_auth.allowed_section_ids:
                    continue
                if reader_auth.allowed_course_ids is not None:
                    # Course restrictions cannot be safely matched to a section
                    # without the canonical parent relation.
                    continue
                identity = connection.execute(
                    """SELECT attributes_json FROM college_identities
                       WHERE actor_id=? AND workspace_id=? AND canonical_id=?""",
                    (scope.actor_id, scope.workspace_id, row["section_id"]),
                ).fetchone()
                attributes = json.loads(identity["attributes_json"] or "{}") if identity else {}
                label = attributes.get("name") or attributes.get("label") or attributes.get("title")
                if isinstance(label, str) and label.strip():
                    result.append({"binding_id": row["binding_id"], "label": label[:100]})
            return {"bindings": result}

    @application.post("/college/surface/context")
    def change_context(
        payload: Annotated[dict[str, Any], Body()],
        scope: ContextScope = Depends(trusted_scope),
    ) -> dict[str, Any]:
        unrestricted_context()
        allowed = {"operation", "command_id", "idempotency_key", "item_id", "expected_revision", "summary"}
        if set(payload) - allowed:
            raise HTTPException(status_code=400, detail="Unexpected review fields")
        store = write_context_store()
        item_id = payload.get("item_id")
        revision = payload.get("expected_revision")
        if not isinstance(item_id, str) or not isinstance(revision, int) or isinstance(revision, bool):
            raise HTTPException(status_code=400, detail="Review target and revision are required")
        item = store.inspect_item(scope, item_id)
        if item is None or item["scope"] != CAPTURE_SCOPE:
            raise HTTPException(status_code=404, detail="Review item unavailable")
        identity = _identity(payload)
        try:
            if payload.get("operation") == "correct":
                summary = payload.get("summary")
                if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
                    raise HTTPException(status_code=400, detail="A short correction is required")
                receipt = store.correct_context(
                    scope, identity, item_id=item_id, expected_revision=revision,
                    content={"reported_update": summary.strip()}, reason="user_correction",
                    certainty="unknown",
                )
            elif payload.get("operation") == "remove_raw":
                receipt = store.remove_raw_evidence(
                    scope, identity, item_id=item_id, expected_revision=revision,
                )
            elif payload.get("operation") == "forget":
                receipt = store.forget_context(
                    scope, identity, item_id=item_id, expected_revision=revision,
                )
            else:
                raise HTTPException(status_code=400, detail="Unsupported review operation")
        except ContextStoreError as exc:
            raise _context_error(exc) from exc
        return {"state": receipt["state"], "receipt_id": receipt["receipt_id"]}

    @application.get("/college/surface/update-status")
    def surface_update_status(
        command_id: Annotated[str, Query(min_length=1, max_length=128)],
        scope: ContextScope = Depends(trusted_scope),
    ) -> dict[str, Any]:
        # Both HTTP surfaces share the read-only, scope-checked receipt resolver.
        read_context = reader_auth.authenticate(f"Bearer {reader_auth.api_key}")
        result = reader.get_update_status(read_context, CollegeStatusReadRequest(command_id=command_id))
        if result.get("source") == "context":
            unrestricted_context()
        return {"status": result["status"], "source": result.get("source", "college"),
                "receipt": result["receipt"],
                **({"outcome_hint": result["outcome_hint"]} if "outcome_hint" in result else {})}

    return application


app = None if os.getenv("PCOS_SYNTHETIC_RUNTIME") == "1" else create_college_surface_app()
