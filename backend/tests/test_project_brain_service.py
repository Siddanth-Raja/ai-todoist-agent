from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calendar_tools import CalendarReadResult  # noqa: E402
from app.project_brain import PROJECT_DEFINITIONS, ProjectBrainService  # noqa: E402
from app.todoist_tools import TodoistReadResult  # noqa: E402


@dataclass
class FakeSettings:
    timezone: str = "America/Chicago"

    @property
    def local_tz(self):
        return ZoneInfo(self.timezone)


class ProjectBrainServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ProjectBrainService()
        self.now = datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("America/Chicago"))

    def test_preserves_project_keys_and_aliases(self):
        self.assertEqual(
            [project["key"] for project in PROJECT_DEFINITIONS],
            [
                "pcos-ai-todoist-agent",
                "nebulo",
                "xo",
                "freelance",
                "am",
                "personal",
                "needs-classification",
            ],
        )
        self.assertEqual(self.service.canonical_project_key("pcos"), "pcos-ai-todoist-agent")
        self.assertEqual(self.service.canonical_project_key("A&M"), "am")
        self.assertEqual(
            self.service.canonical_project_key("Needs Classification"),
            "needs-classification",
        )

    def test_build_project_preserves_hierarchy_and_ranks_executable_leaf(self):
        project = next(item for item in PROJECT_DEFINITIONS if item["key"] == "pcos-ai-todoist-agent")
        tasks = [
            {
                "id": "parent",
                "content": "ai todoist agent",
                "description": "",
                "section_name": "Misc",
                "todoist_section_name": "Misc",
                "category": "Misc",
                "priority": 1,
                "todoist_priority": 1,
                "labels": [],
            },
            {
                "id": "child",
                "parent_id": "parent",
                "content": "Extract Project Brain service",
                "description": "",
                "section_name": "Misc",
                "todoist_section_name": "Misc",
                "category": "Misc",
                "priority": 4,
                "todoist_priority": 4,
                "labels": [],
            },
        ]

        brain = self.service.build_project(
            project=project,
            tasks=tasks,
            events=[],
            memories=[],
            activity=[],
            now=self.now,
        )

        self.assertEqual(brain["task_count"], 2)
        self.assertEqual(brain["next_recommendation"], "Work next: Extract Project Brain service")
        self.assertEqual(len(brain["task_groups"]), 1)
        self.assertTrue(brain["task_groups"][0]["is_container"])
        self.assertEqual(brain["task_groups"][0]["parent_task"]["id"], "parent")
        self.assertEqual(brain["task_groups"][0]["subtasks"][0]["id"], "child")

    def test_build_project_preserves_needs_classification_diagnostics(self):
        project = next(item for item in PROJECT_DEFINITIONS if item["key"] == "needs-classification")
        task = {
            "id": "ddn",
            "content": "Clarify DDN plan",
            "description": "",
            "section_name": "Misc",
            "todoist_section_name": "Misc",
            "category": "Misc",
            "priority": 4,
            "todoist_priority": 4,
            "labels": [],
        }

        brain = self.service.build_project(
            project=project,
            tasks=[task],
            events=[],
            memories=[],
            activity=[],
            now=self.now,
        )

        self.assertEqual(brain["tasks"][0]["content"], "Clarify DDN plan")
        diagnostic = brain["classification_diagnostics"][0]
        self.assertEqual(diagnostic["resolved_project"], "Needs Classification")
        self.assertTrue(diagnostic["included"])

    def test_list_projects_aggregates_provider_and_internal_context(self):
        tasks = [
            {
                "id": "nebulo-task",
                "content": "Waiting on Brandon feedback",
                "description": "Blocked pending review",
                "section_name": "Nebulo",
                "todoist_section_name": "Nebulo",
                "category": "Nebulo",
                "due": {"date": "2026-06-04"},
                "priority": 4,
                "todoist_priority": 4,
                "created_at": "2026-05-20T12:00:00-05:00",
                "labels": [],
            }
        ]
        events = [
            {
                "id": "nebulo-event",
                "title": "Nebulo review with Brandon",
                "start": "2026-06-06T13:00:00-05:00",
                "end": "2026-06-06T13:30:00-05:00",
                "duration_minutes": 30,
                "busy": True,
                "all_day": False,
                "event_category": "hard",
            }
        ]
        memories = [
            {"id": "memory-nebulo", "type": "project", "title": "Nebulo", "content": "Private storage", "enabled": True},
            {"id": "memory-brandon", "type": "person", "title": "Brandon", "content": "Nebulo collaborator", "enabled": True},
        ]
        activity = [
            {"id": "activity-nebulo", "type": "task_updated", "title": "Nebulo task updated", "payload": {"project_key": "nebulo"}}
        ]

        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)), patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=events),
        ), patch("app.project_brain.list_memory_entries", return_value=memories), patch(
            "app.project_brain.list_activity",
            return_value=activity,
        ):
            projects = self.service.list_projects(settings=FakeSettings(), current_time=self.now)

        nebulo = next(project for project in projects if project["key"] == "nebulo")
        self.assertEqual(nebulo["status"], "Blocked")
        self.assertEqual(nebulo["upcoming_events"][0]["id"], "nebulo-event")
        self.assertEqual(nebulo["recent_activity"][0]["id"], "activity-nebulo")
        self.assertIn("Brandon", nebulo["people"])
        self.assertEqual({memory["id"] for memory in nebulo["memories"]}, {"memory-nebulo", "memory-brandon"})
        self.assertTrue(nebulo["next_recommendation"].startswith("Resolve blocker:"))


if __name__ == "__main__":
    unittest.main()
