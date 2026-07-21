from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.email_domain import (  # noqa: E402
    EmailAccountRole,
    EmailMessageIdentity,
    EmailProviderAccountIdentity,
)
from app.gmail_client import (  # noqa: E402
    GmailLabel,
    GmailLabelResult,
    GmailMessagePage,
    GmailMessageRecord,
    GmailProviderState,
)
from app.gmail_review import (  # noqa: E402
    GMAIL_READONLY_SCOPE,
    MAX_READONLY_REVIEW_SCAN_MESSAGES,
    GmailReadonlyReviewError,
    GmailReadonlyReviewService,
    GmailReviewState,
)


NOW = datetime(2026, 7, 21, 18, 0, tzinfo=timezone.utc)
ACCOUNT = EmailProviderAccountIdentity(
    provider="gmail",
    account_role=EmailAccountRole.PERSONAL,
    provider_account_id="personal-review-account",
)


def record(
    message_id: str,
    *,
    sender: str = "Updates Service <no-reply@updates.example.test>",
    subject: str = "Action required: review account update",
    labels: tuple[str, ...] = ("INBOX", "UNREAD", "CATEGORY_UPDATES"),
) -> GmailMessageRecord:
    return GmailMessageRecord(
        identity=EmailMessageIdentity(
            account=ACCOUNT,
            provider_message_id=message_id,
            provider_thread_id=f"thread-{message_id}",
        ),
        sender=sender,
        subject=subject,
        internal_date=NOW,
        label_ids=labels,
        unread="UNREAD" in labels,
        body_accessed=False,
    )


def labels() -> tuple[GmailLabel, ...]:
    return (
        GmailLabel(provider_label_id="INBOX", name="INBOX", label_type="system"),
        GmailLabel(provider_label_id="UNREAD", name="UNREAD", label_type="system"),
        GmailLabel(
            provider_label_id="CATEGORY_UPDATES",
            name="CATEGORY_UPDATES",
            label_type="system",
        ),
        GmailLabel(
            provider_label_id="CATEGORY_PROMOTIONS",
            name="CATEGORY_PROMOTIONS",
            label_type="system",
        ),
        GmailLabel(
            provider_label_id="Label_action",
            name="PCOS/Action",
            label_type="user",
        ),
        GmailLabel(
            provider_label_id="Label_review",
            name="PCOS/Review",
            label_type="user",
        ),
    )


class FakeReadonlyClient:
    def __init__(self, messages: tuple[GmailMessageRecord, ...], label_values=None):
        self.messages = messages
        self.label_values = label_values or labels()
        self.calls = []

    def list_labels(self):
        self.calls.append(("list_labels", {}))
        return GmailLabelResult(
            state=GmailProviderState.CONNECTED,
            labels=self.label_values,
        )

    def list_message_metadata(self, **kwargs):
        self.calls.append(("list_message_metadata", kwargs))
        return GmailMessagePage(
            state=(
                GmailProviderState.CONNECTED
                if self.messages
                else GmailProviderState.CONNECTED_EMPTY
            ),
            messages=self.messages,
            next_page_token="bounded-continuation",
            complete=False,
            truncated=True,
            pages_fetched=1,
            result_size_estimate=500,
        )


class GmailReadonlyReviewTests(unittest.TestCase):
    def setUp(self):
        self.service = GmailReadonlyReviewService()

    def test_load_builds_bounded_body_free_real_review_and_excludes_protected_mail(self):
        client = FakeReadonlyClient(
            (
                record("action-message"),
                record(
                    "promotion-message",
                    sender="Newsletter <newsletter@offers.example.test>",
                    subject="Weekend sale and promotion",
                    labels=("INBOX", "CATEGORY_PROMOTIONS"),
                ),
                record(
                    "human-message",
                    sender="Trusted Person <person@example.test>",
                    subject="Action required: personal response",
                    labels=("INBOX",),
                ),
                record(
                    "important-message",
                    labels=("INBOX", "IMPORTANT", "CATEGORY_UPDATES"),
                ),
                record(
                    "financial-message",
                    sender="Small Cap Stocks <updates@newsletter.example.test>",
                    subject="Latest opportunity with recent news",
                ),
                record(
                    "address-only-message",
                    sender="no-reply@updates.example.test",
                ),
            )
        )

        surface = self.service.load(client)

        self.assertEqual(surface.state, GmailReviewState.READY)
        self.assertEqual(surface.configured_scope, GMAIL_READONLY_SCOPE)
        self.assertEqual(surface.source_issue, "SID-230")
        self.assertEqual(surface.source_label, "INBOX")
        self.assertEqual(len(surface.targets), 2)
        self.assertLessEqual(len(surface.targets), 10)
        self.assertEqual(
            {item.name for item in surface.labels},
            {"PCOS/Action", "PCOS/Review"},
        )
        self.assertTrue(all(item.sender_domain.endswith(".test") for item in surface.targets))
        self.assertTrue(all(item.current_labels for item in surface.targets))
        self.assertTrue(all(item.selection_reason for item in surface.targets))
        self.assertEqual(surface.provider_evidence.body_requests, 0)
        self.assertEqual(surface.provider_evidence.full_inventory_scans, 0)
        self.assertEqual(surface.provider_evidence.provider_mutation_calls, 0)
        exclusions = {item.reason: item.count for item in surface.exclusions}
        self.assertEqual(exclusions["direct_human"], 1)
        self.assertEqual(exclusions["provider_important"], 1)
        self.assertEqual(exclusions["financial"], 1)
        self.assertEqual(exclusions["incomplete_review_metadata"], 1)
        rendered = surface.model_dump_json()
        self.assertNotIn("action-message", rendered)
        self.assertNotIn("thread-action-message", rendered)
        self.assertNotIn("no-reply@updates.example.test", rendered)
        call = next(value for name, value in client.calls if name == "list_message_metadata")
        self.assertEqual(call["max_messages"], MAX_READONLY_REVIEW_SCAN_MESSAGES)
        self.assertEqual(call["query"], "-has:attachment")
        self.assertEqual(call["label_ids"], ("INBOX",))
        self.assertFalse(hasattr(client, "inventory_label_messages"))

    def test_selection_reloads_and_seals_exact_label_manifest_without_action(self):
        client = FakeReadonlyClient((record("action-message"),))
        surface = self.service.load(client)
        label = surface.labels[0]
        target = surface.targets[0]

        sealed = self.service.seal_selection(
            client,
            expected_snapshot_fingerprint=surface.snapshot_fingerprint,
            label_token=label.label_token,
            selected_message_tokens=(target.message_token,),
        )

        self.assertTrue(sealed.hand_reviewed)
        self.assertTrue(sealed.stale_state_revalidated)
        self.assertFalse(sealed.executable)
        self.assertEqual(sealed.provider_mutation_calls, 0)
        self.assertEqual(sealed.exact_message_count, 1)
        self.assertEqual(sealed.exact_thread_count, 1)
        self.assertEqual(sealed.label.name, "PCOS/Action")
        self.assertEqual(len(sealed.selection_fingerprint), 64)
        self.assertEqual(len(sealed.manifest_fingerprint), 64)
        self.assertEqual(
            [name for name, _value in client.calls].count("list_message_metadata"),
            2,
        )

    def test_sealed_review_builds_exact_existing_label_canary_without_executing(self):
        live_labels = (*labels(), GmailLabel(
            provider_label_id="Label_notes",
            name="Notes",
            label_type="user",
        ))
        client = FakeReadonlyClient((record("action-message"),), label_values=live_labels)
        surface = self.service.load(client)
        label = next(item for item in surface.labels if item.name == "Notes")
        target = surface.targets[0]

        sealed = self.service.build_canary_proposal(
            client,
            expected_snapshot_fingerprint=surface.snapshot_fingerprint,
            label_token=label.label_token,
            selected_message_tokens=(target.message_token,),
        )

        self.assertEqual(sealed.payload.action_type.value, "gmail_apply_label")
        self.assertEqual(sealed.payload.label.name, "Notes")
        self.assertEqual(sealed.payload.label.provider_label_id, "Label_notes")
        self.assertTrue(sealed.payload.canary)
        self.assertTrue(sealed.payload.hand_reviewed)
        self.assertEqual(len(sealed.payload.manifest.targets), 1)
        self.assertEqual(
            sealed.payload.manifest.selection_fingerprint,
            sealed.preview.manifest_fingerprint,
        )
        self.assertIn(sealed.preview.selection_fingerprint, sealed.idempotency_key)

    def test_prior_seal_survives_new_mail_only_when_exact_target_state_matches(self):
        client = FakeReadonlyClient((record("first"), record("second")))
        old_surface = self.service.load(client)
        label = old_surface.labels[0]
        selected = old_surface.targets[1]
        old_seal = self.service.seal_selection(
            client,
            expected_snapshot_fingerprint=old_surface.snapshot_fingerprint,
            label_token=label.label_token,
            selected_message_tokens=(selected.message_token,),
        )
        prior_tokens = tuple(item.message_token for item in old_surface.targets)
        client.messages = (record("new-arrival"), record("first"), record("second"))

        preserved = self.service.build_canary_proposal(
            client,
            expected_snapshot_fingerprint=old_surface.snapshot_fingerprint,
            expected_selection_fingerprint=old_seal.selection_fingerprint,
            label_token=label.label_token,
            selected_message_tokens=(selected.message_token,),
            prior_review_message_tokens=prior_tokens,
        )

        self.assertEqual(
            preserved.preview.selection_fingerprint,
            old_seal.selection_fingerprint,
        )
        self.assertEqual(len(preserved.payload.manifest.targets), 1)

        client.messages = (
            record("new-arrival"),
            record("first"),
            record("second", labels=("INBOX", "CATEGORY_UPDATES")),
        )
        with self.assertRaisesRegex(GmailReadonlyReviewError, "did not match"):
            self.service.build_canary_proposal(
                client,
                expected_snapshot_fingerprint=old_surface.snapshot_fingerprint,
                expected_selection_fingerprint=old_seal.selection_fingerprint,
                label_token=label.label_token,
                selected_message_tokens=(selected.message_token,),
                prior_review_message_tokens=prior_tokens,
            )

    def test_selection_rejects_stale_duplicate_unknown_and_label_mismatch(self):
        client = FakeReadonlyClient((record("action-message"),))
        surface = self.service.load(client)
        label = surface.labels[0]
        target = surface.targets[0]

        with self.assertRaisesRegex(GmailReadonlyReviewError, "unique reviewed"):
            self.service.seal_selection(
                client,
                expected_snapshot_fingerprint=surface.snapshot_fingerprint,
                label_token=label.label_token,
                selected_message_tokens=(target.message_token, target.message_token),
            )

        client.messages = (record("different-message"),)
        with self.assertRaisesRegex(GmailReadonlyReviewError, "snapshot changed"):
            self.service.seal_selection(
                client,
                expected_snapshot_fingerprint=surface.snapshot_fingerprint,
                label_token=label.label_token,
                selected_message_tokens=(target.message_token,),
            )

    def test_review_fails_closed_when_no_existing_supported_label_exists(self):
        client = FakeReadonlyClient(
            (record("action-message"),),
            label_values=tuple(item for item in labels() if item.label_type == "system"),
        )

        surface = self.service.load(client)

        self.assertEqual(surface.state, GmailReviewState.EMPTY)
        self.assertEqual(surface.labels, ())
        self.assertEqual(surface.targets, ())
        self.assertEqual(surface.provider_evidence.provider_mutation_calls, 0)


if __name__ == "__main__":
    unittest.main()
