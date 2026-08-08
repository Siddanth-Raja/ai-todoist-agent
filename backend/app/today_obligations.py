from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from .reality_reconciliation import RealityClassification, RealityItem
from .work_domain import NormalizedWorkItem, WorkProviderReadState, WorkStatus


class TodayObligationUrgency(StrEnum):
    OVERDUE = "overdue"
    DUE_TODAY = "due_today"


class TodayObligationState(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class TodayObligation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_record_id: str
    canonical_project_id: str | None = None
    title: str
    due_date: date
    due_at: datetime | None = None
    urgency: TodayObligationUrgency
    days_overdue: int
    priority: int
    provider_url: str | None = None
    reality: RealityItem | None = None


class TodayObligationProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: TodayObligationState
    items: tuple[TodayObligation, ...]
    errors: tuple[str, ...]
    providers: tuple[WorkProviderReadState, ...]


class TodayObligationService:
    def build(
        self,
        work_items: tuple[NormalizedWorkItem, ...] | list[NormalizedWorkItem],
        *,
        current_time: datetime,
        provider_states: tuple[WorkProviderReadState, ...] = (),
        reality_items: tuple[RealityItem, ...] = (),
    ) -> TodayObligationProjection:
        today = current_time.date()
        reality_by_identity = {
            (
                item.normalized_work_identity.provider,
                item.normalized_work_identity.provider_record_id,
            ): item
            for item in reality_items
            if item.normalized_work_identity is not None
        }
        by_identity: dict[tuple[str, str], TodayObligation] = {}
        for item in work_items:
            if not _eligible(item):
                continue
            local_due_date = _local_due_date(item, current_time)
            if local_due_date is None or local_due_date > today:
                continue
            identity = (item.provider, item.provider_record_id)
            reality = reality_by_identity.get(identity)
            if (
                reality is not None
                and reality.classification != RealityClassification.NEEDS_ACTION
            ):
                continue
            by_identity[identity] = TodayObligation(
                provider=item.provider,
                provider_record_id=item.provider_record_id,
                canonical_project_id=item.canonical_project_id,
                title=item.title,
                due_date=local_due_date,
                due_at=item.due_at,
                urgency=(
                    TodayObligationUrgency.OVERDUE
                    if local_due_date < today
                    else TodayObligationUrgency.DUE_TODAY
                ),
                days_overdue=max(0, (today - local_due_date).days),
                priority=int(item.priority),
                provider_url=item.provider_url,
                reality=reality,
            )

        failures = tuple(state for state in provider_states if not state.available)
        available = tuple(state for state in provider_states if state.available)
        if failures and available:
            state = TodayObligationState.DEGRADED
        elif failures:
            state = TodayObligationState.UNAVAILABLE
        else:
            state = TodayObligationState.AVAILABLE
        errors = tuple(
            dict.fromkeys(
                provider.error
                for provider in failures
                if provider.error
            )
        )
        items = tuple(sorted(by_identity.values(), key=_obligation_sort_key))
        return TodayObligationProjection(
            state=state,
            items=items,
            errors=errors,
            providers=provider_states,
        )


def _eligible(item: NormalizedWorkItem) -> bool:
    return (
        item.status == WorkStatus.OPEN
        and item.is_executable
        and not item.is_container
        and not item.is_blocked
    )


def _local_due_date(
    item: NormalizedWorkItem,
    current_time: datetime,
) -> date | None:
    if item.due_at is None:
        return item.due_date
    due_at = item.due_at
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=current_time.tzinfo)
    if current_time.tzinfo is not None:
        due_at = due_at.astimezone(current_time.tzinfo)
    return due_at.date()


def _obligation_sort_key(item: TodayObligation) -> tuple[object, ...]:
    return (
        0 if item.urgency == TodayObligationUrgency.OVERDUE else 1,
        item.due_date,
        item.due_at.isoformat() if item.due_at else "9999",
        -item.priority,
        item.provider,
        item.provider_record_id,
        item.title.casefold(),
    )


today_obligation_service = TodayObligationService()
