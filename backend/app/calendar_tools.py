from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import Settings


CALENDAR_READONLY_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


@dataclass
class CalendarReadResult:
    events: list[dict[str, Any]]
    error: str | None = None


def list_todays_events(
    settings: Settings,
    now: datetime | None = None,
) -> CalendarReadResult:
    """Read today's Google Calendar events in the configured local timezone."""
    missing_fields = settings.missing_google_calendar_fields
    if missing_fields:
        joined = ", ".join(missing_fields)
        return CalendarReadResult(
            events=[],
            error=f"{joined} missing. Add Google OAuth credentials to backend/.env to read Calendar events.",
        )

    local_tz = settings.local_tz
    local_now = now.astimezone(local_tz) if now else datetime.now(local_tz)
    start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    try:
        service = _build_calendar_service(settings)
        response = (
            service.events()
            .list(
                calendarId=settings.google_calendar_id,
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except HttpError as exc:
        status_code = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "resp", None), "status", "unknown"
        )
        return CalendarReadResult(
            events=[],
            error=f"Could not read Google Calendar events. Google returned HTTP {status_code}.",
        )
    except Exception as exc:  # noqa: BLE001 - provider setup failures should surface clearly.
        return CalendarReadResult(
            events=[],
            error=f"Could not read Google Calendar events: {exc.__class__.__name__}.",
        )

    raw_events = response.get("items", [])
    events = [_normalize_event(event, local_tz) for event in raw_events]
    events.sort(key=lambda event: event["start"])
    return CalendarReadResult(events=events)


def _build_calendar_service(settings: Settings):
    credentials = Credentials(
        token=None,
        refresh_token=settings.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=CALENDAR_READONLY_SCOPES,
    )
    credentials.refresh(GoogleAuthRequest())
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _normalize_event(event: dict[str, Any], local_tz) -> dict[str, Any]:
    start, start_is_all_day = _parse_google_time(event.get("start", {}), local_tz)
    end, end_is_all_day = _parse_google_time(event.get("end", {}), local_tz)
    all_day = start_is_all_day or end_is_all_day

    transparency = event.get("transparency") or "opaque"
    status = event.get("status") or "confirmed"
    busy = status != "cancelled" and transparency != "transparent"
    title = event.get("summary") or "(No title)"
    attendees = event.get("attendees") or []

    duration_minutes = max(0, int((end - start).total_seconds() // 60))

    return {
        "id": event.get("id"),
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": duration_minutes,
        "all_day": all_day,
        "transparency": transparency,
        "status": status,
        "busy": busy,
        "event_type": _infer_event_type(title, attendees),
        "attendees_count": len(attendees),
        "location": event.get("location"),
        "html_link": event.get("htmlLink"),
    }


def _parse_google_time(value: dict[str, Any], local_tz) -> tuple[datetime, bool]:
    if "dateTime" in value:
        parsed = datetime.fromisoformat(str(value["dateTime"]).replace("Z", "+00:00"))
        return parsed.astimezone(local_tz), False

    if "date" in value:
        parsed_date = date.fromisoformat(str(value["date"]))
        return datetime.combine(parsed_date, time.min, tzinfo=local_tz), True

    return datetime.now(local_tz), False


def _infer_event_type(title: str, attendees: list[dict[str, Any]]) -> str:
    text = title.lower()

    hard_keywords = (
        "meeting",
        "call",
        "class",
        "appointment",
        "interview",
        "exam",
        "doctor",
        "dentist",
    )
    flexible_keywords = (
        "gym",
        "work block",
        "deep work",
        "errand",
        "errands",
        "study block",
        "focus block",
    )
    soft_keywords = (
        "rest",
        "chill",
        "show",
        "watch",
        "buffer",
        "break",
    )

    if attendees or any(keyword in text for keyword in hard_keywords):
        return "hard"
    if any(keyword in text for keyword in flexible_keywords):
        return "flexible"
    if any(keyword in text for keyword in soft_keywords):
        return "soft"
    return "unknown"
