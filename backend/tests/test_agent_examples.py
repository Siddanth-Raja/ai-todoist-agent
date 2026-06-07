from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.agent as agent  # noqa: E402
from app.agent import _decision_schema, _sanitize_decision, handle_chat  # noqa: E402
from app.calendar_tools import CalendarReadResult, CalendarWriteResult  # noqa: E402
from app.main import ChatRequest, chat, require_agent_api_key  # noqa: E402
from app.todoist_tools import TodoistReadResult, TodoistWriteResult, create_task  # noqa: E402


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


TASKS = [
    {
        "id": "task-1",
        "content": "migrate things from notion",
        "project_id": "project-todo",
        "project_name": "To-Do",
        "section_id": "section-personal",
        "section_name": "Personal",
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
        "section_id": None,
        "section_name": None,
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

MEMORIES = [
    {
        "id": "memory-person-brandon",
        "type": "person",
        "title": "Brandon",
        "content": "Associated with Nebulo.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-person-ashwin",
        "type": "person",
        "title": "Ashwin",
        "content": "Associated with XO.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-person-charlie",
        "type": "person",
        "title": "Charlie",
        "content": "Associated with XO.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-person-nikhil",
        "type": "person",
        "title": "Nikhil",
        "content": "A&M roommate.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-person-andy",
        "type": "person",
        "title": "Andy",
        "content": "A&M roommate.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-person-kamden",
        "type": "person",
        "title": "Kamden",
        "content": "A&M roommate.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-person-sam",
        "type": "person",
        "title": "Sam",
        "content": "Carrollton house / UTD friend group.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-person-jai",
        "type": "person",
        "title": "Jai",
        "content": "Carrollton house / UTD friend group.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-person-krrish",
        "type": "person",
        "title": "Krrish",
        "content": "Carrollton house / UTD friend group.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-group-am-roommates",
        "type": "group",
        "title": "A&M roommates",
        "content": "Nikhil, Andy, Kamden.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-group-carrollton-utd",
        "type": "group",
        "title": "Carrollton house / UTD group",
        "content": "Sam, Jai, Krrish.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-rule-shopping",
        "type": "classification_rule",
        "title": "Shopping and errands",
        "content": "Shopping and errands go to Personal.",
        "confidence": 1.0,
        "enabled": True,
    },
    {
        "id": "memory-disabled",
        "type": "person",
        "title": "Disabled Person",
        "content": "Associated with Nebulo.",
        "confidence": 1.0,
        "enabled": False,
    },
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
            patch("app.agent.list_upcoming_events", return_value=CalendarReadResult(events=EVENTS)),
            patch("app.agent.list_memory_entries", return_value=MEMORIES),
            patch(
                "app.agent.create_task",
                return_value=TodoistWriteResult(task={**TASKS[0], "id": "task-created"}),
            ),
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

    def test_water_bottle_capture_overrides_bad_planning_decision(self):
        created_task = {
            **TASKS[0],
            "id": "task-water-bottle",
            "content": "Buy a new water bottle from Target",
            "project_name": "Personal",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="You could think about errands later.",
                intent="plan",
                action_type="none",
            ),
            None,
        )), patch("app.agent.create_task", return_value=TodoistWriteResult(task=created_task)):
            response = handle_chat("I need to buy a new water bottle from Target", self.now)

        self.assertEqual(response["intent"], "capture_task")
        self.assertEqual(response["actions_taken"][0]["type"], "create_todoist_task")
        self.assertEqual(response["actions_taken"][0]["task"]["project_name"], "To-Do")
        self.assertEqual(response["actions_taken"][0]["task"]["section_name"], "Personal")
        self.assertNotIn("think about errands later", response["answer"])

    def test_exact_water_bottle_target_capture_infers_personal_from_memory_rule(self):
        created_task = {
            **TASKS[0],
            "id": "task-water-bottle",
            "content": "Buy water bottle from Target",
            "project_name": "To-Do",
            "section_name": "Personal",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="You could plan errands later.",
                intent="plan",
                action_type="none",
            ),
            None,
        )), patch("app.agent.create_task", return_value=TodoistWriteResult(task=created_task)) as create_task_mock:
            response = handle_chat("buy water bottle from Target", self.now)

        create_task_kwargs = create_task_mock.call_args.kwargs
        self.assertEqual(create_task_kwargs["project_name"], "To-Do")
        self.assertEqual(create_task_kwargs["section_name"], "Personal")
        self.assertEqual(response["actions_taken"][0]["task"]["project_category"], "Personal")

    def test_brandon_memory_hint_maps_meeting_to_nebulo_context(self):
        def fake_decision(settings, context):
            hints = context["memory_context"]["memory_hints"]
            self.assertIn(
                {
                    "match": "Brandon",
                    "type": "person",
                    "context": "Brandon: Associated with Nebulo. Project/category: Nebulo.",
                    "project_category": "Nebulo",
                },
                hints,
            )
            return (
                self._decision(
                    answer="I can put the Nebulo meeting on your calendar.",
                    intent="schedule_event",
                    action_type="create_calendar_event",
                    calendar_event={
                        "title": "Meeting with Brandon",
                        "start": "2026-06-04T18:00:00-05:00",
                        "end": "2026-06-04T19:00:00-05:00",
                    },
                ),
                None,
            )

        event = {
            "id": "event-brandon",
            "title": "Meeting with Brandon",
            "start": "2026-06-04T18:00:00-05:00",
            "end": "2026-06-04T19:00:00-05:00",
        }
        with patch("app.agent._get_llm_decision", side_effect=fake_decision), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=event),
        ) as create_event_mock:
            response = handle_chat("meeting with Brandon at 6", self.now)

        create_event_kwargs = create_event_mock.call_args.kwargs
        self.assertEqual(create_event_kwargs["title"], "Nebulo — Meeting with Brandon")
        self.assertIn("Brandon: Associated with Nebulo.", create_event_kwargs["description"])
        self.assertEqual(response["intent"], "schedule_event")
        self.assertIn("I recognized Brandon as Nebulo.", response["answer"])

    def test_ashwin_and_charlie_memory_hints_map_to_xo(self):
        def fake_decision(settings, context):
            hints = context["memory_context"]["memory_hints"]
            xo_matches = {
                hint["match"]
                for hint in hints
                if hint.get("project_category") == "XO"
            }
            self.assertEqual(xo_matches, {"Ashwin", "Charlie"})
            return (
                self._decision(
                    answer="That is XO context.",
                    intent="schedule_event",
                    action_type="none",
                ),
                None,
            )

        with patch("app.agent._get_llm_decision", side_effect=fake_decision):
            response = handle_chat("meet with Ashwin and Charlie", self.now)

        self.assertEqual(response["intent"], "schedule_event")

    def test_ashwin_and_charlie_meeting_prefixes_xo_event_title(self):
        event = {
            "id": "event-xo",
            "title": "XO — Meeting with Ashwin and Charlie",
            "start": "2026-06-05T16:00:00-05:00",
            "end": "2026-06-05T17:00:00-05:00",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can put that on your calendar.",
                intent="schedule_event",
                action_type="create_calendar_event",
                calendar_event={
                    "title": "Meeting with Ashwin and Charlie",
                    "start": "2026-06-05T16:00:00-05:00",
                    "end": "2026-06-05T17:00:00-05:00",
                    "description": None,
                },
            ),
            None,
        )), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=event),
        ) as create_event_mock:
            response = handle_chat("meet with Ashwin and Charlie tomorrow at 4", self.now)

        create_event_kwargs = create_event_mock.call_args.kwargs
        self.assertEqual(create_event_kwargs["title"], "XO — Meeting with Ashwin and Charlie")
        self.assertIn("Project context:", create_event_kwargs["description"])
        self.assertIn("XO", create_event_kwargs["description"])
        self.assertIn("I recognized this as XO.", response["answer"])

    def test_project_meeting_dual_writes_calendar_and_todoist(self):
        event = {
            "id": "event-xo",
            "title": "XO — Meeting with Ashwin and Charlie",
            "start": "2026-06-05T16:00:00-05:00",
            "end": "2026-06-05T17:00:00-05:00",
        }
        created_task = {
            **TASKS[0],
            "id": "task-xo-meeting",
            "content": "Meeting with Ashwin and Charlie",
            "section_name": "XO",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can add that.",
                intent="schedule_event",
                action_type="create_calendar_event",
                calendar_event={
                    "title": "Meeting with Ashwin and Charlie",
                    "start": "2026-06-05T16:00:00-05:00",
                    "end": "2026-06-05T17:00:00-05:00",
                    "description": None,
                },
            ),
            None,
        )), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=event),
        ), patch(
            "app.agent.create_task",
            return_value=TodoistWriteResult(task=created_task),
        ) as create_task_mock:
            response = handle_chat("meet with Ashwin and Charlie tomorrow at 4", self.now)

        create_task_kwargs = create_task_mock.call_args.kwargs
        self.assertEqual(create_task_kwargs["content"], "Meeting with Ashwin and Charlie")
        self.assertEqual(create_task_kwargs["section_name"], "XO")
        self.assertEqual(create_task_kwargs["due_string"], "2026-06-05")
        self.assertEqual([action["type"] for action in response["actions_taken"]], [
            "create_calendar_event",
            "create_todoist_task",
        ])
        self.assertIn("created a Todoist task under XO", response["answer"])

    def test_gym_schedule_is_calendar_only(self):
        event = {
            "id": "event-gym",
            "title": "Gym",
            "start": "2026-06-05T14:30:00-05:00",
            "end": "2026-06-05T15:30:00-05:00",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I added gym tomorrow.",
                intent="schedule_event",
                action_type="create_calendar_event",
                calendar_event={
                    "title": "Gym",
                    "start": "2026-06-05T14:30:00-05:00",
                    "end": "2026-06-05T15:30:00-05:00",
                    "description": None,
                },
            ),
            None,
        )), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=event),
        ), patch("app.agent.create_task") as create_task_mock:
            response = handle_chat("I want to go gym tomorrow at 2:30", self.now)

        create_task_mock.assert_not_called()
        self.assertEqual([action["type"] for action in response["actions_taken"]], ["create_calendar_event"])

    def test_today_meeting_does_not_affect_tomorrow_gym_scheduling(self):
        today_meeting = {
            "id": "event-today-xo",
            "title": "XO — Meeting with Ashwin and Charlie",
            "start": "2026-06-04T16:00:00-05:00",
            "end": "2026-06-04T17:00:00-05:00",
            "busy": True,
            "event_type": "hard",
        }
        tomorrow_gym = {
            "id": "event-gym",
            "title": "Gym",
            "start": "2026-06-05T14:30:00-05:00",
            "end": "2026-06-05T15:30:00-05:00",
        }

        def fake_decision(settings, context):
            self.assertEqual(context["calendar_events_today"][0]["title"], "XO — Meeting with Ashwin and Charlie")
            self.assertEqual(context["calendar_events_for_requested_date"], [])
            return (
                self._decision(
                    answer="I can put gym on your calendar.",
                    intent="schedule_event",
                    action_type="create_calendar_event",
                    calendar_event={
                        "title": "Gym",
                        "start": "2026-06-05T14:30:00-05:00",
                        "end": "2026-06-05T15:30:00-05:00",
                        "description": None,
                    },
                ),
                None,
            )

        with patch("app.agent.list_todays_events", return_value=CalendarReadResult(events=[today_meeting])), patch(
            "app.agent.list_upcoming_events",
            return_value=CalendarReadResult(events=[today_meeting]),
        ), patch("app.agent._get_llm_decision", side_effect=fake_decision), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=tomorrow_gym),
        ) as create_event_mock:
            response = handle_chat("I want to go gym tomorrow at 2:30", self.now)

        self.assertEqual(create_event_mock.call_args.kwargs["existing_events"], [])
        self.assertEqual(response["actions_taken"][0]["type"], "create_calendar_event")
        self.assertNotIn("Ashwin", response["answer"])

    def test_tomorrow_event_conflict_detection_still_uses_tomorrow_events(self):
        tomorrow_meeting = {
            "id": "event-tomorrow-meeting",
            "title": "Nebulo — Meeting with Brandon",
            "start": "2026-06-05T14:00:00-05:00",
            "end": "2026-06-05T15:00:00-05:00",
            "busy": True,
            "event_type": "hard",
        }

        def fake_decision(settings, context):
            self.assertEqual(
                context["calendar_events_for_requested_date"][0]["title"],
                "Nebulo — Meeting with Brandon",
            )
            return (
                self._decision(
                    answer="I can put gym on your calendar.",
                    intent="schedule_event",
                    action_type="create_calendar_event",
                    calendar_event={
                        "title": "Gym",
                        "start": "2026-06-05T14:30:00-05:00",
                        "end": "2026-06-05T15:30:00-05:00",
                        "description": None,
                    },
                ),
                None,
            )

        with patch("app.agent.list_upcoming_events", return_value=CalendarReadResult(events=[tomorrow_meeting])), patch(
            "app.agent._get_llm_decision",
            side_effect=fake_decision,
        ), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(error="Calendar event conflicts with existing event: Nebulo — Meeting with Brandon."),
        ) as create_event_mock:
            response = handle_chat("I want to go gym tomorrow at 2:30", self.now)

        self.assertEqual(create_event_mock.call_args.kwargs["existing_events"], [tomorrow_meeting])
        self.assertEqual(response["actions_taken"], [])
        self.assertIn("conflicts with existing event", response["errors"][0])

    def test_am_roommates_resolve_to_am_context(self):
        event = {
            "id": "event-roommates",
            "title": "A&M — Meeting with Nikhil, Andy, and Kamden",
            "start": "2026-06-04T18:00:00-05:00",
            "end": "2026-06-04T19:00:00-05:00",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can add that.",
                intent="schedule_event",
                action_type="create_calendar_event",
                calendar_event={
                    "title": "Meeting with Nikhil, Andy, and Kamden",
                    "start": "2026-06-04T18:00:00-05:00",
                    "end": "2026-06-04T19:00:00-05:00",
                    "description": None,
                },
            ),
            None,
        )), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=event),
        ) as create_event_mock:
            response = handle_chat("meeting with Nikhil, Andy, and Kamden at 6", self.now)

        self.assertEqual(create_event_mock.call_args.kwargs["title"], "A&M — Meeting with Nikhil, Andy, and Kamden")
        self.assertIn("I recognized this as A&M.", response["answer"])

    def test_carrollton_utd_group_resolves_to_personal_not_am(self):
        event = {
            "id": "event-carrollton",
            "title": "Personal — Meeting with Sam, Jai, and Krrish",
            "start": "2026-06-04T18:00:00-05:00",
            "end": "2026-06-04T19:00:00-05:00",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can add that.",
                intent="schedule_event",
                action_type="create_calendar_event",
                calendar_event={
                    "title": "Meeting with Sam, Jai, and Krrish",
                    "start": "2026-06-04T18:00:00-05:00",
                    "end": "2026-06-04T19:00:00-05:00",
                    "description": None,
                },
            ),
            None,
        )), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=event),
        ) as create_event_mock:
            response = handle_chat("meeting with Sam, Jai, and Krrish at 6", self.now)

        create_event_kwargs = create_event_mock.call_args.kwargs
        self.assertEqual(create_event_kwargs["title"], "Personal — Meeting with Sam, Jai, and Krrish")
        self.assertIn("Carrollton house / UTD", create_event_kwargs["description"])
        self.assertNotIn("A&M —", create_event_kwargs["title"])
        self.assertIn("I recognized this as Personal.", response["answer"])

    def test_no_memory_match_keeps_plain_event_title(self):
        event = {
            "id": "event-jordan",
            "title": "Meeting with Jordan",
            "start": "2026-06-04T18:00:00-05:00",
            "end": "2026-06-04T19:00:00-05:00",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can add that.",
                intent="schedule_event",
                action_type="create_calendar_event",
                calendar_event={
                    "title": "Meeting with Jordan",
                    "start": "2026-06-04T18:00:00-05:00",
                    "end": "2026-06-04T19:00:00-05:00",
                    "description": None,
                },
            ),
            None,
        )), patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=event),
        ) as create_event_mock:
            response = handle_chat("meeting with Jordan at 6", self.now)

        self.assertEqual(create_event_mock.call_args.kwargs["title"], "Meeting with Jordan")
        self.assertIsNone(create_event_mock.call_args.kwargs["description"])
        self.assertNotIn("I recognized", response["answer"])

    def test_resolved_project_routes_todoist_task_to_section(self):
        created_task = {
            **TASKS[0],
            "id": "task-brandon",
            "content": "Call Brandon",
            "section_name": "Nebulo",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can add that.",
                intent="capture_task",
                action_type="create_todoist_task",
                task={
                    "content": "Call Brandon",
                    "project_category": "Misc",
                    "due_string": None,
                    "due_date": None,
                    "labels": [],
                    "priority": 4,
                    "project_name": None,
                    "section_name": None,
                },
            ),
            None,
        )), patch("app.agent.create_task", return_value=TodoistWriteResult(task=created_task)) as create_task_mock:
            response = handle_chat("call Brandon", self.now)

        create_task_kwargs = create_task_mock.call_args.kwargs
        self.assertEqual(create_task_kwargs["section_name"], "Nebulo")
        self.assertEqual(response["actions_taken"][0]["task"]["project_category"], "Nebulo")
        self.assertEqual(response["actions_taken"][0]["task"]["resolved_project"], "Nebulo")
        self.assertIn("I recognized Brandon as Nebulo.", response["answer"])

    def test_disabled_memories_are_not_in_openai_context(self):
        def fake_decision(settings, context):
            memory_context = context["memory_context"]
            serialized = str(memory_context)
            self.assertNotIn("Disabled Person", serialized)
            self.assertNotIn("memory-disabled", serialized)
            return (
                self._decision(answer="I can help with that.", intent="question"),
                None,
            )

        with patch("app.agent._get_llm_decision", side_effect=fake_decision):
            response = handle_chat("Who is Disabled Person?", self.now)

        self.assertEqual(response["intent"], "question")

    def test_before_event_capture_sets_personal_section_and_due_date(self):
        created_task = {
            **TASKS[0],
            "id": "task-grad-speech",
            "content": "Prepare grad speech",
            "project_name": "To-Do",
            "section_name": "Personal",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="You should think about that later.",
                intent="plan",
                action_type="none",
            ),
            None,
        )), patch("app.agent.create_task", return_value=TodoistWriteResult(task=created_task)) as create_task_mock:
            response = handle_chat(
                "Prepare for my grad speech before my grad on saturday",
                self.now,
            )

        create_task_kwargs = create_task_mock.call_args.kwargs
        self.assertEqual(create_task_kwargs["content"], "Prepare grad speech")
        self.assertEqual(create_task_kwargs["project_id"], "project-todo")
        self.assertEqual(create_task_kwargs["project_name"], "To-Do")
        self.assertEqual(create_task_kwargs["section_name"], "Personal")
        self.assertEqual(create_task_kwargs["due_string"], "2026-06-05")
        self.assertEqual(create_task_kwargs["priority"], 4)
        self.assertEqual(response["actions_taken"][0]["task"]["project_category"], "Personal")
        self.assertEqual(response["actions_taken"][0]["task"]["due_date"], "2026-06-05")

    def test_task_extraction_classifies_life_area_examples(self):
        cases = [
            ("Buy groceries today", "Buy groceries", "Personal", "2026-06-04"),
            ("Study for college exam tomorrow", "Study for college exam", "A&M", "2026-06-05"),
            ("Draft freelance client proposal by friday", "Draft freelance client proposal", "Freelance", "2026-06-05"),
            ("Prepare XO prototype review next week", "Prepare XO prototype review", "XO", "2026-06-08"),
        ]

        for message, expected_content, expected_category, expected_due_date in cases:
            with self.subTest(message=message):
                metadata = agent._extract_capture_metadata(message, {}, self.now)

            self.assertEqual(metadata["content"], expected_content)
            self.assertEqual(metadata["project_category"], expected_category)
            self.assertEqual(metadata["due_date"], expected_due_date)

    def test_temporal_phrase_extraction(self):
        cases = [
            ("today", "2026-06-04"),
            ("tomorrow", "2026-06-05"),
            ("friday", "2026-06-05"),
            ("saturday", "2026-06-06"),
            ("next week", "2026-06-08"),
        ]

        for phrase, expected_due_date in cases:
            with self.subTest(phrase=phrase):
                due_date = agent._extract_due_date_from_message(
                    f"Finish paperwork {phrase}",
                    self.now,
                )

            self.assertEqual(due_date.isoformat(), expected_due_date)

    def test_todoist_create_task_resolves_project_and_section_names(self):
        response = requests.Response()
        response.status_code = 200
        response._content = (
            b'{"id":"task-grad-speech","content":"Prepare grad speech",'
            b'"project_id":"project-todo","section_id":"section-personal",'
            b'"priority":4,"labels":[]}'
        )

        with patch("app.todoist_tools._fetch_projects", return_value={"project-todo": "To-Do"}), patch(
            "app.todoist_tools._fetch_sections",
            return_value={"section-personal": "Personal"},
        ), patch("app.todoist_tools.requests.post", return_value=response) as post_mock:
            result = create_task(
                settings=FakeSettings(),
                content="Prepare grad speech",
                project_name="To-Do",
                section_name="Personal",
                due_string="2026-06-05",
                priority=4,
            )

        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["project_id"], "project-todo")
        self.assertEqual(payload["section_id"], "section-personal")
        self.assertEqual(payload["due_string"], "2026-06-05")
        self.assertEqual(payload["priority"], 4)
        self.assertIsNone(result.error)
        self.assertEqual(result.task["project_name"], "To-Do")
        self.assertEqual(result.task["section_name"], "Personal")

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
        self.assertEqual(response["actions_taken"][1]["type"], "create_todoist_task")
        self.assertIn("created a Todoist task under Nebulo", response["answer"])

    def test_affirmative_reply_executes_pending_calendar_event(self):
        created_event = {
            "id": "event-brandon",
            "title": "Meeting with Brandon",
            "start": "2026-06-05T18:00:00-05:00",
            "end": "2026-06-05T19:00:00-05:00",
            "duration_minutes": 60,
            "all_day": False,
            "busy": True,
            "event_type": "hard",
            "event_category": "hard",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can add that, but it overlaps with gym. Add it anyway?",
                intent="schedule_event",
                action_type="create_calendar_event",
                calendar_event={
                    "title": "Meeting with Brandon",
                    "start": "2026-06-05T18:00:00-05:00",
                    "end": "2026-06-05T19:00:00-05:00",
                },
                needs_confirmation=True,
                confirmation_prompt="Add it anyway?",
            ),
            None,
        )):
            first_response = handle_chat("Meeting with Brandon tomorrow at 6 for an hour", self.now)

        self.assertTrue(first_response["needs_confirmation"])
        self.assertEqual(agent.PENDING_ACTION["type"], "create_calendar_event")

        with patch("app.agent._get_llm_decision") as llm_mock, patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=created_event),
        ) as create_event_mock:
            second_response = handle_chat("yes please", self.now)

        llm_mock.assert_not_called()
        self.assertFalse(second_response["needs_confirmation"])
        self.assertIsNone(second_response["pending_action"])
        self.assertIsNone(agent.PENDING_ACTION)
        self.assertEqual(second_response["actions_taken"][0]["type"], "create_calendar_event")
        self.assertTrue(create_event_mock.call_args.kwargs["allow_conflicts"])

    def test_schema_allowed_actions_are_documented(self):
        schema = _decision_schema()
        action_enum = schema["properties"]["action_type"]["enum"]
        self.assertEqual(action_enum, ["none", "create_todoist_task", "create_calendar_event"])
        self.assertIn("pending_action", schema["required"])
        self.assertEqual(
            schema["properties"]["pending_action"]["properties"]["type"]["enum"],
            ["resolve_calendar_conflict"],
        )

    def test_structured_output_schema_objects_are_strict(self):
        def check_object(node):
            if isinstance(node, dict):
                if node.get("type") == "object" or (
                    isinstance(node.get("type"), list) and "object" in node["type"]
                ):
                    self.assertIn("additionalProperties", node)
                    self.assertFalse(node["additionalProperties"])
                for value in node.values():
                    check_object(value)
            elif isinstance(node, list):
                for value in node:
                    check_object(value)

        check_object(_decision_schema())

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
        self.assertEqual(response["pending_action"]["type"], pending_action["type"])
        self.assertEqual(response["pending_action"]["details"], pending_action["details"])
        self.assertEqual(response["pending_action"]["resolved_project"], "Nebulo")
        self.assertEqual(agent.PENDING_ACTION, response["pending_action"])
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

    def test_api_auth_missing_returns_401(self):
        with patch("app.main.get_settings", return_value=FakeSettings()):
            with self.assertRaises(HTTPException) as exc:
                require_agent_api_key(None)

        self.assertEqual(exc.exception.status_code, 401)

    def test_api_auth_valid_allows_chat(self):
        with patch("app.main.get_settings", return_value=FakeSettings()):
            require_agent_api_key("Bearer test-agent-key")

            with patch("app.agent._get_llm_decision", return_value=(
                self._decision(answer="Start with the Notion migration.", intent="plan"),
                None,
            )):
                response = chat(
                    ChatRequest(message="What should I work on right now?"),
                    authorization="Bearer test-agent-key",
                )

        self.assertEqual(response["intent"], "plan")

    def _decision(
        self,
        answer,
        intent,
        action_type="none",
        task=None,
        calendar_event=None,
        resolved_project=None,
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
                "due_date": None,
                "labels": [],
                "priority": None,
                "project_name": None,
                "section_name": None,
            },
            "calendar_event": calendar_event or {
                "title": None,
                "start": None,
                "end": None,
                "description": None,
            },
            "resolved_project": resolved_project,
            "needs_confirmation": needs_confirmation,
            "confirmation_prompt": confirmation_prompt,
            "pending_action": pending_action,
        }


if __name__ == "__main__":
    unittest.main()
