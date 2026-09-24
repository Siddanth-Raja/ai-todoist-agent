from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.college_capture import (  # noqa: E402
    CollegeAssessmentRequest,
    CollegeCaptureAdapter,
    CollegeCaptureError,
    CollegeCaptureRequest,
    CollegeQuestionDispositionRequest,
    TrustedCollegeCaptureContext,
)
from app.college_capture_api import (  # noqa: E402
    CollegeCaptureAuthenticator,
    _request,
    create_college_capture_app,
)
from app.college_domain import (  # noqa: E402
    CollegeCommandIdentity,
    CollegeDomainService,
    CollegeScope,
)
from app.college_reads import (  # noqa: E402
    CollegeReadService,
    CollegeStatusReadRequest,
    TrustedCollegeContext,
)
from app.conversation_context import (  # noqa: E402
    CommandIdentity,
    ContextScope,
    SharedConversationContextService,
)
from app.storage import database_connection  # noqa: E402


NOW = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)


class CollegeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "capture.sqlite3")
        self.environment = patch.dict(os.environ, {"APP_DB_PATH": self.db_path})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        SharedConversationContextService.initialize_schema()
        CollegeDomainService.initialize_schema()
        self.context = SharedConversationContextService(clock=lambda: NOW)
        self.domain = CollegeDomainService(clock=lambda: NOW)
        self.context_scope = ContextScope("actor-a", "workspace-a")
        self.college_scope = CollegeScope("actor-a", "workspace-a")
        self.counter = 0
        self._identity("course-calc", "course", ())
        self._identity("section-calc", "section", ("course-calc",))
        self._identity("topic-4-individual", "work_item", ("section-calc",))
        self._identity("topic-4-team", "work_item", ("section-calc",))
        self._grant()
        self._binding("binding-calc", "calc-chat")
        self.auth = TrustedCollegeCaptureContext(
            actor_id="actor-a",
            workspace_id="workspace-a",
            allowed_section_ids=frozenset({"section-calc"}),
            binding_ids_by_conversation={"calc-chat": ("binding-calc",)},
            reviewed_referents={
                "Topic 4 individual": "topic-4-individual",
                "team": "topic-4-team",
            },
        )
        self.adapter = CollegeCaptureAdapter(
            context_service=self.context,
            college_service=self.domain,
            clock=lambda: NOW,
        )

    def _command(self, prefix: str) -> CommandIdentity:
        self.counter += 1
        return CommandIdentity(f"{prefix}-{self.counter}", f"{prefix}-key-{self.counter}")

    def _college_command(self, prefix: str) -> CollegeCommandIdentity:
        self.counter += 1
        return CollegeCommandIdentity(f"{prefix}-{self.counter}", f"{prefix}-key-{self.counter}")

    def _identity(self, canonical_id: str, kind: str, parents: tuple[str, ...]) -> None:
        self.domain.create_identity(
            self.college_scope,
            self._college_command("identity"),
            canonical_id=canonical_id,
            identity_kind=kind,
            identity_status="resolved",
            attributes={"label": canonical_id},
            parent_ids=parents,
            reviewed_composite={"kind": kind, "code": canonical_id},
        )

    def _grant(self) -> None:
        self.context.grant_capture_consent(
            self.context_scope,
            self._command("consent"),
            capture_scope="college-operational",
            scope_version="1",
        )

    def _binding(self, binding_id: str, conversation_id: str, section_id: str = "section-calc") -> None:
        self.context.create_course_binding(
            self.context_scope,
            self._command("binding"),
            binding_id=binding_id,
            term_id="fall-2026",
            section_id=section_id,
            binding_scope="course",
            review_provenance="user-reviewed",
            reviewed_at=NOW - timedelta(days=1),
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=90),
            conversation_id=conversation_id,
            attested_surface_id=f"surface:{conversation_id}",
        )

    def _request(
        self,
        message: str,
        *,
        command: str = "capture-1",
        key: str = "capture-key-1",
        surface: str = "chatgpt",
        conversation: str = "calc-chat",
        binding_id: str | None = None,
    ) -> CollegeCaptureRequest:
        return CollegeCaptureRequest(
            command_id=command,
            idempotency_key=key,
            message=message,
            source_surface=surface,
            conversation_id=conversation,
            asserted_at=NOW,
            timezone_name="America/Chicago",
            binding_id=binding_id,
        )

    def _claims(self):
        return self.domain.inspect_state(self.college_scope)["claims"]

    def test_calc_walkthrough_applies_from_both_conversation_surfaces_without_inference(self):
        message = "Calc covered continuity today; there was a quick check and an exam warning."
        for index, surface in enumerate(("chatgpt", "app"), start=1):
            receipt = self.adapter.record_college_update(
                self.auth,
                self._request(message, command=f"calc-{index}", key=f"calc-key-{index}", surface=surface),
            )
            self.assertEqual(receipt["outcome"], "applied")
            self.assertIsNotNone(receipt["receipt_id"])
            self.assertEqual(receipt["status_lookup"]["command_id"], f"calc-{index}")
            self.assertEqual(receipt["provider_actions"], [])
        fields = {claim["field"] for claim in self._claims()}
        self.assertEqual(len([field for field in fields if field.endswith(":topic_covered")]), 2)
        self.assertEqual(len([field for field in fields if field.endswith(":assessment_observed")]), 2)
        self.assertEqual(len([field for field in fields if field.endswith(":announcement_reported")]), 2)
        self.assertFalse({"attendance", "grade", "deadline", "understanding"} & fields)

    def test_engr_mixed_statement_keeps_individual_and_team_state_distinct(self):
        receipt = self.adapter.record_college_update(
            self.auth,
            self._request(
                "Topic 4 individual is submitted but needs work; team started, no group chat.",
                command="engr-mixed",
                key="engr-mixed-key",
            ),
        )
        self.assertEqual(receipt["outcome"], "saved_for_review")
        self.assertIsNotNone(receipt["receipt_id"])
        self.assertEqual(receipt["status_lookup"]["command_id"], "engr-mixed")
        claims = self._claims()
        individual = {
            item["field"]: item["value"] for item in claims
            if item["subject_id"] == "topic-4-individual"
        }
        team = {
            item["field"]: item["value"] for item in claims
            if item["subject_id"] == "topic-4-team"
        }
        self.assertEqual(individual["submission"], "submitted")
        self.assertEqual(team["completion"], "in_progress")
        self.assertNotEqual(individual.get("completion"), "finished")
        self.assertNotEqual(team.get("completion"), "finished")
        self.assertTrue(any(item["field"].endswith(":coordination_blocker") for item in claims))

    def test_derivatives_walkthrough_records_topic_and_distinct_learning_need(self):
        result = self.adapter.record_college_update(
            self.auth,
            self._request(
                "We covered derivatives; I'm lost on definition problems.",
                command="derivatives",
                key="derivatives-key",
            ),
        )
        self.assertEqual(result["outcome"], "applied")
        fields = {claim["field"] for claim in self._claims()}
        self.assertIn("learning_need", fields)
        self.assertNotIn("submission", fields)
        self.assertNotIn("completion", fields)

    def test_same_delivery_returns_original_receipt_and_changed_payload_conflicts(self):
        original = self._request(
            "Calc covered continuity today; there was a quick check and an exam warning.",
            command="duplicate",
            key="duplicate-key",
        )
        first = self.adapter.record_college_update(self.auth, original)
        duplicate = self.adapter.record_college_update(self.auth, original)
        self.assertEqual(duplicate["receipt_id"], first["receipt_id"])
        self.assertEqual(duplicate["delivery_disposition"], "duplicate")
        before = len(self._claims())
        changed = self._request(
            "We covered derivatives; I'm lost on definition problems.",
            command="duplicate",
            key="duplicate-key",
        )
        with self.assertRaises(CollegeCaptureError) as denied:
            self.adapter.record_college_update(self.auth, changed)
        self.assertEqual(denied.exception.code, "idempotency_payload_conflict")
        self.assertEqual(len(self._claims()), before)

        status = CollegeReadService(self.db_path, clock=lambda: NOW).get_update_status(
            TrustedCollegeContext("actor-a", "workspace-a", allow_cross_course=True),
            CollegeStatusReadRequest(command_id="duplicate"),
        )
        self.assertEqual(status["status"], "found")
        self.assertEqual(status["receipt"]["receipt_id"], first["receipt_id"])

    def test_stale_field_revision_is_saved_for_review_without_overwrite(self):
        def racing_write():
            event = {
                "schema_version": "college-event/1.0",
                "event_id": "race-event",
                "event_type": "completion_submission_recorded",
                "subject_ref": "topic-4-individual",
                "payload": {"submission": "accepted"},
                "expected_revisions": [{
                    "subject_id": "topic-4-individual", "field": "submission", "revision": "absent"
                }],
                "source_class": "provider_observation",
                "source_actor": "provider:lms",
                "observed_at": NOW,
                "evidence": [{"evidence_id": "lms:submission"}],
                "certainty": "confirmed",
                "action_intent": "no_provider_action",
            }
            self.domain.record_update(
                self.college_scope,
                CollegeCommandIdentity("race", "race-key"),
                [event],
            )

        adapter = CollegeCaptureAdapter(
            context_service=self.context,
            college_service=self.domain,
            clock=lambda: NOW,
            before_apply=racing_write,
        )
        result = adapter.record_college_update(
            self.auth,
            self._request(
                "Topic 4 individual is submitted but needs work; team started, no group chat.",
                command="stale",
                key="stale-key",
            ),
        )
        self.assertEqual(result["outcome"], "saved_for_review")
        submissions = [item for item in self._claims() if item["field"] == "submission"]
        self.assertEqual([item["value"] for item in submissions], ["accepted"])
        self.assertTrue(result["review_refs"])

    def test_missing_and_revoked_opt_in_fail_closed_without_college_event(self):
        other_scope = ContextScope("actor-b", "workspace-b")
        other_college = CollegeScope("actor-b", "workspace-b")
        self.domain.create_identity(
            other_college,
            CollegeCommandIdentity("other-section", "other-section-key"),
            canonical_id="section-other",
            identity_kind="section",
            identity_status="resolved",
            attributes={"label": "other"},
            reviewed_composite={"kind": "section", "code": "other"},
        )
        missing_auth = TrustedCollegeCaptureContext("actor-b", "workspace-b")
        with self.assertRaises(CollegeCaptureError) as missing:
            self.adapter.record_college_update(
                missing_auth,
                self._request("Calc covered continuity today; there was a quick check and an exam warning."),
            )
        self.assertEqual(missing.exception.code, "capture_not_authorized")

        self.context.revoke_capture_consent(
            self.context_scope,
            self._command("revoke"),
            capture_scope="college-operational",
            scope_version="1",
            expected_revision=1,
        )
        with self.assertRaises(CollegeCaptureError) as revoked:
            self.adapter.record_college_update(
                self.auth,
                self._request(
                    "Calc covered continuity today; there was a quick check and an exam warning.",
                    command="revoked",
                    key="revoked-key",
                ),
            )
        self.assertEqual(revoked.exception.code, "capture_not_authorized")
        with database_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM college_events WHERE command_id='revoked'"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_ambiguous_course_identity_is_durably_reviewable(self):
        self._binding("binding-second", "calc-chat")
        ambiguous_auth = TrustedCollegeCaptureContext(
            actor_id="actor-a",
            workspace_id="workspace-a",
            allowed_section_ids=frozenset({"section-calc"}),
            binding_ids_by_conversation={
                "calc-chat": ("binding-calc", "binding-second")
            },
        )
        result = self.adapter.record_college_update(
            ambiguous_auth,
            self._request(
                "Calc covered continuity today; there was a quick check and an exam warning.",
                command="ambiguous",
                key="ambiguous-key",
            ),
        )
        self.assertEqual(result["outcome"], "saved_for_review")
        self.assertEqual(result["review"]["reason"], "ambiguous_course_identity")
        self.assertIsNotNone(self.context.get_receipt(self.context_scope, command_id="ambiguous"))
        question_id = result["review"]["question_id"]
        questions = self.context.list_questions(self.context_scope)
        self.assertEqual(questions[0]["disposition"], "asked")
        answered = self.adapter.record_college_update(
            ambiguous_auth,
            CollegeQuestionDispositionRequest(
                command_id="answer-ambiguous",
                idempotency_key="answer-ambiguous-key",
                question_id=question_id,
                prompt_key="ambiguous_course_identity",
                disposition="answered",
                expected_revision=1,
                conversation_id="calc-chat",
                answer_summary="Fall 2026 Calc",
            ),
        )
        self.assertEqual(answered["outcome"], "applied")
        self.assertEqual(
            self.context.list_questions(self.context_scope)[0]["disposition"],
            "answered",
        )
        self.assertEqual(self._claims(), [])

    def test_cross_workspace_binding_is_indistinguishable_from_missing(self):
        other_scope = ContextScope("actor-b", "workspace-b")
        self.context.grant_capture_consent(
            other_scope,
            CommandIdentity("other-consent", "other-consent-key"),
            capture_scope="college-operational",
            scope_version="1",
        )
        self.context.create_course_binding(
            other_scope,
            CommandIdentity("other-binding", "other-binding-key"),
            binding_id="private-binding",
            term_id="fall-2026",
            section_id="private-section",
            binding_scope="course",
            review_provenance="private",
            reviewed_at=NOW,
            valid_from=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(days=1),
            explicitly_selected=True,
        )
        request = self._request(
            "Calc covered continuity today; there was a quick check and an exam warning.",
            command="foreign",
            key="foreign-key",
            binding_id="private-binding",
        )
        with self.assertRaises(CollegeCaptureError) as foreign:
            self.adapter.record_college_update(self.auth, request)
        request = self._request(
            "Calc covered continuity today; there was a quick check and an exam warning.",
            command="missing-binding",
            key="missing-binding-key",
            binding_id="missing-binding",
        )
        with self.assertRaises(CollegeCaptureError) as missing:
            self.adapter.record_college_update(self.auth, request)
        self.assertEqual(foreign.exception.code, missing.exception.code)

    def test_pending_and_uncertain_acknowledgments_are_receipt_backed(self):
        request = self._request(
            "Calc covered continuity today; there was a quick check and an exam warning.",
            command="pending",
            key="pending-key",
        )
        pending = CollegeCaptureAdapter(
            context_service=self.context,
            college_service=self.domain,
            receive_only=True,
        ).record_college_update(self.auth, request)
        self.assertEqual(pending["outcome"], "pending")
        self.assertIsNotNone(pending["receipt_id"])

        failing_domain = CollegeDomainService(
            clock=lambda: NOW,
            failure_injector=lambda point: (_ for _ in ()).throw(RuntimeError("injected"))
            if point == "after_domain_mutation" else None,
        )
        uncertain = CollegeCaptureAdapter(
            context_service=self.context,
            college_service=failing_domain,
        ).record_college_update(
            self.auth,
            self._request(
                "Calc covered continuity today; there was a quick check and an exam warning.",
                command="uncertain",
                key="uncertain-key",
            ),
        )
        self.assertEqual(uncertain["outcome"], "uncertain")
        self.assertIsNotNone(uncertain["receipt_id"])

    def test_assessment_command_does_not_require_capture_opt_in(self):
        other = TrustedCollegeCaptureContext(
            actor_id="actor-a",
            workspace_id="workspace-a",
            allowed_section_ids=frozenset({"section-calc"}),
        )
        result = self.adapter.record_college_update(
            other,
            CollegeAssessmentRequest(
                command_id="assessment",
                idempotency_key="assessment-key",
                authorized_scope={"kind": "course", "subject_ids": ["section-calc"]},
                horizon={"start": NOW.isoformat(), "end": (NOW + timedelta(days=1)).isoformat()},
                timezone_name="America/Chicago",
                valid_through=NOW + timedelta(hours=2),
                baseline={"kind": "explicit", "version": 1},
                window={"kind": "today"},
            ),
        )
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(result["provider_actions"], [])

    def test_capture_does_not_mutate_non_college_provider_tables(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            tables = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            excluded = (
                "college_", "context_", "shared_", "raw_conversation_",
                "course_context_", "conversation_", "interaction_",
            )
            provider_tables = [name for name in tables if not name.startswith(excluded)]
            before = {
                name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                for name in provider_tables
            }
        self.adapter.record_college_update(
            self.auth,
            self._request(
                "Calc covered continuity today; there was a quick check and an exam warning.",
                command="side-effects",
                key="side-effects-key",
            ),
        )
        with closing(sqlite3.connect(self.db_path)) as connection:
            after = {
                name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                for name in provider_tables
            }
        self.assertEqual(after, before)

    def test_standalone_api_has_one_write_operation_and_rejects_spoofed_identity(self):
        authenticator = CollegeCaptureAuthenticator(
            api_key="secret",
            actor_id="actor-a",
            workspace_id="workspace-a",
            allowed_section_ids=frozenset({"section-calc"}),
        )
        app = create_college_capture_app(adapter=self.adapter, authenticator=authenticator)
        self.assertEqual(
            {route.operation_id for route in app.routes if getattr(route, "operation_id", None)},
            {"record_college_update"},
        )
        with self.assertRaises(CollegeCaptureError) as spoofed:
            _request({
                "operation": "capture",
                "command_id": "spoof",
                "idempotency_key": "spoof-key",
                "actor_id": "attacker",
                "workspace_id": "other",
            })
        self.assertEqual(spoofed.exception.code, "server_identity_forbidden")


if __name__ == "__main__":
    unittest.main()
