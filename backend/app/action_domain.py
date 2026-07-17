"""Typed provider-neutral contracts for durable pending actions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


ACTION_SCHEMA_VERSION = 1


class PendingActionType(StrEnum):
    CREATE_TODOIST_TASK = "create_todoist_task"
    CREATE_TODOIST_SUBTASK = "create_todoist_subtask"
    CREATE_MANY_TODOIST_TASKS = "create_many_todoist_tasks"
    CREATE_MANY_TODOIST_SUBTASKS = "create_many_todoist_subtasks"
    CREATE_CALENDAR_EVENT = "create_calendar_event"
    UPDATE_CALENDAR_EVENT = "update_calendar_event"


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

    provider: Literal["todoist", "google_calendar"]
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


ActionPayload = Annotated[
    Union[
        CreateTodoistTaskPayload,
        CreateTodoistSubtaskPayload,
        CreateManyTodoistTasksPayload,
        CreateManyTodoistSubtasksPayload,
        CreateCalendarEventPayload,
        UpdateCalendarEventPayload,
    ],
    Field(discriminator="action_type"),
]
ACTION_PAYLOAD_ADAPTER = TypeAdapter(ActionPayload)


class StoredActionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["succeeded", "failed", "outcome_unknown"]
    provider_references: tuple[ProviderTargetReference, ...] = ()
    action_count: int = Field(default=0, ge=0)


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
    provider: Literal["todoist", "google_calendar"]
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


def payload_provider(payload: ActionPayload) -> Literal["todoist", "google_calendar"]:
    return (
        "google_calendar"
        if payload.action_type
        in {PendingActionType.CREATE_CALENDAR_EVENT, PendingActionType.UPDATE_CALENDAR_EVENT}
        else "todoist"
    )


def payload_target_references(payload: ActionPayload) -> tuple[ProviderTargetReference, ...]:
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
    else:
        common["details"] = {
            "event_id": payload.event_id,
            "title": payload.title,
            "old_start": payload.old_start.isoformat(),
            "old_end": payload.old_end.isoformat(),
            "new_start": payload.new_start.isoformat(),
            "new_end": payload.new_end.isoformat(),
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
