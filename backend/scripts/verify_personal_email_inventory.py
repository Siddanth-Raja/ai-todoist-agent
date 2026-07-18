"""Run the redacted authenticated SID-230 full Personal Gmail inventory gate."""

from collections import Counter
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.email_inventory import (  # noqa: E402
    EmailInventoryService,
    EmailOrganizationProposalService,
)
from app.gmail_client import (  # noqa: E402
    GMAIL_READONLY_SCOPE,
    GmailClient,
    PERSONAL_GMAIL_SCOPES,
)


def _print_inventory(name, inventory) -> None:
    print(f"{name} exact provider label resolved: {inventory.state.value != 'label_not_found'}")
    print(f"{name} state: {inventory.state.value}")
    print(f"{name} complete: {inventory.complete}")
    print(f"{name} message records: {inventory.message_count}")
    print(f"{name} unique threads: {inventory.unique_thread_count}")
    print(f"{name} duplicate provider references: {inventory.duplicate_message_count}")
    print(f"{name} unread: {inventory.unread_count}")
    print(f"{name} important: {inventory.important_count}")
    print(f"{name} protected: {inventory.protected_count}")
    print(f"{name} uncertain: {inventory.uncertain_count}")
    print(f"{name} date range available: {inventory.earliest_message_at is not None and inventory.latest_message_at is not None}")
    print(f"{name} top sender buckets: {len(inventory.top_senders)}")
    print(f"{name} top domain buckets: {len(inventory.top_domains)}")
    print(f"{name} existing label buckets: {len(inventory.existing_labels)}")
    print(f"{name} coarse type buckets: {len(inventory.coarse_types)}")
    print(f"{name} provider pages: {inventory.pages_fetched}")
    print(f"{name} attachment-evidence pages: {inventory.attachment_pages_fetched}")
    print(f"{name} provider size estimate available: {inventory.result_size_estimate is not None}")
    print(f"{name} metadata requests: {inventory.metadata_requests}")
    print(f"{name} transient provider retries: {inventory.provider_retry_count}")
    print(f"{name} body requests: {inventory.body_requests}")
    print(f"{name} remaining cursor present: {inventory.remaining_cursor_present}")
    print(f"{name} attachment cursor present: {inventory.attachment_cursor_present}")
    print(f"{name} stable fingerprint present: {bool(inventory.stable_fingerprint)}")
    if inventory.provider_diagnostic is not None:
        print(f"{name} provider diagnostic code: {inventory.provider_diagnostic.code}")


def main() -> None:
    client = GmailClient(get_settings())
    inventory = EmailInventoryService().inventory_personal(client)
    proposals = EmailOrganizationProposalService().propose(inventory)

    operation_counts = Counter(item.operation.value for item in proposals.proposals)
    organization_labels = Counter(
        item.organization_label.value
        for item in proposals.proposals
        if item.organization_label is not None
    )
    topic_labels = Counter(
        value.value for item in proposals.proposals for value in item.topic_labels
    )

    print("Personal Email Full Inventory Live Verification")
    print("-----------------------------------------------")
    print(f"Configured scope count: {len(PERSONAL_GMAIL_SCOPES)}")
    print(f"Exact Gmail readonly scope: {PERSONAL_GMAIL_SCOPES == (GMAIL_READONLY_SCOPE,)}")
    _print_inventory("INBOX", inventory.inbox)
    _print_inventory("Old Stuff", inventory.old_stuff)
    print(f"Both exact-label inventories complete: {inventory.complete}")
    print(f"Combined stable fingerprint present: {bool(inventory.stable_fingerprint)}")
    print(f"Advisory proposal batches: {len(proposals.proposals)}")
    print(f"Proposal operation counts: {dict(sorted(operation_counts.items()))}")
    print(f"Organization-label counts: {dict(sorted(organization_labels.items()))}")
    print(f"Grounded topic-label counts: {dict(sorted(topic_labels.items()))}")
    print(f"Selected message total across distinct proposals: {sum(item.exact_message_count for item in proposals.proposals)}")
    print(f"Every proposal requires approval: {all(item.approval_required for item in proposals.proposals)}")
    print(f"Every proposal is non-executable: {all(not item.executable for item in proposals.proposals)}")
    print(f"External model calls performed: {inventory.external_model_calls + proposals.external_model_calls}")
    print(f"Memory writes performed: {inventory.memory_writes}")
    print(f"Provider mutation calls performed: {inventory.provider_mutation_calls + proposals.provider_mutation_calls}")

    if not inventory.complete:
        raise SystemExit(1)
    if inventory.inbox.body_requests != 0 or inventory.old_stuff.body_requests != 0:
        raise SystemExit(1)
    if inventory.external_model_calls or proposals.external_model_calls:
        raise SystemExit(1)
    if inventory.memory_writes:
        raise SystemExit(1)
    if inventory.provider_mutation_calls or proposals.provider_mutation_calls:
        raise SystemExit(1)
    if any(item.executable or not item.approval_required for item in proposals.proposals):
        raise SystemExit(1)
    print("Full read-only Personal Gmail inventory verification passed.")


if __name__ == "__main__":
    main()
