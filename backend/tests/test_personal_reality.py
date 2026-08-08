from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.personal_reality import personal_reality_service  # noqa: E402
from app.reality_reconciliation import (  # noqa: E402
    EffectiveRealityCorrection,
    ProviderRecordIdentity,
    RealityClassification,
    RealityConfidence,
    RealityEvidence,
    RealityEvidenceType,
    RealityIdentityState,
    RealityItem,
    RealityProjection,
    TemporalActionability,
    WorkIdentity,
)


NOW = datetime(2026, 8, 8, 9, 0, tzinfo=ZoneInfo("America/Chicago"))


def item(index: int, classification: RealityClassification) -> RealityItem:
    provider = "linear" if index % 2 else "todoist"
    record_id = f"record-{index:02d}"
    work = WorkIdentity(provider=provider, provider_record_id=record_id)
    provider_identity = ProviderRecordIdentity(
        provider=provider,
        provider_record_type="work_item",
        provider_record_id=record_id,
    )
    evidence = RealityEvidence(
        evidence_id=f"evidence:{provider}:{record_id}",
        evidence_type=RealityEvidenceType.WORK_STATE,
        canonical_project_id="project-arbitrary",
        normalized_work_identity=work,
        provider_identity=provider_identity,
        claim="open",
        observed_state="open",
        observed_at=NOW,
        summary="Canonical provider evidence.",
    )
    return RealityItem(
        reality_item_id=f"reality:{provider}:{record_id}",
        reconciliation_id=f"reality:{provider}:{record_id}",
        canonical_project_id="project-arbitrary",
        canonical_project_key="arbitrary-project",
        normalized_work_identity=work,
        provider_identity=provider_identity,
        title=f"Work {index}",
        classification=classification,
        classification_reason="Deterministic shared classification.",
        temporal=TemporalActionability(action_possible_now=True),
        identity_state=RealityIdentityState.EXACT,
        confidence=RealityConfidence.HIGH,
        evidence=(evidence,),
        evidence_version=f"version-{index}",
    )


class PersonalRealityProjectionTests(unittest.TestCase):
    def test_complete_set_is_counted_and_ordered_before_surface_bound(self):
        items = tuple(
            item(
                index,
                RealityClassification.NEEDS_ACTION
                if index in {10, 12}
                else RealityClassification.UPCOMING_NOT_ACTIONABLE,
            )
            for index in range(15)
        )
        reality = RealityProjection(
            canonical_project_id="project-arbitrary",
            canonical_project_key="arbitrary-project",
            evaluated_at=NOW,
            overall_classification=RealityClassification.NEEDS_ACTION,
            items=items,
            total_count=15,
            returned_count=15,
            item_limit=15,
            classification_counts={"needs_action": 2, "upcoming_not_actionable": 13},
            complete_evidence=True,
        )
        projection = personal_reality_service.build(
            (SimpleNamespace(reality=reality),),
            evaluated_at=NOW,
            item_limit=3,
        )

        self.assertEqual(projection.schema_version, 1)
        self.assertEqual(projection.total_count, 15)
        self.assertEqual(projection.returned_count, 3)
        self.assertTrue(projection.truncated)
        self.assertEqual(
            projection.classification_counts,
            {"needs_action": 2, "upcoming_not_actionable": 13},
        )
        self.assertEqual(
            [value.classification for value in projection.items[:2]],
            [RealityClassification.NEEDS_ACTION, RealityClassification.NEEDS_ACTION],
        )

    def test_same_canonical_item_preserves_identity_evidence_and_schema(self):
        reality_item = item(1, RealityClassification.POTENTIAL_MISMATCH)
        reality = RealityProjection(
            canonical_project_id="project-arbitrary",
            canonical_project_key="arbitrary-project",
            evaluated_at=NOW,
            overall_classification=RealityClassification.POTENTIAL_MISMATCH,
            items=(reality_item,),
            total_count=1,
            returned_count=1,
            item_limit=12,
            classification_counts={"potential_mismatch": 1},
            complete_evidence=False,
            provider_diagnostics=("gmail: unavailable",),
        )

        projection = personal_reality_service.build(
            (SimpleNamespace(reality=reality),),
            evaluated_at=NOW,
        )

        self.assertIs(projection.items[0], reality_item)
        self.assertEqual(projection.items[0].evidence_version, "version-1")
        self.assertEqual(projection.items[0].evidence[0].evidence_id, "evidence:linear:record-01")
        self.assertEqual(projection.provider_diagnostics, ("gmail: unavailable",))
        self.assertFalse(projection.complete_evidence)

    def test_effective_correction_reprojects_classification_and_preserves_evidence(self):
        original = item(3, RealityClassification.NEEDS_ACTION)
        corrected = original.model_copy(
            update={
                "classification": RealityClassification.WAITING,
                "classification_reason": "Explicitly waiting on someone.",
                "effective_correction": EffectiveRealityCorrection(
                    correction_id="correction-3",
                    correction_type="waiting_on_someone",
                    attribution="morning_brief_user_correction",
                    effective_at=NOW,
                ),
            }
        )
        reality = RealityProjection(
            canonical_project_id="project-arbitrary",
            canonical_project_key="arbitrary-project",
            evaluated_at=NOW,
            overall_classification=RealityClassification.NEEDS_ACTION,
            items=(original,),
            total_count=1,
            returned_count=1,
            item_limit=12,
            classification_counts={"needs_action": 1},
            complete_evidence=True,
        )

        with patch(
            "app.personal_reality.morning_correction_service.apply_to_reality_items",
            return_value=(corrected,),
        ):
            effective = personal_reality_service.apply_corrections(
                reality,
                evaluated_at=NOW,
            )

        self.assertEqual(effective.overall_classification, RealityClassification.WAITING)
        self.assertEqual(effective.classification_counts, {"waiting": 1})
        self.assertEqual(effective.items[0].evidence, original.evidence)
        self.assertEqual(
            effective.items[0].effective_correction.correction_id,
            "correction-3",
        )


if __name__ == "__main__":
    unittest.main()
