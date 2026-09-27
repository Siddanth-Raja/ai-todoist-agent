from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.college_briefing import (  # noqa: E402
    CollegeBriefRequest,
    CollegeBriefingService,
)
from app.college_reads import TrustedCollegeContext  # noqa: E402


TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 9, 26, 9, 0, tzinfo=TZ)


class FakeReads:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_college_state(self, auth, request):
        self.calls.append((auth, request))
        return deepcopy(self.response)


def identity(subject_id, label):
    return {
        "record_type": "identity",
        "record_id": subject_id,
        "canonical_id": subject_id,
        "attributes": {"label": label},
    }


def attention(subject_id, category, summary, order, **extra):
    return {
        "subject_id": subject_id,
        "category": category,
        "categories": [category],
        "summary": summary,
        "certainty": extra.pop("certainty", "confirmed"),
        "evidence_refs": [f"evidence-{order}"],
        **extra,
    }


def ready_response(items, *, scope=None, coverage=None, omissions=None):
    assessed = NOW - timedelta(minutes=5)
    return {
        "assessment_status": "ready",
        "records": [
            identity("calc", "Calculus"),
            identity("calc-exam", "Calculus exam"),
            identity("calc-section", "Calculus class"),
            identity("engr-bonus", "ENGR bonus"),
            identity("club", "Engineering club"),
            {
                "record_type": "assessment",
                "record_id": "assessment-current",
                "assessment_id": "assessment-current",
                "assessment_status": "ready",
                "assessed_at": assessed.isoformat(),
                "valid_through": (NOW + timedelta(hours=2)).isoformat(),
                "attention_items": items,
                "coverage": coverage or [],
                "omissions": omissions or [],
                "evidence_refs": [ref for item in items for ref in item["evidence_refs"]],
                "authorized_scope": scope or {"kind": "cross_course"},
            },
        ],
        "diagnostics": [],
        "pagination": {"next_cursor": None},
        "coverage_expectations": [{
            "provider": "blinn",
            "availability": "pending",
            "completeness": "unknown",
            "freshness": "unknown",
            "reason": "administrator_approval",
        }],
    }


class CollegeBriefingTests(unittest.TestCase):
    def setUp(self):
        self.auth = TrustedCollegeContext("actor", "workspace")

    def build(self, response, *, scope="cross_course", courses=()):
        reads = FakeReads(response)
        service = CollegeBriefingService(read_service_factory=lambda: reads)
        result = service.build(
            self.auth,
            CollegeBriefRequest(
                evaluated_at=NOW,
                timezone_name="America/Chicago",
                scope=scope,
                course_ids=tuple(courses),
            ),
        )
        return result, reads, service

    def test_anything_important_from_calc_today_is_course_scoped(self):
        response = ready_response([
            attention(
                "calc-exam", "required_obligations", 'requirement: "required"', 0,
                due_lower_bound="2026-09-26",
            )
        ], scope={"kind": "course", "course_ids": ["calc"]})

        result, reads, _service = self.build(response, scope="course", courses=("calc",))

        self.assertEqual(result.primary.subject_id, "calc-exam")
        self.assertIn("required obligation", result.opening)
        self.assertIn("course-scoped", result.opening)
        self.assertFalse(result.whole_college_reassurance)
        self.assertEqual(reads.calls[0][1].scope, "course")
        self.assertEqual(reads.calls[0][1].course_ids, ("calc",))

    def test_cross_course_today_preserves_recorded_order_and_evidence(self):
        items = [
            attention("calc-exam", "current_conflicts_blockers", "Review conflicting deadline evidence.", 0),
            attention("calc", "learning_needs", 'learning_need: {"statement":"practice limits"}', 1),
            attention("calc-section", "relevant_changes", 'session:calc:topic:topic_covered: "continuity"', 2, field="session:calc:topic:topic_covered"),
        ]
        result, _reads, _service = self.build(ready_response(items))

        self.assertEqual(
            [item.subject_id for item in result.decisive_items],
            ["calc-exam", "calc"],
        )
        self.assertEqual(result.primary.evidence_refs, ("evidence-0",))
        self.assertIn("Learning is still needed", result.decisive_items[1].summary)
        self.assertIn("Finished work remains a separate", result.decisive_items[1].summary)
        self.assertIn("continuity", result.session_changes[0].summary)
        self.assertIn("session change", result.session_changes[0].summary)

    def test_repeated_reads_are_stable_and_do_not_request_assessment(self):
        response = ready_response([
            attention("calc", "learning_needs", 'learning_need: "review derivatives"', 0)
        ])
        reads = FakeReads(response)
        service = CollegeBriefingService(read_service_factory=lambda: reads)
        request = CollegeBriefRequest(evaluated_at=NOW, timezone_name="America/Chicago")

        first = service.build(self.auth, request)
        second = service.build(self.auth, request)

        self.assertEqual(first, second)
        self.assertEqual(len(reads.calls), 2)
        self.assertFalse(first.assessment_requested)
        self.assertFalse(first.provider_refresh_performed)
        self.assertFalse(first.interaction_cursor_advanced)

    def test_expired_assessment_is_not_used_as_current(self):
        response = ready_response([
            attention("calc-exam", "required_obligations", 'requirement: "required"', 0)
        ])
        assessment = response["records"][-1]
        assessment["assessment_status"] = "expired"
        assessment["valid_through"] = (NOW - timedelta(minutes=1)).isoformat()
        response["assessment_status"] = "expired"

        result, _reads, _service = self.build(response)

        self.assertEqual(result.assessment_status, "expired")
        self.assertIsNone(result.primary)
        self.assertEqual(result.decisive_items, ())
        self.assertIn("did not refresh providers", result.opening)

    def test_missing_queued_failed_and_invalidated_assessments_are_honest(self):
        expected = {
            "missing": "no recorded assessment",
            "queued": "no current conclusion",
            "running": "no current conclusion",
            "failed": "no current conclusion",
            "invalidated": "invalidated",
        }
        for status, fragment in expected.items():
            with self.subTest(status=status):
                response = ready_response([
                    attention("calc-exam", "required_obligations", 'requirement: "required"', 0)
                ])
                assessment = response["records"][-1]
                assessment["assessment_status"] = status
                response["assessment_status"] = status
                if status == "missing":
                    response["records"].pop()

                result, _reads, _service = self.build(response)

                self.assertEqual(result.assessment_status, status)
                self.assertIsNone(result.primary)
                self.assertIn(fragment, result.opening.lower())

    def test_optional_work_is_safe_to_wait_not_a_decisive_obligation(self):
        result, _reads, _service = self.build(ready_response([
            attention("engr-bonus", "optional_recommended_opportunities", 'requirement: "optional"', 0)
        ]))

        self.assertIsNone(result.primary)
        self.assertEqual(len(result.safe_to_wait), 1)
        self.assertIn("does not block", result.safe_to_wait[0].summary)

    def test_selected_commitment_marked_free_still_consumes_capacity(self):
        result, _reads, _service = self.build(ready_response([
            attention(
                "club", "relevant_changes",
                "Selected commitment consumes capacity regardless of provider free/busy.", 0,
            )
        ]))

        self.assertIn("consumes time", result.session_changes[0].summary)
        self.assertIn("marks the time free", result.session_changes[0].summary)

    def test_material_blinn_gap_blocks_reassurance_and_stays_pending(self):
        response = ready_response(
            [],
            coverage=[{
                "coverage_id": "coverage-blinn",
                "provider": "blinn",
                "account_id": "student",
                "availability": "pending",
                "completeness": "unknown",
                "freshness": "unknown",
                "reason": "administrator_approval",
                "bounds": {"material_to_scope": True},
            }],
        )

        result, _reads, _service = self.build(response)

        self.assertFalse(result.complete_for_scope)
        self.assertFalse(result.whole_college_reassurance)
        self.assertEqual(result.coverage_gaps[0].availability, "pending")
        self.assertEqual(result.coverage_gaps[0].reason, "administrator_approval")
        self.assertIn("prevent reassurance", result.opening)

    def test_explicit_assessment_command_is_separate_from_reads(self):
        response = ready_response([])
        result, reads, service = self.build(response)
        commands = []

        refreshed = service.request_then_build(
            assessment_command=lambda: commands.append("requested"),
            auth=self.auth,
            request=CollegeBriefRequest(evaluated_at=NOW, timezone_name="America/Chicago"),
        )

        self.assertEqual(result.assessment_status, "ready")
        self.assertEqual(refreshed.assessment_status, "ready")
        self.assertEqual(commands, ["requested"])
        self.assertEqual(len(reads.calls), 2)


if __name__ == "__main__":
    unittest.main()
