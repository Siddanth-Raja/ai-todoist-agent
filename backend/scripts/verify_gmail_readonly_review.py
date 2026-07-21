"""Redacted live verification for the SID-231 Phase-A hand-review surface."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.gmail_client import GMAIL_READONLY_SCOPE, GmailClient  # noqa: E402
from app.gmail_review import (  # noqa: E402
    MAX_READONLY_REVIEW_TARGETS,
    GmailReadonlyReviewService,
    GmailReviewState,
)


def main() -> int:
    surface = GmailReadonlyReviewService().load(GmailClient(get_settings()))
    complete_cards = all(
        target.sender_display
        and "@" not in target.sender_display
        and target.sender_domain
        and target.subject
        and target.received_at
        and target.current_labels
        and target.selection_reason
        and target.message_token
        and target.thread_token
        for target in surface.targets
    )
    evidence = surface.provider_evidence
    safe = (
        surface.state == GmailReviewState.READY
        and surface.configured_scope == GMAIL_READONLY_SCOPE
        and 1 <= len(surface.targets) <= MAX_READONLY_REVIEW_TARGETS
        and bool(surface.labels)
        and complete_cards
        and evidence.body_requests == 0
        and evidence.full_inventory_scans == 0
        and evidence.external_model_calls == 0
        and evidence.memory_writes == 0
        and evidence.provider_mutation_calls == 0
        and not surface.executable
        and surface.oauth_change_required_before_execution
    )
    print(f"Review state: {surface.state.value}")
    print(f"Exact gmail.readonly scope: {surface.configured_scope == GMAIL_READONLY_SCOPE}")
    print(f"Bounded metadata records: {surface.scanned_message_count}")
    print(f"Review cards: {len(surface.targets)}")
    print(f"Existing eligible labels: {len(surface.labels)}")
    print(
        "Redacted exclusions: "
        + ", ".join(
            f"{item.reason}={item.count}" for item in surface.exclusions
        )
    )
    print(f"Every card has complete safe metadata: {complete_cards}")
    print(f"Continuation retained internally: {surface.next_page_available}")
    print(f"Body requests: {evidence.body_requests}")
    print(f"Full inventory scans: {evidence.full_inventory_scans}")
    print(f"External model calls: {evidence.external_model_calls}")
    print(f"Memory writes: {evidence.memory_writes}")
    print(f"Provider mutation calls: {evidence.provider_mutation_calls}")
    print(f"Executable before OAuth gate: {surface.executable}")
    print("Addresses, subjects, labels, message IDs, thread IDs, and OAuth values emitted: False")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
