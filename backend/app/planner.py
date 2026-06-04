from datetime import date, datetime, time, timedelta
import re
from typing import Any


DEFAULT_ESTIMATED_DURATION_MINUTES = 30
MAX_RECOMMENDATIONS = 3

LOW_ENERGY_USER_KEYWORDS = (
    "lazy",
    "tired",
    "fried",
    "low energy",
    "exhausted",
    "burned out",
    "burnt out",
    "drained",
    "unmotivated",
    "no motivation",
    "don't feel like",
    "do not feel like",
    "chill",
    "don't feel like working",
    "do not feel like working",
)

HIGH_ENERGY_USER_KEYWORDS = (
    "energized",
    "locked in",
    "focused",
    "high energy",
    "motivated",
)

LOW_ENERGY_TASK_KEYWORDS = (
    "email",
    "reply",
    "respond",
    "follow up",
    "follow-up",
    "send",
    "check",
    "schedule",
    "buy",
    "order",
    "admin",
    "text",
    "call",
    "organize",
    "organizing",
    "migrate",
    "migration",
)

HIGH_ENERGY_TASK_KEYWORDS = (
    "build",
    "code",
    "implement",
    "study",
    "write",
    "draft",
    "design",
    "research",
    "proposal",
    "finish",
    "deep work",
    "prototype",
    "environment",
    "agent",
    "context control",
)

QUICK_TASK_KEYWORDS = (
    "email",
    "reply",
    "respond",
    "follow up",
    "follow-up",
    "send",
    "text",
    "call",
    "check",
    "schedule",
    "buy",
    "order",
    "organize",
    "organizing",
    "migrate",
    "migration",
)

LONG_TASK_KEYWORDS = (
    "build",
    "code",
    "implement",
    "study",
    "write",
    "draft",
    "design",
    "research",
    "proposal",
    "prototype",
    "environment",
)

SHOPPING_KEYWORDS = (
    "buy",
    "order",
    "purchase",
    "need",
    "pick up",
    "socks",
    "shoes",
    "groceries",
)

PERSONAL_KEYWORDS = (
    "gym",
    "workout",
    "doctor",
    "dentist",
    "health",
    "laundry",
    "rent",
    "home",
    "clean",
    "family",
    "notion migration",
    "notion",
    "organize",
    "organizing",
    "productivity",
)

FREELANCE_KEYWORDS = (
    "client",
    "clients",
    "invoice",
    "proposal",
    "contract",
    "deliverable",
    "freelance",
    "outreach",
    "business",
    "law firm",
    "law firms",
)

XO_KEYWORDS = (
    "vr",
    "headset",
    "prototype",
    "environment",
)

NEBULO_KEYWORDS = (
    "nebulo",
    "agent",
    "context control",
)

AM_KEYWORDS = (
    "a&m",
    "a and m",
    "college",
    "transcript",
    "housing",
)

DURATION_MINUTE_RE = re.compile(r"\b(\d{1,3})\s*(m|min|mins|minute|minutes)\b", re.IGNORECASE)
DURATION_HOUR_RE = re.compile(r"\b(\d{1,2})\s*(h|hr|hrs|hour|hours)\b", re.IGNORECASE)


def build_plan(
    tasks: list[dict[str, Any]],
    calendar_events: list[dict[str, Any]],
    message: str,
    local_tz,
    now: datetime | None = None,
    calendar_available: bool = True,
) -> dict[str, Any]:
    local_now = now.astimezone(local_tz) if now else datetime.now(local_tz)
    user_energy = infer_user_energy(message)
    free_block = (
        find_current_or_next_free_block(calendar_events, local_now)
        if calendar_available
        else None
    )
    focus_category = (
        infer_focus_category(calendar_events, local_now) if calendar_available else None
    )

    enriched_tasks = [enrich_task(task, local_now.date()) for task in tasks]
    enriched_tasks = [task for task in enriched_tasks if task.get("content")]

    ranked_tasks = rank_tasks(
        enriched_tasks,
        free_block=free_block,
        user_energy=user_energy,
        focus_category=focus_category,
        today=local_now.date(),
    )

    recommendation_limit = 1 if user_energy == "low" else MAX_RECOMMENDATIONS

    return {
        "now": local_now.isoformat(),
        "user_energy": user_energy,
        "free_block": free_block,
        "focus_category": focus_category,
        "recommended_tasks": ranked_tasks[:recommendation_limit],
    }


def enrich_task(task: dict[str, Any], today: date) -> dict[str, Any]:
    content = str(task.get("content") or "").strip()
    labels = task.get("labels") or []
    project_name = task.get("project_name")
    combined_text = " ".join(
        [
            content,
            str(task.get("description") or ""),
            str(project_name or ""),
            " ".join(str(label) for label in labels),
        ]
    )

    due_date = extract_due_date(task.get("due"))

    enriched = dict(task)
    enriched["category"] = infer_project_category(
        content=content,
        project_name=project_name,
        labels=labels,
    )
    enriched["estimated_duration"] = infer_estimated_duration(combined_text)
    enriched["energy_level"] = infer_task_energy(combined_text)
    enriched["due_date"] = due_date.isoformat() if due_date else None
    enriched["due_status"] = classify_due_status(due_date, today)
    return enriched


def rank_tasks(
    tasks: list[dict[str, Any]],
    free_block: dict[str, Any] | None,
    user_energy: str,
    focus_category: str | None,
    today: date,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []

    for task in tasks:
        score, reasons = score_task(
            task=task,
            free_block=free_block,
            user_energy=user_energy,
            focus_category=focus_category,
            today=today,
        )
        ranked.append(
            {
                "id": task.get("id"),
                "content": task.get("content"),
                "project_id": task.get("project_id"),
                "project_name": task.get("project_name"),
                "category": task.get("category"),
                "due": task.get("due"),
                "due_date": task.get("due_date"),
                "due_status": task.get("due_status"),
                "priority": task.get("priority"),
                "labels": task.get("labels") or [],
                "url": task.get("url"),
                "estimated_duration": task.get("estimated_duration"),
                "energy_level": task.get("energy_level"),
                "score": round(score, 2),
                "reasons": reasons[:3],
                "explanation": format_task_explanation(reasons),
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def score_task(
    task: dict[str, Any],
    free_block: dict[str, Any] | None,
    user_energy: str,
    focus_category: str | None,
    today: date,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    due_date = extract_due_date(task.get("due"))
    if due_date:
        days_until_due = (due_date - today).days
        if days_until_due < 0:
            score += 100
            reasons.append("overdue")
        elif days_until_due == 0:
            score += 80
            reasons.append("due today")
        elif days_until_due == 1:
            score += 50
            reasons.append("due tomorrow")
        elif days_until_due <= 7:
            score += 20
            reasons.append("due this week")

    priority = int(task.get("priority") or 1)
    if priority >= 4:
        score += 40
        reasons.append("high Todoist priority")
    elif priority == 3:
        score += 25
        reasons.append("medium-high Todoist priority")
    elif priority == 2:
        score += 10

    estimated_duration = int(task.get("estimated_duration") or DEFAULT_ESTIMATED_DURATION_MINUTES)
    free_minutes = int(free_block["duration_minutes"]) if free_block else None
    if free_minutes is not None:
        if estimated_duration <= free_minutes:
            score += 25
            reasons.append("fits your available time")
        elif estimated_duration <= free_minutes + 15:
            score += 5
            reasons.append("almost fits the available time")
        else:
            score -= 30

    task_energy = task.get("energy_level") or "medium"
    if user_energy == "low":
        if task_energy == "low":
            score += 60
            reasons.append("low-energy friendly")
        elif task_energy == "high":
            if due_date and due_date <= today:
                reasons.append("higher effort, but time-sensitive")
            else:
                score -= 70

        if estimated_duration <= 20:
            score += 45
            reasons.append("tiny enough to count as a win")
        elif estimated_duration <= 30:
            score += 20
            reasons.append("small enough to start now")
        elif estimated_duration > 45:
            score -= 35
    elif user_energy == "high" and task_energy == "high":
        score += 15
        reasons.append("matches high-energy focus")

    category = task.get("category")
    if focus_category and category == focus_category and category != "Misc":
        score += 20
        reasons.append(f"matches the {focus_category} calendar focus")

    if not reasons:
        reasons.append("reasonable next task")

    return score, reasons


def find_current_or_next_free_block(
    calendar_events: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any] | None:
    end_of_day = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
    free_start = now
    started_now = True

    for event in _busy_events(calendar_events):
        event_start = datetime.fromisoformat(event["start"])
        event_end = datetime.fromisoformat(event["end"])

        if event_end <= free_start:
            continue

        if event_start <= free_start < event_end:
            free_start = event_end
            started_now = False
            continue

        if event_start > free_start:
            return _format_free_block(
                start=free_start,
                end=min(event_start, end_of_day),
                now=now,
                is_current=started_now,
            )

    if free_start < end_of_day:
        return _format_free_block(
            start=free_start,
            end=end_of_day,
            now=now,
            is_current=started_now,
        )

    return None


def infer_focus_category(
    calendar_events: list[dict[str, Any]],
    now: datetime,
) -> str | None:
    for event in _busy_events(calendar_events):
        event_start = datetime.fromisoformat(event["start"])
        event_end = datetime.fromisoformat(event["end"])
        if event_start <= now < event_end:
            category = infer_category_from_text(str(event.get("title") or ""))
            return category if category != "Misc" else None

    return None


def infer_user_energy(message: str) -> str:
    text = message.lower()
    if any(keyword in text for keyword in LOW_ENERGY_USER_KEYWORDS):
        return "low"
    if any(keyword in text for keyword in HIGH_ENERGY_USER_KEYWORDS):
        return "high"
    return "medium"


def infer_project_category(
    content: str,
    project_name: str | None,
    labels: list[str],
) -> str:
    text = " ".join([content, project_name or "", " ".join(labels)])
    return infer_category_from_text(text)


def infer_category_from_text(text: str) -> str:
    lowered = text.lower()

    if any(keyword in lowered for keyword in AM_KEYWORDS):
        return "A&M"
    if re.search(r"\bxo\b", lowered):
        return "XO"
    if any(keyword in lowered for keyword in XO_KEYWORDS):
        return "XO"
    if any(keyword in lowered for keyword in NEBULO_KEYWORDS):
        return "Nebulo"
    if "freelance" in lowered or any(keyword in lowered for keyword in FREELANCE_KEYWORDS):
        return "Freelance"
    if any(keyword in lowered for keyword in SHOPPING_KEYWORDS):
        return "Misc"
    if "personal" in lowered or any(keyword in lowered for keyword in PERSONAL_KEYWORDS):
        return "Personal"
    return "Misc"


def infer_estimated_duration(text: str) -> int:
    explicit_duration = extract_explicit_duration(text)
    if explicit_duration:
        return explicit_duration

    lowered = text.lower()
    if any(keyword in lowered for keyword in QUICK_TASK_KEYWORDS):
        return 15
    if any(keyword in lowered for keyword in LONG_TASK_KEYWORDS):
        return 60
    return DEFAULT_ESTIMATED_DURATION_MINUTES


def extract_explicit_duration(text: str) -> int | None:
    minute_match = DURATION_MINUTE_RE.search(text)
    if minute_match:
        return int(minute_match.group(1))

    hour_match = DURATION_HOUR_RE.search(text)
    if hour_match:
        return int(hour_match.group(1)) * 60

    return None


def infer_task_energy(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in LOW_ENERGY_TASK_KEYWORDS):
        return "low"
    if any(keyword in lowered for keyword in HIGH_ENERGY_TASK_KEYWORDS):
        return "high"
    return "medium"


def extract_due_date(due: Any) -> date | None:
    if not isinstance(due, dict):
        return None

    datetime_text = due.get("datetime")
    if datetime_text:
        try:
            parsed = datetime.fromisoformat(str(datetime_text).replace("Z", "+00:00"))
            return parsed.date()
        except ValueError:
            return None

    date_text = due.get("date")
    if date_text:
        try:
            return date.fromisoformat(str(date_text))
        except ValueError:
            return None

    return None


def classify_due_status(due_date: date | None, today: date) -> str | None:
    if not due_date:
        return None

    days_until_due = (due_date - today).days
    if days_until_due < 0:
        return "overdue"
    if days_until_due == 0:
        return "today"
    if days_until_due == 1:
        return "tomorrow"
    if days_until_due <= 7:
        return "this_week"
    return "later"


def format_task_explanation(reasons: list[str]) -> str:
    if not reasons:
        return "Reasonable next task."

    selected = reasons[:2]
    if len(selected) == 1:
        return selected[0].capitalize() + "."
    return selected[0].capitalize() + " and " + selected[1] + "."


def _busy_events(calendar_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = [event for event in calendar_events if event.get("busy")]
    events.sort(key=lambda event: event["start"])
    return events


def _format_free_block(
    start: datetime,
    end: datetime,
    now: datetime,
    is_current: bool,
) -> dict[str, Any] | None:
    duration_minutes = max(0, int((end - start).total_seconds() // 60))
    if duration_minutes <= 0:
        return None

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": duration_minutes,
        "is_current": is_current and start <= now + timedelta(seconds=1),
    }
