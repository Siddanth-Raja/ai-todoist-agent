from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
import re
from typing import Any

from .calendar_time import normalize_event, parse_event_datetime
from .calendar_tools import CalendarReadResult


class CalendarGroundingState(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONNECTED_NO_MATCH = "connected_no_match"
    EXACT_MATCH = "exact_match"
    AMBIGUOUS_MATCH = "ambiguous_match"


@dataclass(frozen=True)
class CalendarChatGrounding:
    answer: str
    state: CalendarGroundingState
    context: dict[str, Any]
    awaiting: str | None = None
    last_question: str | None = None
    warnings: tuple[str, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CalendarLookupRequest:
    title: str | None
    target_date: date
    asks_location: bool = False
    asks_preparation: bool = False


CALENDAR_TITLE_ALIASES = {
    "interview": ("interview", "recruiter", "hiring", "career", "phone screen"),
    "meeting": ("meeting", "meet", "sync", "call"),
    "appointment": ("appointment", "doctor", "dentist"),
    "party": ("party", "parties"),
    "gym": ("gym", "workout"),
    "class": ("class", "lecture", "seminar"),
}

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

READ_PREFIXES = (
    "what time",
    "when",
    "where",
    "do i have",
    "do i need",
    "is there",
    "is my",
    "is the",
    "what is on my calendar",
    "what's on my calendar",
    "whats on my calendar",
)

WRITE_REQUEST_PATTERN = re.compile(
    r"^(?:please\s+)?(?:add|create|schedule|move|reschedule|update|delete|cancel|put|book)\b"
    r"|^(?:can|could|would)\s+you\s+(?:please\s+)?"
    r"(?:add|create|schedule|move|reschedule|update|delete|cancel|put|book)\b",
    flags=re.IGNORECASE,
)


class CalendarChatGroundingService:
    def ground(
        self,
        message: str,
        *,
        today_result: CalendarReadResult,
        upcoming_result: CalendarReadResult,
        local_now: datetime,
        conversation_state: dict[str, Any] | None = None,
    ) -> CalendarChatGrounding | None:
        state = conversation_state if isinstance(conversation_state, dict) else {}
        context = state.get("context") if isinstance(state.get("context"), dict) else {}
        awaiting = state.get("awaiting")

        request = _lookup_request(message, local_now, context=context, awaiting=awaiting)
        if request is None:
            return None

        provider_result = (
            today_result if request.target_date == local_now.date() else upcoming_result
        )
        base_context = _base_context(request)
        if provider_result.error:
            return _provider_unavailable(
                request,
                diagnostic=provider_result.error,
                context=base_context,
            )
        if not isinstance(provider_result.events, list):
            diagnostic = "Calendar returned a malformed event collection."
            return _provider_unavailable(
                request,
                diagnostic=diagnostic,
                context=base_context,
            )

        normalized_events, malformed_count = _normalized_events(
            provider_result.events,
            local_now.tzinfo,
        )
        if provider_result.events and not normalized_events:
            diagnostic = (
                "Calendar returned event data, but none of it had readable start "
                "and end times."
            )
            return _provider_unavailable(
                request,
                diagnostic=diagnostic,
                context=base_context,
            )

        date_events = [
            event
            for event in normalized_events
            if parse_event_datetime(event["start"], local_now.tzinfo).date()
            == request.target_date
        ]
        warnings = (
            (f"Ignored {malformed_count} malformed Calendar event record(s).",)
            if malformed_count
            else ()
        )
        matches = _matching_events(
            date_events,
            request.title,
            context=context,
            awaiting=awaiting,
        )

        if not matches and malformed_count:
            diagnostic = (
                f"Calendar returned {malformed_count} malformed event record(s), so a "
                "connected no-match result cannot be trusted."
            )
            return _provider_unavailable(
                request,
                diagnostic=diagnostic,
                context=base_context,
            )

        if not matches:
            manual_time = _manual_followup_time(
                message,
                request.target_date,
                local_now,
                awaiting=awaiting,
            )
            if manual_time is not None:
                title = request.title or str(context.get("event_title") or "event")
                answer = (
                    f"Using the time you provided, {title} is "
                    f"{_day_label(request.target_date, local_now)} at "
                    f"{_format_time(manual_time)}. Calendar did not contain a matching "
                    "event, so this time is user-provided rather than provider-grounded."
                )
                return CalendarChatGrounding(
                    answer=answer,
                    state=CalendarGroundingState.CONNECTED_NO_MATCH,
                    context={
                        **base_context,
                        "calendar_grounding_state": CalendarGroundingState.CONNECTED_NO_MATCH.value,
                        "event_title": title,
                        "time_source": "user",
                    },
                    warnings=warnings,
                )

            subject = _subject_phrase(request.title)
            day = _day_label(request.target_date, local_now)
            answer = (
                f"Calendar is connected, but I could not find {subject} {day}. "
                "If it is not on Calendar, what time should I use?"
            )
            context_payload = {
                **base_context,
                "calendar_grounding_state": CalendarGroundingState.CONNECTED_NO_MATCH.value,
            }
            return CalendarChatGrounding(
                answer=answer,
                state=CalendarGroundingState.CONNECTED_NO_MATCH,
                context=context_payload,
                awaiting="event_detail",
                last_question="What time should I use?",
                warnings=warnings,
            )

        if len(matches) > 1:
            answer = _ambiguous_answer(request, matches, local_now)
            context_payload = {
                **base_context,
                "calendar_grounding_state": CalendarGroundingState.AMBIGUOUS_MATCH.value,
                "candidate_events": [
                    {
                        "id": event.get("id"),
                        "title": event.get("title") or "Untitled event",
                    }
                    for event in matches
                ],
            }
            return CalendarChatGrounding(
                answer=answer,
                state=CalendarGroundingState.AMBIGUOUS_MATCH,
                context=context_payload,
                awaiting="calendar_match_clarification",
                last_question="Which one do you mean?",
                warnings=warnings,
                evidence=tuple(matches),
            )

        event = matches[0]
        answer = _exact_answer(event, request, local_now)
        context_payload = {
            **base_context,
            "calendar_grounding_state": CalendarGroundingState.EXACT_MATCH.value,
            "event_id": event.get("id"),
            "event_title": str(event.get("title") or "Untitled event"),
        }
        return CalendarChatGrounding(
            answer=answer,
            state=CalendarGroundingState.EXACT_MATCH,
            context=context_payload,
            warnings=warnings,
            evidence=(event,),
        )


def _lookup_request(
    message: str,
    local_now: datetime,
    *,
    context: dict[str, Any],
    awaiting: Any,
) -> CalendarLookupRequest | None:
    text = " ".join(message.strip().replace("’", "'").split())
    lowered = text.lower()
    if WRITE_REQUEST_PATTERN.search(lowered) or "what should" in lowered or "missed" in lowered:
        return None
    if re.search(r"^do i have time\b|\btime to work\b|\bfree block\b", lowered):
        return None

    context_is_calendar = context.get("topic") == "calendar_event_lookup" or (
        awaiting in {"calendar_lookup_confirmation", "event_detail", "calendar_match_clarification"}
        and bool(context.get("kind") or context.get("search_title") or context.get("event_title"))
    )
    target_date = _target_date(lowered, local_now)
    if target_date is None and context_is_calendar:
        target_date = _context_date(context, local_now)

    if awaiting == "calendar_lookup_confirmation" and context_is_calendar:
        if _is_affirmative(lowered):
            return CalendarLookupRequest(
                title=_context_title(context),
                target_date=target_date or local_now.date(),
                asks_preparation=bool(
                    context.get("asks_preparation")
                    or context.get("is_interview_wakeup")
                ),
            )
        if _is_negative(lowered):
            return None

    if awaiting == "event_detail" and context_is_calendar and _contains_time(lowered):
        return CalendarLookupRequest(
            title=_context_title(context),
            target_date=target_date or local_now.date(),
            asks_preparation=bool(
                context.get("asks_preparation")
                or context.get("is_interview_wakeup")
            ),
        )

    if awaiting == "calendar_match_clarification" and context_is_calendar:
        return CalendarLookupRequest(
            title=_clarification_title(lowered, context) or _context_title(context),
            target_date=target_date or local_now.date(),
            asks_location=_asks_location(lowered),
            asks_preparation=bool(context.get("asks_preparation")),
        )

    if context_is_calendar and _looks_like_context_followup(lowered):
        return CalendarLookupRequest(
            title=str(context.get("event_title") or _context_title(context) or "event"),
            target_date=target_date or _context_date(context, local_now),
            asks_location=_asks_location(lowered),
            asks_preparation=_asks_preparation(lowered),
        )

    looks_like_read = (
        lowered.endswith("?")
        or lowered.startswith(READ_PREFIXES)
    )
    if not looks_like_read:
        return None

    title = _extract_title(text)
    if title is None and "calendar" not in lowered and "schedule" not in lowered:
        return None
    if title is not None and _normalized_text(title) in {"it", "that", "this", "event"}:
        return None
    return CalendarLookupRequest(
        title=title,
        target_date=target_date or local_now.date(),
        asks_location=_asks_location(lowered),
        asks_preparation=_asks_preparation(lowered),
    )


def _normalized_events(
    events: list[dict[str, Any]],
    local_tz,
) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    malformed = 0
    for event in events:
        value = normalize_event(event, local_tz)
        if value is None:
            malformed += 1
        else:
            normalized.append(value)
    normalized.sort(key=lambda event: str(event.get("start") or ""))
    return normalized, malformed


def _matching_events(
    events: list[dict[str, Any]],
    title: str | None,
    *,
    context: dict[str, Any],
    awaiting: Any,
) -> list[dict[str, Any]]:
    if awaiting == "calendar_match_clarification":
        candidate_ids = {
            str(item.get("id"))
            for item in context.get("candidate_events") or ()
            if isinstance(item, dict) and item.get("id") is not None
        }
        if candidate_ids:
            events = [event for event in events if str(event.get("id")) in candidate_ids]

    normalized_title = _normalized_text(title or "")
    if not normalized_title or normalized_title in {"anything", "events", "event", "schedule"}:
        return events

    exact = [
        event
        for event in events
        if _normalized_text(str(event.get("title") or "")) == normalized_title
    ]
    if exact:
        return exact

    aliases = CALENDAR_TITLE_ALIASES.get(normalized_title, (normalized_title,))
    matches = []
    for event in events:
        searchable = _normalized_text(
            " ".join(
                str(event.get(field) or "")
                for field in ("title", "description", "location")
            )
        )
        if any(_normalized_text(alias) in searchable for alias in aliases):
            matches.append(event)
    return matches


def _provider_unavailable(
    request: CalendarLookupRequest,
    *,
    diagnostic: str,
    context: dict[str, Any],
) -> CalendarChatGrounding:
    answer = (
        "Calendar is unavailable, so I cannot verify that event from connected state right now. "
        f"Provider diagnostic: {diagnostic}"
    )
    return CalendarChatGrounding(
        answer=answer,
        state=CalendarGroundingState.PROVIDER_UNAVAILABLE,
        context={
            **context,
            "calendar_grounding_state": CalendarGroundingState.PROVIDER_UNAVAILABLE.value,
            "provider_diagnostic": diagnostic,
        },
        warnings=(diagnostic,),
    )


def _exact_answer(
    event: dict[str, Any],
    request: CalendarLookupRequest,
    local_now: datetime,
) -> str:
    title = str(event.get("title") or "Untitled event")
    start = parse_event_datetime(event["start"], local_now.tzinfo)
    end = parse_event_datetime(event["end"], local_now.tzinfo)
    day = _day_label(start.date(), local_now)
    fact = f"{title} is {day} at {_format_time(start)} - {_format_time(end)}."
    location = str(event.get("location") or "").strip()
    if request.asks_location:
        location_fact = (
            f" Calendar lists the location as {location}."
            if location
            else " Calendar does not list a location."
        )
        return fact + location_fact
    if request.asks_preparation:
        return (
            fact
            + " Calendar provides the event time, but not enough evidence to determine "
            "a wake, travel, or preparation time without your assumptions."
        )
    return fact


def _ambiguous_answer(
    request: CalendarLookupRequest,
    matches: list[dict[str, Any]],
    local_now: datetime,
) -> str:
    items = []
    for event in matches:
        start = parse_event_datetime(event["start"], local_now.tzinfo)
        end = parse_event_datetime(event["end"], local_now.tzinfo)
        items.append(
            f"{event.get('title') or 'Untitled event'} "
            f"({_format_time(start)} - {_format_time(end)})"
        )
    return (
        f"Calendar has multiple plausible matches {_day_label(request.target_date, local_now)}: "
        f"{', '.join(items)}. Which one do you mean?"
    )


def _base_context(request: CalendarLookupRequest) -> dict[str, Any]:
    return {
        "topic": "calendar_event_lookup",
        "target_date": request.target_date.isoformat(),
        "search_title": request.title,
        "kind": request.title,
        "search_terms": (
            list(
                CALENDAR_TITLE_ALIASES.get(
                    _normalized_text(request.title or ""),
                    (request.title,),
                )
            )
            if request.title
            else []
        ),
        "asks_preparation": request.asks_preparation,
        "is_interview_wakeup": (
            request.asks_preparation
            and _normalized_text(request.title or "") == "interview"
        ),
    }


def _extract_title(message: str) -> str | None:
    text = message.strip().rstrip("?.!")
    lowered = text.lower()
    preparation = re.search(r"\bfor\s+(?:my|the|an?|your)\s+(.+)$", text, flags=re.IGNORECASE)
    if _asks_preparation(lowered) and preparation:
        candidate = preparation.group(1)
    else:
        patterns = (
            r"^what time (?:is|does)\s+(?:my|the|an?|your)?\s*(.+?)(?:\s+start)?$",
            r"^when (?:is|does)\s+(?:my|the|an?|your)?\s*(.+?)(?:\s+start)?$",
            r"^where is\s+(?:my|the|an?|your)?\s*(.+)$",
            r"^do i have\s+(?:an?|the|my)?\s*(.+)$",
            r"^is there\s+(?:an?|the|my)?\s*(.+)$",
            r"^is (?:my|the|an?|your)\s+(.+?)(?:\s+on my calendar)?$",
        )
        candidate = None
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1)
                break
    if candidate is None and "calendar" in lowered:
        return None
    if candidate is None:
        return None
    cleaned = _strip_temporal_phrase(candidate)
    cleaned = re.sub(r"\s+on (?:my|the) calendar$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:my|the|an?|your)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or None


def _strip_temporal_phrase(value: str) -> str:
    weekday_pattern = "|".join(WEEKDAYS)
    return re.sub(
        rf"\s+(?:today|tomorrow|next week|(?:next\s+)?(?:{weekday_pattern}))$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def _target_date(text: str, local_now: datetime) -> date | None:
    today = local_now.date()
    if re.search(r"\btoday\b", text):
        return today
    if re.search(r"\btomorrow\b", text):
        return today + timedelta(days=1)
    if re.search(r"\bnext week\b", text):
        days = (7 - today.weekday()) % 7 or 7
        return today + timedelta(days=days)
    for weekday, index in WEEKDAYS.items():
        if re.search(rf"\b(next\s+)?{weekday}\b", text):
            days = (index - today.weekday()) % 7
            if re.search(rf"\bnext\s+{weekday}\b", text) and days == 0:
                days = 7
            return today + timedelta(days=days)
    return None


def _context_date(context: dict[str, Any], local_now: datetime) -> date:
    value = context.get("target_date")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return local_now.date()


def _context_title(context: dict[str, Any]) -> str | None:
    value = context.get("event_title") or context.get("search_title") or context.get("kind")
    return str(value) if value else None


def _clarification_title(message: str, context: dict[str, Any]) -> str | None:
    candidates = context.get("candidate_events") or ()
    words = set(_normalized_text(message).split()) - {"the", "one", "event", "at"}
    ranked = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        title = str(candidate.get("title") or "")
        overlap = words & set(_normalized_text(title).split())
        if overlap:
            ranked.append((len(overlap), title))
    ranked.sort(reverse=True)
    return ranked[0][1] if len(ranked) == 1 or (ranked and ranked[0][0] > ranked[1][0]) else None


def _manual_followup_time(
    message: str,
    target_date: date,
    local_now: datetime,
    *,
    awaiting: Any,
) -> datetime | None:
    if awaiting != "event_detail":
        return None
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", message.lower())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if meridiem is None and 1 <= hour <= 7:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return datetime.combine(target_date, time(hour, minute), tzinfo=local_now.tzinfo)


def _contains_time(message: str) -> bool:
    return bool(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", message))


def _looks_like_context_followup(message: str) -> bool:
    return bool(
        re.match(r"^(what time|when|where|which|what day|how long)\b", message)
        or message in {"where is it", "when is it", "what time is it"}
    )


def _asks_location(message: str) -> bool:
    return message.startswith("where") or "location" in message


def _asks_preparation(message: str) -> bool:
    return "wake up" in message or "early" in message or "prepare" in message or "leave" in message


def _is_affirmative(message: str) -> bool:
    return message in {"yes", "yes please", "yeah", "yep", "sure", "it is"}


def _is_negative(message: str) -> bool:
    return message in {"no", "nope", "nah", "it is not", "it isn't"}


def _normalized_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _subject_phrase(title: str | None) -> str:
    if not title or _normalized_text(title) in {"anything", "events", "event", "schedule"}:
        return "any matching events"
    article = "an" if title[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
    return f"{article} {title} event"


def _day_label(target_date: date, local_now: datetime) -> str:
    if target_date == local_now.date():
        return "today"
    if target_date == local_now.date() + timedelta(days=1):
        return "tomorrow"
    return f"on {target_date.strftime('%A, %b %-d')}"


def _format_time(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


calendar_chat_grounding_service = CalendarChatGroundingService()
