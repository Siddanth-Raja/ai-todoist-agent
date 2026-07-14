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
from app.dependency_evaluator import dependency_evaluator  # noqa: E402
from app.linear_client import LinearProviderError, LinearReadResult  # noqa: E402
from app.linear_work_adapter import linear_work_adapter  # noqa: E402
from app.project_brain import ProjectBrainService  # noqa: E402
from app.project_registry import project_registry_service  # noqa: E402
from app.recommendation_service import recommendation_service  # noqa: E402
from app.storage import create_canonical_project, ensure_database  # noqa: E402
from app.todoist_tools import TodoistReadResult  # noqa: E402
from app.todoist_work_adapter import todoist_work_adapter  # noqa: E402
from app.work_domain import (  # noqa: E402
    NormalizedWorkItem,
    WorkDependency,
    WorkPriority,
    WorkStatus,
)


@dataclass
class FakeSettings:
    timezone: str = "America/Chicago"
    linear_api_key: str | None = None

    @property
    def local_tz(self):
        return ZoneInfo(self.timezone)


def linear_issue(
    project_id: str,
    *,
    record_id: str = "linear-issue",
    identifier: str = "SID-135",
    title: str = "Feed Linear work into Project Brain",
    priority: int = 1,
    milestone_id: str | None = "linear-milestone",
    milestone_name: str = "Finish Linear integration",
):
    return {
        "id": record_id,
        "identifier": identifier,
        "title": title,
        "description": "Read-only mapped work",
        "priority": priority,
        "priorityLabel": "Urgent" if priority == 1 else "Medium",
        "createdAt": "2026-07-01T10:00:00Z",
        "updatedAt": "2026-07-13T10:00:00Z",
        "completedAt": None,
        "canceledAt": None,
        "dueDate": None,
        "url": f"https://linear.app/example/issue/{identifier}",
        "state": {"id": "state", "name": "In Progress", "type": "started"},
        "project": {"id": project_id, "name": "A rename must not matter"},
        "parent": None,
        "projectMilestone": (
            {"id": milestone_id, "name": milestone_name, "targetDate": None}
            if milestone_id
            else None
        ),
        "assignee": None,
        "team": {"id": "team", "key": "SID", "name": "Siddanth"},
        "relations": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
        "inverseRelations": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    }


def normalized_linear_item(
    project_id: str,
    record_id: str,
    identifier: str,
    title: str,
    *,
    status: WorkStatus = WorkStatus.OPEN,
    priority: WorkPriority = WorkPriority.MEDIUM,
    blocked_by: tuple[str, ...] = (),
    container: bool = False,
    milestone_id: str = "milestone",
):
    return NormalizedWorkItem(
        provider="linear",
        provider_record_id=record_id,
        canonical_project_id=project_id,
        title=title,
        status=status,
        priority=priority,
        is_container=container,
        is_executable=status == WorkStatus.OPEN and not container,
        dependencies=tuple(
            WorkDependency(
                provider="linear",
                provider_record_id=blocker,
                dependency_type="blocked_by",
            )
            for blocker in blocked_by
        ),
        provider_url=f"https://linear.app/example/issue/{identifier}",
        provider_metadata={
            "issue_identifier": identifier,
            "provider_project_id": "provider-project",
            "project_milestone": {"id": milestone_id, "name": "Sendable audit"},
            "inverse_relations": [],
        },
    )


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

    def test_build_project_uses_shared_recommendation_service_without_contract_leak(self):
        project = self.registry.get_project_definition("nebulo")
        tasks = todoist_work_adapter.adapt_many(
            [
                {
                    "id": "nebulo-next",
                    "content": "Ship Nebulo demo",
                    "description": "",
                    "section_name": "Nebulo",
                    "todoist_section_name": "Nebulo",
                    "category": "Nebulo",
                    "priority": 4,
                    "todoist_priority": 4,
                    "labels": [],
                }
            ],
            registry=self.registry,
            today=self.now.date(),
        )

        with patch(
            "app.project_brain.recommendation_service.recommend_project_next_move",
            wraps=recommendation_service.recommend_project_next_move,
        ) as recommend:
            brain = self.service.build_project(
                project=project,
                tasks=tasks,
                events=[],
                memories=[],
                activity=[],
                now=self.now,
                registry=self.registry,
            )

        recommend.assert_called_once()
        self.assertIsInstance(recommend.call_args.args[0][0], NormalizedWorkItem)
        self.assertEqual(brain["next_recommendation"], "Work next: Ship Nebulo demo")
        self.assertNotIn("recommendation", brain)
        self.assertNotIn("provider_record_id", brain["tasks"][0])
        self.assertNotIn("canonical_project_id", brain["tasks"][0])

    def test_build_project_surfaces_explicit_blocker_resolution_distinctly(self):
        project = self.registry.get_project_definition("nebulo")
        blocked = NormalizedWorkItem(
            provider="linear",
            provider_record_id="SID-999",
            canonical_project_id=project["canonical_project_id"],
            title="Ship release",
            status=WorkStatus.OPEN,
            priority=WorkPriority.URGENT,
            is_blocked=True,
            dependencies=(
                WorkDependency(
                    provider="linear",
                    provider_record_id="SID-998",
                    dependency_type="blocked_by",
                ),
            ),
        )

        brain = self.service.build_project(
            project=project,
            tasks=[blocked],
            events=[],
            memories=[],
            activity=[],
            now=self.now,
            registry=self.registry,
        )

        self.assertEqual(
            brain["next_recommendation"],
            "Resolve blocker: Ship release",
        )

    def test_available_work_outranks_unrelated_blocked_future_work(self):
        project = self.registry.get_project_definition("nebulo")
        canonical_id = project["canonical_project_id"]
        blocker = normalized_linear_item(
            canonical_id,
            "blocker",
            "SID-103",
            "External prerequisite",
            container=True,
        )
        blocked = normalized_linear_item(
            canonical_id,
            "blocked",
            "SID-104",
            "Future blocked work",
            blocked_by=("blocker",),
        )
        available = normalized_linear_item(
            canonical_id,
            "available",
            "SID-105",
            "Available Nebulo action",
            priority=WorkPriority.URGENT,
        )
        evaluated = dependency_evaluator.evaluate(
            [blocker, blocked, available],
            registry=self.registry,
        )

        brain = self.service.build_project(
            project=project,
            tasks=list(evaluated.work_items),
            events=[],
            memories=[],
            activity=[],
            now=self.now,
            registry=self.registry,
            dependency_evidence=evaluated.evidence,
        )

        self.assertEqual(brain["status"], "Needs attention")
        self.assertEqual(brain["next_recommendation"], "Work next: Available Nebulo action")
        self.assertEqual(brain["blockers"][0]["type"], "explicit_dependency_active")

    def test_no_executable_work_produces_grounded_blocker_resolution(self):
        project = self.registry.get_project_definition("nebulo")
        canonical_id = project["canonical_project_id"]
        blocker = normalized_linear_item(
            canonical_id,
            "blocker",
            "SID-103",
            "External prerequisite",
            container=True,
        )
        blocked = normalized_linear_item(
            canonical_id,
            "blocked",
            "SID-104",
            "Only blocked action",
            blocked_by=("blocker",),
        )
        evaluated = dependency_evaluator.evaluate(
            [blocker, blocked],
            registry=self.registry,
        )

        brain = self.service.build_project(
            project=project,
            tasks=list(evaluated.work_items),
            events=[],
            memories=[],
            activity=[],
            now=self.now,
            registry=self.registry,
            dependency_evidence=evaluated.evidence,
        )

        self.assertEqual(brain["status"], "Blocked")
        self.assertEqual(brain["next_recommendation"], "Resolve blocker: Only blocked action")

    def test_unevaluable_dependency_needs_attention_instead_of_blocked(self):
        project = self.registry.get_project_definition("nebulo")
        canonical_id = project["canonical_project_id"]
        canceled_blocker = normalized_linear_item(
            canonical_id,
            "canceled-blocker",
            "SID-103",
            "Canceled prerequisite",
            status=WorkStatus.CANCELED,
        )
        downstream = normalized_linear_item(
            canonical_id,
            "downstream",
            "SID-104",
            "Review the canceled dependency",
            blocked_by=("canceled-blocker",),
        )
        evaluated = dependency_evaluator.evaluate(
            [canceled_blocker, downstream],
            registry=self.registry,
        )

        brain = self.service.build_project(
            project=project,
            tasks=list(evaluated.work_items),
            events=[],
            memories=[],
            activity=[],
            now=self.now,
            registry=self.registry,
            dependency_evidence=evaluated.evidence,
        )

        self.assertEqual(brain["status"], "Needs attention")
        self.assertEqual(
            brain["blockers"][0]["type"],
            "explicit_dependency_needs_review",
        )
        self.assertEqual(
            brain["work_packages"][0].availability_state.value,
            "needs_review",
        )

    def test_freelance_resolved_chain_drives_package_and_project_consistently(self):
        project = self.registry.get_project_definition("freelance")
        canonical_id = project["canonical_project_id"]
        sid_173 = normalized_linear_item(
            canonical_id,
            "sid-173",
            "SID-173",
            "Run sendability review",
            status=WorkStatus.COMPLETED,
        )
        sid_174 = normalized_linear_item(
            canonical_id,
            "sid-174",
            "SID-174",
            "Export and visually verify the final audit PDF",
            priority=WorkPriority.URGENT,
            blocked_by=("sid-173",),
        )
        sid_175 = normalized_linear_item(
            canonical_id,
            "sid-175",
            "SID-175",
            "Send the audit",
            blocked_by=("sid-174",),
        )
        evaluated = dependency_evaluator.evaluate(
            [sid_173, sid_174, sid_175],
            registry=self.registry,
        )

        brain = self.service.build_project(
            project=project,
            tasks=list(evaluated.work_items),
            events=[],
            memories=[],
            activity=[],
            now=self.now,
            registry=self.registry,
            dependency_evidence=evaluated.evidence,
        )

        package = brain["work_packages"][0]
        self.assertEqual(package.next_action.provider_identifier, "SID-174")
        self.assertEqual(
            brain["next_recommendation"],
            "Work next: Export and visually verify the final audit PDF",
        )
        states = {
            evidence.evaluation_state.value for evidence in brain["dependency_evidence"]
        }
        self.assertEqual(states, {"resolved", "active"})
        self.assertTrue(
            all(
                blocker["source_id"] != "sid-174"
                for blocker in brain["blockers"]
            )
        )

    def test_mixed_todoist_and_linear_work_uses_shared_recommendation_without_deduping(self):
        project = self.registry.get_project_definition("pcos")
        todoist = todoist_work_adapter.adapt_many(
            [
                {
                    "id": "todoist-same-title",
                    "content": "Feed Linear work into Project Brain",
                    "description": "ai todoist agent",
                    "section_name": "Misc",
                    "todoist_section_name": "Misc",
                    "category": "Misc",
                    "priority": 1,
                    "todoist_priority": 1,
                    "labels": [],
                }
            ],
            registry=self.registry,
            today=self.now.date(),
        )
        linear = [
            item.model_copy(update={"canonical_project_id": project["canonical_project_id"]})
            for item in linear_work_adapter.adapt_many(
                [linear_issue("8622937e-f05d-48b7-ba54-43604a8aa733")]
            )
        ]

        brain = self.service.build_project(
            project=project,
            tasks=[*todoist, *linear],
            events=[],
            memories=[],
            activity=[],
            now=self.now,
            registry=self.registry,
        )

        self.assertEqual(
            brain["next_recommendation"],
            "Work next: Feed Linear work into Project Brain",
        )
        self.assertEqual(brain["tasks"][0]["id"], "todoist-same-title")
        package_item = brain["work_packages"][0].work_items[0]
        self.assertEqual(package_item.provider, "linear")
        self.assertEqual(package_item.provider_record_id, "linear-issue")
        self.assertEqual(package_item.provider_url, "https://linear.app/example/issue/SID-135")
        from app.main import ProjectBrain

        payload = ProjectBrain.model_validate(brain).model_dump(mode="json")
        self.assertEqual(payload["work_packages"][0]["provider"], "linear")
        self.assertNotIn("recommendation_score", payload["work_packages"][0])

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
        self.assertEqual(nebulo["status"], "Needs attention")
        self.assertEqual(nebulo["upcoming_events"][0]["id"], "nebulo-event")
        self.assertEqual(nebulo["recent_activity"][0]["id"], "activity-nebulo")
        self.assertIn("Brandon", nebulo["people"])
        self.assertEqual({memory["id"] for memory in nebulo["memories"]}, {"memory-nebulo", "memory-brandon"})
        self.assertEqual(
            nebulo["next_recommendation"],
            "Work next: Waiting on Brandon feedback",
        )
        self.assertEqual(nebulo["blockers"], [])
        self.assertTrue(
            any(
                signal["type"] == "keyword_attention"
                for signal in nebulo["attention_signals"]
            )
        )

    def test_all_four_exact_mappings_are_read_without_name_matching(self):
        expected = {
            "8622937e-f05d-48b7-ba54-43604a8aa733": "pcos-ai-todoist-agent",
            "6752d640-2f40-423f-b86f-ef11e0c4deda": "xo",
            "d9fdfe44-3e66-4dc0-b564-b2bcb646e635": "nebulo",
            "2bde590c-a8ab-4f4e-81eb-f7a8da8c1833": "freelance",
        }
        client = unittest.mock.Mock()
        client.list_issues.side_effect = lambda *, project_id: LinearReadResult(
            records=[
                linear_issue(
                    project_id,
                    record_id=f"issue-{project_id}",
                    identifier=f"ISSUE-{project_id[:4]}",
                )
            ]
        )
        with patch("app.project_brain.LinearClient", return_value=client), patch(
            "app.project_brain.list_active_tasks",
            return_value=TodoistReadResult(tasks=[]),
        ), patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=[]),
        ), patch("app.project_brain.list_memory_entries", return_value=[]), patch(
            "app.project_brain.list_activity", return_value=[]
        ):
            projects = self.service.list_projects(
                settings=FakeSettings(linear_api_key="configured"),
                current_time=self.now,
            )

        self.assertEqual(
            {call.kwargs["project_id"] for call in client.list_issues.call_args_list},
            set(expected),
        )
        for project_id, project_key in expected.items():
            project = next(item for item in projects if item["key"] == project_key)
            self.assertEqual(project["linear_diagnostic"].status, "connected")
            self.assertEqual(project["linear_diagnostic"].provider_ref, project_id)
            self.assertEqual(project["work_packages"][0].canonical_project_key, project_key)
            self.assertTrue(
                all(
                    item.provider_record_id == f"issue-{project_id}"
                    for item in project["work_packages"][0].work_items
                )
            )

    def test_linear_failures_are_additive_and_preserve_existing_project_context(self):
        todoist_task = {
            "id": "pcos-todoist",
            "content": "Keep Todoist recommendation",
            "description": "ai todoist agent",
            "section_name": "Misc",
            "todoist_section_name": "Misc",
            "category": "Misc",
            "priority": 4,
            "todoist_priority": 4,
            "labels": [],
        }
        client = unittest.mock.Mock()
        client.list_issues.return_value = LinearReadResult(
            records=[],
            error=LinearProviderError(code="provider", message="safe"),
        )
        with patch("app.project_brain.LinearClient", return_value=client), patch(
            "app.project_brain.list_active_tasks",
            return_value=TodoistReadResult(tasks=[todoist_task]),
        ), patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=[]),
        ), patch(
            "app.project_brain.list_memory_entries",
            return_value=[
                {
                    "id": "memory-pcos",
                    "type": "project",
                    "title": "PCOS",
                    "content": "Preserved",
                    "enabled": True,
                }
            ],
        ), patch("app.project_brain.list_activity", return_value=[]):
            project = self.service.get_project(
                "pcos",
                settings=FakeSettings(linear_api_key="configured"),
                current_time=self.now,
            )

        self.assertEqual(project["linear_diagnostic"].status, "provider_failure")
        self.assertEqual(project["work_packages"], [])
        self.assertEqual(project["tasks"][0]["id"], "pcos-todoist")
        self.assertEqual(project["next_recommendation"], "Work next: Keep Todoist recommendation")
        self.assertEqual(project["memories"][0]["id"], "memory-pcos")

    def test_authentication_and_unexpected_provider_failures_degrade_safely(self):
        cases = [
            (
                LinearReadResult(
                    records=[],
                    error=LinearProviderError(
                        code="authentication",
                        message="permission denied",
                        http_status=403,
                    ),
                ),
                "authentication_failure",
            ),
            (RuntimeError("unexpected provider failure"), "provider_failure"),
        ]
        for result_or_error, expected_status in cases:
            client = unittest.mock.Mock()
            if isinstance(result_or_error, Exception):
                client.list_issues.side_effect = result_or_error
            else:
                client.list_issues.return_value = result_or_error
            with self.subTest(expected_status=expected_status), patch(
                "app.project_brain.LinearClient", return_value=client
            ), patch(
                "app.project_brain.list_active_tasks",
                return_value=TodoistReadResult(tasks=[]),
            ), patch(
                "app.project_brain.list_upcoming_events",
                return_value=CalendarReadResult(events=[]),
            ), patch("app.project_brain.list_memory_entries", return_value=[]), patch(
                "app.project_brain.list_activity", return_value=[]
            ):
                project = self.service.get_project(
                    "pcos",
                    settings=FakeSettings(linear_api_key="configured"),
                    current_time=self.now,
                )
                self.assertEqual(
                    project["linear_diagnostic"].status,
                    expected_status,
                )
                self.assertEqual(project["work_packages"], [])

    def test_missing_key_and_unmapped_projects_are_diagnosable_without_linear_calls(self):
        client = unittest.mock.Mock()
        client.list_issues.return_value = LinearReadResult(
            records=[],
            error=LinearProviderError(
                code="not_configured",
                message="Linear is not configured.",
            ),
        )
        with patch("app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=[])), patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=[]),
        ), patch("app.project_brain.list_memory_entries", return_value=[]), patch(
            "app.project_brain.list_activity", return_value=[]
        ), patch("app.project_brain.LinearClient", return_value=client) as client_class:
            pcos = self.service.get_project(
                "pcos", settings=FakeSettings(), current_time=self.now
            )
            am = self.service.get_project(
                "am", settings=FakeSettings(), current_time=self.now
            )
            personal = self.service.get_project(
                "personal", settings=FakeSettings(), current_time=self.now
            )
            needs = self.service.get_project(
                "needs-classification",
                settings=FakeSettings(),
                current_time=self.now,
            )

        self.assertEqual(pcos["linear_diagnostic"].status, "not_configured")
        self.assertEqual(pcos["work_packages"], [])
        self.assertEqual(am["linear_diagnostic"].status, "not_mapped")
        self.assertEqual(personal["linear_diagnostic"].status, "not_mapped")
        self.assertEqual(needs["linear_diagnostic"].status, "not_mapped")
        self.assertEqual(client_class.call_count, 1)
        client.list_issues.assert_called_once_with(
            project_id="8622937e-f05d-48b7-ba54-43604a8aa733"
        )

    def test_out_of_project_provider_record_fails_closed(self):
        client = unittest.mock.Mock()
        client.list_issues.return_value = LinearReadResult(
            records=[linear_issue("wrong-project")]
        )
        with patch("app.project_brain.LinearClient", return_value=client), patch(
            "app.project_brain.list_active_tasks", return_value=TodoistReadResult(tasks=[])
        ), patch(
            "app.project_brain.list_upcoming_events",
            return_value=CalendarReadResult(events=[]),
        ), patch("app.project_brain.list_memory_entries", return_value=[]), patch(
            "app.project_brain.list_activity", return_value=[]
        ):
            project = self.service.get_project(
                "pcos",
                settings=FakeSettings(linear_api_key="configured"),
                current_time=self.now,
            )
        self.assertEqual(project["linear_diagnostic"].status, "malformed_response")
        self.assertEqual(project["work_packages"], [])

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
