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
from app.agent import _decision_schema, _sanitize_decision, confirm_pending_action, handle_chat  # noqa: E402
from app.calendar_tools import CalendarReadResult, CalendarWriteResult  # noqa: E402
from app.main import ChatRequest, chat, require_agent_api_key  # noqa: E402
from app.project_chat_grounding import ProjectChatGrounding, ProjectQuestionKind  # noqa: E402
from app.todoist_tools import (  # noqa: E402
    TodoistReadResult,
    TodoistSectionResult,
    TodoistWriteResult,
    TodoistBulkWriteResult,
    create_task,
    create_many_subtasks,
    create_subtask,
    find_task_by_name,
    list_todoist_sections,
)


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

ROADMAP_PARENT_TASK = {
    "id": "task-roadmap-parent",
    "content": "ai todoist agent",
    "project_id": "project-todo",
    "project_name": "To-Do",
    "section_id": "section-personal",
    "section_name": "Personal",
    "parent_id": None,
    "due": None,
    "priority": 2,
    "todoist_priority": 3,
    "labels": [],
    "url": "https://app.todoist.com/app/task/task-roadmap-parent",
}

ROADMAP_CHILD_TASK = {
    "id": "task-roadmap-child",
    "content": "Fix confirmation execution",
    "project_id": "project-todo",
    "project_name": "To-Do",
    "section_id": "section-personal",
    "section_name": "Personal",
    "parent_id": "task-roadmap-parent",
    "due": None,
    "priority": 2,
    "todoist_priority": 3,
    "labels": [],
    "url": "https://app.todoist.com/app/task/task-roadmap-child",
}

NEBULO_DEMO_PARENT_TASK = {
    "id": "task-nebulo-demo-1",
    "content": "Demo 1",
    "project_id": "project-todo",
    "project_name": "To-Do",
    "section_id": "section-nebulo",
    "section_name": "Nebulo",
    "parent_id": None,
    "due": None,
    "priority": 2,
    "todoist_priority": 3,
    "labels": [],
    "url": "https://app.todoist.com/app/task/task-nebulo-demo-1",
}

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

TODOIST_SECTIONS = [
    {"id": "section-am", "name": "A&M"},
    {"id": "section-xo", "name": "XO Collective"},
    {"id": "section-freelance", "name": "Freelance Web Design"},
    {"id": "section-nebulo", "name": "Nebulo"},
    {"id": "section-personal", "name": "Personal"},
    {"id": "section-misc", "name": "Misc"},
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
        agent.CONVERSATION_STATES.clear()
        self.addCleanup(self._clear_pending_action)
        self.now = datetime(2026, 6, 4, 14, 0, tzinfo=ZoneInfo("America/Chicago"))
        self.base_patches = [
            patch("app.agent.get_settings", return_value=FakeSettings()),
            patch("app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=TASKS)),
            patch("app.agent.list_todoist_sections", return_value=TodoistSectionResult(sections=TODOIST_SECTIONS)),
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
        agent.CONVERSATION_STATES.clear()

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

    def test_project_question_uses_deterministic_grounding_without_openai(self):
        settings = FakeSettings(openai_api_key=None)
        grounding = ProjectChatGrounding(
            answer="XO: Start SID-129 from Linear.",
            question_kind=ProjectQuestionKind.NEXT_MOVE,
            canonical_project_key="xo",
            evidence=({"next_recommendation": "Start SID-129 from Linear."},),
        )
        with patch("app.agent.get_settings", return_value=settings), patch.object(
            agent.project_chat_grounding_service,
            "ground",
            return_value=grounding,
        ) as ground_mock, patch("app.agent._get_llm_decision") as llm_mock:
            response = handle_chat("What should I work on next for XO?", self.now, session_id="project-chat")

        self.assertEqual(response["answer"], grounding.answer)
        self.assertEqual(response["intent"], "question")
        self.assertEqual(response["actions_taken"], [])
        self.assertFalse(response["needs_confirmation"])
        self.assertEqual(response["conversation_state"]["context"]["canonical_project_key"], "xo")
        ground_mock.assert_called_once()
        llm_mock.assert_not_called()

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

    def test_exact_water_bottle_target_capture_infers_personal_from_rule(self):
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
        self.assertEqual(create_task_kwargs["section_id"], "section-personal")
        self.assertEqual(response["actions_taken"][0]["task"]["project_category"], "Personal")
        self.assertEqual(response["actions_taken"][0]["task"]["todoist_section_id"], "section-personal")

    def test_roadmap_under_parent_requests_bulk_subtask_confirmation(self):
        roadmap_tasks = [*TASKS, ROADMAP_PARENT_TASK]
        message = """Take this roadmap and add it under Personal -> ai todoist agent as subtasks:
- Fix confirmation execution
- Calendar Intelligence V1
- Project Workspaces
- Package as Mac app"""
        with patch("app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=roadmap_tasks)), patch(
            "app.agent.find_task_by_name", return_value=ROADMAP_PARENT_TASK
        ):
            response = handle_chat(message, self.now)

        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["pending_action"]["type"], "create_many_todoist_subtasks")
        self.assertEqual(response["pending_action"]["details"]["project_name"], "To-Do")
        self.assertEqual(response["pending_action"]["details"]["section_name"], "Personal")
        self.assertEqual(response["pending_action"]["details"]["parent_task_title"], "ai todoist agent")
        self.assertEqual(response["pending_action"]["details"]["parent_task_id"], "task-roadmap-parent")
        self.assertEqual(len(response["pending_action"]["details"]["tasks"]), 4)

    def test_numbered_roadmap_under_nebulo_parent_requests_bulk_subtask_confirmation(self):
        roadmap_tasks = [*TASKS, NEBULO_DEMO_PARENT_TASK]
        message = """Add these under Nebulo -> Demo 1 as subtasks:
1. Merge/verify provider extraction
2. Implement Google Drive read-only provider
3. Mount Drive into existing storage API
4. Add basic Nebulo Search indexing
5. Update Nebulo Search app
6. Update Claude/MCP access
7. Phone result view
8. Demo polish"""
        with patch("app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=roadmap_tasks)), patch(
            "app.agent.find_task_by_name", return_value=NEBULO_DEMO_PARENT_TASK
        ), patch("app.agent.create_task") as create_task_mock, self.assertLogs("app.agent", level="INFO") as logs:
            response = handle_chat(message, self.now)

        create_task_mock.assert_not_called()
        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["pending_action"]["type"], "create_many_todoist_subtasks")
        self.assertEqual(response["pending_action"]["details"]["section_name"], "Nebulo")
        self.assertEqual(response["pending_action"]["details"]["parent_task_title"], "Demo 1")
        self.assertEqual(response["pending_action"]["details"]["parent_task_id"], "task-nebulo-demo-1")
        self.assertEqual(len(response["pending_action"]["details"]["tasks"]), 8)
        self.assertEqual(
            response["pending_action"]["details"]["tasks"][0]["content"],
            "Merge/verify provider extraction",
        )
        self.assertTrue(
            any("bulk_subtask_confirmation_ready" in log and "create_many_todoist_subtasks" in log for log in logs.output)
        )

    def test_natural_roadmap_parser_supported_parent_formats(self):
        cases = [
            (
                "Add these under Nebulo -> Demo 1:\n1.\tMerge/verify provider extraction\n2.\tDemo polish",
                "Nebulo",
                "Demo 1",
            ),
            (
                "Put these in Demo 1:\n- Merge/verify provider extraction\n- Demo polish",
                None,
                "Demo 1",
            ),
            (
                "These are subtasks for Demo 1:\n- Merge/verify provider extraction\n- Demo polish",
                None,
                "Demo 1",
            ),
            (
                "Here's the roadmap for Demo 1:\n- Merge/verify provider extraction\n- Demo polish",
                None,
                "Demo 1",
            ),
            (
                "Create these under Personal -> ai todoist agent:\n- Fix confirmation execution\n- Calendar Intelligence V1",
                "Personal",
                "ai todoist agent",
            ),
            (
                "Add these under Nebulo / Demo 1:\n- Merge/verify provider extraction\n- Demo polish",
                "Nebulo",
                "Demo 1",
            ),
            (
                "Add these inside Demo 1:\n- Merge/verify provider extraction\n- Demo polish",
                None,
                "Demo 1",
            ),
        ]

        for message, section_name, parent_title in cases:
            with self.subTest(message=message):
                parsed, reason, attempted = agent._parse_bulk_subtask_request(message)

            self.assertTrue(attempted)
            self.assertEqual(reason, "parsed")
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["section_name"], section_name)
            self.assertEqual(parsed["parent_task_title"], parent_title)
            self.assertEqual(len(parsed["tasks"]), 2)

    def test_natural_roadmap_parser_supported_list_markers(self):
        message = """Add these under Nebulo -> Demo 1:
- [ ] Merge/verify provider extraction

* Implement Google Drive read-only provider
+ Mount Drive into existing storage API
1) Add basic Nebulo Search indexing
\uFFFC Update Nebulo Search app"""

        parsed, reason, attempted = agent._parse_bulk_subtask_request(message)

        self.assertTrue(attempted)
        self.assertEqual(reason, "parsed")
        self.assertEqual(parsed["parent_task_title"], "Demo 1")
        self.assertEqual(
            [task["content"] for task in parsed["tasks"]],
            [
                "Merge/verify provider extraction",
                "Implement Google Drive read-only provider",
                "Mount Drive into existing storage API",
                "Add basic Nebulo Search indexing",
                "Update Nebulo Search app",
            ],
        )

    def test_roadmap_with_multiple_items_but_no_parent_asks_clarification_without_create_task(self):
        message = """Break this into subtasks:
- Merge/verify provider extraction
- Demo polish"""
        with patch("app.agent.create_task") as create_task_mock, patch(
            "app.agent._get_llm_decision"
        ) as llm_mock, self.assertLogs("app.agent", level="INFO") as logs:
            response = handle_chat(message, self.now)

        create_task_mock.assert_not_called()
        llm_mock.assert_not_called()
        self.assertFalse(response["needs_confirmation"])
        self.assertIsNone(response["pending_action"])
        self.assertIn("Which parent Todoist task", response["answer"])
        self.assertTrue(any("selected_action=clarify_parent_task" in log for log in logs.output))

    def test_parent_only_roadmap_resolves_section_from_todoist_parent_task(self):
        roadmap_tasks = [*TASKS, NEBULO_DEMO_PARENT_TASK]
        message = """Put these in Demo 1:
- Merge/verify provider extraction
- Demo polish"""
        with patch("app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=roadmap_tasks)), patch(
            "app.agent.find_task_by_name", return_value=NEBULO_DEMO_PARENT_TASK
        ):
            response = handle_chat(message, self.now)

        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["pending_action"]["type"], "create_many_todoist_subtasks")
        self.assertEqual(response["pending_action"]["details"]["section_name"], "Nebulo")
        self.assertEqual(response["pending_action"]["details"]["parent_task_title"], "Demo 1")

    def test_roadmap_parser_logs_failure_reason_before_fallback(self):
        plan = {"free_block": None, "recommended_tasks": []}
        with self.assertLogs("app.agent", level="INFO") as logs:
            response = agent._build_bulk_subtask_confirmation(
                message="Add these under Nebulo -> Demo 1 as subtasks:",
                settings=FakeSettings(),
                tasks=[],
                plan=plan,
                calendar_events=[],
                errors=[],
                session_key="test-session",
            )

        self.assertIsNone(response)
        self.assertTrue(any("no_numbered_or_bulleted_items_found" in log for log in logs.output))
        self.assertTrue(any("selected_action=fallback" in log for log in logs.output))

    def test_bulk_subtask_confirmation_creates_multiple_subtasks(self):
        pending_action = {
            "type": "create_many_todoist_subtasks",
            "action_type": "create_many_todoist_subtasks",
            "intent": "capture_task",
            "details": {
                "project_name": "To-Do",
                "section_name": "Personal",
                "parent_task_title": "ai todoist agent",
                "parent_task_id": "task-roadmap-parent",
                "tasks": [
                    {"content": "Calendar Intelligence V1", "priority": 3},
                    {"content": "Project Workspaces", "priority": 3},
                ],
            },
        }
        created = [
            {**ROADMAP_CHILD_TASK, "id": "task-calendar", "content": "Calendar Intelligence V1"},
            {**ROADMAP_CHILD_TASK, "id": "task-workspaces", "content": "Project Workspaces"},
        ]
        with patch("app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=[*TASKS, ROADMAP_PARENT_TASK])), patch(
            "app.agent.create_many_subtasks",
            return_value=TodoistBulkWriteResult(tasks=created, skipped=[]),
        ) as create_many_subtasks_mock:
            response = confirm_pending_action(pending_action, self.now)

        create_many_subtasks_mock.assert_called_once()
        self.assertEqual(response["actions_taken"][0]["type"], "create_many_todoist_subtasks")
        self.assertEqual(response["actions_taken"][0]["task_count"], 2)
        self.assertEqual(response["answer"], "Created 2 subtasks under ai todoist agent.")

    def test_bulk_subtask_confirmation_reports_duplicate_skips(self):
        pending_action = {
            "type": "create_many_todoist_subtasks",
            "action_type": "create_many_todoist_subtasks",
            "intent": "capture_task",
            "details": {
                "project_name": "To-Do",
                "section_name": "Personal",
                "parent_task_title": "ai todoist agent",
                "parent_task_id": "task-roadmap-parent",
                "tasks": [
                    {"content": "Fix confirmation execution", "priority": 3},
                    {"content": "Calendar Intelligence V1", "priority": 3},
                ],
            },
        }
        created = [{**ROADMAP_CHILD_TASK, "id": "task-calendar", "content": "Calendar Intelligence V1"}]
        with patch("app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=[*TASKS, ROADMAP_PARENT_TASK, ROADMAP_CHILD_TASK])), patch(
            "app.agent.create_many_subtasks",
            return_value=TodoistBulkWriteResult(
                tasks=created,
                skipped=[{"content": "Fix confirmation execution", "reason": "duplicate"}],
            ),
        ):
            response = confirm_pending_action(pending_action, self.now)

        self.assertEqual(response["actions_taken"][0]["task_count"], 1)
        self.assertEqual(len(response["actions_taken"][0]["skipped"]), 1)
        self.assertIn("Skipped 1 duplicate", response["answer"])

    def test_missing_parent_asks_to_create_parent_first(self):
        message = """Take this roadmap and add it under Personal -> ai todoist agent as subtasks:
- Fix confirmation execution
- Calendar Intelligence V1"""
        with patch("app.agent.find_task_by_name", return_value=None):
            response = handle_chat(message, self.now)

        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["pending_action"]["type"], "create_todoist_task")
        self.assertEqual(response["pending_action"]["task"]["content"], "ai todoist agent")
        self.assertIn("Create that parent task first", response["answer"])

    def test_find_parent_task_in_personal_section(self):
        with patch("app.todoist_tools.list_active_tasks", return_value=TodoistReadResult(tasks=[ROADMAP_PARENT_TASK])):
            task = find_task_by_name(FakeSettings(), "AI TODOIST AGENT", section_name="Personal")

        self.assertIsNotNone(task)
        self.assertEqual(task["id"], "task-roadmap-parent")

    def test_create_one_subtask_under_parent(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "id": "task-subtask",
                    "content": "Calendar Intelligence V1",
                    "project_id": "project-todo",
                    "section_id": "section-personal",
                    "parent_id": "task-roadmap-parent",
                    "priority": 3,
                    "labels": [],
                }

        with patch("app.todoist_tools._fetch_projects", return_value={"project-todo": "To-Do"}), patch(
            "app.todoist_tools._fetch_sections", return_value={"section-personal": "Personal"}
        ), patch("app.todoist_tools.requests.post", return_value=FakeResponse()) as post_mock:
            result = create_subtask(
                settings=FakeSettings(),
                parent_id="task-roadmap-parent",
                content="Calendar Intelligence V1",
                priority=3,
            )

        self.assertIsNone(result.error)
        self.assertEqual(result.task["parent_id"], "task-roadmap-parent")
        self.assertEqual(post_mock.call_args.kwargs["json"]["parent_id"], "task-roadmap-parent")

    def test_create_many_subtasks_skips_duplicate_title_under_parent(self):
        with patch(
            "app.todoist_tools.create_subtask",
            return_value=TodoistWriteResult(
                task={**ROADMAP_CHILD_TASK, "id": "task-calendar", "content": "Calendar Intelligence V1"}
            ),
        ) as create_subtask_mock:
            result = create_many_subtasks(
                settings=FakeSettings(),
                parent_id="task-roadmap-parent",
                tasks=[
                    {"content": "Fix confirmation execution", "priority": 3},
                    {"content": "Calendar Intelligence V1", "priority": 3},
                ],
                existing_tasks=[ROADMAP_CHILD_TASK],
            )

        self.assertEqual(len(result.tasks), 1)
        self.assertEqual(result.skipped, [{"content": "Fix confirmation execution", "reason": "duplicate"}])
        create_subtask_mock.assert_called_once()

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
            "section_name": "XO Collective",
            "todoist_section_name": "XO Collective",
            "todoist_section_id": "section-xo",
            "classification_source": "memory",
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
        self.assertEqual(create_task_kwargs["section_name"], "XO Collective")
        self.assertEqual(create_task_kwargs["section_id"], "section-xo")
        self.assertEqual(create_task_kwargs["due_string"], "2026-06-05")
        self.assertEqual([action["type"] for action in response["actions_taken"]], [
            "create_calendar_event",
            "create_todoist_task",
        ])
        self.assertIn("created a Todoist task under XO Collective", response["answer"])

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

    def test_exact_interview_event_found_uses_calendar_details(self):
        interview = {
            "id": "event-interview",
            "title": "Shake Shack Interview",
            "start": "2026-06-05T14:00:00-05:00",
            "end": "2026-06-05T14:30:00-05:00",
            "duration_minutes": 30,
            "all_day": False,
            "busy": True,
            "event_type": "hard",
            "event_category": "hard",
        }

        with patch("app.agent.list_upcoming_events", return_value=CalendarReadResult(events=[interview])), patch(
            "app.agent._get_llm_decision"
        ) as llm_mock:
            response = handle_chat(
                "Do I need to wake up early for my interview tomorrow?",
                self.now,
                session_id="interview-session",
            )

        llm_mock.assert_not_called()
        self.assertIn("Shake Shack Interview", response["answer"])
        self.assertIn("2:00 PM", response["answer"])
        self.assertIn("2:30 PM", response["answer"])
        self.assertIn("11:00 AM", response["answer"])
        self.assertIn("You probably don't need to wake up extremely early", response["answer"])
        self.assertNotIn("check your schedule", response["answer"].lower())
        self.assertIsNone(response["conversation_state"]["awaiting"])

    def test_multiple_interviews_lists_matches_and_asks_which_one(self):
        interviews = [
            {
                "id": "event-first",
                "title": "Shake Shack Interview",
                "start": "2026-06-05T14:00:00-05:00",
                "end": "2026-06-05T14:30:00-05:00",
                "duration_minutes": 30,
                "all_day": False,
                "busy": True,
                "event_type": "hard",
                "event_category": "hard",
            },
            {
                "id": "event-second",
                "title": "Recruiter Interview",
                "start": "2026-06-05T16:00:00-05:00",
                "end": "2026-06-05T16:30:00-05:00",
                "duration_minutes": 30,
                "all_day": False,
                "busy": True,
                "event_type": "hard",
                "event_category": "hard",
            },
        ]

        with patch("app.agent.list_upcoming_events", return_value=CalendarReadResult(events=interviews)), patch(
            "app.agent._get_llm_decision"
        ) as llm_mock:
            response = handle_chat(
                "Do I need to wake up early for my interview tomorrow?",
                self.now,
                session_id="multiple-interviews",
            )

        llm_mock.assert_not_called()
        self.assertIn("multiple interview events", response["answer"])
        self.assertIn("Shake Shack Interview", response["answer"])
        self.assertIn("Recruiter Interview", response["answer"])
        self.assertIn("Which one do you mean?", response["answer"])
        self.assertEqual(response["conversation_state"]["awaiting"], "event_detail")

    def test_no_interview_found_asks_for_event_details(self):
        with patch("app.agent._get_llm_decision") as llm_mock:
            response = handle_chat(
                "Do I need to wake up early for my interview tomorrow?",
                self.now,
                session_id="no-interview",
            )

        llm_mock.assert_not_called()
        self.assertIn("I could not find an interview tomorrow", response["answer"])
        self.assertIn("What time is it?", response["answer"])
        self.assertEqual(response["conversation_state"]["awaiting"], "event_detail")

    def test_time_after_no_interview_found_is_used_as_event_detail(self):
        handle_chat(
            "Do I need to wake up early for my interview tomorrow?",
            self.now,
            session_id="interview-time",
        )

        with patch("app.agent._get_llm_decision") as llm_mock:
            response = handle_chat("6pm", self.now, session_id="interview-time")

        llm_mock.assert_not_called()
        self.assertIn("6:00 PM", response["answer"])
        self.assertIn("You probably don't need to wake up extremely early", response["answer"])
        self.assertNotIn("Your your interview", response["answer"])
        self.assertIsNone(response["conversation_state"]["awaiting"])

    def test_vague_yes_after_calendar_lookup_question_searches_calendar(self):
        interview = {
            "id": "event-interview",
            "title": "Shake Shack Interview",
            "start": "2026-06-05T14:00:00-05:00",
            "end": "2026-06-05T14:30:00-05:00",
            "duration_minutes": 30,
            "all_day": False,
            "busy": True,
            "event_type": "hard",
            "event_category": "hard",
        }
        agent.CONVERSATION_STATES["calendar-yes"] = {
            "last_question": "Do you have that in your calendar?",
            "awaiting": "calendar_lookup_confirmation",
            "context": {
                "kind": "interview",
                "target_date": "2026-06-05",
                "search_terms": ["interview", "recruiter", "hiring", "career", "phone screen"],
                "is_interview_wakeup": True,
            },
        }

        with patch("app.agent.list_upcoming_events", return_value=CalendarReadResult(events=[interview])), patch(
            "app.agent._get_llm_decision"
        ) as llm_mock:
            response = handle_chat("yes", self.now, session_id="calendar-yes")

        llm_mock.assert_not_called()
        self.assertIn("Shake Shack Interview", response["answer"])
        self.assertIn("2:00 PM", response["answer"])
        self.assertIsNone(response["conversation_state"]["awaiting"])

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

    def test_tomorrow_event_conflict_detection_requests_confirmation_before_write(self):
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
        ) as create_event_mock:
            response = handle_chat("I want to go gym tomorrow at 2:30", self.now)

        create_event_mock.assert_not_called()
        self.assertEqual(response["actions_taken"], [])
        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["pending_action"]["type"], "create_calendar_event")
        self.assertEqual(response["pending_action"]["calendar_event"]["start"], "2026-06-05T15:30:00-05:00")
        self.assertIn("Recommended: move Gym", response["answer"])

    def test_new_hard_event_overlapping_flexible_event_suggests_update_pending_action(self):
        tomorrow_gym = {
            "id": "event-gym",
            "title": "Gym",
            "start": "2026-06-05T14:15:00-05:00",
            "end": "2026-06-05T15:15:00-05:00",
            "busy": True,
            "event_type": "flexible",
            "event_category": "flexible",
        }

        with patch("app.agent.list_upcoming_events", return_value=CalendarReadResult(events=[tomorrow_gym])), patch(
            "app.agent._get_llm_decision",
            return_value=(
                self._decision(
                    answer="I can put that on your calendar.",
                    intent="schedule_event",
                    action_type="create_calendar_event",
                    calendar_event={
                        "title": "Client meeting",
                        "start": "2026-06-05T14:00:00-05:00",
                        "end": "2026-06-05T14:30:00-05:00",
                        "description": None,
                    },
                ),
                None,
            ),
        ), patch("app.agent.create_calendar_event") as create_event_mock:
            response = handle_chat("Schedule a client meeting tomorrow at 2", self.now)

        create_event_mock.assert_not_called()
        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["pending_action"]["type"], "update_calendar_event")
        self.assertEqual(response["pending_action"]["details"]["event_id"], "event-gym")
        self.assertEqual(response["pending_action"]["details"]["new_start"], "2026-06-05T15:00:00-05:00")
        self.assertIn("This overlaps with Gym", response["answer"])

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
            "todoist_section_name": "Nebulo",
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
        self.assertEqual(create_task_kwargs["section_id"], "section-nebulo")
        self.assertEqual(response["actions_taken"][0]["task"]["project_category"], "Nebulo")
        self.assertEqual(response["actions_taken"][0]["task"]["resolved_project"], "Nebulo")
        self.assertEqual(response["actions_taken"][0]["task"]["classification_source"], "memory")
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
        self.assertEqual(create_task_kwargs["section_id"], "section-personal")
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

    def test_todoist_task_extraction_strips_command_section_and_date_phrases(self):
        cases = [
            (
                "add a todoist task cancel apple news+ free trial for sep 20th",
                "Cancel Apple News+ free trial",
                "Personal",
                "2026-09-20",
            ),
            (
                "add task cancel walmart+ by Wednesday",
                "Cancel Walmart+",
                "Personal",
                "2026-06-10",
            ),
            (
                "put cancel apple news in misc due sep 20",
                "Cancel apple news",
                "Misc",
                "2026-09-20",
            ),
            (
                "add task buy water bottle from Target",
                "Buy water bottle from Target",
                "Personal",
                None,
            ),
            (
                "add task contact dentist website lead in Freelance",
                "Contact dentist website lead",
                "Freelance",
                None,
            ),
        ]

        for message, expected_content, expected_category, expected_due_date in cases:
            with self.subTest(message=message):
                metadata = agent._extract_capture_metadata(message, {}, self.now)

            self.assertEqual(metadata["content"], expected_content)
            self.assertEqual(metadata["project_category"], expected_category)
            self.assertEqual(metadata["section_name"], agent.LIFE_AREA_TO_TODOIST_SECTION[expected_category])
            self.assertEqual(metadata["due_date"], expected_due_date)

    def test_todoist_task_creation_uses_clean_content_section_alias_and_due_date(self):
        created_task = {
            **TASKS[0],
            "id": "task-cancel-apple-news",
            "content": "Cancel Apple News+ free trial",
            "project_name": "To-Do",
            "section_name": "Personal",
        }
        with patch("app.agent._get_llm_decision", return_value=(
            self._decision(
                answer="I can add that.",
                intent="plan",
                action_type="none",
            ),
            None,
        )), patch("app.agent.create_task", return_value=TodoistWriteResult(task=created_task)) as create_task_mock:
            response = handle_chat(
                "add a todoist task cancel apple news+ free trial for sep 20th",
                self.now,
            )

        create_task_kwargs = create_task_mock.call_args.kwargs
        self.assertEqual(create_task_kwargs["content"], "Cancel Apple News+ free trial")
        self.assertEqual(create_task_kwargs["section_name"], "Personal")
        self.assertEqual(create_task_kwargs["section_id"], "section-personal")
        self.assertEqual(create_task_kwargs["due_string"], "2026-09-20")
        self.assertNotIn("todoist task", response["actions_taken"][0]["task"]["content"].lower())
        self.assertNotIn("sep 20", response["actions_taken"][0]["task"]["content"].lower())

    def test_section_alias_resolution_maps_user_aliases_to_real_todoist_sections(self):
        cases = [
            ("Miscellaneous", "Misc"),
            ("Other", "Misc"),
            ("Uncategorized", "Misc"),
            ("life admin", "Personal"),
            ("errands", "Personal"),
            ("shopping", "Personal"),
            ("XO", "XO Collective"),
            ("Freelance", "Freelance Web Design"),
            ("TAMU", "A&M"),
            ("college", "A&M"),
        ]

        from app.todoist_tools import canonical_todoist_section_name

        for alias, expected_section in cases:
            with self.subTest(alias=alias):
                self.assertEqual(canonical_todoist_section_name(alias), expected_section)

    def test_task_creation_uses_real_todoist_sections(self):
        cases = [
            ("call Ashwin and Charlie", "XO Collective", "section-xo", "XO", "memory"),
            ("call Brandon", "Nebulo", "section-nebulo", "Nebulo", "memory"),
            ("send client outreach email", "Freelance Web Design", "section-freelance", "Freelance", "rule"),
            ("buy water bottle", "Personal", "section-personal", "Personal", "rule"),
            ("add mysterious follow up", "Misc", "section-misc", "Misc", "fallback"),
        ]

        for message, expected_section, expected_section_id, expected_category, expected_source in cases:
            with self.subTest(message=message):
                created_task = {
                    **TASKS[0],
                    "id": f"task-{expected_category.lower()}",
                    "content": message,
                    "section_name": expected_section,
                    "todoist_section_name": expected_section,
                    "todoist_section_id": expected_section_id,
                    "classification_source": expected_source,
                }
                with patch("app.agent._get_llm_decision", return_value=(
                    self._decision(
                        answer="I can add that.",
                        intent="plan",
                        action_type="none",
                    ),
                    None,
                )), patch(
                    "app.agent.create_task",
                    return_value=TodoistWriteResult(task=created_task),
                ) as create_task_mock:
                    response = handle_chat(message, self.now)

                create_task_kwargs = create_task_mock.call_args.kwargs
                self.assertEqual(create_task_kwargs["project_name"], "To-Do")
                self.assertEqual(create_task_kwargs["section_name"], expected_section)
                self.assertEqual(create_task_kwargs["section_id"], expected_section_id)
                self.assertEqual(response["actions_taken"][0]["task"]["project_category"], expected_category)
                self.assertEqual(response["actions_taken"][0]["task"]["resolved_project"], expected_category)
                self.assertEqual(response["actions_taken"][0]["task"]["todoist_section_name"], expected_section)
                self.assertEqual(response["actions_taken"][0]["task"]["todoist_section_id"], expected_section_id)
                self.assertEqual(response["actions_taken"][0]["task"]["classification_source"], expected_source)

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

    def test_todoist_sections_are_fetched_from_to_do_project(self):
        with patch("app.todoist_tools._fetch_projects", return_value={"project-todo": "To-Do"}), patch(
            "app.todoist_tools._fetch_sections",
            return_value={
                "section-am": "A&M",
                "section-xo": "XO Collective",
                "section-freelance": "Freelance Web Design",
                "section-nebulo": "Nebulo",
                "section-personal": "Personal",
                "section-misc": "Misc",
            },
        ) as fetch_sections_mock:
            result = list_todoist_sections(FakeSettings())

        fetch_sections_mock.assert_called_once_with(FakeSettings(), project_id="project-todo")
        self.assertIsNone(result.error)
        self.assertEqual(
            {section["name"]: section["id"] for section in result.sections},
            {
                "A&M": "section-am",
                "XO Collective": "section-xo",
                "Freelance Web Design": "section-freelance",
                "Nebulo": "section-nebulo",
                "Personal": "section-personal",
                "Misc": "section-misc",
            },
        )

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

    def test_affirmative_reply_updates_existing_calendar_event(self):
        gym_event = {
            "id": "event-gym",
            "title": "Gym",
            "start": "2026-06-04T14:30:00-05:00",
            "end": "2026-06-04T15:30:00-05:00",
            "duration_minutes": 60,
            "all_day": False,
            "busy": True,
            "event_type": "flexible",
            "event_category": "flexible",
        }
        updated_event = {
            **gym_event,
            "start": "2026-06-04T14:45:00-05:00",
            "end": "2026-06-04T15:45:00-05:00",
        }

        with patch("app.agent.list_todays_events", return_value=CalendarReadResult(events=[gym_event])), patch(
            "app.agent.list_upcoming_events", return_value=CalendarReadResult(events=[gym_event])
        ), patch(
            "app.agent._get_llm_decision",
            return_value=(
                self._decision(answer="I can help move that.", intent="replan"),
                None,
            ),
        ):
            first_response = handle_chat("move gym to 2:45", self.now)

        self.assertTrue(first_response["needs_confirmation"])
        self.assertEqual(first_response["pending_action"]["type"], "update_calendar_event")
        self.assertEqual(first_response["pending_action"]["details"]["event_id"], "event-gym")
        self.assertEqual(first_response["pending_action"]["details"]["old_start"], "2026-06-04T14:30:00-05:00")
        self.assertEqual(first_response["pending_action"]["details"]["new_start"], "2026-06-04T14:45:00-05:00")

        with patch("app.agent._get_llm_decision") as llm_mock, patch(
            "app.agent.update_calendar_event",
            return_value=CalendarWriteResult(event=updated_event),
        ) as update_event_mock:
            second_response = handle_chat("yes", self.now)

        llm_mock.assert_not_called()
        update_event_mock.assert_called_once()
        call_kwargs = update_event_mock.call_args.kwargs
        self.assertEqual(call_kwargs["event_id"], "event-gym")
        self.assertEqual(call_kwargs["title"], "Gym")
        self.assertEqual(call_kwargs["start"].isoformat(), "2026-06-04T14:45:00-05:00")
        self.assertEqual(call_kwargs["end"].isoformat(), "2026-06-04T15:45:00-05:00")
        self.assertFalse(second_response["needs_confirmation"])
        self.assertIsNone(second_response["pending_action"])
        self.assertEqual(second_response["actions_taken"][0]["type"], "update_calendar_event")

    def test_confirm_create_calendar_event_executes_event_creation(self):
        event = {
            "id": "event-confirmed",
            "title": "Meeting with Brandon",
            "start": "2026-06-05T18:00:00-05:00",
            "end": "2026-06-05T19:00:00-05:00",
            "duration_minutes": 60,
            "all_day": False,
            "busy": True,
            "event_type": "hard",
            "event_category": "hard",
        }
        pending_action = {
            "type": "create_calendar_event",
            "action_type": "create_calendar_event",
            "intent": "schedule_event",
            "calendar_event": {
                "title": "Meeting with Brandon",
                "start": "2026-06-05T18:00:00-05:00",
                "end": "2026-06-05T19:00:00-05:00",
                "description": None,
            },
            "details": {},
        }

        with patch(
            "app.agent.create_calendar_event",
            return_value=CalendarWriteResult(event=event),
        ) as create_event_mock:
            response = confirm_pending_action(pending_action, self.now)

        create_event_mock.assert_called_once()
        self.assertFalse(response["needs_confirmation"])
        self.assertEqual(response["actions_taken"][0]["type"], "create_calendar_event")

    def test_confirm_create_todoist_task_executes_task_creation(self):
        created_task = {
            **TASKS[0],
            "id": "task-confirmed",
            "content": "Buy water bottle",
            "section_name": "Personal",
            "todoist_section_name": "Personal",
        }
        pending_action = {
            "type": "create_todoist_task",
            "action_type": "create_todoist_task",
            "intent": "capture_task",
            "task": {
                "content": "Buy water bottle",
                "project_category": "Personal",
                "due_string": None,
                "due_date": None,
                "labels": [],
                "priority": 4,
                "project_name": "To-Do",
                "section_name": "Personal",
                "todoist_section_name": "Personal",
            },
            "details": {},
        }

        with patch(
            "app.agent.create_task",
            return_value=TodoistWriteResult(task=created_task),
        ) as create_task_mock:
            response = confirm_pending_action(pending_action, self.now)

        create_task_mock.assert_called_once()
        self.assertFalse(response["needs_confirmation"])
        self.assertEqual(response["actions_taken"][0]["type"], "create_todoist_task")
        self.assertEqual(response["actions_taken"][0]["task"]["content"], "Buy water bottle")

    def test_confirm_update_calendar_event_executes_calendar_update(self):
        updated_event = {
            "id": "event-gym",
            "title": "Gym",
            "start": "2026-06-04T14:45:00-05:00",
            "end": "2026-06-04T15:45:00-05:00",
            "duration_minutes": 60,
            "all_day": False,
            "busy": True,
            "event_type": "flexible",
            "event_category": "flexible",
        }
        pending_action = {
            "type": "update_calendar_event",
            "action_type": "update_calendar_event",
            "intent": "replan",
            "details": {
                "event_id": "event-gym",
                "title": "Gym",
                "old_start": "2026-06-04T14:30:00-05:00",
                "old_end": "2026-06-04T15:30:00-05:00",
                "new_start": "2026-06-04T14:45:00-05:00",
                "new_end": "2026-06-04T15:45:00-05:00",
            },
        }

        with patch(
            "app.agent.update_calendar_event",
            return_value=CalendarWriteResult(event=updated_event),
        ) as update_event_mock:
            response = confirm_pending_action(pending_action, self.now)

        update_event_mock.assert_called_once()
        self.assertFalse(response["needs_confirmation"])
        self.assertEqual(response["actions_taken"][0]["type"], "update_calendar_event")
        self.assertEqual(response["actions_taken"][0]["previous_event"]["id"], "event-gym")

    def test_schema_allowed_actions_are_documented(self):
        schema = _decision_schema()
        action_enum = schema["properties"]["action_type"]["enum"]
        self.assertEqual(
            action_enum,
            [
                "none",
                "create_todoist_task",
                "create_todoist_subtask",
                "create_many_todoist_tasks",
                "create_many_todoist_subtasks",
                "create_calendar_event",
                "update_calendar_event",
            ],
        )
        self.assertIn("pending_action", schema["required"])
        self.assertEqual(
            schema["properties"]["pending_action"]["properties"]["type"]["enum"],
            [
                "resolve_calendar_conflict",
                "update_calendar_event",
                "create_todoist_task",
                "create_todoist_subtask",
                "create_many_todoist_tasks",
                "create_many_todoist_subtasks",
            ],
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

    def test_chat_formats_approaching_event_in_configured_timezone(self):
        now = datetime(2026, 6, 5, 17, 45, tzinfo=ZoneInfo("America/Chicago"))
        event = {
            "id": "approaching",
            "title": "Gym",
            "start": "2026-06-05T23:30:00+00:00",
            "end": "2026-06-06T00:30:00+00:00",
            "duration_minutes": 60,
            "all_day": False,
            "busy": True,
            "event_type": "hard",
            "event_category": "hard",
        }
        with patch("app.agent.get_settings", return_value=FakeSettings(openai_api_key=None)), patch(
            "app.agent.list_active_tasks", return_value=TodoistReadResult(tasks=[])
        ), patch(
            "app.agent.list_todays_events", return_value=CalendarReadResult(events=[event])
        ), patch(
            "app.agent.list_upcoming_events", return_value=CalendarReadResult(events=[event])
        ):
            response = handle_chat("Do I have time before the gym?", now)

        self.assertEqual(response["free_block"]["duration_minutes"], 45)
        self.assertEqual(response["free_block"]["end"], "2026-06-05T18:30:00-05:00")
        self.assertIn("6:30 PM", response["answer"])

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
