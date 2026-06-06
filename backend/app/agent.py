from datetime import datetime, timedelta
import json
import re
from typing import Any

import requests

from .calendar_tools import create_calendar_event, list_todays_events
from .config import get_settings
from .planner import build_plan, enrich_task
from .storage import list_memory_entries
from .todoist_tools import create_task, list_active_tasks


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
TODOIST_PERSONAL_PROJECT_NAME = "To-Do"
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
    "dentist",
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
COLLEGE_CAPTURE_KEYWORDS = {
    "a&m",
    "a and m",
    "tamu",
    "college",
    "class",
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
    "sure",
    "do it",
    "sounds good",
    "add it",
}
PENDING_ACTION: dict[str, Any] | None = None


def handle_chat(message: str, current_time: datetime | None = None) -> dict[str, Any]:
    global PENDING_ACTION

    settings = get_settings()
    cleaned_message = message.strip()
    active_pending_action = PENDING_ACTION

    todoist_result = list_active_tasks(settings)
    calendar_result = list_todays_events(settings, now=current_time)
    enabled_memories = _enabled_memory_entries()
    errors = [
        error
        for error in (todoist_result.error, calendar_result.error)
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
            calendar_events=calendar_result.events,
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

    if not settings.openai_api_key:
        fallback = _fallback_response(
            plan=plan,
            todoist_error=todoist_result.error,
            calendar_error=calendar_result.error,
            task_count=len(todoist_result.tasks),
            calendar_events=calendar_result.events,
            errors=[*errors, "OPENAI_API_KEY is missing. Used deterministic planner fallback."],
        )
        return fallback

    context = _build_llm_context(
        message=cleaned_message,
        now=local_now,
        settings_timezone=settings.timezone,
        tasks=enriched_tasks,
        calendar_events=calendar_result.events,
        plan=plan,
        provider_errors=errors,
        pending_action=active_pending_action,
        memory_entries=enabled_memories,
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
        return fallback

    decision = _sanitize_decision(decision)
    decision = _apply_capture_override(cleaned_message, decision, local_now, enabled_memories)
    if decision["needs_confirmation"]:
        PENDING_ACTION = decision["pending_action"]
    elif active_pending_action:
        PENDING_ACTION = None

    actions_taken, action_errors = _execute_allowed_action(
        settings=settings,
        decision=decision,
        tasks=enriched_tasks,
        calendar_events=calendar_result.events,
        local_now=local_now,
    )
    errors.extend(action_errors)

    answer = _answer_with_actions(decision, actions_taken, action_errors)

    return {
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
    }


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
    plan: dict[str, Any],
    provider_errors: list[str],
    pending_action: dict[str, Any] | None,
    memory_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    memory_context = _build_memory_context(memory_entries, message)
    return {
        "user_message": message,
        "current_datetime": now.isoformat(),
        "timezone": settings_timezone,
        "project_categories": PROJECT_CATEGORIES,
        "memory_context": memory_context,
        "todoist_tasks": _compact_tasks(tasks),
        "calendar_events_today": _summarize_calendar_events(calendar_events),
        "free_block": plan["free_block"],
        "deterministic_recommendations": plan["recommended_tasks"],
        "provider_errors": provider_errors,
        "pending_action": pending_action,
        "safety_rules": {
            "allowed_automatic_actions": [
                "none: answer only; use for planning, replanning, reminders that need confirmation, questions, and unknown requests",
                "create_todoist_task: create one simple Todoist task only when the user explicitly asks to capture/create/add a task",
                "create_calendar_event: create one simple Google Calendar event only when the user explicitly asks to schedule an event and no busy conflict exists",
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
                "When a calendar conflict or reschedule choice needs a decision, include pending_action.type='resolve_calendar_conflict'.",
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
- create_calendar_event: create one simple calendar event with a title, start, and end. Use only when the user explicitly asks to schedule an event.

Do not propose unsafe actions: deleting tasks/events, moving fixed events, cancelling meetings,
sending emails, inviting attendees, or completing tasks unless explicitly requested.
If a request is risky, ambiguous, or unsupported, set needs_confirmation true and use action_type none.
If a supported task or calendar create action only needs user approval, keep action_type and the task/calendar fields populated while setting needs_confirmation true.
If your answer asks the user to choose, approve, confirm, or decide before an action can happen, needs_confirmation must be true.
When needs_confirmation is true, confirmation_prompt must contain the decision being requested.
When the decision is about a calendar conflict, moving a flexible block, or rescheduling, pending_action must be {"type":"resolve_calendar_conflict","details":{...}}.
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
                "enum": ["none", "create_todoist_task", "create_calendar_event"],
                "description": "Allowed actions. Use none for planning/replanning/questions. Use create_todoist_task only for explicit task capture. Use create_calendar_event only for explicit scheduling.",
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
                "required": ["title", "start", "end"],
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "start": {"type": ["string", "null"], "description": "ISO 8601 datetime with timezone."},
                    "end": {"type": ["string", "null"], "description": "ISO 8601 datetime with timezone."},
                },
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
                        "enum": ["resolve_calendar_conflict"],
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
    if action_type not in {"none", "create_todoist_task", "create_calendar_event"}:
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

    if proposed_action_type in {"create_todoist_task", "create_calendar_event"}:
        pending["intent"] = intent
        pending["confirmation_prompt"] = confirmation_prompt
        pending["action_type"] = proposed_action_type
        pending["type"] = proposed_action_type
        if proposed_action_type == "create_todoist_task":
            pending["task"] = task
        if proposed_action_type == "create_calendar_event":
            pending["calendar_event"] = calendar_event

    return pending


def _is_affirmative_confirmation(message: str) -> bool:
    normalized = re.sub(r"[^a-z\s]", "", message.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in AFFIRMATIVE_CONFIRMATION_REPLIES


def _decision_from_pending_action(pending_action: dict[str, Any]) -> dict[str, Any]:
    action_type = pending_action.get("action_type") or pending_action.get("type")
    if action_type not in {"create_todoist_task", "create_calendar_event"}:
        return {
            "answer": "I have a pending confirmation, but it is not an executable action yet.",
            "intent": str(pending_action.get("intent") or "unknown"),
            "action_type": "none",
            "task": {},
            "calendar_event": {},
            "needs_confirmation": False,
            "confirmation_prompt": None,
            "pending_action": None,
        }

    intent = pending_action.get("intent")
    if intent not in ALLOWED_INTENTS:
        intent = "capture_task" if action_type == "create_todoist_task" else "schedule_event"

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


def _extract_capture_metadata(
    message: str,
    task: dict[str, Any],
    local_now: datetime,
    memory_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task_content = _capture_task_content(message)
    existing_content = str(task.get("content") or "").strip()
    content = task_content or existing_content
    category = _infer_capture_category(" ".join([content, message]), memory_entries or [])
    due_date = _extract_due_date_from_message(message, local_now)
    due_date_text = due_date.isoformat() if due_date else None
    section_name = category if category != "Misc" else None
    project_name = TODOIST_PERSONAL_PROJECT_NAME if category == "Personal" else None

    return {
        "content": content,
        "project_category": category,
        "due_string": due_date_text or task.get("due_string"),
        "due_date": due_date_text or task.get("due_date"),
        "priority": task.get("priority") or _infer_capture_priority(message, due_date_text),
        "project_name": task.get("project_name") or project_name,
        "section_name": task.get("section_name") or section_name,
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
) -> str:
    text = task_content.lower()
    memory_category = _infer_category_from_memory(task_content, memory_entries or [])
    if memory_category:
        return memory_category
    if any(keyword in text for keyword in ("grad", "graduation", "commencement", "speech")):
        return "Personal"
    if any(keyword in text for keyword in PERSONAL_CAPTURE_KEYWORDS):
        return "Personal"
    if any(keyword in text for keyword in FREELANCE_CAPTURE_KEYWORDS):
        return "Freelance"
    if any(keyword in text for keyword in XO_CAPTURE_KEYWORDS):
        return "XO"
    if any(keyword in text for keyword in NEBULO_CAPTURE_KEYWORDS):
        return "Nebulo"
    if any(keyword in text for keyword in COLLEGE_CAPTURE_KEYWORDS):
        return "A&M"
    return "Misc"


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

        category = task.get("project_category")
        project_id = _project_id_for_category(tasks, category)
        result = create_task(
            settings=settings,
            content=content,
            project_id=project_id,
            project_name=task.get("project_name") or _project_name_for_category(category),
            section_name=task.get("section_name") or _section_name_for_category(category),
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

    if action_type == "create_calendar_event" and decision["intent"] == "schedule_event":
        event = decision.get("calendar_event") or {}
        title = (event.get("title") or "").strip()
        start = _parse_llm_datetime(event.get("start"), local_now)
        end = _parse_llm_datetime(event.get("end"), local_now)
        if not title or not start or not end:
            return [], ["OpenAI proposed calendar creation without a title, start, and end."]

        result = create_calendar_event(
            settings=settings,
            title=title,
            start=start,
            end=end,
            existing_events=calendar_events,
            allow_conflicts=bool(decision.get("allow_conflicts")),
        )
        if result.error:
            return [], [result.error]
        return [
            {
                "type": "create_calendar_event",
                "status": "success",
                "event": result.event,
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
    if action["type"] == "create_todoist_task":
        task = action.get("task") or {}
        return f"{decision['answer']} Added Todoist task: {task.get('content')}."
    if action["type"] == "create_calendar_event":
        event = action.get("event") or {}
        return f"{decision['answer']} Added calendar event: {event.get('title')}."
    return decision["answer"]


def _compact_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": task.get("id"),
            "content": task.get("content"),
            "project_id": task.get("project_id"),
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
    if category == "Personal":
        return TODOIST_PERSONAL_PROJECT_NAME
    return None


def _section_name_for_category(category: str | None) -> str | None:
    if category and category != "Misc":
        return category
    return None


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
