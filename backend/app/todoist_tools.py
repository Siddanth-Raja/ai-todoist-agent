from dataclasses import dataclass
import uuid
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


@dataclass
class TodoistWriteResult:
    task: dict[str, Any] | None = None
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


def create_task(
    settings: Settings,
    content: str,
    project_id: str | None = None,
    project_name: str | None = None,
    section_id: str | None = None,
    section_name: str | None = None,
    due_string: str | None = None,
    labels: list[str] | None = None,
    priority: int | None = None,
) -> TodoistWriteResult:
    """Create a simple Todoist task. Used only after the agent allows it."""
    if settings.missing_todoist:
        return TodoistWriteResult(
            error="TODOIST_API_TOKEN is missing. Add it to backend/.env to create Todoist tasks.",
        )

    try:
        projects: dict[str, str] | None = None
        sections: dict[str, str] | None = None

        if project_name and not project_id:
            projects = _fetch_projects(settings)
            project_id = _find_id_by_name(projects, project_name)

        if section_name and not section_id:
            sections = _fetch_sections(settings, project_id=project_id)
            section_id = _find_id_by_name(sections, section_name)

        payload: dict[str, Any] = {"content": content}
        if project_id:
            payload["project_id"] = project_id
        if section_id:
            payload["section_id"] = section_id
        if due_string:
            payload["due_string"] = due_string
        if labels:
            payload["labels"] = labels
        if priority:
            payload["priority"] = max(1, min(4, priority))

        response = requests.post(
            f"{TODOIST_API_BASE_URL}/tasks",
            headers={
                **_auth_headers(settings),
                "Content-Type": "application/json",
                "X-Request-Id": str(uuid.uuid4()),
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if projects is None:
            projects = _fetch_projects(settings)
        if sections is None and (section_id or section_name):
            sections = _fetch_sections(settings, project_id=project_id)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        return TodoistWriteResult(
            error=f"Could not create Todoist task. Todoist returned HTTP {status_code}.",
        )
    except requests.RequestException as exc:
        return TodoistWriteResult(
            error=f"Could not create Todoist task: {exc.__class__.__name__}.",
        )

    return TodoistWriteResult(task=_normalize_task(response.json(), projects, sections))


def _fetch_projects(settings: Settings) -> dict[str, str]:
    projects: dict[str, str] = {}
    for project in _fetch_paginated(settings, "projects"):
        project_id = project.get("id")
        project_name = project.get("name")
        if project_id and project_name:
            projects[str(project_id)] = str(project_name)

    return projects


def _fetch_sections(settings: Settings, project_id: str | None = None) -> dict[str, str]:
    sections: dict[str, str] = {}
    params = {"project_id": project_id} if project_id else None
    for section in _fetch_paginated(settings, "sections", extra_params=params):
        section_id = section.get("id")
        section_name = section.get("name")
        if section_id and section_name:
            sections[str(section_id)] = str(section_name)

    return sections


def _find_id_by_name(items: dict[str, str], name: str) -> str | None:
    normalized_name = name.strip().lower()
    for item_id, item_name in items.items():
        if item_name.strip().lower() == normalized_name:
            return item_id

    return None


def _fetch_paginated(
    settings: Settings,
    resource: str,
    extra_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        params: dict[str, Any] = {"limit": PAGE_LIMIT}
        if extra_params:
            params.update(extra_params)
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


def _normalize_task(
    task: dict[str, Any],
    projects: dict[str, str],
    sections: dict[str, str] | None = None,
) -> dict[str, Any]:
    project_id = task.get("project_id")
    project_id_text = str(project_id) if project_id is not None else None
    section_id = task.get("section_id")
    section_id_text = str(section_id) if section_id is not None else None
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
        "section_id": section_id_text,
        "section_name": sections.get(section_id_text) if sections and section_id_text else None,
        "due": task.get("due"),
        "priority": internal_priority,
        "todoist_priority": todoist_priority,
        "labels": [str(label) for label in labels],
        "url": f"https://app.todoist.com/app/task/{task_id}" if task_id else None,
    }
