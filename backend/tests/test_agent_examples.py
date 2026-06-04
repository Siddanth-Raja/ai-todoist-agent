from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.agent as agent  # noqa: E402
from app.agent import _decision_schema, _sanitize_decision, handle_chat  # noqa: E402
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
        agent.PENDING_ACTION = None
        self.addCleanup(self._clear_pending_action)
        self.now = datetime(2026, 6, 4, 14, 0, tzinfo=ZoneInfo("America/Chicago"))
        self.base_patches = [
            patch("app.agent.get_settings", return_value=FakeSettings()),
            patch("app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=TASKS)),
            patch("app.agent.list_todays_events", return_value=CalendarReadResult(events=EVENTS)),
        ]
        for item in self.base_patches:
            item.start()
            self.addCleanup(item.stop)

    def _clear_pending_action(self):
        agent.PENDING_ACTION = None

    def test_plan_now(self):
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="Start with migrating things from Notion. It is due today and high priority.",
                intent="plan",
                action_type="none",
            ),
            None,
        )):
            response = handle_chat("What should I work on right now?", self.now)

        self.assertEqual(response["intent"], "plan")
        self.assertEqual(response["actions_taken"], [])
        self.assertFalse(response["needs_confirmation"])
        self.assertIsNone(response["pending_action"])
        self.assertIn("Start with", response["answer"])
        self.assertIn("recommended_tasks", response)

    def test_planning_question_action_none_even_if_model_proposes_tool(self):
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="Do one tiny useful win: migrate one small batch from Notion.",
                intent="plan",
                action_type="create_todoist_task",
                task={
                    "content": "Bad planning tool call",
                    "project_category": "Misc",
                    "due_string": None,
                    "labels": [],
                    "priority": 4,
                },
            ),
            None,
        )), patch("app.agent.create_task") as create_task_mock:
            response = handle_chat("I feel lazy, what's one small useful thing I can do?", self.now)

        self.assertEqual(response["intent"], "plan")
        self.assertEqual(response["actions_taken"], [])
        create_task_mock.assert_not_called()
        self.assertIn("tiny", response["answer"].lower())

    def test_capture_task(self):
        created_task = {**TASKS[0], "id": "task-nike", "content": "Buy Nike socks"}
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I’ll add that to Todoist.",
                intent="capture_task",
                action_type="create_todoist_task",
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
        self.assertEqual(response["actions_taken"][0]["type"], "create_todoist_task")
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

    def test_schema_allowed_actions_are_documented(self):
        schema = _decision_schema()
        action_enum = schema["properties"]["action_type"]["enum"]
        self.assertEqual(action_enum, ["none", "create_todoist_task", "create_calendar_event"])
        self.assertIn("pending_action", schema["required"])
        self.assertEqual(
            schema["properties"]["pending_action"]["properties"]["type"]["enum"],
            ["resolve_calendar_conflict"],
        )

    def test_calendar_conflict_needs_confirmation(self):
        pending_action = {
            "type": "resolve_calendar_conflict",
            "details": {
                "conflict": "Gym overlaps with Brandon meeting",
                "options": ["move gym", "keep calendar unchanged"],
            },
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="That conflicts with gym. Would you like me to move gym or keep the calendar unchanged?",
                intent="schedule_event",
                needs_confirmation=True,
                confirmation_prompt="Move gym or keep the calendar unchanged?",
                pending_action=pending_action,
            ),
            None,
        )):
            response = handle_chat("Meeting with Brandon at 6", self.now)

        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["confirmation_prompt"], "Move gym or keep the calendar unchanged?")
        self.assertEqual(response["pending_action"], pending_action)
        self.assertEqual(agent.PENDING_ACTION, pending_action)
        self.assertEqual(response["actions_taken"], [])

    def test_reschedule_suggestion_needs_confirmation(self):
        pending_action = {
            "type": "resolve_calendar_conflict",
            "details": {
                "suggested_change": "reschedule gym to 7pm",
                "affected_event": "Gym",
            },
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can reschedule gym to 7pm if you want.",
                intent="replan",
                needs_confirmation=True,
                confirmation_prompt="Should I reschedule gym to 7pm?",
                pending_action=pending_action,
            ),
            None,
        )):
            response = handle_chat("I missed gym, what should I do?", self.now)

        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["pending_action"]["type"], "resolve_calendar_conflict")
        self.assertEqual(response["confirmation_prompt"], "Should I reschedule gym to 7pm?")

    def test_informational_response_does_not_need_confirmation(self):
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="You have enough time for a 30-minute task before the next block.",
                intent="question",
                needs_confirmation=False,
            ),
            None,
        )):
            response = handle_chat("Do I have time to work before my next event?", self.now)

        self.assertFalse(response["needs_confirmation"])
        self.assertIsNone(response["confirmation_prompt"])
        self.assertIsNone(response["pending_action"])

    def test_next_response_can_resolve_pending_action(self):
        pending_action = {
            "type": "resolve_calendar_conflict",
            "details": {"options": ["move gym", "keep calendar unchanged"]},
        }
        agent.PENDING_ACTION = pending_action

        def fake_decision(settings, context):
            self.assertEqual(context["pending_action"], pending_action)
            return (
                self._decision(
                    answer="Got it. I will treat moving gym as the selected resolution.",
                    intent="replan",
                    needs_confirmation=False,
                ),
                None,
            )

        with patch("app.agent._get_llm_decision", side_effect=fake_decision):
            response = handle_chat("move gym", self.now)

        self.assertFalse(response["needs_confirmation"])
        self.assertIsNone(response["pending_action"])
        self.assertIsNone(agent.PENDING_ACTION)

    def test_legacy_create_task_action_is_rejected(self):
        decision = _sanitize_decision(
            self._decision(
                answer="I will add that.",
                intent="capture_task",
                action_type="create_task",
                task={
                    "content": "Buy Nike socks",
                    "project_category": "Misc",
                    "due_string": None,
                    "labels": [],
                    "priority": 4,
                },
            )
        )

        self.assertEqual(decision["action_type"], "none")

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

    def test_openai_http_error_includes_debug_details(self):
        response = requests.Response()
        response.status_code = 401
        response._content = b'{"error":{"message":"Invalid API key"}}'
        error = requests.HTTPError("401 Client Error", response=response)

        with patch("app.agent.requests.post", side_effect=error):
            result = handle_chat("What should I work on right now?", self.now)

        self.assertEqual(result["mode"], "planning_deterministic_fallback")
        self.assertEqual(result["errors"][-1]["source"], "openai")
        self.assertEqual(result["errors"][-1]["type"], "HTTPError")
        self.assertEqual(result["errors"][-1]["status"], 401)
        self.assertIn("Invalid API key", result["errors"][-1]["message"])

    def _decision(
        self,
        answer,
        intent,
        action_type="none",
        task=None,
        calendar_event=None,
        needs_confirmation=False,
        confirmation_prompt=None,
        pending_action=None,
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
            "needs_confirmation": needs_confirmation,
            "confirmation_prompt": confirmation_prompt,
            "pending_action": pending_action,
        }


if __name__ == "__main__":
    unittest.main()
