"""Typed provider-neutral contracts for durable pending actions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from .email_domain import EmailAccountRole, EmailProviderAccountIdentity


ACTION_SCHEMA_VERSION = 1


class PendingActionType(StrEnum):
    CREATE_TODOIST_TASK = "create_todoist_task"
    CREATE_TODOIST_SUBTASK = "create_todoist_subtask"
    CREATE_MANY_TODOIST_TASKS = "create_many_todoist_tasks"
    CREATE_MANY_TODOIST_SUBTASKS = "create_many_todoist_subtasks"
    CREATE_CALENDAR_EVENT = "create_calendar_event"
    UPDATE_CALENDAR_EVENT = "update_calendar_event"
    GMAIL_APPLY_LABEL = "gmail_apply_label"
    GMAIL_REMOVE_LABEL = "gmail_remove_label"
    GMAIL_ARCHIVE = "gmail_archive"
    GMAIL_RESTORE_INBOX = "gmail_restore_inbox"
    GMAIL_MARK_READ = "gmail_mark_read"
    GMAIL_MARK_UNREAD = "gmail_mark_unread"
    GMAIL_CREATE_LABEL = "gmail_create_label"


class PendingActionLifecycle(StrEnum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    OUTCOME_UNKNOWN = "outcome_unknown"


TERMINAL_ACTION_STATES = {
    PendingActionLifecycle.SUCCEEDED,
    PendingActionLifecycle.FAILED,
    PendingActionLifecycle.CANCELLED,
    PendingActionLifecycle.EXPIRED,
    PendingActionLifecycle.OUTCOME_UNKNOWN,
}


class ProviderTargetReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["todoist", "google_calendar", "gmail"]
    resource_type: str = Field(min_length=1, max_length=80)
    provider_ref: str = Field(min_length=1, max_length=500)


class ActionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=1000)
    source_ref: str | None = Field(default=None, min_length=1, max_length=500)


class TodoistTaskSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(min_length=1, max_length=500)
    project_id: str | None = Field(default=None, min_length=1, max_length=500)
    project_name: str | None = Field(default=None, min_length=1, max_length=200)
    section_id: str | None = Field(default=None, min_length=1, max_length=500)
    section_name: str | None = Field(default=None, min_length=1, max_length=200)
    due_string: str | None = Field(default=None, min_length=1, max_length=200)
    labels: tuple[str, ...] = ()
    priority: int | None = Field(default=None, ge=1, le=4)
    project_category: str | None = Field(default=None, min_length=1, max_length=100)
    classification_source: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("task content cannot be blank")
        return value

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("task labels cannot be blank")
        return values


class CreateTodoistTaskPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.CREATE_TODOIST_TASK]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    task: TodoistTaskSpec


class CreateTodoistSubtaskPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.CREATE_TODOIST_SUBTASK]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    parent_task_id: str = Field(min_length=1, max_length=500)
    parent_task_title: str | None = Field(default=None, min_length=1, max_length=500)
    task: TodoistTaskSpec


class CreateManyTodoistTasksPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.CREATE_MANY_TODOIST_TASKS]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    tasks: tuple[TodoistTaskSpec, ...] = Field(min_length=1, max_length=100)


class CreateManyTodoistSubtasksPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.CREATE_MANY_TODOIST_SUBTASKS]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    parent_task_id: str = Field(min_length=1, max_length=500)
    parent_task_title: str | None = Field(default=None, min_length=1, max_length=500)
    project_name: str | None = Field(default=None, min_length=1, max_length=200)
    section_name: str | None = Field(default=None, min_length=1, max_length=200)
    tasks: tuple[TodoistTaskSpec, ...] = Field(min_length=1, max_length=100)


class CreateCalendarEventPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.CREATE_CALENDAR_EVENT]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    title: str = Field(min_length=1, max_length=500)
    start: datetime
    end: datetime
    description: str | None = Field(default=None, max_length=5000)
    allow_conflicts: bool = False
    project_category: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_time_range(self) -> "CreateCalendarEventPayload":
        _require_timezone(self.start, "calendar start")
        _require_timezone(self.end, "calendar end")
        if self.end <= self.start:
            raise ValueError("calendar event end must be after start")
        return self


class UpdateCalendarEventPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.UPDATE_CALENDAR_EVENT]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    old_start: datetime
    old_end: datetime
    new_start: datetime
    new_end: datetime

    @model_validator(mode="after")
    def validate_time_ranges(self) -> "UpdateCalendarEventPayload":
        for name, value in (
            ("old_start", self.old_start),
            ("old_end", self.old_end),
            ("new_start", self.new_start),
            ("new_end", self.new_end),
        ):
            _require_timezone(value, name)
        if self.old_end <= self.old_start or self.new_end <= self.new_start:
            raise ValueError("calendar update ranges must have positive duration")
        return self


GMAIL_ORGANIZATION_LABELS = (
    "PCOS/Action",
    "PCOS/Waiting",
    "PCOS/Keep",
    "PCOS/Review",
    "Finance",
    "School",
    "Freelance",
    "Travel",
)


class GmailExpectedMessageState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_message_id: str = Field(min_length=1, max_length=500)
    provider_thread_id: str | None = Field(default=None, min_length=1, max_length=500)
    expected_label_ids: tuple[str, ...]
    expected_unread: bool
    protected: Literal[False] = False
    uncertain: Literal[False] = False
    review: "GmailMessageReviewMetadata"

    @field_validator("expected_label_ids")
    @classmethod
    def validate_label_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("expected Gmail label identities cannot be blank")
        if len(values) != len(set(values)):
            raise ValueError("expected Gmail label identities must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def bind_review_labels_to_expected_state(self) -> "GmailExpectedMessageState":
        review_label_ids = tuple(
            sorted(item.provider_label_id for item in self.review.current_labels)
        )
        if review_label_ids != self.expected_label_ids:
            raise ValueError(
                "review label identities must exactly match expected Gmail state"
            )
        return self


class GmailReviewLabelIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_label_id: str = Field(min_length=1, max_length=500)
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("provider_label_id", "display_name")
    @classmethod
    def validate_safe_label_text(cls, value: str) -> str:
        if value != " ".join(value.split()):
            raise ValueError("Gmail review label text must be normalized")
        return value


class GmailMessageReviewMetadata(BaseModel):
    """Local, approval-only metadata; raw addresses and bodies are forbidden."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sender_display: str = Field(min_length=1, max_length=200)
    sender_domain: str = Field(min_length=1, max_length=253)
    subject: str = Field(min_length=1, max_length=500)
    received_at: datetime
    current_labels: tuple[GmailReviewLabelIdentity, ...] = Field(min_length=1)
    selection_reason: str = Field(min_length=1, max_length=500)

    @field_validator("sender_display", "subject", "selection_reason")
    @classmethod
    def validate_safe_review_text(cls, value: str) -> str:
        if value != " ".join(value.split()):
            raise ValueError("Gmail review text must be normalized")
        return value

    @field_validator("sender_display")
    @classmethod
    def forbid_sender_address(cls, value: str) -> str:
        if "@" in value or "<" in value or ">" in value:
            raise ValueError("Gmail review sender must not expose a raw address")
        return value

    @field_validator("sender_domain")
    @classmethod
    def validate_sender_domain(cls, value: str) -> str:
        if value != value.strip().casefold() or "@" in value or any(
            character.isspace() for character in value
        ):
            raise ValueError("Gmail review sender domain must be normalized")
        return value

    @field_validator("current_labels")
    @classmethod
    def validate_current_labels(
        cls, values: tuple[GmailReviewLabelIdentity, ...]
    ) -> tuple[GmailReviewLabelIdentity, ...]:
        label_ids = [item.provider_label_id for item in values]
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("Gmail review labels must have unique identities")
        return tuple(sorted(values, key=lambda item: item.provider_label_id))

    @model_validator(mode="after")
    def require_timezone(self) -> "GmailMessageReviewMetadata":
        _require_timezone(self.received_at, "Gmail review received_at")
        return self


GmailExpectedMessageState.model_rebuild()


class GmailOrganizationManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account: EmailProviderAccountIdentity
    targets: tuple[GmailExpectedMessageState, ...] = Field(min_length=1, max_length=1000)
    selection_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    originating_proposal_id: str = Field(min_length=1, max_length=200)
    originating_proposal_fingerprint: str = Field(min_length=1, max_length=200)
    originating_inventory_fingerprint: str = Field(min_length=1, max_length=200)
    selection_criteria: tuple[str, ...] = Field(min_length=1, max_length=20)
    exclusions: tuple[str, ...] = Field(max_length=50)
    representative_example_tokens: tuple[str, ...] = Field(max_length=5)
    uncertainty_count: Literal[0] = 0

    @field_validator(
        "selection_criteria", "exclusions", "representative_example_tokens"
    )
    @classmethod
    def validate_text_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Gmail action evidence cannot contain blank values")
        return values

    @model_validator(mode="after")
    def validate_exact_manifest(self) -> "GmailOrganizationManifest":
        if (
            self.account.provider != "gmail"
            or self.account.account_role != EmailAccountRole.PERSONAL
        ):
            raise ValueError("Gmail organization is limited to the Personal account")
        message_ids = [item.provider_message_id for item in self.targets]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("Gmail action manifest cannot duplicate messages")
        expected = gmail_manifest_fingerprint(self.account, self.targets)
        if expected != self.selection_fingerprint:
            raise ValueError("Gmail action manifest fingerprint is invalid")
        return self


class GmailUserLabelIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_label_id: str = Field(min_length=1, max_length=500)
    name: Literal[
        "PCOS/Action",
        "PCOS/Waiting",
        "PCOS/Keep",
        "PCOS/Review",
        "Finance",
        "School",
        "Freelance",
        "Travel",
    ]
    label_type: Literal["user"] = "user"

    @field_validator("provider_label_id")
    @classmethod
    def forbid_system_label_identity(cls, value: str) -> str:
        if not value.startswith("Label_"):
            raise ValueError("label actions require an exact user-label identity")
        return value


class GmailApplyLabelPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.GMAIL_APPLY_LABEL]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    manifest: GmailOrganizationManifest
    label: GmailUserLabelIdentity
    canary: bool = False
    hand_reviewed: bool = False
    undo_action_type: Literal[PendingActionType.GMAIL_REMOVE_LABEL] = (
        PendingActionType.GMAIL_REMOVE_LABEL
    )
    undo_of_action_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_canary(self) -> "GmailApplyLabelPayload":
        if self.canary and (not self.hand_reviewed or len(self.manifest.targets) > 10):
            raise ValueError("Gmail label canary requires 1-10 hand-reviewed messages")
        return self


class GmailRemoveLabelPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.GMAIL_REMOVE_LABEL]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    manifest: GmailOrganizationManifest
    label: GmailUserLabelIdentity
    canary_undo: bool = False
    hand_reviewed: bool = False
    undo_action_type: Literal[PendingActionType.GMAIL_APPLY_LABEL] = (
        PendingActionType.GMAIL_APPLY_LABEL
    )
    undo_of_action_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_canary_undo(self) -> "GmailRemoveLabelPayload":
        if self.canary_undo and (
            not self.hand_reviewed
            or self.undo_of_action_id is None
            or len(self.manifest.targets) > 10
        ):
            raise ValueError("Gmail canary undo must match a hand-reviewed canary")
        return self


class GmailArchivePayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.GMAIL_ARCHIVE]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    manifest: GmailOrganizationManifest
    undo_action_type: Literal[PendingActionType.GMAIL_RESTORE_INBOX] = (
        PendingActionType.GMAIL_RESTORE_INBOX
    )
    undo_of_action_id: str | None = Field(default=None, min_length=1, max_length=128)


class GmailRestoreInboxPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.GMAIL_RESTORE_INBOX]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    manifest: GmailOrganizationManifest
    undo_action_type: Literal[PendingActionType.GMAIL_ARCHIVE] = (
        PendingActionType.GMAIL_ARCHIVE
    )
    undo_of_action_id: str = Field(min_length=1, max_length=128)


class GmailMarkReadPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.GMAIL_MARK_READ]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    manifest: GmailOrganizationManifest
    undo_action_type: Literal[PendingActionType.GMAIL_MARK_UNREAD] = (
        PendingActionType.GMAIL_MARK_UNREAD
    )
    undo_of_action_id: str | None = Field(default=None, min_length=1, max_length=128)


class GmailMarkUnreadPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.GMAIL_MARK_UNREAD]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    manifest: GmailOrganizationManifest
    undo_action_type: Literal[PendingActionType.GMAIL_MARK_READ] = (
        PendingActionType.GMAIL_MARK_READ
    )
    undo_of_action_id: str = Field(min_length=1, max_length=128)


class GmailCreateLabelPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_type: Literal[PendingActionType.GMAIL_CREATE_LABEL]
    schema_version: Literal[ACTION_SCHEMA_VERSION] = ACTION_SCHEMA_VERSION
    account: EmailProviderAccountIdentity
    label_name: Literal[
        "PCOS/Action",
        "PCOS/Waiting",
        "PCOS/Keep",
        "PCOS/Review",
        "Finance",
        "School",
        "Freelance",
        "Travel",
    ]
    originating_proposal_id: str = Field(min_length=1, max_length=200)
    undo_action_type: Literal[None] = None
    undo_unavailable_reason: Literal[
        "label removal capability is intentionally absent"
    ] = "label removal capability is intentionally absent"

    @model_validator(mode="after")
    def validate_personal_account(self) -> "GmailCreateLabelPayload":
        if (
            self.account.provider != "gmail"
            or self.account.account_role != EmailAccountRole.PERSONAL
        ):
            raise ValueError("Gmail label creation is limited to the Personal account")
        return self


ActionPayload = Annotated[
    Union[
        CreateTodoistTaskPayload,
        CreateTodoistSubtaskPayload,
        CreateManyTodoistTasksPayload,
        CreateManyTodoistSubtasksPayload,
        CreateCalendarEventPayload,
        UpdateCalendarEventPayload,
        GmailApplyLabelPayload,
        GmailRemoveLabelPayload,
        GmailArchivePayload,
        GmailRestoreInboxPayload,
        GmailMarkReadPayload,
        GmailMarkUnreadPayload,
        GmailCreateLabelPayload,
    ],
    Field(discriminator="action_type"),
]
ACTION_PAYLOAD_ADAPTER = TypeAdapter(ActionPayload)


class StoredTargetResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_token: str = Field(min_length=1, max_length=128)
    status: Literal["succeeded", "failed", "outcome_unknown"]
    diagnostic_code: str | None = Field(default=None, min_length=1, max_length=100)


class StoredActionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["succeeded", "failed", "outcome_unknown"]
    provider_references: tuple[ProviderTargetReference, ...] = ()
    target_results: tuple[StoredTargetResult, ...] = ()
    action_count: int = Field(default=0, ge=0)
    undo_action_id: str | None = Field(default=None, min_length=1, max_length=128)


class StoredActionFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)


class PendingActionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str = Field(min_length=1)
    action_type: PendingActionType
    schema_version: Literal[ACTION_SCHEMA_VERSION]
    payload: ActionPayload
    canonical_project_id: str | None = None
    provider: Literal["todoist", "google_calendar", "gmail"]
    target_references: tuple[ProviderTargetReference, ...]
    confirmation_prompt: str = Field(min_length=1, max_length=2000)
    evidence: tuple[ActionEvidence, ...]
    payload_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    session_id: str | None = Field(default=None, max_length=500)
    source: str = Field(min_length=1, max_length=80)
    source_ref: str | None = Field(default=None, max_length=500)
    lifecycle: PendingActionLifecycle
    version: int = Field(ge=1)
    proposed_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None = None
    execution_started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    result: StoredActionResult | None = None
    failure: StoredActionFailure | None = None

    @model_validator(mode="after")
    def preserve_payload_identity(self) -> "PendingActionRecord":
        if self.payload.action_type != self.action_type:
            raise ValueError("stored action type must match typed payload")
        if self.payload.schema_version != self.schema_version:
            raise ValueError("stored schema version must match typed payload")
        if payload_fingerprint(self.payload) != self.payload_fingerprint:
            raise ValueError("stored payload fingerprint is invalid")
        return self


def parse_legacy_pending_action(value: dict[str, Any]) -> ActionPayload:
    action_type = value.get("action_type") or value.get("type")
    try:
        action = PendingActionType(str(action_type))
    except ValueError as exc:
        raise ValueError("Unknown or unsupported pending action type.") from exc

    details = value.get("details") if isinstance(value.get("details"), dict) else {}
    if action == PendingActionType.CREATE_TODOIST_TASK:
        task = value.get("task") if isinstance(value.get("task"), dict) else details
        raw = {
            "action_type": action.value,
            "task": _task_spec(task, fallback_category=value.get("resolved_project")),
        }
    elif action == PendingActionType.CREATE_TODOIST_SUBTASK:
        raw = {
            "action_type": action.value,
            "parent_task_id": details.get("parent_task_id"),
            "parent_task_title": details.get("parent_task_title"),
            "task": _task_spec(details, fallback_category=value.get("resolved_project")),
        }
    elif action == PendingActionType.CREATE_MANY_TODOIST_TASKS:
        raw = {
            "action_type": action.value,
            "tasks": tuple(
                _task_spec(item, fallback_category=value.get("resolved_project"))
                for item in details.get("tasks", [])
                if isinstance(item, dict)
            ),
        }
    elif action == PendingActionType.CREATE_MANY_TODOIST_SUBTASKS:
        raw = {
            "action_type": action.value,
            "parent_task_id": details.get("parent_task_id"),
            "parent_task_title": details.get("parent_task_title"),
            "project_name": details.get("project_name"),
            "section_name": details.get("section_name"),
            "tasks": tuple(
                _task_spec(item, fallback_category=value.get("resolved_project"))
                for item in details.get("tasks", [])
                if isinstance(item, dict)
            ),
        }
    elif action == PendingActionType.CREATE_CALENDAR_EVENT:
        event = value.get("calendar_event") if isinstance(value.get("calendar_event"), dict) else {}
        raw = {
            "action_type": action.value,
            "title": event.get("title"),
            "start": event.get("start"),
            "end": event.get("end"),
            "description": event.get("description"),
            "allow_conflicts": bool(value.get("allow_conflicts", True)),
            "project_category": value.get("resolved_project") or event.get("resolved_project"),
        }
    else:
        raw = {
            "action_type": action.value,
            "event_id": details.get("event_id"),
            "title": details.get("title"),
            "old_start": details.get("old_start"),
            "old_end": details.get("old_end"),
            "new_start": details.get("new_start"),
            "new_end": details.get("new_end"),
        }
    return ACTION_PAYLOAD_ADAPTER.validate_python(raw)


def payload_fingerprint(payload: ActionPayload) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def gmail_manifest_fingerprint(
    account: EmailProviderAccountIdentity,
    targets: tuple[GmailExpectedMessageState, ...],
) -> str:
    canonical = json.dumps(
        {
            "account": account.model_dump(mode="json"),
            "targets": [
                item.model_dump(mode="json")
                for item in sorted(targets, key=lambda value: value.provider_message_id)
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def payload_provider(
    payload: ActionPayload,
) -> Literal["todoist", "google_calendar", "gmail"]:
    if payload.action_type in {
        PendingActionType.CREATE_CALENDAR_EVENT,
        PendingActionType.UPDATE_CALENDAR_EVENT,
    }:
        return "google_calendar"
    if payload.action_type.value.startswith("gmail_"):
        return "gmail"
    return "todoist"


def payload_target_references(payload: ActionPayload) -> tuple[ProviderTargetReference, ...]:
    if isinstance(
        payload,
        (
            GmailApplyLabelPayload,
            GmailRemoveLabelPayload,
            GmailArchivePayload,
            GmailRestoreInboxPayload,
            GmailMarkReadPayload,
            GmailMarkUnreadPayload,
        ),
    ):
        return tuple(
            ProviderTargetReference(
                provider="gmail",
                resource_type="message",
                provider_ref=item.provider_message_id,
            )
            for item in payload.manifest.targets
        )
    if isinstance(payload, GmailCreateLabelPayload):
        return (
            ProviderTargetReference(
                provider="gmail",
                resource_type="label_collection",
                provider_ref=payload.account.provider_account_id,
            ),
        )
    if isinstance(payload, (CreateTodoistSubtaskPayload, CreateManyTodoistSubtasksPayload)):
        return (
            ProviderTargetReference(
                provider="todoist",
                resource_type="parent_task",
                provider_ref=payload.parent_task_id,
            ),
        )
    if isinstance(payload, UpdateCalendarEventPayload):
        return (
            ProviderTargetReference(
                provider="google_calendar",
                resource_type="event",
                provider_ref=payload.event_id,
            ),
        )
    if isinstance(payload, CreateTodoistTaskPayload):
        task = payload.task
        reference = task.section_id or task.section_name or task.project_id or task.project_name or "todoist-inbox"
        return (
            ProviderTargetReference(
                provider="todoist",
                resource_type="task_collection",
                provider_ref=reference,
            ),
        )
    if isinstance(payload, CreateManyTodoistTasksPayload):
        return (
            ProviderTargetReference(
                provider="todoist",
                resource_type="task_collection",
                provider_ref="validated-task-batch",
            ),
        )
    return (
        ProviderTargetReference(
            provider="google_calendar",
            resource_type="calendar",
            provider_ref="configured-primary-calendar",
        ),
    )


def legacy_client_payload(record: PendingActionRecord) -> dict[str, Any]:
    payload = record.payload
    common: dict[str, Any] = {
        "action_id": record.action_id,
        "version": record.version,
        "fingerprint": record.payload_fingerprint,
        "schema_version": record.schema_version,
        "type": record.action_type.value,
        "action_type": record.action_type.value,
        "confirmation_prompt": record.confirmation_prompt,
        "canonical_project_id": record.canonical_project_id,
        "provider": record.provider,
        "lifecycle": record.lifecycle.value,
    }
    if isinstance(payload, CreateTodoistTaskPayload):
        common["task"] = payload.task.model_dump(mode="json")
        common["details"] = {}
    elif isinstance(payload, CreateTodoistSubtaskPayload):
        common["details"] = {
            "parent_task_id": payload.parent_task_id,
            "parent_task_title": payload.parent_task_title,
            **payload.task.model_dump(mode="json"),
        }
    elif isinstance(payload, CreateManyTodoistTasksPayload):
        common["details"] = {
            "tasks": [item.model_dump(mode="json") for item in payload.tasks]
        }
    elif isinstance(payload, CreateManyTodoistSubtasksPayload):
        common["details"] = {
            "parent_task_id": payload.parent_task_id,
            "parent_task_title": payload.parent_task_title,
            "project_name": payload.project_name,
            "section_name": payload.section_name,
            "tasks": [item.model_dump(mode="json") for item in payload.tasks],
        }
    elif isinstance(payload, CreateCalendarEventPayload):
        common["calendar_event"] = {
            "title": payload.title,
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "description": payload.description,
        }
        common["details"] = {}
    elif isinstance(payload, UpdateCalendarEventPayload):
        common["details"] = {
            "event_id": payload.event_id,
            "title": payload.title,
            "old_start": payload.old_start.isoformat(),
            "old_end": payload.old_end.isoformat(),
            "new_start": payload.new_start.isoformat(),
            "new_end": payload.new_end.isoformat(),
        }
    elif isinstance(payload, GmailCreateLabelPayload):
        common["details"] = {
            "account_role": payload.account.account_role.value,
            "label_name": payload.label_name,
            "originating_proposal_id": payload.originating_proposal_id,
            "undo_action_type": payload.undo_action_type,
            "undo_unavailable_reason": payload.undo_unavailable_reason,
        }
    else:
        common["details"] = {
            "account_role": payload.manifest.account.account_role.value,
            "message_count": len(payload.manifest.targets),
            "selection_fingerprint": payload.manifest.selection_fingerprint,
            "originating_proposal_id": payload.manifest.originating_proposal_id,
            "originating_inventory_fingerprint": (
                payload.manifest.originating_inventory_fingerprint
            ),
            "selection_criteria": list(payload.manifest.selection_criteria),
            "exclusions": list(payload.manifest.exclusions),
            "uncertainty_count": payload.manifest.uncertainty_count,
            "representative_example_tokens": list(
                payload.manifest.representative_example_tokens
            ),
            "label_name": getattr(getattr(payload, "label", None), "name", None),
            "canary": bool(getattr(payload, "canary", False)),
            "canary_undo": bool(getattr(payload, "canary_undo", False)),
            "hand_reviewed": bool(getattr(payload, "hand_reviewed", False)),
            "undo_of_action_id": getattr(payload, "undo_of_action_id", None),
            "undo_action_type": payload.undo_action_type.value,
            "targets": [
                {
                    "message_token": hashlib.sha256(
                        item.provider_message_id.encode("utf-8")
                    ).hexdigest()[:16],
                    "thread_token": (
                        hashlib.sha256(item.provider_thread_id.encode("utf-8")).hexdigest()[:16]
                        if item.provider_thread_id
                        else None
                    ),
                    "expected_unread": item.expected_unread,
                    "expected_label_count": len(item.expected_label_ids),
                    "sender_display": item.review.sender_display,
                    "sender_domain": item.review.sender_domain,
                    "subject": item.review.subject,
                    "received_at": item.review.received_at.isoformat(),
                    "current_labels": [
                        {
                            "label_token": hashlib.sha256(
                                label.provider_label_id.encode("utf-8")
                            ).hexdigest()[:16],
                            "name": label.display_name,
                        }
                        for label in item.review.current_labels
                    ],
                    "selection_reason": item.review.selection_reason,
                }
                for item in payload.manifest.targets
            ],
        }
    return common


def _task_spec(value: dict[str, Any], *, fallback_category: Any = None) -> dict[str, Any]:
    return {
        "content": str(value.get("content") or "").strip(),
        "project_id": _optional_string(value.get("project_id")),
        "project_name": _optional_string(value.get("project_name")),
        "section_id": _optional_string(
            value.get("section_id") or value.get("todoist_section_id")
        ),
        "section_name": _optional_string(
            value.get("section_name") or value.get("todoist_section_name")
        ),
        "due_string": _optional_string(value.get("due_string") or value.get("due_date")),
        "labels": tuple(value.get("labels") or ()),
        "priority": value.get("priority"),
        "project_category": _optional_string(
            value.get("project_category") or value.get("resolved_project") or fallback_category
        ),
        "classification_source": _optional_string(value.get("classification_source")),
    }


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _require_timezone(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
