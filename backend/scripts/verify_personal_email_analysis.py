"""Run bounded, redacted live verification of SID-146 Personal Email analysis."""

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
from app.gmail_client import GmailClient, GmailProviderState  # noqa: E402


ALLOWED_LIVE_STATES = {
    EmailAnalysisState.CONNECTED_ATTENTION,
    EmailAnalysisState.CONNECTED_QUIET,
    EmailAnalysisState.CONNECTED_EMPTY,
    EmailAnalysisState.DEGRADED_PARTIAL,
}


def _counter_values(counter: Counter) -> str:
    return ", ".join(
        f"{key}={counter[key]}" for key in sorted(counter)
    ) or "none"


def main() -> None:
    client = GmailClient(get_settings())
    result = EmailAnalysisService().analyze_recent(
        client,
        max_messages=DEFAULT_ANALYSIS_MAX_MESSAGES,
    )

    candidate_kinds = Counter(
        kind.value
        for candidate in result.attention_candidates
        for kind in candidate.attention_kinds
    )
    dispositions = Counter(
        assessment.organization_disposition.value
        for assessment in result.assessments
    )
    importance = Counter(
        assessment.importance.value for assessment in result.assessments
    )
    urgency = Counter(
        assessment.urgency.value for assessment in result.assessments
    )
    surfaces = Counter(
        assessment.surface_decision.value for assessment in result.assessments
    )
    associations = Counter(
        assessment.project_association.state.value
        for assessment in result.assessments
    )
    evidence_categories = Counter(
        category.value
        for assessment in result.assessments
        for category in assessment.evidence_categories
    )
    confidence = Counter(
        f"{assessment.confidence:.2f}" for assessment in result.assessments
    )

    print("Personal Email Analysis Live Verification")
    print("-----------------------------------------")
    print(f"Explicit maximum messages: {DEFAULT_ANALYSIS_MAX_MESSAGES}")
    print("Full-inbox scan requested: False")
    print("Old Stuff label scan requested: False")
    print(f"Provider state: {result.provider_state.value}")
    print(f"Analysis state: {result.state.value}")
    print(f"Analyzed message records: {result.analyzed_message_count}")
    print(f"Unique thread/message assessments: {result.unique_thread_count}")
    print(f"Thread deduplications: {result.deduplication_count}")
    print(f"Attention candidates: {len(result.attention_candidates)}")
    print(f"Quiet assessments: {result.quiet_assessment_count}")
    print(f"Uncertain review assessments: {result.uncertain_review_count}")
    print(f"Provider pages fetched: {result.pages_fetched}")
    print(f"Provider read complete: {result.complete}")
    print(f"Provider read truncated: {result.truncated}")
    print(f"Candidate attention kinds: {_counter_values(candidate_kinds)}")
    print(f"Organization dispositions: {_counter_values(dispositions)}")
    print(f"Importance levels: {_counter_values(importance)}")
    print(f"Urgency levels: {_counter_values(urgency)}")
    print(f"Surface decisions: {_counter_values(surfaces)}")
    print(f"Project association states: {_counter_values(associations)}")
    print(f"Evidence categories: {_counter_values(evidence_categories)}")
    print(f"Assessment confidence values: {_counter_values(confidence)}")
    if result.provider_diagnostic is not None:
        print(f"Provider diagnostic code: {result.provider_diagnostic.code}")
    print(f"External model calls performed: {result.interpretation_calls}")
    print(f"Provider mutation calls performed: {result.provider_mutation_calls}")

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
    print("Bounded live Personal Email analysis verification passed.")


if __name__ == "__main__":
    main()
