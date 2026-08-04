from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.activity_domain import (  # noqa: E402
    ActivityFreshness,
    MeaningfulActivityCategory,
    MeaningfulActivityEvent,
    activity_contract_projection,
)
from app.storage import (  # noqa: E402
    ensure_database,
    get_latest_project_focus_intent,
    list_activity,
    log_activity,
    log_meaningful_activity,
    save_project_focus_intent,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 4, 15, 0, tzinfo=UTC)


def meaningful_event(**updates):
    values = {
        "category": MeaningfulActivityCategory.WORK_COMPLETED,
        "canonical_project_id": "project-pcos-ai-todoist-agent",
        "source_provider": "linear",
        "provider_record_type": "issue",
        "provider_record_id": "issue-138",
        "source_timestamp": NOW - timedelta(hours=1),
        "observed_at": NOW,
        "freshness": ActivityFreshness.FRESH,
        "evidence_key": "linear:issue-138:completed:v1",
        "summary": "Completed SID-138",
        "attributable_payload": {
            "provider_identifier": "SID-138",
            "provider_url": "https://linear.app/example/SID-138",
        },
    }
    values.update(updates)
    return MeaningfulActivityEvent(**values)


class MeaningfulActivityContractTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.env = patch.dict(
            os.environ,
            {"APP_DB_PATH": os.path.join(self.tempdir.name, "activity.sqlite3")},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_database()

    def test_typed_event_requires_timezone_aware_attribution(self):
        with self.assertRaises(ValidationError):
            meaningful_event(source_timestamp=datetime(2026, 8, 4, 14, 0))
        with self.assertRaises(ValidationError):
            meaningful_event(observed_at=datetime(2026, 8, 4, 15, 0))

    def test_provider_record_type_and_identity_are_atomic(self):
        with self.assertRaises(ValidationError):
            meaningful_event(provider_record_id=None)
        with self.assertRaises(ValidationError):
            meaningful_event(provider_record_type=None)

    def test_typed_activity_rejects_secrets_raw_payloads_and_unbounded_data(self):
        for sensitive in ("access_token", "refresh_token", "email_body", "raw_payload"):
            with self.subTest(sensitive=sensitive), self.assertRaises(ValidationError):
                meaningful_event(attributable_payload={sensitive: "do-not-store"})
        with self.assertRaises(ValidationError):
            meaningful_event(attributable_payload={"summary": "x" * 20_001})

    def test_low_level_reads_and_ui_interactions_are_not_categories(self):
        for value in ("get_request", "provider_poll", "health_check", "page_view", "ui_click"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                meaningful_event(category=value)

    def test_typed_activity_round_trip_preserves_canonical_and_provider_identity(self):
        created = log_meaningful_activity(meaningful_event())
        listed = list_activity(limit=10)

        self.assertEqual(created["meaningful_event"]["category"], "work_completed")
        self.assertEqual(
            created["meaningful_event"]["canonical_project_id"],
            "project-pcos-ai-todoist-agent",
        )
        self.assertEqual(created["meaningful_event"]["provider_record_id"], "issue-138")
        self.assertEqual(created["activity_schema_version"], 1)
        self.assertFalse(created["legacy_unstructured"])
        self.assertEqual(listed[0]["meaningful_event"], created["meaningful_event"])

    def test_legacy_activity_remains_readable_and_distinguishable(self):
        legacy = log_activity(
            action_type="task_created",
            title="Task created: legacy",
            source="todoist",
            payload={"task": {"id": "legacy-task"}},
        )

        self.assertEqual(legacy["type"], "task_created")
        self.assertEqual(legacy["payload"]["task"]["id"], "legacy-task")
        self.assertIsNone(legacy["meaningful_event"])
        self.assertIsNone(legacy["activity_schema_version"])
        self.assertTrue(legacy["legacy_unstructured"])

    def test_unknown_future_activity_schema_is_readable_as_unstructured(self):
        projected = activity_contract_projection(
            {
                "id": "future-version",
                "payload": {
                    "activity_event": {
                        **meaningful_event().model_dump(mode="json"),
                        "schema_version": 2,
                    }
                },
            }
        )

        self.assertIsNone(projected["meaningful_event"])
        self.assertTrue(projected["legacy_unstructured"])

    def test_unbounded_internal_activity_read_preserves_all_evidence(self):
        for index in range(205):
            log_activity(
                action_type="legacy_event",
                title=f"Legacy event {index}",
            )
        self.assertEqual(len(list_activity(limit=200)), 200)
        self.assertEqual(len(list_activity(limit=None)), 205)

    def test_explicit_pause_requires_review_or_expiry_and_persists_as_pcos_state(self):
        with self.assertRaises(ValidationError):
            save_project_focus_intent(
                canonical_project_id="project-xo",
                confirmed_state="intentionally_paused",
                reason="Waiting for a deliberate restart",
                confirmed_at=NOW,
            )

        saved = save_project_focus_intent(
            canonical_project_id="project-xo",
            confirmed_state="intentionally_paused",
            reason="Pause until the next review",
            confirmed_at=NOW,
            review_after=NOW + timedelta(days=14),
            review_trigger="new completed work or a reviewed focus decision",
        )
        loaded = get_latest_project_focus_intent("project-xo")

        self.assertEqual(loaded["id"], saved["id"])
        self.assertEqual(loaded["confirmed_state"], "intentionally_paused")
        self.assertEqual(loaded["review_after"], (NOW + timedelta(days=14)).isoformat())


if __name__ == "__main__":
    unittest.main()
