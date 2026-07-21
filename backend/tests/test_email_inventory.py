from pathlib import Path
from datetime import datetime, timezone
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.email_domain import (  # noqa: E402
    EmailAccountRole,
    EmailMessageIdentity,
    EmailProviderAccountIdentity,
)
from app.email_inventory import (  # noqa: E402
    EmailInventoryService,
    EmailInventoryState,
    EmailOrganizationProposalService,
    FutureOrganizationOperation,
    GroundedTopicLabel,
    InventoryCoarseType,
    InventoryProtectionReason,
    OLD_STUFF_LABEL_NAME,
    OrganizationLabel,
)
from app.gmail_client import (  # noqa: E402
    GmailInventoryPage,
    GmailLabel,
    GmailLabelResult,
    GmailMessageRecord,
    GmailProviderDiagnostic,
    GmailProviderState,
)
from tests.test_gmail_provider import (  # noqa: E402
    FakeService,
    client,
    headers,
)


ACCOUNT = EmailProviderAccountIdentity(
    provider="gmail",
    account_role=EmailAccountRole.PERSONAL,
    provider_account_id="personal-test-account",
)


def metadata_message(
    message_id: str,
    thread_id: str,
    *,
    subject: str = "Weekly newsletter sale",
    sender: str = "Updates <updates@example.test>",
    labels: tuple[str, ...] = ("INBOX", "UNREAD", "CATEGORY_PROMOTIONS"),
):
    values = headers()
    values = [
        {"name": item["name"], "value": item["value"]}
        for item in values
        if item["name"] not in {"From", "Subject"}
    ]
    values.extend(
        [
            {"name": "From", "value": sender},
            {"name": "Subject", "value": subject},
        ]
    )
    return {
        "id": message_id,
        "threadId": thread_id,
        "historyId": "history-test",
        "internalDate": "1784304000000",
        "labelIds": list(labels),
        "sizeEstimate": 128,
        "payload": {
            "mimeType": "text/plain",
            "headers": values,
            "body": {"size": 50},
        },
    }


def record(
    message_id: str,
    thread_id: str,
    *,
    subject: str = "Weekly newsletter sale",
    sender: str = "Updates <updates@example.test>",
    labels: tuple[str, ...] = ("INBOX", "UNREAD", "CATEGORY_PROMOTIONS"),
    attachment: bool = False,
):
    raw = metadata_message(
        message_id,
        thread_id,
        subject=subject,
        sender=sender,
        labels=labels,
    )
    header_map = {item["name"]: item["value"] for item in raw["payload"]["headers"]}
    return GmailMessageRecord(
        identity=EmailMessageIdentity(
            account=ACCOUNT,
            provider_message_id=message_id,
            provider_thread_id=thread_id,
        ),
        sender=header_map["From"],
        recipients=("Account Owner",),
        subject=header_map["Subject"],
        internal_date=None,
        message_date=datetime(2026, 7, 17, 16, 0, tzinfo=timezone.utc),
        label_ids=labels,
        unread="UNREAD" in labels,
        has_attachment=attachment,
        body_accessed=False,
    )


class FakeInventoryClient:
    def __init__(self, inbox_page, old_page, *, labels=None):
        self.pages = {"INBOX": inbox_page, "old-stuff-id": old_page}
        self.labels = labels or (
            GmailLabel(provider_label_id="INBOX", name="INBOX", label_type="system"),
            GmailLabel(
                provider_label_id="old-stuff-id",
                name=OLD_STUFF_LABEL_NAME,
                label_type="user",
            ),
        )
        self.calls = []

    def list_labels(self):
        self.calls.append(("list_labels", None))
        return GmailLabelResult(state=GmailProviderState.CONNECTED, labels=self.labels)

    def inventory_label_messages(self, *, provider_label_id):
        self.calls.append(("inventory_label_messages", provider_label_id))
        return self.pages[provider_label_id]


def page(*messages, complete=True, diagnostic=None):
    return GmailInventoryPage(
        state=(
            GmailProviderState.CONNECTED
            if complete
            else GmailProviderState.PROVIDER_FAILURE
        ),
        messages=messages,
        complete=complete,
        pages_fetched=2,
        attachment_pages_fetched=1,
        metadata_requests=len(messages),
        next_page_token=(None if complete else "opaque-cursor"),
        diagnostic=diagnostic,
    )


class GmailFullInventoryProviderTests(unittest.TestCase):
    def test_transient_inventory_reads_retry_with_a_strict_bound(self):
        class FlakyRequest:
            def __init__(self):
                self.calls = 0

            def execute(self):
                self.calls += 1
                if self.calls == 1:
                    raise OSError("synthetic transient provider failure")
                return {"messages": []}

        gmail, _, _ = client(FakeService())
        request = FlakyRequest()

        payload, diagnostic, retries = gmail._execute_inventory_read(request)

        self.assertEqual(payload, {"messages": []})
        self.assertIsNone(diagnostic)
        self.assertEqual(retries, 1)
        self.assertEqual(request.calls, 2)

    def test_multipage_inventory_deduplicates_and_never_reads_bodies(self):
        service = FakeService(
            list_pages=[
                {
                    "messages": [
                        {"id": "m1", "threadId": "t1"},
                        {"id": "m2", "threadId": "t2"},
                    ],
                    "nextPageToken": "page-2",
                    "resultSizeEstimate": 3,
                },
                {
                    "messages": [
                        {"id": "m2", "threadId": "t2"},
                        {"id": "m3", "threadId": "t3"},
                    ]
                },
                {"messages": [{"id": "m3", "threadId": "t3"}]},
            ],
            message_details={
                value: metadata_message(value, f"t{index}")
                for index, value in enumerate(("m1", "m2", "m3"), start=1)
            },
        )
        gmail, _, _ = client(service)

        result = gmail.inventory_label_messages(provider_label_id="INBOX")

        self.assertTrue(result.complete)
        self.assertEqual(result.pages_fetched, 2)
        self.assertEqual(result.attachment_pages_fetched, 1)
        self.assertEqual(result.duplicate_message_count, 1)
        self.assertEqual(result.metadata_requests, 3)
        self.assertEqual(result.body_requests, 0)
        self.assertEqual([item.has_attachment for item in result.messages], [False, False, True])
        get_calls = [value for name, value in service.calls if name == "messages.get"]
        self.assertEqual(len(get_calls), 3)
        self.assertTrue(all(value["format"] == "metadata" for value in get_calls))
        self.assertTrue(all("metadataHeaders" in value for value in get_calls))
        self.assertTrue(all(item.body_text is None for item in result.messages))
        self.assertTrue(all(not item.body_accessed for item in result.messages))
        self.assertFalse(any("attachments.get" == name for name, _ in service.calls))

    def test_repeated_cursor_is_incomplete_and_fetches_no_metadata(self):
        service = FakeService(
            list_pages=[
                {
                    "messages": [{"id": "m1", "threadId": "t1"}],
                    "nextPageToken": "repeat",
                },
                {"messages": [], "nextPageToken": "repeat"},
                {"messages": []},
            ]
        )
        gmail, _, _ = client(service)

        result = gmail.inventory_label_messages(provider_label_id="INBOX")

        self.assertFalse(result.complete)
        self.assertEqual(result.state, GmailProviderState.MALFORMED_RESPONSE)
        self.assertEqual(result.diagnostic.code, "malformed_response")
        self.assertEqual(result.metadata_requests, 0)
        self.assertTrue(result.next_page_token)

    def test_malformed_metadata_retains_partial_evidence_but_never_completes(self):
        service = FakeService(
            list_pages=[
                {
                    "messages": [
                        {"id": "m1", "threadId": "t1"},
                        {"id": "m2", "threadId": "t2"},
                    ]
                },
                {"messages": []},
            ],
            message_details={
                "m1": metadata_message("m1", "t1"),
                "m2": {"id": "m2", "threadId": "t2"},
            },
        )
        gmail, _, _ = client(service)

        result = gmail.inventory_label_messages(provider_label_id="INBOX")

        self.assertFalse(result.complete)
        self.assertEqual(result.state, GmailProviderState.MALFORMED_RESPONSE)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.metadata_requests, 2)
        self.assertEqual(result.body_requests, 0)

    def test_exact_label_lookup_does_not_case_fold(self):
        service = FakeService(
            labels_payload={
                "labels": [
                    {"id": "wrong", "name": "old stuff", "type": "user"},
                    {"id": "exact", "name": "Old Stuff", "type": "user"},
                ]
            }
        )
        gmail, _, _ = client(service)

        self.assertEqual(gmail.find_label_exact("Old Stuff").matched_label.provider_label_id, "exact")
        self.assertIsNone(gmail.find_label_exact("OLD STUFF").matched_label)


class EmailInventoryAndProposalTests(unittest.TestCase):
    def test_inventory_summarizes_both_exact_labels_and_is_deterministic(self):
        inbox_page = page(
            record("m1", "thread-shared"),
            record("m2", "thread-shared", labels=("INBOX", "CATEGORY_PROMOTIONS")),
        )
        old_page = page(
            record(
                "m3",
                "thread-old",
                labels=("old-stuff-id", "CATEGORY_PROMOTIONS"),
            )
        )
        service = EmailInventoryService()

        first = service.inventory_personal(FakeInventoryClient(inbox_page, old_page))
        second = service.inventory_personal(FakeInventoryClient(inbox_page, old_page))

        self.assertTrue(first.complete)
        self.assertEqual(first.stable_fingerprint, second.stable_fingerprint)
        self.assertEqual(first.inbox.message_count, 2)
        self.assertEqual(first.inbox.unique_thread_count, 1)
        self.assertEqual(first.inbox.unread_count, 1)
        self.assertEqual(first.inbox.body_requests, 0)
        self.assertEqual(first.old_stuff.label.exact_name, "Old Stuff")
        self.assertEqual(first.provider_mutation_calls, 0)
        self.assertEqual(first.inbox.messages[0].sender_display, "Updates")
        self.assertEqual(first.inbox.messages[0].sender_domain, "example.test")
        self.assertEqual(first.inbox.messages[0].subject, "Weekly newsletter sale")
        self.assertEqual(
            {item.provider_label_id for item in first.label_catalog},
            {"INBOX", "old-stuff-id"},
        )
        self.assertNotIn("updates@example.test", first.model_dump_json())
        self.assertNotIn("Account Owner", first.model_dump_json())

    def test_protected_and_uncertain_messages_are_excluded_by_default(self):
        safe = record("safe", "safe-thread")
        important = record(
            "important",
            "important-thread",
            labels=("INBOX", "IMPORTANT", "CATEGORY_PROMOTIONS"),
        )
        attachment = record("attachment", "attachment-thread", attachment=True)
        uncertain = record(
            "uncertain",
            "uncertain-thread",
            subject="",
            sender="",
            labels=("INBOX",),
        )
        inventory = EmailInventoryService().inventory_personal(
            FakeInventoryClient(page(safe, important, attachment, uncertain), page())
        )

        proposals = EmailOrganizationProposalService().propose(inventory)

        selected = {
            value
            for proposal in proposals.proposals
            for target in proposal.targets
            for value in target.provider_message_ids
        }
        self.assertEqual(selected, {"safe"})
        important_fact = next(item for item in inventory.inbox.messages if item.identity.provider_message_id == "important")
        self.assertIn(InventoryProtectionReason.PROVIDER_IMPORTANT, important_fact.protection_reasons)
        attachment_fact = next(item for item in inventory.inbox.messages if item.identity.provider_message_id == "attachment")
        self.assertIn(InventoryProtectionReason.ATTACHMENT, attachment_fact.protection_reasons)
        uncertain_fact = next(item for item in inventory.inbox.messages if item.identity.provider_message_id == "uncertain")
        self.assertTrue(uncertain_fact.uncertain)
        self.assertIn(InventoryProtectionReason.UNCERTAIN, uncertain_fact.protection_reasons)
        self.assertTrue(all(proposal.uncertainty_count == 0 for proposal in proposals.proposals))

    def test_label_archive_and_mark_read_are_separate_advisory_batches(self):
        inventory = EmailInventoryService().inventory_personal(
            FakeInventoryClient(
                page(
                    record("m1", "shared"),
                    record("m2", "shared"),
                ),
                page(),
            )
        )

        result = EmailOrganizationProposalService().propose(inventory)
        operations = {item.operation for item in result.proposals}

        self.assertEqual(
            operations,
            {
                FutureOrganizationOperation.LABEL,
                FutureOrganizationOperation.ARCHIVE,
                FutureOrganizationOperation.MARK_READ,
            },
        )
        label = next(item for item in result.proposals if item.operation == FutureOrganizationOperation.LABEL)
        self.assertEqual(label.organization_label, OrganizationLabel.REVIEW)
        self.assertEqual(label.exact_message_count, 2)
        self.assertEqual(label.exact_thread_count, 1)
        self.assertTrue(label.approval_required)
        self.assertFalse(label.executable)
        self.assertEqual(label.provider_mutation_calls, 0)
        self.assertTrue(
            all(
                item.organization_label is None
                for item in result.proposals
                if item.operation != FutureOrganizationOperation.LABEL
            )
        )

    def test_grounded_topic_vocabulary_is_closed(self):
        travel = record(
            "travel",
            "travel-thread",
            subject="Flight itinerary newsletter sale",
            sender="Updates <updates@example.test>",
        )
        inventory = EmailInventoryService().inventory_personal(
            FakeInventoryClient(page(travel), page())
        )

        result = EmailOrganizationProposalService().propose(inventory)
        label = next(item for item in result.proposals if item.operation == FutureOrganizationOperation.LABEL)

        self.assertEqual(label.topic_labels, (GroundedTopicLabel.TRAVEL,))
        self.assertEqual(
            {item.value for item in GroundedTopicLabel},
            {"Finance", "School", "Freelance", "Travel"},
        )

    def test_every_required_sensitive_category_is_protected(self):
        messages = (
            record("security", "t-security", subject="Security alert sale"),
            record("finance", "t-finance", subject="Payment statement sale"),
            record("academic", "t-academic", subject="University course sale"),
            record("client", "t-client", subject="Client proposal sale"),
            record(
                "human",
                "t-human",
                subject="Personal hello",
                sender="Known Person <person@example.test>",
                labels=("INBOX",),
            ),
        )
        inventory = EmailInventoryService().inventory_personal(
            FakeInventoryClient(page(*messages), page())
        )
        facts = {
            item.identity.provider_message_id: item
            for item in inventory.inbox.messages
        }

        self.assertIn(InventoryProtectionReason.SECURITY, facts["security"].protection_reasons)
        self.assertIn(InventoryProtectionReason.FINANCIAL, facts["finance"].protection_reasons)
        self.assertIn(InventoryProtectionReason.ACADEMIC, facts["academic"].protection_reasons)
        self.assertIn(InventoryProtectionReason.CLIENT, facts["client"].protection_reasons)
        self.assertIn(InventoryProtectionReason.DIRECT_HUMAN, facts["human"].protection_reasons)
        selected = {
            value
            for proposal in EmailOrganizationProposalService().propose(inventory).proposals
            for target in proposal.targets
            for value in target.provider_message_ids
        }
        self.assertTrue(set(facts).isdisjoint(selected))

    def test_incomplete_inventory_never_produces_proposals(self):
        failure = GmailProviderDiagnostic(code="provider", message="Provider read failed.")
        inventory = EmailInventoryService().inventory_personal(
            FakeInventoryClient(page(record("m1", "t1"), complete=False, diagnostic=failure), page())
        )

        result = EmailOrganizationProposalService().propose(inventory)

        self.assertFalse(inventory.complete)
        self.assertEqual(inventory.inbox.state, EmailInventoryState.PROVIDER_FAILURE)
        self.assertTrue(inventory.inbox.remaining_cursor_present)
        self.assertEqual(result.proposals, ())

    def test_old_stuff_discovery_preserves_provider_exact_identity(self):
        inbox_page = page()
        old_page = page()
        client_value = FakeInventoryClient(
            inbox_page,
            old_page,
            labels=(
                GmailLabel(provider_label_id="INBOX", name="INBOX"),
                GmailLabel(provider_label_id="wrong", name="old stuff"),
            ),
        )
        client_value.pages["wrong"] = old_page

        inventory = EmailInventoryService().inventory_personal(client_value)

        self.assertTrue(inventory.complete)
        self.assertEqual(inventory.old_stuff.label.provider_label_id, "wrong")
        self.assertEqual(inventory.old_stuff.label.exact_name, "old stuff")

    def test_delete_and_trash_are_absent_from_domain_and_provider(self):
        forbidden = {"delete", "trash", "modify", "batch_modify"}

        self.assertTrue(
            forbidden.isdisjoint(item.value for item in FutureOrganizationOperation)
        )
        self.assertTrue(forbidden.isdisjoint(vars(EmailOrganizationProposalService)))
        from app.gmail_client import GmailClient

        self.assertTrue(forbidden.isdisjoint(vars(GmailClient)))
        self.assertNotIn("pending_action", OrganizationLabel.__members__)
        self.assertNotIn("provider_action", OrganizationLabel.__members__)

    def test_live_verifier_is_redacted_and_scope_stays_readonly(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "verify_personal_email_inventory.py"
        ).read_text()

        self.assertIn("GMAIL_READONLY_SCOPE", source)
        self.assertIn("Provider mutation calls performed", source)
        self.assertIn("External model calls performed", source)
        self.assertIn("Memory writes performed", source)
        self.assertNotIn("openai", source.casefold())
        self.assertNotIn("provider_message_id", source)
        self.assertNotIn("provider_thread_id", source)
        self.assertNotIn("body_text", source)
        self.assertNotIn(".modify(", source)
        self.assertNotIn(".trash(", source)
        self.assertNotIn(".delete(", source)


if __name__ == "__main__":
    unittest.main()
