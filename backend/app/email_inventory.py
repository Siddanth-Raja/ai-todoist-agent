"""Read-only Personal Email inventory and advisory organization proposals.

SID-230 deliberately stops before OAuth scope changes, pending actions, mailbox
mutations, persistence, UI, Memory, or external-model access.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from email.utils import parseaddr
from enum import StrEnum
import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .email_domain import (
    EmailAccountRole,
    EmailMessageIdentity,
    EmailProviderAccountIdentity,
)
from .gmail_client import (
    GmailClient,
    GmailInventoryPage,
    GmailLabel,
    GmailMessageRecord,
    GmailProviderDiagnostic,
    GmailProviderState,
)


PERSONAL_INBOX_LABEL_NAME = "INBOX"
OLD_STUFF_LABEL_NAME = "Old Stuff"
MAX_REDACTED_EXAMPLES = 3


class EmailInventoryState(StrEnum):
    COMPLETE = "complete"
    CONNECTED_EMPTY = "connected_empty"
    INCOMPLETE = "incomplete"
    LABEL_NOT_FOUND = "label_not_found"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION_FAILURE = "authentication_failure"
    PROVIDER_FAILURE = "provider_failure"
    MALFORMED_RESPONSE = "malformed_response"


class InventoryCoarseType(StrEnum):
    ACTION = "action"
    WAITING = "waiting"
    REFERENCE = "reference"
    PROMOTIONAL = "promotional"
    SECURITY = "security"
    FINANCIAL = "financial"
    ACADEMIC = "academic"
    CLIENT = "client"
    TRAVEL = "travel"
    DIRECT_HUMAN = "direct_human"
    OTHER = "other"


class InventoryProtectionReason(StrEnum):
    PROVIDER_IMPORTANT = "provider_important"
    SECURITY = "security"
    FINANCIAL = "financial"
    ACADEMIC = "academic"
    CLIENT = "client"
    DIRECT_HUMAN = "direct_human"
    ATTACHMENT = "attachment"
    UNCERTAIN = "uncertain"


class OrganizationLabel(StrEnum):
    ACTION = "PCOS/Action"
    WAITING = "PCOS/Waiting"
    KEEP = "PCOS/Keep"
    REVIEW = "PCOS/Review"


class GroundedTopicLabel(StrEnum):
    FINANCE = "Finance"
    SCHOOL = "School"
    FREELANCE = "Freelance"
    TRAVEL = "Travel"


class FutureOrganizationOperation(StrEnum):
    LABEL = "label"
    ARCHIVE = "archive"
    MARK_READ = "mark_read"


class InventoryLabelIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_label_id: str = Field(min_length=1)
    exact_name: str = Field(min_length=1)


class InventoryCount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str = Field(min_length=1)
    count: int = Field(ge=1)


class InventoryMessageFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: EmailMessageIdentity
    received_at: datetime | None = None
    sender_fingerprint: str = Field(min_length=1)
    sender_domain: str | None = Field(default=None, min_length=1)
    unread: bool
    provider_important: bool
    label_ids: tuple[str, ...]
    has_attachment: bool | None
    coarse_types: tuple[InventoryCoarseType, ...] = Field(min_length=1)
    protection_reasons: tuple[InventoryProtectionReason, ...] = ()
    uncertain: bool
    uncertainty_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def preserve_uncertainty(self) -> "InventoryMessageFact":
        if self.uncertain != bool(self.uncertainty_reasons):
            raise ValueError("uncertainty flag and reasons must agree")
        if self.uncertain and InventoryProtectionReason.UNCERTAIN not in self.protection_reasons:
            raise ValueError("uncertain mail must be protected")
        if self.has_attachment and InventoryProtectionReason.ATTACHMENT not in self.protection_reasons:
            raise ValueError("attachment-bearing mail must be protected")
        return self


class LabelInventory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: InventoryLabelIdentity
    state: EmailInventoryState
    provider_state: GmailProviderState
    complete: bool
    messages: tuple[InventoryMessageFact, ...] = ()
    message_count: int = Field(ge=0)
    unique_thread_count: int = Field(ge=0)
    duplicate_message_count: int = Field(ge=0)
    unread_count: int = Field(ge=0)
    important_count: int = Field(ge=0)
    protected_count: int = Field(ge=0)
    uncertain_count: int = Field(ge=0)
    earliest_message_at: datetime | None = None
    latest_message_at: datetime | None = None
    top_senders: tuple[InventoryCount, ...] = ()
    top_domains: tuple[InventoryCount, ...] = ()
    existing_labels: tuple[InventoryCount, ...] = ()
    coarse_types: tuple[InventoryCount, ...] = ()
    pages_fetched: int = Field(ge=0)
    attachment_pages_fetched: int = Field(ge=0)
    result_size_estimate: int | None = Field(default=None, ge=0)
    metadata_requests: int = Field(ge=0)
    provider_retry_count: int = Field(ge=0)
    body_requests: Literal[0] = 0
    remaining_cursor_present: bool
    attachment_cursor_present: bool
    provider_diagnostic: GmailProviderDiagnostic | None = None
    stable_fingerprint: str = Field(min_length=1)
    provider_mutation_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_inventory(self) -> "LabelInventory":
        if self.message_count != len(self.messages):
            raise ValueError("message count must match the exact inventory")
        identities = [item.identity for item in self.messages]
        if len(identities) != len(set(identities)):
            raise ValueError("inventory message identities must be unique")
        accounts = {item.identity.account for item in self.messages}
        if len(accounts) > 1 or any(
            account.account_role != EmailAccountRole.PERSONAL for account in accounts
        ):
            raise ValueError("inventory must preserve one Personal provider account")
        if any(self.label.provider_label_id not in item.label_ids for item in self.messages):
            raise ValueError("every inventory record must preserve the exact provider label")
        if self.complete and (
            self.remaining_cursor_present or self.attachment_cursor_present
        ):
            raise ValueError("complete inventory cannot retain provider cursors")
        if self.complete and self.provider_diagnostic is not None:
            raise ValueError("complete inventory cannot retain provider failure")
        if self.unread_count != sum(item.unread for item in self.messages):
            raise ValueError("unread count must derive from inventory facts")
        if self.important_count != sum(item.provider_important for item in self.messages):
            raise ValueError("important count must derive from inventory facts")
        if self.protected_count != sum(bool(item.protection_reasons) for item in self.messages):
            raise ValueError("protected count must derive from inventory facts")
        if self.uncertain_count != sum(item.uncertain for item in self.messages):
            raise ValueError("uncertain count must derive from inventory facts")
        return self


class PersonalEmailInventoryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["gmail"] = "gmail"
    account_role: Literal[EmailAccountRole.PERSONAL] = EmailAccountRole.PERSONAL
    inbox: LabelInventory
    old_stuff: LabelInventory
    complete: bool
    stable_fingerprint: str = Field(min_length=1)
    body_requests: Literal[0] = 0
    external_model_calls: Literal[0] = 0
    memory_writes: Literal[0] = 0
    provider_mutation_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_complete(self) -> "PersonalEmailInventoryResult":
        if self.complete != (self.inbox.complete and self.old_stuff.complete):
            raise ValueError("overall completeness must require both exact labels")
        return self


class InventorySelectionTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account: EmailProviderAccountIdentity
    provider_thread_id: str | None = Field(default=None, min_length=1)
    provider_message_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_message_ids(self) -> "InventorySelectionTarget":
        if len(self.provider_message_ids) != len(set(self.provider_message_ids)):
            raise ValueError("selection target message identities must be unique")
        if any(not value.strip() for value in self.provider_message_ids):
            raise ValueError("selection target message identities cannot be blank")
        return self


class RedactedInventoryExample(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_token: str = Field(min_length=1)
    sender_domain: str | None = Field(default=None, min_length=1)
    received_at: datetime | None = None
    coarse_types: tuple[InventoryCoarseType, ...] = Field(min_length=1)


class OrganizationBatchProposal(BaseModel):
    """Advisory batch only; deliberately cannot be executed or approved here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: str = Field(min_length=1)
    source_label: InventoryLabelIdentity
    operation: FutureOrganizationOperation
    organization_label: OrganizationLabel | None = None
    topic_labels: tuple[GroundedTopicLabel, ...] = ()
    targets: tuple[InventorySelectionTarget, ...] = Field(min_length=1)
    exact_message_count: int = Field(ge=1)
    exact_thread_count: int = Field(ge=1)
    selection_criteria: tuple[str, ...] = Field(min_length=1)
    exclusions: tuple[InventoryCount, ...]
    uncertainty_count: Literal[0] = 0
    representative_examples: tuple[RedactedInventoryExample, ...]
    selection_fingerprint: str = Field(min_length=1)
    approval_required: Literal[True] = True
    executable: Literal[False] = False
    provider_mutation_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_exact_selection(self) -> "OrganizationBatchProposal":
        message_ids = [
            value for target in self.targets for value in target.provider_message_ids
        ]
        message_count = len(message_ids)
        if message_count != self.exact_message_count:
            raise ValueError("exact message count must match target manifest")
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("proposal target manifest cannot duplicate messages")
        if len(self.targets) != self.exact_thread_count:
            raise ValueError("exact thread count must match thread-deduplicated targets")
        if self.operation == FutureOrganizationOperation.LABEL:
            if self.organization_label is None:
                raise ValueError("label proposal requires the exact organization label")
        elif self.organization_label is not None or self.topic_labels:
            raise ValueError("archive and mark-read remain separate from label approval")
        return self


class EmailOrganizationProposalResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inventory_fingerprint: str = Field(min_length=1)
    proposals: tuple[OrganizationBatchProposal, ...]
    complete_inventory_required: Literal[True] = True
    advisory_only: Literal[True] = True
    external_model_calls: Literal[0] = 0
    provider_mutation_calls: Literal[0] = 0


class EmailInventoryService:
    def inventory_personal(self, client: GmailClient) -> PersonalEmailInventoryResult:
        label_result = client.list_labels()
        labels = label_result.labels if label_result.diagnostic is None else ()
        inbox_label = next(
            (
                item
                for item in labels
                if item.provider_label_id == PERSONAL_INBOX_LABEL_NAME
                and item.name == PERSONAL_INBOX_LABEL_NAME
            ),
            None,
        )
        old_stuff_matches = tuple(
            item
            for item in labels
            if item.name.casefold() == OLD_STUFF_LABEL_NAME.casefold()
        )
        old_stuff_label = (
            old_stuff_matches[0] if len(old_stuff_matches) == 1 else None
        )
        inbox = self._inventory_exact_label(
            client,
            inbox_label,
            PERSONAL_INBOX_LABEL_NAME,
            label_result.state,
            label_result.diagnostic,
        )
        old_stuff = self._inventory_exact_label(
            client,
            old_stuff_label,
            OLD_STUFF_LABEL_NAME,
            label_result.state,
            label_result.diagnostic,
        )
        fingerprint = _stable_hash(
            "personal-inventory",
            inbox.stable_fingerprint,
            old_stuff.stable_fingerprint,
        )
        return PersonalEmailInventoryResult(
            inbox=inbox,
            old_stuff=old_stuff,
            complete=inbox.complete and old_stuff.complete,
            stable_fingerprint=fingerprint,
        )

    def _inventory_exact_label(
        self,
        client: GmailClient,
        label: GmailLabel | None,
        exact_name: str,
        label_provider_state: GmailProviderState,
        label_error: GmailProviderDiagnostic | None,
    ) -> LabelInventory:
        fallback = InventoryLabelIdentity(
            provider_label_id=_stable_hash("missing-label", exact_name),
            exact_name=exact_name,
        )
        if label_error is not None:
            return _empty_label_inventory(
                fallback,
                _state_for_provider(label_provider_state),
                label_provider_state,
                label_error,
            )
        if label is None:
            diagnostic = GmailProviderDiagnostic(
                code="label_not_found",
                message=f"Required exact Gmail label {exact_name!r} was not found.",
            )
            return _empty_label_inventory(
                fallback,
                EmailInventoryState.LABEL_NOT_FOUND,
                GmailProviderState.CONNECTED_EMPTY,
                diagnostic,
            )
        identity = InventoryLabelIdentity(
            provider_label_id=label.provider_label_id,
            exact_name=label.name,
        )
        page = client.inventory_label_messages(
            provider_label_id=label.provider_label_id
        )
        return _summarize_page(identity, page)


class EmailOrganizationProposalService:
    def propose(
        self, inventory: PersonalEmailInventoryResult
    ) -> EmailOrganizationProposalResult:
        if not inventory.complete:
            return EmailOrganizationProposalResult(
                inventory_fingerprint=inventory.stable_fingerprint,
                proposals=(),
            )
        proposals: list[OrganizationBatchProposal] = []
        for label_inventory in (inventory.inbox, inventory.old_stuff):
            proposals.extend(_proposals_for_label(label_inventory))
        proposals.sort(key=lambda item: item.proposal_id)
        return EmailOrganizationProposalResult(
            inventory_fingerprint=inventory.stable_fingerprint,
            proposals=tuple(proposals),
        )


_SECURITY_RE = re.compile(
    r"\b(?:security|password|sign[- ]?in|login|two.factor|2fa|verification code|"
    r"unusual activity|account locked)\b",
    re.IGNORECASE,
)
_FINANCE_RE = re.compile(
    r"\b(?:bank|credit card|payment|invoice|receipt|billing|tax|balance|statement|"
    r"refund|transaction|payroll)\b",
    re.IGNORECASE,
)
_ACADEMIC_RE = re.compile(
    r"\b(?:school|university|college|course|class|academic|registrar|tuition|"
    r"student|campus|semester|admissions?)\b",
    re.IGNORECASE,
)
_CLIENT_RE = re.compile(r"\b(?:client|freelance|proposal|contract|deliverable)\b", re.IGNORECASE)
_TRAVEL_RE = re.compile(r"\b(?:flight|hotel|reservation|itinerary|travel|boarding)\b", re.IGNORECASE)
_ACTION_RE = re.compile(
    r"\b(?:action required|please (?:review|complete|confirm|respond|submit)|"
    r"response required|due|deadline)\b",
    re.IGNORECASE,
)
_WAITING_RE = re.compile(r"\b(?:waiting for|awaiting|following up|let me know)\b", re.IGNORECASE)
_REFERENCE_RE = re.compile(r"\b(?:reference|confirmation|record|summary|documentation)\b", re.IGNORECASE)
_PROMOTIONAL_RE = re.compile(
    r"\b(?:sale|discount|newsletter|promotion|offer|shop now|unsubscribe|marketing)\b",
    re.IGNORECASE,
)
_AUTOMATED_LOCAL_RE = re.compile(r"^(?:no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|updates?)$")


def _summarize_page(label: InventoryLabelIdentity, page: GmailInventoryPage) -> LabelInventory:
    facts = tuple(sorted((_fact_for_record(item) for item in page.messages), key=_fact_sort_key))
    dates = [item.received_at for item in facts if item.received_at is not None]
    thread_keys = {
        (
            item.identity.account.provider_account_id,
            item.identity.provider_thread_id or item.identity.provider_message_id,
        )
        for item in facts
    }
    fingerprint = _inventory_fingerprint(label, facts, page.complete)
    return LabelInventory(
        label=label,
        state=(
            EmailInventoryState.CONNECTED_EMPTY
            if page.complete and not facts
            else EmailInventoryState.COMPLETE
            if page.complete
            else _state_for_provider(page.state)
        ),
        provider_state=page.state,
        complete=page.complete,
        messages=facts,
        message_count=len(facts),
        unique_thread_count=len(thread_keys),
        duplicate_message_count=page.duplicate_message_count,
        unread_count=sum(item.unread for item in facts),
        important_count=sum(item.provider_important for item in facts),
        protected_count=sum(bool(item.protection_reasons) for item in facts),
        uncertain_count=sum(item.uncertain for item in facts),
        earliest_message_at=min(dates) if dates else None,
        latest_message_at=max(dates) if dates else None,
        top_senders=_counter_rows(item.sender_fingerprint for item in facts),
        top_domains=_counter_rows(item.sender_domain for item in facts if item.sender_domain),
        existing_labels=_counter_rows(value for item in facts for value in item.label_ids),
        coarse_types=_counter_rows(value.value for item in facts for value in item.coarse_types),
        pages_fetched=page.pages_fetched,
        attachment_pages_fetched=page.attachment_pages_fetched,
        result_size_estimate=page.result_size_estimate,
        metadata_requests=page.metadata_requests,
        provider_retry_count=page.provider_retry_count,
        remaining_cursor_present=page.next_page_token is not None,
        attachment_cursor_present=page.attachment_next_page_token is not None,
        provider_diagnostic=page.diagnostic,
        stable_fingerprint=fingerprint,
    )


def _fact_for_record(record: GmailMessageRecord) -> InventoryMessageFact:
    sender = record.sender or ""
    _name, address = parseaddr(sender)
    address = address.strip().casefold()
    local, separator, domain = address.partition("@")
    sender_domain = domain if separator and domain else None
    subject = record.subject or ""
    labels = set(record.label_ids)
    bulk = bool(labels.intersection({"CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}))
    promotional = bulk or bool(_PROMOTIONAL_RE.search(subject))
    automated = (bool(_AUTOMATED_LOCAL_RE.match(local)) if local else False) or promotional
    types: list[InventoryCoarseType] = []
    protections: list[InventoryProtectionReason] = []
    uncertainty: list[str] = []

    def match(pattern: re.Pattern[str], item: InventoryCoarseType, protection=None):
        if pattern.search(subject) or (sender_domain and pattern.search(sender_domain)):
            types.append(item)
            if protection is not None:
                protections.append(protection)

    match(_SECURITY_RE, InventoryCoarseType.SECURITY, InventoryProtectionReason.SECURITY)
    match(_FINANCE_RE, InventoryCoarseType.FINANCIAL, InventoryProtectionReason.FINANCIAL)
    match(_ACADEMIC_RE, InventoryCoarseType.ACADEMIC, InventoryProtectionReason.ACADEMIC)
    if sender_domain and sender_domain.endswith(".edu"):
        types.append(InventoryCoarseType.ACADEMIC)
        protections.append(InventoryProtectionReason.ACADEMIC)
    match(_CLIENT_RE, InventoryCoarseType.CLIENT, InventoryProtectionReason.CLIENT)
    match(_TRAVEL_RE, InventoryCoarseType.TRAVEL)
    match(_ACTION_RE, InventoryCoarseType.ACTION)
    match(_WAITING_RE, InventoryCoarseType.WAITING)
    match(_REFERENCE_RE, InventoryCoarseType.REFERENCE)
    if promotional:
        types.append(InventoryCoarseType.PROMOTIONAL)
    if address and not automated and not bulk:
        types.append(InventoryCoarseType.DIRECT_HUMAN)
        protections.append(InventoryProtectionReason.DIRECT_HUMAN)
    if "IMPORTANT" in labels:
        protections.append(InventoryProtectionReason.PROVIDER_IMPORTANT)
    if record.has_attachment:
        protections.append(InventoryProtectionReason.ATTACHMENT)
    if not address:
        uncertainty.append("sender identity unavailable")
    if not subject.strip():
        uncertainty.append("subject unavailable")
    if record.internal_date is None and record.message_date is None:
        uncertainty.append("message date unavailable")
    if record.has_attachment is None:
        uncertainty.append("attachment evidence unavailable")
    if record.parse_diagnostics:
        uncertainty.append("provider metadata parse diagnostics present")
    if not types:
        types.append(InventoryCoarseType.OTHER)
        uncertainty.append("no grounded coarse message type")
    if uncertainty:
        protections.append(InventoryProtectionReason.UNCERTAIN)
    return InventoryMessageFact(
        identity=record.identity,
        received_at=record.internal_date or record.message_date,
        sender_fingerprint=_stable_hash("sender", sender.casefold() or "unavailable"),
        sender_domain=sender_domain,
        unread=record.unread,
        provider_important="IMPORTANT" in labels,
        label_ids=tuple(sorted(labels)),
        has_attachment=record.has_attachment,
        coarse_types=tuple(dict.fromkeys(types)),
        protection_reasons=tuple(dict.fromkeys(protections)),
        uncertain=bool(uncertainty),
        uncertainty_reasons=tuple(dict.fromkeys(uncertainty)),
    )


def _proposals_for_label(inventory: LabelInventory) -> list[OrganizationBatchProposal]:
    eligible = [item for item in inventory.messages if not item.protection_reasons]
    groups: dict[OrganizationLabel, list[InventoryMessageFact]] = defaultdict(list)
    for item in eligible:
        kinds = set(item.coarse_types)
        if InventoryCoarseType.ACTION in kinds:
            groups[OrganizationLabel.ACTION].append(item)
        elif InventoryCoarseType.WAITING in kinds:
            groups[OrganizationLabel.WAITING].append(item)
        elif InventoryCoarseType.REFERENCE in kinds:
            groups[OrganizationLabel.KEEP].append(item)
        elif InventoryCoarseType.PROMOTIONAL in kinds:
            groups[OrganizationLabel.REVIEW].append(item)

    exclusions = _exclusion_rows(inventory.messages)
    proposals: list[OrganizationBatchProposal] = []
    for organization_label, facts in groups.items():
        proposals.append(
            _make_proposal(
                inventory,
                facts,
                FutureOrganizationOperation.LABEL,
                organization_label=organization_label,
                topic_labels=_grounded_topics(facts),
                criteria=(
                    f"grounded {organization_label.value} metadata classification",
                    "no protected or uncertain evidence",
                ),
                exclusions=exclusions,
            )
        )
    review = groups.get(OrganizationLabel.REVIEW, [])
    if review:
        proposals.append(
            _make_proposal(
                inventory,
                review,
                FutureOrganizationOperation.ARCHIVE,
                criteria=(
                    "grounded promotional or bulk metadata",
                    "no protected or uncertain evidence",
                ),
                exclusions=exclusions,
            )
        )
        unread_review = [item for item in review if item.unread]
        if unread_review:
            proposals.append(
                _make_proposal(
                    inventory,
                    unread_review,
                    FutureOrganizationOperation.MARK_READ,
                    criteria=(
                        "grounded promotional or bulk metadata",
                        "currently unread",
                        "no protected or uncertain evidence",
                    ),
                    exclusions=exclusions,
                )
            )
    return proposals


def _make_proposal(
    inventory: LabelInventory,
    facts: list[InventoryMessageFact],
    operation: FutureOrganizationOperation,
    *,
    organization_label: OrganizationLabel | None = None,
    topic_labels: tuple[GroundedTopicLabel, ...] = (),
    criteria: tuple[str, ...],
    exclusions: tuple[InventoryCount, ...],
) -> OrganizationBatchProposal:
    ordered = sorted(facts, key=_fact_sort_key)
    by_thread: dict[tuple[str, str], list[InventoryMessageFact]] = defaultdict(list)
    for item in ordered:
        thread_id = item.identity.provider_thread_id or item.identity.provider_message_id
        by_thread[(item.identity.account.provider_account_id, thread_id)].append(item)
    targets = tuple(
        InventorySelectionTarget(
            account=items[0].identity.account,
            provider_thread_id=items[0].identity.provider_thread_id,
            provider_message_ids=tuple(
                sorted(item.identity.provider_message_id for item in items)
            ),
        )
        for _key, items in sorted(by_thread.items())
    )
    fingerprint = _stable_hash(
        "selection",
        inventory.stable_fingerprint,
        operation.value,
        organization_label.value if organization_label else "",
        *(value.value for value in topic_labels),
        *(message_id for target in targets for message_id in target.provider_message_ids),
    )
    return OrganizationBatchProposal(
        proposal_id=_stable_hash("proposal", fingerprint),
        source_label=inventory.label,
        operation=operation,
        organization_label=organization_label,
        topic_labels=topic_labels,
        targets=targets,
        exact_message_count=len(ordered),
        exact_thread_count=len(targets),
        selection_criteria=criteria,
        exclusions=exclusions,
        representative_examples=tuple(
            RedactedInventoryExample(
                message_token=_stable_hash(
                    "example", item.identity.provider_message_id
                ),
                sender_domain=item.sender_domain,
                received_at=item.received_at,
                coarse_types=item.coarse_types,
            )
            for item in ordered[:MAX_REDACTED_EXAMPLES]
        ),
        selection_fingerprint=fingerprint,
    )


def _grounded_topics(facts: list[InventoryMessageFact]) -> tuple[GroundedTopicLabel, ...]:
    values: set[GroundedTopicLabel] = set()
    for item in facts:
        kinds = set(item.coarse_types)
        if InventoryCoarseType.FINANCIAL in kinds:
            values.add(GroundedTopicLabel.FINANCE)
        if InventoryCoarseType.ACADEMIC in kinds:
            values.add(GroundedTopicLabel.SCHOOL)
        if InventoryCoarseType.CLIENT in kinds:
            values.add(GroundedTopicLabel.FREELANCE)
        if InventoryCoarseType.TRAVEL in kinds:
            values.add(GroundedTopicLabel.TRAVEL)
    return tuple(sorted(values, key=lambda item: item.value))


def _exclusion_rows(messages: tuple[InventoryMessageFact, ...]) -> tuple[InventoryCount, ...]:
    counts = Counter(
        reason.value for item in messages for reason in item.protection_reasons
    )
    return tuple(
        InventoryCount(value=value, count=count)
        for value, count in sorted(counts.items())
    )


def _counter_rows(values, limit: int = 10) -> tuple[InventoryCount, ...]:
    counts = Counter(values)
    return tuple(
        InventoryCount(value=value, count=count)
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    )


def _inventory_fingerprint(
    label: InventoryLabelIdentity,
    facts: tuple[InventoryMessageFact, ...],
    complete: bool,
) -> str:
    return _stable_hash(
        "label-inventory",
        label.provider_label_id,
        label.exact_name,
        str(complete),
        *(
            f"{item.identity.provider_message_id}:{item.identity.provider_thread_id or ''}:"
            f"{','.join(item.label_ids)}:{int(item.unread)}:{int(bool(item.has_attachment))}"
            for item in facts
        ),
    )


def _empty_label_inventory(
    label: InventoryLabelIdentity,
    state: EmailInventoryState,
    provider_state: GmailProviderState,
    diagnostic: GmailProviderDiagnostic,
) -> LabelInventory:
    return LabelInventory(
        label=label,
        state=state,
        provider_state=provider_state,
        complete=False,
        message_count=0,
        unique_thread_count=0,
        duplicate_message_count=0,
        unread_count=0,
        important_count=0,
        protected_count=0,
        uncertain_count=0,
        pages_fetched=0,
        attachment_pages_fetched=0,
        result_size_estimate=None,
        metadata_requests=0,
        provider_retry_count=0,
        remaining_cursor_present=False,
        attachment_cursor_present=False,
        provider_diagnostic=diagnostic,
        stable_fingerprint=_stable_hash("empty-inventory", label.exact_name, state.value),
    )


def _state_for_provider(state: GmailProviderState) -> EmailInventoryState:
    return {
        GmailProviderState.NOT_CONFIGURED: EmailInventoryState.NOT_CONFIGURED,
        GmailProviderState.AUTHENTICATION_FAILURE: EmailInventoryState.AUTHENTICATION_FAILURE,
        GmailProviderState.PROVIDER_FAILURE: EmailInventoryState.PROVIDER_FAILURE,
        GmailProviderState.MALFORMED_RESPONSE: EmailInventoryState.MALFORMED_RESPONSE,
        GmailProviderState.CONNECTED_EMPTY: EmailInventoryState.INCOMPLETE,
        GmailProviderState.CONNECTED: EmailInventoryState.INCOMPLETE,
    }[state]


def _fact_sort_key(item: InventoryMessageFact) -> tuple[str, str, str]:
    return (
        item.identity.account.provider_account_id,
        item.identity.provider_thread_id or "",
        item.identity.provider_message_id,
    )


def _stable_hash(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"sid230-{digest[:32]}"
