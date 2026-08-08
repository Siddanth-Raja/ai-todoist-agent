from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .morning_corrections import morning_correction_service
from .reality_reconciliation import (
    RealityClassification,
    RealityItem,
    RealityProjection,
    reality_reconciliation_service,
)


PERSONAL_REALITY_SCHEMA_VERSION = 1


class PersonalRealityProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = PERSONAL_REALITY_SCHEMA_VERSION
    evaluated_at: datetime
    items: tuple[RealityItem, ...] = ()
    total_count: int = 0
    returned_count: int = 0
    item_limit: int = 0
    truncated: bool = False
    classification_counts: dict[str, int] = Field(default_factory=dict)
    complete_evidence: bool = False
    provider_diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> "PersonalRealityProjection":
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.returned_count != len(self.items):
            raise ValueError("returned_count must match returned items")
        if self.total_count < self.returned_count:
            raise ValueError("total_count cannot be smaller than returned_count")
        if self.truncated != (self.total_count > self.returned_count):
            raise ValueError("truncated must reflect the complete item count")
        return self

    def bounded(self, item_limit: int) -> "PersonalRealityProjection":
        bound = max(0, item_limit)
        returned = self.items[:bound]
        return self.model_copy(
            update={
                "items": returned,
                "returned_count": len(returned),
                "item_limit": bound,
                "truncated": self.total_count > len(returned),
            }
        )

    def item_for_work(self, provider: str, provider_record_id: str) -> RealityItem | None:
        return next(
            (
                item
                for item in self.items
                if item.normalized_work_identity is not None
                and item.normalized_work_identity.provider == provider
                and item.normalized_work_identity.provider_record_id == provider_record_id
            ),
            None,
        )


class PersonalRealityService:
    def apply_corrections(
        self,
        projection: RealityProjection,
        *,
        evaluated_at: datetime,
    ) -> RealityProjection:
        effective = morning_correction_service.apply_to_reality_items(
            projection.items,
            evaluated_at=evaluated_at,
            include_snoozed=True,
        )
        if effective == projection.items:
            return projection
        return reality_reconciliation_service.reproject_effective_items(
            projection,
            effective,
            item_limit=projection.item_limit,
        )

    def build(
        self,
        projects: Iterable[Any],
        *,
        evaluated_at: datetime,
        item_limit: int | None = None,
    ) -> PersonalRealityProjection:
        project_list = tuple(projects)
        items = tuple(
            item
            for project in project_list
            if getattr(project, "reality", None) is not None
            for item in project.reality.items
        )
        ordered = tuple(sorted(items, key=_item_order_key))
        total = len(ordered)
        bound = total if item_limit is None else max(0, item_limit)
        returned = ordered[:bound]
        counts = Counter(item.classification.value for item in ordered)
        projections = tuple(
            project.reality
            for project in project_list
            if getattr(project, "reality", None) is not None
        )
        diagnostics = tuple(
            dict.fromkeys(
                diagnostic
                for projection in projections
                for diagnostic in projection.provider_diagnostics
            )
        )
        return PersonalRealityProjection(
            evaluated_at=evaluated_at,
            items=returned,
            total_count=total,
            returned_count=len(returned),
            item_limit=bound,
            truncated=total > len(returned),
            classification_counts=dict(sorted(counts.items())),
            complete_evidence=bool(projections)
            and all(projection.complete_evidence for projection in projections),
            provider_diagnostics=diagnostics,
        )


def _item_order_key(item: RealityItem) -> tuple[Any, ...]:
    priority = {
        RealityClassification.NEEDS_ACTION: 0,
        RealityClassification.POTENTIAL_MISMATCH: 1,
        RealityClassification.WAITING: 2,
        RealityClassification.UNKNOWN: 3,
        RealityClassification.UPCOMING_NOT_ACTIONABLE: 4,
        RealityClassification.ALREADY_HANDLED: 5,
        RealityClassification.NO_MEANINGFUL_CHANGE: 6,
    }
    due = item.temporal.due_at.isoformat() if item.temporal.due_at else "9999"
    due_date = item.temporal.due_date.isoformat() if item.temporal.due_date else "9999"
    identity = item.normalized_work_identity
    return (
        priority[item.classification],
        due_date,
        due,
        item.canonical_project_id,
        identity.provider if identity else "",
        identity.provider_record_id if identity else "",
        item.reality_item_id,
    )


personal_reality_service = PersonalRealityService()
