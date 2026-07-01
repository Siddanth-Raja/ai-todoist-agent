from datetime import datetime, timedelta
import json
import logging
import re
from typing import Any

import requests

from .calendar_intelligence import CalendarAnalysis, analyze_calendar_change
from .calendar_tools import (
    create_calendar_event,
    list_todays_events,
    list_upcoming_events,
    update_calendar_event,
)
from .config import get_settings
from .planner import build_plan, enrich_task
from .storage import list_memory_entries
from .todoist_tools import (
    LIFE_AREA_TO_TODOIST_SECTION,
    TODOIST_INBOX_PROJECT_NAME,
    create_many_tasks,
    create_many_subtasks,
    create_task,
    find_task_by_name,
    list_active_tasks,
    list_todoist_sections,
)


logger = logging.getLogger(__name__)
MODE = "ai_agent"
FALLBACK_MODE = "planning_deterministic_fallback"
READ_ONLY_NOTE = "No changes were made."
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TIMEOUT_SECONDS = 30
PROJECT_CATEGORIES = ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc"]
MEMORY_CONTEXT_TYPES = (
    "project",
    "person",
    "group",
    "rule",
    "preference",
    "pattern",
    "sensitive_habit",
)
MEMORY_TYPE_ALIASES = {
    "classification_rule": "rule",
    "sensitive_private_habit": "sensitive_habit",
}
MEMORY_ITEMS_PER_TYPE_LIMIT = 8
MEMORY_TEXT_LIMIT = 140
BEFORE_EVENT_LEAD_DAYS = 1
PERSONAL_CAPTURE_KEYWORDS = {
    "buy",
    "purchase",
    "order",
    "target",
    "grocery",
    "groceries",
    "shopping",
    "errand",
    "gym",
    "health",
    "doctor",
    "car",
    "oil change",
    "registration",
    "life admin",
    "water bottle",
    "socks",
    "grad",
    "graduation",
    "commencement",
    "speech",
}
CALENDAR_ONLY_EVENT_KEYWORDS = {
    "gym",
    "workout",
    "hangout",
    "hang out",
    "party",
    "parties",
    "meal",
    "lunch",
    "dinner",
    "breakfast",
    "brunch",
    "coffee",
    "birthday",
    "birthdays",
    "holiday",
    "holidays",
}
COLLEGE_CAPTURE_KEYWORDS = {
    "a&m",
    "a and m",
    "tamu",
    "blinn",
    "college",
    "class",
    "classes",
    "exam",
    "homework",
    "assignment",
    "transcript",
    "housing",
}
FREELANCE_CAPTURE_KEYWORDS = {
    "client",
    "clients",
    "outreach",
    "business",
    "law firm",
    "law firms",
    "dentist",
    "dentists",
    "realtor",
    "realtors",
    "website",
    "websites",
    "invoice",
    "proposal",
    "contract",
    "deliverable",
    "freelance",
}
XO_CAPTURE_KEYWORDS = {
    "xo",
    "vr",
    "headset",
    "prototype",
    "environment",
}
NEBULO_CAPTURE_KEYWORDS = {
    "nebulo",
    "agent",
    "context control",
}
WEEKDAY_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
ALLOWED_INTENTS = {
    "plan",
    "capture_task",
    "schedule_event",
    "replan",
    "reminder",
    "question",
    "unknown",
}
AFFIRMATIVE_CONFIRMATION_REPLIES = {
    "yes",
    "yes please",
    "yeah",
    "yep",
    "sure",
    "do it",
    "do that",
    "it is",
    "make it calendar",
    "sounds good",
    "add it",
    "confirm",
}
NEGATIVE_CONFIRMATION_REPLIES = {
    "no",
    "nope",
    "nah",
    "it is not",
    "it isn't",
}
PENDING_ACTION: dict[str, Any] | None = None
CONVERSATION_STATES: dict[str, dict[str, Any]] = {}
EXECUTABLE_PENDING_ACTION_TYPES = {
    "create_calendar_event",
    "create_many_todoist_tasks",
    "create_many_todoist_subtasks",
    "create_todoist_task",
    "create_todoist_subtask",
    "update_calendar_event",
}
CALENDAR_LOOKUP_TERMS = {
    "interview": ("interview", "recruiter", "hiring", "career", "phone screen"),
    "meeting": ("meeting", "meet", "sync", "call"),
    "appointment": ("appointment", "doctor", "dentist"),
    "party": ("party", "parties"),
    "gym": ("gym", "workout"),
    "class": ("class", "lecture", "seminar"),
}


def handle_chat(
    message: str,
    current_time: datetime | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    global PENDING_ACTION

    settings = get_settings()
    cleaned_message = message.strip()
    session_key = _session_key(session_id)
    conversation_state = _conversation_state(session_key)
    active_pending_action = PENDING_ACTION

    todoist_result = list_active_tasks(settings)
    calendar_result = list_todays_events(settings, now=current_time)
    upcoming_calendar_result = list_upcoming_events(settings, now=current_time)
    enabled_memories = _enabled_memory_entries()
    resolved_memory = _resolve_memory_context(cleaned_message, enabled_memories)
    errors = [
        error
        for error in (todoist_result.error, calendar_result.error, upcoming_calendar_result.error)
        if error is not None
    ]
    local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)

    plan = build_plan(
        tasks=todoist_result.tasks,
        calendar_events=calendar_result.events,
        message=cleaned_message,
        local_tz=settings.local_tz,
        now=current_time,
        calendar_available=calendar_result.error is None,
    )
    enriched_tasks = [
        enrich_task(task, local_now.date()) for task in todoist_result.tasks if task.get("content")
    ]

    if active_pending_action and _is_affirmative_confirmation(cleaned_message):
        decision = _decision_from_pending_action(active_pending_action)
        actions_taken, action_errors = _execute_allowed_action(
            settings=settings,
            decision=decision,
            tasks=enriched_tasks,
            calendar_events=upcoming_calendar_result.events or calendar_result.events,
            local_now=local_now,
        )
        errors.extend(action_errors)
        PENDING_ACTION = None
        answer = _answer_with_actions(decision, actions_taken, action_errors)
        return _with_conversation_state(session_key, {
            "answer": answer,
            "intent": decision["intent"],
            "actions_taken": actions_taken,
            "needs_confirmation": False,
            "confirmation_prompt": None,
            "pending_action": None,
            "free_block": plan["free_block"],
            "recommended_tasks": plan["recommended_tasks"],
            "calendar_events": _summarize_calendar_events(calendar_result.events),
            "mode": MODE,
            "errors": errors,
        })

    roadmap_response = _build_bulk_subtask_confirmation(
        message=cleaned_message,
        settings=settings,
        tasks=todoist_result.tasks,
        plan=plan,
        calendar_events=calendar_result.events,
        errors=errors,
        session_key=session_key,
    )
    if roadmap_response:
        return roadmap_response

    followup_response = _handle_conversation_followup(
        message=cleaned_message,
        state=conversation_state,
        plan=plan,
        calendar_events=upcoming_calendar_result.events or calendar_result.events,
        visible_calendar_events=calendar_result.events,
        local_now=local_now,
        errors=errors,
    )
    if followup_response:
        response, next_state = followup_response
        return _with_conversation_state(session_key, response, next_state)

    calendar_question_response = _handle_calendar_event_question(
        message=cleaned_message,
        plan=plan,
        calendar_events=upcoming_calendar_result.events or calendar_result.events,
        visible_calendar_events=calendar_result.events,
        local_now=local_now,
        errors=errors,
    )
    if calendar_question_response:
        response, next_state = calendar_question_response
        return _with_conversation_state(session_key, response, next_state)

    if not settings.openai_api_key:
        fallback = _fallback_response(
            plan=plan,
            todoist_error=todoist_result.error,
            calendar_error=calendar_result.error,
            task_count=len(todoist_result.tasks),
            calendar_events=calendar_result.events,
            errors=[*errors, "OPENAI_API_KEY is missing. Used deterministic planner fallback."],
        )
        return _with_conversation_state(session_key, fallback)

    context = _build_llm_context(
        message=cleaned_message,
        now=local_now,
        settings_timezone=settings.timezone,
        tasks=enriched_tasks,
        calendar_events=calendar_result.events,
        upcoming_calendar_events=upcoming_calendar_result.events or calendar_result.events,
        plan=plan,
        provider_errors=errors,
        pending_action=active_pending_action,
        memory_entries=enabled_memories,
        resolved_memory=resolved_memory,
    )
    decision, llm_error = _get_llm_decision(settings, context)
    if llm_error or decision is None:
        fallback = _fallback_response(
            plan=plan,
            todoist_error=todoist_result.error,
            calendar_error=calendar_result.error,
            task_count=len(todoist_result.tasks),
            calendar_events=calendar_result.events,
            errors=[*errors, llm_error or "OpenAI decision was empty. Used deterministic planner fallback."],
        )
        return _with_conversation_state(session_key, fallback)

    decision = _sanitize_decision(decision)
    decision = _apply_capture_override(cleaned_message, decision, local_now, enabled_memories)
    decision = _apply_memory_resolution(decision, resolved_memory)
    decision = _apply_calendar_update_override(
        cleaned_message,
        decision,
        upcoming_calendar_result.events or calendar_result.events,
        local_now,
    )
    decision = _apply_calendar_intelligence_confirmation(
        decision,
        upcoming_calendar_result.events or calendar_result.events,
        local_now,
    )
    if decision["needs_confirmation"]:
        PENDING_ACTION = decision["pending_action"]
    elif active_pending_action:
        PENDING_ACTION = None

    actions_taken, action_errors = _execute_allowed_action(
        settings=settings,
        decision=decision,
        tasks=enriched_tasks,
        calendar_events=upcoming_calendar_result.events or calendar_result.events,
        local_now=local_now,
    )
    errors.extend(action_errors)

    answer = _answer_with_actions(decision, actions_taken, action_errors)

    return _with_conversation_state(session_key, {
        "answer": answer,
        "intent": decision["intent"],
        "actions_taken": actions_taken,
        "needs_confirmation": decision["needs_confirmation"],
        "confirmation_prompt": decision["confirmation_prompt"],
        "pending_action": decision["pending_action"],
        "free_block": plan["free_block"],
        "recommended_tasks": plan["recommended_tasks"],
        "calendar_events": _summarize_calendar_events(calendar_result.events),
        "mode": MODE,
        "errors": errors,
    })


def confirm_pending_action(
    pending_action: dict[str, Any],
    current_time: datetime | None = None,
) -> dict[str, Any]:
    global PENDING_ACTION

    if not is_executable_pending_action(pending_action):
        raise ValueError("Pending action is not executable.")

    settings = get_settings()
    todoist_result = list_active_tasks(settings)
    calendar_result = list_todays_events(settings, now=current_time)
    upcoming_calendar_result = list_upcoming_events(settings, now=current_time)
    errors = [
        error
        for error in (todoist_result.error, calendar_result.error, upcoming_calendar_result.error)
        if error is not None
    ]
    local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)
    plan = build_plan(
        tasks=todoist_result.tasks,
        calendar_events=calendar_result.events,
        message="",
        local_tz=settings.local_tz,
        now=current_time,
        calendar_available=calendar_result.error is None,
    )
    enriched_tasks = [
        enrich_task(task, local_now.date()) for task in todoist_result.tasks if task.get("content")
    ]

    decision = _decision_from_pending_action(pending_action)
    actions_taken, action_errors = _execute_allowed_action(
        settings=settings,
        decision=decision,
        tasks=enriched_tasks,
        calendar_events=upcoming_calendar_result.events or calendar_result.events,
        local_now=local_now,
    )
    errors.extend(action_errors)
    PENDING_ACTION = None
    answer = _answer_with_actions(decision, actions_taken, action_errors)

    return {
        "answer": answer,
        "intent": decision["intent"],
        "actions_taken": actions_taken,
        "needs_confirmation": False,
        "confirmation_prompt": None,
        "pending_action": None,
        "free_block": plan["free_block"],
        "recommended_tasks": plan["recommended_tasks"],
        "calendar_events": _summarize_calendar_events(calendar_result.events),
        "mode": MODE,
        "errors": errors,
    }


def _session_key(session_id: str | None) -> str:
    return str(session_id or "default").strip() or "default"


def _conversation_state(session_key: str) -> dict[str, Any]:
    state = CONVERSATION_STATES.get(session_key)
    if isinstance(state, dict):
        return {
            "last_question": state.get("last_question"),
            "awaiting": state.get("awaiting"),
            "context": state.get("context") if isinstance(state.get("context"), dict) else {},
        }
    return {"last_question": None, "awaiting": None, "context": {}}


def _with_conversation_state(
    session_key: str,
    response: dict[str, Any],
    next_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = next_state if next_state is not None else _state_from_response(response)
    CONVERSATION_STATES[session_key] = state
    response["conversation_state"] = state
    return response


def _state_from_response(response: dict[str, Any]) -> dict[str, Any]:
    last_question = _last_question(response.get("confirmation_prompt") or response.get("answer"))
    if response.get("needs_confirmation"):
        return {
            "last_question": last_question,
            "awaiting": "action_confirmation",
            "context": {"pending_action": response.get("pending_action")},
        }
    return {
        "last_question": last_question,
        "awaiting": None,
        "context": {},
    }


def _last_question(text: Any) -> str | None:
    if not isinstance(text, str) or "?" not in text:
        return None
    matches = re.findall(r"([^?]*\?)", text)
    if not matches:
        return None
    return matches[-1].strip()


def _handle_calendar_event_question(
    *,
    message: str,
    plan: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    visible_calendar_events: list[dict[str, Any]],
    local_now: datetime,
    errors: list[str | dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    lookup = _calendar_lookup_request(message, local_now)
    if not lookup:
        return None

    return _calendar_lookup_result(
        lookup=lookup,
        plan=plan,
        calendar_events=calendar_events,
        visible_calendar_events=visible_calendar_events,
        local_now=local_now,
        errors=errors,
    )


def _handle_conversation_followup(
    *,
    message: str,
    state: dict[str, Any],
    plan: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    visible_calendar_events: list[dict[str, Any]],
    local_now: datetime,
    errors: list[str | dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    awaiting = state.get("awaiting")
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    if awaiting == "calendar_lookup_confirmation":
        if _is_affirmative_confirmation(message):
            return _calendar_lookup_followup(
                context=context,
                plan=plan,
                calendar_events=calendar_events,
                visible_calendar_events=visible_calendar_events,
                local_now=local_now,
                errors=errors,
            )
        if _is_negative_confirmation(message):
            answer = "What time is the interview?"
            next_state = {
                "last_question": answer,
                "awaiting": "event_detail",
                "context": context,
            }
            return (
                _conversation_answer(
                    answer=answer,
                    intent="question",
                    plan=plan,
                    calendar_events=visible_calendar_events,
                    errors=errors,
                ),
                next_state,
            )

    if awaiting == "event_detail":
        event_time = _extract_followup_time(message, local_now, context)
        if event_time:
            answer = _answer_interview_wakeup_from_time(event_time)
            next_state = {"last_question": None, "awaiting": None, "context": {}}
            return (
                _conversation_answer(
                    answer=answer,
                    intent="question",
                    plan=plan,
                    calendar_events=visible_calendar_events,
                    errors=errors,
                ),
                next_state,
            )

    return None


def _calendar_lookup_followup(
    *,
    context: dict[str, Any],
    plan: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    visible_calendar_events: list[dict[str, Any]],
    local_now: datetime,
    errors: list[str | dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    lookup = {
        "kind": str(context.get("kind") or context.get("topic") or "event"),
        "target_date": _date_from_context(context, local_now),
        "search_terms": tuple(context.get("search_terms") or ()),
        "is_interview_wakeup": bool(context.get("is_interview_wakeup")),
    }
    return _calendar_lookup_result(
        lookup=lookup,
        plan=plan,
        calendar_events=calendar_events,
        visible_calendar_events=visible_calendar_events,
        local_now=local_now,
        errors=errors,
    )


def _calendar_lookup_result(
    *,
    lookup: dict[str, Any],
    plan: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    visible_calendar_events: list[dict[str, Any]],
    local_now: datetime,
    errors: list[str | dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    target_date = lookup["target_date"]
    kind = str(lookup.get("kind") or "event")
    matches = _calendar_events_for_date_matching(
        calendar_events,
        target_date,
        tuple(lookup.get("search_terms") or (kind,)),
    )
    if matches:
        if len(matches) > 1:
            answer = _multiple_calendar_matches_answer(kind, target_date, matches, local_now)
            next_state = {
                "last_question": "Which one do you mean?",
                "awaiting": "event_detail",
                "context": _calendar_lookup_context(lookup),
            }
            return (
                _conversation_answer(
                    answer=answer,
                    intent="question",
                    plan=plan,
                    calendar_events=visible_calendar_events,
                    errors=errors,
                ),
                next_state,
            )

        answer = _answer_calendar_event_lookup(matches[0], lookup, local_now)
        next_state = {"last_question": None, "awaiting": None, "context": {}}
        return (
            _conversation_answer(
                answer=answer,
                intent="question",
                plan=plan,
                calendar_events=visible_calendar_events,
                errors=errors,
            ),
            next_state,
        )

    day_label = _day_context_label(target_date, local_now)
    answer = f"I could not find {_event_kind_phrase(kind)} {day_label}. What time is it?"
    next_state = {
        "last_question": "What time is it?",
        "awaiting": "event_detail",
        "context": _calendar_lookup_context(lookup),
    }
    return (
        _conversation_answer(
            answer=answer,
            intent="question",
            plan=plan,
            calendar_events=visible_calendar_events,
            errors=errors,
        ),
        next_state,
    )


def _conversation_answer(
    *,
    answer: str,
    intent: str,
    plan: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    errors: list[str | dict[str, Any]],
) -> dict[str, Any]:
    return {
        "answer": answer,
        "intent": intent,
        "actions_taken": [],
        "needs_confirmation": False,
        "confirmation_prompt": None,
        "pending_action": None,
        "free_block": plan["free_block"],
        "recommended_tasks": plan["recommended_tasks"],
        "calendar_events": _summarize_calendar_events(calendar_events),
        "mode": MODE,
        "errors": errors,
    }


def _looks_like_interview_wakeup_question(message: str) -> bool:
    text = message.lower()
    return "interview" in text and "tomorrow" in text and ("wake up" in text or "early" in text)


def _calendar_lookup_request(message: str, local_now: datetime) -> dict[str, Any] | None:
    text = message.lower()
    if _looks_like_calendar_write_request(text):
        return None
    if "missed" in text or "what should" in text:
        return None

    kind = next((name for name, terms in CALENDAR_LOOKUP_TERMS.items() if any(term in text for term in terms)), None)
    if not kind:
        return None

    asks_calendar_question = (
        "?" in message
        or "what time" in text
        or "when" in text
        or "do i need" in text
        or "do i have" in text
        or "is there" in text
        or "wake up" in text
        or "early" in text
    )
    asks_for_event_details = (
        "what time" in text
        or "when" in text
        or "do i need" in text
        or "do i have" in text
        or "is there" in text
        or "wake up" in text
        or "early" in text
    )
    if not asks_calendar_question or not asks_for_event_details:
        return None

    target_date = _extract_temporal_date(message, local_now) or local_now.date()
    return {
        "kind": kind,
        "target_date": target_date,
        "search_terms": CALENDAR_LOOKUP_TERMS[kind],
        "is_interview_wakeup": kind == "interview" and ("wake up" in text or "early" in text),
    }


def _looks_like_calendar_write_request(text: str) -> bool:
    return any(
        text.startswith(prefix)
        for prefix in (
            "add ",
            "create ",
            "schedule ",
            "move ",
            "reschedule ",
            "put ",
            "book ",
        )
    )


def _calendar_lookup_context(lookup: dict[str, Any]) -> dict[str, Any]:
    target_date = lookup.get("target_date")
    return {
        "topic": "calendar_event_lookup",
        "kind": lookup.get("kind"),
        "target_date": target_date.isoformat() if hasattr(target_date, "isoformat") else target_date,
        "search_terms": list(lookup.get("search_terms") or []),
        "is_interview_wakeup": bool(lookup.get("is_interview_wakeup")),
    }


def _calendar_events_for_date_matching(
    events: list[dict[str, Any]],
    target_date,
    search_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    matches = []
    for event in _events_on_date(events, target_date):
        text = " ".join(
            [
                str(event.get("title") or ""),
                str(event.get("description") or ""),
                str(event.get("location") or ""),
            ]
        ).lower()
        if any(term in text for term in search_terms):
            matches.append(event)
    matches.sort(key=lambda event: str(event.get("start") or ""))
    return matches


def _answer_calendar_event_lookup(
    event: dict[str, Any],
    lookup: dict[str, Any],
    local_now: datetime,
) -> str:
    if lookup.get("kind") == "interview":
        return _answer_interview_lookup_from_event(event, local_now)
    return _answer_generic_calendar_lookup(event, lookup, local_now)


def _answer_interview_lookup_from_event(event: dict[str, Any], local_now: datetime) -> str:
    start = _parse_followup_event_datetime(event.get("start"))
    title = str(event.get("title") or "your interview")
    if not start:
        return f"I found {title} on your calendar, but I could not read the start time."
    return _answer_interview_wakeup(title, start, _parse_followup_event_datetime(event.get("end")), event, local_now)


def _answer_interview_wakeup_from_time(start: datetime) -> str:
    return _answer_interview_wakeup("your interview", start, None, {}, None)


def _answer_interview_wakeup(
    title: str,
    start: datetime,
    end: datetime | None,
    event: dict[str, Any],
    local_now: datetime | None,
) -> str:
    time_text = _format_followup_time(start)
    end_text = f" - {_format_followup_time(end)}" if end else ""
    day_context = _event_day_context(start, local_now)
    title_phrase = _possessive_event_title(title)
    wake_time = start - timedelta(hours=3)
    ready_time = start - timedelta(minutes=90)
    location = str(event.get("location") or "").strip()
    if location:
        leave_time = start - timedelta(minutes=45)
        location_text = f" Since it is at {location}, I would leave around {_format_followup_time(leave_time)}."
    else:
        location_text = " I do not see a location, so use a safe buffer for travel or setup."

    if start.hour < 10:
        return (
            f"{title_phrase} is {day_context} at {time_text}{end_text}. "
            f"Yes, I would wake up by around {_format_followup_time(wake_time)} so you have time to eat, "
            f"get ready around {_format_followup_time(ready_time)}, and leave with buffer.{location_text}"
        )
    return (
        f"{title_phrase} is {day_context} at {time_text}{end_text}. "
        f"You probably don't need to wake up extremely early, but I'd wake up by around "
        f"{_format_followup_time(wake_time)} so you have time to eat, start getting ready around "
        f"{_format_followup_time(ready_time)}, and leave with buffer."
        f"{location_text}"
    )


def _possessive_event_title(title: str) -> str:
    clean_title = title.strip()
    if clean_title.lower().startswith("your "):
        return clean_title[:1].upper() + clean_title[1:]
    return f"Your {clean_title}"


def _answer_generic_calendar_lookup(
    event: dict[str, Any],
    lookup: dict[str, Any],
    local_now: datetime,
) -> str:
    title = str(event.get("title") or "your event")
    start = _parse_followup_event_datetime(event.get("start"))
    end = _parse_followup_event_datetime(event.get("end"))
    if not start:
        return f"I found {title} on your calendar, but I could not read the start time."

    end_text = f" - {_format_followup_time(end)}" if end else ""
    kind = str(lookup.get("kind") or "event")
    return (
        f"Your {title} is {_event_day_context(start, local_now)} at {_format_followup_time(start)}{end_text}. "
        f"Practical recommendation: give yourself a buffer before the {kind} so you are not rushing."
    )


def _multiple_calendar_matches_answer(
    kind: str,
    target_date,
    matches: list[dict[str, Any]],
    local_now: datetime,
) -> str:
    day_label = _day_context_label(target_date, local_now)
    items = []
    for event in matches:
        title = str(event.get("title") or "Untitled event")
        start = _parse_followup_event_datetime(event.get("start"))
        end = _parse_followup_event_datetime(event.get("end"))
        if start and end:
            items.append(f"{title} ({_format_followup_time(start)} - {_format_followup_time(end)})")
        elif start:
            items.append(f"{title} ({_format_followup_time(start)})")
        else:
            items.append(title)
    return f"I found multiple {kind} events {day_label}: {', '.join(items)}. Which one do you mean?"


def _event_day_context(start: datetime, local_now: datetime | None) -> str:
    if not local_now:
        return "scheduled"
    day_label = _day_context_label(start.date(), local_now)
    time_until = _format_time_until(start, local_now)
    return f"{day_label}{f' ({time_until})' if time_until else ''}"


def _day_context_label(target_date, local_now: datetime) -> str:
    if target_date == local_now.date():
        return "today"
    if target_date == (local_now.date() + timedelta(days=1)):
        return "tomorrow"
    return f"on {target_date.strftime('%A, %b %-d')}"


def _event_kind_phrase(kind: str) -> str:
    article = "an" if kind[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
    return f"{article} {kind}"


def _format_time_until(start: datetime, local_now: datetime) -> str:
    delta_minutes = int((start - local_now).total_seconds() // 60)
    if delta_minutes < 0:
        return ""
    if delta_minutes < 60:
        return f"in {delta_minutes} minutes"
    hours = delta_minutes // 60
    minutes = delta_minutes % 60
    if hours < 24:
        return f"in about {hours} hour{'s' if hours != 1 else ''}{f' {minutes} minutes' if minutes else ''}"
    days = hours // 24
    remaining_hours = hours % 24
    return f"in about {days} day{'s' if days != 1 else ''}{f' {remaining_hours} hours' if remaining_hours else ''}"


def _date_from_context(context: dict[str, Any], local_now: datetime):
    value = context.get("target_date")
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(f"{value}T00:00:00").date()
        except ValueError:
            pass
    return local_now.date() + timedelta(days=1)


def _extract_followup_time(
    message: str,
    local_now: datetime,
    context: dict[str, Any],
) -> datetime | None:
    target_date = _date_from_context(context, local_now)
    text = message.lower().strip()
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text)
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
    return datetime.combine(target_date, datetime.min.time(), tzinfo=local_now.tzinfo).replace(
        hour=hour,
        minute=minute,
    )


def _format_followup_time(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _parse_followup_event_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_negative_confirmation(message: str) -> bool:
    normalized = re.sub(r"[^a-z\s]", "", message.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in NEGATIVE_CONFIRMATION_REPLIES


def is_executable_pending_action(pending_action: dict[str, Any] | None) -> bool:
    if not isinstance(pending_action, dict):
        return False

    action_type = pending_action.get("action_type") or pending_action.get("type")
    if action_type not in EXECUTABLE_PENDING_ACTION_TYPES:
        return False

    if action_type == "update_calendar_event":
        details = pending_action.get("details") if isinstance(pending_action.get("details"), dict) else {}
        return _calendar_update_details(details) is not None

    if action_type == "create_many_todoist_subtasks":
        details = pending_action.get("details") if isinstance(pending_action.get("details"), dict) else {}
        parent_id = str(details.get("parent_task_id") or "").strip()
        tasks = details.get("tasks")
        return bool(parent_id and isinstance(tasks, list) and tasks)

    return True


def _build_bulk_subtask_confirmation(
    *,
    message: str,
    settings,
    tasks: list[dict[str, Any]],
    plan: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    errors: list[str],
    session_key: str,
) -> dict[str, Any] | None:
    global PENDING_ACTION

    parsed, parse_reason, parse_attempted = _parse_bulk_subtask_request(message)
    logger.info(
        "roadmap_subtask_parser attempted=%s success=%s reason=%s selected_action=%s",
        parse_attempted,
        parsed is not None,
        parse_reason,
        "pending" if parsed else "fallback",
    )
    if not parsed:
        if parse_attempted and parse_reason != "no_numbered_or_bulleted_items_found":
            clarification = (
                "I found multiple roadmap items. Which parent Todoist task should I put these under?"
            )
            logger.info(
                "roadmap_subtask_parser attempted=%s success=%s reason=%s selected_action=%s",
                parse_attempted,
                False,
                parse_reason,
                "clarify_parent_task",
            )
            return _with_conversation_state(session_key, {
                "answer": clarification,
                "intent": "capture_task",
                "actions_taken": [],
                "needs_confirmation": False,
                "confirmation_prompt": None,
                "pending_action": None,
                "free_block": plan["free_block"],
                "recommended_tasks": plan["recommended_tasks"],
                "calendar_events": _summarize_calendar_events(calendar_events),
                "mode": MODE,
                "errors": errors,
            })
        return None

    section_name = parsed["section_name"]
    parent_title = parsed["parent_task_title"]
    parent_task = find_task_by_name(settings, parent_title, section_name=section_name)
    if parent_task and not section_name:
        section_name = parent_task.get("todoist_section_name") or parent_task.get("section_name")
    if not parent_task:
        logger.info(
            "roadmap_subtask_parser attempted=%s success=%s reason=%s section=%s parent=%s selected_action=%s",
            parse_attempted,
            True,
            "parent_task_not_found",
            section_name,
            parent_title,
            "create_todoist_task",
        )
        pending_action = {
            "type": "create_todoist_task",
            "action_type": "create_todoist_task",
            "intent": "capture_task",
            "confirmation_prompt": _missing_parent_prompt(parent_title, section_name),
            "resolved_project": section_name if section_name in PROJECT_CATEGORIES else None,
            "task": {
                "content": parent_title,
                "project_category": section_name if section_name in PROJECT_CATEGORIES else None,
                "due_string": None,
                "due_date": None,
                "labels": [],
                "priority": 4,
                "project_name": TODOIST_INBOX_PROJECT_NAME,
                "section_name": section_name,
                "todoist_section_name": section_name,
            },
            "details": {
                "project_name": TODOIST_INBOX_PROJECT_NAME,
                "section_name": section_name,
                "parent_task_title": parent_title,
            },
        }
        PENDING_ACTION = pending_action
        return _with_conversation_state(session_key, {
            "answer": _missing_parent_prompt(parent_title, section_name),
            "intent": "capture_task",
            "actions_taken": [],
            "needs_confirmation": True,
            "confirmation_prompt": pending_action["confirmation_prompt"],
            "pending_action": pending_action,
            "free_block": plan["free_block"],
            "recommended_tasks": plan["recommended_tasks"],
            "calendar_events": _summarize_calendar_events(calendar_events),
            "mode": MODE,
            "errors": errors,
        })

    requested_tasks = parsed["tasks"]
    existing_titles = {
        _normalize_text(task.get("content"))
        for task in tasks
        if str(task.get("parent_id") or "") == str(parent_task.get("id") or "")
    }
    preview_tasks = [
        {"content": item["content"], "priority": item.get("priority", 3)}
        for item in requested_tasks
    ]
    duplicate_count = sum(1 for item in preview_tasks if _normalize_text(item["content"]) in existing_titles)
    task_count = len(preview_tasks)
    large_batch_warning = " This is a large batch, so please review it carefully." if task_count > 20 else ""
    duplicate_note = f" I found {duplicate_count} duplicate title(s) that will be skipped." if duplicate_count else ""
    confirmation_prompt = (
        _bulk_subtask_confirmation_prompt(task_count, parent_title, section_name)
        + large_batch_warning
        + duplicate_note
    )
    logger.info(
        "roadmap_subtask_parser attempted=%s success=%s reason=%s section=%s parent=%s task_count=%s selected_action=%s",
        parse_attempted,
        True,
        "bulk_subtask_confirmation_ready",
        section_name,
        parent_title,
        task_count,
        "create_many_todoist_subtasks",
    )
    pending_action = {
        "type": "create_many_todoist_subtasks",
        "action_type": "create_many_todoist_subtasks",
        "intent": "capture_task",
        "confirmation_prompt": confirmation_prompt,
        "resolved_project": section_name if section_name in PROJECT_CATEGORIES else None,
        "details": {
            "project_name": TODOIST_INBOX_PROJECT_NAME,
            "section_name": section_name,
            "parent_task_title": parent_title,
            "parent_task_id": parent_task.get("id"),
            "tasks": preview_tasks,
        },
    }
    PENDING_ACTION = pending_action
    return _with_conversation_state(session_key, {
        "answer": confirmation_prompt,
        "intent": "capture_task",
        "actions_taken": [],
        "needs_confirmation": True,
        "confirmation_prompt": confirmation_prompt,
        "pending_action": pending_action,
        "free_block": plan["free_block"],
        "recommended_tasks": plan["recommended_tasks"],
        "calendar_events": _summarize_calendar_events(calendar_events),
        "mode": MODE,
        "errors": errors,
    })


def _parse_bulk_subtask_request(message: str) -> tuple[dict[str, Any] | None, str, bool]:
    bullet_tasks = _extract_roadmap_items(message)
    multiple_items_detected = len(bullet_tasks) > 1
    parse_attempted = multiple_items_detected or bool(
        re.search(r"\b(roadmap|subtasks?|under|inside|for|break this into)\b", message, flags=re.IGNORECASE)
        or re.search(r"(?:->|→|/)", message)
    )

    if not multiple_items_detected:
        return None, "no_numbered_or_bulleted_items_found", parse_attempted

    header = _roadmap_header(message)
    section_name, parent_title, reason = _extract_roadmap_target(header)
    if not parent_title:
        return None, reason, True

    return {
        "project_name": TODOIST_INBOX_PROJECT_NAME,
        "section_name": section_name,
        "parent_task_title": parent_title,
        "tasks": bullet_tasks,
    }, "parsed", True


def _extract_roadmap_items(message: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for line in message.splitlines():
        content = _roadmap_item_content(line)
        if content:
            tasks.append({"content": content, "priority": 3})
    return tasks


def _roadmap_item_content(line: str) -> str | None:
    match = re.match(
        r"^\s*(?:[-*+]\s+\[[ xX]\]|[-*+]|\d+[.)]|\uFFFC)\s*(.+?)\s*$",
        line,
    )
    if not match:
        return None
    content = re.sub(r"\s+", " ", match.group(1).strip())
    return content or None


def _roadmap_header(message: str) -> str:
    return "\n".join(line for line in message.splitlines() if not _roadmap_item_content(line)).strip()


def _extract_roadmap_target(header: str) -> tuple[str | None, str | None, str]:
    cleaned_header = _clean_roadmap_target(header)
    if not cleaned_header:
        return None, None, "header_missing_parent_context"

    arrow_target = re.search(
        r"(?:under|inside|in|for)?\s*(?P<section>[A-Za-z0-9& _-]+?)\s*(?:->|→|/)\s*(?P<parent>[^:\n]+)",
        cleaned_header,
        flags=re.IGNORECASE,
    )
    if arrow_target:
        section_name = _clean_route_part(arrow_target.group("section"))
        parent_title = _clean_route_part(arrow_target.group("parent"))
        return section_name, parent_title, "parsed_route_with_section"

    phrase_target = re.search(
        r"\b(?:under|inside|in|for)\s+(?P<target>[^:\n]+)",
        cleaned_header,
        flags=re.IGNORECASE,
    )
    if phrase_target:
        target = _clean_roadmap_target(phrase_target.group("target"))
        section_name, parent_title = _split_section_parent_from_target(target)
        return section_name, parent_title, "parsed_phrase_target"

    roadmap_target = re.search(
        r"\broadmap\s*(?:for)?\s+(?P<target>[^:\n]+)",
        cleaned_header,
        flags=re.IGNORECASE,
    )
    if roadmap_target:
        target = _clean_roadmap_target(roadmap_target.group("target"))
        section_name, parent_title = _split_section_parent_from_target(target)
        return section_name, parent_title, "parsed_roadmap_target"

    return None, None, "parent_task_not_detected"


def _split_section_parent_from_target(target: str) -> tuple[str | None, str | None]:
    route_match = re.search(r"(?P<section>.+?)\s*(?:->|→|/)\s*(?P<parent>.+)", target)
    if route_match:
        return (
            _clean_route_part(route_match.group("section")),
            _clean_route_part(route_match.group("parent")),
        )

    return None, _clean_roadmap_target(target)


def _clean_roadmap_target(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = re.sub(
        r"\b(?:as\s+subtasks?|subtasks?|tasks?|roadmap|these|this|create|add|put|break\s+this\s+into)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip(" :-\t")


def _clean_route_part(value: Any) -> str:
    text = _clean_roadmap_target(value)
    text = re.sub(r"\b(?:under|inside|in|for|here'?s|the|take|and|it)\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" :-\t")


def _bulk_subtask_confirmation_prompt(task_count: int, parent_title: str, section_name: str | None) -> str:
    location = f" under {section_name}" if section_name else ""
    return f"I found {task_count} subtasks for {parent_title}{location}. Create them?"


def _missing_parent_prompt(parent_title: str, section_name: str | None) -> str:
    location = f" in {section_name}" if section_name else ""
    return f"I could not find '{parent_title}'{location}. Create that parent task first?"


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _fallback_response(
    plan: dict[str, Any],
    todoist_error: str | None,
    calendar_error: str | None,
    task_count: int,
    calendar_events: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "answer": _build_answer(
            plan=plan,
            todoist_error=todoist_error,
            calendar_error=calendar_error,
            task_count=task_count,
        ),
        "intent": "plan",
        "actions_taken": [],
        "needs_confirmation": False,
        "confirmation_prompt": None,
        "pending_action": None,
        "free_block": plan["free_block"],
        "recommended_tasks": plan["recommended_tasks"],
        "calendar_events": _summarize_calendar_events(calendar_events),
        "mode": FALLBACK_MODE,
        "errors": errors,
    }


def _build_llm_context(
    message: str,
    now: datetime,
    settings_timezone: str,
    tasks: list[dict[str, Any]],
    calendar_events: list[dict[str, Any]],
    upcoming_calendar_events: list[dict[str, Any]],
    plan: dict[str, Any],
    provider_errors: list[str],
    pending_action: dict[str, Any] | None,
    memory_entries: list[dict[str, Any]],
    resolved_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    memory_context = _build_memory_context(memory_entries, message)
    if resolved_memory:
        memory_context["resolved_context"] = resolved_memory
    return {
        "user_message": message,
        "current_datetime": now.isoformat(),
        "timezone": settings_timezone,
        "project_categories": PROJECT_CATEGORIES,
        "memory_context": memory_context,
        "todoist_tasks": _compact_tasks(tasks),
        "calendar_events_today": _summarize_calendar_events(
            _events_on_date(calendar_events, now.date())
        ),
        "calendar_events_for_requested_date": _summarize_calendar_events(
            _events_for_message_target_date(message, upcoming_calendar_events, now)
        ),
        "free_block": plan["free_block"],
        "deterministic_recommendations": plan["recommended_tasks"],
        "provider_errors": provider_errors,
        "pending_action": pending_action,
        "safety_rules": {
            "allowed_automatic_actions": [
                "none: answer only; use for planning, replanning, reminders that need confirmation, questions, and unknown requests",
                "create_todoist_task: create one simple Todoist task only when the user explicitly asks to capture/create/add a task",
                "create_todoist_subtask: create one Todoist subtask under an existing parent task; requires confirmation",
                "create_many_todoist_tasks: create multiple Todoist tasks; always requires confirmation",
                "create_many_todoist_subtasks: create multiple Todoist subtasks under an existing parent task; always requires confirmation",
                "create_calendar_event: create one simple Google Calendar event only when the user explicitly asks to schedule an event and no busy conflict exists",
                "update_calendar_event: update one existing Google Calendar event only after explicit confirmation of event_id, old time, and new time",
            ],
            "not_allowed_automatic_actions": [
                "delete tasks",
                "delete events",
                "move fixed calendar events",
                "cancel meetings",
                "send emails",
                "invite attendees",
                "mark tasks complete unless explicitly requested",
            ],
            "confirmation_rules": [
                "If the answer asks the user to choose, approve, confirm, or decide before an action can happen, set needs_confirmation=true.",
                "When needs_confirmation=true, set confirmation_prompt to the exact decision requested.",
                "For supported task or calendar create actions that only need approval, keep action_type and the task/calendar fields populated so the backend can execute after a yes reply.",
                "Bulk task creation always needs confirmation. Include the parent task and task list in pending_action.details for create_many_todoist_subtasks.",
                "When a reschedule is specific and executable, include pending_action.type='update_calendar_event' with event_id, title, old_start, old_end, new_start, and new_end.",
                "When a calendar conflict or reschedule choice needs a decision but is not yet executable, include pending_action.type='resolve_calendar_conflict'.",
                "If pending_action is present in context, interpret the next user message as an attempt to resolve it.",
            ],
            "routing_rules": [
                "Clear task-capture requests like 'I need to buy a new water bottle from Target' must be intent=capture_task and action_type=create_todoist_task.",
                "Use memory_context.memory_hints first when it maps names or topics to a project/context.",
                "Brandon maps to Nebulo. Ashwin and Charlie map to XO. Nikhil, Andy, and Kamden are A&M roommate context. Sam, Jai, and Krrish are Carrollton house / UTD group context.",
                "Shopping, errands, personal purchases, gym/health, car, and life admin tasks belong in Personal.",
                "Use Misc only when no better category fits.",
                "Do not give planning advice for a clear capture request.",
            ],
            "calendar_conflict_rules": [
                "When scheduling a new event, check conflicts only against calendar_events_for_requested_date.",
                "Do not treat events from a different date as conflicts for the requested date.",
                "For calendar conflict flows, identify the conflicting event, include its event_id when proposing a move, and propose the exact new start/end time before asking for confirmation.",
                "Important project/work commitments should be both calendar events and Todoist tasks unless they are gym, social hangouts, parties, casual meals, birthdays, holidays, or purely personal/social events.",
            ],
            "tool_boundary": "The model must not call external APIs. It returns a structured decision only; backend tools execute allowed actions.",
        },
    }


def _enabled_memory_entries() -> list[dict[str, Any]]:
    return [memory for memory in list_memory_entries() if memory.get("enabled")]


def _build_memory_context(
    memory_entries: list[dict[str, Any]],
    message: str,
) -> dict[str, Any]:
    grouped = {memory_type: [] for memory_type in MEMORY_CONTEXT_TYPES}
    for memory in memory_entries:
        if not memory.get("enabled"):
            continue

        memory_type = _normalized_memory_type(str(memory.get("type") or ""))
        if memory_type not in grouped:
            continue

        if len(grouped[memory_type]) >= MEMORY_ITEMS_PER_TYPE_LIMIT:
            continue

        title = _compact_memory_text(str(memory.get("title") or ""))
        content = _compact_memory_text(str(memory.get("content") or ""))
        if not title and not content:
            continue

        grouped[memory_type].append(
            {
                "title": title,
                "content": content,
            }
        )

    return {
        "entries_by_type": grouped,
        "memory_hints": _memory_hints_for_message(memory_entries, message),
    }


def _normalized_memory_type(memory_type: str) -> str:
    normalized = memory_type.strip().lower()
    return MEMORY_TYPE_ALIASES.get(normalized, normalized)


def _compact_memory_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= MEMORY_TEXT_LIMIT:
        return text
    return f"{text[: MEMORY_TEXT_LIMIT - 3].rstrip()}..."


def _memory_hints_for_message(
    memory_entries: list[dict[str, Any]],
    message: str,
) -> list[dict[str, str]]:
    text = message.lower()
    hints: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for memory in memory_entries:
        if not memory.get("enabled"):
            continue

        memory_type = _normalized_memory_type(str(memory.get("type") or ""))
        if memory_type not in {"person", "group", "project", "rule"}:
            continue

        title = str(memory.get("title") or "").strip()
        content = str(memory.get("content") or "").strip()
        if not title or title.lower() not in text:
            continue

        category = _category_from_memory_text(f"{title} {content}")
        context = _context_from_memory_text(title, content, category)
        key = (title.lower(), context.lower())
        if key in seen:
            continue
        seen.add(key)

        hint = {
            "match": title,
            "type": memory_type,
            "context": context,
        }
        if category:
            hint["project_category"] = category
        hints.append(hint)

    if re.search(r"\b(shopping|errand|errands|target|buy|purchase|order)\b", text):
        hints.append(
            {
                "match": "shopping/errand",
                "type": "rule",
                "context": "Shopping and errands go to Personal.",
                "project_category": "Personal",
            }
        )

    return hints[:12]


def _resolve_memory_context(
    message: str,
    memory_entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    matches: list[dict[str, str]] = []
    category_scores: dict[str, int] = {}
    category_contexts: dict[str, list[str]] = {}

    for memory in memory_entries:
        if not memory.get("enabled"):
            continue

        memory_type = _normalized_memory_type(str(memory.get("type") or ""))
        if memory_type not in {"project", "person", "group"}:
            continue

        title = str(memory.get("title") or "").strip()
        content = str(memory.get("content") or "").strip()
        mentioned = _mentioned_memory_terms(message, title, content, memory_type)
        if not mentioned:
            continue

        category = _category_from_memory_text(f"{title} {content}")
        if not category and memory_type == "project" and title in PROJECT_CATEGORIES:
            category = title
        if not category:
            continue

        context = _context_from_memory_text(title, content, category)
        weight = 3 if memory_type == "project" else 2 if memory_type == "person" else 1
        category_scores[category] = category_scores.get(category, 0) + weight + len(mentioned)
        category_contexts.setdefault(category, []).append(context)
        matches.append(
            {
                "title": title,
                "type": memory_type,
                "matched_terms": ", ".join(mentioned),
                "project_category": category,
                "context": context,
            }
        )

    if not matches:
        return None

    project = max(category_scores, key=lambda category: category_scores[category])
    return {
        "resolved_project": project,
        "context": category_contexts[project][0],
        "matches": [match for match in matches if match.get("project_category") == project][:6],
    }


def _mentioned_memory_terms(
    message: str,
    title: str,
    content: str,
    memory_type: str,
) -> list[str]:
    terms = [title]
    if memory_type == "group":
        terms.extend(re.split(r"[,/&]|\band\b", content, flags=re.IGNORECASE))

    seen: set[str] = set()
    mentioned: list[str] = []
    for raw_term in terms:
        term = re.sub(r"\s+", " ", raw_term).strip(" .,:;-")
        if len(term) < 2:
            continue
        normalized = term.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if _message_mentions_term(message, term):
            mentioned.append(term)

    return mentioned


def _message_mentions_term(message: str, term: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])"
    return re.search(pattern, message.lower()) is not None


def _category_from_memory_text(text: str) -> str | None:
    lowered = text.lower()
    if "nebulo" in lowered or "context control" in lowered or "context-control" in lowered:
        return "Nebulo"
    if "xo" in lowered or "vr" in lowered or "headset" in lowered:
        return "XO"
    if "a&m" in lowered or "tamu" in lowered or "blinn" in lowered or "roommate" in lowered:
        return "A&M"
    if "freelance" in lowered or "client" in lowered or "website" in lowered:
        return "Freelance"
    if "carrollton" in lowered or "utd" in lowered:
        return "Personal"
    if "personal" in lowered or "shopping" in lowered or "errand" in lowered:
        return "Personal"
    return None


def _context_from_memory_text(title: str, content: str, category: str | None) -> str:
    text = f"{title}: {content}".strip(": ")
    if category:
        return f"{text} Project/category: {category}."
    return text


def _get_llm_decision(settings, context: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "chief_of_staff_decision",
                "strict": True,
                "schema": _decision_schema(),
            },
        },
    }

    try:
        response = requests.post(
            OPENAI_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content), None
    except requests.HTTPError as exc:
        return None, _format_openai_error(exc)
    except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
        return None, _format_openai_error(exc)


def _format_openai_error(exc: Exception) -> dict[str, Any]:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else None
    response_body = None
    message = str(exc)

    if response is not None:
        response_body = getattr(response, "text", None)
        if response_body:
            message = response_body

    return {
        "source": "openai",
        "type": exc.__class__.__name__,
        "status": status,
        "message": message,
        "response_body": response_body,
        "fallback": "deterministic_planner",
    }


def _system_prompt() -> str:
    return """
You are Personal Chief of Staff, a practical AI assistant for one user.
You coordinate Todoist tasks, Google Calendar events, reminders, and replanning.

Use the provided JSON context only. Be concise, realistic, and human.
Use memory_context for durable user context. Treat memory_context.memory_hints as
high-priority routing/context clues, and ignore disabled memories because they are not included.
Choose Todoist for unscheduled tasks. Choose Calendar for time-specific events.
Calendar event categories are hard, flexible, and informational. Informational events
such as birthdays, graduations, holidays, and anniversaries do not create conflicts.
For planning, choose a clear next action, adapt to energy, and avoid robotic ranked dumps.
For low energy, recommend a tiny useful win unless something is truly urgent.
For missed plans, replan from the current time and protect hard commitments.

Classify intent as one of: plan, capture_task, schedule_event, replan, reminder, question, unknown.

You may propose exactly one backend action:
- none: answer only. Use this for planning questions, replanning, questions, reminders, and anything that does not explicitly ask to create something.
- create_todoist_task: create one simple Todoist task. Use only when the user explicitly asks to capture/create/add a task.
- create_todoist_subtask: create one Todoist subtask under an existing parent task. This always needs confirmation.
- create_many_todoist_tasks: create multiple Todoist tasks. This always needs confirmation.
- create_many_todoist_subtasks: create multiple Todoist subtasks under an existing parent task. This always needs confirmation.
- create_calendar_event: create one simple calendar event with a title, start, and end. Use only when the user explicitly asks to schedule an event.
- update_calendar_event: update one existing calendar event after the user explicitly confirms the exact event and new time.

Do not propose unsafe actions: deleting tasks/events, moving fixed events without confirmation, cancelling meetings,
sending emails, inviting attendees, or completing tasks unless explicitly requested.
If a request is risky, ambiguous, or unsupported, set needs_confirmation true and use action_type none.
If a supported task or calendar create action only needs user approval, keep action_type and the task/calendar fields populated while setting needs_confirmation true.
If your answer asks the user to choose, approve, confirm, or decide before an action can happen, needs_confirmation must be true.
When needs_confirmation is true, confirmation_prompt must contain the decision being requested.
When a calendar conflict or reschedule can be executed, pending_action must be {"type":"update_calendar_event","details":{"event_id":"...","title":"...","old_start":"...","old_end":"...","new_start":"...","new_end":"..."}}.
When creating multiple subtasks, pending_action must be {"type":"create_many_todoist_subtasks","details":{"project_name":"To-Do","section_name":"...","parent_task_title":"...","parent_task_id":"...","tasks":[{"content":"...","priority":3}]}}.
When a calendar conflict or reschedule still needs a choice, pending_action must be {"type":"resolve_calendar_conflict","details":{...}}.
If pending_action is provided in context, treat the user message as a possible resolution of that pending action and answer accordingly.
For planning questions like "I feel lazy, what is one small useful thing I can do?", action_type must be none.
For clear capture requests like "I need to buy a new water bottle from Target", return intent="capture_task", action_type="create_todoist_task", task.project_category="Personal", and no planning advice.
Shopping, errands, personal purchases, gym/health, car, and life admin tasks are Personal. Misc is only for items with no better section.
Always return valid JSON matching the schema.
""".strip()


def _decision_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "answer",
            "intent",
            "action_type",
            "task",
            "calendar_event",
            "resolved_project",
            "needs_confirmation",
            "confirmation_prompt",
            "pending_action",
        ],
        "properties": {
            "answer": {"type": "string"},
            "intent": {
                "type": "string",
                "enum": ["plan", "capture_task", "schedule_event", "replan", "reminder", "question", "unknown"],
            },
            "action_type": {
                "type": "string",
                "enum": [
                    "none",
                    "create_todoist_task",
                    "create_todoist_subtask",
                    "create_many_todoist_tasks",
                    "create_many_todoist_subtasks",
                    "create_calendar_event",
                    "update_calendar_event",
                ],
                "description": "Allowed actions. Bulk task/subtask actions always require confirmation.",
            },
            "task": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "content",
                    "project_category",
                    "due_string",
                    "due_date",
                    "labels",
                    "priority",
                    "project_name",
                    "section_name",
                ],
                "properties": {
                    "content": {"type": ["string", "null"]},
                    "project_category": {
                        "type": ["string", "null"],
                        "enum": ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc", None],
                    },
                    "due_string": {"type": ["string", "null"]},
                    "due_date": {
                        "type": ["string", "null"],
                        "description": "ISO date YYYY-MM-DD when the task should be due.",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "priority": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": 4,
                        "description": "Todoist API priority where 1 is highest and 4 is normal.",
                    },
                    "project_name": {"type": ["string", "null"]},
                    "section_name": {"type": ["string", "null"]},
                },
            },
            "calendar_event": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "start", "end", "description"],
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "start": {"type": ["string", "null"], "description": "ISO 8601 datetime with timezone."},
                    "end": {"type": ["string", "null"], "description": "ISO 8601 datetime with timezone."},
                    "description": {"type": ["string", "null"]},
                },
            },
            "resolved_project": {
                "type": ["string", "null"],
                "enum": ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc", None],
                "description": "Project/category resolved from Memory Center entity matches, if any.",
            },
            "needs_confirmation": {"type": "boolean"},
            "confirmation_prompt": {"type": ["string", "null"]},
            "pending_action": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": ["type", "details"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "resolve_calendar_conflict",
                            "update_calendar_event",
                            "create_todoist_task",
                            "create_todoist_subtask",
                            "create_many_todoist_tasks",
                            "create_many_todoist_subtasks",
                        ],
                    },
                    "details": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "conflict",
                            "options",
                            "suggested_change",
                            "affected_event",
                            "requested_decision",
                            "event_id",
                            "title",
                            "old_start",
                            "old_end",
                            "new_start",
                            "new_end",
                            "project_name",
                            "section_name",
                            "parent_task_title",
                            "parent_task_id",
                            "content",
                            "due_string",
                            "priority",
                            "tasks",
                        ],
                        "properties": {
                            "conflict": {"type": ["string", "null"]},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "suggested_change": {"type": ["string", "null"]},
                            "affected_event": {"type": ["string", "null"]},
                            "requested_decision": {"type": ["string", "null"]},
                            "event_id": {"type": ["string", "null"]},
                            "title": {"type": ["string", "null"]},
                            "old_start": {"type": ["string", "null"], "description": "ISO 8601 datetime with timezone."},
                            "old_end": {"type": ["string", "null"], "description": "ISO 8601 datetime with timezone."},
                            "new_start": {"type": ["string", "null"], "description": "ISO 8601 datetime with timezone."},
                            "new_end": {"type": ["string", "null"], "description": "ISO 8601 datetime with timezone."},
                            "project_name": {"type": ["string", "null"]},
                            "section_name": {"type": ["string", "null"]},
                            "parent_task_title": {"type": ["string", "null"]},
                            "parent_task_id": {"type": ["string", "null"]},
                            "content": {"type": ["string", "null"]},
                            "due_string": {"type": ["string", "null"]},
                            "priority": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
                            "tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["content", "due_string", "priority"],
                                    "properties": {
                                        "content": {"type": "string"},
                                        "due_string": {"type": ["string", "null"]},
                                        "priority": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def _sanitize_decision(decision: dict[str, Any]) -> dict[str, Any]:
    intent = decision.get("intent")
    action_type = decision.get("action_type")
    proposed_action_type = action_type
    needs_confirmation = bool(decision.get("needs_confirmation"))
    pending_action = decision.get("pending_action")
    task = decision.get("task") if isinstance(decision.get("task"), dict) else {}
    calendar_event = (
        decision.get("calendar_event") if isinstance(decision.get("calendar_event"), dict) else {}
    )

    if intent not in ALLOWED_INTENTS:
        intent = "unknown"
    if action_type not in {
        "none",
        "create_todoist_task",
        "create_todoist_subtask",
        "create_many_todoist_tasks",
        "create_many_todoist_subtasks",
        "create_calendar_event",
        "update_calendar_event",
    }:
        action_type = "none"

    if needs_confirmation or intent in {"plan", "replan", "question", "reminder", "unknown"}:
        action_type = "none"

    if needs_confirmation:
        if not decision.get("confirmation_prompt"):
            decision["confirmation_prompt"] = decision.get("answer")
        if not isinstance(pending_action, dict):
            pending_action = {"type": "resolve_calendar_conflict", "details": {}}
        pending_action = _executable_pending_action(
            pending_action=pending_action,
            proposed_action_type=proposed_action_type,
            intent=intent,
            task=task,
            calendar_event=calendar_event,
            confirmation_prompt=decision.get("confirmation_prompt"),
        )
    else:
        pending_action = None

    return {
        "answer": str(decision.get("answer") or "I can help with that, but I need a little more detail."),
        "intent": intent,
        "action_type": action_type,
        "task": task,
        "calendar_event": calendar_event,
        "resolved_project": _valid_project_category(decision.get("resolved_project")),
        "needs_confirmation": needs_confirmation,
        "confirmation_prompt": decision.get("confirmation_prompt"),
        "pending_action": pending_action,
    }


def _executable_pending_action(
    *,
    pending_action: dict[str, Any],
    proposed_action_type: str | None,
    intent: str,
    task: dict[str, Any],
    calendar_event: dict[str, Any],
    confirmation_prompt: str | None,
) -> dict[str, Any]:
    pending = dict(pending_action)
    details = pending.get("details")
    if not isinstance(details, dict):
        details = {}
    pending["details"] = details

    pending_type = pending.get("type")
    executable_update = pending_type == "update_calendar_event" and _calendar_update_details(details)
    if proposed_action_type in {
        "create_todoist_task",
        "create_todoist_subtask",
        "create_many_todoist_tasks",
        "create_many_todoist_subtasks",
        "create_calendar_event",
    } or executable_update:
        if executable_update:
            proposed_action_type = "update_calendar_event"
        pending["intent"] = intent
        pending["confirmation_prompt"] = confirmation_prompt
        pending["action_type"] = proposed_action_type
        pending["type"] = proposed_action_type
        pending["resolved_project"] = _valid_project_category(task.get("project_category"))
        if proposed_action_type == "create_todoist_task":
            pending["task"] = task
        if proposed_action_type == "create_calendar_event":
            pending["calendar_event"] = calendar_event

    return pending


def _calendar_update_details(details: dict[str, Any]) -> dict[str, Any] | None:
    required_fields = ("event_id", "title", "old_start", "old_end", "new_start", "new_end")
    normalized = {field: str(details.get(field) or "").strip() for field in required_fields}
    if not all(normalized.values()):
        return None
    return normalized


def _valid_project_category(value: Any) -> str | None:
    return value if value in PROJECT_CATEGORIES else None


def _apply_memory_resolution(
    decision: dict[str, Any],
    resolved_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    if not resolved_memory:
        return decision

    resolved_project = _valid_project_category(resolved_memory.get("resolved_project"))
    if not resolved_project or resolved_project == "Misc":
        return decision

    decision["resolved_project"] = resolved_project
    recognition = _recognition_sentence(resolved_memory)
    answer = str(decision.get("answer") or "")
    if recognition and recognition not in answer:
        decision["answer"] = f"{recognition} {answer}".strip()

    task = decision.get("task") if isinstance(decision.get("task"), dict) else {}
    if task:
        task["resolved_project"] = resolved_project
        task["project_category"] = resolved_project
        task["section_name"] = _section_name_for_category(resolved_project)
        task["todoist_section_name"] = _section_name_for_category(resolved_project)
        task["project_name"] = _project_name_for_category(resolved_project)
        task["classification_source"] = "memory"
        decision["task"] = task

    calendar_event = (
        decision.get("calendar_event") if isinstance(decision.get("calendar_event"), dict) else {}
    )
    if calendar_event:
        title = str(calendar_event.get("title") or "").strip()
        if title:
            calendar_event["title"] = _prefix_title_with_project(title, resolved_project)
        description = str(calendar_event.get("description") or "").strip()
        context = str(resolved_memory.get("context") or "").strip()
        context_line = f"Project context: {context}" if context else f"Project context: {resolved_project}"
        calendar_event["description"] = (
            f"{description}\n\n{context_line}".strip() if description else context_line
        )
        decision["calendar_event"] = calendar_event

    pending_action = (
        decision.get("pending_action") if isinstance(decision.get("pending_action"), dict) else None
    )
    if pending_action:
        pending_action["resolved_project"] = resolved_project
        if task and pending_action.get("action_type") == "create_todoist_task":
            pending_action["task"] = task
        if calendar_event and pending_action.get("action_type") == "create_calendar_event":
            pending_action["calendar_event"] = calendar_event
        decision["pending_action"] = pending_action

    return decision


def _recognition_sentence(resolved_memory: dict[str, Any]) -> str:
    project = _valid_project_category(resolved_memory.get("resolved_project"))
    matches = resolved_memory.get("matches") if isinstance(resolved_memory.get("matches"), list) else []
    people = [match.get("title") for match in matches if match.get("type") == "person" and match.get("title")]
    if project and len(people) == 1:
        return f"I recognized {people[0]} as {project}."
    if project:
        return f"I recognized this as {project}."
    return ""


def _prefix_title_with_project(title: str, project: str) -> str:
    prefix = f"{project} — "
    if title == project or title.startswith(prefix):
        return title
    return f"{prefix}{title}"


def _is_affirmative_confirmation(message: str) -> bool:
    normalized = re.sub(r"[^a-z\s]", "", message.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in AFFIRMATIVE_CONFIRMATION_REPLIES


def _decision_from_pending_action(pending_action: dict[str, Any]) -> dict[str, Any]:
    action_type = pending_action.get("action_type") or pending_action.get("type")
    if action_type not in EXECUTABLE_PENDING_ACTION_TYPES:
        return {
            "answer": "I can suggest this, but calendar editing for this action is not implemented yet.",
            "intent": str(pending_action.get("intent") or "unknown"),
            "action_type": "none",
            "task": {},
            "calendar_event": {},
            "resolved_project": _valid_project_category(pending_action.get("resolved_project")),
            "needs_confirmation": False,
            "confirmation_prompt": None,
            "pending_action": None,
        }

    intent = pending_action.get("intent")
    if intent not in ALLOWED_INTENTS:
        if action_type in {
            "create_todoist_task",
            "create_todoist_subtask",
            "create_many_todoist_tasks",
            "create_many_todoist_subtasks",
        }:
            intent = "capture_task"
        elif action_type == "update_calendar_event":
            intent = "replan"
        else:
            intent = "schedule_event"

    return {
        "answer": "Got it.",
        "intent": intent,
        "action_type": action_type,
        "task": pending_action.get("task") if isinstance(pending_action.get("task"), dict) else {},
        "calendar_event": (
            pending_action.get("calendar_event")
            if isinstance(pending_action.get("calendar_event"), dict)
            else {}
        ),
        "calendar_event_update": (
            pending_action.get("details") if isinstance(pending_action.get("details"), dict) else {}
        ),
        "todoist_bulk_details": (
            pending_action.get("details") if isinstance(pending_action.get("details"), dict) else {}
        ),
        "resolved_project": _valid_project_category(pending_action.get("resolved_project")),
        "needs_confirmation": False,
        "confirmation_prompt": None,
        "pending_action": None,
        "allow_conflicts": True,
    }


def _apply_capture_override(
    message: str,
    decision: dict[str, Any],
    local_now: datetime,
    memory_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    is_model_capture = (
        decision.get("intent") == "capture_task"
        and decision.get("action_type") == "create_todoist_task"
    )
    if not _is_clear_capture_request(message) and not is_model_capture:
        return decision

    task = decision.get("task") if isinstance(decision.get("task"), dict) else {}
    metadata = _extract_capture_metadata(message, task, local_now, memory_entries)
    category = metadata["project_category"]
    content = metadata["content"]
    task.update(
        {
            "content": content,
            "project_category": category,
            "due_string": metadata["due_string"],
            "due_date": metadata["due_date"],
            "labels": task.get("labels") or [],
            "priority": metadata["priority"],
            "project_name": metadata["project_name"],
            "section_name": metadata["section_name"],
        }
    )

    decision.update(
        {
            "answer": f"I'll add this to Todoist under {category}: {content}.",
            "intent": "capture_task",
            "action_type": "create_todoist_task",
            "task": task,
            "calendar_event": decision.get("calendar_event") or {
                "title": None,
                "start": None,
                "end": None,
            },
            "needs_confirmation": False,
            "confirmation_prompt": None,
            "pending_action": None,
        }
    )
    return decision


def _apply_calendar_update_override(
    message: str,
    decision: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    local_now: datetime,
) -> dict[str, Any]:
    update_request = _extract_calendar_update_request(message)
    if not update_request:
        return decision

    event = _matching_calendar_event(update_request["title"], calendar_events)
    if not event:
        return decision

    old_start = _parse_event_datetime(event.get("start"), local_now)
    old_end = _parse_event_datetime(event.get("end"), local_now)
    event_id = str(event.get("id") or "").strip()
    title = str(event.get("title") or update_request["title"]).strip()
    if not event_id or not title or not old_start or not old_end or old_end <= old_start:
        return decision

    new_start = _parse_update_time(update_request["time"], old_start, local_now)
    if not new_start:
        return decision
    new_end = new_start + (old_end - old_start)

    old_range = f"{_format_time(old_start)}-{_format_time(old_end)}"
    new_range = f"{_format_time(new_start)}-{_format_time(new_end)}"
    confirmation_prompt = f"Move {title} from {old_range} to {new_range}?"
    pending_action = {
        "type": "update_calendar_event",
        "action_type": "update_calendar_event",
        "intent": "replan",
        "confirmation_prompt": confirmation_prompt,
        "details": {
            "event_id": event_id,
            "title": title,
            "old_start": old_start.isoformat(),
            "old_end": old_end.isoformat(),
            "new_start": new_start.isoformat(),
            "new_end": new_end.isoformat(),
        },
    }

    return {
        **decision,
        "answer": f"I found {title}. {confirmation_prompt}",
        "intent": "replan",
        "action_type": "none",
        "needs_confirmation": True,
        "confirmation_prompt": confirmation_prompt,
        "pending_action": pending_action,
    }


def _extract_calendar_update_request(message: str) -> dict[str, str] | None:
    match = re.search(
        r"\b(?:move|reschedule)\s+(?P<title>.+?)\s+(?:to|for)\s+(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        message,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    title = re.sub(r"\b(my|the|a|an)\b", " ", match.group("title"), flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" .,:;-")
    target_time = re.sub(r"\s+", "", match.group("time")).lower()
    if not title or not target_time:
        return None
    return {"title": title, "time": target_time}


def _matching_calendar_event(title_hint: str, calendar_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    hint = title_hint.lower()
    hint_words = {word for word in re.findall(r"[a-z0-9]+", hint) if len(word) > 1}
    if not hint_words:
        return None

    for event in calendar_events:
        if event.get("all_day"):
            continue
        title = str(event.get("title") or "").lower()
        title_words = {word for word in re.findall(r"[a-z0-9]+", title) if len(word) > 1}
        if hint in title or title in hint or hint_words & title_words:
            return event
    return None


def _parse_event_datetime(value: Any, local_now: datetime) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_now.tzinfo)
    return parsed.astimezone(local_now.tzinfo)


def _parse_update_time(value: str, reference_start: datetime, local_now: datetime) -> datetime | None:
    match = re.fullmatch(r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?P<meridiem>am|pm)?", value)
    if not match:
        return None

    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    meridiem = match.group("meridiem")
    if minute > 59 or hour < 1 or hour > 23:
        return None

    if meridiem:
        if hour > 12:
            return None
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
    elif hour <= 12 and reference_start.hour >= 12:
        hour = 12 if hour == 12 else hour + 12

    return reference_start.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(
        local_now.tzinfo
    )


def _extract_capture_metadata(
    message: str,
    task: dict[str, Any],
    local_now: datetime,
    memory_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task_content = _capture_task_content(message)
    existing_content = str(task.get("content") or "").strip()
    content = task_content or existing_content
    category, classification_source = _infer_capture_category(" ".join([content, message]), memory_entries or [])
    due_date = _extract_due_date_from_message(message, local_now)
    due_date_text = due_date.isoformat() if due_date else None
    section_name = LIFE_AREA_TO_TODOIST_SECTION.get(category)
    project_name = TODOIST_INBOX_PROJECT_NAME

    return {
        "content": content,
        "resolved_project": category,
        "project_category": category,
        "due_string": due_date_text or task.get("due_string"),
        "due_date": due_date_text or task.get("due_date"),
        "priority": task.get("priority") or _infer_capture_priority(message, due_date_text),
        "project_name": task.get("project_name") or project_name,
        "section_name": task.get("section_name") or section_name,
        "todoist_section_name": task.get("todoist_section_name") or section_name,
        "classification_source": task.get("classification_source") or classification_source,
    }


def _is_clear_capture_request(message: str) -> bool:
    text = message.lower().strip()
    capture_starts = (
        "i need to ",
        "i need ",
        "add ",
        "remind me to ",
        "todoist ",
    )
    capture_verbs = (
        "buy ",
        "purchase ",
        "order ",
        "pick up ",
        "prepare ",
        "draft ",
        "write ",
        "study ",
        "finish ",
        "submit ",
        "send ",
        "email ",
        "call ",
        "pay ",
        "renew ",
        "review ",
    )
    if not text.startswith(capture_starts) and not text.startswith(capture_verbs):
        return False

    schedule_words = ("meeting", "appointment", " at ", " from ", " tomorrow at ")
    if any(word in text for word in schedule_words) and not any(
        word in text for word in PERSONAL_CAPTURE_KEYWORDS
    ):
        return False

    planning_words = ("what should", "should i", "plan", "prioritize")
    return not any(word in text for word in planning_words)


def _capture_task_content(message: str) -> str:
    text = message.strip()
    lowered = text.lower()
    prefixes = [
        "i need to ",
        "i need ",
        "add ",
        "remind me to ",
        "todoist ",
    ]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break

    text = re.split(r"\bbefore\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = _remove_due_phrase(text)
    text = re.sub(r"\bfor my\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(my|the|a|an)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .,:;-")

    if not text.lower().startswith(("buy ", "purchase ", "order ")):
        if any(word in text.lower() for word in ("target", "water bottle", "socks", "groceries")):
            text = f"Buy {text}"

    return text[:1].upper() + text[1:] if text else text


def _infer_capture_category(
    task_content: str,
    memory_entries: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    text = task_content.lower()
    memory_category = _infer_category_from_memory(task_content, memory_entries or [])
    if memory_category:
        return memory_category, "memory"
    if any(keyword in text for keyword in ("grad", "graduation", "commencement", "speech")):
        return "Personal", "rule"
    if any(keyword in text for keyword in PERSONAL_CAPTURE_KEYWORDS):
        return "Personal", "rule"
    if any(keyword in text for keyword in FREELANCE_CAPTURE_KEYWORDS):
        return "Freelance", "rule"
    if any(keyword in text for keyword in XO_CAPTURE_KEYWORDS):
        return "XO", "rule"
    if any(keyword in text for keyword in NEBULO_CAPTURE_KEYWORDS):
        return "Nebulo", "rule"
    if any(keyword in text for keyword in COLLEGE_CAPTURE_KEYWORDS):
        return "A&M", "rule"
    return "Misc", "fallback"


def _infer_category_from_memory(
    task_content: str,
    memory_entries: list[dict[str, Any]],
) -> str | None:
    hints = _memory_hints_for_message(memory_entries, task_content)
    for hint in hints:
        category = hint.get("project_category")
        if category in PROJECT_CATEGORIES and category != "Misc":
            return category
    return None


def _infer_capture_priority(message: str, due_date: str | None) -> int:
    text = message.lower()
    urgent_words = ("urgent", "important", "deadline", "before", "due")
    if due_date or any(word in text for word in urgent_words):
        return 4
    return 4


def _extract_due_date_from_message(message: str, local_now: datetime):
    text = message.lower()
    before_match = re.search(r"\bbefore\b(?P<event>.+)$", text)
    if before_match:
        event_date = _extract_temporal_date(before_match.group("event"), local_now)
        if event_date:
            return event_date - timedelta(days=BEFORE_EVENT_LEAD_DAYS)

    return _extract_temporal_date(text, local_now)


def _extract_temporal_date(text: str, local_now: datetime):
    today = local_now.date()
    lowered = text.lower()

    if re.search(r"\btoday\b", lowered):
        return today
    if re.search(r"\btomorrow\b", lowered):
        return today + timedelta(days=1)
    if re.search(r"\bnext week\b", lowered):
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return today + timedelta(days=days_until_monday)

    for weekday, weekday_index in WEEKDAY_TO_INDEX.items():
        if re.search(rf"\b(next\s+)?{weekday}\b", lowered):
            days_until_weekday = (weekday_index - today.weekday()) % 7
            if re.search(rf"\bnext\s+{weekday}\b", lowered) and days_until_weekday == 0:
                days_until_weekday = 7
            return today + timedelta(days=days_until_weekday)

    return None


def _remove_due_phrase(text: str) -> str:
    temporal_words = "|".join(WEEKDAY_TO_INDEX.keys())
    return re.sub(
        rf"\b(by|on|due|for)\s+(today|tomorrow|next week|next\s+(?:{temporal_words})|{temporal_words})\b.*$|\b(today|tomorrow|next week)\b.*$",
        "",
        text,
        flags=re.IGNORECASE,
    )


def _events_for_message_target_date(
    message: str,
    events: list[dict[str, Any]],
    local_now: datetime,
) -> list[dict[str, Any]]:
    target_date = _extract_temporal_date(message, local_now) or local_now.date()
    return _events_on_date(events, target_date)


def _events_for_datetime_target(
    events: list[dict[str, Any]],
    target_start: datetime,
) -> list[dict[str, Any]]:
    return _events_on_date(events, target_start.date())


def _events_on_date(events: list[dict[str, Any]], target_date) -> list[dict[str, Any]]:
    target_events = []
    for event in events:
        start_value = event.get("start")
        if not start_value:
            continue
        try:
            event_start = datetime.fromisoformat(str(start_value))
        except ValueError:
            continue
        if event_start.date() == target_date:
            target_events.append(event)
    return target_events


def _should_dual_write_calendar_event(
    decision: dict[str, Any],
    title: str,
) -> tuple[bool, str | None]:
    text = " ".join(
        [
            title,
            str(decision.get("answer") or ""),
            str((decision.get("calendar_event") or {}).get("description") or ""),
        ]
    ).lower()
    if any(keyword in text for keyword in CALENDAR_ONLY_EVENT_KEYWORDS):
        return False, None

    category = _valid_project_category(decision.get("resolved_project"))
    if not category:
        category = _infer_scheduled_project_category(title)
    if category in {"A&M", "XO", "Nebulo", "Freelance"}:
        return True, category
    return False, None


def _infer_scheduled_project_category(title: str) -> str | None:
    text = title.lower()
    if "ashwin" in text or "charlie" in text or "xo" in text:
        return "XO"
    if "brandon" in text or "nebulo" in text:
        return "Nebulo"
    if (
        "a&m" in text
        or "a and m" in text
        or "tamu" in text
        or "advising" in text
        or "advisor" in text
    ):
        return "A&M"
    if any(keyword in text for keyword in FREELANCE_CAPTURE_KEYWORDS):
        return "Freelance"
    return None


def _todoist_content_for_calendar_event(title: str, project: str | None) -> str:
    if project:
        return re.sub(rf"^{re.escape(project)}\s+[—-]\s+", "", title).strip()
    return title


def _apply_calendar_intelligence_confirmation(
    decision: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    local_now: datetime,
) -> dict[str, Any]:
    if decision.get("action_type") != "create_calendar_event" or decision.get("intent") != "schedule_event":
        return decision
    if decision.get("allow_conflicts"):
        return decision

    event = decision.get("calendar_event") if isinstance(decision.get("calendar_event"), dict) else {}
    title = str(event.get("title") or "").strip()
    start = _parse_llm_datetime(event.get("start"), local_now)
    end = _parse_llm_datetime(event.get("end"), local_now)
    if not title or not start or not end:
        return decision

    target_date_events = _events_for_datetime_target(calendar_events, start)
    analysis = analyze_calendar_change(
        {
            "title": title,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "description": event.get("description"),
            "busy": True,
            "all_day": bool(event.get("all_day")),
            "event_category": event.get("event_category") or event.get("event_type"),
        },
        target_date_events,
        {"now": local_now.isoformat()},
    )

    if analysis.severity == "none":
        informational = next((issue for issue in analysis.issues if issue.type == "informational_overlap"), None)
        if informational:
            decision["answer"] = f"{informational.message} {decision['answer']}".strip()
        return decision

    if analysis.severity not in {"medium", "high"}:
        return decision

    pending_action = _pending_action_for_calendar_analysis(
        decision=decision,
        event=event,
        title=title,
        start=start,
        end=end,
        calendar_events=target_date_events,
        analysis=analysis,
    )
    confirmation_prompt = _calendar_analysis_confirmation_prompt(title, analysis)

    decision["answer"] = confirmation_prompt
    decision["action_type"] = "none"
    decision["needs_confirmation"] = True
    decision["confirmation_prompt"] = confirmation_prompt
    decision["pending_action"] = pending_action
    return decision


def _pending_action_for_calendar_analysis(
    *,
    decision: dict[str, Any],
    event: dict[str, Any],
    title: str,
    start: datetime,
    end: datetime,
    calendar_events: list[dict[str, Any]],
    analysis: CalendarAnalysis,
) -> dict[str, Any]:
    fix = analysis.suggested_fix
    if fix and fix.action == "move_existing_event" and fix.event_id:
        affected_event = _event_by_id(calendar_events, fix.event_id)
        if affected_event and fix.new_start and fix.new_end:
            return {
                "type": "update_calendar_event",
                "action_type": "update_calendar_event",
                "intent": "replan",
                "confirmation_prompt": _calendar_analysis_confirmation_prompt(title, analysis),
                "resolved_project": decision.get("resolved_project"),
                "details": {
                    "event_id": fix.event_id,
                    "title": str(affected_event.get("title") or "Event"),
                    "old_start": str(affected_event.get("start") or ""),
                    "old_end": str(affected_event.get("end") or ""),
                    "new_start": fix.new_start,
                    "new_end": fix.new_end,
                },
            }

    pending_event = dict(event)
    if fix and fix.action == "move_new_event" and fix.new_start and fix.new_end:
        pending_event["start"] = fix.new_start
        pending_event["end"] = fix.new_end
    else:
        pending_event["start"] = start.isoformat()
        pending_event["end"] = end.isoformat()
    pending_event["title"] = title

    return {
        "type": "create_calendar_event",
        "action_type": "create_calendar_event",
        "intent": "schedule_event",
        "confirmation_prompt": _calendar_analysis_confirmation_prompt(title, analysis),
        "resolved_project": decision.get("resolved_project"),
        "calendar_event": pending_event,
        "details": {
            "conflict": _primary_calendar_issue_message(analysis),
            "options": [],
            "suggested_change": fix.reason if fix else None,
            "affected_event": _primary_affected_event_title(analysis),
            "requested_decision": "Confirm the calendar event.",
        },
    }


def _calendar_analysis_confirmation_prompt(title: str, analysis: CalendarAnalysis) -> str:
    issue_message = _primary_calendar_issue_message(analysis)
    fix = analysis.suggested_fix
    if fix and fix.action == "move_existing_event":
        return f"{issue_message} Recommended: move {_primary_affected_event_title(analysis) or 'the flexible event'} to {_format_iso_time(fix.new_start)}."
    if fix and fix.action == "move_new_event":
        return f"{issue_message} Recommended: move {title} to {_format_iso_time(fix.new_start)}."
    if fix and fix.action in {"add_travel_buffer", "add_prep_block"}:
        return f"{issue_message} Recommended: add a prep/travel buffer before this event. Create it anyway?"
    return f"{issue_message} Create it anyway?"


def _primary_calendar_issue_message(analysis: CalendarAnalysis) -> str:
    if analysis.issues:
        return analysis.issues[0].message
    return "This calendar change may need attention."


def _primary_affected_event_title(analysis: CalendarAnalysis) -> str | None:
    for issue in analysis.issues:
        if issue.affected_event_title:
            return issue.affected_event_title
    return None


def _event_by_id(events: list[dict[str, Any]], event_id: str) -> dict[str, Any] | None:
    for event in events:
        if str(event.get("id") or "") == event_id:
            return event
    return None


def _format_iso_time(value: str | None) -> str:
    if not value:
        return "the suggested time"
    try:
        return _format_time(datetime.fromisoformat(value))
    except ValueError:
        return value


def _execute_allowed_action(
    settings,
    decision: dict[str, Any],
    tasks: list[dict[str, Any]],
    calendar_events: list[dict[str, Any]],
    local_now: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    action_type = decision["action_type"]
    if action_type == "none":
        return [], []

    if action_type == "create_todoist_task" and decision["intent"] == "capture_task":
        task = decision.get("task") or {}
        content = (task.get("content") or "").strip()
        if not content:
            return [], ["OpenAI proposed task creation without task content."]

        category = decision.get("resolved_project") or task.get("project_category")
        todoist_section = _todoist_section_for_category(settings, category)
        section_name = todoist_section.get("name") or task.get("section_name") or _section_name_for_category(category)
        section_id = todoist_section.get("id") or task.get("section_id") or task.get("todoist_section_id")
        task.update(
            {
                "resolved_project": category,
                "project_category": category,
                "section_name": section_name,
                "todoist_section_name": section_name,
                "todoist_section_id": section_id,
            }
        )
        project_id = _project_id_for_category(tasks, category)
        result = create_task(
            settings=settings,
            content=content,
            project_id=project_id,
            project_name=task.get("project_name") or _project_name_for_category(category),
            section_id=section_id,
            section_name=section_name,
            due_string=task.get("due_date") or task.get("due_string"),
            labels=task.get("labels") or [],
            priority=task.get("priority"),
        )
        if result.error:
            return [], [result.error]
        task_metadata = _created_task_metadata(task, result.task)
        return [
            {
                "type": "create_todoist_task",
                "status": "success",
                "task": task_metadata,
            }
        ], []

    if action_type == "create_many_todoist_subtasks" and decision["intent"] == "capture_task":
        details = decision.get("todoist_bulk_details") if isinstance(
            decision.get("todoist_bulk_details"), dict
        ) else {}
        parent_id = str(details.get("parent_task_id") or "").strip()
        parent_title = str(details.get("parent_task_title") or "").strip()
        requested_tasks = details.get("tasks") if isinstance(details.get("tasks"), list) else []
        if not parent_id or not requested_tasks:
            return [], ["Bulk subtask creation requires a parent_task_id and at least one task."]

        result = create_many_subtasks(
            settings=settings,
            parent_id=parent_id,
            tasks=[
                {
                    "content": str(task.get("content") or "").strip(),
                    "due_string": task.get("due_string") or task.get("due_date"),
                    "priority": task.get("priority"),
                }
                for task in requested_tasks
                if isinstance(task, dict)
            ],
            existing_tasks=tasks,
        )
        if result.error:
            return [], [result.error]
        return [
            {
                "type": "create_many_todoist_subtasks",
                "status": "success",
                "parent_task_id": parent_id,
                "parent_task_title": parent_title,
                "section_name": details.get("section_name"),
                "task_count": len(result.tasks),
                "requested_count": len(requested_tasks),
                "tasks": result.tasks,
                "skipped": result.skipped,
            }
        ], []

    if action_type == "create_todoist_subtask" and decision["intent"] == "capture_task":
        details = decision.get("todoist_bulk_details") if isinstance(
            decision.get("todoist_bulk_details"), dict
        ) else {}
        parent_id = str(details.get("parent_task_id") or "").strip()
        content = str(details.get("content") or "").strip()
        if not parent_id or not content:
            return [], ["Subtask creation requires parent_task_id and content."]

        result = create_many_subtasks(
            settings=settings,
            parent_id=parent_id,
            tasks=[{"content": content, "due_string": details.get("due_string"), "priority": details.get("priority")}],
            existing_tasks=tasks,
        )
        if result.error:
            return [], [result.error]
        return [
            {
                "type": "create_todoist_subtask",
                "status": "success",
                "parent_task_id": parent_id,
                "parent_task_title": details.get("parent_task_title"),
                "task": result.tasks[0] if result.tasks else None,
                "skipped": result.skipped,
            }
        ], []

    if action_type == "create_many_todoist_tasks" and decision["intent"] == "capture_task":
        details = decision.get("todoist_bulk_details") if isinstance(
            decision.get("todoist_bulk_details"), dict
        ) else {}
        requested_tasks = details.get("tasks") if isinstance(details.get("tasks"), list) else []
        if not requested_tasks:
            return [], ["Bulk task creation requires at least one task."]

        result = create_many_tasks(
            settings=settings,
            tasks=[task for task in requested_tasks if isinstance(task, dict)],
        )
        if result.error:
            return [], [result.error]
        return [
            {
                "type": "create_many_todoist_tasks",
                "status": "success",
                "task_count": len(result.tasks),
                "requested_count": len(requested_tasks),
                "tasks": result.tasks,
                "skipped": result.skipped,
            }
        ], []

    if action_type == "create_calendar_event" and decision["intent"] == "schedule_event":
        event = decision.get("calendar_event") or {}
        title = (event.get("title") or "").strip()
        start = _parse_llm_datetime(event.get("start"), local_now)
        end = _parse_llm_datetime(event.get("end"), local_now)
        if not title or not start or not end:
            return [], ["OpenAI proposed calendar creation without a title, start, and end."]

        target_date_events = _events_for_datetime_target(calendar_events, start)
        result = create_calendar_event(
            settings=settings,
            title=title,
            start=start,
            end=end,
            existing_events=target_date_events,
            allow_conflicts=bool(decision.get("allow_conflicts")),
            description=event.get("description"),
        )
        if result.error:
            return [], [result.error]
        actions = [
            {
                "type": "create_calendar_event",
                "status": "success",
                "event": result.event,
            }
        ]

        should_dual_write, project = _should_dual_write_calendar_event(decision, title)
        if should_dual_write:
            content = _todoist_content_for_calendar_event(title, project)
            todoist_section = _todoist_section_for_category(settings, project)
            section_name = todoist_section.get("name") or _section_name_for_category(project)
            section_id = todoist_section.get("id")
            task_result = create_task(
                settings=settings,
                content=content,
                project_id=_project_id_for_category(tasks, project),
                project_name=_project_name_for_category(project),
                section_id=section_id,
                section_name=section_name,
                due_string=start.date().isoformat(),
                labels=[],
                priority=4,
            )
            if task_result.error:
                return actions, [task_result.error]
            task_metadata = _created_task_metadata(
                {
                    "content": content,
                    "project_category": project,
                    "due_date": start.date().isoformat(),
                    "due_string": start.date().isoformat(),
                    "labels": [],
                    "priority": 4,
                    "project_name": _project_name_for_category(project),
                    "section_name": section_name,
                    "todoist_section_name": section_name,
                    "todoist_section_id": section_id,
                    "classification_source": "rule",
                    "resolved_project": project,
                },
                task_result.task,
            )
            actions.append(
                {
                    "type": "create_todoist_task",
                    "status": "success",
                    "task": task_metadata,
                    "source": "dual_write_calendar_commitment",
                }
            )

        return actions, []

    if action_type == "update_calendar_event" and decision["intent"] in {"replan", "schedule_event"}:
        details = decision.get("calendar_event_update") if isinstance(
            decision.get("calendar_event_update"), dict
        ) else {}
        update_details = _calendar_update_details(details)
        if not update_details:
            return [], ["Calendar update requires event_id, title, old_start, old_end, new_start, and new_end."]

        start = _parse_llm_datetime(update_details["new_start"], local_now)
        end = _parse_llm_datetime(update_details["new_end"], local_now)
        if not start or not end:
            return [], ["Calendar update requires valid new_start and new_end values."]

        result = update_calendar_event(
            settings=settings,
            event_id=update_details["event_id"],
            title=update_details["title"],
            start=start,
            end=end,
        )
        if result.error:
            return [], [result.error]

        return [
            {
                "type": "update_calendar_event",
                "status": "success",
                "event": result.event,
                "previous_event": {
                    "id": update_details["event_id"],
                    "title": update_details["title"],
                    "start": update_details["old_start"],
                    "end": update_details["old_end"],
                },
            }
        ], []

    return [], [f"OpenAI proposed unsupported action: {action_type}."]


def _answer_with_actions(
    decision: dict[str, Any],
    actions_taken: list[dict[str, Any]],
    action_errors: list[str],
) -> str:
    if action_errors and decision["action_type"] != "none":
        return f"{decision['answer']} I could not complete the action: {action_errors[0]}"

    if not actions_taken:
        return decision["answer"]

    action = actions_taken[0]
    if any(item.get("type") == "create_calendar_event" for item in actions_taken) and any(
        item.get("type") == "create_todoist_task" for item in actions_taken
    ):
        project = next(
            (
                (item.get("task") or {}).get("section_name")
                for item in actions_taken
                if item.get("type") == "create_todoist_task"
            ),
            None,
        )
        section_text = f" under {project}" if project else ""
        return f"{decision['answer']} I added it to your calendar and created a Todoist task{section_text}."

    if action["type"] == "create_todoist_task":
        task = action.get("task") or {}
        return f"{decision['answer']} Added Todoist task: {task.get('content')}."
    if action["type"] == "create_many_todoist_subtasks":
        parent_title = action.get("parent_task_title") or "the parent task"
        count = action.get("task_count") or 0
        skipped = action.get("skipped") or []
        skipped_text = f" Skipped {len(skipped)} duplicate or invalid item(s)." if skipped else ""
        return f"Created {count} subtasks under {parent_title}.{skipped_text}"
    if action["type"] == "create_todoist_subtask":
        parent_title = action.get("parent_task_title") or "the parent task"
        if action.get("task"):
            return f"Created 1 subtask under {parent_title}."
        return f"No new subtask was created under {parent_title}."
    if action["type"] == "create_many_todoist_tasks":
        count = action.get("task_count") or 0
        skipped = action.get("skipped") or []
        skipped_text = f" Skipped {len(skipped)} invalid item(s)." if skipped else ""
        return f"Created {count} Todoist tasks.{skipped_text}"
    if action["type"] == "create_calendar_event":
        event = action.get("event") or {}
        return f"{decision['answer']} Added calendar event: {event.get('title')}."
    if action["type"] == "update_calendar_event":
        event = action.get("event") or {}
        return f"{decision['answer']} Updated calendar event: {event.get('title')}."
    return decision["answer"]


def _compact_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": task.get("id"),
            "content": task.get("content"),
            "project_id": task.get("project_id"),
            "parent_id": task.get("parent_id"),
            "project_name": task.get("project_name"),
            "category": task.get("category"),
            "due_date": task.get("due_date"),
            "due": task.get("due"),
            "priority": task.get("priority"),
            "todoist_priority": task.get("todoist_priority"),
            "labels": task.get("labels") or [],
            "estimated_duration": task.get("estimated_duration"),
            "energy_level": task.get("energy_level"),
            "section_id": task.get("section_id"),
            "section_name": task.get("section_name"),
            "todoist_section_id": task.get("todoist_section_id"),
            "todoist_section_name": task.get("todoist_section_name"),
            "classification_source": task.get("classification_source"),
            "url": task.get("url"),
        }
        for task in tasks
    ]


def _project_id_for_category(tasks: list[dict[str, Any]], category: str | None) -> str | None:
    if not category:
        return None

    project_name = _project_name_for_category(category)
    if project_name:
        for task in tasks:
            if task.get("project_name") == project_name and task.get("project_id"):
                return task["project_id"]

    for task in tasks:
        if task.get("category") == category and task.get("project_id"):
            return task["project_id"]

    return None


def _project_name_for_category(category: str | None) -> str | None:
    return TODOIST_INBOX_PROJECT_NAME if category in PROJECT_CATEGORIES else None


def _section_name_for_category(category: str | None) -> str | None:
    return LIFE_AREA_TO_TODOIST_SECTION.get(category or "")


def _todoist_section_for_category(settings, category: str | None) -> dict[str, str | None]:
    section_name = _section_name_for_category(category)
    if not section_name:
        return {"id": None, "name": None}

    result = list_todoist_sections(settings)
    for section in result.sections:
        if section.get("name") == section_name:
            return {"id": section.get("id"), "name": section_name}

    return {"id": None, "name": section_name}


def _created_task_metadata(
    proposed_task: dict[str, Any],
    created_task: dict[str, Any] | None,
) -> dict[str, Any]:
    task = dict(created_task or {})
    for key in (
        "content",
        "project_category",
        "priority",
        "due_date",
        "project_name",
        "section_name",
        "todoist_section_name",
        "todoist_section_id",
        "classification_source",
        "resolved_project",
    ):
        value = proposed_task.get(key)
        if value is not None:
            task[key] = value

    if proposed_task.get("due_date") and "due_string" not in task:
        task["due_string"] = proposed_task["due_date"]

    return task


def _parse_llm_datetime(value: str | None, local_now: datetime) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_now.tzinfo)
    return parsed.astimezone(local_now.tzinfo)


def _build_answer(
    plan: dict[str, Any],
    todoist_error: str | None,
    calendar_error: str | None,
    task_count: int,
) -> str:
    recommended_tasks = plan["recommended_tasks"]

    if todoist_error and calendar_error:
        return (
            "I cannot make a useful plan yet because I could not read Todoist or "
            f"Google Calendar. {todoist_error} {calendar_error} {READ_ONLY_NOTE}"
        )

    if todoist_error:
        return (
            "I could not read Todoist, so I do not have active tasks to rank. "
            f"{todoist_error} {READ_ONLY_NOTE}"
        )

    if task_count == 0 or not recommended_tasks:
        calendar_context = _describe_free_block(plan["free_block"], calendar_error)
        return (
            f"{calendar_context} I did not find any active Todoist tasks to recommend. "
            f"{READ_ONLY_NOTE}"
        )

    free_block_text = _describe_free_block(plan["free_block"], calendar_error)
    primary_task = recommended_tasks[0]
    secondary_task = recommended_tasks[1] if len(recommended_tasks) > 1 else None

    if plan["user_energy"] == "low":
        answer = _format_low_energy_answer(
            free_block_text=free_block_text,
            primary_task=primary_task,
            secondary_task=secondary_task,
        )
    else:
        answer = _format_normal_answer(
            free_block_text=free_block_text,
            primary_task=primary_task,
            secondary_task=secondary_task,
        )

    if calendar_error:
        answer += (
            " I could not read today's calendar, so I ranked this without schedule fit."
        )

    return f"{answer} {READ_ONLY_NOTE}"


def _describe_free_block(
    free_block: dict[str, Any] | None,
    calendar_error: str | None,
) -> str:
    if calendar_error:
        return "I could not confirm your current free block from Google Calendar."

    if not free_block:
        return "I could not find an open free block left today."

    start = datetime.fromisoformat(free_block["start"])
    end = datetime.fromisoformat(free_block["end"])
    duration = free_block["duration_minutes"]

    if duration > 240:
        if free_block.get("is_current"):
            return f"You're mostly open until {_format_time(end)}."
        return f"Your next big open stretch starts at {_format_time(start)} and runs until {_format_time(end)}."

    if free_block.get("is_current"):
        return f"You have about {_format_duration(duration)} free right now, until {_format_time(end)}."

    return (
        f"Your next free block starts at {_format_time(start)} and runs for "
        f"about {_format_duration(duration)}."
    )


def _format_normal_answer(
    free_block_text: str,
    primary_task: dict[str, Any],
    secondary_task: dict[str, Any] | None,
) -> str:
    task = primary_task.get("content")
    reason = _human_reason(primary_task)
    duration = primary_task.get("estimated_duration")

    answer = (
        f"{free_block_text} Start with: {task}. "
        f"Why: {reason} Keep it to about {_format_duration(duration)}."
    )

    if secondary_task:
        answer += f" After that: {secondary_task.get('content')}."

    return answer


def _format_low_energy_answer(
    free_block_text: str,
    primary_task: dict[str, Any],
    secondary_task: dict[str, Any] | None,
) -> str:
    task = primary_task.get("content")
    reason = _human_reason(primary_task)
    duration = primary_task.get("estimated_duration")

    answer = (
        f"{free_block_text} Since you sound low-energy, make this a tiny useful win. "
        f"Start with: {task}. Why: {reason} Keep it to about {_format_duration(duration)}."
    )

    if secondary_task and secondary_task.get("energy_level") != "high":
        answer += f" After that, only if you have momentum: {secondary_task.get('content')}."

    return answer


def _human_reason(task: dict[str, Any]) -> str:
    reasons = task.get("reasons") or []
    category = task.get("category")

    if "overdue" in reasons:
        return "it is overdue, so clearing it will reduce pressure."
    if "due today" in reasons and "high Todoist priority" in reasons:
        return "it is due today and high priority."
    if "due today" in reasons:
        return "it is due today."
    if "due tomorrow" in reasons:
        return "it is due tomorrow, so starting now keeps it from becoming urgent."
    if "tiny enough to count as a win" in reasons:
        return "it is small enough to finish without needing a huge push."
    if "low-energy friendly" in reasons:
        return "it is low-friction and still moves something forward."
    if "high Todoist priority" in reasons:
        return "Todoist marks it as high priority."
    if "fits your available time" in reasons:
        return "it fits the time you have."
    if category and category != "Misc":
        return f"it moves {category} forward."
    return "it is a concrete next step."


def _summarize_calendar_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": event.get("id"),
            "title": event.get("title"),
            "start": event.get("start"),
            "end": event.get("end"),
            "duration_minutes": event.get("duration_minutes"),
            "all_day": event.get("all_day"),
            "busy": event.get("busy"),
            "event_type": event.get("event_type"),
            "event_category": event.get("event_category"),
        }
        for event in events
    ]


def _looks_like_planning_request(message: str) -> bool:
    text = message.lower()
    planning_keywords = (
        "what should",
        "work on",
        "start with",
        "priorit",
        "urgent",
        "plan",
        "replan",
        "small piece",
        "small win",
        "feel accomplished",
    )
    return any(keyword in text for keyword in planning_keywords)


def _looks_like_write_request(message: str) -> bool:
    text = message.lower()
    write_keywords = (
        "add ",
        "create ",
        "schedule ",
        "meeting with",
        "remind me",
        "move ",
        "delete ",
        "complete ",
        "cancel ",
        "i need ",
    )
    return any(keyword in text for keyword in write_keywords)


def _describe_unsupported_write_request(message: str) -> str:
    text = message.lower()
    if "remind me" in text:
        return (
            "I read this as a reminder request. Reminder creation is not enabled "
            "in the MVP yet."
        )
    if "meeting with" in text or "schedule" in text:
        return (
            "I read this as a calendar event request. Calendar creation is not "
            "enabled in the MVP yet."
        )
    if "i need" in text or "add " in text or "create " in text:
        return (
            "I read this as a Todoist task request. Task creation is not enabled "
            "in the MVP yet."
        )
    return "Write actions are not enabled in the MVP yet."


def _format_time(value: datetime) -> str:
    if value.hour == 0 and value.minute == 0:
        return "midnight"
    if value.hour == 12 and value.minute == 0:
        return "noon"
    return value.strftime("%I:%M %p").lstrip("0").replace("AM", "am").replace("PM", "pm")


def _format_duration(minutes: int | None) -> str:
    if minutes is None:
        return "30 minutes"

    if minutes < 60:
        return f"{minutes} minutes"

    hours = minutes // 60
    remainder = minutes % 60
    if remainder == 0:
        return "1 hour" if hours == 1 else f"{hours} hours"

    return f"{hours} hr {remainder} min"
