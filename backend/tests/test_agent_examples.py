from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import handle_chat  # noqa: E402
from app.calendar_tools import CalendarReadResult, CalendarWriteResult  # noqa: E402
from app.todoist_tools import TodoistReadResult, TodoistWriteResult  # noqa: E402


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

    @property
    def local_tz(self):
        return ZoneInfo(self.timezone)

    @property
    def missing_todoist(self):
        return False

    @property
    def missing_google_calendar_fields(self):
        return []


TASKS = [
    {
        "id": "task-1",
        "content": "migrate things from notion",
        "project_id": "project-personal",
        "project_name": "Personal",
        "due": {"date": "2026-06-04"},
        "priority": 4,
        "todoist_priority": 1,
        "labels": [],
        "url": "https://app.todoist.com/app/task/task-1",
    },
    {
        "id": "task-2",
        "content": "contact more clients",
        "project_id": "project-freelance",
        "project_name": "Freelance",
        "due": None,
        "priority": 3,
        "todoist_priority": 2,
        "labels": [],
        "url": "https://app.todoist.com/app/task/task-2",
    },
]

EVENTS = [
    {
        "id": "event-1",
        "title": "Work block",
        "start": "2026-06-04T09:00:00-05:00",
        "end": "2026-06-04T10:00:00-05:00",
        "duration_minutes": 60,
        "all_day": False,
        "busy": True,
        "event_type": "flexible",
    }
]


class AgentExampleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 4, 14, 0, tzinfo=ZoneInfo("America/Chicago"))
        self.base_patches = [
            patch("app.agent.get_settings", return_value=FakeSettings()),
            patch("app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=TASKS)),
            patch("app.agent.list_todays_events", return_value=CalendarReadResult(events=EVENTS)),
        ]
        for item in self.base_patches:
            item.start()
            self.addCleanup(item.stop)

    def test_plan_now(self):
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="Start with migrating things from Notion. It is due today and high priority.",
                intent="plan",
            ),
            None,
        )):
            response = handle_chat("What should I work on right now?", self.now)

        self.assertEqual(response["intent"], "plan")
        self.assertEqual(response["actions_taken"], [])
        self.assertIn("Start with", response["answer"])
        self.assertIn("recommended_tasks", response)

    def test_low_energy_plan(self):
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="Do one tiny useful win: migrate one small batch from Notion.",
                intent="plan",
            ),
            None,
        )):
            response = handle_chat("I feel lazy, what's one small useful thing I can do?", self.now)

        self.assertEqual(response["intent"], "plan")
        self.assertEqual(response["actions_taken"], [])
        self.assertIn("tiny", response["answer"].lower())

    def test_capture_task(self):
        created_task = {**TASKS[0], "id": "task-nike", "content": "Buy Nike socks"}
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I’ll add that to Todoist.",
                intent="capture_task",
                action_type="create_task",
                task={
                    "content": "Buy Nike socks",
                    "project_category": "Misc",
                    "due_string": None,
                    "labels": [],
                    "priority": 4,
                },
            ),
            None,
        )), patch("app.agent.create_task", return_value=TodoistWriteResult(task=created_task)):
            response = handle_chat("I need Nike socks", self.now)

        self.assertEqual(response["intent"], "capture_task")
        self.assertEqual(response["actions_taken"][0]["type"], "create_task")
        self.assertIn("Added Todoist task", response["answer"])

    def test_schedule_event(self):
        event = {
            "id": "event-brandon",
            "title": "Meeting with Brandon",
            "start": "2026-06-05T18:00:00-05:00",
            "end": "2026-06-05T19:00:00-05:00",
            "duration_minutes": 60,
            "all_day": False,
            "busy": True,
            "event_type": "hard",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can put that on your calendar.",
                intent="schedule_event",
                action_type="create_calendar_event",
                calendar_event={
                    "title": "Meeting with Brandon",
                    "start": "2026-06-05T18:00:00-05:00",
                    "end": "2026-06-05T19:00:00-05:00",
                },
            ),
            None,
        )), patch("app.agent.create_calendar_event", return_value=CalendarWriteResult(event=event)):
            response = handle_chat("Meeting with Brandon tomorrow at 6 for an hour", self.now)

        self.assertEqual(response["intent"], "schedule_event")
        self.assertEqual(response["actions_taken"][0]["type"], "create_calendar_event")
        self.assertIn("Added calendar event", response["answer"])

    def test_replan_after_lunch(self):
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="You just finished lunch, so restart with a contained task before changing the calendar.",
                intent="replan",
            ),
            None,
        )):
            response = handle_chat("I just finished lunch, what should I do now?", self.now)

        self.assertEqual(response["intent"], "replan")
        self.assertEqual(response["actions_taken"], [])
        self.assertIn("lunch", response["answer"].lower())

    def _decision(
        self,
        answer,
        intent,
        action_type="none",
        task=None,
        calendar_event=None,
    ):
        return {
            "answer": answer,
            "intent": intent,
            "action_type": action_type,
            "task": task or {
                "content": None,
                "project_category": None,
                "due_string": None,
                "labels": [],
                "priority": None,
            },
            "calendar_event": calendar_event or {
                "title": None,
                "start": None,
                "end": None,
            },
            "needs_confirmation": False,
            "confirmation_prompt": None,
        }


if __name__ == "__main__":
    unittest.main()
