import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.morning_corrections import (  # noqa: E402
    MorningCorrectionParameters,
    MorningCorrectionRequest,
    MorningCorrectionService,
    MorningCorrectionType,
    MorningCorrectionUndoRequest,
    MorningProviderReconciliationService,
    ProviderMutationResult,
    ProviderPreviewConfirmationRequest,
    ProviderPreviewRequest,
    ProviderPreviewStatus,
    ProviderTargetSnapshot,
)
from app.morning_state import (  # noqa: E402
    MorningAvailability,
    MorningBriefPresentation,
    MorningCheckpointMode,
    MorningCheckpointSelection,
    MorningConfidence,
    MorningFactType,
    MorningFreshness,
    MorningSection,
    MorningSectionId,
    MorningStateSynthesis,
    MorningStatement,
)
from app.reality_reconciliation import (  # noqa: E402
    ProviderRecordIdentity,
    RealityClassification,
    RealityConfidence,
    RealityEvidence,
    RealityEvidenceType,
    RealityFreshness,
    RealityItem,
    RealityIdentityState,
    TemporalActionability,
    WorkIdentity,
    reality_confirmation_repository,
)
from app.storage import database_connection, ensure_database  # noqa: E402


TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=TZ)
PROJECT_ID = "project-test"
RECONCILIATION_ID = "reconciliation-test"
EVIDENCE_VERSION = "evidence-v1"
WORK = WorkIdentity(provider="linear", provider_record_id="issue-uuid")


def statement() -> MorningStatement:
    return MorningStatement(
        statement_id="statement-1",
        source_reconciliation_id=RECONCILIATION_ID,
        source_reality_item_id="reality-1",
        evidence_version=EVIDENCE_VERSION,
        section=MorningSectionId.ATTENTION_TODAY,
        classification=RealityClassification.POTENTIAL_MISMATCH,
        status="potential_mismatch",
        summary="Sent follow-up; Linear remains open.",
        reason="Exactly linked evidence conflicts.",
        canonical_project_id=PROJECT_ID,
        canonical_project_key="test",
        life_area_id="test",
        linked_work_identity=WORK,
        provider_identities=(
            ProviderRecordIdentity(
                provider="linear",
                provider_record_type="issue",
                provider_record_id="issue-uuid",
            ),
            ProviderRecordIdentity(
                provider="gmail",
                provider_record_type="thread",
                provider_record_id="thread-opaque",
            ),
        ),
        source_evidence_references=("linear:issue-uuid", "gmail:thread-opaque"),
        source_evidence_summaries=("Linear is open.", "Follow-up was sent."),
        source_timestamps=(NOW - timedelta(hours=1),),
        observed_at=NOW,
        freshness=MorningFreshness.FRESH,
        availability=MorningAvailability.COMPLETE,
        fact_type=MorningFactType.DETERMINISTIC_CONCLUSION,
        confidence=MorningConfidence.MEDIUM,
        temporal=TemporalActionability(action_possible_now=True, action_useful_now=True),
    )


def section(section_id: MorningSectionId, statements=()) -> MorningSection:
    values = tuple(statements)
    return MorningSection(
        section_id=section_id,
        heading=section_id.value,
        statements=values,
        total_count=len(values),
        returned_count=len(values),
        item_limit=12,
        truncated=False,
    )


def synthesis() -> MorningStateSynthesis:
    return MorningStateSynthesis(
        synthesis_id="synthesis-1",
        evaluated_at=NOW,
        overall_classification=RealityClassification.POTENTIAL_MISMATCH,
        complete_evidence=True,
        no_urgent_attention=False,
        urgent_attention_count=1,
        briefing=MorningBriefPresentation(
            headline="Review the evidence before you act.",
            summary="One linked mismatch needs review.",
            primary_kind="review",
            primary_statement_id="statement-1",
        ),
        changes_since_meaningful_check=section(
            MorningSectionId.CHANGES_SINCE_CHECK
        ),
        attention_today=section(MorningSectionId.ATTENTION_TODAY, (statement(),)),
        handled_paused_waiting=section(MorningSectionId.HANDLED_PAUSED_WAITING),
        project_momentum_constraints=section(
            MorningSectionId.PROJECT_MOMENTUM_CONSTRAINTS
        ),
        realistic_day_shape=section(MorningSectionId.REALISTIC_DAY_SHAPE),
        checkpoint=MorningCheckpointSelection(
            consumer_id="morning-state",
            mode=MorningCheckpointMode.RETAINED_HISTORY_FALLBACK,
            selected_since=NOW - timedelta(days=30),
            coverage_complete=True,
        ),
    )


def reality_item() -> RealityItem:
    evidence = RealityEvidence(
        evidence_id="linear:issue-uuid",
        evidence_type=RealityEvidenceType.WORK_STATE,
        canonical_project_id=PROJECT_ID,
        normalized_work_identity=WORK,
        provider_identity=ProviderRecordIdentity(
            provider="linear",
            provider_record_type="issue",
            provider_record_id="issue-uuid",
        ),
        linked_work_identity=WORK,
        claim="open",
        observed_state="open",
        source_timestamp=NOW - timedelta(hours=1),
        observed_at=NOW,
        freshness=RealityFreshness.FRESH,
        summary="Linear remains open.",
    )
    return RealityItem(
        reality_item_id="reality-1",
        reconciliation_id=RECONCILIATION_ID,
        canonical_project_id=PROJECT_ID,
        canonical_project_key="test",
        normalized_work_identity=WORK,
        provider_identity=evidence.provider_identity,
        title="Follow up",
        classification=RealityClassification.POTENTIAL_MISMATCH,
        classification_reason="Providers conflict.",
        temporal=TemporalActionability(action_possible_now=True, action_useful_now=True),
        identity_state=RealityIdentityState.EXACT,
        confidence=RealityConfidence.MEDIUM,
        evidence=(evidence,),
        evidence_version=EVIDENCE_VERSION,
    )


class FakeProviderAdapter:
    def __init__(self, *, value="started", revision="rev-1", result="succeeded"):
        self.value = value
        self.revision = revision
        self.result = result
        self.mutations = 0

    def inspect(self, **_kwargs):
        return ProviderTargetSnapshot(value=self.value, revision=self.revision)

    def mutate(self, *, proposed_value, **_kwargs):
        self.mutations += 1
        if self.result == "succeeded":
            self.value = proposed_value
            self.revision = "rev-2"
        return ProviderMutationResult(
            status=self.result,
            confirmed_value=self.value,
            result_reference="provider-result-1" if self.result == "succeeded" else None,
            diagnostic=None if self.result == "succeeded" else "Provider rejected the exact mutation.",
        )


class ExplodingMutationAdapter(FakeProviderAdapter):
    def mutate(self, **_kwargs):
        self.mutations += 1
        raise RuntimeError("simulated provider transport failure")


class ExplodingInspectAdapter(FakeProviderAdapter):
    def inspect(self, **_kwargs):
        raise RuntimeError("simulated provider read failure")


class MorningCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.env = patch.dict(
            os.environ,
            {"APP_DB_PATH": os.path.join(self.tempdir.name, "corrections.sqlite3")},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_database()
        self.service = MorningCorrectionService()

    def request(self, correction_type, *, key="correction-1", parameters=None):
        return MorningCorrectionRequest(
            synthesis_id="synthesis-1",
            evaluated_at=NOW,
            statement_id="statement-1",
            evidence_version=EVIDENCE_VERSION,
            correction_type=correction_type,
            parameters=parameters or MorningCorrectionParameters(),
            correcting_actor="user-primary",
            idempotency_key=key,
        )

    def test_additive_schema_and_ordinary_read_side_effect_freedom(self):
        with database_connection() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            before = connection.execute(
                "SELECT COUNT(*) FROM morning_corrections"
            ).fetchone()[0]
        synthesis().model_dump()
        with database_connection() as connection:
            after = connection.execute(
                "SELECT COUNT(*) FROM morning_corrections"
            ).fetchone()[0]
        self.assertIn("morning_corrections", tables)
        self.assertIn("morning_provider_previews", tables)
        self.assertIn("reality_confirmation_reversals", tables)
        self.assertEqual(before, after)

    def test_legacy_provider_preview_schema_is_migrated_additively(self):
        legacy_path = os.path.join(self.tempdir.name, "legacy-preview.sqlite3")
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE morning_provider_previews (
                    id TEXT PRIMARY KEY,
                    statement_id TEXT NOT NULL,
                    synthesis_id TEXT NOT NULL,
                    evidence_version TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_record_type TEXT NOT NULL,
                    provider_record_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    previous_value_json TEXT,
                    proposed_value_json TEXT NOT NULL,
                    provider_revision TEXT,
                    requested_by_actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    diagnostic TEXT,
                    confirmation_idempotency_key TEXT UNIQUE,
                    confirmed_at TEXT,
                    result_reference TEXT,
                    request_idempotency_key TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL
                )
                """
            )

        with patch.dict(os.environ, {"APP_DB_PATH": legacy_path}):
            ensure_database()
            with database_connection() as connection:
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(morning_provider_previews)"
                    ).fetchall()
                }
            self.assertIn("confirmed_by_actor", columns)

            adapter = FakeProviderAdapter()
            service = MorningProviderReconciliationService(adapters={"linear": adapter})
            preview = service.preview(
                self.preview_request(key="legacy-preview"),
                synthesis=synthesis(),
                created_at=NOW,
            )
            self.assertEqual(preview.status, ProviderPreviewStatus.READY)
            self.assertEqual(adapter.mutations, 0)

    def test_already_done_is_idempotent_attributable_and_reversible(self):
        request = self.request(MorningCorrectionType.ALREADY_DONE)
        first = self.service.create(request, synthesis=synthesis(), created_at=NOW)
        second = self.service.create(
            request,
            synthesis=synthesis(),
            created_at=NOW + timedelta(seconds=5),
        )
        self.assertEqual(first, second)
        self.assertEqual(first.correcting_actor, "user-primary")
        self.assertEqual(first.work_provider_record_id, "issue-uuid")
        self.assertEqual(
            len(reality_confirmation_repository.list_for_project(PROJECT_ID)), 1
        )
        applied = self.service.apply_to_reality_items((reality_item(),), evaluated_at=NOW)
        self.assertEqual(applied[0].classification, RealityClassification.ALREADY_HANDLED)
        self.assertEqual(applied[0].evidence[-1].provider_identity.provider, "pcos")

        reversed_record = self.service.repository.reverse(
            first.correction_id,
            MorningCorrectionUndoRequest(
                reversing_actor="user-primary", idempotency_key="undo-1"
            ),
            reversed_at=NOW + timedelta(minutes=1),
        )
        self.assertEqual(reversed_record.status.value, "reversed")
        self.assertEqual(
            reality_confirmation_repository.list_for_project(PROJECT_ID), ()
        )

    def test_not_today_derives_local_review_boundary_and_expires(self):
        record = self.service.create(
            self.request(MorningCorrectionType.NOT_TODAY),
            synthesis=synthesis(),
            created_at=NOW,
        )
        self.assertEqual(record.review_at, datetime(2026, 8, 8, 0, 0, tzinfo=TZ))
        applied = self.service.apply_to_reality_items((reality_item(),), evaluated_at=NOW)
        self.assertEqual(
            applied[0].classification, RealityClassification.UPCOMING_NOT_ACTIONABLE
        )
        returned = self.service.apply_to_reality_items(
            (reality_item(),), evaluated_at=record.review_at
        )
        self.assertEqual(
            returned[0].classification, RealityClassification.POTENTIAL_MISMATCH
        )

    def test_waiting_is_durable_without_inventing_deadline_or_provider_write(self):
        record = self.service.create(
            self.request(MorningCorrectionType.WAITING_ON_SOMEONE),
            synthesis=synthesis(),
            created_at=NOW,
        )
        applied = self.service.apply_to_reality_items((reality_item(),), evaluated_at=NOW)
        self.assertEqual(applied[0].classification, RealityClassification.WAITING)
        self.assertIsNone(applied[0].temporal.waiting_until)
        self.assertEqual(record.source_provider, "linear")
        with database_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM morning_provider_previews"
                ).fetchone()[0],
                0,
            )
        review_at = NOW + timedelta(hours=2)
        bounded = self.service.create(
            self.request(
                MorningCorrectionType.WAITING_ON_SOMEONE,
                key="waiting-bounded",
                parameters=MorningCorrectionParameters(waiting_until=review_at),
            ),
            synthesis=synthesis(),
            created_at=NOW + timedelta(minutes=1),
        )
        self.assertEqual(bounded.review_at, review_at)
        reevaluated = self.service.apply_to_reality_items(
            (reality_item(),), evaluated_at=review_at
        )[0]
        self.assertEqual(
            reevaluated.classification, RealityClassification.POTENTIAL_MISMATCH
        )

    def test_superseding_already_done_reverses_its_reality_confirmation(self):
        first = self.service.create(
            self.request(MorningCorrectionType.ALREADY_DONE, key="done-first"),
            synthesis=synthesis(),
            created_at=NOW,
        )
        replacement = self.service.create(
            self.request(MorningCorrectionType.NOT_TODAY, key="not-today-second"),
            synthesis=synthesis(),
            created_at=NOW + timedelta(minutes=1),
        )
        self.assertEqual(replacement.supersedes_correction_id, first.correction_id)
        self.assertEqual(
            reality_confirmation_repository.list_for_project(PROJECT_ID), ()
        )
        after_expiry = self.service.apply_to_reality_items(
            (reality_item(),), evaluated_at=replacement.review_at
        )[0]
        self.assertEqual(
            after_expiry.classification, RealityClassification.POTENTIAL_MISMATCH
        )

    def test_snooze_suppresses_then_returns_and_wrong_context_preserves_evidence(self):
        wake = NOW + timedelta(hours=2)
        self.service.create(
            self.request(
                MorningCorrectionType.SNOOZE,
                parameters=MorningCorrectionParameters(snooze_until=wake),
            ),
            synthesis=synthesis(),
            created_at=NOW,
        )
        self.assertEqual(
            self.service.apply_to_reality_items((reality_item(),), evaluated_at=NOW),
            (),
        )
        shared = self.service.apply_to_reality_items(
            (reality_item(),),
            evaluated_at=NOW,
            include_snoozed=True,
        )[0]
        self.assertEqual(
            shared.classification,
            RealityClassification.UPCOMING_NOT_ACTIONABLE,
        )
        self.assertEqual(shared.effective_correction.correction_type, "snooze")
        self.assertEqual(shared.temporal.earliest_useful_action_at, wake)
        self.assertEqual(
            len(self.service.apply_to_reality_items((reality_item(),), evaluated_at=wake)),
            1,
        )

        wrong = self.request(MorningCorrectionType.WRONG_CONTEXT, key="wrong-1")
        self.service.create(wrong, synthesis=synthesis(), created_at=wake)
        disputed = self.service.apply_to_reality_items(
            (reality_item(),), evaluated_at=wake
        )[0]
        self.assertEqual(disputed.classification, RealityClassification.UNKNOWN)
        self.assertEqual(disputed.evidence[0].evidence_id, "linear:issue-uuid")
        self.assertEqual(disputed.evidence[-1].claim, "wrong_context")

    def test_evidence_and_synthesis_version_binding_reject_stale_input(self):
        bad = self.request(MorningCorrectionType.ALREADY_DONE).model_copy(
            update={"evidence_version": "old"}
        )
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.service.create(bad, synthesis=synthesis(), created_at=NOW)
        changed = self.request(MorningCorrectionType.ALREADY_DONE).model_copy(
            update={"synthesis_id": "old-synthesis"}
        )
        with self.assertRaisesRegex(ValueError, "synthesis changed"):
            self.service.create(changed, synthesis=synthesis(), created_at=NOW)

    def test_sensitive_correction_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            MorningCorrectionRequest.model_validate(
                {
                    "synthesis_id": "synthesis-1",
                    "evaluated_at": NOW.isoformat(),
                    "statement_id": "statement-1",
                    "evidence_version": EVIDENCE_VERSION,
                    "correction_type": "already_done",
                    "parameters": {"token": "secret"},
                    "correcting_actor": "user-primary",
                    "idempotency_key": "bad",
                }
            )

    def preview_request(self, key="preview-1"):
        return ProviderPreviewRequest(
            synthesis_id="synthesis-1",
            evaluated_at=NOW,
            statement_id="statement-1",
            evidence_version=EVIDENCE_VERSION,
            requested_by_actor="user-primary",
            idempotency_key=key,
        )

    def confirmation(self, preview, key="confirm-1"):
        return ProviderPreviewConfirmationRequest(
            preview_id=preview.preview_id,
            evidence_version=preview.evidence_version,
            provider=preview.provider,
            provider_record_type=preview.provider_record_type,
            provider_record_id=preview.provider_record_id,
            field_name=preview.field_name,
            previous_value=preview.previous_value,
            proposed_value=preview.proposed_value,
            confirming_actor="user-primary",
            idempotency_key=key,
        )

    def test_preview_is_exact_and_never_mutates(self):
        adapter = FakeProviderAdapter()
        service = MorningProviderReconciliationService(adapters={"linear": adapter})
        preview = service.preview(
            self.preview_request(), synthesis=synthesis(), created_at=NOW
        )
        self.assertEqual(preview.status, ProviderPreviewStatus.READY)
        self.assertEqual(preview.provider_record_id, "issue-uuid")
        self.assertEqual(preview.field_name, "status")
        self.assertEqual(preview.previous_value, "started")
        self.assertEqual(preview.proposed_value, "completed")
        self.assertEqual(adapter.mutations, 0)

        adapter.value = "canceled"
        duplicate = service.preview(
            self.preview_request(),
            synthesis=synthesis(),
            created_at=NOW + timedelta(seconds=5),
        )
        self.assertEqual(duplicate, preview)

    def test_production_default_has_no_broad_provider_mutation(self):
        service = MorningProviderReconciliationService()
        preview = service.preview(
            self.preview_request(), synthesis=synthesis(), created_at=NOW
        )
        self.assertEqual(preview.status, ProviderPreviewStatus.UNSUPPORTED)
        self.assertIn("not registered", preview.diagnostic)
        with self.assertRaisesRegex(ValueError, "not ready"):
            service.confirm(self.confirmation(preview), confirmed_at=NOW)

    def test_provider_preview_failure_is_attributable_and_non_mutating(self):
        adapter = ExplodingInspectAdapter()
        service = MorningProviderReconciliationService(adapters={"linear": adapter})
        preview = service.preview(
            self.preview_request(), synthesis=synthesis(), created_at=NOW
        )
        self.assertEqual(preview.status, ProviderPreviewStatus.FAILED)
        self.assertEqual(preview.requested_by_actor, "user-primary")
        self.assertIn("no mutation occurred", preview.diagnostic)
        self.assertEqual(adapter.mutations, 0)

    def test_exact_confirmation_revalidates_and_attributes_success(self):
        adapter = FakeProviderAdapter()
        service = MorningProviderReconciliationService(adapters={"linear": adapter})
        preview = service.preview(
            self.preview_request(), synthesis=synthesis(), created_at=NOW
        )
        result = service.confirm(
            self.confirmation(preview), confirmed_at=NOW + timedelta(seconds=1)
        )
        self.assertEqual(result.status, ProviderPreviewStatus.SUCCEEDED)
        self.assertEqual(result.result_reference, "provider-result-1")
        self.assertEqual(result.confirmed_by_actor, "user-primary")
        self.assertEqual(adapter.mutations, 1)
        duplicate = service.confirm(
            self.confirmation(preview), confirmed_at=NOW + timedelta(seconds=2)
        )
        self.assertEqual(duplicate.status, ProviderPreviewStatus.SUCCEEDED)
        self.assertEqual(adapter.mutations, 1)

        collision = self.confirmation(preview).model_copy(
            update={"proposed_value": "canceled"}
        )
        with self.assertRaisesRegex(ValueError, "another exact confirmation"):
            service.confirm(collision, confirmed_at=NOW + timedelta(seconds=3))
        self.assertEqual(adapter.mutations, 1)

    def test_stale_preview_rejects_changed_provider_state_without_mutation(self):
        adapter = FakeProviderAdapter()
        service = MorningProviderReconciliationService(adapters={"linear": adapter})
        preview = service.preview(
            self.preview_request(), synthesis=synthesis(), created_at=NOW
        )
        adapter.value = "canceled"
        adapter.revision = "rev-new"
        result = service.confirm(
            self.confirmation(preview), confirmed_at=NOW + timedelta(seconds=1)
        )
        self.assertEqual(result.status, ProviderPreviewStatus.STALE)
        self.assertEqual(adapter.mutations, 0)

    def test_provider_failure_is_not_reported_as_success(self):
        adapter = FakeProviderAdapter(result="failed")
        service = MorningProviderReconciliationService(adapters={"linear": adapter})
        preview = service.preview(
            self.preview_request(), synthesis=synthesis(), created_at=NOW
        )
        result = service.confirm(
            self.confirmation(preview), confirmed_at=NOW + timedelta(seconds=1)
        )
        self.assertEqual(result.status, ProviderPreviewStatus.FAILED)
        self.assertIn("rejected", result.diagnostic)

    def test_provider_exception_is_audited_as_uncertain_not_success(self):
        adapter = ExplodingMutationAdapter()
        service = MorningProviderReconciliationService(adapters={"linear": adapter})
        preview = service.preview(
            self.preview_request(), synthesis=synthesis(), created_at=NOW
        )
        result = service.confirm(
            self.confirmation(preview), confirmed_at=NOW + timedelta(seconds=1)
        )
        self.assertEqual(result.status, ProviderPreviewStatus.UNCERTAIN)
        self.assertEqual(result.confirmed_by_actor, "user-primary")
        self.assertIn("re-read", result.diagnostic)
        self.assertEqual(adapter.mutations, 1)

    def test_confirmation_must_match_every_exact_preview_field(self):
        adapter = FakeProviderAdapter()
        service = MorningProviderReconciliationService(adapters={"linear": adapter})
        preview = service.preview(
            self.preview_request(), synthesis=synthesis(), created_at=NOW
        )
        tampered = self.confirmation(preview).model_copy(
            update={"provider_record_id": "same-title-different-id"}
        )
        with self.assertRaisesRegex(ValueError, "exact provider preview"):
            service.confirm(tampered, confirmed_at=NOW + timedelta(seconds=1))
        self.assertEqual(adapter.mutations, 0)


if __name__ == "__main__":
    unittest.main()
