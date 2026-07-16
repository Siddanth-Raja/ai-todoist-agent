from datetime import datetime
from typing import Any

from .calendar_time import CalendarTimeState, normalize_calendar_time
from .calendar_tools import list_remaining_today_events
from .project_brain import (
    ProjectBrainProjectSnapshot,
    ProjectBrainSnapshot,
    project_brain_service,
)
from .recommendation_service import (
    RecommendationContext,
    WorkRecommendation,
    recommendation_service,
)
from .work_domain import NormalizedWorkItem, WorkPriority, WorkStatus


TODAY_PROJECTS = (
    ("A&M", "am"),
    ("XO", "xo"),
    ("Freelance", "freelance"),
    ("Nebulo", "nebulo"),
    ("Personal", "personal"),
    ("Misc", "needs-classification"),
)

LIFE_AREA_DESCRIPTIONS = {
    "A&M": "College, TAMU, Blinn, housing, registration",
    "XO": "VR, prototype, headset, Ashwin, Charlie",
    "Nebulo": "AI context control, private storage, product work",
    "Freelance": "clients, outreach, websites, invoices",
    "Personal": "gym, health, shopping, errands, car, life admin",
    "Misc": "uncategorized",
}

CONTEXT_SIGNAL_NAMES = {
    "usable_free_block_fit",
    "upcoming_commitment",
    "energy_fit",
}


class TodayProjectionService:
    def build(
        self,
        *,
        settings: Any,
        current_time: datetime | None = None,
    ) -> dict[str, Any]:
        project_snapshot = project_brain_service.snapshot(
            settings=settings,
            current_time=current_time,
        )
        calendar_result = list_remaining_today_events(settings, now=current_time)
        calendar_time = normalize_calendar_time(
            calendar_result.events,
            now=project_snapshot.now,
            local_tz=settings.local_tz,
        )
        context = RecommendationContext(
            current_time=calendar_time.now,
            usable_free_block_minutes=(
                calendar_time.current_free_block["duration_minutes"]
                if calendar_time.current_free_block
                else None
            ),
            upcoming_commitment_title=(
                str(calendar_time.next_event.get("title") or "Upcoming commitment")
                if calendar_time.next_event
                else None
            ),
            minutes_until_upcoming_commitment=calendar_time.minutes_until_next_event,
        )
        current_action = recommendation_service.recommend_current_action(
            list(project_snapshot.normalized_work),
            context=context,
        )
        errors = tuple(
            dict.fromkeys(
                [
                    *project_snapshot.warnings,
                    *([calendar_result.error] if calendar_result.error else []),
                ]
            )
        )
        current_free_block = _today_free_block_payload(
            calendar_time,
        )

        return {
            "now": calendar_time.now.isoformat(),
            "now_display": _format_datetime_display(calendar_time.now),
            "next_event": (
                _today_event_payload(calendar_time.next_event, settings.local_tz)
                if calendar_time.next_event
                else None
            ),
            "minutes_until_next_event": calendar_time.minutes_until_next_event,
            "current_free_block": current_free_block,
            "today_remaining_events": [
                _today_event_payload(event, settings.local_tz)
                for event in calendar_time.remaining_events
            ],
            "recommendation": _today_recommendation(
                project_snapshot=project_snapshot,
                calendar_time=calendar_time,
                current_action=current_action,
                errors=errors,
            ),
            "life_areas": _life_area_projections(project_snapshot),
            "errors": list(errors),
        }


def _today_recommendation(
    *,
    project_snapshot: ProjectBrainSnapshot,
    calendar_time: CalendarTimeState,
    current_action: WorkRecommendation | None,
    errors: tuple[str, ...],
) -> dict[str, Any]:
    next_event = calendar_time.next_event
    minutes_until = calendar_time.minutes_until_next_event
    if next_event and minutes_until is not None and minutes_until <= 60:
        event_payload = _today_event_payload(next_event, calendar_time.now.tzinfo)
        if minutes_until <= 30:
            title = f"Prepare to leave for {next_event.get('title')}"
            detail = "This is inside 30 minutes, so only preparation, packing, notes, or travel should be considered."
        else:
            title = f"Prepare for {next_event.get('title')}"
            detail = "The next commitment starts within 60 minutes. Review context, agenda, materials, and travel buffer now."
        return _recommendation_payload(
            recommendation_type="prepare",
            source="calendar",
            title=title,
            detail=detail,
            reason=detail,
            event=event_payload,
            evidence=[
                {
                    "signal": "upcoming_commitment",
                    "value": {
                        "title": next_event.get("title"),
                        "minutes_until": minutes_until,
                    },
                    "score_delta": 0,
                    "explanation": "Calendar-first preparation takes precedence inside 60 minutes.",
                }
            ],
        )

    if current_action:
        selected_item = _selected_work_item(project_snapshot, current_action)
        project = _project_for_recommendation(project_snapshot, current_action)
        contextual_evidence = [
            signal
            for signal in current_action.evidence
            if signal.signal in CONTEXT_SIGNAL_NAMES and signal.score_delta != 0
        ]
        canonical = project.canonical_recommendation if project else None
        contextual_override = bool(
            canonical
            and _recommendation_identity(canonical) != _recommendation_identity(current_action)
            and contextual_evidence
        )
        reason = (
            "Contextual override: "
            + " ".join(signal.explanation for signal in contextual_evidence)
            if contextual_override
            else current_action.explanation
        )
        return _recommendation_payload(
            recommendation_type="task",
            source="shared_recommendation",
            title=current_action.selected_work.title,
            detail=reason,
            reason=reason,
            task=_work_payload(selected_item) if selected_item else None,
            evidence=[signal.model_dump(mode="json") for signal in current_action.evidence],
            alternatives=[
                alternative.model_dump(mode="json")
                for alternative in current_action.considered_alternatives
            ],
            provider=current_action.selected_work.provider,
            provider_record_id=current_action.selected_work.provider_record_id,
            canonical_project_id=current_action.canonical_project_id,
            canonical_project_key=(str(project.definition["key"]) if project else None),
            canonical_project_next_move=(
                str(project.summary["next_recommendation"]) if project else None
            ),
            contextual_override=contextual_override,
        )

    if errors:
        detail = "Shared project intelligence is degraded. Provider errors are shown below instead of treating unavailable work as an empty day."
        return _recommendation_payload(
            recommendation_type="unavailable",
            source="fallback",
            title="Project intelligence unavailable",
            detail=detail,
            reason=detail,
        )

    if next_event:
        detail = "No normalized work clearly fits the available block, so keep the calendar transition clean."
        return _recommendation_payload(
            recommendation_type="calendar",
            source="calendar",
            title=f"Protect the buffer before {next_event.get('title')}",
            detail=detail,
            reason=detail,
            event=_today_event_payload(next_event, calendar_time.now.tzinfo),
        )

    detail = "No executable normalized work or remaining calendar commitment is available."
    return _recommendation_payload(
        recommendation_type="open",
        source="fallback",
        title="No remaining calendar commitments",
        detail=detail,
        reason=detail,
    )


def _recommendation_payload(
    *,
    recommendation_type: str,
    source: str,
    title: str,
    detail: str,
    reason: str,
    task: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    alternatives: list[dict[str, Any]] | None = None,
    provider: str | None = None,
    provider_record_id: str | None = None,
    canonical_project_id: str | None = None,
    canonical_project_key: str | None = None,
    canonical_project_next_move: str | None = None,
    contextual_override: bool = False,
) -> dict[str, Any]:
    return {
        "type": recommendation_type,
        "source": source,
        "title": title,
        "detail": detail,
        "reason": reason,
        "task": task,
        "event": event,
        "evidence": evidence or [],
        "alternatives": alternatives or [],
        "provider": provider,
        "provider_record_id": provider_record_id,
        "canonical_project_id": canonical_project_id,
        "canonical_project_key": canonical_project_key,
        "canonical_project_next_move": canonical_project_next_move,
        "contextual_override": contextual_override,
    }


def _life_area_projections(
    snapshot: ProjectBrainSnapshot,
) -> list[dict[str, Any]]:
    areas: list[dict[str, Any]] = []
    for name, project_key in TODAY_PROJECTS:
        project = snapshot.project_for_key(project_key)
        if not project:
            continue
        todoist_work = [
            item
            for item in project.work_items
            if item.provider == "todoist" and item.status == WorkStatus.OPEN
        ]
        diagnostic = project.summary.get("linear_diagnostic")
        provider_status = getattr(diagnostic, "status", None)
        provider_message = getattr(diagnostic, "message", None)
        areas.append(
            {
                "name": name,
                "description": LIFE_AREA_DESCRIPTIONS[name],
                "project_key": project_key,
                "canonical_project_id": project.definition.get("canonical_project_id"),
                "status": project.summary["status"],
                "next_recommendation": project.summary["next_recommendation"],
                "task_count": project.summary["task_count"],
                "overdue_count": sum(
                    1
                    for item in todoist_work
                    if item.due_date and item.due_date < snapshot.now.date()
                ),
                "today_count": sum(
                    1 for item in todoist_work if item.due_date == snapshot.now.date()
                ),
                "high_priority_count": sum(
                    1 for item in todoist_work if item.priority == WorkPriority.URGENT
                ),
                "provider_status": provider_status,
                "provider_message": provider_message,
                "degraded": bool(
                    provider_status
                    and provider_status not in {"connected", "not_mapped"}
                ),
            }
        )
    return areas


def _project_for_recommendation(
    snapshot: ProjectBrainSnapshot,
    recommendation: WorkRecommendation,
) -> ProjectBrainProjectSnapshot | None:
    by_canonical_id = snapshot.project_for_canonical_id(
        recommendation.canonical_project_id
    )
    if by_canonical_id:
        return by_canonical_id
    identity = _recommendation_identity(recommendation)
    return next(
        (
            project
            for project in snapshot.projects
            if any(
                (item.provider, item.provider_record_id) == identity
                for item in project.work_items
            )
        ),
        None,
    )


def _selected_work_item(
    snapshot: ProjectBrainSnapshot,
    recommendation: WorkRecommendation,
) -> NormalizedWorkItem | None:
    identity = _recommendation_identity(recommendation)
    return next(
        (
            item
            for item in snapshot.normalized_work
            if (item.provider, item.provider_record_id) == identity
        ),
        None,
    )


def _recommendation_identity(
    recommendation: WorkRecommendation,
) -> tuple[str, str]:
    return (
        recommendation.selected_work.provider,
        recommendation.selected_work.provider_record_id,
    )


def _work_payload(item: NormalizedWorkItem) -> dict[str, Any]:
    return {
        **item.to_legacy_task(),
        "provider": item.provider,
        "provider_record_id": item.provider_record_id,
        "canonical_project_id": item.canonical_project_id,
        "normalized_priority": int(item.priority),
        "estimated_duration_minutes": item.estimated_duration_minutes,
        "energy_requirement": (
            item.energy_requirement.value if item.energy_requirement else None
        ),
    }


def _today_free_block_payload(
    calendar_time: CalendarTimeState,
) -> dict[str, Any] | None:
    block = calendar_time.current_free_block
    minutes_until = calendar_time.minutes_until_next_event
    if not block or (minutes_until is not None and minutes_until <= 30):
        return None
    start = datetime.fromisoformat(block["start"])
    end = datetime.fromisoformat(block["end"])
    return {
        "start": block["start"],
        "end": block["end"],
        "start_display": _format_time_display(start),
        "end_display": _format_time_display(end),
        "time_range_display": f"{_format_time_display(start)}-{_format_time_display(end)}",
        "duration_minutes": block["duration_minutes"],
        "low_usefulness": bool(minutes_until is not None and minutes_until <= 60),
    }


def _today_event_payload(event: dict[str, Any], local_tz) -> dict[str, Any]:
    start = _event_datetime(event.get("start"), local_tz)
    end = _event_datetime(event.get("end"), local_tz)
    return {
        "id": event.get("id"),
        "title": event.get("title") or "(No title)",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "start_display": _format_time_display(start),
        "end_display": _format_time_display(end),
        "time_range_display": f"{_format_time_display(start)}-{_format_time_display(end)}",
        "duration_minutes": int(
            event.get("duration_minutes") or (end - start).total_seconds() // 60
        ),
        "event_category": str(
            event.get("event_category") or event.get("event_type") or "flexible"
        ),
        "location": event.get("location"),
        "html_link": event.get("html_link"),
    }


def _event_datetime(value: Any, local_tz) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(local_tz)


def _format_time_display(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _format_datetime_display(value: datetime) -> str:
    return f"{value.strftime('%A, %B')} {value.day} at {_format_time_display(value)}"


today_projection_service = TodayProjectionService()
