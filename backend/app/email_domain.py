"""Provider-neutral Email Attention domain contracts.

These models describe observed email state, attention candidates, and advisory
organization suggestions. They intentionally contain no provider client,
classification behavior, executable action payload, or mailbox mutation.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EmailAccountRole(StrEnum):
    PERSONAL = "personal"
    AM = "am"
    BLINN = "blinn"
    FREELANCE = "freelance"


class EmailAttentionKind(StrEnum):
    INFORMATIONAL = "informational"
    IMPORTANT_ATTENTION = "important_attention"
    DEADLINE = "deadline"
    EXPLICIT_ACTION_REQUEST = "explicit_action_request"
    SCHEDULING_REQUEST = "scheduling_request"
    ADMINISTRATIVE_REQUIREMENT = "administrative_requirement"
    PROJECT_COMMUNICATION = "project_communication"


class EmailImportance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EmailUrgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EmailDeadlineState(StrEnum):
    GROUNDED = "grounded"
    AMBIGUOUS = "ambiguous"


class EmailProjectAssociationState(StrEnum):
    GROUNDED = "grounded"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class EmailProposalKind(StrEnum):
    TASK = "task"
    CALENDAR = "calendar"


class EmailCandidateLifecycle(StrEnum):
    ACTIVE = "active"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class EmailEvidenceKind(StrEnum):
    SENDER = "sender"
    RECIPIENT = "recipient"
    SUBJECT = "subject"
    BODY_EXCERPT = "body_excerpt"
    TIMESTAMP = "timestamp"
    PROVIDER_FACT = "provider_fact"


class EmailOrganizationDisposition(StrEnum):
    NEEDS_ACTION = "needs_action"
    WAITING = "waiting"
    KEEP_REFERENCE = "keep_reference"
    LOW_VALUE = "low_value"
    REVIEW_UNCERTAIN = "review_uncertain"


class EmailProviderAccountIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)
    account_role: EmailAccountRole
    provider_account_id: str = Field(min_length=1)

    @field_validator("provider", "provider_account_id")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider identity values cannot be blank")
        return value


class EmailMessageIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account: EmailProviderAccountIdentity
    provider_message_id: str = Field(min_length=1)
    provider_thread_id: str | None = Field(default=None, min_length=1)

    @field_validator("provider_message_id", "provider_thread_id")
    @classmethod
    def reject_blank_message_identity(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("message and thread identity values cannot be blank")
        return value


class EmailThreadState(BaseModel):
    """Provider-neutral thread facts only when the adapter actually knows them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_unread: bool | None = None
    has_user_reply: bool | None = None
    latest_message_at: datetime | None = None

    @model_validator(mode="after")
    def require_known_thread_fact(self) -> "EmailThreadState":
        if (
            self.is_unread is None
            and self.has_user_reply is None
            and self.latest_message_at is None
        ):
            raise ValueError("thread state must contain at least one known fact")
        return self


class DeterministicEmailEvidence(BaseModel):
    """Observed evidence; never a model-generated interpretation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EmailEvidenceKind
    source_field: str = Field(min_length=1)
    value: str = Field(min_length=1)

    @field_validator("source_field", "value")
    @classmethod
    def reject_blank_evidence(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence fields cannot be blank")
        return value


class EmailModelInterpretation(BaseModel):
    """Bounded model output kept distinct from deterministic evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty_reasons: tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model interpretation summary cannot be blank")
        return value

    @field_validator("uncertainty_reasons")
    @classmethod
    def validate_uncertainty_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("uncertainty reasons cannot be blank")
        return values

    @model_validator(mode="after")
    def preserve_bounded_uncertainty(self) -> "EmailModelInterpretation":
        if self.confidence < 1.0 and not self.uncertainty_reasons:
            raise ValueError("non-certain model interpretation requires uncertainty reasons")
        return self


class EmailDeadline(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: EmailDeadlineState
    value: date | datetime | None = None
    source_evidence: tuple[DeterministicEmailEvidence, ...] = Field(min_length=1)
    ambiguity_reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def preserve_deadline_certainty(self) -> "EmailDeadline":
        if self.state == EmailDeadlineState.GROUNDED:
            if self.value is None:
                raise ValueError("grounded deadline requires a value")
            if self.ambiguity_reason is not None:
                raise ValueError("grounded deadline cannot have an ambiguity reason")
        else:
            if self.value is not None:
                raise ValueError("ambiguous deadline cannot claim a concrete value")
            if self.ambiguity_reason is None or not self.ambiguity_reason.strip():
                raise ValueError("ambiguous deadline requires an ambiguity reason")
        return self


class EmailRequestedAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1)
    responsible_party: str | None = Field(default=None, min_length=1)
    source_evidence: tuple[DeterministicEmailEvidence, ...] = Field(min_length=1)

    @field_validator("description", "responsible_party")
    @classmethod
    def reject_blank_action_fields(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("requested-action fields cannot be blank")
        return value


class EmailProjectAssociation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: EmailProjectAssociationState
    canonical_project_id: str | None = Field(default=None, min_length=1)
    candidate_project_ids: tuple[str, ...] = ()
    evidence: tuple[DeterministicEmailEvidence, ...] = ()

    @field_validator("candidate_project_ids")
    @classmethod
    def validate_candidate_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("candidate project IDs cannot be blank")
        if len(values) != len(set(values)):
            raise ValueError("candidate project IDs must be unique")
        return values

    @model_validator(mode="after")
    def preserve_association_certainty(self) -> "EmailProjectAssociation":
        if self.state == EmailProjectAssociationState.GROUNDED:
            if self.canonical_project_id is None:
                raise ValueError("grounded project association requires a canonical project ID")
            if self.candidate_project_ids:
                raise ValueError("grounded project association cannot retain ambiguous candidates")
        elif self.state == EmailProjectAssociationState.AMBIGUOUS:
            if self.canonical_project_id is not None:
                raise ValueError("ambiguous project association cannot claim a canonical project")
            if not self.candidate_project_ids:
                raise ValueError("ambiguous project association requires candidate project IDs")
        elif self.canonical_project_id is not None or self.candidate_project_ids:
            raise ValueError("unresolved project association cannot claim project identity")
        return self


class EmailActionProposal(BaseModel):
    """A non-executable description for later task or Calendar review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EmailProposalKind
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_evidence: tuple[DeterministicEmailEvidence, ...] = Field(min_length=1)

    @field_validator("title", "description")
    @classmethod
    def reject_blank_proposal_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("proposal fields cannot be blank")
        return value


class EmailOrganizationSuggestion(BaseModel):
    """Advisory organization only; this is not an approval or mutation payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition: EmailOrganizationDisposition
    proposed_labels: tuple[str, ...] = ()
    approval_required: Literal[True] = True

    @field_validator("proposed_labels")
    @classmethod
    def validate_proposed_labels(cls, labels: tuple[str, ...]) -> tuple[str, ...]:
        normalized = [label.strip().casefold() for label in labels]
        if any(not label for label in normalized):
            raise ValueError("proposed organization labels cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("proposed organization labels must be unique")
        forbidden = ("delete", "deleted", "trash", "trashed")
        if any(term in label for label in normalized for term in forbidden):
            raise ValueError("delete and trash cannot be proposed")
        return labels

    @model_validator(mode="after")
    def keep_uncertain_mail_untouched(self) -> "EmailOrganizationSuggestion":
        if (
            self.disposition == EmailOrganizationDisposition.REVIEW_UNCERTAIN
            and self.proposed_labels
        ):
            raise ValueError("uncertain mail cannot receive organization labels")
        return self


class EmailAttentionCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str = Field(min_length=1)
    message: EmailMessageIdentity
    received_at: datetime | None = None
    sent_at: datetime | None = None
    thread_state: EmailThreadState | None = None
    attention_kinds: tuple[EmailAttentionKind, ...] = Field(min_length=1)
    importance: EmailImportance | None = None
    urgency: EmailUrgency | None = None
    deadline: EmailDeadline | None = None
    requested_action: EmailRequestedAction | None = None
    project_association: EmailProjectAssociation
    action_proposals: tuple[EmailActionProposal, ...] = ()
    lifecycle: EmailCandidateLifecycle = EmailCandidateLifecycle.ACTIVE
    superseded_by_candidate_id: str | None = Field(default=None, min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    review_reasons: tuple[str, ...] = ()
    deterministic_evidence: tuple[DeterministicEmailEvidence, ...] = ()
    model_interpretation: EmailModelInterpretation | None = None
    organization_suggestion: EmailOrganizationSuggestion | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("candidate_id", "superseded_by_candidate_id")
    @classmethod
    def reject_blank_candidate_ids(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("candidate IDs cannot be blank")
        return value

    @field_validator("attention_kinds")
    @classmethod
    def validate_attention_kinds(
        cls, values: tuple[EmailAttentionKind, ...]
    ) -> tuple[EmailAttentionKind, ...]:
        if len(values) != len(set(values)):
            raise ValueError("attention kinds must be unique")
        if EmailAttentionKind.INFORMATIONAL in values and len(values) > 1:
            raise ValueError("informational cannot be combined with attention-requiring kinds")
        return values

    @field_validator("review_reasons")
    @classmethod
    def validate_review_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("review reasons cannot be blank")
        return values

    @model_validator(mode="after")
    def validate_candidate_contract(self) -> "EmailAttentionCandidate":
        if EmailAttentionKind.DEADLINE in self.attention_kinds and self.deadline is None:
            raise ValueError("deadline attention requires deadline evidence")
        if (
            EmailAttentionKind.EXPLICIT_ACTION_REQUEST in self.attention_kinds
            and self.requested_action is None
        ):
            raise ValueError("explicit action attention requires a requested action")

        if self.lifecycle == EmailCandidateLifecycle.SUPERSEDED:
            if self.superseded_by_candidate_id is None:
                raise ValueError("superseded candidate requires its replacement identity")
        elif self.superseded_by_candidate_id is not None:
            raise ValueError("only a superseded candidate can name a replacement")

        uncertainty_present = (
            self.confidence < 1.0
            or self.project_association.state
            != EmailProjectAssociationState.GROUNDED
            or (self.deadline is not None and self.deadline.state == EmailDeadlineState.AMBIGUOUS)
            or (
                self.organization_suggestion is not None
                and self.organization_suggestion.disposition
                == EmailOrganizationDisposition.REVIEW_UNCERTAIN
            )
        )
        if uncertainty_present and not self.review_reasons:
            raise ValueError("uncertain candidate requires explicit review reasons")
        return self
