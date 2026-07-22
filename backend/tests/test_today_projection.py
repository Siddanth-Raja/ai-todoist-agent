from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calendar_tools import CalendarReadResult  # noqa: E402
from app.project_brain import (  # noqa: E402
    ProjectBrainProjectSnapshot,
    ProjectBrainSnapshot,
)
from app.project_work_packages import LinearProjectDiagnostic  # noqa: E402
from app.recommendation_service import recommendation_service  # noqa: E402
from app.today_projection import TodayProjectionService  # noqa: E402
from app.work_domain import (  # noqa: E402
    NormalizedWorkItem,
    WorkPriority,
    WorkProviderReadState,
    WorkStatus,
)


LOCAL_TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=LOCAL_TZ)


@dataclass
class FakeSettings:
    timezone: str = "America/Chicago"

    @property
    def local_tz(self):
        return ZoneInfo(self.timezone)


def work_item(
    record_id: str,
    title: str,
    *,
    canonical_project_id: str | None,
    priority: WorkPriority,
    duration: int,
    provider: str = "todoist",
) -> NormalizedWorkItem:
    return NormalizedWorkItem(
        provider=provider,
        provider_record_id=record_id,
        canonical_project_id=canonical_project_id,
        title=title,
        status=WorkStatus.OPEN,
        priority=priority,
        is_executable=True,
        estimated_duration_minutes=duration,
        provider_metadata={"section_name": "XO"},
    )


def project_snapshot(
    key: str,
    name: str,
    canonical_project_id: str | None,
    items: list[NormalizedWorkItem],
    *,
    status: str = "Active",
    diagnostic: LinearProjectDiagnostic | None = None,
) -> ProjectBrainProjectSnapshot:
    canonical = recommendation_service.recommend_project_next_move(
        items,
        current_time=NOW,
    )
    next_move = (
        f"Work next: {canonical.selected_work.title}"
        if canonical
        else "Add a concrete next task."
    )
    return ProjectBrainProjectSnapshot(
        definition={
            "key": key,
            "name": name,
            "canonical_project_id": canonical_project_id,
        },
        summary={
            "key": key,
            "name": name,
            "description": f"{name} description",
            "status": status,
            "task_count": len(items),
            "next_recommendation": next_move,
            "linear_diagnostic": diagnostic,
        },
        work_items=tuple(items),
        recommendation_candidates=tuple(items),
        canonical_recommendation=canonical,
    )


def brain_snapshot(
    projects: list[ProjectBrainProjectSnapshot],
    *,
    warnings: tuple[str, ...] = (),
    work_provider_states: tuple[WorkProviderReadState, ...] = (),
) -> ProjectBrainSnapshot:
    work = {
        (item.provider, item.provider_record_id): item
        for project in projects
        for item in project.work_items
    }
    return ProjectBrainSnapshot(
        now=NOW,
        projects=tuple(projects),
        normalized_work=tuple(work.values()),
        warnings=warnings,
        work_provider_states=work_provider_states,
    )


def calendar_event(minutes_from_now: int) -> dict:
    start = NOW + timedelta(minutes=minutes_from_now)
    end = start + timedelta(hours=1)
    return {
        "id": "commitment",
        "title": "XO review",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": 60,
        "all_day": False,
        "busy": True,
        "event_category": "hard",
        "event_type": "hard",
    }


class TodayProjectionTests(unittest.TestCase):
    def setUp(self):
        self.service = TodayProjectionService()
        self.settings = FakeSettings()

    def build(
        self,
        snapshot: ProjectBrainSnapshot,
        events: list[dict] | None = None,
        *,
        calendar_error: str | None = None,
    ) -> dict:
        with patch(
            "app.today_projection.project_brain_service.snapshot",
            return_value=snapshot,
        ), patch(
            "app.today_projection.list_remaining_today_events",
            return_value=CalendarReadResult(
                events=events or [],
                error=calendar_error,
            ),
        ):
            return self.service.build(settings=self.settings, current_time=NOW)

    def test_current_action_uses_shared_service_without_legacy_rank_tasks(self):
        item = work_item(
            "pcos-action",
            "Ship the Today projection",
            canonical_project_id="pcos-id",
            priority=WorkPriority.URGENT,
            duration=30,
        )
        snapshot = brain_snapshot(
            [project_snapshot("pcos-ai-todoist-agent", "PCOS", "pcos-id", [item])]
        )

        with patch("app.planner.rank_tasks", side_effect=AssertionError("legacy ranker called")):
            payload = self.build(snapshot)

        recommendation = payload["recommendation"]
        self.assertEqual(recommendation["source"], "shared_recommendation")
        self.assertEqual(recommendation["provider_record_id"], "pcos-action")
        self.assertEqual(recommendation["canonical_project_key"], "pcos-ai-todoist-agent")
        self.assertEqual(
            recommendation["canonical_project_next_move"],
            "Work next: Ship the Today projection",
        )
        self.assertFalse(recommendation["contextual_override"])

    def test_due_today_blinn_payment_is_protected_from_freelance_recommendation(self):
        blinn_payment = NormalizedWorkItem(
            provider="todoist",
            provider_record_id="blinn-payment",
            canonical_project_id="am-id",
            title="Blinn payment",
            status=WorkStatus.OPEN,
            priority=WorkPriority.MEDIUM,
            due_date=NOW.date(),
            is_executable=True,
            provider_metadata={"section_name": "A&M"},
        )
        freelance_follow_up = work_item(
            "freelance-follow-up",
            "Follow up with the Freelance lead",
            canonical_project_id="freelance-id",
            priority=WorkPriority.URGENT,
            duration=20,
        )
        snapshot = brain_snapshot(
            [
                project_snapshot("am", "A&M", "am-id", [blinn_payment]),
                project_snapshot(
                    "freelance",
                    "Freelance",
                    "freelance-id",
                    [freelance_follow_up],
                ),
            ],
            work_provider_states=(
                WorkProviderReadState(provider="todoist", available=True),
            ),
        )

        payload = self.build(snapshot)

        self.assertEqual(payload["must_do"]["state"], "available")
        self.assertEqual(
            [item["title"] for item in payload["must_do"]["items"]],
            ["Blinn payment"],
        )
        self.assertEqual(payload["must_do"]["items"][0]["urgency"], "due_today")
        self.assertEqual(
            payload["recommendation"]["provider_record_id"],
            "freelance-follow-up",
        )
        self.assertNotEqual(
            payload["must_do"]["items"][0]["provider_record_id"],
            payload["recommendation"]["provider_record_id"],
        )
        self.assertTrue(payload["recommendation"]["evidence"])

    def test_must_do_orders_overdue_before_today_and_excludes_ineligible_work(self):
        overdue = NormalizedWorkItem(
            provider="todoist",
            provider_record_id="overdue",
            canonical_project_id="personal-id",
            title="Overdue obligation",
            status=WorkStatus.OPEN,
            due_date=NOW.date() - timedelta(days=2),
            is_executable=True,
        )
        due_today = NormalizedWorkItem(
            provider="linear",
            provider_record_id="today",
            canonical_project_id="pcos-id",
            title="Due today obligation",
            status=WorkStatus.OPEN,
            due_date=NOW.date(),
            is_executable=True,
        )
        completed = NormalizedWorkItem(
            provider="todoist",
            provider_record_id="completed",
            title="Completed obligation",
            status=WorkStatus.COMPLETED,
            due_date=NOW.date() - timedelta(days=3),
            is_executable=False,
        )
        canceled = NormalizedWorkItem(
            provider="linear",
            provider_record_id="canceled",
            title="Canceled obligation",
            status=WorkStatus.CANCELED,
            due_date=NOW.date(),
            is_executable=False,
        )
        container = NormalizedWorkItem(
            provider="todoist",
            provider_record_id="container",
            title="Container obligation",
            status=WorkStatus.OPEN,
            due_date=NOW.date(),
            is_container=True,
            is_executable=False,
        )
        blocked = NormalizedWorkItem(
            provider="linear",
            provider_record_id="blocked",
            title="Blocked obligation",
            status=WorkStatus.OPEN,
            due_date=NOW.date(),
            is_blocked=True,
            is_executable=True,
        )
        project = project_snapshot(
            "personal",
            "Personal",
            "personal-id",
            [overdue, due_today, completed, canceled, container, blocked, overdue],
        )

        payload = self.build(brain_snapshot([project]))

        self.assertEqual(
            [item["provider_record_id"] for item in payload["must_do"]["items"]],
            ["overdue", "today"],
        )
        self.assertEqual(payload["must_do"]["items"][0]["days_overdue"], 2)

    def test_must_do_classifies_timed_due_values_in_configured_timezone(self):
        timed = NormalizedWorkItem(
            provider="todoist",
            provider_record_id="timed",
            canonical_project_id="am-id",
            title="Evening payment",
            status=WorkStatus.OPEN,
            due_date=date(2026, 7, 17),
            due_at=datetime(2026, 7, 17, 0, 30, tzinfo=ZoneInfo("UTC")),
            is_executable=True,
        )
        snapshot = brain_snapshot(
            [project_snapshot("am", "A&M", "am-id", [timed])]
        )

        payload = self.build(snapshot)

        self.assertEqual(payload["must_do"]["items"][0]["urgency"], "due_today")
        self.assertEqual(payload["must_do"]["items"][0]["due_date"], "2026-07-16")

    def test_must_do_preserves_unavailable_todoist_state_instead_of_empty_success(self):
        error = "Could not read Todoist tasks."
        snapshot = brain_snapshot(
            [],
            warnings=(error,),
            work_provider_states=(
                WorkProviderReadState(
                    provider="todoist",
                    available=False,
                    error=error,
                ),
            ),
        )

        payload = self.build(snapshot)

        self.assertEqual(payload["must_do"]["state"], "unavailable")
        self.assertEqual(payload["must_do"]["items"], [])
        self.assertEqual(payload["must_do"]["errors"], [error])

    def test_free_block_can_override_canonical_next_move_with_explicit_evidence(self):
        deep = work_item(
            "deep",
            "Deep architecture pass",
            canonical_project_id="xo-id",
            priority=WorkPriority.URGENT,
            duration=120,
        )
        quick = work_item(
            "quick",
            "Review controller notes",
            canonical_project_id="xo-id",
            priority=WorkPriority.HIGH,
            duration=20,
        )
        snapshot = brain_snapshot(
            [project_snapshot("xo", "XO", "xo-id", [deep, quick])]
        )

        payload = self.build(snapshot, [calendar_event(70)])

        recommendation = payload["recommendation"]
        self.assertEqual(recommendation["title"], "Review controller notes")
        self.assertTrue(recommendation["contextual_override"])
        self.assertEqual(
            recommendation["canonical_project_next_move"],
            "Work next: Deep architecture pass",
        )
        self.assertIn("Contextual override", recommendation["reason"])
        self.assertIn("fits the supplied 70-minute block", recommendation["reason"])
        signals = {evidence["signal"] for evidence in recommendation["evidence"]}
        self.assertIn("usable_free_block_fit", signals)
        self.assertNotIn("energy_fit", signals)

    def test_calendar_preparation_remains_first_inside_sixty_minutes(self):
        item = work_item(
            "urgent",
            "Urgent work",
            canonical_project_id="xo-id",
            priority=WorkPriority.URGENT,
            duration=15,
        )
        snapshot = brain_snapshot([project_snapshot("xo", "XO", "xo-id", [item])])

        payload = self.build(snapshot, [calendar_event(45)])

        self.assertEqual(payload["recommendation"]["type"], "prepare")
        self.assertEqual(payload["recommendation"]["source"], "calendar")
        self.assertEqual(payload["minutes_until_next_event"], 45)
        self.assertEqual(payload["current_free_block"]["duration_minutes"], 45)

    def test_provider_degradation_is_not_rendered_as_nothing_to_do(self):
        diagnostic = LinearProjectDiagnostic(
            status="provider_failure",
            provider_ref="linear-project",
            message="Linear could not be reached.",
        )
        project = project_snapshot(
            "xo",
            "XO",
            "xo-id",
            [],
            status="Quiet",
            diagnostic=diagnostic,
        )
        snapshot = brain_snapshot([project], warnings=(diagnostic.message,))

        payload = self.build(snapshot)

        self.assertEqual(payload["recommendation"]["type"], "unavailable")
        self.assertIn("Linear could not be reached.", payload["errors"])
        self.assertTrue(payload["life_areas"][0]["degraded"])
        self.assertEqual(payload["life_areas"][0]["provider_status"], "provider_failure")

    def test_project_cards_preserve_project_brain_status_and_system_state(self):
        definitions = [
            ("pcos-ai-todoist-agent", "PCOS", "pcos-id", "Needs attention"),
            ("xo", "XO", "xo-id", "Blocked"),
            ("nebulo", "Nebulo", "nebulo-id", "Active"),
            ("freelance", "Freelance", "freelance-id", "Quiet"),
            ("am", "A&M", "am-id", "Active"),
            ("personal", "Personal", "personal-id", "Needs attention"),
            ("needs-classification", "Needs Classification", None, "Quiet"),
        ]
        projects = [
            project_snapshot(key, name, canonical_id, [], status=status)
            for key, name, canonical_id, status in definitions
        ]

        payload = self.build(brain_snapshot(projects))

        areas = {area["project_key"]: area for area in payload["life_areas"]}
        self.assertEqual(
            set(areas),
            {"xo", "nebulo", "freelance", "am", "personal", "needs-classification"},
        )
        self.assertEqual(areas["xo"]["status"], "Blocked")
        self.assertEqual(areas["personal"]["status"], "Needs attention")
        self.assertEqual(areas["needs-classification"]["name"], "Misc")
        self.assertIsNone(areas["needs-classification"]["canonical_project_id"])


if __name__ == "__main__":
    unittest.main()
