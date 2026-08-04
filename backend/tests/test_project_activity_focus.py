from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.activity_domain import (  # noqa: E402
    ActivityFreshness,
    MeaningfulActivityCategory,
    MeaningfulActivityEvent,
    activity_event_payload,
)
from app.dependency_evaluator import (  # noqa: E402
    DependencyEvaluationState,
    DependencyWorkEvidence,
    EvaluatedDependencyEvidence,
)
from app.project_activity_focus import (  # noqa: E402
    ExplicitProjectIntent,
    ProjectFocusState,
    ProviderCoverage,
    ProviderCoverageState,
    project_activity_focus_service,
)
from app.work_domain import (  # noqa: E402
    NormalizedWorkItem,
    WorkEffortSize,
    WorkPriority,
    WorkStatus,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 4, 15, 0, tzinfo=UTC)
PROJECT_ID = "project-fixture"


def coverage(
    state=ProviderCoverageState.FRESH,
    *,
    history_start=NOW - timedelta(days=90),
):
    return ProviderCoverage(
        provider="linear",
        provider_reference="linear-project",
        state=state,
        observed_at=NOW,
        historical_coverage_start=(
            history_start if state == ProviderCoverageState.FRESH else None
        ),
        detail="fixture coverage",
    )


def work(
    record_id: str,
    *,
    status=WorkStatus.OPEN,
    updated_at=NOW - timedelta(days=1),
    completed_at=None,
    effort_size=None,
    contexts=(),
    workflow_type="started",
):
    return NormalizedWorkItem(
        provider="linear",
        provider_record_id=record_id,
        canonical_project_id=PROJECT_ID,
        title=f"Work {record_id}",
        status=status,
        original_provider_status="Done" if status == WorkStatus.COMPLETED else "In Progress",
        priority=WorkPriority.HIGH,
        is_executable=status == WorkStatus.OPEN,
        created_at=NOW - timedelta(days=60),
        updated_at=updated_at,
        provider_url=f"https://linear.app/example/{record_id}",
        effort_size=effort_size,
        context_requirements=tuple(contexts),
        provider_metadata={
            "issue_identifier": record_id.upper(),
            "workflow_state": {"type": workflow_type},
            "completed_at": completed_at.isoformat() if completed_at else None,
        },
    )


def event(
    key: str,
    category: MeaningfulActivityCategory,
    timestamp: datetime,
    *,
    freshness=ActivityFreshness.FRESH,
):
    typed = MeaningfulActivityEvent(
        category=category,
        canonical_project_id=PROJECT_ID,
        source_provider="linear",
        provider_record_type="issue",
        provider_record_id=key,
        source_timestamp=timestamp,
        observed_at=NOW,
        freshness=freshness,
        evidence_key=key,
        summary=f"{category.value}: {key}",
    )
    return {"id": key, "payload": activity_event_payload(typed)}


def blocker(*, state=DependencyEvaluationState.ACTIVE):
    return EvaluatedDependencyEvidence(
        relationship_provider="linear",
        relationship_id="relation-1",
        canonical_project_id=PROJECT_ID,
        blocked_work=DependencyWorkEvidence(
            provider="linear",
            provider_record_id="blocked",
            provider_identifier="SID-2",
            title="Blocked work",
            status=WorkStatus.OPEN,
            canonical_project_id=PROJECT_ID,
        ),
        blocking_work=DependencyWorkEvidence(
            provider="linear",
            provider_record_id="external",
            provider_identifier="EXT-1",
            title="External dependency",
            status=WorkStatus.OPEN,
            canonical_project_id="external-project",
        ),
        evaluation_state=state,
        explanation="SID-2 is waiting on open EXT-1.",
    )


def evaluate(
    *,
    work_items=(),
    activities=(),
    dependencies=(),
    coverages=None,
    intent=None,
    next_step=None,
    key="fixture",
    limit=12,
):
    return project_activity_focus_service.evaluate(
        canonical_project_id=PROJECT_ID,
        canonical_project_key=key,
        work_items=work_items,
        activity_records=activities,
        dependency_evidence=dependencies,
        provider_coverage=(coverage(),) if coverages is None else coverages,
        evaluated_at=NOW,
        explicit_intent=intent,
        next_step=next_step,
        evidence_limit=limit,
    )


class ProjectActivityFocusServiceTests(unittest.TestCase):
    def test_7_14_30_day_boundaries_are_inclusive_and_future_is_not_recent(self):
        activities = [
            event("at-7", MeaningfulActivityCategory.WORK_UPDATED, NOW - timedelta(days=7)),
            event("at-14", MeaningfulActivityCategory.WORK_UPDATED, NOW - timedelta(days=14)),
            event("at-30", MeaningfulActivityCategory.WORK_UPDATED, NOW - timedelta(days=30)),
            event("future", MeaningfulActivityCategory.WORK_COMPLETED, NOW + timedelta(seconds=1)),
        ]
        result = evaluate(activities=activities)
        counts = {window.days: window.evidence_count for window in result.evaluated_windows}

        self.assertEqual(counts, {7: 1, 14: 2, 30: 3})
        self.assertEqual(result.primary_state, ProjectFocusState.ACTIVE_MOMENTUM)
        future = next(item for item in result.evidence if item.evidence_key == "future")
        self.assertEqual(future.freshness, ActivityFreshness.UNKNOWN)
        self.assertTrue(future.metadata["future_source_timestamp"])

    def test_evaluated_now_is_deterministic_and_timezone_aware(self):
        central = timezone(timedelta(hours=-5))
        same_instant = NOW.astimezone(central)
        result = project_activity_focus_service.evaluate(
            canonical_project_id=PROJECT_ID,
            canonical_project_key="fixture",
            work_items=(),
            activity_records=(
                event("recent", MeaningfulActivityCategory.WORK_UPDATED, NOW - timedelta(hours=1)),
            ),
            dependency_evidence=(),
            provider_coverage=(coverage(),),
            evaluated_at=same_instant,
        )
        self.assertEqual(result.evaluated_at, same_instant)
        self.assertEqual(result.evaluated_windows[0].evidence_count, 1)

    def test_recent_completed_work_is_completion_not_total_project_completion(self):
        completed = work(
            "completed",
            status=WorkStatus.COMPLETED,
            updated_at=NOW - timedelta(days=2),
            completed_at=NOW - timedelta(days=2),
        )
        result = evaluate(work_items=(completed,))

        self.assertEqual(result.primary_state, ProjectFocusState.RECENTLY_COMPLETED)
        self.assertIn("work_completed", result.evaluated_windows[0].categories)
        self.assertNotIn("project_completed", result.evaluated_windows[0].categories)

    def test_recent_started_work_produces_active_momentum(self):
        result = evaluate(work_items=(work("started"),))
        self.assertEqual(result.primary_state, ProjectFocusState.ACTIVE_MOMENTUM)
        self.assertEqual(result.confidence.value, "medium")

    def test_external_blocker_prevents_drift(self):
        result = evaluate(dependencies=(blocker(),))
        self.assertEqual(result.primary_state, ProjectFocusState.WAITING_EXTERNAL)
        self.assertNotIn(ProjectFocusState.QUIET_POSSIBLE_DRIFT, result.supporting_states)
        self.assertEqual(result.evidence[0].metadata["blocking_work_id"], "external")

    def test_recent_momentum_and_waiting_are_compatible_without_silent_overwrite(self):
        result = evaluate(work_items=(work("active"),), dependencies=(blocker(),))
        self.assertEqual(result.primary_state, ProjectFocusState.ACTIVE_MOMENTUM)
        self.assertIn(ProjectFocusState.WAITING_EXTERNAL, result.supporting_states)

    def test_large_context_dependent_next_step_is_general_and_conservative(self):
        next_step = work(
            "large-step",
            updated_at=NOW - timedelta(days=40),
            effort_size=WorkEffortSize.LARGE,
            contexts=("VR headset", "dedicated workspace"),
        )
        result = evaluate(work_items=(next_step,), next_step=next_step, key="xo-style")

        self.assertEqual(result.primary_state, ProjectFocusState.DEDICATED_SESSION_NEEDED)
        self.assertIn(ProjectFocusState.QUIET_POSSIBLE_DRIFT, result.supporting_states)
        self.assertTrue(result.user_confirmation_recommended)
        forbidden = " ".join(item.summary.lower() for item in result.evidence)
        self.assertNotIn("abandoned", forbidden)
        self.assertNotIn("neglected", forbidden)
        self.assertNotIn("failed", forbidden)

    def test_dedicated_session_does_not_claim_quiet_without_reliable_history(self):
        next_step = work(
            "context-step",
            updated_at=NOW - timedelta(days=40),
            contexts=("specialized equipment",),
        )
        result = evaluate(
            work_items=(next_step,),
            next_step=next_step,
            coverages=(coverage(ProviderCoverageState.MISSING_HISTORY),),
        )

        self.assertEqual(result.primary_state, ProjectFocusState.DEDICATED_SESSION_NEEDED)
        self.assertNotIn(ProjectFocusState.QUIET_POSSIBLE_DRIFT, result.supporting_states)

    def test_same_structured_next_step_has_same_result_for_unrelated_project_key(self):
        next_step = work(
            "context-step",
            updated_at=NOW - timedelta(days=40),
            contexts=("specialized equipment",),
        )
        states = {
            evaluate(work_items=(next_step,), next_step=next_step, key=key).primary_state
            for key in ("xo", "nebulo", "freelance", "arbitrary-project")
        }
        self.assertEqual(states, {ProjectFocusState.DEDICATED_SESSION_NEEDED})

    def test_explicit_pause_outranks_recent_completion_and_preserves_conflict(self):
        intent = ExplicitProjectIntent(
            id="intent-1",
            canonical_project_id=PROJECT_ID,
            confirmed_state=ProjectFocusState.INTENTIONALLY_PAUSED,
            reason="Reviewed pause",
            confirmed_at=NOW - timedelta(days=3),
            review_after=NOW + timedelta(days=11),
        )
        completed = work(
            "new-completion",
            status=WorkStatus.COMPLETED,
            completed_at=NOW - timedelta(days=1),
        )
        result = evaluate(work_items=(completed,), intent=intent)

        self.assertEqual(result.primary_state, ProjectFocusState.INTENTIONALLY_PAUSED)
        self.assertTrue(result.explicitly_confirmed)
        self.assertEqual(result.explicit_intent.reason, "Reviewed pause")
        self.assertEqual(result.explicit_intent.review_after, NOW + timedelta(days=11))
        self.assertIn(ProjectFocusState.RECENTLY_COMPLETED, result.conflicting_states)
        self.assertTrue(result.user_confirmation_recommended)

    def test_new_blocker_then_removal_does_not_leave_waiting_state(self):
        added = event(
            "blocker-state",
            MeaningfulActivityCategory.BLOCKER_ADDED,
            NOW - timedelta(days=2),
        )
        removed = event(
            "blocker-state-removed",
            MeaningfulActivityCategory.BLOCKER_REMOVED,
            NOW - timedelta(days=1),
        )
        removed["payload"]["activity_event"]["provider_record_id"] = "blocker-state"

        result = evaluate(activities=(added, removed))

        self.assertNotEqual(result.primary_state, ProjectFocusState.WAITING_EXTERNAL)
        self.assertNotIn(ProjectFocusState.WAITING_EXTERNAL, result.supporting_states)

    def test_expired_intent_no_longer_overrides_inference(self):
        intent = ExplicitProjectIntent(
            id="intent-expired",
            canonical_project_id=PROJECT_ID,
            confirmed_state=ProjectFocusState.INTENTIONALLY_PAUSED,
            confirmed_at=NOW - timedelta(days=30),
            expires_at=NOW - timedelta(seconds=1),
        )
        result = evaluate(work_items=(work("active"),), intent=intent)
        self.assertEqual(result.primary_state, ProjectFocusState.ACTIVE_MOMENTUM)
        self.assertFalse(result.explicitly_confirmed)
        self.assertTrue(result.user_confirmation_recommended)

    def test_stale_blocker_is_supporting_uncertainty_not_confident_waiting(self):
        result = evaluate(
            dependencies=(blocker(),),
            coverages=(coverage(ProviderCoverageState.STALE),),
        )
        self.assertEqual(result.primary_state, ProjectFocusState.INSUFFICIENT_EVIDENCE)
        self.assertIn(ProjectFocusState.WAITING_EXTERNAL, result.supporting_states)
        self.assertEqual(result.freshness, ActivityFreshness.STALE)

    def test_provider_failure_and_no_evidence_remain_insufficient(self):
        failed = evaluate(
            coverages=(coverage(ProviderCoverageState.UNAVAILABLE),),
        )
        absent = evaluate(coverages=())

        self.assertEqual(failed.primary_state, ProjectFocusState.INSUFFICIENT_EVIDENCE)
        self.assertEqual(failed.freshness, ActivityFreshness.UNAVAILABLE)
        self.assertEqual(absent.primary_state, ProjectFocusState.INSUFFICIENT_EVIDENCE)
        self.assertEqual(absent.freshness, ActivityFreshness.UNKNOWN)

    def test_quiet_possible_drift_requires_reliable_30_day_coverage(self):
        old = event(
            "old-work",
            MeaningfulActivityCategory.WORK_UPDATED,
            NOW - timedelta(days=45),
        )
        reliable = evaluate(activities=(old,))
        missing = evaluate(
            activities=(old,),
            coverages=(coverage(ProviderCoverageState.MISSING_HISTORY),),
        )

        self.assertEqual(reliable.primary_state, ProjectFocusState.QUIET_POSSIBLE_DRIFT)
        self.assertTrue(reliable.user_confirmation_recommended)
        self.assertEqual(missing.primary_state, ProjectFocusState.INSUFFICIENT_EVIDENCE)

    def test_identical_evidence_is_deduplicated_before_windows_and_totals(self):
        duplicate = event(
            "same-event",
            MeaningfulActivityCategory.WORK_COMPLETED,
            NOW - timedelta(days=1),
        )
        result = evaluate(activities=(duplicate, duplicate, duplicate))
        self.assertEqual(result.evidence_total_count, 1)
        self.assertEqual(result.evaluated_windows[0].evidence_count, 1)

    def test_normalized_work_and_activity_do_not_double_count_same_provider_event(self):
        completed_at = NOW - timedelta(days=1)
        completed = work(
            "shared-event",
            status=WorkStatus.COMPLETED,
            updated_at=completed_at,
            completed_at=completed_at,
        )
        activity = event(
            "activity-alias",
            MeaningfulActivityCategory.WORK_COMPLETED,
            completed_at,
        )
        activity["payload"]["activity_event"]["provider_record_id"] = "shared-event"
        result = evaluate(work_items=(completed,), activities=(activity,))

        self.assertEqual(result.evidence_total_count, 1)
        self.assertEqual(result.evaluated_windows[0].evidence_count, 1)

    def test_full_evidence_computes_state_before_bounded_ordered_projection(self):
        activities = tuple(
            event(
                f"event-{index:02d}",
                MeaningfulActivityCategory.WORK_UPDATED,
                NOW - timedelta(hours=index),
            )
            for index in range(20)
        )
        result = evaluate(activities=activities, limit=5)

        self.assertEqual(result.primary_state, ProjectFocusState.ACTIVE_MOMENTUM)
        self.assertEqual(result.evidence_total_count, 20)
        self.assertEqual(result.evidence_returned_count, 5)
        self.assertEqual(
            [item.evidence_key for item in result.evidence],
            [f"event-{index:02d}" for index in range(5)],
        )
        self.assertEqual(result.evaluated_windows[0].evidence_count, 20)


if __name__ == "__main__":
    unittest.main()
