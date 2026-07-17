import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.project_registry import ProjectRegistrySnapshot  # noqa: E402
from app.recommendation_service import recommendation_service  # noqa: E402
from app.tasks_projection import tasks_projection_service  # noqa: E402
from app.todoist_tools import TodoistReadResult  # noqa: E402
from app.work_domain import NormalizedWorkItem  # noqa: E402


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=ZoneInfo("America/New_York"))
REGISTRY = ProjectRegistrySnapshot(projects=(), aliases={})


def task(
    task_id: str,
    content: str,
    section: str,
    *,
    priority: int = 1,
    due: str | None = None,
    created_at: str | None = None,
) -> dict:
    return {
        "id": task_id,
        "content": content,
        "description": "",
        "project_name": "To-Do",
        "section_name": section,
        "todoist_section_name": section,
        "todoist_section_id": f"section-{section}",
        "priority": 5 - priority,
        "todoist_priority": priority,
        "due": {"date": due} if due is not None else None,
        "created_at": created_at,
        "labels": [],
    }


class TasksProjectionTests(unittest.TestCase):
    def project(self, tasks: list[dict], error: str | None = None) -> dict:
        return tasks_projection_service.project(
            todoist_result=TodoistReadResult(tasks=tasks, error=error),
            registry=REGISTRY,
            current_time=NOW,
        )

    def test_returns_all_life_areas_with_explicit_empty_states(self):
        payload = self.project([task("personal", "Buy groceries", "Personal")])

        recommendations = {item["area"]: item for item in payload["recommendations"]}
        self.assertEqual(
            list(recommendations),
            ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc"],
        )
        self.assertEqual(recommendations["Personal"]["state"], "recommended")
        self.assertEqual(recommendations["Personal"]["task_count"], 1)
        self.assertEqual(recommendations["Personal"]["recommendation"]["task"]["id"], "personal")
        self.assertEqual(recommendations["XO"]["state"], "empty")
        self.assertIsNone(recommendations["XO"]["recommendation"])
        self.assertEqual(payload["provider"]["status"], "available")

    def test_shared_service_ranks_and_preserves_evidence_and_task_alternatives(self):
        payload = self.project(
            [
                task("older", "Write notes", "Nebulo", priority=2, created_at="2026-01-01T12:00:00Z"),
                task("urgent", "Ship demo", "Nebulo", priority=4, due="2026-07-17"),
                task("later", "Polish copy", "Nebulo", priority=1),
            ]
        )

        area = next(item for item in payload["recommendations"] if item["area"] == "Nebulo")
        recommendation = area["recommendation"]
        self.assertEqual(recommendation["provider"], "todoist")
        self.assertEqual(recommendation["provider_record_id"], "urgent")
        self.assertEqual(recommendation["action"], "do_work")
        self.assertIsInstance(recommendation["score"], float)
        self.assertTrue(recommendation["explanation"])
        self.assertIn("normalized_priority", {item["signal"] for item in recommendation["evidence"]})
        self.assertIn("due_urgency", {item["signal"] for item in recommendation["evidence"]})
        self.assertEqual(recommendation["alternatives"][0]["task"]["id"], "older")
        self.assertEqual(recommendation["alternatives"][0]["provider_record_id"], "older")

    def test_ties_are_deterministic_and_do_not_depend_on_input_order(self):
        first = task("a", "Same signal A", "A&M", priority=2)
        second = task("b", "Same signal B", "A&M", priority=2)

        forward = self.project([second, first])
        reverse = self.project([first, second])

        def selected(payload: dict) -> str:
            area = next(item for item in payload["recommendations"] if item["area"] == "A&M")
            return area["recommendation"]["provider_record_id"]

        self.assertEqual(selected(forward), selected(reverse))
        self.assertEqual(selected(forward), "a")

    def test_provider_failure_is_not_reported_as_connected_empty(self):
        payload = self.project([], error="Todoist token refresh failed.")

        self.assertEqual(payload["provider"]["status"], "unavailable")
        self.assertEqual(payload["errors"], ["Todoist token refresh failed."])
        self.assertTrue(all(item["state"] == "unavailable" for item in payload["recommendations"]))

    def test_partial_provider_results_are_explicitly_degraded(self):
        payload = self.project(
            [task("known", "Known task", "Personal")],
            error="Todoist pagination stopped early.",
        )

        self.assertEqual(payload["provider"]["status"], "degraded")
        personal = next(item for item in payload["recommendations"] if item["area"] == "Personal")
        self.assertEqual(personal["state"], "recommended")

    def test_malformed_dates_are_safe_and_no_context_is_invented(self):
        payload = self.project(
            [task("bad-dates", "Safe malformed dates", "Misc", due="not-a-date", created_at="not-a-date")]
        )

        area = next(item for item in payload["recommendations"] if item["area"] == "Misc")
        recommendation = area["recommendation"]
        self.assertIsNone(recommendation["task"]["due_date"])
        self.assertIsNone(recommendation["task"]["created_at"])
        signals = {item["signal"] for item in recommendation["evidence"]}
        self.assertFalse(
            signals
            & {"usable_free_block_fit", "energy_fit", "upcoming_commitment", "project_momentum"}
        )
        self.assertIsNone(recommendation["context"]["usable_free_block_minutes"])
        self.assertIsNone(recommendation["context"]["energy"])
        self.assertIsNone(recommendation["context"]["minutes_until_upcoming_commitment"])

    def test_build_reads_todoist_once_and_uses_normalized_adapter(self):
        settings = Mock(local_tz=ZoneInfo("America/New_York"))
        result = TodoistReadResult(tasks=[task("one", "One task", "Personal")])
        with patch("app.tasks_projection.list_active_tasks", return_value=result) as read_tasks, patch(
            "app.tasks_projection.project_registry_service.snapshot",
            return_value=REGISTRY,
        ), patch(
            "app.tasks_projection.todoist_work_adapter.adapt_many",
            wraps=tasks_projection_service.todoist_adapter.adapt_many,
        ) as adapt:
            payload = tasks_projection_service.build(settings=settings, current_time=NOW)

        read_tasks.assert_called_once_with(settings)
        adapt.assert_called_once()
        self.assertEqual(payload["recommendations"][4]["area"], "Personal")

    def test_each_life_area_delegates_to_shared_recommendation_service(self):
        with patch(
            "app.tasks_projection.recommendation_service.recommend_current_action",
            wraps=recommendation_service.recommend_current_action,
        ) as recommend:
            self.project([task("one", "One task", "Personal")])

        self.assertEqual(recommend.call_count, 6)
        personal_call = next(call for call in recommend.call_args_list if call.args[0])
        self.assertIsInstance(personal_call.args[0][0], NormalizedWorkItem)


if __name__ == "__main__":
    unittest.main()
