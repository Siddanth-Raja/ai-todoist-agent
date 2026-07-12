from datetime import datetime
import re
from typing import Any

from .calendar_tools import list_upcoming_events
from .planner import enrich_task, rank_tasks
from .project_registry import (
    ProjectRegistrySnapshot,
    project_registry_service,
)
from .storage import list_activity, list_memory_entries
from .todoist_tools import (
    LIFE_AREA_TO_TODOIST_SECTION,
    TODOIST_SECTION_TO_LIFE_AREA,
    life_area_for_todoist_section,
    list_active_tasks,
)


BLOCKER_WORDS = ("blocked", "blocking", "waiting", "review", "feedback")
FOLLOW_UP_WORDS = ("follow up", "follow-up", "waiting", "pending", "review", "feedback")


class ProjectBrainService:
    def __init__(self, registry_service=project_registry_service):
        self.registry_service = registry_service

    def list_projects(self, *, settings: Any, current_time: datetime | None = None) -> list[dict[str, Any]]:
        registry = self.registry_service.snapshot()
        local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)
        todoist_result = list_active_tasks(settings)
        tasks = [
            enrich_task(task, local_now.date())
            for task in todoist_result.tasks
            if task.get("content")
        ]
        calendar_result = list_upcoming_events(settings, now=current_time, days=14)
        events = _future_events(calendar_result.events, local_now)
        memories = [memory for memory in list_memory_entries() if memory.get("enabled")]
        activity = list_activity(limit=200)

        return [
            self.build_project(
                project=project,
                tasks=tasks,
                events=events,
                memories=memories,
                activity=activity,
                now=local_now,
                registry=registry,
            )
            for project in registry.projects
        ]

    def get_project(
        self,
        project_key: str,
        *,
        settings: Any,
        current_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        registry = self.registry_service.snapshot()
        canonical_key = registry.resolve_key(project_key)
        local_now = current_time.astimezone(settings.local_tz) if current_time else datetime.now(settings.local_tz)
        todoist_result = list_active_tasks(settings)
        tasks = [
            enrich_task(task, local_now.date())
            for task in todoist_result.tasks
            if task.get("content")
        ]
        calendar_result = list_upcoming_events(settings, now=current_time, days=14)
        events = _future_events(calendar_result.events, local_now)
        memories = [memory for memory in list_memory_entries() if memory.get("enabled")]
        activity = list_activity(limit=200)
        return next(
            (
                self.build_project(
                    project=project,
                    tasks=tasks,
                    events=events,
                    memories=memories,
                    activity=activity,
                    now=local_now,
                    registry=registry,
                )
                for project in registry.projects
                if project["key"] == canonical_key
            ),
            None,
        )

    def canonical_project_key(self, project_key: str) -> str:
        return self.registry_service.snapshot().resolve_key(project_key)

    def build_project(
        self,
        *,
        project: dict[str, Any],
        tasks: list[dict[str, Any]],
        events: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        activity: list[dict[str, Any]],
        now: datetime,
        registry: ProjectRegistrySnapshot | None = None,
    ) -> dict[str, Any]:
        registry = registry or self.registry_service.snapshot()
        task_lookup = {str(task.get("id")): task for task in tasks if task.get("id")}
        active_tasks = [task for task in tasks if not _task_completed(task)]
        active_children_by_parent = _children_by_parent(active_tasks)
        project_tasks = [
            task
            for task in active_tasks
            if _task_matches_project(task, project, registry, task_lookup)
        ]
        project_events = [
            event for event in events if _event_matches_project(event, project, registry)
        ]
        project_memories = [
            memory for memory in memories if _memory_matches_project(memory, project, registry)
        ]
        project_activity = [
            entry for entry in activity if _activity_matches_project(entry, project, registry)
        ]
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
            "tasks": [_task_item(task, _todoist_task_section_for(task)) for task in sorted_tasks[:12]],
            "task_groups": task_groups[:12],
            "classification_diagnostics": _project_task_diagnostics(
                project=project,
                tasks=tasks,
                task_lookup=task_lookup,
                active_children_by_parent=active_children_by_parent,
                registry=registry,
            ),
            "upcoming_events": [_project_event_item(event) for event in sorted_events[:8]],
            "people": people,
            "memories": project_memories[:8],
            "recent_activity": project_activity[:8],
        }


project_brain_service = ProjectBrainService()


def _task_matches_project(
    task: dict[str, Any],
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
    task_lookup: dict[str, dict[str, Any]] | None = None,
) -> bool:
    parent = _parent_task(task, task_lookup or {})
    if project.get("classification_bucket"):
        return _task_needs_classification(task, parent=parent, registry=registry)
    life_area = project.get("life_area")
    if life_area and _task_section_for(task) == life_area:
        return True
    if parent and life_area and _task_section_for(parent) == life_area:
        return True
    if parent and _text_matches_project(_task_match_text(parent), project):
        return True
    return _text_matches_project(_task_match_text(task), project)


def _event_matches_project(
    event: dict[str, Any],
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
) -> bool:
    explicit_project = event.get("resolved_project") or event.get("project") or event.get("project_key")
    if explicit_project:
        explicit = registry.resolve_key(str(explicit_project))
        if explicit == project["key"] or _slug_text(str(explicit_project)) == _slug_text(project["name"]):
            return True
    title = str(event.get("title") or "")
    prefix_match = re.match(r"^(.+?)\s+[\u2014-]\s+", title)
    if prefix_match and registry.resolve_key(prefix_match.group(1)) == project["key"]:
        return True
    return _text_matches_project(_event_match_text(event), project)


def _memory_matches_project(
    memory: dict[str, Any],
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
) -> bool:
    memory_type = str(memory.get("type") or "").lower()
    title = str(memory.get("title") or "")
    if memory_type == "project" and _same_project_name(title, project, registry):
        return True
    if memory_type in {"person", "group"} and _slug_text(title) in {
        _slug_text(person) for person in project.get("people", ())
    }:
        return True
    return _text_matches_project(_memory_match_text(memory), project)


def _activity_matches_project(
    entry: dict[str, Any],
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
) -> bool:
    payload = entry.get("payload") or entry.get("metadata") or {}
    if isinstance(payload, dict):
        payload_project = payload.get("resolved_project") or payload.get("project") or payload.get("project_key") or payload.get("project_context")
        task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
        event_payload = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        section_name = task_payload.get("section_name") or task_payload.get("todoist_section_name") or payload.get("section_name")
        if payload_project and registry.resolve_key(str(payload_project)) == project["key"]:
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
    return any(_contains_phrase(normalized, str(value)) for value in (*project.get("keywords", ()), *project.get("people", ())))


def _same_project_name(
    value: str,
    project: dict[str, Any],
    registry: ProjectRegistrySnapshot,
) -> bool:
    return registry.resolve_key(value) == project["key"] or _slug_text(value) == _slug_text(project["name"])


def _project_people(project: dict[str, Any], memories: list[dict[str, Any]]) -> list[str]:
    people = {str(person) for person in project.get("people", ())}
    people.update(
        str(memory.get("title") or "").strip()
        for memory in memories
        if str(memory.get("type") or "").lower() == "person" and str(memory.get("title") or "").strip()
    )
    return sorted(people)


def _children_by_parent(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    children: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        parent_id = str(task.get("parent_id") or "").strip()
        if parent_id:
            children.setdefault(parent_id, []).append(task)
    return children


def _parent_task(task: dict[str, Any], task_lookup: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    parent_id = str(task.get("parent_id") or "").strip()
    return task_lookup.get(parent_id) if parent_id else None


def _task_completed(task: dict[str, Any]) -> bool:
    return bool(task.get("completed") or task.get("is_completed") or task.get("checked"))


def _task_is_container(task: dict[str, Any], active_children_by_parent: dict[str, list[dict[str, Any]]]) -> bool:
    task_id = str(task.get("id") or "")
    return bool(active_children_by_parent.get(task_id)) and not _task_explicitly_completeable(task)


def _task_explicitly_completeable(task: dict[str, Any]) -> bool:
    labels = {str(label).strip().lower() for label in task.get("labels") or []}
    if {"completeable", "completable", "leaf-task"} & labels:
        return True
    text = _normalize_text(f"{task.get('content') or ''} {task.get('description') or ''}")
    return "[completeable]" in text or "[completable]" in text


def _project_leaf_tasks(tasks: list[dict[str, Any]], active_children_by_parent: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [task for task in tasks if not _task_completed(task) and not _task_is_container(task, active_children_by_parent)]


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


def _project_task_groups(tasks: list[dict[str, Any]], task_lookup: dict[str, dict[str, Any]], active_children_by_parent: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    tasks_by_id = {str(task.get("id")): task for task in tasks if task.get("id")}
    grouped_parent_ids = {str(task.get("parent_id")) for task in tasks if task.get("parent_id") and str(task.get("parent_id")) in task_lookup}
    roots = [task for task in tasks if not task.get("parent_id") or str(task.get("id")) in grouped_parent_ids]
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
        subtasks = [task for task in active_children_by_parent.get(parent_id, []) if str(task.get("id") or "") in tasks_by_id]
        groups.append({
            "parent_task": _task_item(parent, _todoist_task_section_for(parent)),
            "subtasks": [_task_item(task, _todoist_task_section_for(task)) for task in _sort_project_tasks(subtasks)],
            "is_container": _task_is_container(parent, active_children_by_parent),
        })
    return groups


def _project_task_diagnostics(
    *,
    project: dict[str, Any],
    tasks: list[dict[str, Any]],
    task_lookup: dict[str, dict[str, Any]],
    active_children_by_parent: dict[str, list[dict[str, Any]]],
    registry: ProjectRegistrySnapshot,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for task in _sort_project_tasks(tasks):
        parent = _parent_task(task, task_lookup)
        included = _task_matches_project(task, project, registry, task_lookup) and not _task_completed(task)
        diagnostics.append({
            "task_title": str(task.get("content") or "Untitled task"),
            "parent_title": str(parent.get("content")) if parent else None,
            "todoist_section": task.get("todoist_section_name") or task.get("section_name"),
            "resolved_project": _resolved_project_name_for_task(task, task_lookup, registry),
            "priority": task.get("todoist_priority") or task.get("priority"),
            "included": included,
            "reason": _task_diagnostic_reason(
                task=task,
                project=project,
                parent=parent,
                included=included,
                active_children_by_parent=active_children_by_parent,
                registry=registry,
            ),
        })
    return diagnostics


def _task_diagnostic_reason(
    *,
    task: dict[str, Any],
    project: dict[str, Any],
    parent: dict[str, Any] | None,
    included: bool,
    active_children_by_parent: dict[str, list[dict[str, Any]]],
    registry: ProjectRegistrySnapshot,
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
    if parent and _task_needs_classification(task, parent=parent, registry=registry):
        return "excluded: needs classification"
    return "excluded: matched another project or no project signal"


def _resolved_project_name_for_task(
    task: dict[str, Any],
    task_lookup: dict[str, dict[str, Any]],
    registry: ProjectRegistrySnapshot,
) -> str:
    parent = _parent_task(task, task_lookup)
    for project in registry.projects:
        if not project.get("classification_bucket") and _task_matches_project(
            task,
            project,
            registry,
            task_lookup,
        ):
            return str(project["name"])
    return (
        "Needs Classification"
        if _task_needs_classification(task, parent=parent, registry=registry)
        else "Uncategorized"
    )


def _task_needs_classification(
    task: dict[str, Any],
    *,
    parent: dict[str, Any] | None,
    registry: ProjectRegistrySnapshot,
) -> bool:
    if parent:
        for project in registry.projects:
            if not project.get("classification_bucket") and _task_matches_project(
                parent,
                project,
                registry,
                {},
            ):
                return False
    if _task_section_for(task) != "Misc":
        return False
    return not any(
        not project.get("classification_bucket") and _text_matches_project(_task_match_text(task), project)
        for project in registry.projects
    )


def _project_blockers(*, project: dict[str, Any], tasks: list[dict[str, Any]], events: list[dict[str, Any]], ranked_tasks: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for task in tasks:
        content = str(task.get("content") or "Untitled task")
        if task.get("due_status") == "overdue":
            blockers.append({"type": "overdue_task", "title": content, "detail": "Overdue Todoist task", "severity": "critical", "source_id": task.get("id")})
        if _is_stale_high_priority_task(task, now):
            blockers.append({"type": "stale_high_priority_task", "title": content, "detail": "High-priority task has been open for more than 7 days", "severity": "warning", "source_id": task.get("id")})
        blocker_word = _first_matching_phrase(_task_match_text(task), BLOCKER_WORDS)
        if blocker_word:
            blockers.append({"type": "blocked_task", "title": content, "detail": f"Task mentions {blocker_word}", "severity": "warning", "source_id": task.get("id")})
    for event in events:
        follow_up_word = _first_matching_phrase(_event_match_text(event), FOLLOW_UP_WORDS)
        if follow_up_word:
            blockers.append({"type": "pending_meeting_follow_up", "title": str(event.get("title") or "Calendar event"), "detail": f"Upcoming event mentions {follow_up_word}", "severity": "warning", "source_id": event.get("id")})
    if events and not ranked_tasks:
        blockers.append({"type": "empty_next_step", "title": "No next task before upcoming event", "detail": f"{project['name']} has calendar context but no matching Todoist next step", "severity": "warning", "source_id": None})
    return _dedupe_blockers(blockers)


def _project_status(*, blockers: list[dict[str, Any]], tasks: list[dict[str, Any]], events: list[dict[str, Any]]) -> str:
    if any(blocker.get("severity") == "critical" for blocker in blockers):
        return "Blocked"
    if blockers:
        return "Needs attention"
    if tasks or events:
        return "Active"
    return "Quiet"


def _project_next_recommendation(*, blockers: list[dict[str, Any]], ranked_tasks: list[dict[str, Any]], events: list[dict[str, Any]], memories: list[dict[str, Any]]) -> str:
    if blockers:
        return f"Resolve blocker: {blockers[0]['title']}"
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
    return sorted(tasks, key=lambda task: (due_order.get(str(task.get("due_status") or ""), 5), -int(task.get("todoist_priority") or task.get("priority") or 0), str(task.get("due_date") or "9999-12-31"), str(task.get("content") or "").lower()))


def _project_event_item(event: dict[str, Any]) -> dict[str, Any]:
    start = _event_start(event)
    end = _event_end(event)
    return {
        "id": event.get("id"), "title": event.get("title") or "(No title)", "start": start.isoformat(), "end": end.isoformat(),
        "duration_minutes": int(event.get("duration_minutes") or _ceil_minutes_between(start, end)), "all_day": bool(event.get("all_day")),
        "busy": bool(event.get("busy")), "event_type": event.get("event_type") or _calendar_event_category(event),
        "event_category": _calendar_event_category(event), "status": event.get("status"), "transparency": event.get("transparency"),
        "attendees_count": event.get("attendees_count"), "location": event.get("location"), "html_link": event.get("html_link"),
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
        if key not in seen:
            seen.add(key)
            deduped.append(blocker)
    return deduped


def _task_match_text(task: dict[str, Any]) -> str:
    return " ".join(str(part or "") for part in (task.get("content"), task.get("description"), task.get("project_name"), task.get("section_name"), task.get("todoist_section_name"), task.get("category"), " ".join(str(label) for label in task.get("labels") or [])))


def _event_match_text(event: dict[str, Any]) -> str:
    return " ".join(str(part or "") for part in (event.get("title"), event.get("summary"), event.get("description"), event.get("location"), event.get("resolved_project"), event.get("project"), event.get("project_key")))


def _memory_match_text(memory: dict[str, Any]) -> str:
    return " ".join(str(memory.get(part) or "") for part in ("type", "title", "content"))


def _activity_match_text(entry: dict[str, Any]) -> str:
    return " ".join(str(part or "") for part in (entry.get("type"), entry.get("action_type"), entry.get("title"), entry.get("description"), entry.get("detail"), entry.get("source"), _flatten_text(entry.get("payload") or entry.get("metadata"))))


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return "" if value is None else str(value)


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").replace("-", " ").split())


def _slug_text(value: str) -> str:
    text = value.lower().replace("&", " and ").replace("_", " ").replace("-", " ")
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
    return next((phrase for phrase in phrases if _contains_phrase(normalized, phrase)), None)


def _task_section_for(task: dict[str, Any]) -> str:
    category = str(task.get("category") or task.get("project_category") or "").strip()
    if category in {"A&M", "XO", "Freelance", "Nebulo", "Personal", "Misc"}:
        return category
    section_category = life_area_for_todoist_section(str(task.get("section_name") or "").strip())
    if section_category:
        return section_category
    todoist_section_category = life_area_for_todoist_section(str(task.get("todoist_section_name") or "").strip())
    return todoist_section_category or "Misc"


def _todoist_task_section_for(task: dict[str, Any]) -> str:
    section_name = str(task.get("todoist_section_name") or task.get("section_name") or "").strip()
    canonical_section = LIFE_AREA_TO_TODOIST_SECTION.get(_task_section_for(task), LIFE_AREA_TO_TODOIST_SECTION["Misc"])
    return section_name if section_name in TODOIST_SECTION_TO_LIFE_AREA else canonical_section


def _task_item(task: dict[str, Any], section: str) -> dict[str, Any]:
    return {
        "id": task.get("id"), "content": str(task.get("content") or ""), "description": task.get("description"), "section": section,
        "parent_id": task.get("parent_id"), "project_name": task.get("project_name"), "section_name": task.get("section_name"),
        "category": task.get("category") or task.get("project_category") or _task_section_for(task),
        "todoist_section_name": task.get("todoist_section_name") or task.get("section_name"),
        "todoist_section_id": task.get("todoist_section_id") or task.get("section_id"),
        "classification_source": task.get("classification_source") or "fallback", "due": task.get("due"), "due_date": task.get("due_date"),
        "due_status": task.get("due_status"), "priority": task.get("priority"), "todoist_priority": task.get("todoist_priority"),
        "completed": _task_completed(task), "labels": task.get("labels") or [], "url": task.get("url"),
    }


def _is_high_priority_task(task: dict[str, Any]) -> bool:
    raw_priority = task.get("todoist_priority")
    try:
        return int(raw_priority if raw_priority is not None else task.get("priority")) >= 4
    except (TypeError, ValueError):
        return False


def _event_start(event: dict[str, Any]) -> datetime:
    value = event.get("start")
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _event_end(event: dict[str, Any]) -> datetime:
    value = event.get("end")
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _ceil_minutes_between(start: datetime, end: datetime) -> int:
    seconds = (end - start).total_seconds()
    return max(0, int(seconds // 60 + (1 if seconds % 60 else 0)))


def _calendar_event_category(event: dict[str, Any]) -> str:
    category = event.get("event_category") or event.get("event_type")
    if category == "soft":
        return "informational"
    return str(category) if category in {"hard", "flexible", "informational"} else "flexible"
