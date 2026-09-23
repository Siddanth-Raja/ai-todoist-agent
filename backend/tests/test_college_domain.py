from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.college_domain import (  # noqa: E402
    CollegeCommandIdentity,
    CollegeDomainError,
    CollegeDomainService,
    CollegeScope,
)
from app.conversation_context import (  # noqa: E402
    CommandIdentity, ContextScope, SharedConversationContextService,
)
from app.storage import database_connection  # noqa: E402


NOW = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)


class CollegeDomainTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "college.sqlite3")
        self.env = patch.dict(os.environ, {"APP_DB_PATH": self.db_path})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.scope = CollegeScope("actor-a", "workspace-a")
        self.counter = 0
        CollegeDomainService.initialize_schema()
        self.service = CollegeDomainService(clock=lambda: NOW)
        self.identity("section-calc", "section", {"course": "course-calc", "term": "fall-2026"})

    def command(self, prefix="command"):
        self.counter += 1
        return CollegeCommandIdentity(f"{prefix}-{self.counter}", f"key-{prefix}-{self.counter}")

    def identity(self, canonical_id, kind="work_item", composite=None, *, scope=None, service=None):
        return (service or self.service).create_identity(
            scope or self.scope,
            self.command("identity"),
            canonical_id=canonical_id,
            identity_kind=kind,
            identity_status="resolved",
            attributes={"label": canonical_id},
            reviewed_composite=composite or {"section": "section-calc", "code": canonical_id},
        )

    def event(
        self,
        event_id,
        event_type,
        subject,
        payload,
        fields,
        *,
        revisions=None,
        source="user_confirmed",
        evidence=None,
        certainty="confirmed",
        supersedes=(),
        source_key=None,
    ):
        revisions = revisions or {field: "absent" for field in fields}
        item = {
            "schema_version": "college-event/1.0",
            "event_id": event_id,
            "event_type": event_type,
            "subject_ref": subject,
            "payload": payload,
            "expected_revisions": [
                {"subject_id": subject, "field": field, "revision": revisions[field]}
                for field in fields
            ],
            "source_class": source,
            "source_actor": "user" if source.startswith("user_") else "provider:test",
            "asserted_at": NOW,
            "evidence": evidence or [{"evidence_id": f"evidence-{event_id}"}],
            "certainty": certainty,
            "supersedes_event_ids": list(supersedes),
            "action_intent": "record_fact",
        }
        if source_key:
            item["source_independence_key"] = source_key
        return item

    def apply(self, event, *, command=None, service=None, scope=None):
        return (service or self.service).record_update(
            scope or self.scope, command or self.command("facts"), [event]
        )

    def assess(self, *, service=None, scope=None, command=None, subjects=None, context=None):
        return (service or self.service).request_assessment(
            scope or self.scope,
            command or self.command("assessment"),
            authorized_scope={"kind": "course", "subject_ids": subjects or []},
            horizon={"start": NOW.isoformat(), "end": (NOW + timedelta(days=1)).isoformat()},
            timezone_name="America/Chicago",
            valid_through=NOW + timedelta(hours=2),
            baseline={"kind": "explicit", "version": 1},
            window={"kind": "today-through-first-commitment"},
            context_snapshot=context,
        )

    def claims(self, field=None, *, scope=None, service=None):
        rows = (service or self.service).inspect_state(scope or self.scope)["claims"]
        return [row for row in rows if field is None or row["field"] == field]

    def latest_assessment(self, *, service=None, scope=None):
        return (service or self.service).inspect_state(scope or self.scope)["assessments"][-1]

    def test_finished_section_does_not_imply_learning_or_submission(self):
        self.identity("work-2-3")
        self.apply(self.event("e-finished", "completion_submission_recorded", "work-2-3",
                              {"completion": "finished"}, ["completion"]))
        self.apply(self.event("e-learning", "study_need_recorded", "work-2-3",
                              {"statement": "did not learn it", "resolution": "open"},
                              ["learning_need"]))
        fields = {claim["field"] for claim in self.claims()}
        self.assertEqual(fields, {"completion", "learning_need"})
        self.assertNotIn("submission", fields)

    def test_user_relayed_deadline_is_tentative_without_direct_evidence(self):
        self.identity("work-deadline")
        receipt = self.apply(self.event(
            "e-user-deadline", "deadline_corrected", "work-deadline",
            {"replacement": {"value": "2026-09-09", "timezone": "America/Chicago",
                             "precision": "date", "kind": "official"}, "reason": "professor said"},
            ["deadline"], source="user_relayed_instructor",
        ))
        self.assertEqual(receipt["state"], "needs_review")
        self.assertEqual(self.claims("deadline")[0]["claim_status"], "tentative")

    def test_direct_evidence_confirms_a_deadline_correction(self):
        self.identity("work-direct-deadline")
        original = self.event(
            "e-original", "deadline_confirmed", "work-direct-deadline",
            {"deadline": {"value": "2026-09-07", "timezone": "America/Chicago",
                          "precision": "date", "kind": "official"}}, ["deadline"],
            source="document_evidence",
        )
        self.apply(original)
        report = self.event(
            "e-report", "deadline_corrected", "work-direct-deadline",
            {"replacement": {"value": "2026-09-09", "timezone": "America/Chicago",
                             "precision": "date", "kind": "official"}, "reason": "reported"},
            ["deadline"], revisions={"deadline": 1}, source="user_relayed_instructor",
        )
        self.apply(report)
        confirmed = self.event(
            "e-confirmed", "deadline_corrected", "work-direct-deadline",
            {"replacement": {"value": "2026-09-09", "timezone": "America/Chicago",
                             "precision": "date", "kind": "official"}, "reason": "announcement"},
            ["deadline"], revisions={"deadline": 2}, source="provider_observation",
            supersedes=("e-original", "e-report"),
        )
        self.assertEqual(self.apply(confirmed)["state"], "applied")
        active = [row for row in self.claims("deadline") if row["claim_status"] == "active"]
        self.assertEqual(active[0]["value"]["value"], "2026-09-09")

    def test_later_deadline_does_not_reopen_completed_work(self):
        self.identity("work-complete-deadline")
        self.apply(self.event("e-complete", "completion_submission_recorded",
                              "work-complete-deadline", {"completion": "finished"}, ["completion"]))
        self.apply(self.event(
            "e-later", "deadline_corrected", "work-complete-deadline",
            {"replacement": {"value": "2026-09-30", "timezone": "America/Chicago",
                             "precision": "date", "kind": "official"}, "reason": "extended"},
            ["deadline"], source="document_evidence", supersedes=("old-deadline",),
        ))
        self.assertEqual(self.claims("completion")[0]["value"], "finished")

    def test_course_session_preserves_separate_observations_without_inference(self):
        payload = {
            "payload_kind": "session_observation", "session_id": "calc-2026-09-23-a",
            "session_date": "2026-09-23", "timezone": "America/Chicago",
            "date_precision": "date", "entries": [
                {"observation_id": "topic", "kind": "topic_covered", "value": "continuity", "asserted_at": NOW.isoformat()},
                {"observation_id": "check", "kind": "assessment_observed", "value": {"kind": "quick_check", "status": "occurred", "outcome": "unknown"}, "asserted_at": NOW.isoformat()},
                {"observation_id": "exam", "kind": "announcement_reported", "value": "exam warning", "asserted_at": NOW.isoformat()},
            ],
        }
        fields = [f"session:calc-2026-09-23-a:{entry['observation_id']}:{entry['kind']}" for entry in payload["entries"]]
        self.apply(self.event("e-session", "course_progress_recorded", "section-calc", payload, fields))
        recorded = {row["field"] for row in self.claims()}
        self.assertTrue(set(fields).issubset(recorded))
        self.assertFalse({"attendance", "grade", "deadline", "understanding"} & recorded)

    def test_individual_and_team_shorthand_remain_distinct_reviewed_subjects(self):
        self.identity("topic-4-individual")
        self.identity("topic-4-team")
        self.apply(self.event("e-individual", "completion_submission_recorded",
                              "topic-4-individual", {"submission": "submitted"}, ["submission"]))
        self.apply(self.event("e-team", "completion_submission_recorded",
                              "topic-4-team", {"completion": "in_progress"}, ["completion"]))
        self.assertEqual({row["subject_id"] for row in self.claims()},
                         {"topic-4-individual", "topic-4-team"})

    def test_two_transport_events_share_one_semantic_claim_but_keep_events_and_receipts(self):
        self.identity("work-copy")
        first = self.event("e-copy-1", "completion_submission_recorded", "work-copy",
                           {"completion": "finished"}, ["completion"], source_key="source-original")
        second = self.event("e-copy-2", "completion_submission_recorded", "work-copy",
                            {"completion": "finished"}, ["completion"],
                            revisions={"completion": 1}, source_key="source-original")
        self.apply(first)
        self.apply(second)
        with database_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM college_events").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM college_receipts WHERE operation='record_facts'").fetchone()[0], 2)
        self.assertEqual(len(self.claims("completion")), 1)

    def test_same_idempotency_key_with_changed_content_rejects_without_change(self):
        self.identity("work-idempotency")
        command = self.command("same")
        original = self.event("e-same", "completion_submission_recorded", "work-idempotency",
                              {"completion": "finished"}, ["completion"])
        first = self.apply(original, command=command)
        duplicate = self.apply(original, command=command)
        self.assertEqual(duplicate["receipt_id"], first["receipt_id"])
        self.assertTrue(duplicate["duplicate"])
        changed = dict(original)
        changed["payload"] = {"completion": "in_progress"}
        with self.assertRaises(CollegeDomainError) as denied:
            self.apply(changed, command=command)
        self.assertEqual(denied.exception.code, "idempotency_payload_conflict")
        self.assertEqual(len(self.claims("completion")), 1)

    def test_same_event_with_new_transport_identity_retains_both_delivery_receipts(self):
        self.identity("work-event-alias")
        event = self.event("e-alias", "completion_submission_recorded", "work-event-alias",
                           {"completion": "finished"}, ["completion"])
        first = self.apply(event, command=CollegeCommandIdentity("delivery-1", "delivery-key-1"))
        duplicate = self.apply(event, command=CollegeCommandIdentity("delivery-2", "delivery-key-2"))
        self.assertNotEqual(duplicate["receipt_id"], first["receipt_id"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(
            self.service.get_receipt(self.scope, command_id="delivery-2")["receipt_id"],
            duplicate["receipt_id"],
        )
        changed = dict(event)
        changed["payload"] = {"completion": "in_progress"}
        denied = self.apply(
            changed, command=CollegeCommandIdentity("delivery-3", "delivery-key-3")
        )
        self.assertEqual((denied["state"], denied["error_code"]),
                         ("rejected", "event_payload_conflict"))

    def test_credible_same_field_claims_conflict_instead_of_last_write_wins(self):
        self.identity("work-conflict")
        self.apply(self.event("e-d1", "deadline_confirmed", "work-conflict",
                              {"deadline": {"value": "2026-10-01", "timezone": "America/Chicago", "precision": "date", "kind": "official"}},
                              ["deadline"], source="document_evidence"))
        receipt = self.apply(self.event("e-d2", "deadline_confirmed", "work-conflict",
                                        {"deadline": {"value": "2026-10-02", "timezone": "America/Chicago", "precision": "date", "kind": "official"}},
                                        ["deadline"], revisions={"deadline": 1}, source="provider_observation"))
        self.assertEqual(receipt["state"], "needs_review")
        self.assertEqual({row["claim_status"] for row in self.claims("deadline")}, {"conflicted"})

    def test_blinn_pending_does_not_block_independent_tamu_evidence(self):
        self.service.record_coverage(
            self.scope, self.command("coverage"), coverage_id="coverage-blinn",
            provider="blinn", account_id="blinn-student", declared_scope={"kind": "mailbox"},
            availability="pending", completeness="unknown", freshness="unknown",
            reason="administrator_approval", bounds={"material_to_scope": True},
        )
        self.service.record_coverage(
            self.scope, self.command("coverage"), coverage_id="coverage-tamu",
            provider="tamu", account_id="tamu-student", declared_scope={"kind": "mailbox"},
            availability="healthy", completeness="complete", freshness="fresh",
            assessed_at=NOW, observed_through=NOW, bounds={"material_to_scope": True},
            freshness_policy={"max_age_hours": 24},
        )
        self.assess(subjects=["section-calc"])
        assessment = self.latest_assessment()
        self.assertTrue(any(x["provider"] == "blinn" for x in assessment["omissions"]))
        self.assertTrue(any(x["provider"] == "tamu" for x in assessment["coverage"]))

    def test_optional_bonus_never_becomes_required(self):
        self.identity("engr-bonus", "opportunity")
        self.apply(self.event("e-bonus", "opportunity_recorded", "engr-bonus",
                              {"title": "ENGR bonus", "requirement": "optional"},
                              ["opportunity", "requirement"], source="document_evidence"))
        self.assess(subjects=["engr-bonus"])
        categories = {item["category"] for item in self.latest_assessment()["items"]}
        self.assertIn("optional_recommended_opportunities", categories)
        self.assertNotIn("required_obligations", categories)

    def test_selected_commitment_consumes_capacity_despite_provider_free_busy(self):
        self.identity("commitment-club", "commitment")
        self.apply(self.event("e-commitment", "recurring_commitment_recorded", "commitment-club",
                              {"recurrence": "weekly", "attendance_intent": "selected", "provider_free_busy": "free"},
                              ["recurrence", "attendance_intent", "provider_free_busy"]))
        self.assess(subjects=["commitment-club"])
        summaries = [item["summary"] for item in self.latest_assessment()["items"]]
        self.assertTrue(any("consumes capacity" in summary for summary in summaries))

    def test_material_unknown_remains_visible_in_concise_attention(self):
        self.service.record_coverage(
            self.scope, self.command("coverage"), coverage_id="coverage-unknown",
            provider="course_mail", account_id="student", declared_scope={"kind": "mailbox"},
            availability="unknown", completeness="unknown", freshness="unknown",
            bounds={"material_to_scope": True}, omission_reason="not_checked",
        )
        self.assess()
        self.assertIn("material_unknowns", {x["category"] for x in self.latest_assessment()["items"]})

    def test_equivalent_transport_copies_do_not_repeat_attention(self):
        self.identity("work-alert")
        self.apply(self.event("e-alert-1", "study_need_recorded", "work-alert",
                              {"statement": "review limits"}, ["learning_need"], source_key="same-source"))
        self.apply(self.event("e-alert-2", "study_need_recorded", "work-alert",
                              {"statement": "review limits"}, ["learning_need"],
                              revisions={"learning_need": 1}, source_key="same-source"))
        self.assess(subjects=["work-alert"])
        learning = [x for x in self.latest_assessment()["items"] if x["category"] == "learning_needs"]
        self.assertEqual(len(learning), 1)

    def test_course_scope_does_not_include_other_course_or_whole_college_reassurance(self):
        self.identity("work-calc")
        self.identity("work-engr")
        for subject in ("work-calc", "work-engr"):
            self.apply(self.event(f"e-{subject}", "study_need_recorded", subject,
                                  {"statement": f"review {subject}"}, ["learning_need"]))
        self.assess(subjects=["work-calc"])
        assessment = self.latest_assessment()
        self.assertEqual({x["subject_id"] for x in assessment["items"]}, {"work-calc"})
        self.assertEqual(assessment["authorized_scope"]["kind"], "course")

    def test_expired_transient_context_is_excluded_without_resolution_claim(self):
        context = {
            "snapshot_id": "context-snapshot", "version": 1,
            "items": [{"item_id": "ipad-missing", "context_kind": "situational",
                       "scope": "section-calc", "status": "active", "resolution_state": "unresolved",
                       "expires_at": (NOW - timedelta(minutes=1)).isoformat()}],
        }
        self.assess(subjects=["section-calc"], context=context)
        assessment = self.latest_assessment()
        self.assertEqual(assessment["transient_context_refs"], [])
        self.assertFalse(any("resolved" in x["summary"].lower() for x in assessment["items"]))

    def test_context_race_prevents_stale_assessment_publication(self):
        versions = iter([1, 2])
        racing = CollegeDomainService(clock=lambda: NOW, context_version_reader=lambda scope, key: next(versions))
        receipt = self.assess(
            service=racing, command=self.command("race"),
            context={"snapshot_id": "context-race", "version": 1, "items": []},
        )
        self.assertEqual(receipt["state"], "retryable_failure")
        self.assertEqual(receipt["error_code"], "assessment_input_race")
        assessment = self.service.inspect_state(self.scope)["assessments"][0]
        self.assertEqual(assessment["lifecycle"], "failed")
        self.assertFalse(assessment["current"])
        self.assertTrue(assessment["failure"]["retryable"])
        self.assertEqual(
            [item["lifecycle"] for item in assessment["transitions"]],
            ["queued", "running", "failed"],
        )

    def test_cross_actor_workspace_data_is_isolated(self):
        other_scope = CollegeScope("actor-b", "workspace-b")
        self.identity("other-course", "course", scope=other_scope)
        self.assertEqual(self.service.inspect_state(other_scope)["identities"][0]["canonical_id"], "other-course")
        self.assertNotIn("other-course", {x["canonical_id"] for x in self.service.inspect_state(self.scope)["identities"]})
        self.assertIsNone(self.service.get_receipt(other_scope, command_id="identity-1"))

    def test_transaction_failure_rolls_back_domain_and_records_only_failure_receipt(self):
        self.identity("work-rollback")
        failing = CollegeDomainService(
            clock=lambda: NOW,
            failure_injector=lambda point: (_ for _ in ()).throw(RuntimeError("injected"))
            if point == "after_domain_mutation" else None,
        )
        receipt = self.apply(self.event("e-rollback", "completion_submission_recorded",
                                        "work-rollback", {"completion": "finished"}, ["completion"]),
                             service=failing, command=self.command("rollback"))
        self.assertEqual(receipt["state"], "retryable_failure")
        self.assertEqual(self.claims("completion"), [])
        with database_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM college_events WHERE event_id='e-rollback'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM college_field_revisions WHERE subject_id='work-rollback'").fetchone()[0], 0)

    def test_retryable_failure_retries_same_identity_and_transitions_original_receipt(self):
        self.identity("work-retry")
        command = self.command("retryable")
        event = self.event("e-retryable", "completion_submission_recorded", "work-retry",
                           {"completion": "finished"}, ["completion"])
        failing = CollegeDomainService(
            clock=lambda: NOW,
            failure_injector=lambda point: (_ for _ in ()).throw(RuntimeError("injected"))
            if point == "after_domain_mutation" else None,
        )
        failed = self.apply(event, service=failing, command=command)
        applied = self.apply(event, service=CollegeDomainService(clock=lambda: NOW), command=command)
        self.assertEqual(failed["receipt_id"], applied["receipt_id"])
        self.assertEqual(applied["state"], "applied")
        with database_connection() as connection:
            transitions = connection.execute(
                "SELECT state FROM college_receipt_transitions WHERE receipt_id=? ORDER BY sequence",
                (applied["receipt_id"],),
            ).fetchall()
        self.assertEqual(
            [row["state"] for row in transitions],
            ["received", "retryable_failure", "applied"],
        )

    def test_restart_and_schema_migration_preserve_all_canonical_history(self):
        self.identity("work-restart")
        self.apply(self.event("e-restart", "completion_submission_recorded", "work-restart",
                              {"completion": "finished"}, ["completion"]))
        self.service.record_coverage(
            self.scope, self.command("coverage"), coverage_id="coverage-restart",
            provider="tamu", account_id="student", declared_scope={"kind": "mailbox"},
            availability="healthy", completeness="partial", freshness="fresh",
            assessed_at=NOW, observed_through=NOW,
        )
        self.assess(subjects=["work-restart"])
        before = self.service.inspect_state(self.scope)
        CollegeDomainService.initialize_schema()
        restarted = CollegeDomainService(clock=lambda: NOW)
        after = restarted.inspect_state(self.scope)
        self.assertEqual(before, after)
        database_bytes = Path(self.db_path).read_bytes()
        script = """
import json
from app.college_domain import CollegeDomainService, CollegeScope
service = CollegeDomainService()
print(json.dumps(service.inspect_state(CollegeScope('actor-a', 'workspace-a')), sort_keys=True))
"""
        environment = os.environ.copy()
        environment["APP_DB_PATH"] = self.db_path
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        child = subprocess.run(
            [sys.executable, "-c", script], check=True, capture_output=True,
            text=True, env=environment,
        )
        child_state = json.loads(child.stdout)
        self.assertEqual(child_state["canonical_version"], before["canonical_version"])
        self.assertEqual(child_state["identities"], before["identities"])
        self.assertEqual(child_state["claims"], before["claims"])
        self.assertEqual(child_state["coverage"], before["coverage"])
        self.assertEqual(Path(self.db_path).read_bytes(), database_bytes)

    def test_schema_migrates_additively_and_reads_have_no_hidden_writes(self):
        legacy_path = os.path.join(self.tempdir.name, "legacy.sqlite3")
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
            connection.execute("INSERT INTO legacy_marker VALUES ('preserved')")
            connection.commit()
        with patch.dict(os.environ, {"APP_DB_PATH": legacy_path}):
            CollegeDomainService.initialize_schema()
            migrated = CollegeDomainService(clock=lambda: NOW)
            before = os.path.getsize(legacy_path)
            first = migrated.inspect_state(self.scope)
            second = migrated.inspect_state(self.scope)
            after = os.path.getsize(legacy_path)
            with database_connection() as connection:
                marker = connection.execute("SELECT value FROM legacy_marker").fetchone()[0]
                table_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'college_%'"
                ).fetchone()[0]
            self.assertEqual(marker, "preserved")
            self.assertEqual(first, second)
            self.assertEqual(before, after)
            self.assertGreaterEqual(table_count, 14)

    def test_construction_does_not_create_or_migrate_schema(self):
        uninitialized = os.path.join(self.tempdir.name, "uninitialized.sqlite3")
        with closing(sqlite3.connect(uninitialized)) as connection:
            connection.execute("CREATE TABLE legacy_only(value TEXT NOT NULL)")
            connection.execute("INSERT INTO legacy_only VALUES ('preserved')")
            connection.commit()
        before = Path(uninitialized).read_bytes()
        with patch.dict(os.environ, {"APP_DB_PATH": uninitialized}):
            with self.assertRaises(CollegeDomainError) as denied:
                CollegeDomainService(clock=lambda: NOW)
        self.assertEqual(denied.exception.code, "college_schema_uninitialized")
        self.assertEqual(Path(uninitialized).read_bytes(), before)
        with closing(sqlite3.connect(uninitialized)) as connection:
            tables = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
        self.assertEqual(tables, ["legacy_only"])

    def test_identity_never_merges_by_title_alone_and_provider_link_has_no_write_authority(self):
        with self.assertRaises(CollegeDomainError) as denied:
            self.service.create_identity(
                self.scope, self.command("unsafe"), canonical_id="title-only", identity_kind="course",
                identity_status="resolved", attributes={}, reviewed_composite={"title": "Calculus"},
            )
        self.assertEqual(denied.exception.code, "title_only_identity_forbidden")
        receipt = self.service.create_provider_link(
            self.scope, self.command("link"), provider_link_id="link-1", provider="canvas",
            account_id="tamu", record_kind="course", provider_record_id="123",
            purpose="evidence", canonical_target_id="section-calc",
        )
        self.assertEqual(receipt["state"], "applied")
        self.assertNotIn("write", receipt)

    def test_blinn_coverage_cannot_fabricate_a_mailbox_check(self):
        with self.assertRaises(CollegeDomainError) as denied:
            self.service.record_coverage(
                self.scope, self.command("bad-blinn"), coverage_id="bad", provider="blinn",
                account_id="student", declared_scope={"kind": "mailbox"},
                availability="pending", completeness="unknown", freshness="unknown",
                reason="administrator_approval", assessed_at=NOW,
            )
        self.assertEqual(denied.exception.code, "fabricated_blinn_check")

    def test_concurrent_equivalent_delivery_returns_one_receipt_and_one_event(self):
        self.identity("work-concurrent")
        event = self.event("e-concurrent", "completion_submission_recorded", "work-concurrent",
                           {"completion": "finished"}, ["completion"])
        command = CollegeCommandIdentity("concurrent-command", "concurrent-key")

        def deliver(_):
            return CollegeDomainService(clock=lambda: NOW).record_update(self.scope, command, [event])

        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(executor.map(deliver, range(2)))
        self.assertEqual(len({item["receipt_id"] for item in receipts}), 1)
        with database_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM college_events WHERE event_id='e-concurrent'").fetchone()[0], 1)

    def test_fact_change_records_assessment_invalidation(self):
        self.identity("work-invalidation")
        self.assess(subjects=["work-invalidation"])
        assessment_id = self.latest_assessment()["assessment_id"]
        self.apply(self.event("e-invalidate", "completion_submission_recorded", "work-invalidation",
                              {"completion": "finished"}, ["completion"]))
        assessment = self.latest_assessment()
        self.assertEqual(assessment["assessment_id"], assessment_id)
        self.assertIsNotNone(assessment["invalidated_at"])
        self.assertIn("facts_changed", assessment["invalidation_reason"])

    def test_sid151_snapshot_seam_is_bounded_side_effect_free_and_scope_checked(self):
        SharedConversationContextService.initialize_schema()
        context_service = SharedConversationContextService(clock=lambda: NOW)
        context_scope = ContextScope(self.scope.actor_id, self.scope.workspace_id)
        before = context_service.retrieve_context(context_scope)
        snapshot = self.service.context_snapshot_from_sid151(
            self.scope, context_service, context_scope,
            snapshot_id="sid151-snapshot", limit=10, at=NOW,
        )
        after = context_service.retrieve_context(context_scope)
        self.assertEqual(before, after)
        self.assertEqual(snapshot["items"], [])
        with self.assertRaises(CollegeDomainError) as denied:
            self.service.context_snapshot_from_sid151(
                self.scope, context_service, ContextScope("other", "workspace-a"),
                snapshot_id="mismatch",
            )
        self.assertEqual(denied.exception.code, "context_scope_mismatch")

    def test_sid151_generation_makes_ready_assessment_historical_immediately_on_context_change(self):
        SharedConversationContextService.initialize_schema()
        context_service = SharedConversationContextService(clock=lambda: NOW)
        context_scope = ContextScope(self.scope.actor_id, self.scope.workspace_id)
        context_service.grant_capture_consent(
            context_scope, CommandIdentity("grant-context", "grant-context-key"),
            capture_scope="college-operational", scope_version="1",
        )
        context_service.capture_context(
            context_scope, CommandIdentity("capture-context", "capture-context-key"),
            item_id="context-item", capture_scope="college-operational", scope_version="1",
            context_kind="situational", content={"limitation": "device unavailable"},
            source_identity="conversation/message", source_authority="user_confirmed",
            asserted_at=NOW, conversation_id="conversation", raw_content="device unavailable",
            sensitive=False, requires_raw_context=False, certainty="confirmed",
            attestation={"subject_ref": "section-calc", "field": "limitation",
                         "normalized_value": "device unavailable", "source_verified": True},
            expires_at=NOW + timedelta(hours=2), expiry_basis="explicit",
            resolution_state="unresolved",
        )
        snapshot = self.service.context_snapshot_from_sid151(
            self.scope, context_service, context_scope,
            snapshot_id="sid151-generation", at=NOW,
        )
        self.assess(subjects=["section-calc"], context=snapshot)
        self.assertTrue(self.latest_assessment()["current"])
        before_size = os.path.getsize(self.db_path)
        context_service.resolve_situational_context(
            context_scope, CommandIdentity("resolve-context", "resolve-context-key"),
            item_id="context-item", expected_revision=1, resolution_state="resolved",
        )
        restarted = CollegeDomainService(clock=lambda: NOW)
        stale = self.latest_assessment(service=restarted)
        self.assertFalse(stale["current"])
        self.assertEqual(stale["unusable_reason"], "stale_context_generation")
        self.assertIsNone(stale["invalidated_at"])
        self.assertEqual(os.path.getsize(self.db_path), before_size)

    def test_college_lifecycle_revisions_undo_forgetting_and_independent_support(self):
        self.identity("work-lifecycle")
        self.apply(self.event(
            "e-lifecycle-completion", "completion_submission_recorded", "work-lifecycle",
            {"completion": "finished"}, ["completion"],
        ))
        original = self.claims("completion")[0]
        corrected = self.service.correct_claim(
            self.scope, self.command("correct-claim"), claim_id=original["claim_id"],
            expected_revision=1, value="in_progress", reason="user_correction",
        )
        self.assertEqual(corrected["state"], "applied")
        correction = self.claims("completion")[0]
        self.assertEqual(correction["revision"], 2)
        self.assertEqual(correction["value"], "in_progress")
        undone = self.service.undo_update(
            self.scope, self.command("undo-claim"), claim_id=correction["claim_id"],
            expected_revision=2, reason="undo_exact_update",
        )
        self.assertEqual(undone["state"], "applied")
        current = self.claims("completion")[0]
        self.assertEqual((current["revision"], current["value"]), (3, "finished"))
        with self.assertRaises(CollegeDomainError) as obsolete:
            self.service.undo_update(
                self.scope, self.command("obsolete-undo"), claim_id=correction["claim_id"],
                expected_revision=2, reason="obsolete",
            )
        self.assertEqual(obsolete.exception.code, "revision_conflict")

        self.apply(self.event(
            "e-independent-requirement", "recurring_commitment_recorded", "work-lifecycle",
            {"recurrence": "once", "requirement": "required"},
            ["recurrence", "requirement"], source="document_evidence",
        ))
        marker = "PRIVATE-FORGOTTEN-7391"
        self.apply(self.event(
            "e-dependent-learning", "study_need_recorded", "work-lifecycle",
            {"statement": marker}, ["learning_need"], source="inferred_interpretation",
            evidence=[{"evidence_id": "derived", "claim_id": current["claim_id"]}],
        ))
        provider_links_before = self.service.inspect_state(self.scope)["identities"]
        self.service.forget_claim(
            self.scope, self.command("forget-claim"), claim_id=current["claim_id"],
        )
        state = self.service.inspect_state(self.scope)
        self.assertEqual(
            [claim["value"] for claim in state["claims"] if claim["field"] == "requirement"],
            ["required"],
        )
        with database_connection() as connection:
            statuses = {
                row["field"]: row["claim_status"]
                for row in connection.execute(
                    "SELECT field, claim_status FROM college_claims WHERE subject_id='work-lifecycle'"
                ).fetchall()
            }
        self.assertEqual(statuses["learning_need"], "retracted")
        self.assertEqual(provider_links_before, state["identities"])
        self.assertNotIn(marker.encode(), Path(self.db_path).read_bytes())

    def test_raw_evidence_removal_only_degrades_unsupported_interpretation(self):
        self.identity("work-raw")
        self.apply(self.event(
            "e-raw-unsupported", "study_need_recorded", "work-raw",
            {"statement": "review derivatives"}, ["learning_need"],
            source="inferred_interpretation",
            evidence=[{"evidence_id": "raw-unsupported", "excerpt": "needs review"}],
        ))
        self.identity("work-attested")
        self.apply(self.event(
            "e-raw-attested", "study_need_recorded", "work-attested",
            {"statement": "review limits"}, ["learning_need"],
            source="inferred_interpretation",
            evidence=[{"evidence_id": "raw-attested", "excerpt": "review",
                       "retained_attestation": True}],
        ))
        self.service.remove_raw_evidence(
            self.scope, self.command("remove-raw"), evidence_id="raw-unsupported",
        )
        self.service.remove_raw_evidence(
            self.scope, self.command("remove-attested"), evidence_id="raw-attested",
        )
        unsupported = [
            claim for claim in self.claims("learning_need")
            if claim["subject_id"] == "work-raw"
        ][0]
        attested = [
            claim for claim in self.claims("learning_need")
            if claim["subject_id"] == "work-attested"
        ][0]
        self.assertEqual((unsupported["certainty"], unsupported["claim_status"]),
                         ("unknown", "tentative"))
        self.assertEqual(attested["certainty"], "confirmed")
        self.assertTrue(attested["evidence_refs"][0]["retained_attestation"])
        self.assertNotIn("excerpt", attested["evidence_refs"][0])

    def test_lifecycle_retry_uses_one_receipt_and_invalidates_only_with_committed_revision(self):
        self.identity("work-lifecycle-retry")
        self.apply(self.event(
            "e-lifecycle-retry", "completion_submission_recorded", "work-lifecycle-retry",
            {"completion": "finished"}, ["completion"],
        ))
        claim = self.claims("completion")[0]
        self.assess(subjects=["work-lifecycle-retry"])
        assessment_id = self.latest_assessment()["assessment_id"]
        command = self.command("lifecycle-retry")
        failing = CollegeDomainService(
            clock=lambda: NOW,
            failure_injector=lambda point: (_ for _ in ()).throw(RuntimeError("injected"))
            if point == "after_assessment_invalidation" else None,
        )
        failed = failing.correct_claim(
            self.scope, command, claim_id=claim["claim_id"], expected_revision=1,
            value="in_progress", reason="correction",
        )
        self.assertEqual(failed["state"], "retryable_failure")
        self.assertEqual(self.claims("completion")[0]["revision"], 1)
        self.assertIsNone(self.latest_assessment()["invalidated_at"])
        applied = CollegeDomainService(clock=lambda: NOW).correct_claim(
            self.scope, command, claim_id=claim["claim_id"], expected_revision=1,
            value="in_progress", reason="correction",
        )
        self.assertEqual(applied["receipt_id"], failed["receipt_id"])
        self.assertEqual(applied["state"], "applied")
        self.assertEqual(self.claims("completion")[0]["revision"], 2)
        self.assertEqual(self.latest_assessment()["assessment_id"], assessment_id)
        self.assertIsNotNone(self.latest_assessment()["invalidated_at"])

    def test_receipt_boundaries_rejection_restart_batch_and_non_disclosing_lookup(self):
        self.identity("work-receipt")
        event = self.event(
            "e-receipt", "completion_submission_recorded", "work-receipt",
            {"completion": "finished"}, ["completion"],
        )
        command = self.command("durable-receipt")
        received = self.service.receive_update(self.scope, command, [event])
        self.assertEqual(received["state"], "received")
        applied = CollegeDomainService(clock=lambda: NOW).record_update(
            self.scope, command, [event]
        )
        self.assertEqual(applied["state"], "applied")
        replay = self.service.record_update(self.scope, command, [event])
        self.assertTrue(replay["duplicate"])
        with database_connection() as connection:
            transitions = [row[0] for row in connection.execute(
                "SELECT state FROM college_receipt_transitions WHERE receipt_id=? ORDER BY sequence",
                (applied["receipt_id"],),
            )]
        self.assertEqual(transitions, ["received", "applied"])
        invalid = dict(event)
        invalid["event_id"] = "e-invalid-version"
        invalid["schema_version"] = "college-event/2.0"
        rejected = self.service.record_update(
            self.scope, self.command("rejected"), [invalid]
        )
        self.assertEqual((rejected["state"], rejected["error_code"]),
                         ("rejected", "unsupported_event_version"))
        self.assertIsNone(self.service.get_receipt(
            CollegeScope("other", "workspace-a"), command_id=command.command_id
        ))

    def test_assessment_states_are_durable_and_ready_can_mean_insufficient_evidence(self):
        command = self.command("queued-assessment")
        kwargs = {
            "authorized_scope": {"kind": "course", "subject_ids": []},
            "horizon": {"start": NOW.isoformat(),
                        "end": (NOW + timedelta(days=1)).isoformat()},
            "timezone_name": "America/Chicago",
            "valid_through": NOW + timedelta(hours=2),
        }
        queued = self.service.queue_assessment(self.scope, command, **kwargs)
        assessment_id = queued["affected_ids"][0]
        restarted = CollegeDomainService(clock=lambda: NOW)
        self.assertEqual(
            restarted.inspect_state(self.scope)["assessments"][-1]["lifecycle"],
            "queued",
        )
        restarted.start_assessment(self.scope, assessment_id=assessment_id)
        self.assertEqual(
            CollegeDomainService(clock=lambda: NOW).inspect_state(self.scope)["assessments"][-1]["lifecycle"],
            "running",
        )
        failed = restarted.fail_assessment(
            self.scope, assessment_id=assessment_id, code="no_result",
            message="known terminal failure", retryable=False,
        )
        self.assertEqual(failed["state"], "rejected")
        failure = restarted.inspect_state(self.scope)["assessments"][-1]
        self.assertEqual(failure["lifecycle"], "failed")
        self.assertFalse(failure["failure"]["retryable"])
        ready = self.assess(command=self.command("new-assessment"))
        self.assertEqual(ready["state"], "applied")
        result = next(
            item for item in self.service.inspect_state(self.scope)["assessments"]
            if item["assessment_id"] == ready["affected_ids"][0]
        )
        self.assertEqual(result["result_kind"], "insufficient_evidence")
        self.assertEqual(
            [item["lifecycle"] for item in result["transitions"]],
            ["queued", "running", "ready"],
        )

    def test_retryable_assessment_reuses_receipt_and_assessment_history(self):
        command = self.command("retry-assessment")
        failing = CollegeDomainService(
            clock=lambda: NOW,
            failure_injector=lambda point: (_ for _ in ()).throw(RuntimeError("injected"))
            if point == "assessment_running" else None,
        )
        failed = self.assess(service=failing, command=command)
        self.assertEqual(failed["state"], "retryable_failure")
        retried = self.assess(
            service=CollegeDomainService(clock=lambda: NOW), command=command
        )
        self.assertEqual(retried["state"], "applied")
        self.assertEqual(retried["receipt_id"], failed["receipt_id"])
        assessment = self.latest_assessment()
        self.assertEqual(assessment["assessment_id"], failed["affected_ids"][0])
        self.assertEqual(
            [item["lifecycle"] for item in assessment["transitions"]],
            ["queued", "running", "failed", "queued", "running", "ready"],
        )

    def test_concurrent_identity_keys_links_and_provisional_resolution_are_scoped(self):
        def create_provider(index, scope=self.scope):
            try:
                return CollegeDomainService(clock=lambda: NOW).create_identity(
                    scope, CollegeCommandIdentity(f"provider-{index}", f"provider-key-{index}"),
                    canonical_id=f"provider-subject-{index}", identity_kind="work_item",
                    identity_status="resolved", attributes={"title": "Same title"},
                    stable_provider_ref={"provider": "canvas", "account_id": "student",
                                         "record_id": "assignment-1"},
                )["state"]
            except CollegeDomainError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = sorted(executor.map(create_provider, (1, 2)))
        self.assertEqual(outcomes, ["applied", "identity_key_conflict"])
        other = CollegeScope("actor-b", "workspace-b")
        self.assertEqual(create_provider(3, other), "applied")

        self.service.create_provider_link(
            self.scope, self.command("link-race-base"), provider_link_id="link-race-base",
            provider="canvas", account_id="student", record_kind="assignment",
            provider_record_id="assignment-1", purpose="evidence",
            canonical_target_id="provider-subject-1"
            if any(x["canonical_id"] == "provider-subject-1" for x in self.service.inspect_state(self.scope)["identities"])
            else "provider-subject-2",
        )
        target = next(
            x["canonical_id"] for x in self.service.inspect_state(self.scope)["identities"]
            if x["canonical_id"].startswith("provider-subject-")
        )

        def create_link(index):
            try:
                return CollegeDomainService(clock=lambda: NOW).create_provider_link(
                    self.scope, CollegeCommandIdentity(f"link-{index}", f"link-key-{index}"),
                    provider_link_id=f"link-{index}", provider="canvas", account_id="student",
                    record_kind="assignment", provider_record_id="assignment-2",
                    purpose="evidence", canonical_target_id=target,
                )["state"]
            except CollegeDomainError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            link_outcomes = sorted(executor.map(create_link, (1, 2)))
        self.assertEqual(link_outcomes, ["applied", "provider_link_conflict"])

        self.service.create_identity(
            self.scope, self.command("provisional"), canonical_id="provisional-work",
            identity_kind="work_item", identity_status="provisional", attributes={"title": "Lab"},
            reviewed_composite={"section": "section-calc", "candidate": "lab-provisional"},
        )

        def resolve(index):
            try:
                return CollegeDomainService(clock=lambda: NOW).create_identity(
                    self.scope, CollegeCommandIdentity(f"resolve-{index}", f"resolve-key-{index}"),
                    canonical_id=f"resolved-work-{index}", identity_kind="work_item",
                    identity_status="resolved", attributes={"title": "Lab"},
                    reviewed_composite={"section": "section-calc", "candidate": f"lab-{index}"},
                    supersedes_ids=["provisional-work"],
                )["state"]
            except CollegeDomainError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            resolution = sorted(executor.map(resolve, (1, 2)))
        self.assertEqual(resolution, ["applied", "identity_resolution_conflict"])
        provisional = next(
            item for item in self.service.inspect_state(self.scope)["identities"]
            if item["canonical_id"] == "provisional-work"
        )
        self.assertEqual(provisional["identity_status"], "retired")
        self.assertIsNotNone(provisional["retired_at"])

    def test_batch_failures_roll_back_every_domain_boundary_and_membership_is_exact(self):
        self.identity("work-batch-a")
        self.identity("work-batch-b")
        events = [
            self.event("e-batch-a", "completion_submission_recorded", "work-batch-a",
                       {"completion": "finished"}, ["completion"]),
            self.event("e-batch-b", "completion_submission_recorded", "work-batch-b",
                       {"completion": "in_progress"}, ["completion"]),
        ]
        invalid_member = dict(events[1])
        invalid_member["payload"] = {"completion": "not-a-valid-dimension"}
        rejected_member = self.service.record_update(
            self.scope, self.command("invalid-member"), [events[0], invalid_member]
        )
        self.assertEqual((rejected_member["state"], rejected_member["error_code"]),
                         ("rejected", "invalid_dimension_value"))
        omitted_revision = dict(events[0])
        omitted_revision["expected_revisions"] = []
        omitted_revision["event_id"] = "e-omitted-revision"
        rejected_revision = self.service.record_update(
            self.scope, self.command("omitted-revision"), [omitted_revision]
        )
        self.assertEqual((rejected_revision["state"], rejected_revision["error_code"]),
                         ("rejected", "expected_revision_required"))
        duplicate_member = self.service.record_update(
            self.scope, self.command("duplicate-member"), [events[0], events[0]]
        )
        self.assertEqual((duplicate_member["state"], duplicate_member["error_code"]),
                         ("rejected", "duplicate_batch_member"))
        for point in (
            "after_events_before_claims", "after_claims_before_receipt",
            "before_assessment_invalidation", "after_assessment_invalidation",
        ):
            command = self.command(point)
            failing = CollegeDomainService(
                clock=lambda: NOW,
                failure_injector=lambda current, target=point: (_ for _ in ()).throw(
                    RuntimeError(target)
                ) if current == target else None,
            )
            receipt = failing.record_update(self.scope, command, events)
            self.assertEqual(receipt["state"], "retryable_failure")
            with database_connection() as connection:
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM college_events WHERE event_id IN ('e-batch-a','e-batch-b')"
                ).fetchone()[0], 0)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM college_claims WHERE subject_id IN ('work-batch-a','work-batch-b')"
                ).fetchone()[0], 0)
        command = self.command("batch-success")
        applied = self.service.record_update(self.scope, command, events)
        self.assertEqual(applied["state"], "applied")
        self.assertEqual(applied["event_ids"], ["e-batch-a", "e-batch-b"])
        reordered = self.service.record_update(
            self.scope, CollegeCommandIdentity("batch-reordered", "batch-reordered-key"),
            list(reversed(events)),
        )
        self.assertEqual((reordered["state"], reordered["error_code"]),
                         ("rejected", "batch_membership_conflict"))
        with self.assertRaises(CollegeDomainError) as changed_membership:
            self.service.record_update(self.scope, command, [events[0]])
        self.assertEqual(changed_membership.exception.code, "idempotency_payload_conflict")

        self.identity("work-disjoint")
        disjoint = [
            self.event("e-disjoint-completion", "completion_submission_recorded",
                       "work-disjoint", {"completion": "finished"}, ["completion"]),
            self.event("e-disjoint-submission", "completion_submission_recorded",
                       "work-disjoint", {"submission": "submitted"}, ["submission"]),
        ]

        def apply_disjoint(index):
            return CollegeDomainService(clock=lambda: NOW).record_update(
                self.scope,
                CollegeCommandIdentity(f"disjoint-{index}", f"disjoint-key-{index}"),
                [disjoint[index]],
            )["state"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = sorted(executor.map(apply_disjoint, (0, 1)))
        self.assertEqual(outcomes, ["applied", "needs_review"])
        self.assertEqual(
            {claim["field"] for claim in self.claims() if claim["subject_id"] == "work-disjoint"},
            {"completion", "submission"},
        )

    def test_evidence_minimization_and_semantic_corroboration_boundaries(self):
        self.identity("work-evidence")
        forbidden = self.event(
            "e-raw-dump", "study_need_recorded", "work-evidence",
            {"statement": "review"}, ["learning_need"], source="document_evidence",
            evidence=[{"evidence_id": "raw", "raw_body": "entire document"}],
        )
        rejected = self.apply(forbidden)
        self.assertEqual((rejected["state"], rejected["error_code"]),
                         ("rejected", "raw_evidence_forbidden"))

        first = self.event(
            "e-user-copy-1", "completion_submission_recorded", "work-evidence",
            {"completion": "finished"}, ["completion"],
            evidence=[{"evidence_id": "conversation-a", "conversation_id": "a"}],
        )
        second = self.event(
            "e-user-copy-2", "completion_submission_recorded", "work-evidence",
            {"completion": "finished"}, ["completion"],
            revisions={"completion": 1},
            evidence=[{"evidence_id": "conversation-b", "conversation_id": "b"}],
        )
        self.apply(first)
        self.apply(second)
        self.assertEqual(len(self.claims("completion")), 1)

        direct = self.event(
            "e-direct-corroboration", "completion_submission_recorded", "work-evidence",
            {"completion": "finished"}, ["completion"], revisions={"completion": 1},
            source="provider_observation",
            evidence=[{"evidence_id": "canvas-1", "provider": "canvas",
                       "account_id": "student", "record_id": "submission-1"}],
        )
        self.apply(direct)
        self.assertEqual(len(self.claims("completion")), 2)
        second_direct = self.event(
            "e-direct-corroboration-2", "completion_submission_recorded", "work-evidence",
            {"completion": "finished"}, ["completion"], revisions={"completion": 2},
            source="document_evidence",
            evidence=[{"evidence_id": "document-2", "provider": "lms-document",
                       "account_id": "student", "record_id": "submission-proof-2"}],
        )
        self.apply(second_direct)
        self.assertEqual(len(self.claims("completion")), 3)
        self.identity("other-evidence")
        self.apply(self.event(
            "e-other-value", "completion_submission_recorded", "other-evidence",
            {"completion": "finished"}, ["completion"], source_key="same-source",
        ))
        self.assertEqual(
            {claim["subject_id"] for claim in self.claims("completion")},
            {"work-evidence", "other-evidence"},
        )
        self.identity("forwarded-evidence")
        for index, revision in ((1, "absent"), (2, 1)):
            self.apply(self.event(
                f"e-forward-{index}", "completion_submission_recorded",
                "forwarded-evidence", {"completion": "finished"}, ["completion"],
                revisions={"completion": revision}, source="email_evidence",
                evidence=[{"evidence_id": f"transport-{index}", "provider": "gmail",
                           "account_id": "student", "record_id": "original-message",
                           "copy_id": f"copy-{index}"}],
            ))
        self.assertEqual(
            len([claim for claim in self.claims("completion")
                 if claim["subject_id"] == "forwarded-evidence"]),
            1,
        )

    def test_authority_matrix_ignores_client_confidence_and_stale_direct_evidence(self):
        self.identity("work-authority")
        user_submission = self.event(
            "e-user-submission", "completion_submission_recorded", "work-authority",
            {"submission": "submitted"}, ["submission"], certainty="confirmed",
        )
        self.apply(user_submission)
        self.assertEqual(self.claims("submission")[0]["claim_status"], "tentative")
        provider_submission = self.event(
            "e-provider-submission", "completion_submission_recorded", "work-authority",
            {"submission": "accepted"}, ["submission"], revisions={"submission": 1},
            source="provider_observation",
            evidence=[{"evidence_id": "lms-submission", "provider": "canvas",
                       "account_id": "student", "record_id": "submission-status"}],
        )
        self.apply(provider_submission)
        self.assertEqual(
            [claim["value"] for claim in self.claims("submission")
             if claim["claim_status"] == "active"],
            ["accepted"],
        )
        suggestion = self.event(
            "e-suggestion", "study_need_recorded", "work-authority",
            {"statement": "probably study"}, ["learning_need"],
            source="assistant_suggestion", certainty="confirmed",
        )
        self.apply(suggestion)
        assistant = self.claims("learning_need")[0]
        self.assertEqual((assistant["claim_status"], assistant["certainty"]),
                         ("tentative", "unknown"))
        self.apply(self.event(
            "e-waiver", "recurring_commitment_recorded", "work-authority",
            {"recurrence": "once", "requirement": "waived"},
            ["recurrence", "requirement"], source="document_evidence",
        ))
        self.assertEqual(
            [claim["value"] for claim in self.claims("requirement")
             if claim["claim_status"] == "active"],
            ["waived"],
        )

        newer = self.event(
            "e-new-deadline", "deadline_confirmed", "work-authority",
            {"deadline": {"value": "2026-10-02", "timezone": "America/Chicago",
                          "precision": "date", "kind": "official"}}, ["deadline"],
            source="provider_observation",
        )
        newer["observed_at"] = NOW
        self.apply(newer)
        stale = self.event(
            "e-stale-deadline", "deadline_corrected", "work-authority",
            {"replacement": {"value": "2026-10-01", "timezone": "America/Chicago",
                             "precision": "date", "kind": "official"}}, ["deadline"],
            revisions={"deadline": 1}, source="document_evidence",
            supersedes=["e-new-deadline"],
        )
        stale["observed_at"] = NOW - timedelta(days=1)
        result = self.apply(stale)
        self.assertEqual(result["state"], "needs_review")
        active = [claim for claim in self.claims("deadline") if claim["claim_status"] == "active"]
        tentative = [claim for claim in self.claims("deadline") if claim["claim_status"] == "tentative"]
        self.assertEqual(active[0]["value"]["value"], "2026-10-02")
        self.assertEqual(tentative[0]["value"]["value"], "2026-10-01")

    def test_coverage_honesty_is_account_scoped_and_reports_omitted_sources(self):
        cases = [
            ("healthy-unknown", "canvas", "account-a", "healthy", "unknown", "fresh", NOW, NOW),
            ("stale", "canvas", "account-b", "healthy", "complete", "stale", NOW, NOW),
            ("truncated", "gmail", "account-c", "healthy", "truncated", "fresh", NOW, NOW),
            ("pending", "outlook", "account-d", "pending", "unknown", "unknown", None, None),
        ]
        for coverage_id, provider, account, availability, completeness, freshness, assessed, observed in cases:
            self.service.record_coverage(
                self.scope, self.command("coverage-matrix"), coverage_id=coverage_id,
                provider=provider, account_id=account,
                declared_scope={"kind": "mailbox", "folder": "inbox"},
                availability=availability, completeness=completeness,
                freshness=freshness, assessed_at=assessed, observed_through=observed,
                bounds={"material_to_scope": True},
            )
        with self.assertRaises(CollegeDomainError) as no_account:
            self.service.record_coverage(
                self.scope, self.command("no-account"), coverage_id="no-account",
                provider="canvas", account_id="", declared_scope={"kind": "course"},
                availability="unknown", completeness="unknown", freshness="unknown",
            )
        self.assertEqual(no_account.exception.code, "invalid_payload")
        receipt = self.service.request_assessment(
            self.scope, self.command("coverage-assessment"),
            authorized_scope={
                "kind": "course", "subject_ids": [],
                "expected_coverage": [
                    {"provider": "canvas", "account_id": "account-a"},
                    {"provider": "blinn", "account_id": "blinn-student"},
                ],
            },
            horizon={"start": NOW.isoformat(), "end": (NOW + timedelta(days=1)).isoformat()},
            timezone_name="America/Chicago", valid_through=NOW + timedelta(hours=1),
        )
        self.assertEqual(receipt["state"], "applied")
        assessment = self.latest_assessment()
        omissions = {(item["provider"], item["account_id"], item["reason"])
                     for item in assessment["omissions"]}
        self.assertIn(("blinn", "blinn-student", "no_coverage_record"), omissions)
        self.assertIn(("canvas", "account-a", "healthy/unknown/fresh"), omissions)
        self.assertIn(("canvas", "account-b", "healthy/complete/stale"), omissions)
        self.assertEqual(
            {(item["provider"], item["account_id"]) for item in assessment["coverage"]},
            {("canvas", "account-a"), ("canvas", "account-b"),
             ("gmail", "account-c"), ("outlook", "account-d")},
        )
        other = CollegeScope("actor-a", "workspace-other")
        self.assertEqual(self.service.inspect_state(other)["coverage"], [])

    def test_attention_order_deduplication_temporal_precision_and_restart_determinism(self):
        for subject in (
            "overdue", "near", "preparation", "unknown-time", "learning",
            "coordination", "optional",
        ):
            self.identity(subject)
        for subject, due in (("overdue", "2026-09-22"), ("near", "2026-09-24")):
            self.apply(self.event(
                f"e-{subject}-requirement", "recurring_commitment_recorded", subject,
                {"recurrence": "once", "requirement": "required"},
                ["recurrence", "requirement"], source="document_evidence",
            ))
            self.apply(self.event(
                f"e-{subject}-deadline", "deadline_confirmed", subject,
                {"deadline": {"value": due, "timezone": "America/Chicago",
                              "precision": "date", "kind": "official"}},
                ["deadline"], source="document_evidence",
            ))
        self.apply(self.event(
            "e-unknown-deadline", "deadline_confirmed", "unknown-time",
            {"deadline": {"value": {"lower": None, "upper": None},
                          "timezone": "America/Chicago", "precision": "interval",
                          "kind": "reported"}},
            ["deadline"], source="document_evidence",
        ))
        self.apply(self.event(
            "e-learning-only", "study_need_recorded", "learning",
            {"statement": "practice limits"}, ["learning_need"],
        ))
        self.apply(self.event(
            "e-preparation-requirement", "recurring_commitment_recorded", "preparation",
            {"recurrence": "once", "requirement": "required"},
            ["recurrence", "requirement"], source="document_evidence",
        ))
        self.apply(self.event(
            "e-preparation-deadline", "deadline_confirmed", "preparation",
            {"deadline": {"value": "2026-09-24", "timezone": "America/Chicago",
                          "precision": "date", "kind": "official"}},
            ["deadline"], source="document_evidence",
        ))
        self.apply(self.event(
            "e-preparation-learning", "study_need_recorded", "preparation",
            {"statement": "practice before required work"}, ["learning_need"],
        ))
        session_payload = {
            "payload_kind": "session_observation", "session_id": "coord-session",
            "session_date": "2026-09-23", "timezone": "America/Chicago",
            "date_precision": "date", "entries": [{
                "observation_id": "blocker", "kind": "coordination_blocker",
                "value": "team unavailable", "asserted_at": NOW.isoformat(),
            }],
        }
        self.apply(self.event(
            "e-coordination", "course_progress_recorded", "coordination",
            session_payload, ["session:coord-session:blocker:coordination_blocker"],
        ))
        self.apply(self.event(
            "e-optional", "opportunity_recorded", "optional",
            {"title": "bonus", "requirement": "optional"},
            ["opportunity", "requirement"], source="document_evidence",
        ))
        subjects = [
            "overdue", "near", "preparation", "unknown-time", "learning",
            "coordination", "optional",
        ]
        self.assess(subjects=subjects)
        first = self.latest_assessment()
        order = [item["subject_id"] for item in first["items"]]
        self.assertEqual(
            order,
            ["overdue", "near", "preparation", "unknown-time", "coordination",
             "learning", "optional"],
        )
        self.assertEqual(len(order), len(set(order)))
        self.assertEqual(first["items"][0]["category"], "current_conflicts_blockers")
        self.assertEqual(first["items"][1]["category"], "required_obligations")
        self.assertEqual(first["items"][3]["category"], "material_unknowns")
        preparation = next(item for item in first["items"] if item["subject_id"] == "preparation")
        self.assertIn("preparation_pressure", preparation["categories"])
        self.assertFalse(any(
            key in item for item in first["items"]
            for key in ("duration", "capacity", "travel", "exact_start_time")
        ))
        restarted = CollegeDomainService(clock=lambda: NOW)
        self.assess(service=restarted, subjects=subjects, command=self.command("restart-order"))
        second = self.latest_assessment(service=restarted)
        comparable = lambda items: [
            {key: value for key, value in item.items() if key != "evidence_refs"}
            for item in items
        ]
        self.assertEqual(comparable(first["items"]), comparable(second["items"]))

    def test_all_internal_reads_leave_database_bytes_and_assessment_state_unchanged(self):
        self.identity("work-read-only")
        self.assess(subjects=["work-read-only"])
        command_id = self.service.inspect_state(self.scope)["assessments"][-1]["receipt_id"]
        before = Path(self.db_path).read_bytes()
        before_state = self.service.inspect_state(self.scope)
        self.service.get_receipt(self.scope, command_id="missing")
        self.service.inspect_state(self.scope)
        CollegeDomainService(clock=lambda: NOW).inspect_state(self.scope)
        after_state = self.service.inspect_state(self.scope)
        after = Path(self.db_path).read_bytes()
        self.assertEqual(before_state, after_state)
        self.assertEqual(before, after)
        self.assertIsNotNone(command_id)

    def test_content_fingerprints_are_keyed_and_restart_stable(self):
        payload = {
            "canonical_id": "keyed-subject", "identity_kind": "work_item",
            "identity_status": "resolved", "attributes": {"label": "LOW-ENTROPY"},
            "parent_ids": [], "stable_provider_ref": None,
            "reviewed_composite": {"section": "section-calc", "code": "keyed-subject"},
            "supersedes_ids": [],
        }
        command = self.command("keyed")
        receipt = self.service.create_identity(
            self.scope, command, canonical_id="keyed-subject", identity_kind="work_item",
            identity_status="resolved", attributes={"label": "LOW-ENTROPY"},
            reviewed_composite={"section": "section-calc", "code": "keyed-subject"},
        )
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        plain = hashlib.sha256(canonical.encode()).hexdigest()
        with database_connection() as connection:
            key = bytes(connection.execute(
                "SELECT value FROM college_store_metadata WHERE key='hmac_key'"
            ).fetchone()[0])
        self.assertNotEqual(receipt["payload_hash"], plain)
        self.assertEqual(
            receipt["payload_hash"], hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()
        )
        replay = CollegeDomainService(clock=lambda: NOW).create_identity(
            self.scope, command, canonical_id="keyed-subject", identity_kind="work_item",
            identity_status="resolved", attributes={"label": "LOW-ENTROPY"},
            reviewed_composite={"section": "section-calc", "code": "keyed-subject"},
        )
        self.assertEqual(replay["receipt_id"], receipt["receipt_id"])
        self.assertTrue(replay["duplicate"])


if __name__ == "__main__":
    unittest.main()
