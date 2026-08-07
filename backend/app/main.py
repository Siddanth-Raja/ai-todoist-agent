from datetime import date, datetime
from typing import Any, Literal

import requests
from fastapi import FastAPI
from fastapi import Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from .activity_domain import MeaningfulActivityEvent
from .agent import MODE, confirm_pending_action, handle_chat
from .action_executors import ActionExecutionContext
from .pending_actions import PendingActionError, pending_action_service
from .calendar_tools import check_google_auth, categories_conflict, list_upcoming_events
from .config import get_settings
from .dependency_evaluator import DependencySummary, EvaluatedDependencyEvidence
from .linear_client import LinearClient
from .gmail_client import GmailClient, personal_email_health_payload
from .gmail_organization import (
    GmailMutationGateRepository,
    GmailMutationGateState,
    GmailMutationGateStatus,
)
from .gmail_review import (
    GmailReadonlyReviewError,
    GmailReadonlyReviewService,
    GmailReadonlyReviewSurface,
    GmailReadonlySelectionPreview,
    GmailReadonlySelectionRequest,
)
from .morning_state import MorningStateSynthesis, morning_state_service
from .morning_corrections import (
    MorningCorrection,
    MorningCorrectionRequest,
    MorningCorrectionUndoRequest,
    ProviderMutationPreview,
    ProviderPreviewConfirmationRequest,
    ProviderPreviewRequest,
    morning_correction_repository,
    morning_correction_service,
    morning_provider_reconciliation_service,
)
from .project_brain import project_brain_service
from .project_activity_focus import ProjectActivityFocus
from .provider_changes import ChangeQueryResult
from .reality_reconciliation import RealityProjection
from .project_work_packages import LinearProjectDiagnostic, ProjectWorkPackage
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
    log_meaningful_activity,
    update_habit,
    update_memory_entry,
)
from .tasks_projection import tasks_projection_service
from .todoist_tools import list_todoist_sections
from .today_projection import today_projection_service


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
gmail_mutation_gate_repository = GmailMutationGateRepository()
gmail_readonly_review_service = GmailReadonlyReviewService()


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
    action_id: str = Field(..., min_length=1, max_length=128)
    expected_version: int = Field(..., ge=1)
    fingerprint: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    current_time: datetime | None = None


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
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    detail: str | None = Field(default=None, max_length=1000)
    source: str = Field(default="manual", min_length=1, max_length=80)
    metadata: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    meaningful_event: MeaningfulActivityEvent | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "ActivityCreate":
        if self.meaningful_event is not None:
            return self
        if not (self.action_type or self.type) or not self.title:
            raise ValueError(
                "legacy Activity requires a type/action_type and title; typed Activity requires meaningful_event"
            )
        return self


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
    meaningful_event: MeaningfulActivityEvent | None = None
    activity_schema_version: int | None = None
    legacy_unstructured: bool = True


class ConfirmCancelRequest(BaseModel):
    session_id: str | None = None
    action_id: str = Field(..., min_length=1, max_length=128)
    expected_version: int = Field(..., ge=1)
    fingerprint: str = Field(..., pattern=r"^[a-f0-9]{64}$")


class EmailTargetAdjustmentRequest(BaseModel):
    expected_version: int = Field(..., ge=1)
    fingerprint: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    selected_message_tokens: tuple[str, ...] = Field(min_length=1, max_length=1000)


class EmailActionExecutionResponse(BaseModel):
    action: dict[str, Any]
    undo_action: dict[str, Any] | None = None
    actions_taken: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@app.get(
    "/email/organization/gate",
    response_model=GmailMutationGateStatus,
)
def email_organization_gate(
    authorization: str | None = Header(default=None),
) -> GmailMutationGateStatus:
    """Expose only the durable credential-free gate; this never contacts Gmail."""
    require_agent_api_key(authorization)
    return gmail_mutation_gate_repository.status()


@app.get(
    "/email/organization/review",
    response_model=GmailReadonlyReviewSurface,
)
def email_organization_review(
    authorization: str | None = Header(default=None),
) -> GmailReadonlyReviewSurface:
    """Load one bounded, metadata-only Gmail review using the existing readonly token."""
    require_agent_api_key(authorization)
    return gmail_readonly_review_service.load(GmailClient(get_settings()))


@app.post(
    "/email/organization/review/selection",
    response_model=GmailReadonlySelectionPreview,
)
def seal_email_organization_review(
    request: GmailReadonlySelectionRequest,
    authorization: str | None = Header(default=None),
) -> GmailReadonlySelectionPreview:
    """Seal the exact selection and, after OAuth only, create its durable proposal."""
    require_agent_api_key(authorization)
    try:
        client = GmailClient(get_settings())
        if (
            gmail_mutation_gate_repository.status().state
            == GmailMutationGateState.LABEL_CANARY_REQUIRED
        ):
            sealed = gmail_readonly_review_service.build_canary_proposal(
                client,
                expected_snapshot_fingerprint=request.expected_snapshot_fingerprint,
                expected_selection_fingerprint=request.expected_selection_fingerprint,
                label_token=request.label_token,
                selected_message_tokens=request.selected_message_tokens,
                prior_review_message_tokens=request.prior_review_message_tokens,
            )
            pending_action_service.propose_typed(
                sealed.payload,
                confirmation_prompt=(
                    f"Apply the exact existing Gmail label to these "
                    f"{sealed.preview.exact_message_count} hand-reviewed Personal Email "
                    "messages only? No archive or read-state change is included."
                ),
                evidence=sealed.evidence,
                session_id="email-organization",
                source="sid_231_live_canary",
                source_ref=sealed.preview.selection_fingerprint,
                idempotency_key=sealed.idempotency_key,
            )
            return sealed.preview
        return gmail_readonly_review_service.seal_selection(
            client,
            expected_snapshot_fingerprint=request.expected_snapshot_fingerprint,
            expected_selection_fingerprint=request.expected_selection_fingerprint,
            label_token=request.label_token,
            selected_message_tokens=request.selected_message_tokens,
            prior_review_message_tokens=request.prior_review_message_tokens,
        )
    except GmailReadonlyReviewError as exc:
        status_code = 409 if exc.code == "stale_review" else 400
        if exc.code == "review_unavailable":
            status_code = 503
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/email/organization/actions/{action_id}/adjust")
def adjust_email_organization_targets(
    action_id: str,
    request: EmailTargetAdjustmentRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    try:
        record = pending_action_service.adjust_gmail_targets(
            action_id,
            expected_version=request.expected_version,
            expected_fingerprint=request.fingerprint,
            selected_message_tokens=request.selected_message_tokens,
        )
    except PendingActionError as exc:
        raise _pending_action_http_error(exc) from exc
    return pending_action_service.public_payload(record)


@app.post(
    "/email/organization/actions/{action_id}/confirm",
    response_model=EmailActionExecutionResponse,
)
def confirm_email_organization_action(
    action_id: str,
    request: ConfirmRequest,
    authorization: str | None = Header(default=None),
) -> EmailActionExecutionResponse:
    require_agent_api_key(authorization)
    if request.action_id != action_id:
        raise HTTPException(status_code=400, detail="Action identity does not match route.")
    settings = get_settings()
    local_now = (
        request.current_time.astimezone(settings.local_tz)
        if request.current_time
        else datetime.now(settings.local_tz)
    )
    try:
        record = pending_action_service.get(action_id)
        if record.provider != "gmail":
            raise PendingActionError(
                "provider_mismatch",
                "Email confirmation accepts only Gmail organization actions.",
            )
        execution = pending_action_service.confirm(
            action_id,
            expected_version=request.expected_version,
            expected_fingerprint=request.fingerprint,
            context=ActionExecutionContext(
                settings=settings,
                tasks=(),
                calendar_events=(),
                local_now=local_now,
            ),
        )
    except PendingActionError as exc:
        raise _pending_action_http_error(exc) from exc
    return EmailActionExecutionResponse(
        action=pending_action_service.public_payload(execution.record),
        undo_action=(
            pending_action_service.public_payload(execution.undo_record)
            if execution.undo_record
            else None
        ),
        actions_taken=list(execution.actions_taken),
        errors=list(execution.errors),
    )


class PendingActionRecovery(BaseModel):
    answer: str
    needs_confirmation: bool
    confirmation_prompt: str
    pending_action: dict[str, Any]


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


class TaskRecommendationEvidence(BaseModel):
    signal: str
    value: Any
    score_delta: float
    explanation: str


class TaskRecommendationAlternative(BaseModel):
    provider: str
    provider_record_id: str
    title: str
    task: TaskItem
    score: float
    action: str


class TaskRecommendationContext(BaseModel):
    current_time: datetime | None = None
    usable_free_block_minutes: int | None = None
    energy: str | None = None
    upcoming_commitment_title: str | None = None
    minutes_until_upcoming_commitment: int | None = None
    project_momentum_provider_record_ids: list[str] = Field(default_factory=list)


class TaskRecommendation(BaseModel):
    provider: str
    provider_record_id: str
    title: str
    task: TaskItem
    action: str
    score: float
    explanation: str
    evidence: list[TaskRecommendationEvidence]
    alternatives: list[TaskRecommendationAlternative]
    computed_at: datetime
    context: TaskRecommendationContext


class TaskAreaRecommendation(BaseModel):
    area: Literal["A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc"]
    section_name: str
    task_count: int
    state: Literal["recommended", "empty", "unavailable"]
    recommendation: TaskRecommendation | None = None


class TaskProviderState(BaseModel):
    name: Literal["todoist"]
    status: Literal["available", "degraded", "unavailable"]
    message: str | None = None


class TasksResponse(BaseModel):
    sections: list[TaskSection]
    recommendations: list[TaskAreaRecommendation]
    computed_at: datetime
    provider: TaskProviderState
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


class TodayWorkProviderState(BaseModel):
    provider: str
    provider_reference: str | None = None
    available: bool
    error: str | None = None


class TodayObligation(BaseModel):
    provider: str
    provider_record_id: str
    canonical_project_id: str | None = None
    title: str
    due_date: date
    due_at: datetime | None = None
    urgency: Literal["overdue", "due_today"]
    days_overdue: int
    priority: int
    provider_url: str | None = None


class TodayMustDo(BaseModel):
    state: Literal["available", "degraded", "unavailable"]
    items: list[TodayObligation] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    providers: list[TodayWorkProviderState] = Field(default_factory=list)


class TodayRecommendation(BaseModel):
    type: str
    source: Literal["calendar", "shared_recommendation", "fallback"] = "fallback"
    title: str
    detail: str
    reason: str | None = None
    task: dict[str, Any] | None = None
    event: TodayEvent | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    provider: str | None = None
    provider_record_id: str | None = None
    canonical_project_id: str | None = None
    canonical_project_key: str | None = None
    canonical_project_next_move: str | None = None
    contextual_override: bool = False


class LifeArea(BaseModel):
    name: str
    description: str
    project_key: str | None = None
    canonical_project_id: str | None = None
    status: str
    next_recommendation: str | None = None
    task_count: int
    overdue_count: int
    today_count: int
    high_priority_count: int
    provider_status: str | None = None
    provider_message: str | None = None
    degraded: bool = False


class TodayResponse(BaseModel):
    now: datetime
    now_display: str
    next_event: TodayEvent | None = None
    minutes_until_next_event: int | None = None
    current_free_block: TodayFreeBlock | None = None
    today_remaining_events: list[TodayEvent] = Field(default_factory=list)
    must_do: TodayMustDo
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
    attention_signals: list[ProjectBlocker] = Field(default_factory=list)
    dependency_summary: DependencySummary = Field(default_factory=DependencySummary)
    dependency_evidence: list[EvaluatedDependencyEvidence] = Field(default_factory=list)
    tasks: list[TaskItem] = Field(default_factory=list)
    task_groups: list[ProjectTaskGroup] = Field(default_factory=list)
    classification_diagnostics: list[ProjectTaskDiagnostic] = Field(default_factory=list)
    upcoming_events: list[CalendarEvent] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    memories: list[MemoryEntry] = Field(default_factory=list)
    recent_activity: list[ActivityEntry] = Field(default_factory=list)
    work_packages: list[ProjectWorkPackage] = Field(default_factory=list)
    linear_diagnostic: LinearProjectDiagnostic | None = None
    activity_focus: ProjectActivityFocus
    recent_changes: ChangeQueryResult
    reality: RealityProjection


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
            "personal_email": personal_email_health_payload(settings),
            "openai": _openai_health(settings),
            "linear": _linear_health(settings),
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


def _linear_health(settings) -> dict[str, Any]:
    result = LinearClient(settings).check_health()
    details = {"state": result.state}
    if result.error:
        details["error_code"] = result.error.code
        if result.error.http_status is not None:
            details["http_status"] = result.error.http_status
    if result.state == "not_configured":
        return _health_payload(
            status="warning",
            message="Linear is not configured. Set LINEAR_API_KEY to enable read access.",
            details=details,
        )
    if result.state == "connected":
        return _health_payload(
            status="ok",
            message="Connected to Linear with read access.",
            details=details,
        )
    if result.state == "authentication_failure":
        return _health_payload(
            status="error",
            message="Linear rejected the configured API key or its permissions.",
            details=details,
        )
    return _health_payload(
        status="error",
        message="Could not reach Linear or Linear returned an invalid provider response.",
        details=details,
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
            action_id=request.action_id,
            expected_version=request.expected_version,
            expected_fingerprint=request.fingerprint,
            current_time=request.current_time,
        )
    except PendingActionError as exc:
        raise _pending_action_http_error(exc) from exc

    _log_chat_activity(response)
    log_activity(
        action_type="confirmation_completed",
        title="Confirmation completed",
        detail=response.get("answer"),
        source="confirmation",
        payload={
            "session_id": request.session_id,
            "action_id": request.action_id,
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
    try:
        record = pending_action_service.cancel(
            request.action_id,
            expected_version=request.expected_version,
            expected_fingerprint=request.fingerprint,
        )
    except PendingActionError as exc:
        raise _pending_action_http_error(exc) from exc
    return log_activity(
        action_type="confirmation_cancelled",
        title="Confirmation cancelled",
        detail=record.confirmation_prompt,
        source="confirmation",
        payload={
            "session_id": request.session_id,
            "action_id": record.action_id,
            "lifecycle": record.lifecycle.value,
        },
    )


@app.get("/pending-actions/current", response_model=PendingActionRecovery | None)
def pending_action_current(
    session_id: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | None:
    require_agent_api_key(authorization)
    record = pending_action_service.current(session_id)
    if record is None:
        return None
    return {
        "answer": "A pending action was recovered. Review it before confirming.",
        "needs_confirmation": True,
        "confirmation_prompt": record.confirmation_prompt,
        "pending_action": pending_action_service.public_payload(record),
    }


def _pending_action_http_error(exc: PendingActionError) -> HTTPException:
    status = 404 if exc.code == "not_found" else 409
    if exc.code in {"invalid_payload", "invalid_confirmation_prompt"}:
        status = 400
    return HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc)},
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
    return tasks_projection_service.build(
        settings=get_settings(),
        current_time=current_time,
    )


@app.get("/today", response_model=TodayResponse)
def today_index(
    current_time: datetime | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    return today_projection_service.build(
        settings=get_settings(),
        current_time=current_time,
    )


@app.get("/morning-state", response_model=MorningStateSynthesis)
def morning_state_index(
    current_time: datetime | None = None,
    consumer_id: str = "morning-state",
    authorization: str | None = Header(default=None),
) -> MorningStateSynthesis:
    require_agent_api_key(authorization)
    normalized_consumer = consumer_id.strip()
    if not normalized_consumer or len(normalized_consumer) > 120:
        raise HTTPException(
            status_code=400,
            detail="consumer_id must contain 1 to 120 characters",
        )
    try:
        return morning_state_service.build(
            settings=get_settings(),
            current_time=current_time,
            consumer_id=normalized_consumer,
        )
    except ValueError as exc:
        if "timezone-aware" not in str(exc):
            raise
        raise HTTPException(
            status_code=400,
            detail="current_time must include an explicit timezone offset",
        ) from exc


@app.get("/morning-corrections", response_model=list[MorningCorrection])
def morning_correction_history(
    statement_id: str | None = None,
    canonical_project_id: str | None = None,
    authorization: str | None = Header(default=None),
) -> tuple[MorningCorrection, ...]:
    require_agent_api_key(authorization)
    return morning_correction_repository.list(
        statement_id=statement_id,
        canonical_project_id=canonical_project_id,
    )


@app.post("/morning-corrections", response_model=MorningCorrection)
def create_morning_correction(
    request: MorningCorrectionRequest,
    authorization: str | None = Header(default=None),
) -> MorningCorrection:
    require_agent_api_key(authorization)
    settings = get_settings()
    synthesis = morning_state_service.build(
        settings=settings,
        current_time=request.evaluated_at,
    )
    try:
        return morning_correction_service.create(
            request,
            synthesis=synthesis,
            created_at=datetime.now(settings.local_tz),
        )
    except ValueError as exc:
        message = str(exc)
        status = 409 if any(
            token in message
            for token in ("changed", "idempotency", "already", "superseded")
        ) else 400
        raise HTTPException(status_code=status, detail=message) from exc


@app.post(
    "/morning-corrections/{correction_id}/undo",
    response_model=MorningCorrection,
)
def undo_morning_correction(
    correction_id: str,
    request: MorningCorrectionUndoRequest,
    authorization: str | None = Header(default=None),
) -> MorningCorrection:
    require_agent_api_key(authorization)
    try:
        return morning_correction_repository.reverse(
            correction_id,
            request,
            reversed_at=datetime.now(get_settings().local_tz),
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message else 409
        raise HTTPException(status_code=status, detail=message) from exc


@app.post(
    "/morning-provider-reconciliation/preview",
    response_model=ProviderMutationPreview,
)
def preview_morning_provider_reconciliation(
    request: ProviderPreviewRequest,
    authorization: str | None = Header(default=None),
) -> ProviderMutationPreview:
    require_agent_api_key(authorization)
    settings = get_settings()
    synthesis = morning_state_service.build(
        settings=settings,
        current_time=request.evaluated_at,
    )
    try:
        return morning_provider_reconciliation_service.preview(
            request,
            synthesis=synthesis,
            created_at=datetime.now(settings.local_tz),
        )
    except ValueError as exc:
        message = str(exc)
        status = 409 if "changed" in message or "idempotency" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


@app.post(
    "/morning-provider-reconciliation/confirm",
    response_model=ProviderMutationPreview,
)
def confirm_morning_provider_reconciliation(
    request: ProviderPreviewConfirmationRequest,
    authorization: str | None = Header(default=None),
) -> ProviderMutationPreview:
    require_agent_api_key(authorization)
    try:
        return morning_provider_reconciliation_service.confirm(
            request,
            confirmed_at=datetime.now(get_settings().local_tz),
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message else 409
        raise HTTPException(status_code=status, detail=message) from exc


@app.get("/projects", response_model=list[ProjectBrain])
def projects_index(
    current_time: datetime | None = None,
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    require_agent_api_key(authorization)
    return project_brain_service.list_projects(
        settings=get_settings(),
        current_time=current_time,
    )


@app.get("/projects/{project_key}", response_model=ProjectBrain)
def project_detail(
    project_key: str,
    current_time: datetime | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    project = project_brain_service.get_project(
        project_key,
        settings=get_settings(),
        current_time=current_time,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


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
    if request.meaningful_event is not None:
        return log_meaningful_activity(request.meaningful_event)
    return log_activity(
        action_type=payload.get("action_type") or payload.get("type"),
        title=payload.get("title") or "Activity",
        detail=payload.get("detail") or payload.get("description"),
        source=payload.get("source") or "manual",
        payload=payload.get("payload") or payload.get("metadata"),
    )


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
