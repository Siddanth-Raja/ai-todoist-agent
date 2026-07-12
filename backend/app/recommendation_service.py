from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .work_domain import NormalizedWorkItem, WorkEnergy, WorkStatus


class RecommendationPurpose(StrEnum):
    PROJECT_NEXT_MOVE = "project_next_move"
    CURRENT_ACTION = "current_action"


class RecommendationAction(StrEnum):
    DO_WORK = "do_work"
    RESOLVE_BLOCKER = "resolve_blocker"


class RecommendationSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: str
    value: Any
    score_delta: float
    explanation: str


class RecommendationWorkIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    provider_record_id: str
    title: str


class RecommendationAlternative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    work: RecommendationWorkIdentity
    score: float
    action: RecommendationAction


class RecommendationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_time: datetime | None = None
    usable_free_block_minutes: int | None = Field(default=None, ge=1)
    energy: WorkEnergy | None = None
    upcoming_commitment_title: str | None = None
    minutes_until_upcoming_commitment: int | None = Field(default=None, ge=0)
    project_momentum_provider_record_ids: tuple[str, ...] = ()


class WorkRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    purpose: RecommendationPurpose
    action: RecommendationAction
    selected_work: RecommendationWorkIdentity
    canonical_project_id: str | None = None
    score: float
    explanation: str
    evidence: tuple[RecommendationSignal, ...]
    considered_alternatives: tuple[RecommendationAlternative, ...] = ()
    computed_at: datetime
    context: RecommendationContext


class RecommendationService:
    def recommend_project_next_move(
        self,
        work_items: list[NormalizedWorkItem],
        *,
        current_time: datetime,
    ) -> WorkRecommendation | None:
        context = RecommendationContext(current_time=current_time)
        return self._recommend(
            work_items,
            purpose=RecommendationPurpose.PROJECT_NEXT_MOVE,
            context=context,
        )

    def recommend_current_action(
        self,
        work_items: list[NormalizedWorkItem],
        *,
        context: RecommendationContext,
    ) -> WorkRecommendation | None:
        return self._recommend(
            work_items,
            purpose=RecommendationPurpose.CURRENT_ACTION,
            context=context,
        )

    def _recommend(
        self,
        work_items: list[NormalizedWorkItem],
        *,
        purpose: RecommendationPurpose,
        context: RecommendationContext,
    ) -> WorkRecommendation | None:
        candidates = [item for item in work_items if _eligible(item)]
        scored = [
            self._score(item, purpose=purpose, context=context)
            for item in candidates
        ]
        if not scored:
            blocked = [item for item in work_items if _blocked_candidate(item)]
            if not blocked:
                return None
            scored = [
                self._score_blocker(item, purpose=purpose, context=context)
                for item in blocked
            ]

        scored.sort(key=_ranking_key)
        selected_item, selected_score, evidence, action = scored[0]
        computed_at = context.current_time or datetime.now(timezone.utc)
        alternatives = tuple(
            RecommendationAlternative(
                work=_identity(item), score=round(score, 2), action=item_action
            )
            for item, score, _, item_action in scored[1:4]
        )
        return WorkRecommendation(
            purpose=purpose,
            action=action,
            selected_work=_identity(selected_item),
            canonical_project_id=selected_item.canonical_project_id,
            score=round(selected_score, 2),
            explanation=_explanation(selected_item, action, evidence),
            evidence=tuple(evidence),
            considered_alternatives=alternatives,
            computed_at=computed_at,
            context=context,
        )

    def _score(
        self,
        item: NormalizedWorkItem,
        *,
        purpose: RecommendationPurpose,
        context: RecommendationContext,
    ) -> tuple[
        NormalizedWorkItem,
        float,
        list[RecommendationSignal],
        RecommendationAction,
    ]:
        now = context.current_time or datetime.now(timezone.utc)
        today = now.date()
        evidence: list[RecommendationSignal] = []

        priority_scores = {0: 0, 1: 0, 2: 10, 3: 25, 4: 40}
        _signal(
            evidence,
            "normalized_priority",
            int(item.priority),
            priority_scores[int(item.priority)],
            f"Normalized priority is {item.priority.name.lower()}.",
        )

        due_delta, due_text = _due_signal(item.due_date, today)
        if due_text:
            _signal(
                evidence,
                "due_urgency",
                item.due_date.isoformat(),
                due_delta,
                due_text,
            )

        age_days = _age_days(item.created_at, now)
        if age_days is not None:
            age_delta = min(age_days, 30) * 0.25
            _signal(
                evidence,
                "task_age",
                age_days,
                age_delta,
                f"Open for {age_days} day{'s' if age_days != 1 else ''}.",
            )

        foundation = _foundation_value(item)
        if foundation:
            _signal(
                evidence,
                "unblocking_foundation_value",
                foundation,
                float(foundation),
                "Foundation language indicates follow-on value.",
            )

        momentum = _momentum_value(item, context)
        if momentum:
            _signal(
                evidence,
                "project_momentum",
                momentum,
                float(momentum),
                "This work is associated with visible or supplied project momentum.",
            )

        if purpose == RecommendationPurpose.CURRENT_ACTION:
            self._context_signals(item, context, evidence)

        return (
            item,
            sum(signal.score_delta for signal in evidence),
            evidence,
            RecommendationAction.DO_WORK,
        )

    def _context_signals(
        self,
        item: NormalizedWorkItem,
        context: RecommendationContext,
        evidence: list[RecommendationSignal],
    ) -> None:
        duration = item.estimated_duration_minutes
        free_minutes = context.usable_free_block_minutes
        if duration is not None and free_minutes is not None:
            if duration <= free_minutes:
                delta, message = 25.0, f"Estimated {duration} minutes fits the supplied {free_minutes}-minute block."
            elif duration <= free_minutes + 15:
                delta, message = 5.0, f"Estimated {duration} minutes almost fits the supplied {free_minutes}-minute block."
            else:
                delta, message = -30.0, f"Estimated {duration} minutes exceeds the supplied {free_minutes}-minute block."
            _signal(
                evidence,
                "usable_free_block_fit",
                {"task_minutes": duration, "free_minutes": free_minutes},
                delta,
                message,
            )

        if context.energy is not None and item.energy_requirement is not None:
            delta = _energy_delta(context.energy, item.energy_requirement)
            _signal(
                evidence,
                "energy_fit",
                {
                    "available": context.energy.value,
                    "required": item.energy_requirement.value,
                },
                delta,
                "Compared supplied energy with the work's estimated energy requirement.",
            )

        if context.minutes_until_upcoming_commitment is not None:
            minutes = context.minutes_until_upcoming_commitment
            if duration is not None and minutes <= 60:
                delta = 15.0 if duration <= max(0, minutes - 10) else -40.0
            else:
                delta = 0.0
            _signal(
                evidence,
                "upcoming_commitment",
                {
                    "title": context.upcoming_commitment_title,
                    "minutes_until": minutes,
                },
                delta,
                "Used only the supplied upcoming-commitment context.",
            )

    def _score_blocker(
        self,
        item: NormalizedWorkItem,
        *,
        purpose: RecommendationPurpose,
        context: RecommendationContext,
    ) -> tuple[
        NormalizedWorkItem,
        float,
        list[RecommendationSignal],
        RecommendationAction,
    ]:
        _, _, evidence, _ = self._score(
            item,
            purpose=purpose,
            context=context,
        )
        _signal(
            evidence,
            "blocker_resolution",
            True,
            100.0,
            "The work is explicitly blocked, so resolve its blocker instead of doing the work.",
        )
        _signal(
            evidence,
            "dependency_references",
            [dependency.model_dump(mode="json") for dependency in item.dependencies],
            float(len(item.dependencies)),
            "Preserved explicit dependency references.",
        )
        return (
            item,
            sum(signal.score_delta for signal in evidence),
            evidence,
            RecommendationAction.RESOLVE_BLOCKER,
        )


def _eligible(item: NormalizedWorkItem) -> bool:
    return item.status == WorkStatus.OPEN and item.is_executable and not item.is_container and not item.is_blocked


def _blocked_candidate(item: NormalizedWorkItem) -> bool:
    return item.status == WorkStatus.OPEN and item.is_executable and not item.is_container and item.is_blocked


def _identity(item: NormalizedWorkItem) -> RecommendationWorkIdentity:
    return RecommendationWorkIdentity(provider=item.provider, provider_record_id=item.provider_record_id, title=item.title)


def _signal(
    evidence: list[RecommendationSignal],
    name: str,
    value: Any,
    delta: float,
    explanation: str,
) -> None:
    evidence.append(
        RecommendationSignal(
            signal=name,
            value=value,
            score_delta=delta,
            explanation=explanation,
        )
    )


def _due_signal(due: date | None, today: date) -> tuple[float, str | None]:
    if due is None:
        return 0.0, None
    days = (due - today).days
    if days < 0:
        return 100.0, "Overdue work receives the strongest due-urgency signal."
    if days == 0:
        return 80.0, "Due today."
    if days == 1:
        return 50.0, "Due tomorrow."
    if days <= 7:
        return 20.0, "Due within seven days."
    return 0.0, "Has a later due date."


def _age_days(created_at: datetime | None, now: datetime) -> int | None:
    if created_at is None:
        return None
    comparable_now = now
    comparable_created = created_at
    if comparable_now.tzinfo is None and comparable_created.tzinfo is not None:
        comparable_now = comparable_now.replace(tzinfo=comparable_created.tzinfo)
    elif comparable_now.tzinfo is not None and comparable_created.tzinfo is None:
        comparable_created = comparable_created.replace(tzinfo=comparable_now.tzinfo)
    return max(0, (comparable_now - comparable_created).days)


def _text(item: NormalizedWorkItem) -> str:
    labels = item.provider_metadata.get("labels") or []
    return f"{item.title} {item.description} {' '.join(str(label) for label in labels)}".lower()


def _foundation_value(item: NormalizedWorkItem) -> int:
    text = _text(item)
    score = 0
    if re.search(r"\bbuild\b", text):
        score += 2
    if re.search(r"\bsetup\b|\bset up\b", text):
        score += 2
    if "create system" in text:
        score += 3
    if re.search(r"\bfoundation\b|\bfoundational\b", text):
        score += 3
    if re.search(r"\btool\b|\btemplate\b|\bworkflow\b|\baccount\b", text):
        score += 1
    return score


def _momentum_value(item: NormalizedWorkItem, context: RecommendationContext) -> int:
    if item.provider_record_id in context.project_momentum_provider_record_ids:
        return 3
    pattern = (
        r"\bdemo\b|\bclient\b|\boutreach\b|\bproposal\b|"
        r"\bship\b|\blaunch\b|\bpublish\b|\bsend\b"
    )
    return 3 if re.search(pattern, _text(item)) else 0


def _energy_delta(available: WorkEnergy, required: WorkEnergy) -> float:
    if available == required:
        return 15.0
    if available == WorkEnergy.LOW and required == WorkEnergy.HIGH:
        return -70.0
    if available == WorkEnergy.HIGH and required == WorkEnergy.LOW:
        return -5.0
    return 0.0


def _ranking_key(
    scored: tuple[
        NormalizedWorkItem,
        float,
        list[RecommendationSignal],
        RecommendationAction,
    ],
) -> tuple[Any, ...]:
    item, score, _, action = scored
    due = item.due_date or date.max
    created = item.created_at.isoformat() if item.created_at else "9999"
    return (-score, due, created, action.value, item.provider, item.provider_record_id, item.title.casefold())


def _explanation(
    item: NormalizedWorkItem,
    action: RecommendationAction,
    evidence: list[RecommendationSignal],
) -> str:
    if action == RecommendationAction.RESOLVE_BLOCKER:
        return f"Resolve the blocker for {item.title}."
    positive = [signal.explanation for signal in evidence if signal.score_delta > 0]
    return positive[0] if positive else f"Best executable next action: {item.title}."


recommendation_service = RecommendationService()
