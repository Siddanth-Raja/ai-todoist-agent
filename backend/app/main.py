from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI
from fastapi import Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import MODE, handle_chat
from .calendar_tools import list_upcoming_events
from .config import get_settings
from .planner import enrich_task
from .storage import (
    create_habit,
    create_habit_checkin,
    create_memory_entry,
    delete_habit,
    delete_memory_entry,
    list_activity,
    list_habit_checkins,
    list_habits,
    list_memory_entries,
    log_activity,
    update_habit,
    update_memory_entry,
)
from .todoist_tools import list_active_tasks


app = FastAPI(
    title="Personal Chief of Staff",
    description="Planning MVP for Todoist, Google Calendar, Memory, Habits, and local activity.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):\d+|https://.*\.ngrok-free\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    current_time: datetime | None = None


class ChatResponse(BaseModel):
    answer: str
    intent: str
    actions_taken: list[dict[str, Any]]
    needs_confirmation: bool
    confirmation_prompt: str | None
    pending_action: dict[str, Any] | None
    free_block: dict[str, Any] | None
    recommended_tasks: list[dict[str, Any]]
    calendar_events: list[dict[str, Any]]
    mode: str
    errors: list[str | dict[str, Any]] = Field(default_factory=list)


TASK_SECTION_NAMES = ("A&M", "XO", "Freelance", "Personal", "Misc")
LIFE_AREA_DESCRIPTIONS = {
    "A&M": "College, TAMU, Blinn, housing, registration",
    "XO": "VR, prototype, headset, Ashwin, Charlie",
    "Freelance": "clients, outreach, websites, invoices",
    "Personal": "gym, health, shopping, errands, car, life admin",
    "Misc": "uncategorized",
}


class MemoryCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=160)
    content: str = Field(..., min_length=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    enabled: bool = True


class MemoryUpdate(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    content: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    enabled: bool | None = None


class MemoryEntry(BaseModel):
    id: str
    type: str
    title: str
    content: str
    confidence: float
    enabled: bool
    created_at: datetime
    updated_at: datetime


class HabitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    enabled: bool = True


class HabitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


class HabitDefinition(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class HabitCheckInCreate(BaseModel):
    habit: str = Field(..., min_length=1, max_length=120)
    status: Literal["yes", "no", "partial"]
    note: str | None = Field(default=None, max_length=1000)
    timestamp: datetime | None = None


class HabitCheckIn(BaseModel):
    id: str
    habit_id: str | None
    habit: str
    status: Literal["yes", "no", "partial"]
    note: str | None
    timestamp: datetime
    created_at: datetime


class ActivityCreate(BaseModel):
    action_type: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=160)
    detail: str | None = Field(default=None, max_length=1000)
    payload: dict[str, Any] | None = None


class ActivityEntry(BaseModel):
    id: str
    action_type: str
    title: str
    detail: str | None
    payload: dict[str, Any] | None
    created_at: datetime


class TaskItem(BaseModel):
    id: str | None
    content: str
    description: str | None = None
    section: str
    project_name: str | None = None
    section_name: str | None = None
    due: dict[str, Any] | None = None
    due_date: str | None = None
    due_status: str | None = None
    priority: int | None = None
    todoist_priority: int | None = None
    completed: bool
    labels: list[str] = Field(default_factory=list)
    url: str | None = None


class TaskSection(BaseModel):
    name: str
    tasks: list[TaskItem]


class TasksResponse(BaseModel):
    sections: list[TaskSection]
    errors: list[str] = Field(default_factory=list)


class CalendarEvent(BaseModel):
    id: str | None
    title: str
    start: datetime
    end: datetime
    duration_minutes: int
    all_day: bool
    busy: bool
    event_type: str
    status: str | None = None
    transparency: str | None = None
    attendees_count: int | None = None
    location: str | None = None
    html_link: str | None = None


class CalendarConflict(BaseModel):
    first_event_id: str | None
    first_event_title: str
    second_event_id: str | None
    second_event_title: str
    start: datetime
    end: datetime


class CalendarResponse(BaseModel):
    events: list[CalendarEvent]
    conflicts: list[CalendarConflict]
    errors: list[str] = Field(default_factory=list)


class LifeArea(BaseModel):
    name: str
    description: str
    status: str
    task_count: int
    overdue_count: int
    today_count: int
    high_priority_count: int


class TodayResponse(BaseModel):
    life_areas: list[LifeArea]
    errors: list[str] = Field(default_factory=list)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "mode": MODE,
    }


def require_agent_api_key(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected_key = settings.agent_api_key
    if not expected_key:
        raise HTTPException(status_code=401, detail="AGENT_API_KEY is not configured")

    expected_header = f"Bearer {expected_key}"
    if authorization != expected_header:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _model_dump(model: BaseModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be blank")

    response = handle_chat(message=message, current_time=request.current_time)
    _log_chat_activity(response)
    return response


@app.get("/memory", response_model=list[MemoryEntry])
def memory_index(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    require_agent_api_key(authorization)
    return list_memory_entries()


@app.post("/memory", response_model=MemoryEntry)
def memory_create(
    request: MemoryCreate,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    memory = create_memory_entry(**_model_dump(request))
    log_activity(
        action_type="memory_added",
        title=f"Memory added: {memory['title']}",
        detail=memory["content"],
        payload=memory,
    )
    return memory


@app.patch("/memory/{memory_id}", response_model=MemoryEntry)
def memory_update(
    memory_id: str,
    request: MemoryUpdate,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    memory = update_memory_entry(memory_id, _model_dump(request, exclude_unset=True))
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return memory


@app.delete("/memory/{memory_id}")
def memory_delete(
    memory_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, bool]:
    require_agent_api_key(authorization)
    if not delete_memory_entry(memory_id):
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"deleted": True}


@app.get("/habits", response_model=list[HabitDefinition])
def habits_index(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    require_agent_api_key(authorization)
    return list_habits()


@app.post("/habits", response_model=HabitDefinition)
def habits_create(
    request: HabitCreate,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    return create_habit(**_model_dump(request))


@app.patch("/habits/{habit_id}", response_model=HabitDefinition)
def habits_update(
    habit_id: str,
    request: HabitUpdate,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    habit = update_habit(habit_id, _model_dump(request, exclude_unset=True))
    if habit is None:
        raise HTTPException(status_code=404, detail="Habit not found")
    return habit


@app.delete("/habits/{habit_id}")
def habits_delete(
    habit_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, bool]:
    require_agent_api_key(authorization)
    if not delete_habit(habit_id):
        raise HTTPException(status_code=404, detail="Habit not found")
    return {"deleted": True}


@app.get("/habit-checkins", response_model=list[HabitCheckIn])
def habit_checkins_index(
    limit: int = 50,
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    require_agent_api_key(authorization)
    return list_habit_checkins(limit=max(1, min(limit, 200)))


@app.post("/habit-checkins", response_model=HabitCheckIn)
def habit_checkins_create(
    request: HabitCheckInCreate,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    payload = _model_dump(request)
    timestamp = payload.get("timestamp")
    payload["timestamp"] = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
    try:
        checkin = create_habit_checkin(**payload)
    except ValueError as exc:
        if str(exc) == "habit_not_found":
            raise HTTPException(status_code=404, detail="Habit not found") from exc
        raise

    activity_detail = checkin["status"]
    if checkin.get("note"):
        activity_detail = f"{activity_detail} - {checkin['note']}"
    log_activity(
        action_type="habit_logged",
        title=f"Habit logged: {checkin['habit']}",
        detail=activity_detail,
        payload=checkin,
    )
    return checkin


@app.get("/tasks", response_model=TasksResponse)
def tasks_index(
    current_time: datetime | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    settings = get_settings()
    todoist_result = list_active_tasks(settings)
    local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)
    enriched_tasks = [
        enrich_task(task, local_now.date()) for task in todoist_result.tasks if task.get("content")
    ]

    grouped: dict[str, list[dict[str, Any]]] = {section: [] for section in TASK_SECTION_NAMES}
    for task in enriched_tasks:
        section = _task_section_for(task)
        grouped[section].append(_task_item(task, section))

    return {
        "sections": [
            {"name": section, "tasks": grouped[section]} for section in TASK_SECTION_NAMES
        ],
        "errors": [todoist_result.error] if todoist_result.error else [],
    }


@app.get("/today", response_model=TodayResponse)
def today_index(
    current_time: datetime | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    settings = get_settings()
    todoist_result = list_active_tasks(settings)
    local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)
    enriched_tasks = [
        enrich_task(task, local_now.date()) for task in todoist_result.tasks if task.get("content")
    ]

    grouped: dict[str, list[dict[str, Any]]] = {section: [] for section in TASK_SECTION_NAMES}
    for task in enriched_tasks:
        grouped[_task_section_for(task)].append(task)

    return {
        "life_areas": [
            _life_area_summary(section, grouped[section]) for section in TASK_SECTION_NAMES
        ],
        "errors": [todoist_result.error] if todoist_result.error else [],
    }


@app.get("/calendar", response_model=CalendarResponse)
def calendar_index(
    days: int = 7,
    current_time: datetime | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    settings = get_settings()
    result = list_upcoming_events(settings, now=current_time, days=days)
    return {
        "events": result.events,
        "conflicts": _detect_calendar_conflicts(result.events),
        "errors": [result.error] if result.error else [],
    }


@app.get("/activity", response_model=list[ActivityEntry])
def activity_index(
    limit: int = 30,
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    require_agent_api_key(authorization)
    return list_activity(limit=max(1, min(limit, 200)))


@app.post("/activity", response_model=ActivityEntry)
def activity_create(
    request: ActivityCreate,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    return log_activity(**_model_dump(request))


def _task_section_for(task: dict[str, Any]) -> str:
    section_name = str(task.get("section_name") or "").strip()
    if section_name in TASK_SECTION_NAMES:
        return section_name

    category = str(task.get("category") or task.get("project_category") or "").strip()
    if category in TASK_SECTION_NAMES:
        return category

    return "Misc"


def _task_item(task: dict[str, Any], section: str) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "content": str(task.get("content") or ""),
        "description": task.get("description"),
        "section": section,
        "project_name": task.get("project_name"),
        "section_name": task.get("section_name"),
        "due": task.get("due"),
        "due_date": task.get("due_date"),
        "due_status": task.get("due_status"),
        "priority": task.get("priority"),
        "todoist_priority": task.get("todoist_priority"),
        "completed": bool(
            task.get("completed")
            or task.get("is_completed")
            or task.get("checked")
        ),
        "labels": task.get("labels") or [],
        "url": task.get("url"),
    }


def _life_area_summary(section: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    overdue_count = sum(1 for task in tasks if task.get("due_status") == "overdue")
    today_count = sum(1 for task in tasks if task.get("due_status") == "today")
    high_priority_count = sum(1 for task in tasks if _is_high_priority_task(task))

    return {
        "name": section,
        "description": LIFE_AREA_DESCRIPTIONS[section],
        "status": _life_area_status(
            task_count=len(tasks),
            overdue_count=overdue_count,
            today_count=today_count,
            high_priority_count=high_priority_count,
        ),
        "task_count": len(tasks),
        "overdue_count": overdue_count,
        "today_count": today_count,
        "high_priority_count": high_priority_count,
    }


def _life_area_status(
    *,
    task_count: int,
    overdue_count: int,
    today_count: int,
    high_priority_count: int,
) -> str:
    if overdue_count > 0:
        return "Needs attention"
    if high_priority_count > 0:
        return "High priority active"
    if today_count > 0:
        return "Due today"
    if task_count > 0:
        return "Clear for steady work"
    return "Clear"


def _is_high_priority_task(task: dict[str, Any]) -> bool:
    raw_priority = task.get("todoist_priority")
    if raw_priority is not None:
        try:
            return int(raw_priority) >= 4
        except (TypeError, ValueError):
            return False

    priority = task.get("priority")
    try:
        return int(priority) >= 4
    except (TypeError, ValueError):
        return False


def _detect_calendar_conflicts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    busy_events = [event for event in events if event.get("busy")]

    for index, first in enumerate(busy_events):
        first_start = datetime.fromisoformat(str(first["start"]))
        first_end = datetime.fromisoformat(str(first["end"]))
        for second in busy_events[index + 1:]:
            second_start = datetime.fromisoformat(str(second["start"]))
            second_end = datetime.fromisoformat(str(second["end"]))
            if first_start < second_end and first_end > second_start:
                conflicts.append(
                    {
                        "first_event_id": first.get("id"),
                        "first_event_title": first.get("title") or "(No title)",
                        "second_event_id": second.get("id"),
                        "second_event_title": second.get("title") or "(No title)",
                        "start": max(first_start, second_start).isoformat(),
                        "end": min(first_end, second_end).isoformat(),
                    }
                )

    return conflicts


def _log_chat_activity(response: dict[str, Any]) -> None:
    try:
        for action in response.get("actions_taken") or []:
            action_type = action.get("type")
            if action_type == "create_todoist_task":
                task = action.get("task") or {}
                log_activity(
                    action_type="task_created",
                    title=f"Task created: {task.get('content') or 'Todoist task'}",
                    detail=task.get("section_name") or task.get("project_category"),
                    payload=action,
                )
            elif action_type == "create_calendar_event":
                event = action.get("event") or {}
                log_activity(
                    action_type="calendar_event_created",
                    title=f"Calendar event created: {event.get('title') or 'Calendar event'}",
                    detail=event.get("start"),
                    payload=action,
                )

        if response.get("needs_confirmation"):
            log_activity(
                action_type="confirmation_requested",
                title="Confirmation requested",
                detail=response.get("confirmation_prompt"),
                payload=response.get("pending_action"),
            )
    except Exception:
        return
