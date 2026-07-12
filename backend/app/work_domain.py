from datetime import date, datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELED = "canceled"


class WorkPriority(IntEnum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class WorkEnergy(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WorkDependency(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_record_id: str
    dependency_type: str


class NormalizedWorkItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_record_id: str
    canonical_project_id: str | None = None
    title: str
    description: str = ""
    status: WorkStatus
    original_provider_status: str | None = None
    priority: WorkPriority = WorkPriority.NONE
    original_provider_priority: int | str | None = None
    due_date: date | None = None
    due_at: datetime | None = None
    parent_provider_record_id: str | None = None
    is_container: bool = False
    is_executable: bool = True
    explicitly_completable: bool = False
    is_blocked: bool = False
    dependencies: tuple[WorkDependency, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None
    provider_url: str | None = None
    provider_reference: str | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=1)
    energy_requirement: WorkEnergy | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_execution_state(self) -> "NormalizedWorkItem":
        if self.status != WorkStatus.OPEN and self.is_executable:
            raise ValueError("completed or canceled work cannot be executable")
        if self.is_container and self.is_executable:
            raise ValueError("container work cannot be executable")
        return self

    def get(self, key: str, default: Any = None) -> Any:
        compatibility_fields = {
            "id": self.provider_record_id,
            "content": self.title,
            "description": self.description,
            "parent_id": self.parent_provider_record_id,
            "completed": self.status == WorkStatus.COMPLETED,
            "is_completed": self.status == WorkStatus.COMPLETED,
            "checked": self.status == WorkStatus.COMPLETED,
            "url": self.provider_url,
            "created_at": self.provider_metadata.get("created_at"),
            "updated_at": self.provider_metadata.get("updated_at"),
            "todoist_priority": self.original_provider_priority,
        }
        if key in compatibility_fields:
            value = compatibility_fields[key]
            return default if value is None else value
        return self.provider_metadata.get(key, default)

    def to_legacy_task(self) -> dict[str, Any]:
        task = dict(self.provider_metadata)
        task.update(
            {
                "id": self.provider_record_id,
                "content": self.title,
                "description": self.description,
                "parent_id": self.parent_provider_record_id,
                "completed": self.status == WorkStatus.COMPLETED,
                "todoist_priority": self.original_provider_priority,
                "url": self.provider_url,
            }
        )
        return task
