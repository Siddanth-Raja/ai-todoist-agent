"""Deterministic, local-only Email attention analysis.

The service consumes normalized read-only Gmail records and emits SID-143
attention candidates. It intentionally has no model, persistence, mailbox,
task, Calendar, Memory, or UI dependency.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from enum import StrEnum
import hashlib
import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .email_domain import (
    DeterministicEmailEvidence,
    EmailAccountRole,
    EmailAttentionCandidate,
    EmailAttentionKind,
    EmailDeadline,
    EmailDeadlineState,
    EmailEvidenceKind,
    EmailImportance,
    EmailMessageIdentity,
    EmailModelInterpretation,
    EmailOrganizationDisposition,
    EmailOrganizationSuggestion,
    EmailProjectAssociation,
    EmailProjectAssociationState,
    EmailRequestedAction,
    EmailThreadState,
    EmailUrgency,
)
from .gmail_client import (
    GmailClient,
    GmailMessagePage,
    GmailMessageRecord,
    GmailProviderDiagnostic,
    GmailProviderState,
)
from .project_registry import (
    ProjectRegistryService,
    ProjectRegistrySnapshot,
    project_registry_service,
)


DEFAULT_ANALYSIS_MAX_MESSAGES = 12
MAX_ANALYSIS_MESSAGES = 25
MAX_EVIDENCE_EXCERPT_CHARS = 240


class EmailAnalysisState(StrEnum):
    CONNECTED_ATTENTION = "connected_attention"
    CONNECTED_QUIET = "connected_quiet"
    CONNECTED_EMPTY = "connected_empty"
    DEGRADED_PARTIAL = "degraded_partial"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION_FAILURE = "authentication_failure"
    PROVIDER_FAILURE = "provider_failure"
    MALFORMED_RESPONSE = "malformed_response"


class EmailSurfaceDecision(StrEnum):
    SURFACE = "surface"
    QUIET = "quiet"


class EmailSignalCategory(StrEnum):
    UNREAD = "unread"
    PROVIDER_IMPORTANT_LABEL = "provider_important_label"
    BULK_LABEL = "bulk_label"
    AUTOMATED_SENDER = "automated_sender"
    UNSUBSCRIBE_LANGUAGE = "unsubscribe_language"
    PROMOTIONAL_LANGUAGE = "promotional_language"
    EXPLICIT_ACTION = "explicit_action"
    DEADLINE = "deadline"
    AMBIGUOUS_DEADLINE = "ambiguous_deadline"
    SCHEDULING = "scheduling"
    FINANCIAL_REQUIREMENT = "financial_requirement"
    SECURITY_ACCOUNT = "security_account"
    REGISTRATION_FORM = "registration_form"
    ACADEMIC_ADMINISTRATION = "academic_administration"
    PROJECT_CONTEXT = "project_context"
    AMBIGUOUS_PROJECT = "ambiguous_project"
    ATTACHMENT_METADATA = "attachment_metadata"
    RECEIPT_REFERENCE = "receipt_reference"
    GROUNDED_WAITING = "grounded_waiting"
    PARSE_DIAGNOSTIC = "parse_diagnostic"
    BODY_TRUNCATED = "body_truncated"


class EmailInterpretationProvider(Protocol):
    """Optional bounded seam; production leaves it unset and makes no call."""

    def interpret(
        self,
        message: GmailMessageRecord,
        evidence: tuple[DeterministicEmailEvidence, ...],
    ) -> EmailModelInterpretation | None: ...


class EmailAnalysisAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_id: str = Field(min_length=1)
    representative_message: EmailMessageIdentity
    source_message_count: int = Field(ge=1)
    importance: EmailImportance
    urgency: EmailUrgency
    attention_kinds: tuple[EmailAttentionKind, ...] = Field(min_length=1)
    organization_disposition: EmailOrganizationDisposition
    surface_decision: EmailSurfaceDecision
    project_association: EmailProjectAssociation
    evidence_categories: tuple[EmailSignalCategory, ...]
    explanation: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    review_reasons: tuple[str, ...] = ()
    candidate: EmailAttentionCandidate | None = None

    @model_validator(mode="after")
    def preserve_surface_boundary(self) -> "EmailAnalysisAssessment":
        if self.surface_decision == EmailSurfaceDecision.SURFACE:
            if self.candidate is None:
                raise ValueError("surfaced assessment requires an attention candidate")
            if self.candidate.message != self.representative_message:
                raise ValueError("candidate must preserve the representative message")
            if self.candidate.importance != self.importance:
                raise ValueError("candidate importance must match its assessment")
            if self.candidate.urgency != self.urgency:
                raise ValueError("candidate urgency must match its assessment")
        elif self.candidate is not None:
            raise ValueError("quiet assessment cannot contain an attention candidate")
        return self


class EmailAnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: EmailAnalysisState
    provider: Literal["gmail"] = "gmail"
    account_role: EmailAccountRole = EmailAccountRole.PERSONAL
    provider_state: GmailProviderState
    analyzed_message_count: int = Field(ge=0)
    unique_thread_count: int = Field(ge=0)
    assessments: tuple[EmailAnalysisAssessment, ...] = ()
    attention_candidates: tuple[EmailAttentionCandidate, ...] = ()
    quiet_assessment_count: int = Field(ge=0)
    uncertain_review_count: int = Field(ge=0)
    deduplication_count: int = Field(ge=0)
    complete: bool
    truncated: bool
    pages_fetched: int = Field(ge=0)
    provider_diagnostic: GmailProviderDiagnostic | None = None
    computation_timestamp: datetime
    interpretation_calls: int = Field(ge=0)
    provider_mutation_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_counts(self) -> "EmailAnalysisResult":
        if self.unique_thread_count != len(self.assessments):
            raise ValueError("unique thread count must match assessments")
        if self.attention_candidates != tuple(
            assessment.candidate
            for assessment in self.assessments
            if assessment.candidate is not None
        ):
            raise ValueError("candidate collection must derive from surfaced assessments")
        if self.quiet_assessment_count != sum(
            assessment.surface_decision == EmailSurfaceDecision.QUIET
            for assessment in self.assessments
        ):
            raise ValueError("quiet count must match assessments")
        if self.uncertain_review_count != sum(
            assessment.organization_disposition
            == EmailOrganizationDisposition.REVIEW_UNCERTAIN
            for assessment in self.assessments
        ):
            raise ValueError("uncertain count must match assessments")
        if self.deduplication_count != self.analyzed_message_count - self.unique_thread_count:
            raise ValueError("deduplication count must reflect thread grouping")
        return self


_ACTION_RE = re.compile(
    r"\b(?:please|must|required to|need you to|action required|complete|submit|"
    r"review|respond|reply|sign|upload|provide|confirm|register|fill out|pay)\b",
    re.IGNORECASE,
)
_SCHEDULING_RE = re.compile(
    r"\b(?:schedule|reschedule|meeting|appointment|availability|available times?|"
    r"what time works|when can (?:you|we)|calendar invite)\b",
    re.IGNORECASE,
)
_FINANCIAL_RE = re.compile(
    r"\b(?:payment (?:required|due|failed)|balance due|past due|billing issue|"
    r"invoice due|pay by|fee required|card declined)\b",
    re.IGNORECASE,
)
_SECURITY_RE = re.compile(
    r"\b(?:security alert|unusual activity|password reset|account (?:locked|suspended)|"
    r"verify your account|sign[- ]in attempt|two-factor|2fa)\b",
    re.IGNORECASE,
)
_REGISTRATION_RE = re.compile(
    r"\b(?:registration|register|enrollment|application form|required form|"
    r"complete the form|submit the form|waiver|authorization form)\b",
    re.IGNORECASE,
)
_ACADEMIC_RE = re.compile(
    r"\b(?:financial aid|admissions?|registrar|tuition|course|class|semester|"
    r"student account|transcript|campus housing|academic)\b",
    re.IGNORECASE,
)
_RECEIPT_RE = re.compile(
    r"\b(?:receipt|order confirmation|payment confirmation|transaction record|"
    r"purchase confirmation)\b",
    re.IGNORECASE,
)
_PROMOTIONAL_RE = re.compile(
    r"\b(?:newsletter|sale|discount|promotion|special offer|shop now|limited offer|"
    r"marketing update)\b",
    re.IGNORECASE,
)
_UNSUBSCRIBE_RE = re.compile(r"\bunsubscribe\b", re.IGNORECASE)
_AUTOMATED_SENDER_RE = re.compile(
    r"(?:^|[<\s])(no[-_. ]?reply|do[-_. ]?not[-_. ]?reply|notifications?)@?",
    re.IGNORECASE,
)
_WAITING_RE = re.compile(
    r"\b(?:following up|waiting for|awaiting|let me know|please confirm|"
    r"when you have a chance|circle back)\b",
    re.IGNORECASE,
)
_URGENT_RE = re.compile(
    r"\b(?:urgent|immediately|past due|final notice|action required today|due today)\b",
    re.IGNORECASE,
)
_DEADLINE_CONTEXT_RE = re.compile(
    r"\b(?:due|deadline|before|no later than|expires? on|registration closes?)\b|"
    r"\b(?:submit|complete|pay|register)[^.\n]{0,80}\bby\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b")
_NUMERIC_FULL_DATE_RE = re.compile(
    r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/20\d{2}\b"
)
_MONTH_NAME = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_MONTH_FULL_DATE_RE = re.compile(
    rf"\b{_MONTH_NAME}\s+\d{{1,2}}(?:st|nd|rd|th)?,\s+20\d{{2}}\b",
    re.IGNORECASE,
)
_MONTH_DAY_RE = re.compile(
    rf"\b{_MONTH_NAME}\s+\d{{1,2}}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_RELATIVE_DATE_RE = re.compile(
    r"\b(?:today|tomorrow|next (?:monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|week)|this (?:monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)|end of day|eod)\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", re.IGNORECASE)
_TIMEZONE_RE = re.compile(
    r"\b(?:UTC|GMT|CST|CDT|EST|EDT|MST|MDT|PST|PDT|CT|ET|MT|PT)\b|[+-]\d{4}\b",
    re.IGNORECASE,
)


class EmailAnalysisService:
    def __init__(
        self,
        *,
        registry_service: ProjectRegistryService = project_registry_service,
        interpretation_provider: EmailInterpretationProvider | None = None,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._registry_service = registry_service
        self._interpretation_provider = interpretation_provider
        self._clock = clock

    def analyze_recent(
        self,
        client: GmailClient,
        *,
        max_messages: int = DEFAULT_ANALYSIS_MAX_MESSAGES,
    ) -> EmailAnalysisResult:
        if max_messages < 1 or max_messages > MAX_ANALYSIS_MESSAGES:
            raise ValueError(
                f"max_messages must be between 1 and {MAX_ANALYSIS_MESSAGES}"
            )
        page = client.list_recent_messages(max_messages=max_messages)
        return self.analyze_page(
            page,
            registry=self._registry_service.snapshot(),
            account_role=getattr(client, "account_role", EmailAccountRole.PERSONAL),
        )

    def analyze_page(
        self,
        page: GmailMessagePage,
        *,
        registry: ProjectRegistrySnapshot,
        account_role: EmailAccountRole = EmailAccountRole.PERSONAL,
    ) -> EmailAnalysisResult:
        computed_at = self._clock()
        if page.state not in {GmailProviderState.CONNECTED, GmailProviderState.CONNECTED_EMPTY}:
            return _empty_result(
                state=_analysis_state_for_provider(page.state),
                page=page,
                computed_at=computed_at,
                account_role=account_role,
            )
        if not page.messages:
            return _empty_result(
                state=EmailAnalysisState.CONNECTED_EMPTY,
                page=page,
                computed_at=computed_at,
                account_role=account_role,
            )
        if not _single_account(page.messages, account_role=account_role):
            diagnostic = GmailProviderDiagnostic(
                code="malformed_response",
                message="Email analysis received inconsistent account identity.",
            )
            malformed = page.model_copy(
                update={
                    "state": GmailProviderState.MALFORMED_RESPONSE,
                    "messages": (),
                    "diagnostic": diagnostic,
                }
            )
            return _empty_result(
                state=EmailAnalysisState.MALFORMED_RESPONSE,
                page=malformed,
                computed_at=computed_at,
                account_role=account_role,
            )

        groups: dict[tuple[str, str, str, str], list[GmailMessageRecord]] = defaultdict(list)
        for message in page.messages:
            identity = message.identity
            group_kind = "thread" if identity.provider_thread_id else "message"
            group_value = identity.provider_thread_id or identity.provider_message_id
            groups[
                (
                    identity.account.provider,
                    identity.account.provider_account_id,
                    group_kind,
                    group_value,
                )
            ].append(message)

        interpretation_calls = 0
        assessments: list[EmailAnalysisAssessment] = []
        for group_key, records in groups.items():
            assessment, called = self._assess_group(group_key, tuple(records), registry)
            assessments.append(assessment)
            interpretation_calls += called
        assessments.sort(
            key=lambda item: (
                -_message_sort_value(_representative_for_identity(item, page.messages)),
                item.assessment_id,
            )
        )
        assessment_tuple = tuple(assessments)
        candidates = tuple(
            assessment.candidate
            for assessment in assessment_tuple
            if assessment.candidate is not None
        )
        degraded = any(
            message.parse_diagnostics or message.body_truncated
            for message in page.messages
        )
        if degraded:
            state = EmailAnalysisState.DEGRADED_PARTIAL
        elif candidates:
            state = EmailAnalysisState.CONNECTED_ATTENTION
        else:
            state = EmailAnalysisState.CONNECTED_QUIET
        return EmailAnalysisResult(
            state=state,
            account_role=account_role,
            provider_state=page.state,
            analyzed_message_count=len(page.messages),
            unique_thread_count=len(assessment_tuple),
            assessments=assessment_tuple,
            attention_candidates=candidates,
            quiet_assessment_count=sum(
                item.surface_decision == EmailSurfaceDecision.QUIET
                for item in assessment_tuple
            ),
            uncertain_review_count=sum(
                item.organization_disposition
                == EmailOrganizationDisposition.REVIEW_UNCERTAIN
                for item in assessment_tuple
            ),
            deduplication_count=len(page.messages) - len(assessment_tuple),
            complete=page.complete,
            truncated=page.truncated,
            pages_fetched=page.pages_fetched,
            provider_diagnostic=page.diagnostic,
            computation_timestamp=computed_at,
            interpretation_calls=interpretation_calls,
        )

    def _assess_group(
        self,
        group_key: tuple[str, str, str, str],
        records: tuple[GmailMessageRecord, ...],
        registry: ProjectRegistrySnapshot,
    ) -> tuple[EmailAnalysisAssessment, int]:
        representative = max(records, key=_record_sort_key)
        inbound_records = tuple(
            record
            for record in records
            if "SENT" not in {label.upper() for label in record.label_ids}
        )
        text = _combined_text(inbound_records)
        labels = {label.upper() for record in records for label in record.label_ids}
        evidence: list[DeterministicEmailEvidence] = []
        categories: list[EmailSignalCategory] = []

        def signal(
            category: EmailSignalCategory,
            matched_evidence: DeterministicEmailEvidence | None = None,
        ) -> None:
            if category not in categories:
                categories.append(category)
            if matched_evidence is not None and matched_evidence not in evidence:
                evidence.append(matched_evidence)

        if any(record.unread for record in records):
            signal(EmailSignalCategory.UNREAD, _provider_evidence("unread"))
        if "IMPORTANT" in labels:
            signal(
                EmailSignalCategory.PROVIDER_IMPORTANT_LABEL,
                _provider_evidence("provider_important_label"),
            )
        if labels.intersection({"CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_SOCIAL"}):
            signal(EmailSignalCategory.BULK_LABEL, _provider_evidence("bulk_category_label"))
        if any(record.attachments for record in records):
            signal(
                EmailSignalCategory.ATTACHMENT_METADATA,
                _provider_evidence("attachment_metadata_present"),
            )
        if any(record.parse_diagnostics for record in records):
            signal(
                EmailSignalCategory.PARSE_DIAGNOSTIC,
                _provider_evidence("message_parse_diagnostic_present"),
            )
        if any(record.body_truncated for record in records):
            signal(
                EmailSignalCategory.BODY_TRUNCATED,
                _provider_evidence("bounded_body_was_truncated"),
            )

        sender_text = "\n".join(record.sender or "" for record in inbound_records)
        if _AUTOMATED_SENDER_RE.search(sender_text):
            signal(
                EmailSignalCategory.AUTOMATED_SENDER,
                _first_evidence(inbound_records, _AUTOMATED_SENDER_RE, include_sender=True),
            )
        if _UNSUBSCRIBE_RE.search(text):
            signal(
                EmailSignalCategory.UNSUBSCRIBE_LANGUAGE,
                _first_evidence(inbound_records, _UNSUBSCRIBE_RE),
            )
        if _PROMOTIONAL_RE.search(text):
            signal(
                EmailSignalCategory.PROMOTIONAL_LANGUAGE,
                _first_evidence(inbound_records, _PROMOTIONAL_RE),
            )

        action_evidence = _first_evidence(inbound_records, _ACTION_RE)
        scheduling_evidence = _first_evidence(inbound_records, _SCHEDULING_RE)
        financial_evidence = _first_evidence(inbound_records, _FINANCIAL_RE)
        security_evidence = _first_evidence(inbound_records, _SECURITY_RE)
        registration_evidence = _first_evidence(inbound_records, _REGISTRATION_RE)
        academic_evidence = _first_evidence(inbound_records, _ACADEMIC_RE)
        receipt_evidence = _first_evidence(inbound_records, _RECEIPT_RE)
        if action_evidence:
            signal(EmailSignalCategory.EXPLICIT_ACTION, action_evidence)
        if scheduling_evidence:
            signal(EmailSignalCategory.SCHEDULING, scheduling_evidence)
        if financial_evidence:
            signal(EmailSignalCategory.FINANCIAL_REQUIREMENT, financial_evidence)
        if security_evidence:
            signal(EmailSignalCategory.SECURITY_ACCOUNT, security_evidence)
        if registration_evidence:
            signal(EmailSignalCategory.REGISTRATION_FORM, registration_evidence)
        if academic_evidence:
            signal(EmailSignalCategory.ACADEMIC_ADMINISTRATION, academic_evidence)
        if receipt_evidence:
            signal(EmailSignalCategory.RECEIPT_REFERENCE, receipt_evidence)

        deadline, deadline_review = _deadline_from_records(inbound_records)
        if deadline is not None:
            deadline_category = (
                EmailSignalCategory.DEADLINE
                if deadline.state == EmailDeadlineState.GROUNDED
                else EmailSignalCategory.AMBIGUOUS_DEADLINE
            )
            for item in deadline.source_evidence:
                signal(deadline_category, item)

        project_association = _project_association(inbound_records, registry)
        if project_association.state == EmailProjectAssociationState.GROUNDED:
            for item in project_association.evidence:
                signal(EmailSignalCategory.PROJECT_CONTEXT, item)
        elif project_association.state == EmailProjectAssociationState.AMBIGUOUS:
            for item in project_association.evidence:
                signal(EmailSignalCategory.AMBIGUOUS_PROJECT, item)

        waiting = _grounded_waiting(records)
        if waiting:
            signal(
                EmailSignalCategory.GROUNDED_WAITING,
                _first_evidence((representative,), _WAITING_RE),
            )

        bulk_count = sum(
            category
            in {
                EmailSignalCategory.BULK_LABEL,
                EmailSignalCategory.AUTOMATED_SENDER,
                EmailSignalCategory.UNSUBSCRIBE_LANGUAGE,
                EmailSignalCategory.PROMOTIONAL_LANGUAGE,
            }
            for category in categories
        )
        protected = any(
            category
            in {
                EmailSignalCategory.EXPLICIT_ACTION,
                EmailSignalCategory.DEADLINE,
                EmailSignalCategory.AMBIGUOUS_DEADLINE,
                EmailSignalCategory.SCHEDULING,
                EmailSignalCategory.FINANCIAL_REQUIREMENT,
                EmailSignalCategory.SECURITY_ACCOUNT,
                EmailSignalCategory.REGISTRATION_FORM,
                EmailSignalCategory.ACADEMIC_ADMINISTRATION,
                EmailSignalCategory.PROJECT_CONTEXT,
                EmailSignalCategory.AMBIGUOUS_PROJECT,
                EmailSignalCategory.ATTACHMENT_METADATA,
            }
            for category in categories
        )
        material_ambiguity = any(
            category
            in {
                EmailSignalCategory.AMBIGUOUS_DEADLINE,
                EmailSignalCategory.AMBIGUOUS_PROJECT,
                EmailSignalCategory.PARSE_DIAGNOSTIC,
                EmailSignalCategory.BODY_TRUNCATED,
            }
            for category in categories
        ) or (bulk_count >= 2 and protected)

        if material_ambiguity:
            disposition = EmailOrganizationDisposition.REVIEW_UNCERTAIN
        elif waiting:
            disposition = EmailOrganizationDisposition.WAITING
        elif any(
            category
            in {
                EmailSignalCategory.EXPLICIT_ACTION,
                EmailSignalCategory.DEADLINE,
                EmailSignalCategory.SCHEDULING,
                EmailSignalCategory.FINANCIAL_REQUIREMENT,
                EmailSignalCategory.SECURITY_ACCOUNT,
                EmailSignalCategory.REGISTRATION_FORM,
                EmailSignalCategory.ACADEMIC_ADMINISTRATION,
            }
            for category in categories
        ):
            disposition = EmailOrganizationDisposition.NEEDS_ACTION
        elif EmailSignalCategory.RECEIPT_REFERENCE in categories:
            disposition = EmailOrganizationDisposition.KEEP_REFERENCE
        elif bulk_count >= 2 and not protected:
            disposition = EmailOrganizationDisposition.LOW_VALUE
        else:
            disposition = EmailOrganizationDisposition.KEEP_REFERENCE

        surface = (
            disposition
            in {
                EmailOrganizationDisposition.NEEDS_ACTION,
                EmailOrganizationDisposition.WAITING,
                EmailOrganizationDisposition.REVIEW_UNCERTAIN,
            }
            or EmailSignalCategory.PROJECT_CONTEXT in categories
        )
        surface_decision = (
            EmailSurfaceDecision.SURFACE if surface else EmailSurfaceDecision.QUIET
        )
        attention_kinds = _attention_kinds(categories)
        importance = _importance(categories)
        urgency = _urgency(text, categories)
        review_reasons = _review_reasons(
            project_association=project_association,
            deadline_review=deadline_review,
            material_ambiguity=material_ambiguity,
            bulk_conflict=bulk_count >= 2 and protected,
            categories=categories,
            surfaced=surface,
        )
        confidence = 0.65 if material_ambiguity else (0.9 if review_reasons else 1.0)
        assessment_id = _opaque_identity("assessment", group_key)
        candidate_id = _opaque_identity("candidate", group_key)
        explanation = _explanation(categories, disposition, surface_decision)

        candidate: EmailAttentionCandidate | None = None
        interpretation_calls = 0
        if surface:
            requested_action = None
            if EmailAttentionKind.EXPLICIT_ACTION_REQUEST in attention_kinds:
                requested_action = EmailRequestedAction(
                    description="Review and complete the grounded requested action.",
                    responsible_party="account owner",
                    source_evidence=(action_evidence,) if action_evidence else tuple(evidence[:1]),
                )
            interpretation = None
            if self._interpretation_provider is not None:
                interpretation_calls = 1
                interpretation = self._interpretation_provider.interpret(
                    representative,
                    tuple(evidence),
                )
            candidate = EmailAttentionCandidate(
                candidate_id=candidate_id,
                message=representative.identity,
                received_at=representative.internal_date,
                sent_at=representative.message_date,
                thread_state=_thread_state(records),
                attention_kinds=attention_kinds,
                importance=importance,
                urgency=urgency,
                deadline=deadline,
                requested_action=requested_action,
                project_association=project_association,
                confidence=confidence,
                review_reasons=review_reasons,
                deterministic_evidence=tuple(evidence),
                model_interpretation=interpretation,
                organization_suggestion=EmailOrganizationSuggestion(
                    disposition=disposition,
                ),
                provider_metadata={
                    "analysis_version": "sid-146-v1",
                    "assessment_id": assessment_id,
                    "source_message_count": len(records),
                    "surface_decision": surface_decision.value,
                    "evidence_categories": [item.value for item in categories],
                    "explanation": explanation,
                },
            )

        return (
            EmailAnalysisAssessment(
                assessment_id=assessment_id,
                representative_message=representative.identity,
                source_message_count=len(records),
                importance=importance,
                urgency=urgency,
                attention_kinds=attention_kinds,
                organization_disposition=disposition,
                surface_decision=surface_decision,
                project_association=project_association,
                evidence_categories=tuple(categories),
                explanation=explanation,
                confidence=confidence,
                review_reasons=review_reasons,
                candidate=candidate,
            ),
            interpretation_calls,
        )


def _empty_result(
    *,
    state: EmailAnalysisState,
    page: GmailMessagePage,
    computed_at: datetime,
    account_role: EmailAccountRole = EmailAccountRole.PERSONAL,
) -> EmailAnalysisResult:
    return EmailAnalysisResult(
        state=state,
        account_role=account_role,
        provider_state=page.state,
        analyzed_message_count=0,
        unique_thread_count=0,
        quiet_assessment_count=0,
        uncertain_review_count=0,
        deduplication_count=0,
        complete=page.complete,
        truncated=page.truncated,
        pages_fetched=page.pages_fetched,
        provider_diagnostic=page.diagnostic,
        computation_timestamp=computed_at,
        interpretation_calls=0,
    )


def _analysis_state_for_provider(state: GmailProviderState) -> EmailAnalysisState:
    return {
        GmailProviderState.NOT_CONFIGURED: EmailAnalysisState.NOT_CONFIGURED,
        GmailProviderState.AUTHENTICATION_FAILURE: EmailAnalysisState.AUTHENTICATION_FAILURE,
        GmailProviderState.PROVIDER_FAILURE: EmailAnalysisState.PROVIDER_FAILURE,
        GmailProviderState.MALFORMED_RESPONSE: EmailAnalysisState.MALFORMED_RESPONSE,
        GmailProviderState.CONNECTED_EMPTY: EmailAnalysisState.CONNECTED_EMPTY,
        GmailProviderState.CONNECTED: EmailAnalysisState.CONNECTED_QUIET,
    }[state]


def _single_account(
    messages: tuple[GmailMessageRecord, ...], *, account_role: EmailAccountRole
) -> bool:
    accounts = {message.identity.account for message in messages}
    return len(accounts) == 1 and next(iter(accounts)).account_role == account_role


def _record_sort_key(record: GmailMessageRecord) -> tuple[float, str]:
    return (_message_sort_value(record), record.identity.provider_message_id)


def _message_sort_value(record: GmailMessageRecord) -> float:
    value = record.internal_date or record.message_date
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _representative_for_identity(
    assessment: EmailAnalysisAssessment,
    messages: tuple[GmailMessageRecord, ...],
) -> GmailMessageRecord:
    return next(
        message
        for message in messages
        if message.identity == assessment.representative_message
    )


def _combined_text(records: tuple[GmailMessageRecord, ...]) -> str:
    return "\n".join(
        value
        for record in records
        for value in (record.subject, record.body_text, record.snippet)
        if value
    )


def _provider_evidence(value: str) -> DeterministicEmailEvidence:
    return DeterministicEmailEvidence(
        kind=EmailEvidenceKind.PROVIDER_FACT,
        source_field="gmail_record",
        value=value,
    )


def _first_evidence(
    records: tuple[GmailMessageRecord, ...],
    pattern: re.Pattern[str],
    *,
    include_sender: bool = False,
) -> DeterministicEmailEvidence | None:
    for record in sorted(records, key=_record_sort_key, reverse=True):
        fields: list[tuple[EmailEvidenceKind, str, str | None]] = [
            (EmailEvidenceKind.SUBJECT, "subject", record.subject),
            (EmailEvidenceKind.BODY_EXCERPT, "body_text", record.body_text),
        ]
        if include_sender:
            fields.append((EmailEvidenceKind.SENDER, "sender", record.sender))
        for kind, source_field, value in fields:
            if value and (match := pattern.search(value)):
                return DeterministicEmailEvidence(
                    kind=kind,
                    source_field=source_field,
                    value=_bounded_excerpt(value, match.start(), match.end()),
                )
    return None


def _bounded_excerpt(value: str, start: int, end: int) -> str:
    radius = max(20, (MAX_EVIDENCE_EXCERPT_CHARS - (end - start)) // 2)
    excerpt = " ".join(value[max(0, start - radius) : end + radius].split())
    return excerpt[:MAX_EVIDENCE_EXCERPT_CHARS] or value[start:end][:MAX_EVIDENCE_EXCERPT_CHARS]


def _deadline_from_records(
    records: tuple[GmailMessageRecord, ...],
) -> tuple[EmailDeadline | None, str | None]:
    sources = [
        (kind, field, value)
        for record in sorted(records, key=_record_sort_key, reverse=True)
        for kind, field, value in (
            (EmailEvidenceKind.SUBJECT, "subject", record.subject),
            (EmailEvidenceKind.BODY_EXCERPT, "body_text", record.body_text),
        )
        if value and _DEADLINE_CONTEXT_RE.search(value)
    ]
    if not sources:
        return None, None

    parsed: list[tuple[date, DeterministicEmailEvidence]] = []
    ambiguous_evidence: DeterministicEmailEvidence | None = None
    ambiguity_reason: str | None = None
    for kind, field, value in sources:
        assert value is not None
        for pattern, parser in (
            (_ISO_DATE_RE, _parse_iso_date),
            (_NUMERIC_FULL_DATE_RE, _parse_numeric_date),
            (_MONTH_FULL_DATE_RE, _parse_month_date),
        ):
            for match in pattern.finditer(value):
                parsed_date = parser(match.group(0))
                evidence = DeterministicEmailEvidence(
                    kind=kind,
                    source_field=field,
                    value=match.group(0),
                )
                if parsed_date is None:
                    ambiguous_evidence = evidence
                    ambiguity_reason = "The stated deadline date is not valid."
                else:
                    parsed.append((parsed_date, evidence))

        if _TIME_RE.search(value) and not _TIMEZONE_RE.search(value):
            match = _TIME_RE.search(value)
            assert match is not None
            ambiguous_evidence = DeterministicEmailEvidence(
                kind=kind,
                source_field=field,
                value=_bounded_excerpt(value, match.start(), match.end()),
            )
            ambiguity_reason = "The deadline includes a time without a trustworthy timezone."
        elif not parsed:
            match = _RELATIVE_DATE_RE.search(value) or _MONTH_DAY_RE.search(value)
            if match:
                ambiguous_evidence = DeterministicEmailEvidence(
                    kind=kind,
                    source_field=field,
                    value=_bounded_excerpt(value, match.start(), match.end()),
                )
                ambiguity_reason = (
                    "The deadline is relative or omits a required year."
                )

    unique_dates = {item[0] for item in parsed}
    if len(unique_dates) > 1:
        evidence = tuple(dict.fromkeys(item[1] for item in parsed))
        return (
            EmailDeadline(
                state=EmailDeadlineState.AMBIGUOUS,
                source_evidence=evidence,
                ambiguity_reason="The message contains conflicting fully specified dates.",
            ),
            "Conflicting deadline dates require review.",
        )
    if ambiguity_reason and ambiguous_evidence is not None:
        evidence = tuple(dict.fromkeys([item[1] for item in parsed] + [ambiguous_evidence]))
        return (
            EmailDeadline(
                state=EmailDeadlineState.AMBIGUOUS,
                source_evidence=evidence,
                ambiguity_reason=ambiguity_reason,
            ),
            ambiguity_reason,
        )
    if parsed:
        parsed_date, evidence = parsed[0]
        return (
            EmailDeadline(
                state=EmailDeadlineState.GROUNDED,
                value=parsed_date,
                source_evidence=(evidence,),
            ),
            None,
        )
    return None, None


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_numeric_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError:
        return None


def _parse_month_date(value: str) -> date | None:
    normalized = re.sub(r"(\d)(?:st|nd|rd|th)", r"\1", value, flags=re.IGNORECASE)
    for pattern in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def _project_association(
    records: tuple[GmailMessageRecord, ...],
    registry: ProjectRegistrySnapshot,
) -> EmailProjectAssociation:
    matches: dict[str, DeterministicEmailEvidence] = {}
    aliases_by_key: dict[str, set[str]] = defaultdict(set)
    for alias, key in registry.aliases.items():
        aliases_by_key[key].add(alias.replace("-", " "))
    for project in registry.projects:
        if project.get("system_state") or not project.get("canonical_project_id"):
            continue
        key = str(project["key"])
        terms = {
            str(project.get("name") or ""),
            key.replace("-", " "),
            *(str(value) for value in project.get("keywords", ())),
            *(str(value) for value in project.get("people", ())),
            *aliases_by_key.get(key, set()),
        }
        for term in sorted((term.strip() for term in terms if term.strip()), key=len, reverse=True):
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", re.IGNORECASE)
            evidence = _first_evidence(records, pattern, include_sender=True)
            if evidence is not None:
                matches[str(project["canonical_project_id"])] = evidence
                break
    ids = tuple(matches)
    evidence = tuple(dict.fromkeys(matches.values()))
    if len(ids) == 1:
        return EmailProjectAssociation(
            state=EmailProjectAssociationState.GROUNDED,
            canonical_project_id=ids[0],
            evidence=evidence,
        )
    if len(ids) > 1:
        return EmailProjectAssociation(
            state=EmailProjectAssociationState.AMBIGUOUS,
            candidate_project_ids=ids,
            evidence=evidence,
        )
    return EmailProjectAssociation(state=EmailProjectAssociationState.UNRESOLVED)


def _grounded_waiting(records: tuple[GmailMessageRecord, ...]) -> bool:
    if len(records) < 2:
        return False
    ordered = sorted(records, key=_record_sort_key)
    latest = ordered[-1]
    latest_text = "\n".join(value for value in (latest.subject, latest.body_text) if value)
    return (
        "SENT" in {label.upper() for label in latest.label_ids}
        and any("SENT" not in {label.upper() for label in item.label_ids} for item in ordered[:-1])
        and bool(_WAITING_RE.search(latest_text))
    )


def _thread_state(records: tuple[GmailMessageRecord, ...]) -> EmailThreadState:
    latest = max(records, key=_record_sort_key)
    has_user_reply = (
        True
        if any("SENT" in {label.upper() for label in record.label_ids} for record in records)
        else None
    )
    return EmailThreadState(
        is_unread=any(record.unread for record in records),
        has_user_reply=has_user_reply,
        latest_message_at=latest.internal_date or latest.message_date,
    )


def _attention_kinds(
    categories: list[EmailSignalCategory],
) -> tuple[EmailAttentionKind, ...]:
    kinds: list[EmailAttentionKind] = []
    if EmailSignalCategory.DEADLINE in categories or EmailSignalCategory.AMBIGUOUS_DEADLINE in categories:
        kinds.append(EmailAttentionKind.DEADLINE)
    if EmailSignalCategory.EXPLICIT_ACTION in categories:
        kinds.append(EmailAttentionKind.EXPLICIT_ACTION_REQUEST)
    if EmailSignalCategory.SCHEDULING in categories:
        kinds.append(EmailAttentionKind.SCHEDULING_REQUEST)
    if any(
        category in categories
        for category in (
            EmailSignalCategory.FINANCIAL_REQUIREMENT,
            EmailSignalCategory.SECURITY_ACCOUNT,
            EmailSignalCategory.REGISTRATION_FORM,
            EmailSignalCategory.ACADEMIC_ADMINISTRATION,
        )
    ):
        kinds.append(EmailAttentionKind.ADMINISTRATIVE_REQUIREMENT)
    if any(
        category in categories
        for category in (
            EmailSignalCategory.PROJECT_CONTEXT,
            EmailSignalCategory.AMBIGUOUS_PROJECT,
        )
    ):
        kinds.append(EmailAttentionKind.PROJECT_COMMUNICATION)
    if not kinds and any(
        category in categories
        for category in (
            EmailSignalCategory.ATTACHMENT_METADATA,
            EmailSignalCategory.GROUNDED_WAITING,
            EmailSignalCategory.PARSE_DIAGNOSTIC,
            EmailSignalCategory.BODY_TRUNCATED,
        )
    ):
        kinds.append(EmailAttentionKind.IMPORTANT_ATTENTION)
    return tuple(kinds or [EmailAttentionKind.INFORMATIONAL])


def _importance(categories: list[EmailSignalCategory]) -> EmailImportance:
    if any(
        category in categories
        for category in (
            EmailSignalCategory.EXPLICIT_ACTION,
            EmailSignalCategory.DEADLINE,
            EmailSignalCategory.FINANCIAL_REQUIREMENT,
            EmailSignalCategory.SECURITY_ACCOUNT,
            EmailSignalCategory.REGISTRATION_FORM,
            EmailSignalCategory.ACADEMIC_ADMINISTRATION,
        )
    ):
        return EmailImportance.HIGH
    if any(
        category in categories
        for category in (
            EmailSignalCategory.AMBIGUOUS_DEADLINE,
            EmailSignalCategory.SCHEDULING,
            EmailSignalCategory.PROJECT_CONTEXT,
            EmailSignalCategory.AMBIGUOUS_PROJECT,
            EmailSignalCategory.ATTACHMENT_METADATA,
            EmailSignalCategory.PROVIDER_IMPORTANT_LABEL,
            EmailSignalCategory.GROUNDED_WAITING,
        )
    ):
        return EmailImportance.MEDIUM
    return EmailImportance.LOW


def _urgency(text: str, categories: list[EmailSignalCategory]) -> EmailUrgency:
    if _URGENT_RE.search(text):
        return EmailUrgency.HIGH
    if any(
        category in categories
        for category in (
            EmailSignalCategory.DEADLINE,
            EmailSignalCategory.AMBIGUOUS_DEADLINE,
            EmailSignalCategory.EXPLICIT_ACTION,
            EmailSignalCategory.SCHEDULING,
            EmailSignalCategory.FINANCIAL_REQUIREMENT,
            EmailSignalCategory.SECURITY_ACCOUNT,
        )
    ):
        return EmailUrgency.MEDIUM
    return EmailUrgency.LOW


def _review_reasons(
    *,
    project_association: EmailProjectAssociation,
    deadline_review: str | None,
    material_ambiguity: bool,
    bulk_conflict: bool,
    categories: list[EmailSignalCategory],
    surfaced: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if deadline_review:
        reasons.append(deadline_review)
    if project_association.state == EmailProjectAssociationState.AMBIGUOUS:
        reasons.append("Multiple canonical projects have grounded matching evidence.")
    elif surfaced and project_association.state == EmailProjectAssociationState.UNRESOLVED:
        reasons.append("No canonical project association was grounded.")
    if bulk_conflict:
        reasons.append("Bulk-mail evidence conflicts with a protected attention signal.")
    if EmailSignalCategory.PARSE_DIAGNOSTIC in categories:
        reasons.append("Provider parsing diagnostics may hide relevant message content.")
    if EmailSignalCategory.BODY_TRUNCATED in categories:
        reasons.append("The analyzable body reached its safety bound.")
    if material_ambiguity and not reasons:
        reasons.append("Material deterministic evidence requires review.")
    return tuple(dict.fromkeys(reasons))


def _explanation(
    categories: list[EmailSignalCategory],
    disposition: EmailOrganizationDisposition,
    surface: EmailSurfaceDecision,
) -> str:
    meaningful = [
        category.value.replace("_", " ")
        for category in categories
        if category not in {EmailSignalCategory.UNREAD}
    ]
    evidence_text = ", ".join(meaningful[:5]) or "informational provider facts"
    return (
        f"Decision: {surface.value}; disposition: {disposition.value}; "
        f"grounded evidence categories: {evidence_text}."
    )


def _opaque_identity(prefix: str, group_key: tuple[str, str, str, str]) -> str:
    digest = hashlib.sha256("\x1f".join(group_key).encode("utf-8")).hexdigest()
    return f"email-{prefix}-{digest[:24]}"
