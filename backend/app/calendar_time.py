from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo
from typing import Any


@dataclass(frozen=True)
class CalendarTimeState:
    now: datetime
    remaining_events: tuple[dict[str, Any], ...]
    blocking_events: tuple[dict[str, Any], ...]
    next_event: dict[str, Any] | None
    minutes_until_next_event: int | None
    current_free_block: dict[str, Any] | None
    current_or_next_free_block: dict[str, Any] | None


def normalize_calendar_time(
    events: list[dict[str, Any]],
    *,
    now: datetime | None,
    local_tz: tzinfo,
) -> CalendarTimeState:
    local_now = normalize_datetime(now or datetime.now(local_tz), local_tz)
    end_of_day = datetime.combine(local_now.date() + timedelta(days=1), time.min, tzinfo=local_tz)
    normalized_events = [
        normalized
        for event in events
        if (normalized := normalize_event(event, local_tz)) is not None
    ]
    remaining_events = sorted(
        (
            event
            for event in normalized_events
            if event_end(event, local_tz) > local_now
            and event_start(event, local_tz) < end_of_day
        ),
        key=lambda event: event_start(event, local_tz),
    )
    blocking_events = tuple(event for event in remaining_events if event_blocks_time(event))
    next_event = next(
        (event for event in blocking_events if event_start(event, local_tz) > local_now),
        None,
    )
    minutes_until_next_event = (
        ceil_minutes_between(local_now, event_start(next_event, local_tz))
        if next_event
        else None
    )
    current_or_next_free_block = _find_current_or_next_free_block(
        blocking_events,
        now=local_now,
        end_of_day=end_of_day,
        local_tz=local_tz,
    )
    current_free_block = (
        current_or_next_free_block
        if current_or_next_free_block and current_or_next_free_block["is_current"]
        else None
    )
    return CalendarTimeState(
        now=local_now,
        remaining_events=tuple(remaining_events),
        blocking_events=blocking_events,
        next_event=next_event,
        minutes_until_next_event=minutes_until_next_event,
        current_free_block=current_free_block,
        current_or_next_free_block=current_or_next_free_block,
    )


def normalize_datetime(value: datetime, local_tz: tzinfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=local_tz)
    return value.astimezone(local_tz)


def normalize_event(event: dict[str, Any], local_tz: tzinfo) -> dict[str, Any] | None:
    try:
        start = parse_event_datetime(event.get("start"), local_tz)
        end = parse_event_datetime(event.get("end"), local_tz)
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    normalized = dict(event)
    normalized["start"] = start.isoformat()
    normalized["end"] = end.isoformat()
    normalized["duration_minutes"] = int((end - start).total_seconds() // 60)
    normalized["all_day"] = bool(event.get("all_day"))
    normalized["busy"] = bool(event.get("busy"))
    normalized["event_category"] = event_category(event)
    normalized["event_type"] = normalized["event_category"]
    return normalized


def parse_event_datetime(value: Any, local_tz: tzinfo) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        raise ValueError("Calendar event timestamp is missing.")
    return normalize_datetime(parsed, local_tz)


def event_start(event: dict[str, Any], local_tz: tzinfo) -> datetime:
    return parse_event_datetime(event.get("start"), local_tz)


def event_end(event: dict[str, Any], local_tz: tzinfo) -> datetime:
    return parse_event_datetime(event.get("end"), local_tz)


def event_category(event: dict[str, Any]) -> str:
    category = event.get("event_category") or event.get("event_type")
    if category == "soft":
        return "informational"
    if category in {"hard", "flexible", "informational", "social"}:
        return str(category)
    return "flexible"


def event_blocks_time(event: dict[str, Any]) -> bool:
    return (
        bool(event.get("busy"))
        and not bool(event.get("all_day"))
        and event_category(event) != "informational"
    )


def ceil_minutes_between(start: datetime, end: datetime) -> int:
    seconds = (end - start).total_seconds()
    return max(0, int(seconds // 60 + (1 if seconds % 60 else 0)))


def _find_current_or_next_free_block(
    blocking_events: tuple[dict[str, Any], ...],
    *,
    now: datetime,
    end_of_day: datetime,
    local_tz: tzinfo,
) -> dict[str, Any] | None:
    free_start = now
    is_current = True
    for event in blocking_events:
        start = event_start(event, local_tz)
        end = event_end(event, local_tz)
        if end <= free_start:
            continue
        if start <= free_start:
            free_start = max(free_start, end)
            is_current = False
            continue
        block = _free_block(free_start, min(start, end_of_day), is_current=is_current)
        if block:
            return block
    return _free_block(free_start, end_of_day, is_current=is_current)


def _free_block(start: datetime, end: datetime, *, is_current: bool) -> dict[str, Any] | None:
    duration_minutes = int((end - start).total_seconds() // 60)
    if duration_minutes <= 0:
        return None
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": duration_minutes,
        "is_current": is_current,
    }
