from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.project_work_packages import (  # noqa: E402
    WorkPackageAvailability,
    project_work_package_service,
)
from app.work_domain import (  # noqa: E402
    NormalizedWorkItem,
    WorkDependency,
    WorkPriority,
    WorkStatus,
)


CANONICAL_PROJECT_ID = "project-pcos-ai-todoist-agent"
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def work_item(
    record_id: str,
    title: str,
    *,
    milestone_id: str | None = "milestone-1",
    milestone_name: str = "Finish Linear integration",
    status: WorkStatus = WorkStatus.OPEN,
    priority: WorkPriority = WorkPriority.MEDIUM,
    blocked_by: str | None = None,
    parent_id: str | None = None,
    container: bool = False,
    canonical_project_id: str = CANONICAL_PROJECT_ID,
) -> NormalizedWorkItem:
    dependencies = (
        (
            WorkDependency(
                provider="linear",
                provider_record_id=blocked_by,
                dependency_type="blocked_by",
            ),
        )
        if blocked_by
        else ()
    )
    return NormalizedWorkItem(
        provider="linear",
        provider_record_id=record_id,
        canonical_project_id=canonical_project_id,
        title=title,
        status=status,
        priority=priority,
        is_executable=status == WorkStatus.OPEN and not container,
        is_container=container,
        is_blocked=blocked_by is not None,
        dependencies=dependencies,
        parent_provider_record_id=parent_id,
        provider_url=f"https://linear.app/example/issue/{record_id}",
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        provider_metadata={
            "issue_identifier": record_id.upper(),
            "project_milestone": (
                {"id": milestone_id, "name": milestone_name}
                if milestone_id
                else None
            ),
        },
    )


class ProjectWorkPackageServiceTests(unittest.TestCase):
    def build(self, items, *, limit=3):
        return project_work_package_service.build_current_packages(
            items,
            canonical_project_id=CANONICAL_PROJECT_ID,
            canonical_project_key="pcos-ai-todoist-agent",
            current_time=NOW,
            limit=limit,
        )

    def test_milestone_is_package_backbone_and_identity_is_preserved(self):
        packages = self.build(
            [
                work_item("sid-135-uuid", "Feed Linear work", priority=WorkPriority.URGENT),
                work_item("sid-136-uuid", "Interpret blockers"),
            ]
        )

        self.assertEqual(len(packages), 1)
        package = packages[0]
        self.assertEqual(package.package_id, "linear:milestone:milestone-1")
        self.assertEqual(package.provider_reference_id, "milestone-1")
        self.assertEqual(package.title, "Finish Linear integration")
        self.assertEqual(package.canonical_project_id, CANONICAL_PROJECT_ID)
        self.assertEqual(package.open_action_count, 2)
        self.assertEqual(package.executable_action_count, 2)
        self.assertEqual(package.availability_state, WorkPackageAvailability.AVAILABLE)
        self.assertEqual(package.next_action.provider, "linear")
        self.assertEqual(package.next_action.provider_record_id, "sid-135-uuid")
        self.assertEqual(package.next_action.provider_identifier, "SID-135-UUID")
        self.assertEqual(
            package.next_action.provider_url,
            "https://linear.app/example/issue/sid-135-uuid",
        )
        self.assertEqual(package.work_items[0].status, "open")

    def test_unmilestoned_open_issue_becomes_single_item_fallback(self):
        package = self.build(
            [work_item("fallback", "Produce the first sendable audit", milestone_id=None)]
        )[0]
        self.assertEqual(package.package_id, "linear:issue:fallback")
        self.assertEqual(package.title, "Produce the first sendable audit")
        self.assertEqual(package.context, "Unmilestoned Linear issue")
        self.assertEqual(package.open_action_count, 1)

    def test_completed_and_canceled_items_do_not_count_as_open_work(self):
        packages = self.build(
            [
                work_item("open", "Open action"),
                work_item("done", "Done", status=WorkStatus.COMPLETED),
                work_item("canceled", "Canceled", status=WorkStatus.CANCELED),
            ]
        )
        self.assertEqual(packages[0].open_action_count, 1)
        self.assertEqual(
            [item.provider_record_id for item in packages[0].work_items],
            ["open"],
        )
        self.assertEqual(
            self.build([work_item("done", "Done", status=WorkStatus.COMPLETED)]),
            [],
        )

    def test_explicitly_blocked_items_never_become_next_actions(self):
        package = self.build(
            [work_item("blocked", "Blocked action", blocked_by="blocker")]
        )[0]
        self.assertEqual(
            package.availability_state,
            WorkPackageAvailability.EXPLICITLY_BLOCKED,
        )
        self.assertEqual(package.explicitly_blocked_action_count, 1)
        self.assertEqual(package.executable_action_count, 0)
        self.assertIsNone(package.next_action)
        self.assertEqual(
            package.work_items[0].explicit_dependencies[0].dependency_type,
            "blocked_by",
        )

    def test_parent_containers_never_become_next_actions(self):
        package = self.build(
            [
                work_item("parent", "Container", container=True),
                work_item("child", "Concrete action", parent_id="parent"),
            ]
        )[0]
        self.assertEqual(package.next_action.provider_record_id, "child")
        self.assertEqual(package.open_action_count, 1)
        parent = next(item for item in package.work_items if item.provider_record_id == "parent")
        self.assertTrue(parent.is_container)
        self.assertFalse(parent.is_executable)

    def test_milestone_order_and_text_never_invent_blockers_or_membership(self):
        first = work_item(
            "first",
            "Blocked by the next milestone",
            milestone_id="milestone-a",
            milestone_name="Phase 2",
        )
        second = work_item(
            "second",
            "Same words",
            milestone_id="milestone-b",
            milestone_name="Phase 1",
        )
        packages = self.build([first, second])
        self.assertEqual(len(packages), 2)
        self.assertTrue(all(package.next_action for package in packages))
        self.assertTrue(
            all(package.explicitly_blocked_action_count == 0 for package in packages)
        )
        self.assertEqual(
            {package.provider_reference_id for package in packages},
            {"milestone-a", "milestone-b"},
        )

    def test_top_three_is_deterministic_and_favors_executable_packages(self):
        items = [
            work_item("blocked", "Blocked", milestone_id="m-0", blocked_by="x"),
            work_item("low", "Low", milestone_id="m-1", priority=WorkPriority.LOW),
            work_item("urgent", "Urgent", milestone_id="m-2", priority=WorkPriority.URGENT),
            work_item("high", "High", milestone_id="m-3", priority=WorkPriority.HIGH),
        ]
        first = self.build(items)
        second = self.build(list(reversed(items)))
        self.assertEqual(
            [package.package_id for package in first],
            [package.package_id for package in second],
        )
        self.assertEqual(
            [package.provider_reference_id for package in first],
            ["m-2", "m-3", "m-1"],
        )
        self.assertNotIn("m-0", [package.provider_reference_id for package in first])

    def test_other_projects_and_todoist_items_are_not_grouped(self):
        todoist = work_item("todoist", "Same title", milestone_id=None).model_copy(
            update={"provider": "todoist"}
        )
        other_project = work_item(
            "other",
            "Same title",
            canonical_project_id="project-xo",
        )
        self.assertEqual(self.build([todoist, other_project]), [])


if __name__ == "__main__":
    unittest.main()
