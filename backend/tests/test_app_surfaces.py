from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main as main  # noqa: E402
from app.calendar_tools import (  # noqa: E402
    CalendarReadResult,
    categories_conflict,
    find_busy_conflict,
    infer_event_category,
)
from app.storage import DEFAULT_MEMORIES, ensure_database  # noqa: E402
from app.project_work_packages import LinearProjectDiagnostic  # noqa: E402
from app.todoist_tools import TodoistReadResult  # noqa: E402


@dataclass
class FakeSettings:
    todoist_api_token: str | None = "todoist-token"
    google_client_id: str | None = "google-client-id"
    google_client_secret: str | None = "google-client-secret"
    google_refresh_token: str | None = "google-refresh-token"
    google_calendar_id: str = "primary"
    timezone: str = "America/Chicago"
    openai_api_key: str | None = "openai-key"
    openai_model: str = "test-model"
    agent_api_key: str | None = "test-agent-key"

    @property
    def local_tz(self):
        return ZoneInfo(self.timezone)

    @property
    def missing_todoist(self):
        return False

    @property
    def missing_google_calendar_fields(self):
        return []


class AppSurfaceEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = os.path.join(self.tempdir.name, "app.sqlite3")
        self.env_patch = patch.dict(os.environ, {"APP_DB_PATH": self.db_path})
        self.settings_patch = patch("app.main.get_settings", return_value=FakeSettings())
        self.calendar_patch = patch(
            "app.today_projection.list_remaining_today_events",
            return_value=CalendarReadResult(events=[]),
        )
        self.project_calendar_patch = patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=[]),
        )
        self.linear_patch = patch(
            "app.project_brain._read_mapped_linear_work",
            return_value=(
                [],
                (),
                LinearProjectDiagnostic(
                    status="not_mapped",
                    message="No Linear mapping in this endpoint fixture.",
                ),
            ),
        )
        self.env_patch.start()
        self.settings_patch.start()
        self.calendar_patch.start()
        self.project_calendar_patch.start()
        self.linear_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.settings_patch.stop)
        self.addCleanup(self.calendar_patch.stop)
        self.addCleanup(self.project_calendar_patch.stop)
        self.addCleanup(self.linear_patch.stop)
        self.authorization = "Bearer test-agent-key"

    def test_default_memories_are_seeded_once(self):
        memories = main.memory_index(authorization=self.authorization)
        self.assertEqual(len(memories), len(DEFAULT_MEMORIES))

        titles_by_type = {(memory["type"], memory["title"]) for memory in memories}
        self.assertIn(("project", "A&M"), titles_by_type)
        self.assertIn(("project", "Nebulo"), titles_by_type)
        self.assertIn(("person", "Brandon"), titles_by_type)
        self.assertIn(("group", "A&M roommates"), titles_by_type)
        self.assertIn(("classification_rule", "Misc fallback"), titles_by_type)
        self.assertIn(("preference", "Low-energy mode"), titles_by_type)

        ensure_database()
        ensure_database()
        seeded_again = main.memory_index(authorization=self.authorization)
        self.assertEqual(len(seeded_again), len(DEFAULT_MEMORIES))

    def test_confirm_rejects_non_executable_pending_action(self):
        with self.assertRaises(HTTPException) as exc:
            main.confirm(
                main.ConfirmRequest(
                    session_id="test-session",
                    pending_action={
                        "type": "resolve_calendar_conflict",
                        "details": {"options": ["move gym", "keep calendar unchanged"]},
                    },
                ),
                authorization=self.authorization,
            )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("not executable", exc.exception.detail)

    def test_memory_crud_and_activity_log(self):
        initial_count = len(main.memory_index(authorization=self.authorization))
        memory = main.memory_create(
            main.MemoryCreate(
                type="preference",
                title="One next action",
                content="Siddanth prefers one clear next action.",
                confidence=0.9,
            ),
            authorization=self.authorization,
        )
        self.assertEqual(memory["type"], "preference")
        self.assertTrue(memory["enabled"])

        memories = main.memory_index(authorization=self.authorization)
        self.assertEqual(len(memories), initial_count + 1)

        updated = main.memory_update(
            memory["id"],
            main.MemoryUpdate(enabled=False, confidence=0.7),
            authorization=self.authorization,
        )
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["confidence"], 0.7)

        activity = main.activity_index(authorization=self.authorization)
        activity_types = {item["type"] for item in activity}
        self.assertIn("memory_added", activity_types)
        self.assertIn("memory_disabled", activity_types)
        self.assertTrue(all("metadata" in item and "source" in item for item in activity))

        deleted = main.memory_delete(memory["id"], authorization=self.authorization)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(len(main.memory_index(authorization=self.authorization)), initial_count)
        activity = main.activity_index(authorization=self.authorization)
        self.assertIn("memory_deleted", {item["type"] for item in activity})

    def test_habit_definitions_and_checkins(self):
        default_names = [
            habit["name"] for habit in main.habits_index(authorization=self.authorization)
        ]
        self.assertEqual(default_names[:3], ["Gym", "Running", "Work"])

        habit = main.habits_create(
            main.HabitCreate(name="Reading", description="Read for a bit"),
            authorization=self.authorization,
        )
        self.assertEqual(habit["name"], "Reading")

        updated = main.habits_update(
            habit["id"],
            main.HabitUpdate(enabled=False),
            authorization=self.authorization,
        )
        self.assertFalse(updated["enabled"])

        checkin = main.habit_checkins_create(
            main.HabitCheckInCreate(
                habit="gym",
                status="yes",
                note="Lifted",
                timestamp=datetime(2026, 6, 5, 18, 0, tzinfo=ZoneInfo("America/Chicago")),
            ),
            authorization=self.authorization,
        )
        self.assertEqual(checkin["habit"], "Gym")
        self.assertEqual(checkin["status"], "yes")

        checkins = main.habit_checkins_index(authorization=self.authorization)
        self.assertEqual(len(checkins), 1)
        self.assertEqual(checkins[0]["note"], "Lifted")

        activity_types = {
            item["action_type"] for item in main.activity_index(authorization=self.authorization)
        }
        self.assertIn("habit_logged", activity_types)

        deleted = main.habits_delete(habit["id"], authorization=self.authorization)
        self.assertTrue(deleted["deleted"])

    def test_tasks_endpoint_groups_todoist_tasks(self):
        tasks = [
            {
                "id": "task-school",
                "content": "Study for college exam",
                "description": "",
                "project_name": "To-Do",
                "section_name": "A&M",
                "section_id": "section-am",
                "todoist_section_name": "A&M",
                "todoist_section_id": "section-am",
                "category": "A&M",
                "classification_source": "todoist_section",
                "due": {"date": "2026-06-05"},
                "priority": 4,
                "todoist_priority": 1,
                "labels": [],
                "url": "https://app.todoist.com/app/task/task-school",
            },
            {
                "id": "task-client",
                "content": "Call freelance client",
                "description": "",
                "project_name": "To-Do",
                "section_name": "Freelance Web Design",
                "section_id": "section-freelance",
                "todoist_section_name": "Freelance Web Design",
                "todoist_section_id": "section-freelance",
                "category": "Freelance",
                "classification_source": "todoist_section",
                "due": None,
                "priority": 3,
                "todoist_priority": 2,
                "labels": [],
            },
            {
                "id": "task-personal",
                "content": "Buy groceries",
                "description": "",
                "project_name": "To-Do",
                "section_name": "Personal",
                "section_id": "section-personal",
                "todoist_section_name": "Personal",
                "todoist_section_id": "section-personal",
                "category": "Personal",
                "classification_source": "todoist_section",
                "due": None,
                "priority": 1,
                "todoist_priority": 4,
                "completed": True,
                "labels": [],
            },
        ]
        with patch("app.main.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)):
            payload = main.tasks_index(
                current_time=datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("America/Chicago")),
                authorization=self.authorization,
            )

        sections = {section["name"]: section["tasks"] for section in payload["sections"]}
        self.assertEqual(sections["A&M"][0]["content"], "Study for college exam")
        self.assertEqual(sections["A&M"][0]["due_date"], "2026-06-05")
        self.assertEqual(sections["A&M"][0]["todoist_section_name"], "A&M")
        self.assertEqual(sections["A&M"][0]["classification_source"], "todoist_section")
        self.assertEqual(sections["Freelance Web Design"][0]["content"], "Call freelance client")
        self.assertEqual(sections["Freelance Web Design"][0]["category"], "Freelance")
        self.assertTrue(sections["Personal"][0]["completed"])
        self.assertEqual(payload["errors"], [])

    def test_tasks_endpoint_normalizes_optional_created_and_due_dates(self):
        tasks = [
            {
                "id": "valid-dates",
                "content": "Valid dates",
                "todoist_section_name": "Personal",
                "due": {"date": "2026-06-05"},
                "created_at": "2026-06-01T10:30:00Z",
            },
            {
                "id": "null-dates",
                "content": "Null dates",
                "todoist_section_name": "Personal",
                "due": None,
                "created_at": None,
            },
            {
                "id": "missing-dates",
                "content": "Missing dates",
                "todoist_section_name": "Personal",
            },
            {
                "id": "malformed-dates",
                "content": "Malformed dates",
                "todoist_section_name": "Personal",
                "due": {"date": "not-a-date"},
                "created_at": "not-a-date",
            },
        ]
        with patch("app.main.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)):
            payload = main.tasks_index(
                current_time=datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("America/Chicago")),
                authorization=self.authorization,
            )

        by_id = {
            task["id"]: task
            for section in payload["sections"]
            for task in section["tasks"]
        }
        self.assertEqual(by_id["valid-dates"]["due_date"], "2026-06-05")
        self.assertEqual(
            by_id["valid-dates"]["created_at"],
            "2026-06-01T10:30:00+00:00",
        )
        for task_id in ("null-dates", "missing-dates", "malformed-dates"):
            self.assertIsNone(by_id[task_id]["due_date"])
            self.assertIsNone(by_id[task_id]["created_at"])

    def test_today_endpoint_summarizes_life_areas_from_todoist(self):
        tasks = [
            {
                "id": "task-am",
                "content": "Submit housing form",
                "description": "",
                "section_name": "A&M",
                "due": {"date": "2026-06-04"},
                "priority": 1,
                "todoist_priority": 1,
                "labels": [],
            },
            {
                "id": "task-xo",
                "content": "Review headset prototype",
                "description": "",
                "section_name": "XO",
                "due": {"date": "2026-06-05"},
                "priority": 1,
                "todoist_priority": 1,
                "labels": [],
            },
            {
                "id": "task-freelance",
                "content": "Send client invoice",
                "description": "",
                "section_name": "Freelance",
                "due": None,
                "priority": 1,
                "todoist_priority": 4,
                "labels": [],
            },
            {
                "id": "task-personal",
                "content": "Buy groceries",
                "description": "",
                "section_name": "Personal",
                "due": None,
                "priority": 1,
                "todoist_priority": 1,
                "labels": [],
            },
        ]
        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)):
            payload = main.today_index(
                current_time=datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("America/Chicago")),
                authorization=self.authorization,
            )

        areas = {area["name"]: area for area in payload["life_areas"]}
        self.assertEqual(areas["A&M"]["description"], "College, TAMU, Blinn, housing, registration")
        self.assertEqual(areas["A&M"]["task_count"], 1)
        self.assertEqual(areas["A&M"]["overdue_count"], 1)
        self.assertEqual(areas["A&M"]["status"], "Needs attention")
        self.assertEqual(areas["XO"]["today_count"], 1)
        self.assertEqual(areas["XO"]["status"], "Needs attention")
        self.assertEqual(areas["Freelance"]["high_priority_count"], 1)
        self.assertEqual(areas["Freelance"]["status"], "Active")
        self.assertEqual(areas["Personal"]["status"], "Active")
        self.assertEqual(areas["Misc"]["task_count"], 0)
        self.assertEqual(areas["Misc"]["status"], "Quiet")
        self.assertEqual(areas["A&M"]["project_key"], "am")
        self.assertEqual(
            areas["A&M"]["next_recommendation"],
            "Work next: Submit housing form",
        )
        self.assertIsNone(payload["next_event"])
        self.assertEqual(payload["today_remaining_events"], [])
        self.assertEqual(payload["errors"], [])

    def test_today_does_not_use_past_event_as_next_event(self):
        now = datetime(2026, 6, 5, 17, 45, tzinfo=ZoneInfo("America/Chicago"))
        events = [
            self._calendar_event("past", "Lunch", "2026-06-05T12:00:00-05:00", "2026-06-05T13:00:00-05:00"),
        ]
        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=[])), patch(
            "app.today_projection.list_remaining_today_events",
            return_value=CalendarReadResult(events=events),
        ):
            payload = main.today_index(current_time=now, authorization=self.authorization)

        self.assertIsNone(payload["next_event"])
        self.assertEqual(payload["today_remaining_events"], [])
        self.assertGreater(payload["current_free_block"]["duration_minutes"], 0)

    def test_today_does_not_report_current_free_block_during_ongoing_event(self):
        now = datetime(2026, 6, 5, 17, 45, tzinfo=ZoneInfo("America/Chicago"))
        events = [
            self._calendar_event(
                "ongoing",
                "Client review",
                "2026-06-05T17:30:00-05:00",
                "2026-06-05T18:30:00-05:00",
            ),
        ]
        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=[])), patch(
            "app.today_projection.list_remaining_today_events",
            return_value=CalendarReadResult(events=events),
        ):
            payload = main.today_index(current_time=now, authorization=self.authorization)

        self.assertIsNone(payload["current_free_block"])
        self.assertEqual(payload["today_remaining_events"][0]["title"], "Client review")

    def test_today_event_in_45_minutes_is_next_event_and_ends_free_block(self):
        now = datetime(2026, 6, 5, 17, 45, tzinfo=ZoneInfo("America/Chicago"))
        events = [
            self._calendar_event("next", "Gym", "2026-06-05T18:30:00-05:00", "2026-06-05T19:30:00-05:00"),
        ]
        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=[])), patch(
            "app.today_projection.list_remaining_today_events",
            return_value=CalendarReadResult(events=events),
        ):
            payload = main.today_index(current_time=now, authorization=self.authorization)

        self.assertEqual(payload["next_event"]["title"], "Gym")
        self.assertEqual(payload["minutes_until_next_event"], 45)
        self.assertEqual(payload["current_free_block"]["start"], now.isoformat())
        self.assertEqual(payload["current_free_block"]["end"], "2026-06-05T18:30:00-05:00")
        self.assertTrue(payload["current_free_block"]["low_usefulness"])

    def test_today_event_within_45_minutes_triggers_preparation_recommendation(self):
        now = datetime(2026, 6, 5, 17, 45, tzinfo=ZoneInfo("America/Chicago"))
        events = [
            self._calendar_event("next", "XO sync", "2026-06-05T18:30:00-05:00", "2026-06-05T19:30:00-05:00"),
        ]
        tasks = [
            {
                "id": "task-1",
                "content": "Do deep work",
                "section_name": "XO",
                "due": None,
                "priority": 1,
                "todoist_priority": 1,
                "labels": [],
            }
        ]
        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)), patch(
            "app.today_projection.list_remaining_today_events",
            return_value=CalendarReadResult(events=events),
        ):
            payload = main.today_index(current_time=now, authorization=self.authorization)

        self.assertEqual(payload["recommendation"]["type"], "prepare")
        self.assertIn("Prepare for XO sync", payload["recommendation"]["title"])

    def test_today_all_day_birthday_does_not_block_free_time(self):
        now = datetime(2026, 6, 5, 17, 45, tzinfo=ZoneInfo("America/Chicago"))
        events = [
            self._calendar_event(
                "birthday",
                "Ashwin birthday",
                "2026-06-05T00:00:00-05:00",
                "2026-06-06T00:00:00-05:00",
                all_day=True,
                event_category="informational",
            ),
        ]
        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=[])), patch(
            "app.today_projection.list_remaining_today_events",
            return_value=CalendarReadResult(events=events),
        ):
            payload = main.today_index(current_time=now, authorization=self.authorization)

        self.assertIsNone(payload["next_event"])
        self.assertEqual(payload["today_remaining_events"][0]["event_category"], "informational")
        self.assertGreater(payload["current_free_block"]["duration_minutes"], 0)

    def test_today_uses_america_chicago_timezone(self):
        utc_now = datetime(2026, 6, 5, 22, 45, tzinfo=ZoneInfo("UTC"))
        events = [
            self._calendar_event("next", "Dinner", "2026-06-05T18:30:00-05:00", "2026-06-05T19:30:00-05:00"),
        ]
        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=[])), patch(
            "app.today_projection.list_remaining_today_events",
            return_value=CalendarReadResult(events=events),
        ):
            payload = main.today_index(current_time=utc_now, authorization=self.authorization)

        self.assertEqual(payload["now"], "2026-06-05T17:45:00-05:00")
        self.assertIn("5:45 PM", payload["now_display"])
        self.assertEqual(payload["minutes_until_next_event"], 45)

    def test_projects_endpoint_builds_project_brain(self):
        now = datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("America/Chicago"))
        tasks = [
            {
                "id": "task-nebulo",
                "content": "Waiting on Brandon feedback",
                "description": "Blocked until review lands",
                "project_name": "To-Do",
                "section_name": "Nebulo",
                "section_id": "section-nebulo",
                "todoist_section_name": "Nebulo",
                "todoist_section_id": "section-nebulo",
                "category": "Nebulo",
                "classification_source": "todoist_section",
                "due": {"date": "2026-06-04"},
                "priority": 1,
                "todoist_priority": 4,
                "created_at": "2026-05-20T12:00:00-05:00",
                "labels": [],
            },
            {
                "id": "task-xo",
                "content": "Review headset prototype",
                "description": "",
                "project_name": "To-Do",
                "section_name": "XO Collective",
                "todoist_section_name": "XO Collective",
                "category": "XO",
                "due": None,
                "priority": 1,
                "todoist_priority": 2,
                "labels": [],
            },
        ]
        events = [
            self._calendar_event(
                "event-nebulo",
                "Nebulo review with Brandon",
                "2026-06-06T13:00:00-05:00",
                "2026-06-06T13:30:00-05:00",
            ),
            self._calendar_event(
                "event-pcos",
                "PCOS Project Brain QA",
                "2026-06-07T14:00:00-05:00",
                "2026-06-07T15:00:00-05:00",
            ),
        ]
        main.log_activity(
            action_type="calendar_event_updated",
            title="Calendar event updated: Nebulo review with Brandon",
            detail="2026-06-06T13:00:00-05:00",
            source="google_calendar",
            payload={"type": "update_calendar_event", "event": events[0]},
        )

        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)), patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=events),
        ):
            projects = main.projects_index(current_time=now, authorization=self.authorization)
            nebulo = main.project_detail("nebulo", current_time=now, authorization=self.authorization)
            am = main.project_detail("A&M", current_time=now, authorization=self.authorization)

        self.assertEqual(len(projects), 7)
        self.assertEqual(nebulo["name"], "Nebulo")
        self.assertEqual(nebulo["status"], "Needs attention")
        self.assertEqual(nebulo["tasks"][0]["content"], "Waiting on Brandon feedback")
        self.assertEqual(nebulo["upcoming_events"][0]["title"], "Nebulo review with Brandon")
        self.assertIn("Brandon", nebulo["people"])
        self.assertTrue(any(memory["title"] == "Nebulo" for memory in nebulo["memories"]))
        self.assertTrue(any(activity["title"].startswith("Calendar event updated") for activity in nebulo["recent_activity"]))
        self.assertEqual(nebulo["blockers"], [])
        attention_types = {signal["type"] for signal in nebulo["attention_signals"]}
        self.assertIn("overdue_task", attention_types)
        self.assertIn("keyword_attention", attention_types)
        self.assertIn("stale_high_priority_task", attention_types)
        self.assertEqual(
            nebulo["next_recommendation"],
            "Work next: Waiting on Brandon feedback",
        )
        self.assertEqual(am["key"], "am")

    def test_projects_include_subtask_hierarchy_and_rank_leaf_tasks(self):
        now = datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("America/Chicago"))
        pcos_parent = {
            "id": "task-pcos-parent",
            "content": "ai todoist agent",
            "description": "",
            "project_name": "To-Do",
            "section_name": "Misc",
            "todoist_section_name": "Misc",
            "category": "Misc",
            "due": None,
            "priority": 1,
            "todoist_priority": 1,
            "labels": [],
        }
        pcos_subtasks = [
            {
                "id": f"task-pcos-child-{index}",
                "content": f"PCOS implementation subtask {index}",
                "description": "",
                "project_name": "To-Do",
                "parent_id": "task-pcos-parent",
                "section_name": "Misc",
                "todoist_section_name": "Misc",
                "category": "Misc",
                "due": None,
                "priority": 1,
                "todoist_priority": 1,
                "labels": [],
            }
            for index in range(1, 17)
        ]
        pcos_subtasks[7]["content"] = "Wire Project Brain task hierarchy"
        pcos_subtasks[7]["priority"] = 4
        pcos_subtasks[7]["todoist_priority"] = 4
        pcos_subtasks[10]["content"] = "Completed child should not be next"
        pcos_subtasks[10]["priority"] = 4
        pcos_subtasks[10]["todoist_priority"] = 4
        pcos_subtasks[10]["completed"] = True
        freelance_task = {
            "id": "task-ddn-freelance",
            "content": "brainstorm features for DDN and ask Rithika to connect",
            "description": "",
            "project_name": "To-Do",
            "section_name": "Freelance Web Design",
            "todoist_section_name": "Freelance Web Design",
            "category": "Freelance",
            "due": None,
            "priority": 4,
            "todoist_priority": 4,
            "labels": [],
        }
        unknown_ddn_task = {
            "id": "task-ddn-unknown",
            "content": "Clarify DDN plan",
            "description": "",
            "project_name": "To-Do",
            "section_name": "Misc",
            "todoist_section_name": "Misc",
            "category": "Misc",
            "due": None,
            "priority": 4,
            "todoist_priority": 4,
            "labels": [],
        }
        tasks = [pcos_parent, *pcos_subtasks, freelance_task, unknown_ddn_task]

        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)), patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=[]),
        ):
            pcos = main.project_detail("pcos", current_time=now, authorization=self.authorization)
            freelance = main.project_detail("freelance", current_time=now, authorization=self.authorization)
            needs_classification = main.project_detail(
                "needs-classification",
                current_time=now,
                authorization=self.authorization,
            )

        pcos_group = next(
            group for group in pcos["task_groups"] if group["parent_task"]["id"] == "task-pcos-parent"
        )
        self.assertTrue(pcos_group["is_container"])
        self.assertEqual(len(pcos_group["subtasks"]), 15)
        self.assertEqual(pcos["task_count"], 16)
        self.assertIn("Wire Project Brain task hierarchy", pcos["next_recommendation"])
        self.assertNotIn("ai todoist agent", pcos["next_recommendation"])
        self.assertFalse(
            any(task["content"] == "Completed child should not be next" for task in pcos_group["subtasks"])
        )

        self.assertTrue(
            any(task["content"] == "brainstorm features for DDN and ask Rithika to connect" for task in freelance["tasks"])
        )
        self.assertIn("brainstorm features for DDN", freelance["next_recommendation"])

        self.assertEqual(needs_classification["task_count"], 1)
        self.assertEqual(needs_classification["tasks"][0]["content"], "Clarify DDN plan")
        self.assertTrue(
            any(
                diagnostic["task_title"] == "Clarify DDN plan"
                and diagnostic["resolved_project"] == "Needs Classification"
                and diagnostic["included"]
                for diagnostic in needs_classification["classification_diagnostics"]
            )
        )

    def test_calendar_endpoint_returns_labels_and_conflicts(self):
        events = [
            {
                "id": "event-1",
                "title": "XO sync",
                "start": "2026-06-05T12:00:00-05:00",
                "end": "2026-06-05T13:00:00-05:00",
                "duration_minutes": 60,
                "all_day": False,
                "busy": True,
                "event_type": "hard",
                "event_category": "hard",
            },
            {
                "id": "event-2",
                "title": "Gym",
                "start": "2026-06-05T12:30:00-05:00",
                "end": "2026-06-05T13:30:00-05:00",
                "duration_minutes": 60,
                "all_day": False,
                "busy": True,
                "event_type": "flexible",
                "event_category": "flexible",
            },
            {
                "id": "event-3",
                "title": "Graduation",
                "start": "2026-06-05T12:15:00-05:00",
                "end": "2026-06-05T12:45:00-05:00",
                "duration_minutes": 30,
                "all_day": False,
                "busy": True,
                "event_type": "informational",
                "event_category": "informational",
            },
        ]
        with patch(
            "app.main.list_upcoming_events",
            return_value=CalendarReadResult(events=events),
        ):
            payload = main.calendar_index(
                days=7,
                current_time=datetime(2026, 6, 5, 9, 0, tzinfo=ZoneInfo("America/Chicago")),
                authorization=self.authorization,
            )

        self.assertEqual(
            [event["event_type"] for event in payload["events"]],
            ["hard", "flexible", "informational"],
        )
        self.assertEqual(payload["events"][2]["event_category"], "informational")
        self.assertEqual(len(payload["conflicts"]), 1)
        self.assertEqual(payload["conflicts"][0]["first_event_title"], "XO sync")

    def test_calendar_categories_and_conflict_rules(self):
        self.assertEqual(infer_event_category("Dentist appointment", []), "hard")
        self.assertEqual(infer_event_category("Study block", []), "flexible")
        self.assertEqual(infer_event_category("A&M graduation", []), "informational")
        self.assertTrue(categories_conflict("hard", "hard"))
        self.assertTrue(categories_conflict("hard", "flexible"))
        self.assertFalse(categories_conflict("flexible", "flexible"))
        self.assertFalse(categories_conflict("hard", "informational"))

        events = [
            {
                "id": "hard",
                "title": "Interview",
                "start": "2026-06-05T12:00:00-05:00",
                "end": "2026-06-05T13:00:00-05:00",
                "busy": True,
                "event_category": "hard",
            },
            {
                "id": "info",
                "title": "Birthday",
                "start": "2026-06-05T12:00:00-05:00",
                "end": "2026-06-05T13:00:00-05:00",
                "busy": True,
                "event_category": "informational",
            },
        ]
        conflict = find_busy_conflict(
            start=datetime(2026, 6, 5, 12, 30, tzinfo=ZoneInfo("America/Chicago")),
            end=datetime(2026, 6, 5, 13, 30, tzinfo=ZoneInfo("America/Chicago")),
            events=events,
            event_category="flexible",
        )
        self.assertEqual(conflict["id"], "hard")
        self.assertIsNone(
            find_busy_conflict(
                start=datetime(2026, 6, 5, 12, 30, tzinfo=ZoneInfo("America/Chicago")),
                end=datetime(2026, 6, 5, 13, 30, tzinfo=ZoneInfo("America/Chicago")),
                events=events,
                event_category="informational",
            )
        )

    def test_chat_logs_task_and_confirmation_activity(self):
        chat_payload = {
            "answer": "Added it. Also confirm the next thing.",
            "intent": "capture_task",
            "actions_taken": [
                {
                    "type": "create_todoist_task",
                    "status": "success",
                    "task": {
                        "content": "Buy socks",
                        "section_name": "Personal",
                    },
                },
                {
                    "type": "update_calendar_event",
                    "status": "success",
                    "event": {
                        "title": "Gym",
                        "start": "2026-06-05T14:45:00-05:00",
                    },
                    "previous_event": {
                        "title": "Gym",
                        "start": "2026-06-05T14:30:00-05:00",
                    },
                }
            ],
            "needs_confirmation": True,
            "confirmation_prompt": "Move gym?",
            "pending_action": {
                "type": "resolve_calendar_conflict",
                "details": {"affected_event": "Gym"},
            },
            "free_block": None,
            "recommended_tasks": [],
            "calendar_events": [],
            "mode": "ai_agent",
            "errors": [],
        }
        with patch("app.main.handle_chat", return_value=chat_payload):
            response = main.chat(
                main.ChatRequest(
                    message="Add socks",
                    current_time=datetime(2026, 6, 5, 10, 0, tzinfo=ZoneInfo("America/Chicago")),
                ),
                authorization=self.authorization,
            )

        self.assertEqual(response["intent"], "capture_task")
        activity = main.activity_index(authorization=self.authorization)
        activity_types = {item["type"] for item in activity}
        self.assertIn("task_created", activity_types)
        self.assertIn("calendar_event_updated", activity_types)
        self.assertIn("confirmation_requested", activity_types)
        self.assertTrue(all(item["type"] == item["action_type"] for item in activity))

    def test_confirmation_lifecycle_activity(self):
        confirm_payload = {
            "answer": "Updated it.",
            "intent": "replan",
            "actions_taken": [],
            "needs_confirmation": False,
            "confirmation_prompt": None,
            "pending_action": None,
            "free_block": None,
            "recommended_tasks": [],
            "calendar_events": [],
            "mode": "ai_agent",
            "errors": [],
        }
        pending_action = {"type": "update_calendar_event", "details": {"event_id": "event-gym"}}
        with patch("app.main.confirm_pending_action", return_value=confirm_payload):
            main.confirm(
                main.ConfirmRequest(session_id="test-session", pending_action=pending_action),
                authorization=self.authorization,
            )

        main.confirm_cancel(
            main.ConfirmCancelRequest(session_id="test-session", pending_action=pending_action),
            authorization=self.authorization,
        )

        activity_types = {item["type"] for item in main.activity_index(authorization=self.authorization)}
        self.assertIn("confirmation_completed", activity_types)
        self.assertIn("confirmation_cancelled", activity_types)

    def _calendar_event(
        self,
        event_id: str,
        title: str,
        start: str,
        end: str,
        *,
        all_day: bool = False,
        busy: bool = True,
        event_category: str = "hard",
    ) -> dict:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        return {
            "id": event_id,
            "title": title,
            "start": start,
            "end": end,
            "duration_minutes": int((end_dt - start_dt).total_seconds() // 60),
            "all_day": all_day,
            "busy": busy,
            "event_type": event_category,
            "event_category": event_category,
        }

    def test_new_endpoints_require_api_key(self):
        with self.assertRaises(HTTPException) as exc:
            main.memory_index(authorization=None)
        self.assertEqual(exc.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
