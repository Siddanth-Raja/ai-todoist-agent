"""Run redacted authenticated verification of the Personal Gmail read boundary."""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.gmail_client import (  # noqa: E402
    GmailClient,
    GmailProviderState,
    PERSONAL_GMAIL_SCOPES,
)


def main() -> None:
    client = GmailClient(get_settings())
    health = client.check_health()
    print("Personal Gmail Live Verification")
    print("--------------------------------")
    print(f"Scope count: {len(PERSONAL_GMAIL_SCOPES)}")
    print(f"Scope is read-only: {PERSONAL_GMAIL_SCOPES == ('https://www.googleapis.com/auth/gmail.readonly',)}")
    print(f"Health state: {health.state.value}")
    if health.diagnostic:
        print(f"Health error code: {health.diagnostic.code}")
        raise SystemExit(1)
    print("Authenticated account role: personal")
    print(f"Profile message count available: {health.message_total is not None}")
    print(f"Profile thread count available: {health.thread_total is not None}")

    recent = client.list_recent_messages(max_messages=3)
    print(f"Recent read state: {recent.state.value}")
    print(f"Recent message records: {len(recent.messages)}")
    print(f"Pages fetched: {recent.pages_fetched}")
    print(f"Read complete: {recent.complete}")
    print(f"Read truncated: {recent.truncated}")
    print(f"Continuation token present: {recent.next_page_token is not None}")
    if recent.diagnostic:
        print(f"Recent read error code: {recent.diagnostic.code}")
        raise SystemExit(1)
    if not recent.messages:
        print("A real thread cannot be verified because the bounded recent read was empty.")
        raise SystemExit(1)
    parse_diagnostic_count = sum(
        len(message.parse_diagnostics) for message in recent.messages
    )
    attachment_count = sum(len(message.attachments) for message in recent.messages)
    body_count = sum(message.body_text is not None for message in recent.messages)
    print(f"Messages with bounded body text: {body_count}")
    print(f"Attachment metadata records: {attachment_count}")
    print(f"MIME diagnostic codes: {parse_diagnostic_count}")

    thread_id = recent.messages[0].identity.provider_thread_id
    if not thread_id:
        print("The sampled message did not preserve a thread identity.")
        raise SystemExit(1)
    thread = client.get_thread(thread_id)
    print(f"Thread read state: {thread.state.value}")
    print(f"Thread message records: {len(thread.messages)}")
    if thread.diagnostic:
        print(f"Thread read error code: {thread.diagnostic.code}")
        raise SystemExit(1)

    labels = client.list_labels()
    print(f"Label read state: {labels.state.value}")
    print(f"Label records: {len(labels.labels)}")
    if labels.diagnostic:
        print(f"Label read error code: {labels.diagnostic.code}")
        raise SystemExit(1)
    target = client.find_label("Old Stuff")
    print(f"Configured target label found: {target.matched_label is not None}")
    if target.diagnostic or target.matched_label is None:
        raise SystemExit(1)

    if health.state != GmailProviderState.CONNECTED:
        raise SystemExit(1)
    print("Provider mutation calls performed: 0")
    print("Live Personal Gmail read verification passed.")


if __name__ == "__main__":
    main()
