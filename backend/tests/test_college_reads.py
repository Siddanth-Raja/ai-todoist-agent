from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.college_domain import (  # noqa: E402
    CollegeCommandIdentity,
    CollegeDomainService,
    CollegeScope,
)
from app.college_read_api import (  # noqa: E402
    CollegeReadAuthenticator,
    _reject_spoofing,
    create_college_read_app,
)
from app.conversation_context import SharedConversationContextService  # noqa: E402
from app.college_reads import (  # noqa: E402
    CollegeReadError,
    CollegeReadService,
    CollegeStateReadRequest,
    CollegeStatusReadRequest,
    TrustedCollegeContext,
)
from app.storage import database_connection  # noqa: E402


NOW = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
END = NOW + timedelta(days=1)


class CollegeReadTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "college.sqlite3")
        self.env = patch.dict(os.environ, {"APP_DB_PATH": self.db_path})
        self.env.start()
        self.addCleanup(self.env.stop)
        CollegeDomainService.initialize_schema()
        SharedConversationContextService.initialize_schema()
        self.scope = CollegeScope("actor-a", "workspace-a")
        self.auth = TrustedCollegeContext("actor-a", "workspace-a")
        self.domain = CollegeDomainService(clock=lambda: NOW)
        self.reads = CollegeReadService(self.db_path, clock=lambda: NOW)
        self.counter = 0
        self.identity("course-calc", "course")
        self.identity("section-calc", "section", parents=("course-calc",))
        self.identity("work-calc", "work_item", parents=("section-calc",))
        self.identity("course-chem", "course")
        self.identity("section-chem", "section", parents=("course-chem",))
        self.identity("work-chem", "work_item", parents=("section-chem",))

    def command(self, name: str) -> CollegeCommandIdentity:
        self.counter += 1
        return CollegeCommandIdentity(f"{name}-{self.counter}", f"key-{name}-{self.counter}")

    def identity(self, canonical_id: str, kind: str, *, parents=()):
        return self.domain.create_identity(
            self.scope,
            self.command("identity"),
            canonical_id=canonical_id,
            identity_kind=kind,
            identity_status="resolved",
            attributes={"label": canonical_id},
            parent_ids=parents,
            reviewed_composite={"kind": kind, "code": canonical_id},
        )

    def event(self, event_id: str, subject: str, *, field="completion", value="finished"):
        return {
            "schema_version": "college-event/1.0",
            "event_id": event_id,
            "event_type": "completion_submission_recorded",
            "subject_ref": subject,
            "payload": {field: value},
            "expected_revisions": [
                {"subject_id": subject, "field": field, "revision": "absent"}
            ],
            "source_class": "user_confirmed",
            "source_actor": "user",
            "asserted_at": NOW,
            "evidence": [{"evidence_id": f"evidence-{event_id}"}],
            "certainty": "confirmed",
            "supersedes_event_ids": [],
            "action_intent": "record_fact",
        }

    def request(self, *, scope="cross_course", courses=(), limit=25, cursor=None):
        return CollegeStateReadRequest(
            scope=scope,
            course_ids=tuple(courses),
            horizon_start=NOW,
            horizon_end=END,
            timezone_name="America/Chicago",
            limit=limit,
            cursor=cursor,
        )

    def assess(self, *, subject="work-calc", command=None, valid_through=None):
        return self.domain.request_assessment(
            self.scope,
            command or self.command("assessment"),
            authorized_scope={"kind": "course", "subject_ids": [subject], "course_ids": ["course-calc"]},
            horizon={"start": NOW.isoformat(), "end": END.isoformat()},
            timezone_name="America/Chicago",
            valid_through=valid_through or NOW + timedelta(hours=1),
            baseline={"baseline_id": "baseline-calc", "version": 3},
            window={"kind": "explicit"},
        )

    def test_trusted_scope_and_spoofed_identity_rejection(self):
        authenticator = CollegeReadAuthenticator(
            api_key="secret", actor_id="actor-a", workspace_id="workspace-a"
        )
        with self.assertRaises(HTTPException) as missing:
            authenticator.authenticate(None)
        self.assertEqual(missing.exception.status_code, 401)
        for broken in (
            CollegeReadAuthenticator(api_key=None, actor_id="actor-a", workspace_id="workspace-a"),
            CollegeReadAuthenticator(api_key="secret", actor_id=None, workspace_id="workspace-a"),
            CollegeReadAuthenticator(api_key="secret", actor_id="actor-a", workspace_id=None),
        ):
            with self.assertRaises(HTTPException) as not_configured:
                broken.authenticate("Bearer secret")
            self.assertEqual(not_configured.exception.status_code, 401)
        with self.assertRaises(HTTPException) as wrong_key:
            authenticator.authenticate("Bearer wrong")
        self.assertEqual(wrong_key.exception.status_code, 401)
        trusted = authenticator.authenticate("Bearer secret")
        self.assertEqual((trusted.actor_id, trusted.workspace_id), ("actor-a", "workspace-a"))
        spoofed_query = Request({
            "type": "http", "method": "GET", "path": "/college/state",
            "query_string": b"scope=cross_course&actor_id=attacker&workspace_id=other",
            "headers": [],
        })
        with self.assertRaises(HTTPException) as spoofed:
            _reject_spoofing(spoofed_query, {"scope"})
        self.assertEqual(spoofed.exception.status_code, 400)
        spoofed_header = Request({
            "type": "http", "method": "GET", "path": "/college/state",
            "query_string": b"scope=cross_course",
            "headers": [(b"x-actor-id", b"attacker")],
        })
        with self.assertRaises(HTTPException):
            _reject_spoofing(spoofed_header, {"scope"})
        app = create_college_read_app(service=self.reads, authenticator=authenticator)
        self.assertEqual(
            {route.operation_id for route in app.routes if getattr(route, "operation_id", None)},
            {"get_college_state", "get_update_status"},
        )

    def test_environment_auth_defaults_cross_course_permission_off(self):
        environment = {
            "COLLEGE_ACTOR_ID": "actor-a",
            "COLLEGE_WORKSPACE_ID": "workspace-a",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch(
                "app.college_read_api.get_settings",
                return_value=SimpleNamespace(agent_api_key="secret"),
            ),
        ):
            authenticator = CollegeReadAuthenticator.from_environment()
        self.assertFalse(authenticator.allow_cross_course)
        trusted = authenticator.authenticate("Bearer secret")
        with self.assertRaises(CollegeReadError) as denied:
            self.reads.get_college_state(trusted, self.request())
        self.assertEqual(denied.exception.code, "scope_not_authorized")

    def test_cross_workspace_ids_are_indistinguishable_from_missing(self):
        other = CollegeScope("actor-a", "workspace-other")
        self.domain.create_identity(
            other, CollegeCommandIdentity("other", "other-key"),
            canonical_id="course-private", identity_kind="course",
            identity_status="resolved", attributes={"label": "private"},
            reviewed_composite={"kind": "course", "code": "private"},
        )
        foreign = self.reads.get_college_state(
            self.auth, self.request(scope="course", courses=("course-private",))
        )
        missing = self.reads.get_college_state(
            self.auth, self.request(scope="course", courses=("course-missing",))
        )
        self.assertEqual(foreign["status"], "not_found")
        self.assertEqual(missing["status"], "not_found")
        self.assertEqual(foreign["records"], missing["records"])
        self.assertEqual(foreign["snapshot"], missing["snapshot"])

    def test_course_and_cross_course_scopes(self):
        self.domain.record_update(self.scope, self.command("calc"), [self.event("calc", "work-calc")])
        self.domain.record_update(self.scope, self.command("chem"), [self.event("chem", "work-chem")])
        course = self.reads.get_college_state(
            self.auth, self.request(scope="course", courses=("course-calc",))
        )
        cross = self.reads.get_college_state(self.auth, self.request())
        course_ids = {record.get("subject_id") for record in course["records"]}
        cross_ids = {record.get("subject_id") for record in cross["records"]}
        self.assertIn("work-calc", course_ids)
        self.assertNotIn("work-chem", course_ids)
        self.assertTrue({"work-calc", "work-chem"} <= cross_ids)

    def test_restricted_principal_cannot_expand_scope_or_status(self):
        chem_receipt = self.domain.record_update(
            self.scope, self.command("chem-private"), [self.event("chem-private", "work-chem")]
        )
        restricted = TrustedCollegeContext(
            "actor-a", "workspace-a",
            allowed_course_ids=frozenset({"course-calc"}),
            allow_cross_course=False,
        )
        with self.assertRaises(CollegeReadError) as denied:
            self.reads.get_college_state(restricted, self.request())
        self.assertEqual(denied.exception.code, "scope_not_authorized")
        status = self.reads.get_update_status(
            restricted, CollegeStatusReadRequest(receipt_id=chem_receipt["receipt_id"])
        )
        self.assertEqual(status["status"], "not_found")

    def test_empty_course_allowlist_fails_closed(self):
        receipt = self.domain.record_update(
            self.scope, self.command("empty-allowlist"),
            [self.event("empty-allowlist", "work-calc")],
        )
        restricted = TrustedCollegeContext(
            "actor-a", "workspace-a",
            allowed_course_ids=frozenset(),
            allow_cross_course=True,
        )
        state = self.reads.get_college_state(restricted, self.request())
        status = self.reads.get_update_status(
            restricted, CollegeStatusReadRequest(receipt_id=receipt["receipt_id"])
        )
        self.assertEqual(state["records"], [])
        self.assertEqual(state["status"], "missing")
        self.assertEqual(status["status"], "not_found")

    def test_horizon_timezone_and_oversized_requests_are_rejected(self):
        with self.assertRaises(CollegeReadError) as horizon:
            self.reads.get_college_state(
                self.auth,
                CollegeStateReadRequest(
                    scope="cross_course", horizon_start=NOW,
                    horizon_end=NOW + timedelta(days=32),
                    timezone_name="America/Chicago",
                ),
            )
        self.assertEqual(horizon.exception.code, "horizon_too_large")
        with self.assertRaises(CollegeReadError) as timezone_error:
            self.reads.get_college_state(
                self.auth,
                CollegeStateReadRequest(
                    scope="cross_course", horizon_start=NOW, horizon_end=END,
                    timezone_name="Mars/Olympus",
                ),
            )
        self.assertEqual(timezone_error.exception.code, "invalid_timezone")
        with self.assertRaises(CollegeReadError) as too_many:
            self.reads.get_college_state(
                self.auth, self.request(scope="course", courses=tuple(f"c-{i}" for i in range(17)))
            )
        self.assertEqual(too_many.exception.code, "request_too_large")

    def test_assessments_are_selected_by_horizon_and_timezone(self):
        self.assess()
        matching = self.reads.get_college_state(self.auth, self.request())
        wrong_zone = self.reads.get_college_state(
            self.auth,
            CollegeStateReadRequest(
                scope="cross_course", horizon_start=NOW, horizon_end=END,
                timezone_name="America/New_York",
            ),
        )
        self.assertEqual(matching["assessment_status"], "ready")
        self.assertEqual(wrong_zone["assessment_status"], "missing")

    def test_course_assessment_filters_coverage_attention_and_dependencies(self):
        for suffix, course_id in (("calc", "course-calc"), ("chem", "course-chem")):
            self.domain.record_coverage(
                self.scope, self.command(f"coverage-{suffix}"),
                coverage_id=f"coverage-{suffix}", provider="course_mail",
                account_id=f"account-{suffix}", declared_scope={"course_ids": [course_id]},
                availability="healthy", completeness="complete", freshness="fresh",
                assessed_at=NOW, observed_through=NOW,
                bounds={"course_id": course_id}, freshness_policy={"max_age_hours": 24},
            )
        self.assess()
        response = self.reads.get_college_state(
            self.auth, self.request(scope="course", courses=("course-calc",))
        )
        assessment = next(
            record for record in response["records"] if record["record_type"] == "assessment"
        )
        self.assertEqual(
            {(item["provider"], item["account_id"]) for item in assessment["coverage"]},
            {("course_mail", "account-calc")},
        )
        self.assertNotIn("account-chem", json.dumps(assessment))

    def test_stable_pagination_limits_and_cursor_snapshot(self):
        complete = self.reads.get_college_state(self.auth, self.request(limit=50))["records"]
        first = self.reads.get_college_state(self.auth, self.request(limit=2))
        self.assertEqual(len(first["records"]), 2)
        self.assertIsNotNone(first["pagination"]["next_cursor"])
        second = self.reads.get_college_state(
            self.auth, self.request(limit=2, cursor=first["pagination"]["next_cursor"])
        )
        self.assertTrue(set(record["record_id"] for record in first["records"]).isdisjoint(
            record["record_id"] for record in second["records"]
        ))
        pages = list(first["records"])
        cursor = first["pagination"]["next_cursor"]
        while cursor is not None:
            page = self.reads.get_college_state(
                self.auth, self.request(limit=2, cursor=cursor)
            )
            pages.extend(page["records"])
            cursor = page["pagination"]["next_cursor"]
        self.assertEqual(pages, complete)
        self.domain.record_update(self.scope, self.command("change"), [self.event("change", "work-calc")])
        with self.assertRaises(CollegeReadError) as stale:
            self.reads.get_college_state(
                self.auth, self.request(limit=2, cursor=first["pagination"]["next_cursor"])
            )
        self.assertEqual(stale.exception.code, "snapshot_changed")

    def test_cursor_is_bound_to_actor_workspace_and_permission_set(self):
        calc_auth = TrustedCollegeContext(
            "actor-a", "workspace-a", allowed_course_ids=frozenset({"course-calc"})
        )
        chem_auth = TrustedCollegeContext(
            "actor-a", "workspace-a", allowed_course_ids=frozenset({"course-chem"})
        )
        first = self.reads.get_college_state(calc_auth, self.request(limit=1))
        cursor = first["pagination"]["next_cursor"]
        self.assertIsNotNone(cursor)
        self.assertNotIn("actor-a", cursor)
        self.assertNotIn("workspace-a", cursor)
        with self.assertRaises(CollegeReadError) as permission_swap:
            self.reads.get_college_state(
                chem_auth, self.request(limit=1, cursor=cursor)
            )
        self.assertEqual(permission_swap.exception.code, "invalid_cursor")
        with self.assertRaises(CollegeReadError) as actor_swap:
            self.reads.get_college_state(
                TrustedCollegeContext("actor-other", "workspace-other"),
                self.request(limit=1, cursor=cursor),
            )
        self.assertEqual(actor_swap.exception.code, "invalid_cursor")
        tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
        with self.assertRaises(CollegeReadError) as altered:
            self.reads.get_college_state(
                calc_auth, self.request(limit=1, cursor=tampered)
            )
        self.assertEqual(altered.exception.code, "invalid_cursor")

    def test_missing_and_uninitialized_state_do_not_create_schema_or_file(self):
        initialized_missing = self.reads.get_college_state(
            TrustedCollegeContext("actor-missing", "workspace-missing"), self.request()
        )
        self.assertEqual(initialized_missing["status"], "missing")
        self.assertEqual(initialized_missing["assessment_status"], "missing")
        missing_path = os.path.join(self.tempdir.name, "absent.sqlite3")
        service = CollegeReadService(missing_path, clock=lambda: NOW)
        result = service.get_college_state(self.auth, self.request())
        self.assertEqual(result["status"], "uninitialized")
        self.assertFalse(Path(missing_path).exists())
        blank_path = os.path.join(self.tempdir.name, "blank.sqlite3")
        sqlite3.connect(blank_path).close()
        before = Path(blank_path).read_bytes()
        result = CollegeReadService(blank_path, clock=lambda: NOW).get_college_state(
            self.auth, self.request()
        )
        self.assertEqual(result["status"], "uninitialized")
        self.assertEqual(before, Path(blank_path).read_bytes())

    def test_state_and_evidence_output_have_hard_content_bounds(self):
        self.domain.record_update(
            self.scope, self.command("bounded"), [self.event("bounded", "work-calc")]
        )
        with database_connection() as connection:
            connection.execute(
                "UPDATE college_claims SET evidence_refs_json=? WHERE event_id='bounded'",
                (json.dumps(["e" * 500 for _ in range(30)]),),
            )
        bounded = self.reads.get_college_state(self.auth, self.request())
        claim = next(record for record in bounded["records"] if record["record_type"] == "claim")
        self.assertEqual(len(claim["evidence_refs"]), 16)
        self.assertTrue(all(len(value) == 256 for value in claim["evidence_refs"]))
        with database_connection() as connection:
            connection.execute(
                "UPDATE college_claims SET value_json=? WHERE event_id='bounded'",
                (json.dumps({"safe": "x" * 20_000}),),
            )
        result = self.reads.get_college_state(self.auth, self.request())
        claim = next(record for record in result["records"] if record["record_type"] == "claim")
        self.assertEqual(len(claim["value"]["safe"]), 1_000)

    def test_expired_and_invalidated_assessments_are_honest(self):
        self.assess(valid_through=NOW + timedelta(minutes=1))
        expired = CollegeReadService(
            self.db_path, clock=lambda: NOW + timedelta(hours=1)
        ).get_college_state(self.auth, self.request())
        self.assertEqual(expired["assessment_status"], "expired")
        current_assessment = next(
            record for record in expired["records"] if record["record_type"] == "assessment"
        )
        with database_connection() as connection:
            connection.execute(
                "UPDATE college_assessments SET invalidated_at=?, invalidation_reason=? WHERE assessment_id=?",
                (NOW.isoformat(), "test-change", current_assessment["assessment_id"]),
            )
        invalidated = self.reads.get_college_state(self.auth, self.request())
        self.assertEqual(invalidated["assessment_status"], "invalidated")

    def test_assessment_queued_running_ready_and_failed_states(self):
        queued_receipt = self.domain.queue_assessment(
            self.scope, self.command("queued"),
            authorized_scope={"kind": "course", "subject_ids": ["work-calc"], "course_ids": ["course-calc"]},
            horizon={"start": NOW.isoformat(), "end": END.isoformat()},
            timezone_name="America/Chicago", valid_through=NOW + timedelta(hours=1),
        )
        queued_id = queued_receipt["affected_ids"][0]
        queued = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id=queued_receipt["receipt_id"])
        )
        self.assertEqual(queued["receipt"]["assessment"]["assessment_status"], "queued")
        self.domain.start_assessment(self.scope, assessment_id=queued_id)
        running = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id=queued_receipt["receipt_id"])
        )
        self.assertEqual(running["receipt"]["assessment"]["assessment_status"], "running")
        self.domain.fail_assessment(
            self.scope, assessment_id=queued_id, code="transient", message="private", retryable=True
        )
        failed = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id=queued_receipt["receipt_id"])
        )
        self.assertEqual(failed["receipt"]["assessment"]["assessment_status"], "failed")
        self.assertTrue(failed["receipt"]["retryable"])
        ready_receipt = self.assess(command=self.command("ready"))
        ready = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id=ready_receipt["receipt_id"])
        )
        self.assertEqual(ready["receipt"]["assessment"]["assessment_status"], "ready")

    def test_receipt_states_and_history_are_preserved(self):
        applied = self.domain.record_update(
            self.scope, self.command("applied"), [self.event("applied", "work-calc")]
        )
        relayed = {
            "schema_version": "college-event/1.0",
            "event_id": "review",
            "event_type": "deadline_corrected",
            "subject_ref": "work-chem",
            "payload": {
                "replacement": {
                    "value": "2026-09-25", "timezone": "America/Chicago",
                    "precision": "date", "kind": "official",
                },
                "reason": "professor reportedly changed it",
            },
            "expected_revisions": [
                {"subject_id": "work-chem", "field": "deadline", "revision": "absent"}
            ],
            "source_class": "user_relayed_instructor",
            "source_actor": "user",
            "asserted_at": NOW,
            "evidence": [{"evidence_id": "evidence-review"}],
            "certainty": "possible",
            "supersedes_event_ids": [],
            "action_intent": "record_fact",
        }
        needs_review = self.domain.record_update(self.scope, self.command("review"), [relayed])
        queued = self.domain.queue_assessment(
            self.scope, self.command("received"),
            authorized_scope={"kind": "course", "subject_ids": ["work-calc"], "course_ids": ["course-calc"]},
            horizon={"start": NOW.isoformat(), "end": END.isoformat()},
            timezone_name="America/Chicago", valid_through=NOW + timedelta(hours=1),
        )
        with database_connection() as connection:
            now = NOW.isoformat()
            for suffix, state in (("rejected", "rejected"), ("retry", "retryable_failure")):
                connection.execute(
                    "INSERT INTO college_receipts VALUES (?, ?, ?, ?, ?, 'test', ?, ?, NULL, '[]', '[]', '[]', ?, NULL, ?)",
                    ("actor-a", "workspace-a", f"receipt-{suffix}", f"command-{suffix}", f"key-{suffix}",
                     f"hash-{suffix}", state, suffix if state != "received" else None, now),
                )
                connection.execute(
                    "INSERT INTO college_receipt_transitions VALUES (?, ?, ?, 1, ?, ?)",
                    ("actor-a", "workspace-a", f"receipt-{suffix}", state, now),
                )
        expected = {
            applied["receipt_id"]: "applied",
            needs_review["receipt_id"]: "needs_review",
            queued["receipt_id"]: "received",
            "receipt-rejected": "rejected",
            "receipt-retry": "retryable_failure",
        }
        for receipt_id, state in expected.items():
            result = self.reads.get_update_status(
                self.auth, CollegeStatusReadRequest(receipt_id=receipt_id)
            )
            self.assertEqual(result["receipt"]["state"], state)
            self.assertGreaterEqual(len(result["receipt"]["transitions"]), 1)

    def test_status_lookup_by_command_key_and_missing(self):
        command = self.command("lookup")
        receipt = self.domain.record_update(
            self.scope, command, [self.event("lookup", "work-calc")]
        )
        for request in (
            CollegeStatusReadRequest(command_id=command.command_id),
            CollegeStatusReadRequest(idempotency_key=command.idempotency_key),
            CollegeStatusReadRequest(receipt_id=receipt["receipt_id"]),
        ):
            self.assertEqual(self.reads.get_update_status(self.auth, request)["status"], "found")
        self.assertEqual(
            self.reads.get_update_status(
                self.auth, CollegeStatusReadRequest(command_id="missing")
            )["status"],
            "not_found",
        )

    def test_repeated_reads_have_no_database_changes_or_hidden_side_effects(self):
        receipt = self.assess()
        with database_connection() as connection:
            before_counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "college_receipts", "college_assessments", "college_coverage",
                    "interaction_baselines", "provider_record_checkpoints",
                )
            }
            before_changes = connection.total_changes
        before_bytes = Path(self.db_path).read_bytes()
        first = self.reads.get_college_state(self.auth, self.request())
        status = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id=receipt["receipt_id"])
        )
        second = self.reads.get_college_state(self.auth, self.request())
        after_bytes = Path(self.db_path).read_bytes()
        with database_connection() as connection:
            after_counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before_counts
            }
            after_changes = connection.total_changes
        self.assertEqual(first, second)
        self.assertEqual(status["status"], "found")
        self.assertEqual(before_counts, after_counts)
        self.assertEqual(before_changes, after_changes)
        self.assertEqual(before_bytes, after_bytes)

    def test_raw_and_forgotten_content_never_resurface(self):
        with database_connection() as connection:
            connection.execute(
                "UPDATE college_identities SET attributes_json=? WHERE canonical_id='work-calc'",
                (json.dumps({
                    "label": "work", "raw_body": "RAW-SECRET",
                    "content": "CONTENT-SECRET", "notes": "NOTES-SECRET",
                    "unreviewed_private_field": "ATTRIBUTE-SECRET",
                }),),
            )
        response = self.reads.get_college_state(self.auth, self.request())
        self.assertNotIn("RAW-SECRET", json.dumps(response))
        self.assertNotIn("CONTENT-SECRET", json.dumps(response))
        self.assertNotIn("NOTES-SECRET", json.dumps(response))
        self.assertNotIn("ATTRIBUTE-SECRET", json.dumps(response))
        source_receipt = self.domain.record_update(
            self.scope, self.command("forget-source"), [self.event("forget-source", "work-calc")]
        )
        claim_id = self.domain.inspect_state(self.scope)["claims"][0]["claim_id"]
        forget_receipt = self.domain.forget_claim(
            self.scope, self.command("forget"), claim_id=claim_id, reason="user_requested"
        )
        forgotten = self.reads.get_college_state(self.auth, self.request())
        self.assertNotIn(claim_id, json.dumps(forgotten))
        history = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id=source_receipt["receipt_id"])
        )
        serialized = json.dumps(history)
        self.assertNotIn("RAW-SECRET", serialized)
        self.assertNotIn("CONTENT-SECRET", serialized)
        lifecycle_history = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id=forget_receipt["receipt_id"])
        )
        self.assertEqual(lifecycle_history["receipt"]["operation"], "forget_claim")
        self.assertNotIn("RAW-SECRET", json.dumps(lifecycle_history))

    def test_foreign_receipt_and_missing_receipt_have_identical_public_result(self):
        other_scope = CollegeScope("actor-other", "workspace-other")
        receipt = self.domain.create_identity(
            other_scope, CollegeCommandIdentity("foreign-command", "foreign-key"),
            canonical_id="foreign-course", identity_kind="course",
            identity_status="resolved", attributes={"label": "PRIVATE-FOREIGN"},
            reviewed_composite={"kind": "course", "code": "foreign"},
        )
        foreign = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id=receipt["receipt_id"])
        )
        missing = self.reads.get_update_status(
            self.auth, CollegeStatusReadRequest(receipt_id="missing-receipt")
        )
        self.assertEqual(foreign, missing)
        self.assertNotIn("PRIVATE-FOREIGN", json.dumps(foreign))

    def test_blinn_pending_representation_never_claims_a_check(self):
        missing = self.reads.get_college_state(self.auth, self.request())
        blinn = missing["coverage_expectations"][0]
        self.assertEqual(
            (blinn["record_status"], blinn["availability"], blinn["completeness"], blinn["freshness"]),
            ("missing", "pending", "unknown", "unknown"),
        )
        self.assertIsNone(blinn["assessed_at"])
        self.assertIsNone(blinn["observed_through"])

    def test_invalid_recorded_blinn_coverage_fails_closed(self):
        self.domain.record_coverage(
            self.scope, self.command("dishonest-blinn"), coverage_id="blinn-invalid",
            provider="blinn", account_id="blinn-student",
            declared_scope={"course_ids": ["course-calc"]},
            availability="healthy", completeness="complete", freshness="fresh",
            assessed_at=NOW, observed_through=NOW,
            bounds={"course_id": "course-calc"}, freshness_policy={"max_age_hours": 24},
        )
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE college_coverage SET availability='invalid' WHERE coverage_id='blinn-invalid'"
            )
            connection.commit()
        finally:
            connection.close()
        response = self.reads.get_college_state(
            self.auth, self.request(scope="course", courses=("course-calc",))
        )
        self.assertFalse(any(
            record["record_type"] == "coverage" and record["provider"] == "blinn"
            for record in response["records"]
        ))
        self.assertEqual(
            response["diagnostics"],
            [{
                "code": "invalid_stored_coverage",
                "provider": "blinn",
                "coverage_id": "blinn-invalid",
            }],
        )
        blinn = response["coverage_expectations"][0]
        self.assertEqual(
            (blinn["record_status"], blinn["availability"], blinn["completeness"], blinn["freshness"]),
            ("missing", "pending", "unknown", "unknown"),
        )
        self.assertEqual(blinn["reason"], "administrator_approval")
        self.assertIsNone(blinn["assessed_at"])
        self.assertIsNone(blinn["observed_through"])
        self.assertNotIn('"availability": "invalid"', json.dumps(response))

    def test_course_scoped_status_authorizes_coverage_receipts(self):
        receipts = {}
        for suffix, course_id in (("calc", "course-calc"), ("chem", "course-chem")):
            receipts[suffix] = self.domain.record_coverage(
                self.scope, self.command(f"coverage-status-{suffix}"),
                coverage_id=f"coverage-status-{suffix}", provider="course_mail",
                account_id=f"account-{suffix}", declared_scope={"course_ids": [course_id]},
                availability="healthy", completeness="complete", freshness="fresh",
                assessed_at=NOW, observed_through=NOW,
                bounds={"course_id": course_id}, freshness_policy={"max_age_hours": 24},
            )
        restricted = TrustedCollegeContext(
            "actor-a", "workspace-a", allowed_course_ids=frozenset({"course-calc"})
        )
        allowed = self.reads.get_update_status(
            restricted, CollegeStatusReadRequest(receipt_id=receipts["calc"]["receipt_id"])
        )
        denied = self.reads.get_update_status(
            restricted, CollegeStatusReadRequest(receipt_id=receipts["chem"]["receipt_id"])
        )
        self.assertEqual(allowed["status"], "found")
        self.assertEqual(denied["status"], "not_found")

    def test_restart_readback_and_concurrent_reads_are_consistent(self):
        self.domain.record_update(
            self.scope, self.command("restart"), [self.event("restart", "work-calc")]
        )
        first = self.reads.get_college_state(self.auth, self.request())
        restarted = CollegeReadService(self.db_path, clock=lambda: NOW)
        self.assertEqual(first, restarted.get_college_state(self.auth, self.request()))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: restarted.get_college_state(self.auth, self.request()), range(8)))
        self.assertTrue(all(result == first for result in results))

    def test_malformed_status_and_cursor_are_rejected(self):
        for request in (
            CollegeStatusReadRequest(),
            CollegeStatusReadRequest(command_id="a", receipt_id="b"),
            CollegeStatusReadRequest(command_id="x" * 129),
        ):
            with self.assertRaises(CollegeReadError):
                self.reads.get_update_status(self.auth, request)
        with self.assertRaises(CollegeReadError) as cursor:
            self.reads.get_college_state(self.auth, self.request(cursor="not-a-cursor"))
        self.assertEqual(cursor.exception.code, "invalid_cursor")


if __name__ == "__main__":
    unittest.main()
