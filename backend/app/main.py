from datetime import datetime, time, timedelta
import re
from typing import Any, Literal

import requests
from fastapi import FastAPI
from fastapi import Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import MODE, confirm_pending_action, handle_chat
from .calendar_tools import check_google_auth, categories_conflict, list_remaining_today_events, list_upcoming_events
from .config import get_settings
from .planner import enrich_task, rank_tasks
from .storage import (
    create_habit,
    create_habit_checkin,
    create_memory_entry,
    delete_habit,
    delete_memory_entry,
    get_memory_entry,
    list_activity,
    list_habit_checkins,
    list_habits,
    list_memory_entries,
    log_activity,
    update_habit,
    update_memory_entry,
)
from .todoist_tools import list_active_tasks
from .todoist_tools import LIFE_AREA_TO_TODOIST_SECTION, TODOIST_SECTION_TO_LIFE_AREA, life_area_for_todoist_section, list_todoist_sections


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


OPENAI_MODELS_BASE_URL = "https://api.openai.com/v1/models"
PROVIDER_HEALTH_TIMEOUT_SECONDS = 10


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None
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
    conversation_state: dict[str, Any] | None = None
    mode: str
    errors: list[str | dict[str, Any]] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    session_id: str | None = None
    pending_action: dict[str, Any]
    current_time: datetime | None = None


TASK_SECTION_NAMES = ("A&M", "XO", "Freelance", "Nebulo", "Personal", "Misc")
TODOIST_TASK_SECTION_NAMES = tuple(LIFE_AREA_TO_TODOIST_SECTION.values())
LIFE_AREA_DESCRIPTIONS = {
    "A&M": "College, TAMU, Blinn, housing, registration",
    "XO": "VR, prototype, headset, Ashwin, Charlie",
    "Nebulo": "AI context control, private storage, product work",
    "Freelance": "clients, outreach, websites, invoices",
    "Personal": "gym, health, shopping, errands, car, life admin",
    "Misc": "uncategorized",
}

PROJECT_DEFINITIONS = (
    {
        "key": "pcos-ai-todoist-agent",
        "name": "PCOS / ai todoist agent",
        "description": "Personal Chief of Staff system, Todoist agent, local app, and assistant behavior.",
        "life_area": None,
        "keywords": (
            "pcos",
            "personal chief of staff",
            "chief of staff",
            "ai todoist agent",
            "todoist agent",
            "agent api",
            "assistant behavior",
            "settings health",
        ),
        "people": (),
    },
    {
        "key": "nebulo",
        "name": "Nebulo",
        "description": "AI context control, private storage, product work, and Brandon-related follow-through.",
        "life_area": "Nebulo",
        "keywords": ("nebulo", "brandon", "context control", "context-control", "private storage"),
        "people": ("Brandon",),
    },
    {
        "key": "xo",
        "name": "XO",
        "description": "VR, prototype, headset, worldbuilding, Ashwin, and Charlie.",
        "life_area": "XO",
        "keywords": ("xo", "xo collective", "vr", "headset", "prototype", "ashwin", "charlie"),
        "people": ("Ashwin", "Charlie"),
    },
    {
        "key": "freelance",
        "name": "Freelance",
        "description": "Client outreach, websites, proposals, invoices, and delivery work.",
        "life_area": "Freelance",
        "keywords": (
            "freelance",
            "client",
            "website",
            "law firm",
            "dentist",
            "realtor",
            "invoice",
            "proposal",
        ),
        "people": (),
    },
    {
        "key": "am",
        "name": "A&M",
        "description": "College, TAMU, Blinn, housing, registration, classes, and roommate context.",
        "life_area": "A&M",
        "keywords": ("a&m", "a and m", "tamu", "blinn", "college", "housing", "classes", "nikhil", "andy", "kamden"),
        "people": ("Nikhil", "Andy", "Kamden"),
    },
    {
        "key": "personal",
        "name": "Personal",
        "description": "Gym, health, shopping, errands, car, family, and life admin.",
        "life_area": "Personal",
        "keywords": (
            "personal",
            "gym",
            "health",
            "shopping",
            "target",
            "errand",
            "car",
            "family",
            "life admin",
            "sam",
            "jai",
            "krrish",
        ),
        "people": ("Sam", "Jai", "Krrish"),
    },
    {
        "key": "needs-classification",
        "name": "Needs Classification",
        "description": "Unclassified Todoist work that needs a project decision before it can be safely hidden or routed.",
        "life_area": "Misc",
        "keywords": (),
        "people": (),
        "classification_bucket": True,
    },
)
PROJECT_ALIASES = {
    "pcos": "pcos-ai-todoist-agent",
    "ai-todoist-agent": "pcos-ai-todoist-agent",
    "ai todoist agent": "pcos-ai-todoist-agent",
    "personal-chief-of-staff": "pcos-ai-todoist-agent",
    "chief-of-staff": "pcos-ai-todoist-agent",
    "chief of staff": "pcos-ai-todoist-agent",
    "aandm": "am",
    "a-and-m": "am",
    "a&m": "am",
    "a and m": "am",
    "tamu": "am",
    "college": "am",
    "uncategorized": "needs-classification",
    "needs-classification": "needs-classification",
    "needs classification": "needs-classification",
}
BLOCKER_WORDS = ("blocked", "blocking", "waiting", "review", "feedback")
FOLLOW_UP_WORDS = ("follow up", "follow-up", "waiting", "pending", "review", "feedback")


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
    type: str | None = Field(default=None, min_length=1, max_length=80)
    action_type: str | None = Field(default=None, min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    detail: str | None = Field(default=None, max_length=1000)
    source: str = Field(default="manual", min_length=1, max_length=80)
    metadata: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None


class ActivityEntry(BaseModel):
    id: str
    type: str
    action_type: str
    title: str
    description: str | None
    detail: str | None
    source: str
    metadata: dict[str, Any] | None
    payload: dict[str, Any] | None
    created_at: datetime


class ConfirmCancelRequest(BaseModel):
    session_id: str | None = None
    pending_action: dict[str, Any] | None = None


class TaskItem(BaseModel):
    id: str | None
    content: str
    description: str | None = None
    section: str
    parent_id: str | None = None
    project_name: str | None = None
    section_name: str | None = None
    category: str | None = None
    todoist_section_name: str | None = None
    todoist_section_id: str | None = None
    classification_source: str | None = None
    due: dict[str, Any] | None = None
    due_date: str | None = None
    due_status: str | None = None
    priority: int | None = None
    todoist_priority: int | None = None
    created_at: str | None = None
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
    event_category: str | None = None
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


class TodayEvent(BaseModel):
    id: str | None
    title: str
    start: datetime
    end: datetime
    start_display: str
    end_display: str
    time_range_display: str
    duration_minutes: int
    event_category: str
    location: str | None = None
    html_link: str | None = None


class TodayFreeBlock(BaseModel):
    start: datetime
    end: datetime
    start_display: str
    end_display: str
    time_range_display: str
    duration_minutes: int
    low_usefulness: bool


class TodayRecommendation(BaseModel):
    type: str
    title: str
    detail: str
    task: dict[str, Any] | None = None
    event: TodayEvent | None = None


class LifeArea(BaseModel):
    name: str
    description: str
    status: str
    task_count: int
    overdue_count: int
    today_count: int
    high_priority_count: int


class TodayResponse(BaseModel):
    now: datetime
    now_display: str
    next_event: TodayEvent | None = None
    minutes_until_next_event: int | None = None
    current_free_block: TodayFreeBlock | None = None
    today_remaining_events: list[TodayEvent] = Field(default_factory=list)
    recommendation: TodayRecommendation
    life_areas: list[LifeArea]
    errors: list[str] = Field(default_factory=list)


class ProjectBlocker(BaseModel):
    type: str
    title: str
    detail: str | None = None
    severity: Literal["warning", "critical"] = "warning"
    source_id: str | None = None


class ProjectTaskDiagnostic(BaseModel):
    task_title: str
    parent_title: str | None = None
    todoist_section: str | None = None
    resolved_project: str
    priority: int | None = None
    included: bool
    reason: str


class ProjectTaskGroup(BaseModel):
    parent_task: TaskItem
    subtasks: list[TaskItem] = Field(default_factory=list)
    is_container: bool = False


class ProjectBrain(BaseModel):
    key: str
    name: str
    description: str
    status: str
    task_count: int
    next_recommendation: str
    blockers: list[ProjectBlocker] = Field(default_factory=list)
    tasks: list[TaskItem] = Field(default_factory=list)
    task_groups: list[ProjectTaskGroup] = Field(default_factory=list)
    classification_diagnostics: list[ProjectTaskDiagnostic] = Field(default_factory=list)
    upcoming_events: list[CalendarEvent] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    memories: list[MemoryEntry] = Field(default_factory=list)
    recent_activity: list[ActivityEntry] = Field(default_factory=list)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "mode": MODE,
    }


@app.get("/settings/health")
def settings_health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_agent_api_key(authorization)
    settings = get_settings()
    return {
        "checks": {
            "todoist": _todoist_health(settings),
            "google_calendar": _google_calendar_health(settings),
            "openai": _openai_health(settings),
        },
    }


def require_agent_api_key(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected_key = settings.agent_api_key
    if not expected_key:
        raise HTTPException(status_code=401, detail="AGENT_API_KEY is not configured")

    expected_header = f"Bearer {expected_key}"
    if authorization != expected_header:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _health_payload(
    *,
    status: Literal["ok", "warning", "error"],
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "details": details or {},
    }


def _todoist_health(settings) -> dict[str, Any]:
    if settings.missing_todoist:
        return _health_payload(
            status="error",
            message="TODOIST_API_TOKEN is missing. Add it to backend/.env, then restart ./start.sh.",
        )

    result = list_todoist_sections(settings)
    if result.error:
        return _health_payload(status="error", message=result.error)

    return _health_payload(
        status="ok",
        message=f"Connected to Todoist. Found {len(result.sections)} sections in the To-Do project.",
    )


def _google_calendar_health(settings) -> dict[str, Any]:
    diagnostics = check_google_auth(settings)
    errors = diagnostics.get("errors") or []
    missing_config = any(error.get("type") == "missing_config" for error in errors if isinstance(error, dict))

    if missing_config:
        return _health_payload(
            status="error",
            message="Google Calendar OAuth is not configured. Add the missing Google fields to backend/.env, then restart ./start.sh.",
            details=diagnostics,
        )

    token_ok = bool(diagnostics.get("token_refresh_succeeds"))
    read_ok = bool(diagnostics.get("calendar_read_succeeds"))
    write_ok = diagnostics.get("write_permission_status") == "ok"
    if token_ok and read_ok and write_ok:
        return _health_payload(
            status="ok",
            message="Connected to Google Calendar with read and write access.",
            details=diagnostics,
        )

    return _health_payload(
        status="error",
        message=(
            "Google Calendar auth failed. Reconnect by running "
            "`cd backend && .venv/bin/python scripts/google_oauth_setup.py`, then restart ./start.sh."
        ),
        details=diagnostics,
    )


def _openai_health(settings) -> dict[str, Any]:
    if not settings.openai_api_key:
        return _health_payload(
            status="error",
            message="OPENAI_API_KEY is missing. Add it to backend/.env, then restart ./start.sh.",
        )

    try:
        response = requests.get(
            f"{OPENAI_MODELS_BASE_URL}/{settings.openai_model}",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            timeout=PROVIDER_HEALTH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        return _health_payload(
            status="error",
            message=f"OpenAI rejected the configured key or model with HTTP {status_code}.",
        )
    except requests.RequestException as exc:
        return _health_payload(
            status="error",
            message=f"Could not reach OpenAI: {exc.__class__.__name__}.",
        )

    return _health_payload(
        status="ok",
        message=f"Connected to OpenAI model {settings.openai_model}.",
    )


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

    response = handle_chat(message=message, current_time=request.current_time, session_id=request.session_id)
    _log_chat_activity(response)
    return response


@app.post("/confirm", response_model=ChatResponse)
def confirm(
    request: ConfirmRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    try:
        response = confirm_pending_action(
            pending_action=request.pending_action,
            current_time=request.current_time,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _log_chat_activity(response)
    log_activity(
        action_type="confirmation_completed",
        title="Confirmation completed",
        detail=response.get("answer"),
        source="confirmation",
        payload={
            "session_id": request.session_id,
            "pending_action": request.pending_action,
            "actions_taken": response.get("actions_taken") or [],
        },
    )
    return response


@app.post("/confirm-cancel", response_model=ActivityEntry)
def confirm_cancel(
    request: ConfirmCancelRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    return log_activity(
        action_type="confirmation_cancelled",
        title="Confirmation cancelled",
        detail=(request.pending_action or {}).get("confirmation_prompt"),
        source="confirmation",
        payload={
            "session_id": request.session_id,
            "pending_action": request.pending_action,
        },
    )


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
        source="memory",
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
    activity_type = "memory_disabled" if memory.get("enabled") is False else "memory_edited"
    log_activity(
        action_type=activity_type,
        title=f"Memory {'disabled' if activity_type == 'memory_disabled' else 'edited'}: {memory['title']}",
        detail=memory["content"],
        source="memory",
        payload=memory,
    )
    return memory


@app.delete("/memory/{memory_id}")
def memory_delete(
    memory_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, bool]:
    require_agent_api_key(authorization)
    memory = get_memory_entry(memory_id)
    if not delete_memory_entry(memory_id):
        raise HTTPException(status_code=404, detail="Memory entry not found")
    log_activity(
        action_type="memory_deleted",
        title=f"Memory deleted: {(memory or {}).get('title') or memory_id}",
        detail=(memory or {}).get("content"),
        source="memory",
        payload=memory or {"id": memory_id},
    )
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
        source="habit",
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

    grouped: dict[str, list[dict[str, Any]]] = {section: [] for section in TODOIST_TASK_SECTION_NAMES}
    for task in enriched_tasks:
        section = _todoist_task_section_for(task)
        grouped[section].append(_task_item(task, section))

    return {
        "sections": [
            {"name": section, "tasks": grouped[section]} for section in TODOIST_TASK_SECTION_NAMES
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
    calendar_result = list_remaining_today_events(settings, now=current_time)
    local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)
    enriched_tasks = [
        enrich_task(task, local_now.date()) for task in todoist_result.tasks if task.get("content")
    ]
    today_remaining_events = _future_today_events(calendar_result.events, local_now)
    blocking_events = _blocking_today_events(today_remaining_events, local_now)
    next_event = blocking_events[0] if blocking_events else None
    minutes_until_next_event = (
        _ceil_minutes_between(local_now, _event_start(next_event)) if next_event else None
    )
    current_free_block = _today_current_free_block(
        now=local_now,
        next_event=next_event,
        minutes_until_next_event=minutes_until_next_event,
    )
    recommendation = _today_recommendation(
        tasks=enriched_tasks,
        now=local_now,
        next_event=next_event,
        minutes_until_next_event=minutes_until_next_event,
        current_free_block=current_free_block,
    )

    grouped: dict[str, list[dict[str, Any]]] = {section: [] for section in TASK_SECTION_NAMES}
    for task in enriched_tasks:
        grouped[_task_section_for(task)].append(task)

    errors = [
        error
        for error in (todoist_result.error, calendar_result.error)
        if error
    ]
    return {
        "now": local_now.isoformat(),
        "now_display": _format_datetime_display(local_now),
        "next_event": _today_event_payload(next_event, settings.local_tz) if next_event else None,
        "minutes_until_next_event": minutes_until_next_event,
        "current_free_block": current_free_block,
        "today_remaining_events": [
            _today_event_payload(event, settings.local_tz) for event in today_remaining_events
        ],
        "recommendation": recommendation,
        "life_areas": [
            _life_area_summary(section, grouped[section]) for section in TASK_SECTION_NAMES
        ],
        "errors": errors,
    }


@app.get("/projects", response_model=list[ProjectBrain])
def projects_index(
    current_time: datetime | None = None,
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    require_agent_api_key(authorization)
    return _project_brains(current_time=current_time)


@app.get("/projects/{project_key}", response_model=ProjectBrain)
def project_detail(
    project_key: str,
    current_time: datetime | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    canonical_key = _canonical_project_key(project_key)
    project = next(
        (item for item in _project_brains(current_time=current_time) if item["key"] == canonical_key),
        None,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _canonical_project_key(project_key: str) -> str:
    normalized = _slug_text(project_key)
    return PROJECT_ALIASES.get(normalized, normalized)


def _project_brains(current_time: datetime | None = None) -> list[dict[str, Any]]:
    settings = get_settings()
    local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)

    todoist_result = list_active_tasks(settings)
    enriched_tasks = [
        enrich_task(task, local_now.date()) for task in todoist_result.tasks if task.get("content")
    ]
    calendar_result = list_upcoming_events(settings, now=current_time, days=14)
    upcoming_events = _future_events(calendar_result.events, local_now)
    memories = [memory for memory in list_memory_entries() if memory.get("enabled")]
    activity = list_activity(limit=200)

    return [
        _project_brain(
            project=project,
            tasks=enriched_tasks,
            events=upcoming_events,
            memories=memories,
            activity=activity,
            now=local_now,
        )
        for project in PROJECT_DEFINITIONS
    ]


def _project_brain(
    *,
    project: dict[str, Any],
    tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    memories: list[dict[str, Any]],
    activity: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    task_lookup = {str(task.get("id")): task for task in tasks if task.get("id")}
    active_tasks = [task for task in tasks if not _task_completed(task)]
    active_children_by_parent = _children_by_parent(active_tasks)
    project_tasks = [
        task for task in active_tasks if _task_matches_project(task, project, task_lookup)
    ]
    project_events = [event for event in events if _event_matches_project(event, project)]
    project_memories = [memory for memory in memories if _memory_matches_project(memory, project)]
    project_activity = [entry for entry in activity if _activity_matches_project(entry, project)]
    people = _project_people(project, project_memories)
    task_groups = _project_task_groups(project_tasks, task_lookup, active_children_by_parent)
    leaf_tasks = _project_leaf_tasks(project_tasks, active_children_by_parent)

    ranked_tasks = rank_tasks(
        [_project_rankable_task(task) for task in leaf_tasks],
        free_block=None,
        user_energy="medium",
        focus_category=project.get("life_area"),
        today=now.date(),
    )
    sorted_tasks = _sort_project_tasks(project_tasks)
    sorted_events = sorted(project_events, key=_event_start)
    blockers = _project_blockers(
        project=project,
        tasks=sorted_tasks,
        events=sorted_events,
        ranked_tasks=ranked_tasks,
        now=now,
    )

    return {
        "key": project["key"],
        "name": project["name"],
        "description": project["description"],
        "task_count": len(sorted_tasks),
        "status": _project_status(blockers=blockers, tasks=sorted_tasks, events=sorted_events),
        "next_recommendation": _project_next_recommendation(
            blockers=blockers,
            ranked_tasks=ranked_tasks,
            events=sorted_events,
            memories=project_memories,
        ),
        "blockers": blockers[:8],
        "tasks": [
            _task_item(task, _todoist_task_section_for(task)) for task in sorted_tasks[:12]
        ],
        "task_groups": task_groups[:12],
        "classification_diagnostics": _project_task_diagnostics(
            project=project,
            tasks=tasks,
            task_lookup=task_lookup,
            active_children_by_parent=active_children_by_parent,
        ),
        "upcoming_events": [_project_event_item(event) for event in sorted_events[:8]],
        "people": people,
        "memories": project_memories[:8],
        "recent_activity": project_activity[:8],
    }


def _task_matches_project(
    task: dict[str, Any],
    project: dict[str, Any],
    task_lookup: dict[str, dict[str, Any]] | None = None,
) -> bool:
    parent = _parent_task(task, task_lookup or {})
    if project.get("classification_bucket"):
        return _task_needs_classification(task, parent=parent)

    life_area = project.get("life_area")
    if life_area and _task_section_for(task) == life_area:
        return True

    if parent and life_area and _task_section_for(parent) == life_area:
        return True

    if parent and _text_matches_project(_task_match_text(parent), project):
        return True

    return _text_matches_project(_task_match_text(task), project)


def _event_matches_project(event: dict[str, Any], project: dict[str, Any]) -> bool:
    explicit_project = event.get("resolved_project") or event.get("project") or event.get("project_key")
    if explicit_project:
        explicit = _canonical_project_key(str(explicit_project))
        if explicit == project["key"] or _slug_text(str(explicit_project)) == _slug_text(project["name"]):
            return True

    title = str(event.get("title") or "")
    prefix_match = re.match(r"^(.+?)\s+[\u2014-]\s+", title)
    if prefix_match:
        prefix = _canonical_project_key(prefix_match.group(1))
        if prefix == project["key"]:
            return True

    return _text_matches_project(_event_match_text(event), project)


def _memory_matches_project(memory: dict[str, Any], project: dict[str, Any]) -> bool:
    memory_type = str(memory.get("type") or "").lower()
    title = str(memory.get("title") or "")
    if memory_type == "project" and _same_project_name(title, project):
        return True
    if memory_type in {"person", "group"} and _slug_text(title) in {
        _slug_text(person) for person in project.get("people", ())
    }:
        return True
    return _text_matches_project(_memory_match_text(memory), project)


def _activity_matches_project(entry: dict[str, Any], project: dict[str, Any]) -> bool:
    payload = entry.get("payload") or entry.get("metadata") or {}
    if isinstance(payload, dict):
        payload_project = (
            payload.get("resolved_project")
            or payload.get("project")
            or payload.get("project_key")
            or payload.get("project_context")
        )
        task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
        event_payload = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        section_name = (
            task_payload.get("section_name")
            or task_payload.get("todoist_section_name")
            or payload.get("section_name")
        )
        if payload_project and _canonical_project_key(str(payload_project)) == project["key"]:
            return True
        if section_name and project.get("life_area") == life_area_for_todoist_section(str(section_name)):
            return True
        if event_payload and _text_matches_project(_event_match_text(event_payload), project):
            return True

    return _text_matches_project(_activity_match_text(entry), project)


def _text_matches_project(text: str, project: dict[str, Any]) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    if _contains_phrase(normalized, str(project.get("name") or "")):
        return True
    for keyword in project.get("keywords", ()):
        if _contains_phrase(normalized, str(keyword)):
            return True
    for person in project.get("people", ()):
        if _contains_phrase(normalized, str(person)):
            return True
    return False


def _same_project_name(value: str, project: dict[str, Any]) -> bool:
    return _canonical_project_key(value) == project["key"] or _slug_text(value) == _slug_text(project["name"])


def _project_people(project: dict[str, Any], memories: list[dict[str, Any]]) -> list[str]:
    people = {str(person) for person in project.get("people", ())}
    for memory in memories:
        if str(memory.get("type") or "").lower() != "person":
            continue
        title = str(memory.get("title") or "").strip()
        if title:
            people.add(title)
    return sorted(people)


def _children_by_parent(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    children: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        parent_id = str(task.get("parent_id") or "").strip()
        if not parent_id:
            continue
        children.setdefault(parent_id, []).append(task)
    return children


def _parent_task(
    task: dict[str, Any],
    task_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    parent_id = str(task.get("parent_id") or "").strip()
    return task_lookup.get(parent_id) if parent_id else None


def _task_completed(task: dict[str, Any]) -> bool:
    return bool(task.get("completed") or task.get("is_completed") or task.get("checked"))


def _task_is_container(
    task: dict[str, Any],
    active_children_by_parent: dict[str, list[dict[str, Any]]],
) -> bool:
    task_id = str(task.get("id") or "")
    if not active_children_by_parent.get(task_id):
        return False
    return not _task_explicitly_completeable(task)


def _task_explicitly_completeable(task: dict[str, Any]) -> bool:
    labels = {str(label).strip().lower() for label in task.get("labels") or []}
    if {"completeable", "completable", "leaf-task"} & labels:
        return True
    text = _normalize_text(f"{task.get('content') or ''} {task.get('description') or ''}")
    return "[completeable]" in text or "[completable]" in text


def _project_leaf_tasks(
    tasks: list[dict[str, Any]],
    active_children_by_parent: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    return [
        task
        for task in tasks
        if not _task_completed(task) and not _task_is_container(task, active_children_by_parent)
    ]


def _project_rankable_task(task: dict[str, Any]) -> dict[str, Any]:
    rankable = dict(task)
    try:
        todoist_priority = int(task.get("todoist_priority") or 0)
    except (TypeError, ValueError):
        todoist_priority = 0
    try:
        priority = int(task.get("priority") or 0)
    except (TypeError, ValueError):
        priority = 0
    rankable["priority"] = max(priority, todoist_priority)
    return rankable


def _project_task_groups(
    tasks: list[dict[str, Any]],
    task_lookup: dict[str, dict[str, Any]],
    active_children_by_parent: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    tasks_by_id = {str(task.get("id")): task for task in tasks if task.get("id")}
    grouped_parent_ids = {
        str(task.get("parent_id"))
        for task in tasks
        if task.get("parent_id") and str(task.get("parent_id")) in task_lookup
    }
    roots = [
        task
        for task in tasks
        if not task.get("parent_id") or str(task.get("id")) in grouped_parent_ids
    ]
    for parent_id in grouped_parent_ids:
        parent = task_lookup.get(parent_id)
        if parent and parent_id not in tasks_by_id:
            roots.append(parent)

    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for parent in _sort_project_tasks(roots):
        parent_id = str(parent.get("id") or "")
        if parent_id in seen:
            continue
        seen.add(parent_id)
        subtasks = [
            task
            for task in active_children_by_parent.get(parent_id, [])
            if str(task.get("id") or "") in tasks_by_id
        ]
        groups.append(
            {
                "parent_task": _task_item(parent, _todoist_task_section_for(parent)),
                "subtasks": [
                    _task_item(task, _todoist_task_section_for(task)) for task in _sort_project_tasks(subtasks)
                ],
                "is_container": _task_is_container(parent, active_children_by_parent),
            }
        )
    return groups


def _project_task_diagnostics(
    *,
    project: dict[str, Any],
    tasks: list[dict[str, Any]],
    task_lookup: dict[str, dict[str, Any]],
    active_children_by_parent: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for task in _sort_project_tasks(tasks):
        parent = _parent_task(task, task_lookup)
        included = _task_matches_project(task, project, task_lookup) and not _task_completed(task)
        resolved_project = _resolved_project_name_for_task(task, task_lookup)
        diagnostics.append(
            {
                "task_title": str(task.get("content") or "Untitled task"),
                "parent_title": str(parent.get("content")) if parent else None,
                "todoist_section": task.get("todoist_section_name") or task.get("section_name"),
                "resolved_project": resolved_project,
                "priority": task.get("todoist_priority") or task.get("priority"),
                "included": included,
                "reason": _task_diagnostic_reason(
                    task=task,
                    project=project,
                    parent=parent,
                    included=included,
                    active_children_by_parent=active_children_by_parent,
                ),
            }
        )
    return diagnostics


def _task_diagnostic_reason(
    *,
    task: dict[str, Any],
    project: dict[str, Any],
    parent: dict[str, Any] | None,
    included: bool,
    active_children_by_parent: dict[str, list[dict[str, Any]]],
) -> str:
    if _task_completed(task):
        return "excluded: completed"
    if included and task.get("parent_id"):
        return "included: subtask inherited project from parent or section"
    if included and _task_is_container(task, active_children_by_parent):
        return "included: parent container with active children"
    if included:
        return "included: standalone task matched project"
    if project.get("classification_bucket"):
        return "excluded: task already has a resolved project"
    if parent and _task_needs_classification(task, parent=parent):
        return "excluded: needs classification"
    return "excluded: matched another project or no project signal"


def _resolved_project_name_for_task(
    task: dict[str, Any],
    task_lookup: dict[str, dict[str, Any]],
) -> str:
    parent = _parent_task(task, task_lookup)
    for project in PROJECT_DEFINITIONS:
        if project.get("classification_bucket"):
            continue
        if _task_matches_project(task, project, task_lookup):
            return str(project["name"])
    if _task_needs_classification(task, parent=parent):
        return "Needs Classification"
    return "Uncategorized"


def _task_needs_classification(
    task: dict[str, Any],
    *,
    parent: dict[str, Any] | None,
) -> bool:
    if parent:
        for project in PROJECT_DEFINITIONS:
            if not project.get("classification_bucket") and _task_matches_project(parent, project, {}):
                return False
    if _task_section_for(task) != "Misc":
        return False
    for project in PROJECT_DEFINITIONS:
        if not project.get("classification_bucket") and _text_matches_project(_task_match_text(task), project):
            return False
    return True


def _project_blockers(
    *,
    project: dict[str, Any],
    tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    ranked_tasks: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []

    for task in tasks:
        content = str(task.get("content") or "Untitled task")
        if task.get("due_status") == "overdue":
            blockers.append(
                {
                    "type": "overdue_task",
                    "title": content,
                    "detail": "Overdue Todoist task",
                    "severity": "critical",
                    "source_id": task.get("id"),
                }
            )
        if _is_stale_high_priority_task(task, now):
            blockers.append(
                {
                    "type": "stale_high_priority_task",
                    "title": content,
                    "detail": "High-priority task has been open for more than 7 days",
                    "severity": "warning",
                    "source_id": task.get("id"),
                }
            )
        blocker_word = _first_matching_phrase(_task_match_text(task), BLOCKER_WORDS)
        if blocker_word:
            blockers.append(
                {
                    "type": "blocked_task",
                    "title": content,
                    "detail": f"Task mentions {blocker_word}",
                    "severity": "warning",
                    "source_id": task.get("id"),
                }
            )

    for event in events:
        follow_up_word = _first_matching_phrase(_event_match_text(event), FOLLOW_UP_WORDS)
        if follow_up_word:
            blockers.append(
                {
                    "type": "pending_meeting_follow_up",
                    "title": str(event.get("title") or "Calendar event"),
                    "detail": f"Upcoming event mentions {follow_up_word}",
                    "severity": "warning",
                    "source_id": event.get("id"),
                }
            )

    if events and not ranked_tasks:
        blockers.append(
            {
                "type": "empty_next_step",
                "title": "No next task before upcoming event",
                "detail": f"{project['name']} has calendar context but no matching Todoist next step",
                "severity": "warning",
                "source_id": None,
            }
        )

    return _dedupe_blockers(blockers)


def _project_status(
    *,
    blockers: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    if any(blocker.get("severity") == "critical" for blocker in blockers):
        return "Blocked"
    if blockers:
        return "Needs attention"
    if tasks or events:
        return "Active"
    return "Quiet"


def _project_next_recommendation(
    *,
    blockers: list[dict[str, Any]],
    ranked_tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> str:
    if blockers:
        first = blockers[0]
        return f"Resolve blocker: {first['title']}"
    if ranked_tasks:
        return f"Work next: {ranked_tasks[0].get('content')}"
    if events:
        return f"Prepare for: {events[0].get('title') or 'upcoming event'}"
    if memories:
        return "Add a concrete next task from the saved context."
    return "Add a concrete next task."


def _future_events(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    future = [event for event in events if _event_end(event) >= now]
    future.sort(key=_event_start)
    return future


def _sort_project_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    due_order = {"overdue": 0, "today": 1, "tomorrow": 2, "this_week": 3, "later": 4}
    return sorted(
        tasks,
        key=lambda task: (
            due_order.get(str(task.get("due_status") or ""), 5),
            -int(task.get("todoist_priority") or task.get("priority") or 0),
            str(task.get("due_date") or "9999-12-31"),
            str(task.get("content") or "").lower(),
        ),
    )


def _project_event_item(event: dict[str, Any]) -> dict[str, Any]:
    start = _event_start(event)
    end = _event_end(event)
    return {
        "id": event.get("id"),
        "title": event.get("title") or "(No title)",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": int(event.get("duration_minutes") or _ceil_minutes_between(start, end)),
        "all_day": bool(event.get("all_day")),
        "busy": bool(event.get("busy")),
        "event_type": event.get("event_type") or _calendar_event_category(event),
        "event_category": _calendar_event_category(event),
        "status": event.get("status"),
        "transparency": event.get("transparency"),
        "attendees_count": event.get("attendees_count"),
        "location": event.get("location"),
        "html_link": event.get("html_link"),
    }


def _is_stale_high_priority_task(task: dict[str, Any], now: datetime) -> bool:
    if not _is_high_priority_task(task):
        return False
    created_at = _parse_datetime(task.get("created_at"))
    if not created_at:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=now.tzinfo)
    return (now - created_at.astimezone(now.tzinfo)).days >= 7


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _dedupe_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str | None]] = set()
    deduped: list[dict[str, Any]] = []
    for blocker in blockers:
        key = (str(blocker.get("type")), str(blocker.get("title")), blocker.get("source_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(blocker)
    return deduped


def _task_match_text(task: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            task.get("content"),
            task.get("description"),
            task.get("project_name"),
            task.get("section_name"),
            task.get("todoist_section_name"),
            task.get("category"),
            " ".join(str(label) for label in task.get("labels") or []),
        )
    )


def _event_match_text(event: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            event.get("title"),
            event.get("summary"),
            event.get("description"),
            event.get("location"),
            event.get("resolved_project"),
            event.get("project"),
            event.get("project_key"),
        )
    )


def _memory_match_text(memory: dict[str, Any]) -> str:
    return " ".join(str(memory.get(part) or "") for part in ("type", "title", "content"))


def _activity_match_text(entry: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            entry.get("type"),
            entry.get("action_type"),
            entry.get("title"),
            entry.get("description"),
            entry.get("detail"),
            entry.get("source"),
            _flatten_text(entry.get("payload") or entry.get("metadata")),
        )
    )


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").replace("-", " ").split())


def _slug_text(value: str) -> str:
    text = value.lower().replace("&", " and ")
    text = text.replace("_", " ").replace("-", " ")
    return "-".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    if len(normalized_phrase) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])", text) is not None
    return normalized_phrase in text


def _first_matching_phrase(text: str, phrases: tuple[str, ...]) -> str | None:
    normalized = _normalize_text(text)
    for phrase in phrases:
        if _contains_phrase(normalized, phrase):
            return phrase
    return None


def _future_today_events(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    end_of_day = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
    remaining = [
        event
        for event in events
        if _event_end(event) > now and _event_start(event) < end_of_day
    ]
    remaining.sort(key=lambda event: _event_start(event))
    return remaining


def _blocking_today_events(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    blocking = [
        event
        for event in events
        if event.get("busy")
        and not event.get("all_day")
        and _today_event_category(event) in {"hard", "flexible"}
        and _event_start(event) > now
    ]
    blocking.sort(key=lambda event: _event_start(event))
    return blocking


def _today_current_free_block(
    *,
    now: datetime,
    next_event: dict[str, Any] | None,
    minutes_until_next_event: int | None,
) -> dict[str, Any] | None:
    if next_event:
        end = _event_start(next_event)
    else:
        end = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)

    duration_minutes = _ceil_minutes_between(now, end)
    if duration_minutes <= 0:
        return None
    if minutes_until_next_event is not None and minutes_until_next_event <= 30:
        return None

    return {
        "start": now.isoformat(),
        "end": end.isoformat(),
        "start_display": _format_time_display(now),
        "end_display": _format_time_display(end),
        "time_range_display": f"{_format_time_display(now)}-{_format_time_display(end)}",
        "duration_minutes": duration_minutes,
        "low_usefulness": bool(minutes_until_next_event is not None and minutes_until_next_event <= 60),
    }


def _today_recommendation(
    *,
    tasks: list[dict[str, Any]],
    now: datetime,
    next_event: dict[str, Any] | None,
    minutes_until_next_event: int | None,
    current_free_block: dict[str, Any] | None,
) -> dict[str, Any]:
    if next_event and minutes_until_next_event is not None and minutes_until_next_event <= 60:
        event_payload = _today_event_payload(next_event, now.tzinfo)
        if minutes_until_next_event <= 30:
            return {
                "type": "prepare",
                "title": f"Prepare to leave for {next_event.get('title')}",
                "detail": "This is inside 30 minutes, so only preparation, packing, notes, or travel should be considered.",
                "task": None,
                "event": event_payload,
            }
        return {
            "type": "prepare",
            "title": f"Prepare for {next_event.get('title')}",
            "detail": "The next commitment starts within 60 minutes. Review context, agenda, materials, and travel buffer now.",
            "task": None,
            "event": event_payload,
        }

    ranked_tasks = rank_tasks(
        tasks,
        free_block=_free_block_for_planner(current_free_block),
        user_energy="medium",
        focus_category=None,
        today=now.date(),
    )
    if current_free_block:
        ranked_tasks = [
            task
            for task in ranked_tasks
            if int(task.get("estimated_duration") or 0) <= int(current_free_block["duration_minutes"])
        ] or ranked_tasks

    if ranked_tasks:
        task = ranked_tasks[0]
        if current_free_block and next_event:
            detail = (
                f"This fits the {current_free_block['duration_minutes']}-minute block before "
                f"{next_event.get('title')}."
            )
        elif current_free_block:
            detail = f"No blocking events remain today. Use the {current_free_block['duration_minutes']}-minute open block."
        else:
            detail = "No blocking calendar events remain, so this is chosen from Todoist priority and due-date signals."
        return {
            "type": "task",
            "title": str(task.get("content") or "Work the top Todoist task"),
            "detail": detail,
            "task": task,
            "event": None,
        }

    if next_event:
        return {
            "type": "calendar",
            "title": f"Protect the buffer before {next_event.get('title')}",
            "detail": "No Todoist task clearly fits the available block, so keep the calendar transition clean.",
            "task": None,
            "event": _today_event_payload(next_event, now.tzinfo),
        }

    return {
        "type": "open",
        "title": "No remaining calendar commitments",
        "detail": "No Todoist task is available, so keep the rest of the day open or add the next concrete task.",
        "task": None,
        "event": None,
    }


def _free_block_for_planner(block: dict[str, Any] | None) -> dict[str, Any] | None:
    if not block:
        return None
    return {
        "start": block["start"],
        "end": block["end"],
        "duration_minutes": block["duration_minutes"],
        "is_current": True,
    }


def _today_event_payload(event: dict[str, Any], local_tz) -> dict[str, Any]:
    start = _event_start(event).astimezone(local_tz)
    end = _event_end(event).astimezone(local_tz)
    return {
        "id": event.get("id"),
        "title": event.get("title") or "(No title)",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "start_display": _format_time_display(start),
        "end_display": _format_time_display(end),
        "time_range_display": f"{_format_time_display(start)}-{_format_time_display(end)}",
        "duration_minutes": int(event.get("duration_minutes") or _ceil_minutes_between(start, end)),
        "event_category": _today_event_category(event),
        "location": event.get("location"),
        "html_link": event.get("html_link"),
    }


def _today_event_category(event: dict[str, Any]) -> str:
    category = event.get("event_category") or event.get("event_type")
    return str(category or "flexible")


def _event_start(event: dict[str, Any]) -> datetime:
    value = event.get("start")
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _event_end(event: dict[str, Any]) -> datetime:
    value = event.get("end")
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _ceil_minutes_between(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60 + (1 if (end - start).total_seconds() % 60 else 0)))


def _format_time_display(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _format_datetime_display(value: datetime) -> str:
    return f"{value.strftime('%A, %B')} {value.day} at {_format_time_display(value)}"


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
    payload = _model_dump(request)
    return log_activity(
        action_type=payload.get("action_type") or payload.get("type"),
        title=payload["title"],
        detail=payload.get("detail") or payload.get("description"),
        source=payload.get("source") or "manual",
        payload=payload.get("payload") or payload.get("metadata"),
    )


def _task_section_for(task: dict[str, Any]) -> str:
    category = str(task.get("category") or task.get("project_category") or "").strip()
    if category in TASK_SECTION_NAMES:
        return category

    section_name = str(task.get("section_name") or "").strip()
    section_category = life_area_for_todoist_section(section_name)
    if section_category:
        return section_category

    todoist_section_name = str(task.get("todoist_section_name") or "").strip()
    todoist_section_category = life_area_for_todoist_section(todoist_section_name)
    if todoist_section_category:
        return todoist_section_category

    return "Misc"


def _todoist_task_section_for(task: dict[str, Any]) -> str:
    section_name = str(task.get("todoist_section_name") or task.get("section_name") or "").strip()
    canonical_section = LIFE_AREA_TO_TODOIST_SECTION.get(_task_section_for(task), LIFE_AREA_TO_TODOIST_SECTION["Misc"])
    if section_name in TODOIST_SECTION_TO_LIFE_AREA:
        return section_name
    return canonical_section


def _task_item(task: dict[str, Any], section: str) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "content": str(task.get("content") or ""),
        "description": task.get("description"),
        "section": section,
        "parent_id": task.get("parent_id"),
        "project_name": task.get("project_name"),
        "section_name": task.get("section_name"),
        "category": task.get("category") or task.get("project_category") or _task_section_for(task),
        "todoist_section_name": task.get("todoist_section_name") or task.get("section_name"),
        "todoist_section_id": task.get("todoist_section_id") or task.get("section_id"),
        "classification_source": task.get("classification_source") or "fallback",
        "due": task.get("due"),
        "due_date": task.get("due_date"),
        "due_status": task.get("due_status"),
        "priority": task.get("priority"),
        "todoist_priority": task.get("todoist_priority"),
        "completed": _task_completed(task),
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
    busy_events = [
        event
        for event in events
        if event.get("busy") and _calendar_event_category(event) != "informational"
    ]

    for index, first in enumerate(busy_events):
        first_start = datetime.fromisoformat(str(first["start"]))
        first_end = datetime.fromisoformat(str(first["end"]))
        for second in busy_events[index + 1:]:
            if not categories_conflict(
                _calendar_event_category(first),
                _calendar_event_category(second),
            ):
                continue

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


def _calendar_event_category(event: dict[str, Any]) -> str:
    category = event.get("event_category") or event.get("event_type")
    if category == "soft":
        return "informational"
    if category in {"hard", "flexible", "informational"}:
        return str(category)
    return "flexible"


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
                    source="todoist",
                    payload=action,
                )
            elif action_type == "create_calendar_event":
                event = action.get("event") or {}
                log_activity(
                    action_type="calendar_event_created",
                    title=f"Calendar event created: {event.get('title') or 'Calendar event'}",
                    detail=event.get("start"),
                    source="google_calendar",
                    payload=action,
                )
            elif action_type == "create_many_todoist_subtasks":
                parent_title = action.get("parent_task_title") or "Todoist parent task"
                log_activity(
                    action_type="subtasks_created",
                    title=f"Subtasks created: {parent_title}",
                    detail=f"{action.get('task_count') or 0} created",
                    source="todoist",
                    payload=action,
                )
            elif action_type == "update_calendar_event":
                event = action.get("event") or {}
                previous_event = action.get("previous_event") or {}
                log_activity(
                    action_type="calendar_event_updated",
                    title=f"Calendar event updated: {event.get('title') or previous_event.get('title') or 'Calendar event'}",
                    detail=event.get("start"),
                    source="google_calendar",
                    payload=action,
                )

        if response.get("needs_confirmation"):
            log_activity(
                action_type="confirmation_requested",
                title="Confirmation requested",
                detail=response.get("confirmation_prompt"),
                source="confirmation",
                payload=response.get("pending_action"),
            )
    except Exception:
        return
