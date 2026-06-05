from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TIMEZONE = "America/Chicago"

# Load backend/.env first so local development works from either the repo root
# or the backend directory. load_dotenv() is kept as a fallback for deployed envs.
load_dotenv(BACKEND_DIR / ".env")
load_dotenv()


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None

    value = value.strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    todoist_api_token: str | None
    google_client_id: str | None
    google_client_secret: str | None
    google_refresh_token: str | None
    google_calendar_id: str
    timezone: str
    openai_api_key: str | None
    openai_model: str
    agent_api_key: str | None

    @property
    def local_tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def missing_todoist(self) -> bool:
        return not self.todoist_api_token

    @property
    def missing_google_calendar_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.google_client_id:
            missing.append("GOOGLE_CLIENT_ID")
        if not self.google_client_secret:
            missing.append("GOOGLE_CLIENT_SECRET")
        if not self.google_refresh_token:
            missing.append("GOOGLE_REFRESH_TOKEN")
        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    timezone = _optional_env("TIMEZONE") or DEFAULT_TIMEZONE

    # Validate early so calendar date math fails with a clear setup error.
    ZoneInfo(timezone)

    return Settings(
        todoist_api_token=_optional_env("TODOIST_API_TOKEN"),
        google_client_id=_optional_env("GOOGLE_CLIENT_ID"),
        google_client_secret=_optional_env("GOOGLE_CLIENT_SECRET"),
        google_refresh_token=_optional_env("GOOGLE_REFRESH_TOKEN"),
        google_calendar_id=_optional_env("GOOGLE_CALENDAR_ID") or "primary",
        timezone=timezone,
        openai_api_key=_optional_env("OPENAI_API_KEY"),
        openai_model=_optional_env("OPENAI_MODEL") or "gpt-4o-mini",
        agent_api_key=_optional_env("AGENT_API_KEY"),
    )


settings = get_settings()
