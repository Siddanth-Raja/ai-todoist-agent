from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from .calendar_tools import infer_event_category


CalendarSeverity = Literal["none", "low", "medium", "high"]
CalendarIssueType = Literal["overlap", "tight_buffer", "travel_buffer", "informational_overlap"]
CalendarFixAction = Literal[
    "none",
    "move_new_event",
    "move_existing_event",
    "add_travel_buffer",
    "add_prep_block",
]


@dataclass
class CalendarIssue:
    type: CalendarIssueType
    message: str
    affected_event_id: str | None = None
    affected_event_title: str | None = None
    minutes_between: int | None = None


@dataclass
class CalendarSuggestedFix:
    action: CalendarFixAction
    event_id: str | None = None
    new_start: str | None = None
    new_end: str | None = None
    reason: str = ""


@dataclass
class CalendarAnalysis:
    has_conflict: bool
    has_buffer_issue: bool
    severity: CalendarSeverity
    issues: list[CalendarIssue]
    suggested_fix: CalendarSuggestedFix | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TRAVEL_BUFFER_MINUTES = 30


def analyze_calendar_change(
    new_event: dict[str, Any],
    existing_events: list[dict[str, Any]],
    user_context: dict[str, Any] | None = None,
) -> CalendarAnalysis:
    del user_context

    issues: list[CalendarIssue] = []
    suggested_fix: CalendarSuggestedFix | None = None
    new_start = _event_start(new_event)
    new_end = _event_end(new_event)
    new_category = _event_category(new_event)
    new_is_blocking = _is_blocking_event(new_event)

    if new_category == "informational" or _is_all_day_event(new_event):
        return CalendarAnalysis(
            has_conflict=False,
            has_buffer_issue=False,
            severity="none",
            issues=[
                CalendarIssue(
                    type="informational_overlap",
                    message=f"{_event_title(new_event)} is informational/all-day, so it does not block your schedule.",
                )
            ],
            suggested_fix=None,
        )

    for existing_event in existing_events:
        existing_start = _event_start(existing_event)
        existing_end = _event_end(existing_event)
        if existing_start is None or existing_end is None or new_start is None or new_end is None:
            continue

        if _overlaps(new_start, new_end, existing_start, existing_end):
            if not _is_blocking_event(existing_event) or not new_is_blocking:
                issues.append(
                    CalendarIssue(
                        type="informational_overlap",
                        message=f"{_event_title(existing_event)} is informational/all-day, so it does not block your schedule.",
                        affected_event_id=_event_id(existing_event),
                        affected_event_title=_event_title(existing_event),
                    )
                )
                continue

            issues.append(
                CalendarIssue(
                    type="overlap",
                    message=f"This overlaps with {_event_title(existing_event)}.",
                    affected_event_id=_event_id(existing_event),
                    affected_event_title=_event_title(existing_event),
                    minutes_between=None,
                )
            )
            if suggested_fix is None:
                suggested_fix = _overlap_fix(new_event, existing_event)
            continue

        buffer_issue = _buffer_issue_between(new_event, existing_event)
        if buffer_issue:
            issues.append(buffer_issue)
            if suggested_fix is None:
                suggested_fix = _buffer_fix(new_event, existing_event, buffer_issue)

    travel_issue = _travel_issue(new_event, existing_events)
    if travel_issue:
        issues.append(travel_issue)
        if suggested_fix is None:
            suggested_fix = _travel_fix(new_event, travel_issue)

    has_conflict = any(issue.type == "overlap" for issue in issues)
    has_buffer_issue = any(issue.type in {"tight_buffer", "travel_buffer"} for issue in issues)
    severity = _severity_for(issues)

    return CalendarAnalysis(
        has_conflict=has_conflict,
        has_buffer_issue=has_buffer_issue,
        severity=severity,
        issues=issues,
        suggested_fix=suggested_fix,
    )


def _overlap_fix(
    new_event: dict[str, Any],
    existing_event: dict[str, Any],
) -> CalendarSuggestedFix | None:
    new_category = _event_category(new_event)
    existing_category = _event_category(existing_event)
    if new_category == "hard" and existing_category == "flexible":
        return _move_existing_after_new_event(new_event, existing_event, "Move the flexible event after the new hard commitment.")
    if new_category == "flexible" and existing_category == "hard":
        return _move_new_after_existing_event(new_event, existing_event, "Move the flexible event after the hard commitment.")
    return None


def _buffer_fix(
    new_event: dict[str, Any],
    existing_event: dict[str, Any],
    issue: CalendarIssue,
) -> CalendarSuggestedFix | None:
    new_start = _event_start(new_event)
    existing_start = _event_start(existing_event)
    if new_start is None or existing_start is None:
        return None

    if existing_start < new_start and _event_category(new_event) == "flexible":
        return _move_new_after_existing_event(new_event, existing_event, issue.message)
    if existing_start > new_start and _event_category(existing_event) == "flexible":
        return _move_existing_after_new_event(new_event, existing_event, issue.message)
    return None


def _travel_fix(new_event: dict[str, Any], issue: CalendarIssue) -> CalendarSuggestedFix | None:
    start = _event_start(new_event)
    if start is None:
        return None

    action: CalendarFixAction = "add_prep_block" if _has_interview_language(new_event) else "add_travel_buffer"
    buffer_start = start - timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    return CalendarSuggestedFix(
        action=action,
        event_id=None,
        new_start=buffer_start.isoformat(),
        new_end=start.isoformat(),
        reason=issue.message,
    )


def _move_existing_after_new_event(
    new_event: dict[str, Any],
    existing_event: dict[str, Any],
    reason: str,
) -> CalendarSuggestedFix | None:
    new_end = _event_end(new_event)
    existing_start = _event_start(existing_event)
    existing_end = _event_end(existing_event)
    if new_end is None or existing_start is None or existing_end is None:
        return None

    buffer_minutes = _required_buffer_minutes(new_event, existing_event)
    duration = existing_end - existing_start
    moved_start = new_end + timedelta(minutes=buffer_minutes)
    return CalendarSuggestedFix(
        action="move_existing_event",
        event_id=_event_id(existing_event),
        new_start=moved_start.isoformat(),
        new_end=(moved_start + duration).isoformat(),
        reason=reason,
    )


def _move_new_after_existing_event(
    new_event: dict[str, Any],
    existing_event: dict[str, Any],
    reason: str,
) -> CalendarSuggestedFix | None:
    new_start = _event_start(new_event)
    new_end = _event_end(new_event)
    existing_end = _event_end(existing_event)
    if new_start is None or new_end is None or existing_end is None:
        return None

    buffer_minutes = _required_buffer_minutes(existing_event, new_event)
    duration = new_end - new_start
    moved_start = existing_end + timedelta(minutes=buffer_minutes)
    return CalendarSuggestedFix(
        action="move_new_event",
        event_id=None,
        new_start=moved_start.isoformat(),
        new_end=(moved_start + duration).isoformat(),
        reason=reason,
    )


def _buffer_issue_between(new_event: dict[str, Any], existing_event: dict[str, Any]) -> CalendarIssue | None:
    if not _is_blocking_event(new_event) or not _is_blocking_event(existing_event):
        return None

    first_event, second_event = _chronological_pair(new_event, existing_event)
    first_end = _event_end(first_event)
    second_start = _event_start(second_event)
    if first_end is None or second_start is None:
        return None

    minutes_between = int((second_start - first_end).total_seconds() // 60)
    if minutes_between < 0:
        return None

    required_buffer = _required_buffer_minutes(first_event, second_event)
    if required_buffer == 0 or minutes_between >= required_buffer:
        return None

    return CalendarIssue(
        type="tight_buffer",
        message=(
            f"This does not overlap, but it leaves only {minutes_between} minutes after "
            f"{_event_title(first_event)}."
        ),
        affected_event_id=_event_id(existing_event),
        affected_event_title=_event_title(existing_event),
        minutes_between=minutes_between,
    )


def _travel_issue(new_event: dict[str, Any], existing_events: list[dict[str, Any]]) -> CalendarIssue | None:
    if not _has_travel_language(new_event):
        return None
    if _has_explicit_buffer_before(new_event, existing_events):
        return None

    return CalendarIssue(
        type="travel_buffer",
        message=f"{_event_title(new_event)} likely needs a travel or prep buffer.",
        affected_event_id=None,
        affected_event_title=None,
        minutes_between=None,
    )


def _required_buffer_minutes(first_event: dict[str, Any], second_event: dict[str, Any]) -> int:
    first_category = _event_category(first_event)
    second_category = _event_category(second_event)
    first_text = _event_text(first_event)
    second_text = _event_text(second_event)

    if "interview" in first_text or "interview" in second_text:
        return 30
    if first_category == "hard" and second_category == "hard":
        return 15
    if first_category == "hard" and second_category == "flexible":
        return 30
    if first_category == "social" and second_category == "hard":
        return 30
    if "family" in first_text and second_category == "hard":
        return 30
    return 0


def _has_explicit_buffer_before(new_event: dict[str, Any], existing_events: list[dict[str, Any]]) -> bool:
    new_start = _event_start(new_event)
    if new_start is None:
        return False

    for event in existing_events:
        event_end = _event_end(event)
        if event_end is None:
            continue
        minutes_before = int((new_start - event_end).total_seconds() // 60)
        if 0 <= minutes_before <= TRAVEL_BUFFER_MINUTES and _is_buffer_event(event):
            return True
    return False


def _is_buffer_event(event: dict[str, Any]) -> bool:
    text = _event_text(event)
    return any(keyword in text for keyword in ("buffer", "travel", "prep", "drive"))


def _has_travel_language(event: dict[str, Any]) -> bool:
    text = _event_text(event)
    return (
        "at ashwin's" in text
        or "at ashwin’s" in text
        or "plano" in text
        or "dallas" in text
        or "college station" in text
        or "airport" in text
        or "interview" in text
        or "party" in text
    )


def _has_interview_language(event: dict[str, Any]) -> bool:
    return "interview" in _event_text(event)


def _severity_for(issues: list[CalendarIssue]) -> CalendarSeverity:
    if any(issue.type == "overlap" for issue in issues):
        return "high"
    if any(issue.type in {"tight_buffer", "travel_buffer"} for issue in issues):
        return "medium"
    if any(issue.type == "informational_overlap" for issue in issues):
        return "none"
    return "none"


def _chronological_pair(
    first_event: dict[str, Any],
    second_event: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    first_start = _event_start(first_event)
    second_start = _event_start(second_event)
    if first_start is not None and second_start is not None and first_start <= second_start:
        return first_event, second_event
    return second_event, first_event


def _is_blocking_event(event: dict[str, Any]) -> bool:
    if _is_all_day_event(event):
        return False
    if event.get("busy") is False:
        return False
    return _event_category(event) != "informational"


def _is_all_day_event(event: dict[str, Any]) -> bool:
    return bool(event.get("all_day"))


def _event_category(event: dict[str, Any]) -> str:
    category = event.get("event_category") or event.get("event_type")
    if category in {"hard", "flexible", "informational", "social"}:
        return str(category)

    text = _event_text(event)
    if any(keyword in text for keyword in ("party", "hangout", "hang out", "dinner", "family visit")):
        return "social"
    return infer_event_category(_event_title(event), attendees=[])


def _event_text(event: dict[str, Any]) -> str:
    return " ".join(
        [
            str(event.get("title") or ""),
            str(event.get("summary") or ""),
            str(event.get("description") or ""),
            str(event.get("location") or ""),
        ]
    ).lower()


def _event_id(event: dict[str, Any]) -> str | None:
    event_id = event.get("id")
    return str(event_id) if event_id else None


def _event_title(event: dict[str, Any]) -> str:
    return str(event.get("title") or event.get("summary") or "Event")


def _event_start(event: dict[str, Any]) -> datetime | None:
    return _parse_datetime(event.get("start"))


def _event_end(event: dict[str, Any]) -> datetime | None:
    return _parse_datetime(event.get("end"))


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _overlaps(first_start: datetime, first_end: datetime, second_start: datetime, second_end: datetime) -> bool:
    return first_start < second_end and first_end > second_start
