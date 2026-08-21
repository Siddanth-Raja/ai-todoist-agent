"""Run bounded, redacted live verification of TAMU Email analysis."""

from collections import Counter
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.email_analysis import (  # noqa: E402
    DEFAULT_ANALYSIS_MAX_MESSAGES,
    EmailAnalysisService,
    EmailAnalysisState,
)
from app.email_domain import EmailAccountRole  # noqa: E402
from app.gmail_client import GmailClient, GmailProviderState  # noqa: E402


ALLOWED_LIVE_STATES = {
    EmailAnalysisState.CONNECTED_ATTENTION,
    EmailAnalysisState.CONNECTED_QUIET,
    EmailAnalysisState.CONNECTED_EMPTY,
    EmailAnalysisState.DEGRADED_PARTIAL,
}


def _counter_values(counter: Counter) -> str:
    return ", ".join(f"{key}={counter[key]}" for key in sorted(counter)) or "none"


def main() -> None:
    result = EmailAnalysisService().analyze_recent(
        GmailClient.for_tamu(get_settings()),
        max_messages=DEFAULT_ANALYSIS_MAX_MESSAGES,
    )
    kinds = Counter(
        kind.value
        for candidate in result.attention_candidates
        for kind in candidate.attention_kinds
    )
    dispositions = Counter(
        assessment.organization_disposition.value for assessment in result.assessments
    )

    print("TAMU Email Analysis Live Verification")
    print("-------------------------------------")
    print(f"Account role: {result.account_role.value}")
    print(f"Explicit maximum messages: {DEFAULT_ANALYSIS_MAX_MESSAGES}")
    print("Full-inbox scan requested: False")
    print(f"Provider state: {result.provider_state.value}")
    print(f"Analysis state: {result.state.value}")
    print(f"Analyzed message records: {result.analyzed_message_count}")
    print(f"Unique thread/message assessments: {result.unique_thread_count}")
    print(f"Attention candidates: {len(result.attention_candidates)}")
    print(f"Candidate attention kinds: {_counter_values(kinds)}")
    print(f"Organization dispositions: {_counter_values(dispositions)}")
    print(f"Provider read complete: {result.complete}")
    print(f"Provider read truncated: {result.truncated}")
    if result.provider_diagnostic is not None:
        print(f"Provider diagnostic code: {result.provider_diagnostic.code}")
    print(f"External model calls performed: {result.interpretation_calls}")
    print(f"Provider mutation calls performed: {result.provider_mutation_calls}")

    if result.account_role != EmailAccountRole.AM:
        raise SystemExit(1)
    if result.state not in ALLOWED_LIVE_STATES:
        raise SystemExit(1)
    if result.provider_state not in {
        GmailProviderState.CONNECTED,
        GmailProviderState.CONNECTED_EMPTY,
    }:
        raise SystemExit(1)
    if result.analyzed_message_count > DEFAULT_ANALYSIS_MAX_MESSAGES:
        raise SystemExit(1)
    if result.interpretation_calls != 0 or result.provider_mutation_calls != 0:
        raise SystemExit(1)
    print("Bounded live TAMU Email analysis verification passed.")


if __name__ == "__main__":
    main()
