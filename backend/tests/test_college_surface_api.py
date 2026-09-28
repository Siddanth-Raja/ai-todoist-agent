from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import closing
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.college_capture_api import CollegeCaptureAuthenticator  # noqa: E402
from app.college_read_api import CollegeReadAuthenticator  # noqa: E402
from app.college_reads import CollegeReadService  # noqa: E402
from app.college_surface_api import create_college_surface_app  # noqa: E402
from app.conversation_context import (  # noqa: E402
    CommandIdentity, ContextScope, SharedConversationContextService,
)
from app.college_domain import CollegeDomainService  # noqa: E402


class CollegeSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic.sqlite3"
        self.environment = patch.dict(os.environ, {"APP_DB_PATH": str(self.path)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.scope = ContextScope("student", "workspace")

    def app(self, *, restricted: bool = False):
        read_auth = CollegeReadAuthenticator(
            api_key="synthetic-key", actor_id="student", workspace_id="workspace",
            allowed_course_ids=frozenset({"one-course"}) if restricted else None,
            allow_cross_course=True,
        )
        capture_auth = CollegeCaptureAuthenticator(
            api_key="synthetic-key", actor_id="student", workspace_id="workspace",
            allowed_section_ids=frozenset({"one-section"}) if restricted else None,
            allow_cross_course=True,
        )
        return create_college_surface_app(
            read_auth=read_auth, capture_auth=capture_auth,
            read_service=CollegeReadService(self.path),
        )

    @staticmethod
    def route(application, path: str):
        return next(item.endpoint for item in application.routes if getattr(item, "path", None) == path)

    def initialize(self):
        SharedConversationContextService.initialize_schema()
        CollegeDomainService.initialize_schema()
        service = SharedConversationContextService()
        service.grant_capture_consent(
            self.scope, CommandIdentity("opt-in", "opt-in-key"),
            capture_scope="college-operational", scope_version="1",
        )
        return service

    @staticmethod
    def request(application, method: str, path: str, *, payload=None, query: str = "", authorized=True):
        async def dispatch():
            content = json.dumps(payload).encode() if payload is not None else b""
            headers = [(b"host", b"127.0.0.1")]
            if authorized:
                headers.append((b"authorization", b"Bearer synthetic-key"))
            if payload is not None:
                headers.append((b"content-type", b"application/json"))
            scope = {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "scheme": "http", "method": method, "path": path,
                "raw_path": path.encode(), "query_string": query.encode(),
                "root_path": "", "headers": headers, "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 8003),
            }
            messages = []
            sent = False

            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": content, "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message):
                messages.append(message)

            await application(scope, receive, send)
            status = next(item["status"] for item in messages if item["type"] == "http.response.start")
            data = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
            return status, json.loads(data) if data else None

        return asyncio.run(dispatch())

    def test_get_on_missing_database_does_not_create_storage(self):
        application = self.app()
        self.assertFalse(self.path.exists())
        with self.assertRaises(HTTPException) as caught:
            self.route(application, "/college/surface/consent")(scope=self.scope)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertFalse(self.path.exists())

    def test_get_is_byte_stable_and_context_receipt_is_scoped(self):
        store = self.initialize()
        now = datetime.now(timezone.utc)
        store.capture_context(
            self.scope, CommandIdentity("college-report", "college-report-key"),
            item_id="review-one", capture_scope="college-operational", scope_version="1",
            context_kind="operational_attestation",
            content={"reported_update": "We covered derivatives."},
            source_identity="app:synthetic", source_authority="authenticated_user_report",
            asserted_at=now, raw_content="We covered derivatives.", certainty="unknown",
        )
        store.capture_context(
            self.scope, CommandIdentity("other-report", "other-report-key"),
            item_id="other-one", capture_scope="college-operational", scope_version="1",
            context_kind="operational_attestation",
            content={"reported_update": "A separate note."},
            source_identity="app:synthetic", source_authority="authenticated_user_report",
            asserted_at=now, certainty="unknown",
        )
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE shared_context_items SET scope='other-scope' WHERE item_id='other-one'"
            )
            connection.commit()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        app = self.app()
        consent = self.route(app, "/college/surface/consent")(scope=self.scope)
        context = self.route(app, "/college/surface/context")(limit=12, scope=self.scope)
        status = self.route(app, "/college/surface/update-status")(
            command_id="college-report", scope=self.scope,
        )
        foreign = self.route(app, "/college/surface/update-status")(
            command_id="other-report", scope=self.scope,
        )
        after = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertTrue(consent["active"])
        self.assertEqual([item["summary"] for item in context["items"]], ["We covered derivatives."])
        self.assertTrue(context["items"][0]["raw_source_available"])
        self.assertEqual(status["outcome_hint"], "saved_for_review")
        self.assertEqual(foreign["status"], "not_found")
        self.assertEqual(before, after)

    def test_expired_or_removed_raw_source_is_not_offered(self):
        store = self.initialize()
        now = datetime.now(timezone.utc)
        store.capture_context(
            self.scope, CommandIdentity("raw-report", "raw-report-key"),
            item_id="raw-one", capture_scope="college-operational", scope_version="1",
            context_kind="operational_attestation",
            content={"reported_update": "Report for review"},
            source_identity="app:synthetic", source_authority="authenticated_user_report",
            asserted_at=now, raw_content="Report for review", certainty="unknown",
        )
        app = self.app()
        read = self.route(app, "/college/surface/context")
        self.assertTrue(read(limit=12, scope=self.scope)["items"][0]["raw_source_available"])
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE raw_conversation_evidence SET expires_at=? WHERE actor_id=? AND workspace_id=?",
                ((now - timedelta(seconds=1)).isoformat(), "student", "workspace"),
            )
            connection.commit()
        self.assertFalse(read(limit=12, scope=self.scope)["items"][0]["raw_source_available"])
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE raw_conversation_evidence SET expires_at=?, content=NULL WHERE actor_id=? AND workspace_id=?",
                ((now + timedelta(days=1)).isoformat(), "student", "workspace"),
            )
            connection.commit()
        self.assertFalse(read(limit=12, scope=self.scope)["items"][0]["raw_source_available"])

    def test_restricted_context_does_not_leak_unbound_material(self):
        self.initialize()
        app = self.app(restricted=True)
        with self.assertRaises(HTTPException) as caught:
            self.route(app, "/college/surface/context")(limit=12, scope=self.scope)
        self.assertEqual(caught.exception.status_code, 403)

    def test_authenticated_consent_capture_lifecycle_and_status_routes(self):
        SharedConversationContextService.initialize_schema()
        CollegeDomainService.initialize_schema()
        application = self.app()
        unauthorized, _ = self.request(application, "GET", "/college/surface/consent", authorized=False)
        self.assertEqual(unauthorized, 401)

        command = {"command_id": "consent-one", "idempotency_key": "consent-one-key"}
        status, receipt = self.request(
            application, "POST", "/college/surface/consent",
            payload={"operation": "grant", **command},
        )
        self.assertEqual(status, 200)
        self.assertEqual(receipt["state"], "applied")
        duplicate_status, duplicate = self.request(
            application, "POST", "/college/surface/consent",
            payload={"operation": "grant", **command},
        )
        self.assertEqual(duplicate_status, 200)
        self.assertEqual(duplicate["receipt_id"], receipt["receipt_id"])

        capture = {
            "operation": "capture", "command_id": "report-one", "idempotency_key": "report-one-key",
            "message": "Calc covered continuity today; there was a quick check and an exam warning.",
            "source_surface": "app", "conversation_id": "app-synthetic",
            "asserted_at": datetime.now(timezone.utc).isoformat(), "timezone": "America/Chicago",
        }
        spoof_status, _ = self.request(
            application, "POST", "/college/update",
            payload={**capture, "actor_id": "foreign"},
        )
        self.assertEqual(spoof_status, 400)
        capture_status, captured = self.request(application, "POST", "/college/update", payload=capture)
        self.assertEqual(capture_status, 200)
        self.assertEqual(captured["outcome"], "saved_for_review")
        read_status, status_body = self.request(
            application, "GET", "/college/surface/update-status", query="command_id=report-one",
        )
        self.assertEqual(read_status, 200)
        self.assertEqual(status_body["outcome_hint"], "saved_for_review")
        context_status, context = self.request(application, "GET", "/college/surface/context", query="limit=12")
        self.assertEqual(context_status, 200)
        self.assertEqual(len(context["items"]), 1)
        item = context["items"][0]

        missing_status, _ = self.request(
            application, "POST", "/college/surface/context",
            payload={"operation": "forget", "command_id": "foreign", "idempotency_key": "foreign-key",
                     "item_id": "foreign-item", "expected_revision": 1},
        )
        self.assertEqual(missing_status, 404)
        corrected_status, _ = self.request(
            application, "POST", "/college/surface/context",
            payload={"operation": "correct", "command_id": "correct-one", "idempotency_key": "correct-one-key",
                     "item_id": item["item_id"], "expected_revision": item["revision"],
                     "summary": "We covered continuity; exam date still needs review."},
        )
        self.assertEqual(corrected_status, 200)
        stale_status, _ = self.request(
            application, "POST", "/college/surface/context",
            payload={"operation": "correct", "command_id": "stale", "idempotency_key": "stale-key",
                     "item_id": item["item_id"], "expected_revision": item["revision"],
                     "summary": "Stale overwrite"},
        )
        self.assertEqual(stale_status, 409)
        _, latest = self.request(application, "GET", "/college/surface/context", query="limit=12")
        revised = latest["items"][0]
        raw_status, _ = self.request(
            application, "POST", "/college/surface/context",
            payload={"operation": "remove_raw", "command_id": "raw-one", "idempotency_key": "raw-one-key",
                     "item_id": revised["item_id"], "expected_revision": revised["revision"]},
        )
        self.assertEqual(raw_status, 200)
        _, after_raw = self.request(application, "GET", "/college/surface/context", query="limit=12")
        self.assertFalse(after_raw["items"][0]["raw_source_available"])
        forget_status, _ = self.request(
            application, "POST", "/college/surface/context",
            payload={"operation": "forget", "command_id": "forget-one", "idempotency_key": "forget-one-key",
                     "item_id": revised["item_id"], "expected_revision": after_raw["items"][0]["revision"]},
        )
        self.assertEqual(forget_status, 200)
        _, after_forget = self.request(application, "GET", "/college/surface/context", query="limit=12")
        self.assertEqual(after_forget["items"], [])

        _, consent = self.request(application, "GET", "/college/surface/consent")
        revoke_status, _ = self.request(
            application, "POST", "/college/surface/consent",
            payload={"operation": "revoke", "command_id": "revoke-one", "idempotency_key": "revoke-one-key",
                     "expected_revision": consent["revision"]},
        )
        self.assertEqual(revoke_status, 200)
        _, revoked = self.request(application, "GET", "/college/surface/consent")
        self.assertFalse(revoked["active"])


if __name__ == "__main__":
    unittest.main()
