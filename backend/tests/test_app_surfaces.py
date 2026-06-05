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
from app.calendar_tools import CalendarReadResult  # noqa: E402
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
        self.env_patch.start()
        self.settings_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.settings_patch.stop)
        self.authorization = "Bearer test-agent-key"

    def test_memory_crud_and_activity_log(self):
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
        self.assertEqual(len(memories), 1)

        updated = main.memory_update(
            memory["id"],
            main.MemoryUpdate(enabled=False, confidence=0.7),
            authorization=self.authorization,
        )
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["confidence"], 0.7)

        activity = main.activity_index(authorization=self.authorization)
        self.assertIn("memory_added", {item["action_type"] for item in activity})

        deleted = main.memory_delete(memory["id"], authorization=self.authorization)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(main.memory_index(authorization=self.authorization), [])

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
                "project_name": "Freelance",
                "section_name": None,
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
        self.assertEqual(sections["Freelance"][0]["content"], "Call freelance client")
        self.assertTrue(sections["Personal"][0]["completed"])
        self.assertEqual(payload["errors"], [])

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
        with patch("app.main.list_active_tasks", return_value=TodoistReadResult(tasks=tasks)):
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
        self.assertEqual(areas["XO"]["status"], "Due today")
        self.assertEqual(areas["Freelance"]["high_priority_count"], 1)
        self.assertEqual(areas["Freelance"]["status"], "High priority active")
        self.assertEqual(areas["Personal"]["status"], "Clear for steady work")
        self.assertEqual(areas["Misc"]["task_count"], 0)
        self.assertEqual(areas["Misc"]["status"], "Clear")
        self.assertEqual(payload["errors"], [])

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

        self.assertEqual([event["event_type"] for event in payload["events"]], ["hard", "flexible"])
        self.assertEqual(len(payload["conflicts"]), 1)
        self.assertEqual(payload["conflicts"][0]["first_event_title"], "XO sync")

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
        activity_types = {
            item["action_type"] for item in main.activity_index(authorization=self.authorization)
        }
        self.assertIn("task_created", activity_types)
        self.assertIn("confirmation_requested", activity_types)

    def test_new_endpoints_require_api_key(self):
        with self.assertRaises(HTTPException) as exc:
            main.memory_index(authorization=None)
        self.assertEqual(exc.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
