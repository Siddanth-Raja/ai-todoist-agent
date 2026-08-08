from datetime import datetime
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.project_chat_grounding import (  # noqa: E402
    ProjectChatGroundingService,
    ProjectQuestionKind,
)
from app.project_registry import ProjectRegistrySnapshot  # noqa: E402


PROJECTS = (
    {"key": "pcos-ai-todoist-agent", "name": "PCOS / ai todoist agent", "system_state": False},
    {"key": "xo", "name": "XO", "system_state": False},
    {"key": "nebulo", "name": "Nebulo", "system_state": False},
    {"key": "freelance", "name": "Freelance", "system_state": False},
)
REGISTRY = ProjectRegistrySnapshot(
    projects=PROJECTS,
    aliases={
        "pcos-ai-todoist-agent": "pcos-ai-todoist-agent",
        "pcos": "pcos-ai-todoist-agent",
        "chief-of-staff": "pcos-ai-todoist-agent",
        "xo": "xo",
        "nebulo": "nebulo",
        "freelance": "freelance",
    },
)


class FakeRegistryService:
    def snapshot(self):
        return REGISTRY


class FakeBrainService:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.calls = []

    def get_project(self, project_key, *, settings, current_time=None):
        self.calls.append((project_key, settings, current_time))
        return self.snapshots.get(project_key)

    def snapshot(self, *, settings, current_time=None):
        self.calls.append(("snapshot", settings, current_time))
        project_values = tuple(self.snapshots.values())
        return SimpleNamespace(
            projects=tuple(SimpleNamespace(summary=value) for value in project_values),
            personal_reality={
                "schema_version": 1,
                "items": tuple(
                    item
                    for value in project_values
                    for item in value["reality"]["items"]
                ),
            },
        )


def snapshot(key, name, *, diagnostic_status="connected"):
    return {
        "key": key,
        "name": name,
        "status": "blocked",
        "next_recommendation": "Start SID-129 from Linear.",
        "dependency_summary": {
            "active_dependency_count": 2,
            "active_blocked_work_count": 1,
            "needs_review_dependency_count": 1,
            "needs_review_blocked_work_count": 1,
            "resolved_dependency_count": 4,
        },
        "dependency_evidence": [
            {
                "relationship_provider": "linear",
                "evaluation_state": "active",
                "blocked_work": {"provider_identifier": "SID-129", "title": "Ground Chat"},
                "blocking_work": {"provider_identifier": "SID-126", "title": "Project Brain API"},
            },
            {
                "relationship_provider": "linear",
                "evaluation_state": "resolved",
                "blocked_work": {"provider_identifier": "SID-1"},
                "blocking_work": {"provider_identifier": "SID-2"},
            },
        ],
        "work_packages": [
            {
                "title": "Canonical Project Intelligence",
                "provider": "linear",
                "availability_state": "available",
                "next_action": {
                    "provider": "linear",
                    "provider_identifier": "SID-129",
                    "title": "Ground Chat",
                },
            }
        ],
        "people": ["Brandon"],
        "memories": [{"type": "person", "title": "Brandon"}],
        "linear_diagnostic": {
            "status": diagnostic_status,
            "message": (
                "Mapped Linear work loaded successfully."
                if diagnostic_status == "connected"
                else "Linear could not be reached; existing Project Brain sources remain available."
            ),
        },
        "activity_focus": {
            "canonical_project_key": key,
            "primary_state": "active_momentum" if key == "pcos-ai-todoist-agent" else "waiting_external",
            "confidence": "low",
            "freshness": "unknown",
            "evidence": [],
        },
        "recent_changes": {
            "changes": (
                [{"id": "change-1", "provider": "linear", "provider_record_id": "SID-245", "category": "work_completed"}]
                if key == "pcos-ai-todoist-agent"
                else []
            ),
            "total_count": 1 if key == "pcos-ai-todoist-agent" else 0,
        },
        "reality": {
            "items": [
                {
                    "reality_item_id": f"reality:{key}",
                    "canonical_project_key": key,
                    "title": f"{name} obligation",
                    "classification": "needs_action" if key == "pcos-ai-todoist-agent" else "waiting",
                    "classification_reason": "Canonical shared classification.",
                    "temporal": {
                        "action_useful_now": key == "pcos-ai-todoist-agent",
                    },
                    "provider_identity": {
                        "provider": "linear",
                        "provider_record_id": f"record:{key}",
                    },
                    "evidence": [
                        {
                            "evidence_id": f"evidence:{key}",
                            "summary": "Attributable Linear evidence.",
                        }
                    ],
                    "effective_correction": None,
                }
            ],
            "provider_diagnostics": (
                ["todoist: missing_history"] if key == "pcos-ai-todoist-agent" else []
            ),
        },
    }


class ProjectChatGroundingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 16, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
        self.settings = object()
        self.snapshots = {
            project["key"]: snapshot(project["key"], project["name"])
            for project in PROJECTS
        }
        self.brain = FakeBrainService(self.snapshots)
        self.service = ProjectChatGroundingService(
            registry_service=FakeRegistryService(),
            brain_service=self.brain,
        )

    def test_all_four_mapped_projects_resolve_through_registry_aliases(self):
        cases = (
            ("What's going on with chief of staff?", "pcos-ai-todoist-agent", ProjectQuestionKind.OVERVIEW),
            ("What should I work on next for XO?", "xo", ProjectQuestionKind.NEXT_MOVE),
            ("What's blocking Nebulo?", "nebulo", ProjectQuestionKind.BLOCKERS),
            ("What are my Freelance feature options right now?", "freelance", ProjectQuestionKind.WORK_PACKAGES),
        )
        for message, key, kind in cases:
            with self.subTest(message=message):
                result = self.service.ground(
                    message,
                    settings=self.settings,
                    current_time=self.now,
                )
                self.assertIsNotNone(result)
                self.assertEqual(result.canonical_project_key, key)
                self.assertEqual(result.question_kind, kind)
        self.assertEqual([call[0] for call in self.brain.calls], [case[1] for case in cases])

    def test_blocker_answer_uses_snapshot_summary_and_current_evidence(self):
        result = self.service.ground("What's blocking Nebulo?", settings=self.settings)

        self.assertIn("2 active dependencies affecting 1 blocked work items", result.answer)
        self.assertIn("SID-129 is blocked by SID-126", result.answer)
        self.assertEqual(len(result.evidence), 1)

    def test_next_move_is_preserved_verbatim(self):
        result = self.service.ground("What is the XO next move?", settings=self.settings)

        self.assertIn(self.snapshots["xo"]["next_recommendation"], result.answer)
        self.assertEqual(
            result.evidence[0]["next_recommendation"],
            self.snapshots["xo"]["next_recommendation"],
        )

    def test_packages_preserve_provider_and_next_action(self):
        result = self.service.ground("Show Freelance work packages", settings=self.settings)

        self.assertIn("linear", result.answer)
        self.assertIn("SID-129", result.answer)
        self.assertEqual(result.evidence[0]["provider"], "linear")

    def test_people_and_context_can_follow_prior_canonical_project(self):
        result = self.service.ground(
            "Who is involved in this project?",
            settings=self.settings,
            conversation_context={"canonical_project_key": "nebulo"},
        )

        self.assertEqual(result.canonical_project_key, "nebulo")
        self.assertIn("Brandon", result.answer)
        self.assertIn("Attached context", result.answer)

    def test_unknown_and_ambiguous_projects_request_clarification_without_brain_read(self):
        unknown = self.service.ground("What's blocking Atlantis?", settings=self.settings)
        ambiguous = self.service.ground("What's blocking XO and Nebulo?", settings=self.settings)
        unknown_with_context = self.service.ground(
            "What's blocking Atlantis?",
            settings=self.settings,
            conversation_context={"canonical_project_key": "nebulo"},
        )
        mixed_known_unknown = self.service.ground(
            "What's blocking XO and Atlantis?",
            settings=self.settings,
            conversation_context={"canonical_project_key": "nebulo"},
        )
        unknown_package_with_context = self.service.ground(
            "Show Atlantis work packages",
            settings=self.settings,
            conversation_context={"canonical_project_key": "nebulo"},
        )

        self.assertIn("could not resolve", unknown.answer)
        self.assertIn("more than one project", ambiguous.answer)
        self.assertIsNone(unknown.canonical_project_key)
        self.assertIsNone(ambiguous.canonical_project_key)
        self.assertIsNone(unknown_with_context.canonical_project_key)
        self.assertIsNone(mixed_known_unknown.canonical_project_key)
        self.assertIsNone(unknown_package_with_context.canonical_project_key)
        self.assertEqual(self.brain.calls, [])

    def test_typographic_apostrophe_is_supported(self):
        result = self.service.ground("What’s blocking Nebulo?", settings=self.settings)

        self.assertEqual(result.question_kind, ProjectQuestionKind.BLOCKERS)
        self.assertEqual(result.canonical_project_key, "nebulo")

    def test_provider_failure_is_unknown_not_empty(self):
        self.snapshots["nebulo"] = snapshot(
            "nebulo",
            "Nebulo",
            diagnostic_status="provider_failure",
        )
        result = self.service.ground("What's blocking Nebulo?", settings=self.settings)

        self.assertIn("unknown", result.answer)
        self.assertIn("could not be reached", result.answer)
        self.assertNotIn("no current", result.answer.lower())
        self.assertTrue(result.warnings)

        overview = self.service.ground("What's going on with Nebulo?", settings=self.settings)
        self.assertIn("degraded", overview.answer)
        self.assertNotIn("0 active dependencies", overview.answer)
        self.assertNotIn("0 current Linear work packages", overview.answer)

    def test_global_reality_questions_use_one_project_brain_snapshot_with_evidence(self):
        attention = self.service.ground("What needs me today?", settings=self.settings, current_time=self.now)
        changes = self.service.ground("What changed since I last checked?", settings=self.settings, current_time=self.now)
        waiting = self.service.ground("What am I waiting on?", settings=self.settings, current_time=self.now)

        self.assertEqual(attention.question_kind, ProjectQuestionKind.NEEDS_TODAY)
        self.assertIn("PCOS / ai todoist agent obligation", attention.answer)
        self.assertEqual(attention.evidence[0]["reality_item_id"], "reality:pcos-ai-todoist-agent")
        self.assertIn("SID-245", changes.answer)
        self.assertTrue(changes.evidence)
        self.assertIn("waiting", waiting.answer.lower())
        self.assertTrue(waiting.evidence)
        self.assertEqual([call[0] for call in self.brain.calls], ["snapshot", "snapshot", "snapshot"])

    def test_project_today_omission_and_uncertainty_are_explained_without_title_matching(self):
        omitted = self.service.ground("Why is XO not on Today?", settings=self.settings)
        not_actionable = self.service.ground("What needs me today for Nebulo?", settings=self.settings)
        uncertain = self.service.ground("What is uncertain because a provider is unavailable?", settings=self.settings)

        self.assertEqual(omitted.question_kind, ProjectQuestionKind.WHY_NOT_TODAY)
        self.assertIn("waiting", omitted.answer.lower())
        self.assertEqual(omitted.evidence[0]["provider_identity"]["provider_record_id"], "record:xo")
        self.assertEqual(not_actionable.question_kind, ProjectQuestionKind.NEEDS_TODAY)
        self.assertIn("no shared item", not_actionable.answer.lower())
        self.assertEqual(not_actionable.evidence, ())
        self.assertIn("missing_history", uncertain.answer)
        self.assertNotIn("nothing changed", uncertain.answer.lower())

    def test_generic_global_planning_question_is_not_hijacked(self):
        result = self.service.ground("What should I work on right now?", settings=self.settings)

        self.assertIsNone(result)
        self.assertEqual(self.brain.calls, [])

    def test_generic_next_move_can_use_unambiguous_project_conversation_context(self):
        result = self.service.ground(
            "What should I work on right now?",
            settings=self.settings,
            conversation_context={"canonical_project_key": "xo"},
        )

        self.assertEqual(result.canonical_project_key, "xo")
        self.assertIn("Start SID-129 from Linear.", result.answer)


if __name__ == "__main__":
    unittest.main()
