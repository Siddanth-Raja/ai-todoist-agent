"""Bounded read-only Gmail hand-review surface for the SID-231 canary gate."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from enum import StrEnum
import hashlib
import hmac
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .action_domain import (
    ActionEvidence,
    GmailApplyLabelPayload,
    GmailExpectedMessageState,
    GmailMessageReviewMetadata,
    GmailOrganizationManifest,
    GmailReviewLabelIdentity,
    GmailUserLabelIdentity,
    gmail_manifest_fingerprint,
)
from .email_inventory import (
    InventoryCoarseType,
    InventoryMessageFact,
    inventory_fact_for_record,
)
from .gmail_client import (
    GMAIL_READONLY_SCOPE,
    GmailClient,
    GmailLabel,
    GmailProviderState,
)
from .gmail_organization import GMAIL_SYSTEM_LABEL_DISPLAY_NAMES


MAX_READONLY_REVIEW_SCAN_MESSAGES = 50
MAX_READONLY_REVIEW_TARGETS = 10
READONLY_REVIEW_SOURCE_LABEL = "INBOX"
READONLY_REVIEW_QUERY = "-has:attachment"


class GmailReviewState(StrEnum):
    READY = "ready"
    EMPTY = "empty"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION_FAILURE = "authentication_failure"
    PROVIDER_FAILURE = "provider_failure"
    MALFORMED_RESPONSE = "malformed_response"


class GmailReadonlyReviewError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GmailReviewLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label_token: str = Field(min_length=16, max_length=16)
    name: str = Field(min_length=1, max_length=200)


class GmailReviewLabelOption(GmailReviewLabel):
    eligible_message_count: int = Field(ge=1, le=MAX_READONLY_REVIEW_TARGETS)


class GmailReadonlyReviewTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_token: str = Field(min_length=16, max_length=16)
    thread_token: str | None = Field(default=None, min_length=16, max_length=16)
    sender_display: str = Field(min_length=1, max_length=200)
    sender_domain: str = Field(min_length=1, max_length=253)
    subject: str = Field(min_length=1, max_length=500)
    received_at: datetime
    current_labels: tuple[GmailReviewLabel, ...] = Field(min_length=1)
    unread: bool
    selection_reason: str = Field(min_length=1, max_length=500)
    eligible_label_tokens: tuple[str, ...] = Field(min_length=1)


class GmailReviewExclusion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=1)


class GmailReadonlyProviderEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label_list_requests: int = Field(ge=0, le=1)
    message_list_requests: int = Field(ge=0, le=1)
    metadata_requests: int = Field(ge=0, le=MAX_READONLY_REVIEW_SCAN_MESSAGES)
    body_requests: Literal[0] = 0
    full_inventory_scans: Literal[0] = 0
    external_model_calls: Literal[0] = 0
    memory_writes: Literal[0] = 0
    provider_mutation_calls: Literal[0] = 0


class GmailReadonlyReviewSurface(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GmailReviewState
    configured_scope: Literal[GMAIL_READONLY_SCOPE] = GMAIL_READONLY_SCOPE
    account_role: Literal["personal"] = "personal"
    account_token: str | None = Field(default=None, min_length=16, max_length=16)
    source_issue: Literal["SID-230"] = "SID-230"
    source_label: Literal[READONLY_REVIEW_SOURCE_LABEL] = READONLY_REVIEW_SOURCE_LABEL
    query_summary: Literal[
        "One bounded recent Inbox metadata page excluding attachment-bearing, spam, and trash messages"
    ] = "One bounded recent Inbox metadata page excluding attachment-bearing, spam, and trash messages"
    maximum_targets: Literal[MAX_READONLY_REVIEW_TARGETS] = MAX_READONLY_REVIEW_TARGETS
    scanned_message_count: int = Field(ge=0, le=MAX_READONLY_REVIEW_SCAN_MESSAGES)
    next_page_available: bool
    labels: tuple[GmailReviewLabelOption, ...] = ()
    targets: tuple[GmailReadonlyReviewTarget, ...] = Field(
        default=(), max_length=MAX_READONLY_REVIEW_TARGETS
    )
    exclusions: tuple[GmailReviewExclusion, ...] = ()
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    originating_inventory_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    originating_proposal_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    originating_proposal_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_evidence: GmailReadonlyProviderEvidence
    diagnostic_code: str | None = Field(default=None, min_length=1, max_length=100)
    executable: Literal[False] = False
    oauth_change_required_before_execution: Literal[True] = True


class GmailReadonlySelectionPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    originating_inventory_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    originating_proposal_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    originating_proposal_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    label: GmailReviewLabel
    targets: tuple[GmailReadonlyReviewTarget, ...] = Field(
        min_length=1, max_length=MAX_READONLY_REVIEW_TARGETS
    )
    exact_message_count: int = Field(ge=1, le=MAX_READONLY_REVIEW_TARGETS)
    exact_thread_count: int = Field(ge=1, le=MAX_READONLY_REVIEW_TARGETS)
    hand_reviewed: Literal[True] = True
    stale_state_revalidated: Literal[True] = True
    executable: Literal[False] = False
    provider_mutation_calls: Literal[0] = 0
    oauth_change_required_before_execution: Literal[True] = True


class GmailReadonlySelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_selection_fingerprint: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    label_token: str = Field(min_length=16, max_length=16)
    selected_message_tokens: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_READONLY_REVIEW_TARGETS
    )
    prior_review_message_tokens: tuple[str, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_READONLY_REVIEW_TARGETS
    )


@dataclass(frozen=True)
class _ReviewCandidate:
    fact: InventoryMessageFact
    target: GmailReadonlyReviewTarget
    expected: GmailExpectedMessageState


@dataclass(frozen=True)
class _ReviewEvidence:
    surface: GmailReadonlyReviewSurface
    candidates: tuple[_ReviewCandidate, ...]
    labels_by_token: dict[str, GmailLabel]
    supported_labels: tuple[GmailLabel, ...]


@dataclass(frozen=True)
class GmailSealedCanary:
    preview: GmailReadonlySelectionPreview
    payload: GmailApplyLabelPayload
    evidence: tuple[ActionEvidence, ...]
    idempotency_key: str


class GmailReadonlyReviewService:
    """Build and revalidate a non-executable canary review using gmail.readonly."""

    def load(self, client: GmailClient) -> GmailReadonlyReviewSurface:
        return self._load_evidence(client).surface

    def seal_selection(
        self,
        client: GmailClient,
        *,
        expected_snapshot_fingerprint: str,
        expected_selection_fingerprint: str | None = None,
        label_token: str,
        selected_message_tokens: tuple[str, ...],
        prior_review_message_tokens: tuple[str, ...] | None = None,
    ) -> GmailReadonlySelectionPreview:
        return self._seal_selection(
            client,
            expected_snapshot_fingerprint=expected_snapshot_fingerprint,
            expected_selection_fingerprint=expected_selection_fingerprint,
            label_token=label_token,
            selected_message_tokens=selected_message_tokens,
            prior_review_message_tokens=prior_review_message_tokens,
        )[0]

    def build_canary_proposal(
        self,
        client: GmailClient,
        *,
        expected_snapshot_fingerprint: str,
        expected_selection_fingerprint: str | None = None,
        label_token: str,
        selected_message_tokens: tuple[str, ...],
        prior_review_message_tokens: tuple[str, ...] | None = None,
    ) -> GmailSealedCanary:
        preview, selected, label, surface = self._seal_selection(
            client,
            expected_snapshot_fingerprint=expected_snapshot_fingerprint,
            expected_selection_fingerprint=expected_selection_fingerprint,
            label_token=label_token,
            selected_message_tokens=selected_message_tokens,
            prior_review_message_tokens=prior_review_message_tokens,
        )
        account = selected[0].fact.identity.account
        manifest = GmailOrganizationManifest(
            account=account,
            targets=tuple(item.expected for item in selected),
            selection_fingerprint=preview.manifest_fingerprint,
            originating_proposal_id=preview.originating_proposal_id,
            originating_proposal_fingerprint=preview.originating_proposal_fingerprint,
            originating_inventory_fingerprint=preview.originating_inventory_fingerprint,
            selection_criteria=(
                "one bounded recent Inbox metadata page",
                "existing user label selected separately from message eligibility",
                "exact hand-reviewed subset sealed after stale-state revalidation",
                "protected, uncertain, attachment-bearing, and duplicate-thread mail excluded",
            ),
            exclusions=tuple(
                f"{item.reason}: {item.count}" for item in surface.exclusions
            ),
            representative_example_tokens=tuple(
                item.target.message_token for item in selected[:3]
            ),
        )
        payload = GmailApplyLabelPayload(
            action_type="gmail_apply_label",
            manifest=manifest,
            label=GmailUserLabelIdentity(
                provider_label_id=label.provider_label_id,
                name=label.name,
            ),
            canary=True,
            hand_reviewed=True,
        )
        return GmailSealedCanary(
            preview=preview,
            payload=payload,
            evidence=(
                ActionEvidence(
                    kind="sid_231_live_readonly_review",
                    source="gmail_readonly_review",
                    summary=(
                        "The exact existing-label canary manifest was hand-reviewed and "
                        "revalidated with bounded metadata-only Personal Gmail reads."
                    ),
                    source_ref=preview.selection_fingerprint,
                ),
            ),
            idempotency_key=f"sid-231-canary:{preview.selection_fingerprint}",
        )

    def _seal_selection(
        self,
        client: GmailClient,
        *,
        expected_snapshot_fingerprint: str,
        expected_selection_fingerprint: str | None,
        label_token: str,
        selected_message_tokens: tuple[str, ...],
        prior_review_message_tokens: tuple[str, ...] | None,
    ) -> tuple[
        GmailReadonlySelectionPreview,
        tuple[_ReviewCandidate, ...],
        GmailLabel,
        GmailReadonlyReviewSurface,
    ]:
        if (
            not selected_message_tokens
            or len(selected_message_tokens) > MAX_READONLY_REVIEW_TARGETS
            or len(selected_message_tokens) != len(set(selected_message_tokens))
        ):
            raise GmailReadonlyReviewError(
                "invalid_selection",
                "Choose between one and ten unique reviewed messages.",
            )
        evidence = self._load_evidence(client)
        surface = evidence.surface
        if surface.state != GmailReviewState.READY:
            raise GmailReadonlyReviewError(
                "review_unavailable",
                "The bounded read-only Gmail review is not currently available.",
            )
        if (
            surface.snapshot_fingerprint != expected_snapshot_fingerprint
            and expected_selection_fingerprint is None
            and prior_review_message_tokens is None
        ):
            raise GmailReadonlyReviewError(
                "stale_review",
                "The Gmail review snapshot changed. Refresh and inspect every target again.",
            )
        label = evidence.labels_by_token.get(label_token)
        if label is None:
            raise GmailReadonlyReviewError(
                "label_identity_mismatch",
                "The selected existing Gmail label is no longer available.",
            )
        candidates = {item.target.message_token: item for item in evidence.candidates}
        try:
            selected = tuple(candidates[token] for token in selected_message_tokens)
        except KeyError as exc:
            raise GmailReadonlyReviewError(
                "target_identity_mismatch",
                "The selected Gmail target is no longer in the bounded review.",
            ) from exc
        if any(label_token not in item.target.eligible_label_tokens for item in selected):
            raise GmailReadonlyReviewError(
                "label_selection_mismatch",
                "Every selected target must match the reviewed label evidence.",
            )

        lineage_inventory_fingerprint = surface.originating_inventory_fingerprint
        lineage_proposal_fingerprint = surface.originating_proposal_fingerprint
        lineage_proposal_id = surface.originating_proposal_id
        if prior_review_message_tokens is not None:
            if (
                not expected_selection_fingerprint
                or len(prior_review_message_tokens) != len(set(prior_review_message_tokens))
                or any(token not in prior_review_message_tokens for token in selected_message_tokens)
            ):
                raise GmailReadonlyReviewError(
                    "invalid_prior_seal",
                    "Prior sealed review revalidation requires its unique exact review manifest.",
                )
            try:
                prior_candidates = tuple(
                    candidates[token] for token in prior_review_message_tokens
                )
            except KeyError as exc:
                raise GmailReadonlyReviewError(
                    "stale_review",
                    "An original sealed review target is no longer in the bounded metadata page.",
                ) from exc
            account = prior_candidates[0].fact.identity.account
            lineage_inventory_fingerprint = _inventory_fingerprint(
                account.provider_account_id,
                prior_candidates,
            )
            lineage_proposal_fingerprint = _proposal_fingerprint(
                lineage_inventory_fingerprint,
                evidence.supported_labels,
                prior_candidates,
            )
            lineage_proposal_id = _stable_hash(
                "sid-230-proposal", lineage_proposal_fingerprint
            )

        expected_targets = tuple(item.expected for item in selected)
        account = selected[0].fact.identity.account
        manifest_fingerprint = gmail_manifest_fingerprint(account, expected_targets)
        selection_fingerprint = _stable_hash(
            "sid-231-readonly-selection",
            manifest_fingerprint,
            label.provider_label_id,
            label.name,
            lineage_proposal_fingerprint,
        )
        if (
            surface.snapshot_fingerprint != expected_snapshot_fingerprint
            or prior_review_message_tokens is not None
        ) and not (
            expected_selection_fingerprint
            and hmac.compare_digest(
                selection_fingerprint, expected_selection_fingerprint
            )
        ):
            raise GmailReadonlyReviewError(
                "stale_review",
                "The Gmail review changed and the exact sealed target state did not match.",
            )
        preview = GmailReadonlySelectionPreview(
            snapshot_fingerprint=surface.snapshot_fingerprint,
            selection_fingerprint=selection_fingerprint,
            manifest_fingerprint=manifest_fingerprint,
            originating_inventory_fingerprint=lineage_inventory_fingerprint,
            originating_proposal_id=lineage_proposal_id,
            originating_proposal_fingerprint=lineage_proposal_fingerprint,
            label=GmailReviewLabel(label_token=label_token, name=label.name),
            targets=tuple(item.target for item in selected),
            exact_message_count=len(selected),
            exact_thread_count=len(
                {
                    item.fact.identity.provider_thread_id
                    or item.fact.identity.provider_message_id
                    for item in selected
                }
            ),
        )
        return preview, selected, label, surface

    def _load_evidence(self, client: GmailClient) -> _ReviewEvidence:
        label_result = client.list_labels()
        if label_result.diagnostic is not None:
            return self._failed_evidence(
                label_result.state,
                label_result.diagnostic.code,
                message_list_requests=0,
            )
        page = client.list_message_metadata(
            max_messages=MAX_READONLY_REVIEW_SCAN_MESSAGES,
            query=READONLY_REVIEW_QUERY,
            label_ids=(READONLY_REVIEW_SOURCE_LABEL,),
        )
        if page.diagnostic is not None:
            return self._failed_evidence(page.state, page.diagnostic.code)

        label_catalog = {
            **GMAIL_SYSTEM_LABEL_DISPLAY_NAMES,
            **{
                item.provider_label_id: _safe_text(item.name, 200)
                for item in label_result.labels
            },
        }
        supported_labels = _supported_user_labels(label_result.labels)
        exclusion_counts: Counter[str] = Counter()
        candidates: list[_ReviewCandidate] = []
        seen_threads: set[str] = set()
        for record in page.messages:
            fact = inventory_fact_for_record(
                record.model_copy(update={"has_attachment": False})
            )
            sender_display = _safe_text(parseaddr(record.sender or "")[0], 200)
            for reason in fact.protection_reasons:
                exclusion_counts[reason.value] += 1
            if fact.protection_reasons:
                continue
            if (
                not sender_display
                or "@" in sender_display
                or not fact.sender_domain
                or not fact.subject
                or fact.received_at is None
            ):
                exclusion_counts["incomplete_review_metadata"] += 1
                continue
            if any(label_id not in label_catalog for label_id in fact.label_ids):
                exclusion_counts["unknown_current_label"] += 1
                continue
            thread_identity = (
                fact.identity.provider_thread_id or fact.identity.provider_message_id
            )
            if thread_identity in seen_threads:
                exclusion_counts["duplicate_thread"] += 1
                continue
            eligible = tuple(
                label
                for label in supported_labels
                if label.provider_label_id not in fact.label_ids
            )
            if not eligible:
                exclusion_counts["no_existing_eligible_label"] += 1
                continue

            current_labels = tuple(
                GmailReviewLabel(
                    label_token=_token("label", label_id),
                    name=label_catalog[label_id],
                )
                for label_id in fact.label_ids
            )
            selection_reason = _selection_reason(fact.coarse_types)
            target = GmailReadonlyReviewTarget(
                message_token=_token("message", fact.identity.provider_message_id),
                thread_token=(
                    _token("thread", fact.identity.provider_thread_id)
                    if fact.identity.provider_thread_id
                    else None
                ),
                sender_display=sender_display,
                sender_domain=fact.sender_domain,
                subject=fact.subject,
                received_at=fact.received_at,
                current_labels=current_labels,
                unread=fact.unread,
                selection_reason=selection_reason,
                eligible_label_tokens=tuple(
                    _token("label", item.provider_label_id) for item in eligible
                ),
            )
            expected = GmailExpectedMessageState(
                provider_message_id=fact.identity.provider_message_id,
                provider_thread_id=fact.identity.provider_thread_id,
                expected_label_ids=fact.label_ids,
                expected_unread=fact.unread,
                review=GmailMessageReviewMetadata(
                    sender_display=sender_display,
                    sender_domain=fact.sender_domain,
                    subject=fact.subject,
                    received_at=fact.received_at,
                    current_labels=tuple(
                        GmailReviewLabelIdentity(
                            provider_label_id=label_id,
                            display_name=label_catalog[label_id],
                        )
                        for label_id in fact.label_ids
                    ),
                    selection_reason=selection_reason,
                ),
            )
            candidates.append(_ReviewCandidate(fact=fact, target=target, expected=expected))
            seen_threads.add(thread_identity)

        review_candidates = candidates[:MAX_READONLY_REVIEW_TARGETS]
        if len(candidates) > len(review_candidates):
            exclusion_counts["bounded_after_ten_review_targets"] += (
                len(candidates) - len(review_candidates)
            )
        eligible_counts = Counter(
            token
            for candidate in review_candidates
            for token in candidate.target.eligible_label_tokens
        )
        labels_by_token = {
            _token("label", item.provider_label_id): item
            for item in supported_labels
            if eligible_counts[_token("label", item.provider_label_id)]
        }
        label_options = tuple(
            GmailReviewLabelOption(
                label_token=token,
                name=label.name,
                eligible_message_count=eligible_counts[token],
            )
            for token, label in sorted(
                labels_by_token.items(), key=lambda value: value[1].name.casefold()
            )
        )
        account = candidates[0].fact.identity.account if candidates else (
            page.messages[0].identity.account if page.messages else None
        )
        inventory_fingerprint = _inventory_fingerprint(
            account.provider_account_id if account else "unavailable",
            tuple(review_candidates),
        )
        proposal_fingerprint = _proposal_fingerprint(
            inventory_fingerprint,
            supported_labels,
            tuple(review_candidates),
        )
        proposal_id = _stable_hash("sid-230-proposal", proposal_fingerprint)
        snapshot_fingerprint = _stable_hash(
            "sid-231-readonly-review",
            inventory_fingerprint,
            proposal_fingerprint,
            *(f"{item.target.message_token}:{','.join(item.target.eligible_label_tokens)}" for item in review_candidates),
        )
        surface = GmailReadonlyReviewSurface(
            state=(GmailReviewState.READY if review_candidates and label_options else GmailReviewState.EMPTY),
            account_token=(
                _token("account", account.provider_account_id) if account else None
            ),
            scanned_message_count=len(page.messages),
            next_page_available=page.next_page_token is not None,
            labels=label_options,
            targets=tuple(item.target for item in review_candidates),
            exclusions=tuple(
                GmailReviewExclusion(reason=reason, count=count)
                for reason, count in sorted(exclusion_counts.items())
                if count
            ),
            snapshot_fingerprint=snapshot_fingerprint,
            originating_inventory_fingerprint=inventory_fingerprint,
            originating_proposal_id=proposal_id,
            originating_proposal_fingerprint=proposal_fingerprint,
            provider_evidence=GmailReadonlyProviderEvidence(
                label_list_requests=1,
                message_list_requests=1,
                metadata_requests=len(page.messages)
            ),
        )
        return _ReviewEvidence(
            surface=surface,
            candidates=tuple(candidates),
            labels_by_token=labels_by_token,
            supported_labels=supported_labels,
        )

    def _failed_evidence(
        self,
        state: GmailProviderState,
        diagnostic_code: str,
        *,
        message_list_requests: int = 1,
    ) -> _ReviewEvidence:
        fingerprint = _stable_hash("sid-231-readonly-review-unavailable", state.value)
        surface = GmailReadonlyReviewSurface(
            state=_review_state(state),
            scanned_message_count=0,
            next_page_available=False,
            snapshot_fingerprint=fingerprint,
            originating_inventory_fingerprint=fingerprint,
            originating_proposal_id=_stable_hash("sid-230-proposal", fingerprint),
            originating_proposal_fingerprint=fingerprint,
            provider_evidence=GmailReadonlyProviderEvidence(
                label_list_requests=1,
                message_list_requests=message_list_requests,
                metadata_requests=0,
            ),
            diagnostic_code=diagnostic_code,
        )
        return _ReviewEvidence(
            surface=surface,
            candidates=(),
            labels_by_token={},
            supported_labels=(),
        )


def _supported_user_labels(labels: tuple[GmailLabel, ...]) -> tuple[GmailLabel, ...]:
    matches: dict[str, list[GmailLabel]] = {}
    for label in labels:
        if (
            label.label_type == "user"
            and label.provider_label_id.startswith("Label_")
            and "@" not in label.name
            and len(label.name) <= 200
            and _safe_text(label.name, 200)
        ):
            matches.setdefault(label.name, []).append(label)
    return tuple(
        values[0]
        for name, values in sorted(matches.items())
        if len(values) == 1
    )


def _selection_reason(
    coarse_types: tuple[InventoryCoarseType, ...]
) -> str:
    kinds = ", ".join(value.value.replace("_", " ") for value in coarse_types)
    return _safe_text(
        f"Grounded {kinds} metadata matched the SID-230 safe-candidate rules; protected and uncertain signals were excluded, and the existing label choice remains separate.",
        500,
    )


def _review_state(state: GmailProviderState) -> GmailReviewState:
    return {
        GmailProviderState.NOT_CONFIGURED: GmailReviewState.NOT_CONFIGURED,
        GmailProviderState.AUTHENTICATION_FAILURE: GmailReviewState.AUTHENTICATION_FAILURE,
        GmailProviderState.PROVIDER_FAILURE: GmailReviewState.PROVIDER_FAILURE,
        GmailProviderState.MALFORMED_RESPONSE: GmailReviewState.MALFORMED_RESPONSE,
        GmailProviderState.CONNECTED_EMPTY: GmailReviewState.EMPTY,
        GmailProviderState.CONNECTED: GmailReviewState.EMPTY,
    }[state]


def _token(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:16]


def _stable_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _inventory_fingerprint(
    account_id: str, candidates: tuple[_ReviewCandidate, ...]
) -> str:
    return _stable_hash(
        "sid-230-bounded-live-inventory",
        account_id,
        READONLY_REVIEW_SOURCE_LABEL,
        READONLY_REVIEW_QUERY,
        *(
            f"{item.expected.provider_message_id}:{item.expected.provider_thread_id or ''}:"
            f"{','.join(item.expected.expected_label_ids)}:{item.expected.expected_unread}"
            for item in candidates
        ),
    )


def _proposal_fingerprint(
    inventory_fingerprint: str,
    supported_labels: tuple[GmailLabel, ...],
    candidates: tuple[_ReviewCandidate, ...],
) -> str:
    return _stable_hash(
        "sid-230-bounded-live-label-proposal",
        inventory_fingerprint,
        *(f"{item.provider_label_id}:{item.name}" for item in supported_labels),
        *(item.target.message_token for item in candidates),
    )


def _safe_text(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit].rstrip()
