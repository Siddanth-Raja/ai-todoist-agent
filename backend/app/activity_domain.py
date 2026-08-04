from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ACTIVITY_EVENT_PAYLOAD_KEY = "activity_event"
ACTIVITY_EVENT_SCHEMA_VERSION = 1
MAX_ATTRIBUTABLE_PAYLOAD_BYTES = 20_000
SENSITIVE_ACTIVITY_KEYS = {
    "access_token",
    "authorization",
    "email_body",
    "password",
    "provider_token",
    "raw_payload",
    "refresh_token",
    "secret",
    "token",
}


class MeaningfulActivityCategory(StrEnum):
    APPROVED_ACTION = "approved_action"
    WORK_CREATED = "work_created"
    WORK_STARTED = "work_started"
    WORK_UPDATED = "work_updated"
    WORK_COMPLETED = "work_completed"
    MILESTONE_PROGRESS = "milestone_progress"
    MILESTONE_COMPLETED = "milestone_completed"
    BLOCKER_ADDED = "blocker_added"
    BLOCKER_CHANGED = "blocker_changed"
    BLOCKER_REMOVED = "blocker_removed"
    WAITING_EXTERNAL = "waiting_external"
    PROJECT_STATE_REVIEWED = "project_state_reviewed"
    FOCUS_DECISION_REVIEWED = "focus_decision_reviewed"
    PROJECT_PAUSED = "project_paused"
    PROJECT_RESUMED = "project_resumed"
    REPOSITORY_CATCH_UP = "repository_catch_up"
    COMMUNICATION_LINKED = "communication_linked"
    COMMUNICATION_OUTCOME = "communication_outcome"
    MEMORY_CONTEXT_REVIEWED = "memory_context_reviewed"


class ActivityFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class MeaningfulActivityEvent(BaseModel):
    """Versioned, attributable evidence stored inside the legacy Activity payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = ACTIVITY_EVENT_SCHEMA_VERSION
    category: MeaningfulActivityCategory
    canonical_project_id: str | None = Field(default=None, min_length=1)
    source_provider: str = Field(..., min_length=1, max_length=80)
    provider_record_type: str | None = Field(default=None, min_length=1, max_length=80)
    provider_record_id: str | None = Field(default=None, min_length=1, max_length=240)
    source_timestamp: datetime
    observed_at: datetime
    freshness: ActivityFreshness = ActivityFreshness.FRESH
    evidence_key: str = Field(..., min_length=1, max_length=500)
    summary: str = Field(..., min_length=1, max_length=500)
    attributable_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_attribution(self) -> "MeaningfulActivityEvent":
        if self.source_timestamp.tzinfo is None or self.source_timestamp.utcoffset() is None:
            raise ValueError("source_timestamp must be timezone-aware")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if bool(self.provider_record_type) != bool(self.provider_record_id):
            raise ValueError(
                "provider_record_type and provider_record_id must be supplied together"
            )
        _validate_attributable_payload(self.attributable_payload)
        return self


def activity_event_payload(event: MeaningfulActivityEvent) -> dict[str, Any]:
    return {ACTIVITY_EVENT_PAYLOAD_KEY: event.model_dump(mode="json")}


def activity_event_from_record(record: dict[str, Any]) -> MeaningfulActivityEvent | None:
    payload = record.get("payload") or record.get("metadata")
    if not isinstance(payload, dict):
        return None
    raw_event = payload.get(ACTIVITY_EVENT_PAYLOAD_KEY)
    if not isinstance(raw_event, dict):
        return None
    try:
        return MeaningfulActivityEvent.model_validate(raw_event)
    except (TypeError, ValueError):
        # Legacy and malformed historical rows remain readable as unstructured Activity.
        return None


def activity_contract_projection(record: dict[str, Any]) -> dict[str, Any]:
    event = activity_event_from_record(record)
    projected = dict(record)
    projected["meaningful_event"] = (
        event.model_dump(mode="json") if event is not None else None
    )
    projected["activity_schema_version"] = (
        event.schema_version if event is not None else None
    )
    projected["legacy_unstructured"] = event is None
    return projected


def _validate_attributable_payload(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) > MAX_ATTRIBUTABLE_PAYLOAD_BYTES:
        raise ValueError("attributable_payload exceeds the bounded Activity limit")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for raw_key, nested in value.items():
                key = str(raw_key).strip().lower()
                if key in SENSITIVE_ACTIVITY_KEYS:
                    raise ValueError(
                        f"attributable_payload cannot store sensitive field {key}"
                    )
                walk(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                walk(nested)

    walk(payload)
