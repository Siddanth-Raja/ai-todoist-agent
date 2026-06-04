from dataclasses import dataclass
from typing import Any

import requests

from .config import Settings


TODOIST_API_BASE_URL = "https://api.todoist.com/api/v1"
REQUEST_TIMEOUT_SECONDS = 20
PAGE_LIMIT = 100


@dataclass
class TodoistReadResult:
    tasks: list[dict[str, Any]]
    error: str | None = None


def list_active_tasks(settings: Settings) -> TodoistReadResult:
    """Read active Todoist tasks and normalize fields used by the planner."""
    if settings.missing_todoist:
        return TodoistReadResult(
            tasks=[],
            error="TODOIST_API_TOKEN is missing. Add it to backend/.env to read Todoist tasks.",
        )

    try:
        projects = _fetch_projects(settings)
        raw_tasks = _fetch_paginated(settings, "tasks")
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        return TodoistReadResult(
            tasks=[],
            error=f"Could not read Todoist tasks. Todoist returned HTTP {status_code}.",
        )
    except requests.RequestException as exc:
        return TodoistReadResult(
            tasks=[],
            error=f"Could not read Todoist tasks: {exc.__class__.__name__}.",
        )

    tasks = [_normalize_task(task, projects) for task in raw_tasks]
    return TodoistReadResult(tasks=tasks)


def list_tasks(settings: Settings) -> TodoistReadResult:
    """Alias for the MVP read-only Todoist task reader."""
    return list_active_tasks(settings)


def _fetch_projects(settings: Settings) -> dict[str, str]:
    projects: dict[str, str] = {}
    for project in _fetch_paginated(settings, "projects"):
        project_id = project.get("id")
        project_name = project.get("name")
        if project_id and project_name:
            projects[str(project_id)] = str(project_name)

    return projects


def _fetch_paginated(settings: Settings, resource: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        params: dict[str, Any] = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{TODOIST_API_BASE_URL}/{resource}",
            headers=_auth_headers(settings),
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        # Todoist API v1 paginated endpoints return {"results": [...],
        # "next_cursor": ...}. Keeping this defensive also tolerates older
        # list-shaped responses if a fixture or mock uses them.
        if isinstance(payload, list):
            results.extend(payload)
            break

        results.extend(payload.get("results") or [])
        cursor = payload.get("next_cursor")
        if not cursor:
            break

    return results


def _auth_headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.todoist_api_token}",
        "Accept": "application/json",
    }


def _normalize_task(task: dict[str, Any], projects: dict[str, str]) -> dict[str, Any]:
    project_id = task.get("project_id")
    project_id_text = str(project_id) if project_id is not None else None
    task_id = str(task.get("id")) if task.get("id") is not None else None

    labels = task.get("labels") or []
    if not isinstance(labels, list):
        labels = []

    todoist_priority = int(task.get("priority") or 4)
    internal_priority = 5 - todoist_priority if 1 <= todoist_priority <= 4 else 1

    return {
        "id": task_id,
        "content": str(task.get("content") or "").strip(),
        "description": str(task.get("description") or "").strip(),
        "project_id": project_id_text,
        "project_name": projects.get(project_id_text) if project_id_text else None,
        "due": task.get("due"),
        "priority": internal_priority,
        "todoist_priority": todoist_priority,
        "labels": [str(label) for label in labels],
        "url": f"https://app.todoist.com/app/task/{task_id}" if task_id else None,
    }
