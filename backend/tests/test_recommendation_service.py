from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.recommendation_service import (  # noqa: E402
    RecommendationAction,
    RecommendationContext,
    RecommendationPurpose,
    recommendation_service,
)
from app.work_domain import (  # noqa: E402
    NormalizedWorkItem,
    WorkDependency,
    WorkEnergy,
    WorkPriority,
    WorkStatus,
)


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)


class RecommendationServiceTests(unittest.TestCase):
    def test_priority_and_due_urgency_are_scored_with_structured_evidence(self):
        urgent = self.work("urgent", priority=WorkPriority.URGENT)
        overdue = self.work("overdue", due_date=date(2026, 7, 11))

        result = recommendation_service.recommend_project_next_move(
            [urgent, overdue], current_time=NOW
        )

        self.assertEqual(result.selected_work.provider_record_id, "overdue")
        signals = {signal.signal: signal for signal in result.evidence}
        self.assertEqual(signals["due_urgency"].score_delta, 100)
        self.assertIn("normalized_priority", signals)
        self.assertTrue(all(signal.explanation for signal in result.evidence))

    def test_task_age_foundation_and_momentum_contribute_evidence(self):
        foundation = self.work(
            "foundation",
            title="Build foundation workflow and ship demo",
            created_at=NOW - timedelta(days=20),
        )

        result = recommendation_service.recommend_project_next_move(
            [foundation], current_time=NOW
        )
        signals = {signal.signal: signal for signal in result.evidence}

        self.assertGreater(signals["task_age"].score_delta, 0)
        self.assertGreater(signals["unblocking_foundation_value"].score_delta, 0)
        self.assertGreater(signals["project_momentum"].score_delta, 0)

    def test_supplied_project_momentum_identity_is_deterministic(self):
        first = self.work("first")
        second = self.work("second")
        context = RecommendationContext(
            current_time=NOW,
            project_momentum_provider_record_ids=("second",),
        )

        result = recommendation_service.recommend_current_action(
            [first, second], context=context
        )

        self.assertEqual(result.selected_work.provider_record_id, "second")
        self.assertIn("project_momentum", {signal.signal for signal in result.evidence})

    def test_context_uses_supplied_free_block_energy_and_commitment(self):
        short_low = self.work(
            "short-low",
            estimated_duration_minutes=20,
            energy_requirement=WorkEnergy.LOW,
        )
        long_high = self.work(
            "long-high",
            estimated_duration_minutes=90,
            energy_requirement=WorkEnergy.HIGH,
        )
        context = RecommendationContext(
            current_time=NOW,
            usable_free_block_minutes=30,
            energy=WorkEnergy.LOW,
            upcoming_commitment_title="Interview",
            minutes_until_upcoming_commitment=45,
        )

        result = recommendation_service.recommend_current_action(
            [long_high, short_low], context=context
        )

        self.assertEqual(result.purpose, RecommendationPurpose.CURRENT_ACTION)
        self.assertEqual(result.selected_work.provider_record_id, "short-low")
        signals = {signal.signal: signal for signal in result.evidence}
        self.assertEqual(
            set(signals),
            {
                "normalized_priority",
                "usable_free_block_fit",
                "energy_fit",
                "upcoming_commitment",
            },
        )
        self.assertEqual(signals["upcoming_commitment"].value["title"], "Interview")

    def test_missing_context_stays_missing(self):
        result = recommendation_service.recommend_current_action(
            [self.work("plain")],
            context=RecommendationContext(current_time=NOW),
        )

        signals = {signal.signal for signal in result.evidence}
        self.assertNotIn("usable_free_block_fit", signals)
        self.assertNotIn("energy_fit", signals)
        self.assertNotIn("upcoming_commitment", signals)
        self.assertIsNone(result.context.usable_free_block_minutes)
        self.assertIsNone(result.context.energy)

    def test_completed_canceled_and_container_work_are_excluded(self):
        completed = self.work(
            "completed", status=WorkStatus.COMPLETED, is_executable=False
        )
        canceled = self.work(
            "canceled", status=WorkStatus.CANCELED, is_executable=False
        )
        container = self.work(
            "container", is_container=True, is_executable=False
        )
        executable = self.work("executable")

        result = recommendation_service.recommend_project_next_move(
            [completed, canceled, container, executable], current_time=NOW
        )

        self.assertEqual(result.selected_work.provider_record_id, "executable")
        self.assertEqual(result.considered_alternatives, ())

    def test_blocked_work_is_not_selected_while_executable_work_exists(self):
        blocked = self.work("blocked", is_blocked=True, priority=WorkPriority.URGENT)
        open_work = self.work("open")

        result = recommendation_service.recommend_project_next_move(
            [blocked, open_work], current_time=NOW
        )

        self.assertEqual(result.action, RecommendationAction.DO_WORK)
        self.assertEqual(result.selected_work.provider_record_id, "open")

    def test_only_blocked_work_produces_explicit_resolution_recommendation(self):
        blocked = self.work(
            "blocked",
            title="Deploy release",
            is_blocked=True,
            dependencies=(
                WorkDependency(
                    provider="linear",
                    provider_record_id="LIN-9",
                    dependency_type="blocked_by",
                ),
            ),
        )

        result = recommendation_service.recommend_project_next_move(
            [blocked], current_time=NOW
        )

        self.assertEqual(result.action, RecommendationAction.RESOLVE_BLOCKER)
        self.assertEqual(result.explanation, "Resolve the blocker for Deploy release.")
        signals = {signal.signal: signal for signal in result.evidence}
        self.assertTrue(signals["blocker_resolution"].value)
        self.assertEqual(
            signals["dependency_references"].value[0]["provider_record_id"],
            "LIN-9",
        )

    def test_non_executable_blocked_container_is_not_a_resolution_candidate(self):
        blocked_container = self.work(
            "blocked-container",
            is_blocked=True,
            is_container=True,
            is_executable=False,
        )

        result = recommendation_service.recommend_project_next_move(
            [blocked_container], current_time=NOW
        )

        self.assertIsNone(result)

    def test_tie_breaking_is_stable_across_input_order(self):
        alpha = self.work("a", title="Zulu")
        beta = self.work("b", title="Alpha")

        forward = recommendation_service.recommend_project_next_move(
            [beta, alpha], current_time=NOW
        )
        reverse = recommendation_service.recommend_project_next_move(
            [alpha, beta], current_time=NOW
        )

        self.assertEqual(forward, reverse)
        self.assertEqual(forward.selected_work.provider_record_id, "a")
        self.assertEqual(forward.computed_at, NOW)
        self.assertEqual(forward.considered_alternatives[0].work.provider_record_id, "b")

    def test_canonical_project_and_provider_identity_are_preserved(self):
        work = self.work("record-1", canonical_project_id="project-nebulo")

        result = recommendation_service.recommend_project_next_move(
            [work], current_time=NOW
        )

        self.assertEqual(result.canonical_project_id, "project-nebulo")
        self.assertEqual(result.selected_work.provider, "test-provider")
        self.assertEqual(result.selected_work.provider_record_id, "record-1")

    @staticmethod
    def work(
        record_id: str,
        *,
        title: str | None = None,
        status: WorkStatus = WorkStatus.OPEN,
        priority: WorkPriority = WorkPriority.NONE,
        due_date: date | None = None,
        created_at: datetime | None = None,
        is_container: bool = False,
        is_executable: bool = True,
        is_blocked: bool = False,
        dependencies: tuple[WorkDependency, ...] = (),
        estimated_duration_minutes: int | None = None,
        energy_requirement: WorkEnergy | None = None,
        canonical_project_id: str | None = None,
    ) -> NormalizedWorkItem:
        return NormalizedWorkItem(
            provider="test-provider",
            provider_record_id=record_id,
            canonical_project_id=canonical_project_id,
            title=title or record_id,
            status=status,
            priority=priority,
            due_date=due_date,
            created_at=created_at,
            is_container=is_container,
            is_executable=is_executable,
            is_blocked=is_blocked,
            dependencies=dependencies,
            estimated_duration_minutes=estimated_duration_minutes,
            energy_requirement=energy_requirement,
        )


if __name__ == "__main__":
    unittest.main()
