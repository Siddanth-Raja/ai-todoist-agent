from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import Settings


CALENDAR_READONLY_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CALENDAR_EVENT_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_SCOPES = [*CALENDAR_READONLY_SCOPES, *CALENDAR_EVENT_SCOPES]


@dataclass
class CalendarReadResult:
    events: list[dict[str, Any]]
    error: str | None = None


@dataclass
class CalendarWriteResult:
    event: dict[str, Any] | None = None
    error: str | None = None


def check_google_auth(settings: Settings) -> dict[str, Any]:
    """Diagnose Google Calendar OAuth without exposing secrets."""
    diagnostics: dict[str, Any] = {
        "calendar_id": settings.google_calendar_id,
        "configured_scopes": {
            "read": CALENDAR_READONLY_SCOPES,
            "write": CALENDAR_EVENT_SCOPES,
            "combined": CALENDAR_SCOPES,
        },
        "refresh_token_present": bool(settings.google_refresh_token),
        "token_refresh_succeeds": False,
        "calendar_read_succeeds": False,
        "calendar_write_scope_present": False,
        "first_calendar_name": None,
        "write_permission_status": "unknown",
        "errors": [],
    }

    missing_fields = settings.missing_google_calendar_fields
    if missing_fields:
        diagnostics["errors"].append(
            {
                "type": "missing_config",
                "message": f"Missing Google OAuth fields: {', '.join(missing_fields)}.",
            }
        )
        return diagnostics

    credentials = _build_credentials(settings)
    try:
        credentials.refresh(GoogleAuthRequest())
        diagnostics["token_refresh_succeeds"] = True
        diagnostics["granted_scopes"] = _safe_scopes(credentials)
    except RefreshError as exc:
        diagnostics["errors"].append(_format_refresh_error(exc))
        diagnostics["write_permission_status"] = "not_checked_refresh_failed"
        return diagnostics
    except Exception as exc:  # noqa: BLE001 - diagnostics should surface setup failures.
        diagnostics["errors"].append(
            {
                "type": exc.__class__.__name__,
                "message": str(exc),
                "explanation": "Google token refresh failed before Calendar API calls could run.",
            }
        )
        diagnostics["write_permission_status"] = "not_checked_refresh_failed"
        return diagnostics

    try:
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        calendar_list = service.calendarList().list(maxResults=1).execute()
        calendars = calendar_list.get("items") or []
        if calendars:
            diagnostics["first_calendar_name"] = calendars[0].get("summary")

        service.events().list(
            calendarId=settings.google_calendar_id,
            maxResults=1,
            singleEvents=True,
        ).execute()
        diagnostics["calendar_read_succeeds"] = True
    except HttpError as exc:
        diagnostics["errors"].append(_format_http_error(exc, "calendar_read"))
    except Exception as exc:  # noqa: BLE001 - diagnostics should surface setup failures.
        diagnostics["errors"].append(
            {
                "type": exc.__class__.__name__,
                "source": "calendar_read",
                "message": str(exc),
            }
        )

    try:
        target_calendar = service.calendarList().get(
            calendarId=settings.google_calendar_id
        ).execute()
        access_role = target_calendar.get("accessRole")
        diagnostics["calendar_write_scope_present"] = True
        diagnostics["write_permission_status"] = (
            "ok" if access_role in {"owner", "writer"} else f"calendar_access_role_{access_role}"
        )
    except RefreshError as exc:
        diagnostics["errors"].append(_format_refresh_error(exc, source="calendar_write_scope"))
        diagnostics["write_permission_status"] = "refresh_failed_for_write_scope"
    except HttpError as exc:
        diagnostics["errors"].append(_format_http_error(exc, "calendar_write_scope"))
        diagnostics["write_permission_status"] = "write_scope_or_calendar_permission_failed"
    except Exception as exc:  # noqa: BLE001 - diagnostics should surface setup failures.
        diagnostics["errors"].append(
            {
                "type": exc.__class__.__name__,
                "source": "calendar_write_scope",
                "message": str(exc),
            }
        )
        diagnostics["write_permission_status"] = "write_scope_check_failed"

    return diagnostics


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


def create_calendar_event(
    settings: Settings,
    title: str,
    start: datetime,
    end: datetime,
    existing_events: list[dict[str, Any]],
) -> CalendarWriteResult:
    """Create a simple calendar event if it does not conflict with busy events."""
    missing_fields = settings.missing_google_calendar_fields
    if missing_fields:
        joined = ", ".join(missing_fields)
        return CalendarWriteResult(
            error=f"{joined} missing. Add Google OAuth credentials to backend/.env to create Calendar events.",
        )

    if end <= start:
        return CalendarWriteResult(error="Calendar event end time must be after start time.")

    conflict = find_busy_conflict(start=start, end=end, events=existing_events)
    if conflict:
        return CalendarWriteResult(
            error=f"Calendar event conflicts with existing event: {conflict.get('title')}.",
        )

    body = {
        "summary": title,
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": settings.timezone,
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": settings.timezone,
        },
    }

    try:
        service = _build_calendar_service(settings)
        event = (
            service.events()
            .insert(calendarId=settings.google_calendar_id, body=body)
            .execute()
        )
    except HttpError as exc:
        status_code = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "resp", None), "status", "unknown"
        )
        return CalendarWriteResult(
            error=f"Could not create Google Calendar event. Google returned HTTP {status_code}.",
        )
    except Exception as exc:  # noqa: BLE001 - provider setup failures should surface clearly.
        return CalendarWriteResult(
            error=f"Could not create Google Calendar event: {exc.__class__.__name__}.",
        )

    return CalendarWriteResult(event=_normalize_event(event, settings.local_tz))


def find_busy_conflict(
    start: datetime,
    end: datetime,
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for event in events:
        if not event.get("busy"):
            continue

        event_start = datetime.fromisoformat(event["start"])
        event_end = datetime.fromisoformat(event["end"])
        if start < event_end and end > event_start:
            return event

    return None


def _build_calendar_service(settings: Settings):
    credentials = _build_credentials(settings)
    credentials.refresh(GoogleAuthRequest())
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _build_credentials(settings: Settings) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=settings.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=CALENDAR_SCOPES,
    )


def _safe_scopes(credentials: Credentials) -> list[str]:
    scopes = credentials.scopes or credentials._scopes or []
    return [str(scope) for scope in scopes]


def _format_refresh_error(
    exc: RefreshError,
    source: str = "token_refresh",
) -> dict[str, Any]:
    return {
        "type": "RefreshError",
        "source": source,
        "message": str(exc),
        "explanation": (
            "The Google refresh token could not be exchanged for an access token. "
            "It may be invalid, revoked, expired by OAuth testing-mode rules, tied "
            "to a different OAuth client, or missing the requested scope. Generate "
            "a new refresh token with the same GOOGLE_CLIENT_ID/SECRET and include "
            "the needed Calendar scopes."
        ),
    }


def _format_http_error(exc: HttpError, source: str) -> dict[str, Any]:
    status_code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "resp", None), "status", None
    )
    return {
        "type": "HttpError",
        "source": source,
        "status": status_code,
        "message": str(exc),
    }


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
