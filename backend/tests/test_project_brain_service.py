from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calendar_tools import CalendarReadResult  # noqa: E402
from app.project_brain import ProjectBrainService  # noqa: E402
from app.project_registry import project_registry_service  # noqa: E402
from app.storage import create_canonical_project, ensure_database  # noqa: E402
from app.todoist_tools import TodoistReadResult  # noqa: E402
from app.todoist_work_adapter import todoist_work_adapter  # noqa: E402


@dataclass
class FakeSettings:
    timezone: str = "America/Chicago"

    @property
    def local_tz(self):
        return ZoneInfo(self.timezone)


class ProjectBrainServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.env_patch = patch.dict(
            os.environ,
            {"APP_DB_PATH": os.path.join(self.tempdir.name, "app.sqlite3")},
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        ensure_database()
        self.service = ProjectBrainService()
        self.registry = project_registry_service.snapshot()
        self.now = datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("America/Chicago"))

    def test_preserves_project_keys_and_aliases(self):
        self.assertEqual(
            [project["key"] for project in self.registry.projects],
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
        expected_aliases = {
            "ai todoist agent": "pcos-ai-todoist-agent",
            "personal-chief-of-staff": "pcos-ai-todoist-agent",
            "chief of staff": "pcos-ai-todoist-agent",
            "aandm": "am",
            "a&m": "am",
            "a and m": "am",
            "tamu": "am",
            "college": "am",
            "uncategorized": "needs-classification",
        }
        self.assertEqual(
            {
                alias: self.service.canonical_project_key(alias)
                for alias in expected_aliases
            },
            expected_aliases,
        )

    def test_build_project_preserves_hierarchy_and_ranks_executable_leaf(self):
        project = self.registry.get_project_definition("pcos")
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
            tasks=todoist_work_adapter.adapt_many(
                tasks,
                registry=self.registry,
                today=self.now.date(),
            ),
            events=[],
            memories=[],
            activity=[],
            now=self.now,
            registry=self.registry,
        )

        self.assertEqual(brain["task_count"], 2)
        self.assertEqual(brain["next_recommendation"], "Work next: Extract Project Brain service")
        self.assertEqual(len(brain["task_groups"]), 1)
        self.assertTrue(brain["task_groups"][0]["is_container"])
        self.assertEqual(brain["task_groups"][0]["parent_task"]["id"], "parent")
        self.assertEqual(brain["task_groups"][0]["subtasks"][0]["id"], "child")

    def test_build_project_preserves_needs_classification_diagnostics(self):
        project = self.registry.get_project_definition("needs-classification")
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
            tasks=todoist_work_adapter.adapt_many(
                [task],
                registry=self.registry,
                today=self.now.date(),
            ),
            events=[],
            memories=[],
            activity=[],
            now=self.now,
            registry=self.registry,
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

    def test_new_registry_project_flows_into_project_brain_without_code_changes(self):
        create_canonical_project(
            key="future-project",
            display_name="Future Project",
            description="Added through durable registry storage.",
            aliases=["future"],
            classification_hints=[{"type": "keyword", "value": "future signal"}],
            provider_mappings=[
                {
                    "provider": "github",
                    "resource_type": "repository",
                    "provider_ref": "Siddanth-Raja/future-project",
                }
            ],
        )
        tasks = [
            {
                "id": "future-task",
                "content": "Follow up on future signal",
                "description": "",
                "section_name": "Misc",
                "todoist_section_name": "Misc",
                "category": "Misc",
                "priority": 2,
                "todoist_priority": 2,
                "labels": [],
            }
        ]

        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)), patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=[]),
        ), patch("app.project_brain.list_memory_entries", return_value=[]), patch(
            "app.project_brain.list_activity",
            return_value=[],
        ):
            projects = self.service.list_projects(settings=FakeSettings(), current_time=self.now)
            future = self.service.get_project("future", settings=FakeSettings(), current_time=self.now)

        self.assertEqual(len(projects), 8)
        self.assertEqual(future["key"], "future-project")
        self.assertEqual(future["tasks"][0]["id"], "future-task")


if __name__ == "__main__":
    unittest.main()
