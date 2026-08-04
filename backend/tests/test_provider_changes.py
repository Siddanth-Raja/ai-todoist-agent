from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.provider_changes import (  # noqa: E402
    ChangeCategory,
    ChangeComparisonState,
    ChangeTimeBasis,
    CompletionState,
    LinkedCommunicationOutcome,
    ObservedMilestone,
    ObservedRelationship,
    ObservationAvailability,
    ObservationFreshness,
    ProviderEvidenceReference,
    ProviderObservation,
    RelationshipKind,
    provider_change_service,
)
from app.storage import database_connection, ensure_database, list_activity  # noqa: E402


UTC = timezone.utc


def observation(
    *,
    record_id="issue-1",
    observed_at=None,
    updated_at=None,
    created_at=None,
    status="unstarted",
    completion=CompletionState.INCOMPLETE,
    priority=2,
    relationships=(),
    milestone=None,
    communication=None,
):
    observed_at = observed_at or datetime(2026, 8, 1, 12, tzinfo=UTC)
    updated_at = updated_at or observed_at - timedelta(minutes=1)
    return ProviderObservation(
        canonical_project_id="project-pcos",
        provider="linear",
        scope_id="linear-project",
        provider_record_type="issue",
        provider_record_id=record_id,
        provider_revision=updated_at.isoformat(),
        source_created_at=created_at or datetime(2026, 7, 1, tzinfo=UTC),
        source_updated_at=updated_at,
        source_completed_at=(updated_at if completion == CompletionState.COMPLETED else None),
        observed_at=observed_at,
        normalized_status=status,
        completion_state=completion,
        priority=priority,
        relationships=relationships,
        milestone=milestone,
        linked_communication=communication,
        evidence=ProviderEvidenceReference(
            provider_reference="linear-project",
            provider_url=f"https://linear.app/example/{record_id}",
            provider_identifier="SID-139",
        ),
    )


class ProviderChangeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.env = patch.dict(
            os.environ,
            {"APP_DB_PATH": os.path.join(self.tempdir.name, "changes.sqlite3")},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_database()
        self.t0 = datetime(2026, 8, 1, 12, tzinfo=UTC)

    def observe(self, item, **kwargs):
        return provider_change_service.observe_scope(
            provider="linear",
            scope_id="linear-project",
            canonical_project_id="project-pcos",
            observations=[item],
            observed_at=item.observed_at,
            historical_coverage_start=datetime(2026, 7, 1, tzinfo=UTC),
            **kwargs,
        )

    def test_observation_contract_rejects_naive_time_and_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            observation(observed_at=datetime(2026, 8, 1, 12))
        with self.assertRaises(ValueError):
            ProviderObservation.model_validate(
                {**observation().model_dump(), "raw_payload": {"secret": "no"}}
            )

    def test_schema_addition_preserves_legacy_activity_rows(self):
        legacy_path = os.path.join(self.tempdir.name, "legacy.sqlite3")
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE activity_logs (
                    id TEXT PRIMARY KEY, action_type TEXT NOT NULL, title TEXT NOT NULL,
                    detail TEXT, payload TEXT, source TEXT NOT NULL DEFAULT 'app',
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO activity_logs VALUES ('legacy', 'note', 'Legacy', NULL, NULL, 'app', ?)",
                (self.t0.isoformat(),),
            )
        with patch.dict(os.environ, {"APP_DB_PATH": legacy_path}):
            ensure_database()
            with database_connection() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                legacy = connection.execute(
                    "SELECT title FROM activity_logs WHERE id = 'legacy'"
                ).fetchone()
        self.assertIn("provider_record_checkpoints", tables)
        self.assertIn("provider_change_events", tables)
        self.assertEqual(legacy["title"], "Legacy")

    def test_first_observation_establishes_baseline_without_activity(self):
        result = self.observe(observation(observed_at=self.t0))
        self.assertEqual(result.state, ChangeComparisonState.BASELINE_ESTABLISHED)
        self.assertEqual(result.baseline_records, 1)
        self.assertEqual(result.changes, ())
        self.assertEqual(list_activity(limit=None), [])

    def test_identical_read_is_complete_no_change(self):
        first = observation(observed_at=self.t0)
        self.observe(first)
        result = self.observe(first.model_copy(update={"observed_at": self.t0 + timedelta(hours=1)}))
        self.assertEqual(result.state, ChangeComparisonState.COMPLETE_NO_CHANGES)
        self.assertEqual(result.unchanged_records, 1)
        self.assertEqual(list_activity(limit=None), [])

    def test_status_start_completion_and_reopen_transitions(self):
        self.observe(observation(observed_at=self.t0))
        started = observation(
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=self.t0 + timedelta(minutes=50),
            status="started",
        )
        completed = observation(
            observed_at=self.t0 + timedelta(hours=2),
            updated_at=self.t0 + timedelta(hours=1, minutes=50),
            status="completed",
            completion=CompletionState.COMPLETED,
        )
        reopened = observation(
            observed_at=self.t0 + timedelta(hours=3),
            updated_at=self.t0 + timedelta(hours=2, minutes=50),
            status="started",
        )
        self.assertEqual(self.observe(started).changes[0].category, ChangeCategory.WORK_STARTED)
        self.assertEqual(self.observe(completed).changes[0].category, ChangeCategory.WORK_COMPLETED)
        self.assertEqual(self.observe(reopened).changes[0].category, ChangeCategory.WORK_REOPENED)
        self.assertEqual(len(list_activity(limit=None)), 3)

    def test_non_start_workflow_transition_is_status_changed(self):
        self.observe(observation(observed_at=self.t0, status="backlog"))
        changed = observation(
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=self.t0 + timedelta(minutes=50),
            status="unstarted",
        )
        self.assertEqual(
            self.observe(changed).changes[0].category,
            ChangeCategory.STATUS_CHANGED,
        )

    def test_priority_blocker_waiting_and_milestone_transitions(self):
        blocker = ObservedRelationship(
            kind=RelationshipKind.BLOCKER,
            relationship_id="rel-blocker",
            related_provider_record_id="issue-2",
            direction="blocked_by",
        )
        waiting = ObservedRelationship(
            kind=RelationshipKind.WAITING,
            relationship_id="rel-waiting",
            related_provider_record_id="person-1",
            external=True,
        )
        milestone = ObservedMilestone(
            milestone_id="milestone-1", name="Reality Loop", progress=0.2, completed=False
        )
        self.observe(observation(observed_at=self.t0, milestone=milestone))
        changed = observation(
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=self.t0 + timedelta(minutes=50),
            priority=4,
            relationships=(blocker, waiting),
            milestone=milestone.model_copy(update={"progress": 0.6}),
        )
        categories = {event.category for event in self.observe(changed).changes}
        self.assertEqual(
            categories,
            {
                ChangeCategory.PRIORITY_CHANGED,
                ChangeCategory.BLOCKER_ADDED,
                ChangeCategory.WAITING_STARTED,
                ChangeCategory.MILESTONE_PROGRESSED,
            },
        )
        cleared = changed.model_copy(
            update={
                "observed_at": self.t0 + timedelta(hours=2),
                "source_updated_at": self.t0 + timedelta(hours=1, minutes=50),
                "relationships": (),
                "milestone": milestone.model_copy(
                    update={"progress": 1.0, "completed": True}
                ),
            }
        )
        categories = {event.category for event in self.observe(cleared).changes}
        self.assertEqual(
            categories,
            {
                ChangeCategory.BLOCKER_REMOVED,
                ChangeCategory.WAITING_RESOLVED,
                ChangeCategory.MILESTONE_COMPLETED,
            },
        )

    def test_changed_relationship_and_trustworthy_linked_communication(self):
        first = ObservedRelationship(
            kind=RelationshipKind.BLOCKER,
            relationship_id="rel",
            related_provider_record_id="issue-2",
        )
        second = first.model_copy(update={"related_provider_record_id": "issue-3"})
        self.observe(observation(observed_at=self.t0, relationships=(first,)))
        changed = observation(
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=self.t0 + timedelta(minutes=50),
            relationships=(second,),
            communication=LinkedCommunicationOutcome(
                communication_id="thread-1",
                outcome="sent",
                occurred_at=self.t0 + timedelta(minutes=45),
                trustworthy=True,
            ),
        )
        categories = {event.category for event in self.observe(changed).changes}
        self.assertEqual(
            categories,
            {
                ChangeCategory.BLOCKER_CHANGED,
                ChangeCategory.LINKED_COMMUNICATION_CHANGED,
            },
        )

    def test_new_record_requires_a_prior_scope_observation_and_creation_evidence(self):
        self.observe(observation(observed_at=self.t0))
        created = observation(
            record_id="issue-new",
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=self.t0 + timedelta(minutes=50),
            created_at=self.t0 + timedelta(minutes=30),
        )
        result = self.observe(created)
        self.assertEqual(result.changes[0].category, ChangeCategory.RECORD_CREATED)

    def test_duplicate_retry_creates_one_change_and_one_activity(self):
        self.observe(observation(observed_at=self.t0))
        changed = observation(
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=self.t0 + timedelta(minutes=50),
            status="started",
        )
        first = self.observe(changed)
        with database_connection() as connection:
            connection.execute(
                "DELETE FROM provider_record_checkpoints WHERE provider_record_id = 'issue-1'"
            )
            connection.execute(
                "UPDATE provider_change_scopes SET last_success_at = ? WHERE provider = 'linear'",
                ((self.t0 - timedelta(days=1)).isoformat(),),
            )
        # Reconstruct the prior checkpoint so the exact transition is retried after a partial failure.
        self.observe(observation(observed_at=self.t0))
        retry = self.observe(changed)
        self.assertEqual(len(first.changes), 1)
        self.assertEqual(retry.changes, ())
        query = provider_change_service.query_changes(
            canonical_project_id="project-pcos", days=7, evaluated_at=self.t0 + timedelta(days=1)
        )
        self.assertEqual(query.total_count, 1)
        self.assertEqual(len(list_activity(limit=None)), 1)

    def test_out_of_order_observation_is_ignored(self):
        self.observe(observation(observed_at=self.t0))
        latest = observation(
            observed_at=self.t0 + timedelta(hours=2),
            updated_at=self.t0 + timedelta(hours=1),
            status="started",
        )
        self.observe(latest)
        old = observation(
            observed_at=self.t0 + timedelta(hours=3),
            updated_at=self.t0 - timedelta(hours=1),
            status="unstarted",
        )
        result = self.observe(old)
        self.assertEqual(result.out_of_order_records, 1)
        self.assertEqual(result.changes, ())

    def test_return_to_same_value_at_different_source_time_is_not_suppressed(self):
        self.observe(observation(observed_at=self.t0, priority=2))
        higher = observation(
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=self.t0 + timedelta(minutes=50),
            priority=4,
        )
        original = observation(
            observed_at=self.t0 + timedelta(hours=2),
            updated_at=self.t0 + timedelta(hours=1, minutes=50),
            priority=2,
        )
        self.observe(higher)
        self.observe(original)
        query = provider_change_service.query_changes(
            canonical_project_id="project-pcos", days=7, evaluated_at=self.t0 + timedelta(days=1)
        )
        self.assertEqual(
            [event.category for event in query.changes],
            [ChangeCategory.PRIORITY_CHANGED, ChangeCategory.PRIORITY_CHANGED],
        )

    def test_limited_precision_timestamp_still_distinguishes_different_transitions(self):
        self.observe(observation(observed_at=self.t0, priority=2))
        shared_source_time = self.t0 + timedelta(minutes=30)
        higher = observation(
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=shared_source_time,
            priority=4,
        )
        lower = observation(
            observed_at=self.t0 + timedelta(hours=2),
            updated_at=shared_source_time,
            priority=1,
        )
        self.observe(higher)
        self.observe(lower)
        query = provider_change_service.query_changes(
            canonical_project_id="project-pcos", days=7, evaluated_at=self.t0 + timedelta(days=1)
        )
        self.assertEqual(query.total_count, 2)
        self.assertNotEqual(query.changes[0].deduplication_key, query.changes[1].deduplication_key)

    def test_windows_and_injectable_now_are_deterministic(self):
        self.observe(observation(observed_at=self.t0))
        changed = observation(
            observed_at=self.t0 + timedelta(days=10),
            updated_at=self.t0 + timedelta(days=10) - timedelta(minutes=1),
            priority=4,
        )
        self.observe(changed)
        evaluated = self.t0 + timedelta(days=15)
        self.assertEqual(
            provider_change_service.query_changes(
                canonical_project_id="project-pcos", days=7, evaluated_at=evaluated
            ).total_count,
            1,
        )
        self.assertEqual(
            provider_change_service.query_changes(
                canonical_project_id="project-pcos", days=14, evaluated_at=evaluated
            ).total_count,
            1,
        )
        self.assertEqual(
            provider_change_service.query_changes(
                canonical_project_id="project-pcos", days=30, evaluated_at=evaluated
            ).total_count,
            1,
        )

    def test_missing_and_future_source_times_use_observation_fallback(self):
        first = observation(observed_at=self.t0).model_copy(
            update={"source_updated_at": None, "provider_revision": None}
        )
        self.observe(first)
        future = observation(
            observed_at=self.t0 + timedelta(hours=1),
            updated_at=self.t0 + timedelta(days=1),
            priority=4,
        )
        event = self.observe(future).changes[0]
        self.assertEqual(event.time_basis, ChangeTimeBasis.OBSERVED_FALLBACK)
        self.assertEqual(event.effective_at, future.observed_at)

    def test_stale_and_provider_failure_never_claim_no_change(self):
        stale = self.observe(
            observation(observed_at=self.t0), freshness=ObservationFreshness.STALE
        )
        self.assertEqual(stale.state, ChangeComparisonState.STALE_HISTORY)
        unknown = self.observe(
            observation(observed_at=self.t0 + timedelta(minutes=30)),
            freshness=ObservationFreshness.UNKNOWN,
        )
        self.assertEqual(unknown.state, ChangeComparisonState.INCOMPLETE_HISTORY)
        with database_connection() as connection:
            checkpoint_count = connection.execute(
                "SELECT COUNT(*) FROM provider_record_checkpoints"
            ).fetchone()[0]
        self.assertEqual(checkpoint_count, 0)
        provider_change_service.record_coverage(
            provider="linear",
            scope_id="linear-project",
            canonical_project_id="project-pcos",
            availability=ObservationAvailability.UNAVAILABLE,
            observed_at=self.t0 + timedelta(hours=1),
            diagnostic="provider failed",
        )
        query = provider_change_service.query_changes(
            canonical_project_id="project-pcos", days=7, evaluated_at=self.t0 + timedelta(hours=2)
        )
        self.assertEqual(query.conclusion, ChangeComparisonState.PROVIDER_UNAVAILABLE)

    def test_missing_checkpoint_is_explicit_incomplete_history(self):
        query = provider_change_service.query_changes(
            canonical_project_id="project-pcos", days=7, evaluated_at=self.t0
        )
        self.assertEqual(query.conclusion, ChangeComparisonState.INCOMPLETE_HISTORY)
        self.assertEqual(query.total_count, 0)

    def test_read_does_not_acknowledge_and_acknowledgement_is_explicit(self):
        self.observe(observation(observed_at=self.t0))
        self.observe(
            observation(
                observed_at=self.t0 + timedelta(hours=1),
                updated_at=self.t0 + timedelta(minutes=50),
                priority=4,
            )
        )
        query = provider_change_service.query_changes(
            canonical_project_id="project-pcos", days=7, evaluated_at=self.t0 + timedelta(days=1), limit=1
        )
        with database_connection() as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM provider_change_consumers").fetchone()["count"]
        self.assertEqual(count, 0)
        cursor = query.next_cursor
        if cursor is None:
            event = query.changes[-1]
            from app.provider_changes import _encode_cursor  # noqa: PLC0415
            cursor = _encode_cursor(event.effective_at.isoformat(), event.event_position)
        provider_change_service.acknowledge(
            consumer_id="morning-brief",
            provider="linear",
            scope_id="linear-project",
            through_cursor=cursor,
            acknowledged_at=self.t0 + timedelta(days=1),
        )
        with database_connection() as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM provider_change_consumers").fetchone()["count"]
        self.assertEqual(count, 1)

    def test_bounded_query_reports_full_total_before_pagination(self):
        self.observe(observation(observed_at=self.t0, priority=1))
        for index, priority in enumerate((2, 3, 4), start=1):
            self.observe(
                observation(
                    observed_at=self.t0 + timedelta(hours=index),
                    updated_at=self.t0 + timedelta(hours=index, minutes=-5),
                    priority=priority,
                )
            )
        first = provider_change_service.query_changes(
            canonical_project_id="project-pcos",
            days=7,
            evaluated_at=self.t0 + timedelta(days=1),
            limit=2,
        )
        self.assertEqual(first.total_count, 3)
        self.assertEqual(first.returned_count, 2)
        self.assertIsNotNone(first.next_cursor)
        second = provider_change_service.query_changes(
            canonical_project_id="project-pcos",
            days=7,
            evaluated_at=self.t0 + timedelta(days=1),
            limit=2,
            cursor=first.next_cursor,
        )
        self.assertEqual(second.total_count, 3)
        self.assertEqual(second.returned_count, 1)
        from app.provider_changes import _encode_cursor  # noqa: PLC0415

        exhausted = provider_change_service.query_changes(
            canonical_project_id="project-pcos",
            since=self.t0,
            evaluated_at=self.t0 + timedelta(days=1),
            limit=2,
            cursor=_encode_cursor(
                second.changes[-1].effective_at.isoformat(),
                second.changes[-1].event_position,
            ),
        )
        self.assertEqual(exhausted.returned_count, 0)
        self.assertEqual(exhausted.total_count, 3)
        self.assertEqual(
            exhausted.conclusion, ChangeComparisonState.COMPLETE_WITH_CHANGES
        )

    def test_not_configured_and_not_applicable_are_distinct(self):
        provider_change_service.record_coverage(
            provider="linear",
            scope_id="linear-project",
            canonical_project_id="project-pcos",
            availability=ObservationAvailability.NOT_CONFIGURED,
            observed_at=self.t0,
        )
        self.assertEqual(
            provider_change_service.query_changes(
                canonical_project_id="project-pcos", days=7, evaluated_at=self.t0
            ).conclusion,
            ChangeComparisonState.PROVIDER_NOT_CONFIGURED,
        )
        provider_change_service.record_coverage(
            provider="linear",
            scope_id="unmapped-scope",
            canonical_project_id="project-not-applicable",
            availability=ObservationAvailability.NOT_APPLICABLE,
            observed_at=self.t0,
        )
        self.assertEqual(
            provider_change_service.query_changes(
                canonical_project_id="project-not-applicable",
                days=7,
                evaluated_at=self.t0,
            ).conclusion,
            ChangeComparisonState.PROVIDER_NOT_APPLICABLE,
        )


if __name__ == "__main__":
    unittest.main()
