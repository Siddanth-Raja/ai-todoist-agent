from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi import Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import MODE, handle_chat
from .config import get_settings


app = FastAPI(
    title="Personal Chief of Staff",
    description="Read-only planning MVP for Todoist and Google Calendar.",
    version="0.1.0",
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


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_agent_api_key(authorization)
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be blank")

    return handle_chat(message=message, current_time=request.current_time)
