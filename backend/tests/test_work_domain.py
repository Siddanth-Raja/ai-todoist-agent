from datetime import date
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.project_registry import project_registry_service  # noqa: E402
from app.storage import ensure_database  # noqa: E402
from app.todoist_work_adapter import (  # noqa: E402
    normalize_todoist_priority,
    todoist_work_adapter,
)
from app.work_domain import (  # noqa: E402
    NormalizedWorkItem,
    WorkDependency,
    WorkPriority,
    WorkStatus,
)


class TodoistWorkAdapterTests(unittest.TestCase):
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
        self.registry = project_registry_service.snapshot()
        self.today = date(2026, 7, 12)

    def test_normalized_priority_uses_higher_is_more_important_scale(self):
        self.assertEqual(normalize_todoist_priority(None), WorkPriority.NONE)
        self.assertEqual(normalize_todoist_priority(0), WorkPriority.NONE)
        self.assertEqual(normalize_todoist_priority(1), WorkPriority.LOW)
        self.assertEqual(normalize_todoist_priority(2), WorkPriority.MEDIUM)
        self.assertEqual(normalize_todoist_priority(3), WorkPriority.HIGH)
        self.assertEqual(normalize_todoist_priority(4), WorkPriority.URGENT)
        self.assertEqual(normalize_todoist_priority(99), WorkPriority.URGENT)
        self.assertEqual(normalize_todoist_priority("unknown"), WorkPriority.NONE)

    def test_model_represents_dependencies_and_enforces_execution_invariants(self):
        dependency = WorkDependency(
            provider="test-provider",
            provider_record_id="dependency-1",
            dependency_type="blocked_by",
        )
        work = NormalizedWorkItem(
            provider="test-provider",
            provider_record_id="work-1",
            canonical_project_id=None,
            title="Typed work",
            status=WorkStatus.OPEN,
            priority=WorkPriority.HIGH,
            dependencies=(dependency,),
            is_blocked=True,
        )

        self.assertEqual(work.dependencies[0].provider_record_id, "dependency-1")
        self.assertTrue(work.is_blocked)
        with self.assertRaisesRegex(ValidationError, "cannot be executable"):
            NormalizedWorkItem(
                provider="test-provider",
                provider_record_id="completed-work",
                title="Completed work",
                status=WorkStatus.COMPLETED,
                is_executable=True,
            )
        with self.assertRaisesRegex(ValidationError, "container work"):
            NormalizedWorkItem(
                provider="test-provider",
                provider_record_id="container-work",
                title="Container work",
                status=WorkStatus.OPEN,
                is_container=True,
                is_executable=True,
            )

    def test_adapter_preserves_typed_core_and_todoist_source_fields(self):
        task = {
            "id": "todoist-1",
            "content": "Prepare Nebulo review",
            "description": "Bring the context notes",
            "project_id": "todo-project",
            "project_name": "To-Do",
            "section_id": "section-nebulo",
            "section_name": "Nebulo",
            "todoist_section_name": "Nebulo",
            "todoist_section_id": "section-nebulo",
            "category": "Nebulo",
            "classification_source": "todoist_section",
            "due": {"datetime": "2026-07-13T14:30:00-05:00"},
            "priority": 1,
            "todoist_priority": 4,
            "created_at": "2026-07-01T10:00:00-05:00",
            "updated_at": "2026-07-11T11:00:00-05:00",
            "completed": False,
            "labels": ["review"],
            "url": "https://app.todoist.com/app/task/todoist-1",
            "provider_metadata": {"duration": {"amount": 30, "unit": "minute"}},
        }

        work = todoist_work_adapter.adapt_many(
            [task],
            registry=self.registry,
            today=self.today,
        )[0]

        self.assertEqual(work.provider, "todoist")
        self.assertEqual(work.provider_record_id, "todoist-1")
        self.assertEqual(work.canonical_project_id, "project-nebulo")
        self.assertEqual(work.title, "Prepare Nebulo review")
        self.assertEqual(work.description, "Bring the context notes")
        self.assertEqual(work.status, WorkStatus.OPEN)
        self.assertEqual(work.original_provider_status, "active")
        self.assertEqual(work.priority, WorkPriority.URGENT)
        self.assertEqual(work.original_provider_priority, 4)
        self.assertEqual(work.due_date.isoformat(), "2026-07-13")
        self.assertEqual(work.due_at.isoformat(), "2026-07-13T14:30:00-05:00")
        self.assertEqual(work.created_at.isoformat(), "2026-07-01T10:00:00-05:00")
        self.assertEqual(work.updated_at.isoformat(), "2026-07-11T11:00:00-05:00")
        self.assertEqual(work.provider_reference, "todo-project")
        self.assertEqual(work.provider_url, task["url"])
        self.assertEqual(
            work.provider_metadata["provider_metadata"],
            {"duration": {"amount": 30, "unit": "minute"}},
        )
        self.assertEqual(work.dependencies, ())
        self.assertFalse(work.is_blocked)

    def test_hierarchy_sets_container_and_executable_state(self):
        tasks = [
            self._task("parent", "Roadmap parent"),
            self._task("child", "Executable child", parent_id="parent"),
            self._task("explicit-parent", "Explicit parent", labels=["completable"]),
            self._task("explicit-child", "Explicit child", parent_id="explicit-parent"),
            self._task("completed", "Completed leaf", completed=True),
            self._task("canceled", "Canceled leaf", status="canceled"),
            self._task("completed-child-parent", "Parent with completed child"),
            self._task(
                "completed-child",
                "Completed child",
                parent_id="completed-child-parent",
                completed=True,
            ),
        ]

        work_by_id = {
            item.provider_record_id: item
            for item in todoist_work_adapter.adapt_many(
                tasks,
                registry=self.registry,
                today=self.today,
            )
        }

        self.assertTrue(work_by_id["parent"].is_container)
        self.assertFalse(work_by_id["parent"].is_executable)
        self.assertFalse(work_by_id["child"].is_container)
        self.assertTrue(work_by_id["child"].is_executable)
        self.assertFalse(work_by_id["explicit-parent"].is_container)
        self.assertTrue(work_by_id["explicit-parent"].is_executable)
        self.assertEqual(work_by_id["completed"].status, WorkStatus.COMPLETED)
        self.assertFalse(work_by_id["completed"].is_executable)
        self.assertEqual(work_by_id["canceled"].status, WorkStatus.CANCELED)
        self.assertFalse(work_by_id["canceled"].is_executable)
        self.assertFalse(work_by_id["completed-child-parent"].is_container)
        self.assertTrue(work_by_id["completed-child-parent"].is_executable)

    def test_todoist_does_not_invent_blocked_state_or_dependencies_from_text(self):
        task = self._task(
            "blocked-words",
            "Blocked waiting on review feedback",
            description="Depends on another task",
        )

        work = todoist_work_adapter.adapt_many(
            [task],
            registry=self.registry,
            today=self.today,
        )[0]

        self.assertFalse(work.is_blocked)
        self.assertEqual(work.dependencies, ())
        self.assertIsNone(work.canonical_project_id)

    @staticmethod
    def _task(
        task_id: str,
        content: str,
        *,
        parent_id: str | None = None,
        completed: bool = False,
        labels: list[str] | None = None,
        description: str = "",
        status: str | None = None,
    ) -> dict:
        return {
            "id": task_id,
            "content": content,
            "description": description,
            "project_id": "todo-project",
            "project_name": "To-Do",
            "section_name": "Misc",
            "todoist_section_name": "Misc",
            "category": "Misc",
            "parent_id": parent_id,
            "due": None,
            "priority": 4,
            "todoist_priority": 1,
            "created_at": None,
            "updated_at": None,
            "completed": completed,
            "status": status,
            "labels": labels or [],
            "url": f"https://app.todoist.com/app/task/{task_id}",
        }


if __name__ == "__main__":
    unittest.main()
