from datetime import datetime, timedelta
import json
from typing import Any

import requests

from .calendar_tools import create_calendar_event, list_todays_events
from .config import get_settings
from .planner import build_plan, enrich_task
from .todoist_tools import create_task, list_active_tasks


MODE = "ai_agent"
FALLBACK_MODE = "planning_deterministic_fallback"
READ_ONLY_NOTE = "No changes were made."
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TIMEOUT_SECONDS = 30
PROJECT_CATEGORIES = ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc"]
ALLOWED_INTENTS = {
    "plan",
    "capture_task",
    "schedule_event",
    "replan",
    "reminder",
    "question",
    "unknown",
}


def handle_chat(message: str, current_time: datetime | None = None) -> dict[str, Any]:
    settings = get_settings()
    cleaned_message = message.strip()

    todoist_result = list_active_tasks(settings)
    calendar_result = list_todays_events(settings, now=current_time)
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
) -> dict[str, Any]:
    return {
        "user_message": message,
        "current_datetime": now.isoformat(),
        "timezone": settings_timezone,
        "project_categories": PROJECT_CATEGORIES,
        "todoist_tasks": _compact_tasks(tasks),
        "calendar_events_today": _summarize_calendar_events(calendar_events),
        "free_block": plan["free_block"],
        "deterministic_recommendations": plan["recommended_tasks"],
        "provider_errors": provider_errors,
        "safety_rules": {
            "allowed_automatic_actions": [
                "answer planning questions",
                "create a simple Todoist task",
                "create a simple Google Calendar event only if no busy conflict exists",
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
            "tool_boundary": "The model must not call external APIs. It returns a structured decision only; backend tools execute allowed actions.",
        },
    }


def _get_llm_decision(settings, context: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
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
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        return None, f"OpenAI returned HTTP {status_code}. Used deterministic planner fallback."
    except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
        return None, f"OpenAI decision failed: {exc.__class__.__name__}. Used deterministic planner fallback."


def _system_prompt() -> str:
    return """
You are Personal Chief of Staff, a practical AI assistant for one user.
You coordinate Todoist tasks, Google Calendar events, reminders, and replanning.

Use the provided JSON context only. Be concise, realistic, and human.
Choose Todoist for unscheduled tasks. Choose Calendar for time-specific events.
For planning, choose a clear next action, adapt to energy, and avoid robotic ranked dumps.
For low energy, recommend a tiny useful win unless something is truly urgent.
For missed plans, replan from the current time and protect hard commitments.

Classify intent as one of: plan, capture_task, schedule_event, replan, reminder, question, unknown.

You may propose exactly one backend action:
- create_task for a simple Todoist task.
- create_calendar_event for a simple event with a title, start, and end.
- none.

Do not propose unsafe actions: deleting tasks/events, moving fixed events, cancelling meetings,
sending emails, inviting attendees, or completing tasks unless explicitly requested.
If a request is risky, ambiguous, or unsupported, set needs_confirmation true and use action_type none.
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
        ],
        "properties": {
            "answer": {"type": "string"},
            "intent": {
                "type": "string",
                "enum": ["plan", "capture_task", "schedule_event", "replan", "reminder", "question", "unknown"],
            },
            "action_type": {
                "type": "string",
                "enum": ["none", "create_task", "create_calendar_event"],
            },
            "task": {
                "type": "object",
                "additionalProperties": False,
                "required": ["content", "project_category", "due_string", "labels", "priority"],
                "properties": {
                    "content": {"type": ["string", "null"]},
                    "project_category": {
                        "type": ["string", "null"],
                        "enum": ["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc", None],
                    },
                    "due_string": {"type": ["string", "null"]},
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
        },
    }


def _sanitize_decision(decision: dict[str, Any]) -> dict[str, Any]:
    intent = decision.get("intent")
    action_type = decision.get("action_type")
    needs_confirmation = bool(decision.get("needs_confirmation"))

    if intent not in ALLOWED_INTENTS:
        intent = "unknown"
    if action_type not in {"none", "create_task", "create_calendar_event"}:
        action_type = "none"

    if needs_confirmation:
        action_type = "none"

    return {
        "answer": str(decision.get("answer") or "I can help with that, but I need a little more detail."),
        "intent": intent,
        "action_type": action_type,
        "task": decision.get("task") if isinstance(decision.get("task"), dict) else {},
        "calendar_event": decision.get("calendar_event") if isinstance(decision.get("calendar_event"), dict) else {},
        "needs_confirmation": needs_confirmation,
        "confirmation_prompt": decision.get("confirmation_prompt"),
    }


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

    if action_type == "create_task" and decision["intent"] == "capture_task":
        task = decision.get("task") or {}
        content = (task.get("content") or "").strip()
        if not content:
            return [], ["OpenAI proposed task creation without task content."]

        project_id = _project_id_for_category(tasks, task.get("project_category"))
        result = create_task(
            settings=settings,
            content=content,
            project_id=project_id,
            due_string=task.get("due_string"),
            labels=task.get("labels") or [],
            priority=task.get("priority"),
        )
        if result.error:
            return [], [result.error]
        return [
            {
                "type": "create_task",
                "status": "success",
                "task": result.task,
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
    if action["type"] == "create_task":
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
            "url": task.get("url"),
        }
        for task in tasks
    ]


def _project_id_for_category(tasks: list[dict[str, Any]], category: str | None) -> str | None:
    if not category:
        return None

    for task in tasks:
        if task.get("category") == category and task.get("project_id"):
            return task["project_id"]

    return None


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
