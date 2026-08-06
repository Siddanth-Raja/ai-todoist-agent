import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.project_activity_focus import (  # noqa: E402
    ProviderCoverage,
    ProviderCoverageState,
)
from app.project_brain import (  # noqa: E402
    ProjectBrainService,
    _complete_change_evidence,
)
from app.project_registry import project_registry_service  # noqa: E402
from app.provider_changes import (  # noqa: E402
    ChangeCategory,
    ChangeComparisonState,
    ChangeQueryResult,
    ChangeTimeBasis,
    ProviderChangeEvent,
    ProviderEvidenceReference,
)
from app.reality_reconciliation import (  # noqa: E402
    ConfirmationOutcome,
    ProviderRecordIdentity,
    RealityAvailability,
    RealityCandidate,
    RealityClassification,
    RealityEvidence,
    RealityEvidenceType,
    RealityFreshness,
    RealityIdentityState,
    RealityProjection,
    TemporalActionability,
    WorkIdentity,
    reality_confirmation_repository,
    reality_reconciliation_service,
)
from app.storage import database_connection, ensure_database  # noqa: E402
from app.work_domain import NormalizedWorkItem, WorkPriority, WorkStatus  # noqa: E402


PROJECT_ID = "project-test"
PROJECT_KEY = "test-project"
LINEAR_WORK = WorkIdentity(provider="linear", provider_record_id="linear-1")


class RealityReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.env = patch.dict(
            os.environ,
            {"APP_DB_PATH": os.path.join(self.tempdir.name, "reality.sqlite3")},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_database()
        self.now = datetime(2026, 8, 6, 9, 0, tzinfo=ZoneInfo("America/Chicago"))

    def evidence(
        self,
        *,
        provider="linear",
        record_id="linear-1",
        record_type="issue",
        claim="open",
        linked_work=None,
        normalized_work=LINEAR_WORK,
        freshness=RealityFreshness.FRESH,
        availability=RealityAvailability.AVAILABLE,
        trustworthy=True,
        source_timestamp=None,
        observed_at=None,
        evidence_type=RealityEvidenceType.WORK_STATE,
        evidence_id=None,
    ):
        return RealityEvidence(
            evidence_id=evidence_id or f"{provider}:{record_id}:{claim}",
            evidence_type=evidence_type,
            canonical_project_id=PROJECT_ID,
            normalized_work_identity=normalized_work,
            provider_identity=ProviderRecordIdentity(
                provider=provider,
                provider_record_type=record_type,
                provider_record_id=record_id,
            ),
            linked_work_identity=linked_work,
            claim=claim,
            observed_state=claim,
            source_timestamp=source_timestamp or self.now - timedelta(minutes=5),
            observed_at=observed_at or self.now,
            freshness=freshness,
            availability=availability,
            trustworthy=trustworthy,
            summary=f"{provider} reports {claim}",
        )

    def candidate(
        self,
        *,
        evidence=None,
        temporal=None,
        identity_state=RealityIdentityState.EXACT,
        reconciliation_id="reconciliation-1",
        possible_matches=(),
        title="Send follow-up",
    ):
        return RealityCandidate(
            reconciliation_id=reconciliation_id,
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            normalized_work_identity=LINEAR_WORK,
            title=title,
            provider_identity=ProviderRecordIdentity(
                provider="linear",
                provider_record_type="issue",
                provider_record_id="linear-1",
            ),
            evidence=tuple(evidence or (self.evidence(),)),
            temporal=temporal or TemporalActionability(),
            identity_state=identity_state,
            possible_work_matches=possible_matches,
        )

    def evaluate(self, candidate, *, complete=True, confirmations=(), limit=12):
        return reality_reconciliation_service.evaluate(
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            candidates=(candidate,),
            evaluated_at=self.now,
            confirmations=confirmations,
            complete_evidence=complete,
            item_limit=limit,
        )

    def test_contract_is_versioned_strict_and_timezone_aware(self):
        evidence = self.evidence()
        self.assertEqual(evidence.schema_version, 1)
        with self.assertRaises(ValueError):
            RealityEvidence.model_validate(
                {**evidence.model_dump(), "unknown_field": True}
            )
        with self.assertRaises(ValueError):
            RealityEvidence.model_validate(
                {**evidence.model_dump(), "observed_at": datetime(2026, 8, 6, 9)}
            )
        with self.assertRaises(ValueError):
            TemporalActionability(due_at=datetime(2026, 8, 6, 9))

    def test_contract_preserves_canonical_provider_and_work_identity(self):
        item = self.evaluate(self.candidate()).items[0]
        self.assertEqual(item.canonical_project_id, PROJECT_ID)
        self.assertEqual(item.normalized_work_identity, LINEAR_WORK)
        self.assertEqual(item.provider_identity.provider_record_id, "linear-1")
        self.assertEqual(item.evidence[0].provider_identity.provider, "linear")

    def test_sent_follow_up_but_linear_open_is_potential_mismatch(self):
        communication = self.evidence(
            provider="gmail",
            record_id="message-1",
            record_type="message",
            claim="sent",
            linked_work=LINEAR_WORK,
            normalized_work=None,
            evidence_type=RealityEvidenceType.COMMUNICATION_OUTCOME,
        )
        item = self.evaluate(
            self.candidate(evidence=(self.evidence(claim="in_progress"), communication))
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.POTENTIAL_MISMATCH)
        self.assertEqual(
            {(e.provider_identity.provider, e.claim) for e in item.evidence},
            {("linear", "in_progress"), ("gmail", "sent")},
        )
        self.assertEqual(
            item.proposed_safe_resolution.code, "review_mark_work_handled"
        )
        self.assertFalse(item.proposed_safe_resolution.performs_provider_mutation)

    def test_historical_change_evidence_is_not_unquestionable_present_truth(self):
        historical_completion = self.evidence(
            claim="completed",
            evidence_type=RealityEvidenceType.PROVIDER_CHANGE,
            evidence_id="provider_change:historical-completion",
            source_timestamp=self.now - timedelta(days=2),
        )
        item = self.evaluate(
            self.candidate(
                evidence=(self.evidence(claim="open"), historical_completion)
            )
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.UNKNOWN)
        self.assertEqual(len(item.evidence), 2)

    def test_cross_provider_evidence_without_exact_link_is_not_reconciled(self):
        communication = self.evidence(
            provider="gmail",
            record_id="message-1",
            record_type="message",
            claim="sent",
            linked_work=None,
            normalized_work=None,
            evidence_type=RealityEvidenceType.COMMUNICATION_OUTCOME,
        )
        item = self.evaluate(
            self.candidate(
                evidence=(self.evidence(claim="open"), communication),
                title="Identical title does not create a link",
            )
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.UNKNOWN)
        self.assertIn("exact link", item.classification_reason)

    def test_ambiguous_identity_remains_review_candidate(self):
        matches = (
            WorkIdentity(provider="linear", provider_record_id="possible-a"),
            WorkIdentity(provider="linear", provider_record_id="possible-b"),
        )
        item = self.evaluate(
            self.candidate(
                identity_state=RealityIdentityState.AMBIGUOUS,
                possible_matches=matches,
            )
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.UNKNOWN)
        self.assertEqual(item.ambiguity_candidates, matches)
        self.assertEqual(item.proposed_safe_resolution.code, "review_identity_link")

    def test_mismatched_stable_work_identity_is_not_reconciled(self):
        wrong_identity = WorkIdentity(provider="linear", provider_record_id="other")
        evidence = self.evidence(normalized_work=wrong_identity)
        item = self.evaluate(self.candidate(evidence=(evidence,))).items[0]
        self.assertEqual(item.classification, RealityClassification.UNKNOWN)
        self.assertIn("different canonical or normalized", item.classification_reason)

    def test_tomorrow_only_task_is_upcoming_not_actionable(self):
        tomorrow = self.now + timedelta(days=1)
        item = self.evaluate(
            self.candidate(
                temporal=TemporalActionability(
                    due_at=tomorrow + timedelta(hours=3),
                    earliest_useful_action_at=tomorrow,
                    action_possible_now=True,
                    action_useful_now=False,
                )
            )
        ).items[0]
        self.assertEqual(
            item.classification, RealityClassification.UPCOMING_NOT_ACTIONABLE
        )
        self.assertEqual(item.temporal.earliest_useful_action_at, tomorrow)

    def test_preparation_window_now_is_actionable_and_keeps_deadline_distinct(self):
        deadline = self.now + timedelta(days=2)
        item = self.evaluate(
            self.candidate(
                temporal=TemporalActionability(
                    earliest_useful_action_at=self.now,
                    preparation_window_start=self.now,
                    hard_deadline=deadline,
                    action_possible_now=True,
                    action_useful_now=True,
                )
            )
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.NEEDS_ACTION)
        self.assertEqual(item.temporal.hard_deadline, deadline)
        self.assertIn("preparation window", item.classification_reason)
        self.assertTrue(
            any(
                evidence.evidence_type == RealityEvidenceType.TEMPORAL_BOUNDARY
                and evidence.claim == "preparation_window_start"
                for evidence in item.evidence
            )
        )

    def test_waiting_boundary_prevents_false_needs_action(self):
        item = self.evaluate(
            self.candidate(
                temporal=TemporalActionability(
                    waiting_until=self.now + timedelta(hours=4),
                    action_possible_now=False,
                    action_useful_now=False,
                )
            )
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.WAITING)

    def test_trustworthy_waiting_on_someone_evidence_is_waiting(self):
        waiting = self.evidence(
            claim="waiting",
            evidence_type=RealityEvidenceType.WAITING_STATE,
        )
        item = self.evaluate(
            self.candidate(
                evidence=(self.evidence(claim="open"), waiting),
                temporal=TemporalActionability(
                    action_possible_now=False,
                    action_useful_now=False,
                ),
            )
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.WAITING)

    def test_waiting_boundary_passes_and_overdue_action_re_evaluates(self):
        item = self.evaluate(
            self.candidate(
                temporal=TemporalActionability(
                    due_at=self.now - timedelta(hours=1),
                    waiting_until=self.now - timedelta(minutes=1),
                    action_possible_now=True,
                    action_useful_now=True,
                )
            )
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.NEEDS_ACTION)

    def test_completed_or_independently_handled_work_is_already_handled(self):
        item = self.evaluate(
            self.candidate(evidence=(self.evidence(claim="completed"),))
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.ALREADY_HANDLED)

    def test_overdue_executable_obligation_remains_needs_action(self):
        item = self.evaluate(
            self.candidate(
                temporal=TemporalActionability(
                    due_at=self.now - timedelta(days=1),
                    hard_deadline=self.now - timedelta(hours=2),
                    action_possible_now=True,
                    action_useful_now=True,
                )
            )
        ).items[0]
        self.assertEqual(item.classification, RealityClassification.NEEDS_ACTION)

    def test_complete_no_action_state_is_honest_no_meaningful_change(self):
        projection = self.evaluate(
            self.candidate(
                temporal=TemporalActionability(
                    action_possible_now=False,
                    action_useful_now=False,
                )
            ),
            complete=True,
        )
        self.assertEqual(
            projection.items[0].classification,
            RealityClassification.NO_MEANINGFUL_CHANGE,
        )
        self.assertEqual(
            projection.overall_classification,
            RealityClassification.NO_MEANINGFUL_CHANGE,
        )

    def test_provider_failure_and_stale_evidence_are_unknown(self):
        cases = (
            self.evidence(availability=RealityAvailability.UNAVAILABLE),
            self.evidence(freshness=RealityFreshness.STALE),
            self.evidence(trustworthy=False),
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                item = self.evaluate(self.candidate(evidence=(evidence,))).items[0]
                self.assertEqual(item.classification, RealityClassification.UNKNOWN)

    def test_future_source_timestamp_and_clock_skew_are_unknown(self):
        evidence = self.evidence(
            source_timestamp=self.now + timedelta(minutes=6),
            observed_at=self.now,
        )
        item = self.evaluate(self.candidate(evidence=(evidence,))).items[0]
        self.assertEqual(item.classification, RealityClassification.UNKNOWN)

    def test_missing_dates_are_not_invented(self):
        item = self.evaluate(self.candidate()).items[0]
        self.assertEqual(item.classification, RealityClassification.UNKNOWN)
        self.assertIsNone(item.temporal.due_at)
        self.assertIsNone(item.temporal.earliest_useful_action_at)

    def test_incomplete_empty_evidence_cannot_be_no_meaningful_change(self):
        projection = reality_reconciliation_service.evaluate(
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            candidates=(),
            evaluated_at=self.now,
            complete_evidence=False,
        )
        self.assertEqual(
            projection.overall_classification, RealityClassification.UNKNOWN
        )

    def test_complete_set_is_computed_before_deterministic_response_bound(self):
        candidates = []
        for index in range(5):
            candidates.append(
                self.candidate(
                    reconciliation_id=f"reconciliation-{index}",
                    evidence=(
                        self.evidence(
                            record_id=f"linear-{index}",
                            evidence_id=f"evidence-{index}",
                        ),
                    ),
                    temporal=TemporalActionability(
                        due_at=self.now - timedelta(days=index + 1),
                        action_possible_now=True,
                        action_useful_now=True,
                    ),
                )
            )
        first = reality_reconciliation_service.evaluate(
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            candidates=reversed(candidates),
            evaluated_at=self.now,
            complete_evidence=True,
            item_limit=2,
        )
        second = reality_reconciliation_service.evaluate(
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            candidates=candidates,
            evaluated_at=self.now,
            complete_evidence=True,
            item_limit=2,
        )
        self.assertEqual(first.total_count, 5)
        self.assertEqual(first.returned_count, 2)
        self.assertEqual(first.classification_counts["needs_action"], 5)
        self.assertEqual(first.items, second.items)

    def test_project_from_work_is_provider_neutral_and_preserves_counts(self):
        work = NormalizedWorkItem(
            provider="example_provider",
            provider_record_id="record-1",
            canonical_project_id=PROJECT_ID,
            title="Provider-neutral obligation",
            status=WorkStatus.OPEN,
            priority=WorkPriority.HIGH,
            due_at=self.now - timedelta(hours=1),
        )
        coverage = ProviderCoverage(
            provider="example_provider",
            state=ProviderCoverageState.FRESH,
            observed_at=self.now,
            historical_coverage_start=self.now - timedelta(days=30),
        )
        changes = ChangeQueryResult(
            evaluated_at=self.now,
            days=30,
            conclusion=ChangeComparisonState.COMPLETE_NO_CHANGES,
        )
        projection = reality_reconciliation_service.project_from_work(
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            work_items=(work,),
            dependency_evidence=(),
            provider_coverage=(coverage,),
            recent_changes=changes,
            evaluated_at=self.now,
        )
        self.assertEqual(projection.items[0].classification, RealityClassification.NEEDS_ACTION)
        self.assertEqual(projection.items[0].provider_identity.provider, "example_provider")

    def test_naive_provider_timestamps_fail_conservatively_without_crashing(self):
        work = NormalizedWorkItem(
            provider="example_provider",
            provider_record_id="record-naive",
            canonical_project_id=PROJECT_ID,
            title="Malformed temporal evidence",
            status=WorkStatus.OPEN,
            due_at=datetime(2026, 8, 5, 9, 0),
            updated_at=datetime(2026, 8, 5, 8, 0),
        )
        coverage = ProviderCoverage(
            provider="example_provider",
            state=ProviderCoverageState.FRESH,
            observed_at=self.now,
            historical_coverage_start=self.now - timedelta(days=30),
        )
        projection = reality_reconciliation_service.project_from_work(
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            work_items=(work,),
            dependency_evidence=(),
            provider_coverage=(coverage,),
            recent_changes=ChangeQueryResult(
                evaluated_at=self.now,
                days=30,
                conclusion=ChangeComparisonState.COMPLETE_NO_CHANGES,
            ),
            evaluated_at=self.now,
        )
        self.assertEqual(projection.items[0].classification, RealityClassification.UNKNOWN)
        self.assertIsNone(projection.items[0].temporal.due_at)

    def test_project_brain_calls_shared_reality_service_additively(self):
        projection = RealityProjection(
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            evaluated_at=self.now,
            overall_classification=RealityClassification.UNKNOWN,
        )
        project = project_registry_service.snapshot().projects[0]
        with patch(
            "app.project_brain.reality_reconciliation_service.project_from_work",
            return_value=projection,
        ) as reconcile:
            result = ProjectBrainService().build_project(
                project=project,
                tasks=[],
                events=[],
                memories=[],
                activity=[],
                now=self.now,
            )
        self.assertIs(result["reality"], projection)
        reconcile.assert_called_once()
        self.assertEqual(reconcile.call_args.kwargs["work_items"], [])

    def test_project_brain_collects_complete_change_evidence_before_reality_bound(self):
        def change(identifier, position):
            return ProviderChangeEvent(
                event_position=position,
                id=identifier,
                deduplication_key=f"dedupe-{identifier}",
                category=ChangeCategory.STATUS_CHANGED,
                canonical_project_id=PROJECT_ID,
                provider="linear",
                scope_id="scope",
                provider_record_type="issue",
                provider_record_id=f"record-{identifier}",
                source_updated_at=self.now - timedelta(minutes=position),
                observed_at=self.now,
                effective_at=self.now - timedelta(minutes=position),
                time_basis=ChangeTimeBasis.SOURCE_UPDATED,
                before="unstarted",
                after="started",
                evidence=ProviderEvidenceReference(),
                activity_id=f"activity-{identifier}",
            )

        first = ChangeQueryResult(
            evaluated_at=self.now,
            days=30,
            changes=(change("one", 1),),
            total_count=2,
            returned_count=1,
            limit=1,
            next_cursor="cursor-1",
            conclusion=ChangeComparisonState.COMPLETE_WITH_CHANGES,
        )
        second = ChangeQueryResult(
            evaluated_at=self.now,
            days=30,
            changes=(change("two", 2),),
            total_count=2,
            returned_count=1,
            limit=500,
            conclusion=ChangeComparisonState.COMPLETE_WITH_CHANGES,
        )
        with patch(
            "app.project_brain.provider_change_service.query_changes",
            return_value=second,
        ) as query:
            complete = _complete_change_evidence(
                first,
                canonical_project_id=PROJECT_ID,
                evaluated_at=self.now,
            )
        self.assertEqual([item.id for item in complete.changes], ["one", "two"])
        self.assertEqual(complete.returned_count, 2)
        self.assertIsNone(complete.next_cursor)
        query.assert_called_once_with(
            canonical_project_id=PROJECT_ID,
            days=30,
            evaluated_at=self.now,
            limit=500,
            cursor="cursor-1",
        )

    def test_confirmation_is_durable_attributable_and_idempotent(self):
        candidate = self.candidate()
        initial = self.evaluate(candidate).items[0]
        kwargs = dict(
            reconciliation_id=candidate.reconciliation_id,
            canonical_project_id=PROJECT_ID,
            selected_resolution_code="confirm_handled",
            outcome=ConfirmationOutcome.HANDLED,
            confirming_actor="user:siddanth",
            confirmed_at=self.now,
            evidence_references=[item.evidence_id for item in initial.evidence],
            evidence_version=initial.evidence_version,
            idempotency_key="confirmation-retry-key",
        )
        first = reality_confirmation_repository.confirm(**kwargs)
        second = reality_confirmation_repository.confirm(**kwargs)
        self.assertEqual(first, second)
        with database_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM reality_confirmations"
            ).fetchone()["count"]
        self.assertEqual(count, 1)
        self.assertEqual(first.confirming_actor, "user:siddanth")

    def test_current_confirmation_classifies_handled_and_remains_attributable(self):
        candidate = self.candidate()
        initial = self.evaluate(candidate).items[0]
        confirmation = reality_confirmation_repository.confirm(
            reconciliation_id=candidate.reconciliation_id,
            canonical_project_id=PROJECT_ID,
            selected_resolution_code="confirm_handled",
            outcome=ConfirmationOutcome.HANDLED,
            confirming_actor="user:siddanth",
            confirmed_at=self.now,
            evidence_references=[item.evidence_id for item in initial.evidence],
            evidence_version=initial.evidence_version,
            idempotency_key="handled-confirmation",
        )
        item = self.evaluate(candidate, confirmations=(confirmation,)).items[0]
        self.assertEqual(item.classification, RealityClassification.ALREADY_HANDLED)
        confirmation_evidence = next(
            entry
            for entry in item.evidence
            if entry.evidence_type == RealityEvidenceType.USER_CONFIRMATION
        )
        self.assertEqual(
            confirmation_evidence.provider_identity.provider_record_id,
            confirmation.confirmation_id,
        )
        self.assertEqual(
            confirmation_evidence.metadata["evidence_version"],
            initial.evidence_version,
        )

    def test_ordinary_reads_create_no_confirmation(self):
        self.evaluate(self.candidate())
        reality_confirmation_repository.list_for_project(PROJECT_ID)
        with database_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM reality_confirmations"
            ).fetchone()["count"]
        self.assertEqual(count, 0)

    def test_confirmation_does_not_expose_or_execute_provider_mutation(self):
        candidate = self.candidate()
        initial = self.evaluate(candidate).items[0]
        confirmation = reality_confirmation_repository.confirm(
            reconciliation_id=candidate.reconciliation_id,
            canonical_project_id=PROJECT_ID,
            selected_resolution_code="review_only",
            outcome=ConfirmationOutcome.REVIEW_ONLY,
            confirming_actor="user:siddanth",
            confirmed_at=self.now,
            evidence_references=[entry.evidence_id for entry in initial.evidence],
            evidence_version=initial.evidence_version,
            idempotency_key="review-only",
        )
        self.assertEqual(confirmation.outcome, ConfirmationOutcome.REVIEW_ONLY)
        self.assertFalse(hasattr(confirmation, "provider_mutation"))
        self.assertFalse(hasattr(confirmation, "execute"))

    def test_confirmation_rejects_raw_email_actor_identity(self):
        item = self.evaluate(self.candidate()).items[0]
        with self.assertRaises(ValueError):
            reality_confirmation_repository.confirm(
                reconciliation_id="reconciliation-1",
                canonical_project_id=PROJECT_ID,
                selected_resolution_code="review_only",
                outcome=ConfirmationOutcome.REVIEW_ONLY,
                confirming_actor="raw-email-actor@",
                confirmed_at=self.now,
                evidence_references=[entry.evidence_id for entry in item.evidence],
                evidence_version=item.evidence_version,
                idempotency_key="raw-email-actor",
            )

    def test_additive_migration_preserves_legacy_activity(self):
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
                (self.now.astimezone(timezone.utc).isoformat(),),
            )
        with patch.dict(os.environ, {"APP_DB_PATH": legacy_path}):
            ensure_database()
            with database_connection() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                legacy = connection.execute(
                    "SELECT title FROM activity_logs WHERE id = 'legacy'"
                ).fetchone()
        self.assertIn("reality_confirmations", tables)
        self.assertEqual(legacy["title"], "Legacy")

    def test_reality_contract_rejects_sensitive_raw_payloads(self):
        with self.assertRaises(ValueError):
            RealityEvidence.model_validate(
                {**self.evidence().model_dump(), "metadata": {"refresh_token": "no"}}
            )

    def test_projection_serializes_all_required_classifications(self):
        self.assertEqual(
            {value.value for value in RealityClassification},
            {
                "needs_action",
                "potential_mismatch",
                "waiting",
                "already_handled",
                "upcoming_not_actionable",
                "no_meaningful_change",
                "unknown",
            },
        )
        projection = RealityProjection(
            canonical_project_id=PROJECT_ID,
            canonical_project_key=PROJECT_KEY,
            evaluated_at=self.now,
            overall_classification=RealityClassification.UNKNOWN,
        )
        self.assertEqual(projection.model_dump(mode="json")["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
