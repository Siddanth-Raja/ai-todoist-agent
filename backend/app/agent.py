from datetime import datetime
from typing import Any

from .calendar_tools import list_todays_events
from .config import get_settings
from .planner import build_plan
from .todoist_tools import list_active_tasks


MODE = "planning_read_only"
READ_ONLY_NOTE = "MVP read-only: I did not change Todoist or Google Calendar."


def handle_chat(message: str, current_time: datetime | None = None) -> dict[str, Any]:
    settings = get_settings()
    cleaned_message = message.strip()

    if _looks_like_write_request(cleaned_message) and not _looks_like_planning_request(
        cleaned_message
    ):
        return {
            "answer": f"{_describe_unsupported_write_request(cleaned_message)} {READ_ONLY_NOTE}",
            "free_block": None,
            "recommended_tasks": [],
            "calendar_events": [],
            "mode": MODE,
            "errors": [],
        }

    todoist_result = list_active_tasks(settings)
    calendar_result = list_todays_events(settings, now=current_time)

    errors = [
        error
        for error in (todoist_result.error, calendar_result.error)
        if error is not None
    ]

    plan = build_plan(
        tasks=todoist_result.tasks,
        calendar_events=calendar_result.events,
        message=cleaned_message,
        local_tz=settings.local_tz,
        now=current_time,
        calendar_available=calendar_result.error is None,
    )

    answer = _build_answer(
        plan=plan,
        todoist_error=todoist_result.error,
        calendar_error=calendar_result.error,
        task_count=len(todoist_result.tasks),
    )

    return {
        "answer": answer,
        "free_block": plan["free_block"],
        "recommended_tasks": plan["recommended_tasks"],
        "calendar_events": _summarize_calendar_events(calendar_result.events),
        "mode": MODE,
        "errors": errors,
    }


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
    task_text = _format_recommendations(recommended_tasks)

    if plan["user_energy"] == "low":
        opening = "Since you sound low-energy, pick one small useful task."
    else:
        opening = "Here is what I would work on next."

    calendar_note = ""
    if calendar_error:
        calendar_note = (
            " I could not read today's calendar, so I ranked these without schedule fit."
        )

    return (
        f"{free_block_text} {opening} {task_text}{calendar_note} {READ_ONLY_NOTE}"
    )


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

    if free_block.get("is_current"):
        return f"You have about {duration} minutes free right now, until {_format_time(end)}."

    return (
        f"Your next free block starts at {_format_time(start)} and runs for "
        f"about {duration} minutes."
    )


def _format_recommendations(recommended_tasks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, task in enumerate(recommended_tasks, start=1):
        duration = task.get("estimated_duration")
        category = task.get("category")
        explanation = task.get("explanation")
        content = task.get("content")
        parts.append(
            f"{index}. {content} ({category}, about {duration} min): {explanation}"
        )

    return " ".join(parts)


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
    return value.strftime("%I:%M %p").lstrip("0").replace("AM", "am").replace("PM", "pm")
