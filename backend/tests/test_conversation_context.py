from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conversation_context import (  # noqa: E402
    CommandIdentity,
    ContextScope,
    ContextStoreError,
    SharedConversationContextService,
)
from app.storage import database_connection  # noqa: E402


NOW = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)


class SharedConversationContextTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "context.sqlite3")
        self.env = patch.dict(os.environ, {"APP_DB_PATH": self.db_path})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.now = NOW
        self.scope = ContextScope("actor-a", "workspace-a")
        self.authorized_pending_actions = {
            ("actor-a", "workspace-a", "pending-action-123", "conversation-a")
        }
        SharedConversationContextService.initialize_schema()
        self.service = self.make_service()
        self.counter = 0

    def make_service(self, **kwargs):
        return SharedConversationContextService(
            clock=lambda: self.now,
            pending_action_authorizer=lambda scope, action_id, conversation_id: (
                scope.actor_id, scope.workspace_id, action_id, conversation_id
            ) in self.authorized_pending_actions,
            **kwargs,
        )

    def command(self, prefix="command"):
        self.counter += 1
        return CommandIdentity(f"{prefix}-{self.counter}", f"key-{prefix}-{self.counter}")

    def grant(self, *, version="1", sensitive=False):
        return self.service.grant_capture_consent(
            self.scope,
            self.command("grant"),
            capture_scope="college-operational",
            scope_version=version,
            retain_sensitive=sensitive,
        )

    def capture(
        self,
        item_id="context-1",
        *,
        service=None,
        command=None,
        version="1",
        content=None,
        raw_content="I finished the lab.",
        attestation=None,
        sensitive=False,
        requires_raw_context=False,
        context_kind="operational_attestation",
        conversation_id="conversation-a",
        expires_at=None,
        expiry_basis=None,
        resolution_state=None,
        dependencies=(),
    ):
        return (service or self.service).capture_context(
            self.scope,
            command or self.command("capture"),
            item_id=item_id,
            capture_scope="college-operational",
            scope_version=version,
            context_kind=context_kind,
            content=content or {"field": "completion", "value": "finished"},
            source_identity="conversation-a/message-1",
            source_authority="user_confirmed",
            asserted_at=self.now,
            conversation_id=conversation_id,
            raw_content=raw_content,
            sensitive=sensitive,
            requires_raw_context=requires_raw_context,
            certainty="confirmed",
            attestation=attestation or {
                "subject_ref": "future-section/work-1",
                "field": "completion",
                "normalized_value": "finished",
                "source_verified": True,
            },
            expires_at=expires_at,
            expiry_basis=expiry_basis,
            resolution_state=resolution_state,
            dependencies=dependencies,
        )

    def test_capture_requires_exact_active_opt_in_and_revocation_stops_later_capture(self):
        with self.assertRaisesRegex(ContextStoreError, "Exact-scope") as denied:
            self.capture()
        self.assertEqual(denied.exception.code, "capture_not_authorized")

        granted = self.grant()
        self.assertEqual(granted["state"], "applied")
        consent = self.service.inspect_consents(self.scope)[0]
        self.assertEqual(consent["scope_version"], "1")
        self.assertTrue(consent["capture_enabled"])
        self.capture()

        self.service.revoke_capture_consent(
            self.scope,
            self.command("revoke"),
            capture_scope="college-operational",
            scope_version="1",
            expected_revision=1,
        )
        consent = self.service.inspect_consents(self.scope)[0]
        self.assertFalse(consent["capture_enabled"])
        self.assertEqual(consent["revision"], 2)
        with self.assertRaises(ContextStoreError) as denied:
            self.capture("context-2")
        self.assertEqual(denied.exception.code, "capture_not_authorized")
        self.assertIsNotNone(self.service.inspect_item(self.scope, "context-1"))

        self.grant(version="2")
        self.capture("context-2", version="2")
        versions = {item["scope_version"] for item in self.service.inspect_consents(self.scope)}
        self.assertEqual(versions, {"1", "2"})

    def test_sensitive_narrative_has_separate_retention_consent(self):
        self.grant(sensitive=False)
        self.capture("sensitive-1", sensitive=True, raw_content="private health narrative")
        minimized = self.service.inspect_item(self.scope, "sensitive-1")
        self.assertIsNone(minimized["content"])
        self.assertFalse(minimized["raw_source_available"])
        self.assertEqual(minimized["attestation"]["normalized_value"], "finished")
        with self.assertRaises(ContextStoreError) as denied:
            self.capture(
                "sensitive-narrative", sensitive=True, raw_content="private health narrative",
                context_kind="narrative", attestation=None,
            )
        self.assertEqual(denied.exception.code, "sensitive_attestation_required")
        with self.assertRaises(ContextStoreError) as nonminimal:
            self.capture(
                "sensitive-extra", sensitive=True,
                attestation={
                    "subject_ref": "future-section/work-1", "field": "completion",
                    "normalized_value": "finished", "source_verified": True,
                    "narrative": "private health narrative",
                },
            )
        self.assertEqual(nonminimal.exception.code, "sensitive_attestation_not_minimal")

        self.service.revoke_capture_consent(
            self.scope, self.command("revoke"), capture_scope="college-operational",
            scope_version="1", expected_revision=1,
        )
        self.service.grant_capture_consent(
            self.scope, self.command("grant-sensitive"),
            capture_scope="college-operational", scope_version="1",
            retain_sensitive=True,
        )
        self.capture("sensitive-2", sensitive=True, raw_content="private health narrative")
        retained = self.service.inspect_item(self.scope, "sensitive-2")
        self.assertTrue(retained["sensitive"])
        self.assertTrue(retained["raw_source_available"])

    def test_restart_persists_conversation_state_pending_action_and_cross_conversation_context(self):
        self.grant()
        self.capture("shared-preference", context_kind="preference", conversation_id=None)
        saved = self.service.save_conversation_state(
            self.scope,
            self.command("state"),
            conversation_id="conversation-a",
            state={"awaiting": "action_confirmation", "last_question": "Proceed?"},
            expected_revision=None,
            pending_action_id="pending-action-123",
        )
        self.assertEqual(saved["target_revisions"]["conversation-a"], 1)

        restarted = self.make_service()
        state = restarted.get_conversation_state(self.scope, "conversation-a")
        self.assertEqual(state["pending_action_id"], "pending-action-123")
        self.assertEqual(state["state"]["awaiting"], "action_confirmation")
        cross_conversation = restarted.retrieve_context(
            self.scope, conversation_id="conversation-b"
        )
        self.assertEqual([item["item_id"] for item in cross_conversation], ["shared-preference"])

    def test_actor_and_workspace_isolation_applies_to_all_read_surfaces(self):
        self.grant()
        self.capture()
        self.service.set_question_disposition(
            self.scope, self.command("question"), question_id="question-1",
            prompt_key="which-section", disposition="deferred",
            expected_revision=None, conversation_id="conversation-a",
        )
        self.service.advance_baseline(
            self.scope, self.command("baseline"), baseline_id="baseline-1",
            consumer="chat", cursor={"position": 3}, expected_revision=None,
        )
        other_actor = ContextScope("actor-b", "workspace-a")
        other_workspace = ContextScope("actor-a", "workspace-b")
        for other in (other_actor, other_workspace):
            self.assertEqual(self.service.retrieve_context(other), [])
            self.assertEqual(self.service.list_questions(other), [])
            self.assertIsNone(self.service.get_baseline(other, "baseline-1"))
            self.assertIsNone(self.service.inspect_item(other, "context-1"))
            self.assertEqual(
                self.service.get_receipt(other, command_id="capture-2")["state"],
                "not_found",
            )

    def test_question_dispositions_survive_across_conversations(self):
        asked = self.service.set_question_disposition(
            self.scope, self.command("question"), question_id="question-1",
            prompt_key="which-section", disposition="asked", expected_revision=None,
            conversation_id="conversation-a",
        )
        answered = self.service.set_question_disposition(
            self.scope, self.command("question"), question_id="question-1",
            prompt_key="which-section", disposition="answered",
            expected_revision=asked["target_revisions"]["question-1"],
            answer_summary="future-section-1",
            conversation_id="conversation-b",
        )
        self.service.set_question_disposition(
            self.scope, self.command("question"), question_id="question-1",
            prompt_key="which-section", disposition="deferred",
            expected_revision=answered["target_revisions"]["question-1"],
            answer_summary="future-section-1", conversation_id="conversation-c",
        )
        restarted = self.make_service()
        question = restarted.list_questions(self.scope)[0]
        self.assertEqual(question["disposition"], "deferred")
        self.assertEqual(question["conversation_id"], "conversation-c")
        self.assertEqual(question["answer_summary"], "future-section-1")
        self.assertEqual(question["revision"], 3)

    def test_course_bindings_require_review_and_not_a_title_hint(self):
        with self.assertRaises(ContextStoreError) as untrusted:
            self.service.create_course_binding(
                self.scope, self.command("binding"), binding_id="binding-1",
                term_id="future-term-1", section_id="future-section-1",
                binding_scope="conversation", review_provenance="review-1",
                reviewed_at=self.now, valid_from=self.now,
                valid_until=self.now + timedelta(days=1),
                conversation_id="Calculus chat",
            )
        self.assertEqual(untrusted.exception.code, "untrusted_surface_binding")

        self.service.create_course_binding(
            self.scope, self.command("binding"), binding_id="binding-1",
            term_id="future-term-1", section_id="future-section-1",
            binding_scope="conversation", review_provenance="review-1",
            reviewed_at=self.now, valid_from=self.now,
            valid_until=self.now + timedelta(hours=1),
            conversation_id="conversation-a", explicitly_selected=True,
        )
        self.assertTrue(self.service.get_course_binding(self.scope, "binding-1")["valid"])
        self.assertFalse(
            self.service.get_course_binding(
                self.scope, "binding-1", at=self.now + timedelta(hours=2)
            )["valid"]
        )
        self.service.revoke_course_binding(
            self.scope, self.command("binding-revoke"), binding_id="binding-1",
            expected_revision=1,
        )
        self.assertFalse(self.service.get_course_binding(self.scope, "binding-1")["valid"])

    def test_course_binding_is_ambiguous_when_multiple_explicit_bindings_exist(self):
        for index in (1, 2):
            self.service.create_course_binding(
                self.scope, self.command("binding"), binding_id=f"binding-{index}",
                term_id="future-term-1", section_id=f"future-section-{index}",
                binding_scope="selected", review_provenance=f"review-{index}",
                reviewed_at=self.now, valid_from=self.now, valid_until=None,
                explicitly_selected=True,
            )
        with database_connection() as connection:
            count = connection.execute(
                """SELECT count(*) AS count FROM course_context_bindings
                   WHERE actor_id=? AND workspace_id=? AND revoked_at IS NULL""",
                (self.scope.actor_id, self.scope.workspace_id),
            ).fetchone()["count"]
        self.assertEqual(count, 2)
        self.assertIsNone(self.service.get_course_binding(self.scope, "chat-title-calc"))

    def test_interaction_reads_never_advance_baseline(self):
        created = self.service.advance_baseline(
            self.scope, self.command("baseline"), baseline_id="baseline-1",
            consumer="chat", cursor={"position": 2}, expected_revision=None,
        )
        before = self.service.get_baseline(self.scope, "baseline-1")
        for _ in range(3):
            self.service.retrieve_context(self.scope)
            self.service.get_receipt(self.scope, command_id=created["command_id"])
            self.service.get_baseline(self.scope, "baseline-1")
        after = self.service.get_baseline(self.scope, "baseline-1")
        self.assertEqual(before, after)

        advanced = self.service.advance_baseline(
            self.scope, self.command("baseline"), baseline_id="baseline-1",
            consumer="chat", cursor={"position": 5}, expected_revision=1,
        )
        self.assertEqual(advanced["target_revisions"]["baseline-1"], 2)

    def test_assessment_generation_fences_every_relevant_context_lifecycle_atomically(self):
        self.assertEqual(self.service.get_assessment_generation(self.scope), 0)
        self.grant()
        self.assertEqual(self.service.get_assessment_generation(self.scope), 0)
        capture_command = self.command("capture-generation")
        self.capture("generation-claim", command=capture_command)
        self.assertEqual(self.service.get_assessment_generation(self.scope), 1)
        self.capture("generation-claim", command=capture_command)
        self.assertEqual(self.service.get_assessment_generation(self.scope), 1)
        self.service.correct_context(
            self.scope, self.command("correct-generation"), item_id="generation-claim",
            expected_revision=1, content={"field": "completion", "value": "in_progress"},
            reason="correction",
        )
        self.service.undo_context_correction(
            self.scope, self.command("undo-generation"), item_id="generation-claim",
            expected_revision=2, correction_revision=2, reason="undo",
        )
        self.service.remove_raw_evidence(
            self.scope, self.command("remove-generation"), item_id="generation-claim",
            expected_revision=3,
        )
        self.capture(
            "situational-generation", context_kind="situational",
            resolution_state="unresolved", expires_at=self.now + timedelta(hours=2),
            expiry_basis="explicit",
        )
        self.service.resolve_situational_context(
            self.scope, self.command("resolve-generation"),
            item_id="situational-generation", expected_revision=1,
            resolution_state="resolved",
        )
        self.capture(
            "expiry-generation", requires_raw_context=True,
            expires_at=self.now + timedelta(days=1), expiry_basis="explicit",
        )
        self.now += timedelta(days=8)
        self.service.expire_raw_evidence(
            self.scope, self.command("expiry-generation"), through=self.now,
        )
        self.service.forget_context(
            self.scope, self.command("forget-generation"), item_id="generation-claim",
            expected_revision=4,
        )
        self.service.create_course_binding(
            self.scope, self.command("binding-generation"), binding_id="binding-generation",
            term_id="term", section_id="section", binding_scope="selected",
            review_provenance="review", reviewed_at=self.now, valid_from=self.now,
            valid_until=None, explicitly_selected=True,
        )
        self.service.revoke_course_binding(
            self.scope, self.command("revoke-generation"),
            binding_id="binding-generation", expected_revision=1,
        )
        self.service.advance_baseline(
            self.scope, self.command("baseline-generation"), baseline_id="baseline-generation",
            consumer="college", cursor={"position": 1}, expected_revision=None,
        )
        self.assertEqual(self.service.get_assessment_generation(self.scope), 12)
        before = self.service.get_assessment_generation(self.scope)
        self.service.retrieve_context(self.scope)
        self.service.get_baseline(self.scope, "baseline-generation")
        self.assertEqual(self.service.get_assessment_generation(self.scope), before)

        failing = self.make_service(
            failure_injector=lambda point: (_ for _ in ()).throw(RuntimeError("injected"))
            if point == "after_domain_mutation" else None,
        )
        with self.assertRaises(RuntimeError):
            failing.advance_baseline(
                self.scope, self.command("failed-generation"), baseline_id="failed-generation",
                consumer="college", cursor={"position": 2}, expected_revision=None,
            )
        self.assertEqual(self.service.get_assessment_generation(self.scope), before)

    def test_clear_attested_claim_survives_seven_day_raw_expiry(self):
        self.grant()
        self.capture("clear-claim", requires_raw_context=False)
        self.now += timedelta(days=8)
        receipt = self.service.expire_raw_evidence(
            self.scope, self.command("expiry"), through=self.now
        )
        self.assertEqual(receipt["state"], "applied")
        item = self.service.inspect_item(self.scope, "clear-claim")
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["certainty"], "confirmed")
        self.assertFalse(item["raw_source_available"])
        self.assertEqual(item["attestation"]["normalized_value"], "finished")

    def test_ambiguous_interpretation_loses_confidence_when_raw_support_expires(self):
        self.grant()
        self.capture(
            "ambiguous", requires_raw_context=True, context_kind="summary",
            content={"interpretation": "probably needs review"},
        )
        self.now += timedelta(days=8)
        receipt = self.service.expire_raw_evidence(
            self.scope, self.command("expiry"), through=self.now
        )
        self.assertEqual(receipt["state"], "needs_review")
        item = self.service.inspect_item(self.scope, "ambiguous")
        self.assertEqual(item["status"], "needs_review")
        self.assertEqual(item["certainty"], "unknown")

    def test_raw_only_removal_does_not_forget_derived_fact(self):
        self.grant()
        self.capture("claim")
        removed = self.service.remove_raw_evidence(
            self.scope, self.command("raw-remove"), item_id="claim",
            expected_revision=1,
        )
        self.assertEqual(removed["state"], "applied")
        item = self.service.inspect_item(self.scope, "claim")
        self.assertEqual(item["status"], "active")
        self.assertIsNotNone(item["content"])
        self.assertFalse(item["raw_source_available"])

        self.service.forget_context(
            self.scope, self.command("forget"), item_id="claim", expected_revision=2,
        )
        forgotten = self.service.inspect_item(self.scope, "claim")
        self.assertEqual(forgotten["status"], "forgotten")
        self.assertIsNone(forgotten["content"])
        self.assertIsNone(forgotten["attestation"])

    def test_correction_undo_and_optimistic_revision_conflicts(self):
        self.grant()
        self.capture("claim")
        corrected = self.service.correct_context(
            self.scope, self.command("correct"), item_id="claim", expected_revision=1,
            content={"field": "completion", "value": "in_progress"},
            reason="misheard",
        )
        self.assertEqual(corrected["target_revisions"]["claim"], 2)
        with self.assertRaises(ContextStoreError) as stale:
            self.service.correct_context(
                self.scope, self.command("stale"), item_id="claim", expected_revision=1,
                content={"field": "completion", "value": "finished"}, reason="stale",
            )
        self.assertEqual(stale.exception.code, "revision_conflict")
        undone = self.service.undo_context_correction(
            self.scope, self.command("undo"), item_id="claim", expected_revision=2,
            correction_revision=2, reason="restore original",
        )
        self.assertEqual(undone["target_revisions"]["claim"], 3)
        self.assertEqual(
            self.service.inspect_item(self.scope, "claim")["content"]["value"],
            "finished",
        )

    def test_concurrent_same_target_corrections_never_silently_overwrite(self):
        self.grant()
        self.capture("claim")
        identities = (
            CommandIdentity("concurrent-a", "concurrent-key-a"),
            CommandIdentity("concurrent-b", "concurrent-key-b"),
        )

        def correct(index):
            try:
                receipt = self.service.correct_context(
                    self.scope, identities[index], item_id="claim", expected_revision=1,
                    content={"field": "completion", "value": f"candidate-{index}"},
                    reason=f"concurrent-{index}",
                )
                return receipt["state"]
            except ContextStoreError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(correct, (0, 1)))
        self.assertEqual(sorted(outcomes), ["applied", "revision_conflict"])
        item = self.service.inspect_item(self.scope, "claim")
        self.assertEqual(item["revision"], 2)
        self.assertIn(item["content"]["value"], {"candidate-0", "candidate-1"})

    def test_forgetting_propagates_to_unsupported_dependents_and_caches(self):
        self.grant()
        self.capture("source-a")
        self.capture(
            "summary", context_kind="summary", content={"summary": "derived"},
            dependencies=("source-a",),
        )
        self.service.put_cache(
            self.scope, self.command("cache"), cache_key="brief",
            content={"text": "derived"}, source_item_ids=("source-a", "summary"),
        )
        self.assertIsNotNone(self.service.get_cache(self.scope, "brief"))
        result = self.service.forget_context(
            self.scope, self.command("forget"), item_id="source-a", expected_revision=1,
        )
        self.assertEqual(set(result["target_ids"]), {"source-a", "summary"})
        self.assertEqual(self.service.inspect_item(self.scope, "summary")["status"], "forgotten")
        self.assertIsNone(self.service.get_cache(self.scope, "brief"))
        with database_connection() as connection:
            tombstones = connection.execute(
                """SELECT target_id, lifecycle_marker, dependency_ids_json
                   FROM context_tombstones ORDER BY target_id"""
            ).fetchall()
        self.assertEqual({row["target_id"] for row in tombstones}, {"source-a", "summary"})
        self.assertNotIn("derived", "".join(row["dependency_ids_json"] for row in tombstones))

    def test_independently_supported_context_survives_forgetting(self):
        self.grant()
        self.capture("source-a")
        self.capture("source-b")
        self.capture(
            "summary", context_kind="summary", content={"summary": "supported"},
            dependencies=("source-a", "source-b"),
        )
        self.service.forget_context(
            self.scope, self.command("forget"), item_id="source-a", expected_revision=1,
        )
        summary = self.service.inspect_item(self.scope, "summary")
        self.assertEqual(summary["status"], "active")
        self.assertEqual(summary["content"]["summary"], "supported")

    def test_independently_supported_context_survives_source_correction(self):
        self.grant()
        self.capture("source-a")
        self.capture("source-b")
        self.capture(
            "summary", context_kind="summary", content={"summary": "supported"},
            dependencies=("source-a", "source-b"),
        )
        self.service.correct_context(
            self.scope, self.command("correct"), item_id="source-a", expected_revision=1,
            content={"field": "completion", "value": "in_progress"},
            reason="correction",
        )
        summary = self.service.inspect_item(self.scope, "summary")
        self.assertEqual(summary["status"], "active")
        self.assertEqual(summary["revision"], 1)

    def test_forgotten_content_cannot_resurrect_via_retry_or_reseed(self):
        self.grant()
        capture_command = self.command("capture")
        first = self.capture("claim", command=capture_command)
        self.service.forget_context(
            self.scope, self.command("forget"), item_id="claim", expected_revision=1,
        )
        retry = self.capture("claim", command=capture_command)
        self.assertEqual(retry["receipt_id"], first["receipt_id"])
        self.assertEqual(retry["delivery_disposition"], "duplicate")
        self.assertEqual(self.service.inspect_item(self.scope, "claim")["status"], "forgotten")
        with self.assertRaises(ContextStoreError) as reseed:
            self.capture("claim", command=self.command("new-seed"))
        self.assertEqual(reseed.exception.code, "forgotten_target")

    def test_forgetting_scrubs_plaintext_from_logical_store_and_sqlite_file(self):
        self.grant()
        marker = "UNIQUE-FORGOTTEN-NARRATIVE-7F3A91"
        self.capture(
            "private-claim",
            content={"narrative": marker},
            raw_content=marker,
            attestation={"normalized_value": marker},
        )
        self.service.forget_context(
            self.scope, self.command("forget"), item_id="private-claim",
            expected_revision=1,
        )
        with database_connection() as connection:
            rows = connection.execute(
                """SELECT content_json, attestation_json FROM shared_context_revisions
                   WHERE item_id='private-claim'"""
            ).fetchall()
            raw = connection.execute(
                """SELECT content FROM raw_conversation_evidence
                   WHERE removal_reason='forgotten'"""
            ).fetchone()
        self.assertTrue(all(row["content_json"] is None for row in rows))
        self.assertTrue(all(row["attestation_json"] is None for row in rows))
        self.assertIsNone(raw["content"])
        self.assertNotIn(marker.encode(), Path(self.db_path).read_bytes())

    def test_transient_expiry_does_not_become_resolution(self):
        self.grant()
        self.capture(
            "limitation", context_kind="situational",
            content={"limitation": "printer unavailable"},
            expires_at=self.now + timedelta(hours=1),
            expiry_basis="stated current study session",
            resolution_state="unresolved",
        )
        self.assertEqual(len(self.service.retrieve_context(self.scope)), 1)
        self.now += timedelta(hours=2)
        self.assertEqual(self.service.retrieve_context(self.scope), [])
        historical = self.service.retrieve_context(self.scope, include_historical=True)[0]
        self.assertFalse(historical["within_validity"])
        self.assertEqual(historical["resolution_state"], "unresolved")
        self.assertEqual(historical["status"], "active")

    def test_duplicate_retry_changed_payload_conflict_and_restart_status_readback(self):
        self.grant()
        command = self.command("capture")
        first = self.capture("claim", command=command)
        retry = self.capture("claim", command=command)
        self.assertEqual(retry["receipt_id"], first["receipt_id"])
        self.assertEqual(retry["delivery_disposition"], "duplicate")
        with self.assertRaises(ContextStoreError) as changed:
            self.capture(
                "claim", command=command,
                content={"field": "completion", "value": "not_started"},
            )
        self.assertEqual(changed.exception.code, "idempotency_payload_conflict")
        self.assertEqual(self.service.inspect_item(self.scope, "claim")["content"]["value"], "finished")

        restarted = self.make_service()
        status = restarted.get_receipt(self.scope, command_id=command.command_id)
        self.assertEqual(status["receipt_id"], first["receipt_id"])
        self.assertEqual(
            restarted.get_receipt(self.scope, command_id="timed-out-not-accepted")["state"],
            "not_found",
        )

    def test_crossed_command_and_idempotency_identities_reject_without_change(self):
        self.grant()
        first_identity = CommandIdentity("capture-a", "capture-key-a")
        second_identity = CommandIdentity("capture-b", "capture-key-b")
        self.capture("claim-a", command=first_identity)
        self.capture("claim-b", command=second_identity)
        crossed = CommandIdentity(first_identity.command_id, second_identity.idempotency_key)
        with self.assertRaises(ContextStoreError) as conflict:
            self.capture("claim-c", command=crossed)
        self.assertEqual(conflict.exception.code, "command_identity_conflict")
        self.assertIsNone(self.service.inspect_item(self.scope, "claim-c"))

    def test_bounded_retrieval_rejects_unbounded_requests(self):
        with self.assertRaises(ContextStoreError) as invalid:
            self.service.retrieve_context(self.scope, limit=101)
        self.assertEqual(invalid.exception.code, "invalid_limit")

    def test_schema_initialization_is_explicit_and_reads_do_not_create_sid151_tables(self):
        separate_path = os.path.join(self.tempdir.name, "explicit-init.sqlite3")
        with patch.dict(os.environ, {"APP_DB_PATH": separate_path}):
            with self.assertRaises(ContextStoreError) as uninitialized:
                self.make_service()
            self.assertEqual(uninitialized.exception.code, "context_schema_uninitialized")
            with closing(sqlite3.connect(separate_path)) as connection:
                context_table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_store_metadata'"
                ).fetchone()
            self.assertIsNone(context_table)
            SharedConversationContextService.initialize_schema()
            initialized = self.make_service()
            self.assertEqual(initialized.retrieve_context(self.scope), [])

    def test_fingerprint_key_survives_restart_and_missing_or_changed_key_fails_closed(self):
        self.grant()
        command = self.command("capture")
        first = self.capture("keyed", command=command)
        with database_connection() as connection:
            key_before = bytes(connection.execute(
                "SELECT value FROM context_store_metadata WHERE key='hmac_key'"
            ).fetchone()["value"])
            fingerprint = connection.execute(
                "SELECT payload_fingerprint FROM context_command_receipts WHERE receipt_id=?",
                (first["receipt_id"],),
            ).fetchone()["payload_fingerprint"]
            sample_payload = {"sensitive": "not-a-raw-digest"}
            keyed_sample = self.service._fingerprint(connection, sample_payload)
        self.assertEqual(len(key_before), 32)
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        raw_sample = hashlib.sha256(json.dumps(
            sample_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        self.assertNotEqual(keyed_sample, raw_sample)
        restarted = self.make_service()
        retry = self.capture("keyed", service=restarted, command=command)
        self.assertEqual(retry["receipt_id"], first["receipt_id"])
        with database_connection() as connection:
            key_after = bytes(connection.execute(
                "SELECT value FROM context_store_metadata WHERE key='hmac_key'"
            ).fetchone()["value"])
            connection.execute("DELETE FROM context_store_metadata WHERE key='hmac_key'")
        self.assertEqual(key_after, key_before)
        with self.assertRaises(ContextStoreError) as missing:
            SharedConversationContextService.initialize_schema()
        self.assertEqual(missing.exception.code, "fingerprint_key_unavailable")
        with database_connection() as connection:
            self.assertIsNone(connection.execute(
                "SELECT value FROM context_store_metadata WHERE key='hmac_key'"
            ).fetchone())

    def test_changed_fingerprint_key_is_detected_before_commands_or_reads(self):
        self.grant()
        with database_connection() as connection:
            connection.execute(
                "UPDATE context_store_metadata SET value=? WHERE key='hmac_key'",
                (os.urandom(32),),
            )
        with self.assertRaises(ContextStoreError) as changed:
            self.make_service()
        self.assertEqual(changed.exception.code, "fingerprint_key_mismatch")

    def test_existing_pre_verifier_store_migrates_without_changing_key_or_replay(self):
        self.grant()
        identity = self.command("capture")
        first = self.capture("pre-verifier", command=identity)
        with database_connection() as connection:
            key_before = bytes(connection.execute(
                "SELECT value FROM context_store_metadata WHERE key='hmac_key'"
            ).fetchone()["value"])
            connection.execute(
                "DELETE FROM context_store_metadata WHERE key='hmac_key_check'"
            )
        SharedConversationContextService.initialize_schema()
        migrated = self.make_service()
        retry = self.capture("pre-verifier", service=migrated, command=identity)
        with database_connection() as connection:
            key_after = bytes(connection.execute(
                "SELECT value FROM context_store_metadata WHERE key='hmac_key'"
            ).fetchone()["value"])
            self.assertIsNotNone(connection.execute(
                "SELECT value FROM context_store_metadata WHERE key='hmac_key_check'"
            ).fetchone())
        self.assertEqual(key_after, key_before)
        self.assertEqual(retry["receipt_id"], first["receipt_id"])

    def test_expired_raw_content_is_unavailable_before_explicit_cleanup_and_reads_do_not_write(self):
        self.grant()
        marker = "EXPIRED-BUT-NOT-YET-CLEANED-RAW"
        self.capture("expired-raw", raw_content=marker)
        self.now += timedelta(days=8)
        before = self.service.inspect_item(self.scope, "expired-raw")
        listed = self.service.retrieve_context(self.scope)[0]
        self.assertFalse(before["raw_source_available"])
        self.assertFalse(listed["raw_source_available"])
        with database_connection() as connection:
            raw_before_cleanup = connection.execute(
                "SELECT content, removed_at FROM raw_conversation_evidence"
            ).fetchone()
        self.assertEqual(raw_before_cleanup["content"], marker)
        self.assertIsNone(raw_before_cleanup["removed_at"])
        receipt = self.service.expire_raw_evidence(
            self.scope, self.command("expiry"), through=self.now
        )
        self.assertEqual(receipt["state"], "applied")
        with database_connection() as connection:
            raw_after_cleanup = connection.execute(
                "SELECT content, removed_at FROM raw_conversation_evidence"
            ).fetchone()
        self.assertIsNone(raw_after_cleanup["content"])
        self.assertIsNotNone(raw_after_cleanup["removed_at"])

    def test_pending_action_reference_requires_trusted_actor_workspace_and_conversation_scope(self):
        untrusted = SharedConversationContextService(clock=lambda: self.now)
        with self.assertRaises(ContextStoreError) as absent_authorizer:
            untrusted.save_conversation_state(
                self.scope, self.command("state"), conversation_id="conversation-a",
                state={"awaiting": "approval"}, expected_revision=None,
                pending_action_id="pending-action-123",
            )
        self.assertEqual(absent_authorizer.exception.code, "pending_action_scope_unverified")
        wrong_workspace = ContextScope("actor-a", "workspace-b")
        with self.assertRaises(ContextStoreError) as cross_scope:
            self.service.save_conversation_state(
                wrong_workspace, self.command("state"), conversation_id="conversation-a",
                state={"awaiting": "approval"}, expected_revision=None,
                pending_action_id="pending-action-123",
            )
        self.assertEqual(cross_scope.exception.code, "pending_action_scope_unverified")
        self.assertIsNone(self.service.get_conversation_state(wrong_workspace, "conversation-a"))

    def test_failure_after_domain_mutation_rolls_back_rows_revisions_dependencies_and_receipt(self):
        self.grant()

        def fail(point):
            if point == "after_domain_mutation":
                raise RuntimeError("injected domain failure")

        failing = self.make_service(failure_injector=fail)
        identity = self.command("failure")
        with self.assertRaisesRegex(RuntimeError, "injected domain failure"):
            self.capture("failed-capture", service=failing, command=identity)
        self.assertIsNone(self.service.inspect_item(self.scope, "failed-capture"))
        self.assertEqual(
            self.service.get_receipt(self.scope, command_id=identity.command_id)["state"],
            "not_found",
        )
        with database_connection() as connection:
            counts = [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("raw_conversation_evidence", "shared_context_revisions",
                                    "context_dependencies")]
        self.assertEqual(counts, [0, 0, 0])

    def test_failure_after_receipt_insert_rolls_back_forgetting_tombstones_caches_and_receipt(self):
        self.grant()
        self.capture("source")
        self.capture(
            "dependent", context_kind="summary", content={"summary": "derived"},
            dependencies=("source",),
        )
        self.service.put_cache(
            self.scope, self.command("cache"), cache_key="brief",
            content={"summary": "derived"}, source_item_ids=("source", "dependent"),
        )

        def fail(point):
            if point == "after_receipt_insert":
                raise RuntimeError("injected receipt failure")

        failing = self.make_service(failure_injector=fail)
        identity = self.command("failure")
        with self.assertRaisesRegex(RuntimeError, "injected receipt failure"):
            failing.forget_context(
                self.scope, identity, item_id="source", expected_revision=1
            )
        self.assertEqual(self.service.inspect_item(self.scope, "source")["status"], "active")
        self.assertEqual(self.service.inspect_item(self.scope, "dependent")["status"], "active")
        self.assertIsNotNone(self.service.get_cache(self.scope, "brief"))
        self.assertEqual(
            self.service.get_receipt(self.scope, command_id=identity.command_id)["state"],
            "not_found",
        )
        with database_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM context_tombstones").fetchone()[0], 0
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM context_dependencies").fetchone()[0], 1
            )

    def test_two_connections_same_identity_apply_once_and_replay_exactly(self):
        self.grant()
        identity = CommandIdentity("same-command", "same-key")
        first_service = self.make_service()
        second_service = self.make_service()
        barrier = threading.Barrier(2)

        def apply(service):
            barrier.wait()
            return self.capture("same-item", service=service, command=identity)

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(apply, (first_service, second_service)))
        self.assertEqual({outcome["receipt_id"] for outcome in outcomes}, {outcomes[0]["receipt_id"]})
        self.assertEqual(
            sorted(outcome["delivery_disposition"] for outcome in outcomes),
            ["duplicate", "newly_applied"],
        )
        with database_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM context_command_receipts WHERE command_id='same-command'"
                ).fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM shared_context_items WHERE item_id='same-item'"
                ).fetchone()[0], 1
            )

    def test_two_connections_same_identity_changed_payload_conflicts_without_overwrite(self):
        self.grant()
        identity = CommandIdentity("racing-command", "racing-key")
        services = (self.make_service(), self.make_service())
        barrier = threading.Barrier(2)

        def apply(index):
            barrier.wait()
            try:
                receipt = self.capture(
                    "racing-item", service=services[index], command=identity,
                    content={"field": "completion", "value": f"candidate-{index}"},
                )
                return receipt["state"]
            except ContextStoreError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(apply, (0, 1)))
        self.assertEqual(sorted(outcomes), ["applied", "idempotency_payload_conflict"])
        stored = self.service.inspect_item(self.scope, "racing-item")
        self.assertIn(stored["content"]["value"], {"candidate-0", "candidate-1"})
        self.assertEqual(stored["revision"], 1)
        with database_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM context_command_receipts WHERE command_id='racing-command'"
                ).fetchone()[0], 1
            )

    def test_two_connections_allow_independent_target_revisions(self):
        self.grant()
        self.capture("disjoint-a")
        self.capture("disjoint-b")
        services = (self.make_service(), self.make_service())
        barrier = threading.Barrier(2)

        def correct(index):
            barrier.wait()
            return services[index].correct_context(
                self.scope, CommandIdentity(f"disjoint-{index}", f"disjoint-key-{index}"),
                item_id=f"disjoint-{'ab'[index]}", expected_revision=1,
                content={"field": "completion", "value": f"updated-{index}"},
                reason="independent concurrent correction",
            )["state"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(correct, (0, 1)))
        self.assertEqual(outcomes, ["applied", "applied"])
        self.assertEqual(self.service.inspect_item(self.scope, "disjoint-a")["revision"], 2)
        self.assertEqual(self.service.inspect_item(self.scope, "disjoint-b")["revision"], 2)

    def test_wal_database_is_migrated_to_delete_journal_and_forgetting_leaves_no_marker(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        SharedConversationContextService.initialize_schema()
        service = self.make_service()
        with database_connection() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(connection.execute("PRAGMA temp_store").fetchone()[0], 2)
            self.assertEqual(connection.execute("PRAGMA secure_delete").fetchone()[0], 1)
        marker = "WAL-JOURNAL-PRIVATE-MARKER-151"
        self.grant()
        self.capture(
            "journal-private", service=service, content={"narrative": marker},
            raw_content=marker, attestation={"normalized_value": marker},
        )
        service.forget_context(
            self.scope, self.command("forget"), item_id="journal-private", expected_revision=1,
        )
        for path in (
            Path(self.db_path), Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm"),
            Path(f"{self.db_path}-journal"),
        ):
            if path.exists():
                self.assertNotIn(marker.encode(), path.read_bytes(), str(path))

    def test_additive_migration_on_synthetic_legacy_database(self):
        legacy_path = os.path.join(self.tempdir.name, "legacy.sqlite3")
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute(
                "CREATE TABLE legacy_records(id TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute("INSERT INTO legacy_records VALUES ('legacy-1', 'preserved')")
            connection.commit()
        with patch.dict(os.environ, {"APP_DB_PATH": legacy_path}):
            SharedConversationContextService.initialize_schema()
            migrated = self.make_service()
            migrated.grant_capture_consent(
                self.scope, CommandIdentity("migration-1", "migration-key-1"),
                capture_scope="college-operational", scope_version="1",
            )
            with database_connection() as connection:
                legacy = connection.execute("SELECT * FROM legacy_records").fetchone()
                tables = {
                    row["name"] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
        self.assertEqual(legacy["value"], "preserved")
        self.assertIn("shared_context_items", tables)
        self.assertIn("context_command_receipts", tables)
        self.assertIn("pending_actions", tables)


if __name__ == "__main__":
    unittest.main()
