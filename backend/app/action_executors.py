"""Executor registry and provider adapters for the six SID-150 action variants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Callable

from .action_domain import (
    ActionPayload,
    CreateCalendarEventPayload,
    CreateManyTodoistSubtasksPayload,
    CreateManyTodoistTasksPayload,
    CreateTodoistSubtaskPayload,
    CreateTodoistTaskPayload,
    PendingActionType,
    ProviderTargetReference,
    TodoistTaskSpec,
    UpdateCalendarEventPayload,
)
from .calendar_tools import create_calendar_event, update_calendar_event
from .todoist_tools import (
    LIFE_AREA_TO_TODOIST_SECTION,
    TODOIST_INBOX_PROJECT_NAME,
    create_many_subtasks,
    create_many_tasks,
    create_task,
    list_todoist_sections,
)


@dataclass(frozen=True)
class ActionExecutionContext:
    settings: Any
    tasks: tuple[dict[str, Any], ...]
    calendar_events: tuple[dict[str, Any], ...]
    local_now: datetime


@dataclass(frozen=True)
class ActionExecutionResult:
    actions_taken: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()
    provider_references: tuple[ProviderTargetReference, ...] = ()
    partial_mutation: bool = False


class UncertainProviderOutcome(RuntimeError):
    """Raised when a provider mutation may have happened but cannot be proven."""


ActionExecutor = Callable[[ActionPayload, ActionExecutionContext], ActionExecutionResult]


class ActionExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[PendingActionType, ActionExecutor] = {}

    def register(self, action_type: PendingActionType, executor: ActionExecutor) -> None:
        if action_type in self._executors:
            raise ValueError(f"Executor already registered for {action_type.value}.")
        self._executors[action_type] = executor

    def execute(
        self,
        payload: ActionPayload,
        context: ActionExecutionContext,
    ) -> ActionExecutionResult:
        executor = self._executors.get(payload.action_type)
        if executor is None:
            raise ValueError(f"No executor registered for {payload.action_type.value}.")
        return executor(payload, context)

    @property
    def registered_types(self) -> tuple[PendingActionType, ...]:
        return tuple(self._executors)


def build_default_executor_registry() -> ActionExecutorRegistry:
    registry = ActionExecutorRegistry()
    registry.register(PendingActionType.CREATE_TODOIST_TASK, _create_todoist_task)
    registry.register(PendingActionType.CREATE_TODOIST_SUBTASK, _create_todoist_subtask)
    registry.register(PendingActionType.CREATE_MANY_TODOIST_TASKS, _create_many_todoist_tasks)
    registry.register(
        PendingActionType.CREATE_MANY_TODOIST_SUBTASKS,
        _create_many_todoist_subtasks,
    )
    registry.register(PendingActionType.CREATE_CALENDAR_EVENT, _create_calendar_event)
    registry.register(PendingActionType.UPDATE_CALENDAR_EVENT, _update_calendar_event)
    return registry


def _create_todoist_task(
    payload: ActionPayload,
    context: ActionExecutionContext,
) -> ActionExecutionResult:
    assert isinstance(payload, CreateTodoistTaskPayload)
    task = payload.task
    section_id, section_name = _todoist_section(context, task)
    project_id = task.project_id or _project_id_for_category(
        context.tasks,
        task.project_category,
    )
    result = create_task(
        settings=context.settings,
        content=task.content,
        project_id=project_id,
        project_name=task.project_name or _project_name_for_category(task.project_category),
        section_id=section_id,
        section_name=section_name,
        due_string=task.due_string,
        labels=list(task.labels),
        priority=task.priority,
    )
    if result.error:
        return ActionExecutionResult(errors=(result.error,))
    created = _created_task_metadata(task, result.task, section_id, section_name)
    refs = _task_refs(result.task)
    return ActionExecutionResult(
        actions_taken=(
            {"type": payload.action_type.value, "status": "success", "task": created},
        ),
        provider_references=refs,
    )


def _create_todoist_subtask(
    payload: ActionPayload,
    context: ActionExecutionContext,
) -> ActionExecutionResult:
    assert isinstance(payload, CreateTodoistSubtaskPayload)
    result = create_many_subtasks(
        settings=context.settings,
        parent_id=payload.parent_task_id,
        tasks=[_task_write_dict(payload.task)],
        existing_tasks=list(context.tasks),
    )
    refs = _task_refs_many(result.tasks)
    if result.error:
        return ActionExecutionResult(
            errors=(result.error,),
            provider_references=refs,
            partial_mutation=bool(result.tasks),
        )
    return ActionExecutionResult(
        actions_taken=(
            {
                "type": payload.action_type.value,
                "status": "success",
                "parent_task_id": payload.parent_task_id,
                "parent_task_title": payload.parent_task_title,
                "task": result.tasks[0] if result.tasks else None,
                "skipped": result.skipped,
            },
        ),
        provider_references=refs,
    )


def _create_many_todoist_tasks(
    payload: ActionPayload,
    context: ActionExecutionContext,
) -> ActionExecutionResult:
    assert isinstance(payload, CreateManyTodoistTasksPayload)
    result = create_many_tasks(
        settings=context.settings,
        tasks=[_task_write_dict(task) for task in payload.tasks],
    )
    refs = _task_refs_many(result.tasks)
    if result.error:
        return ActionExecutionResult(
            errors=(result.error,),
            provider_references=refs,
            partial_mutation=bool(result.tasks),
        )
    return ActionExecutionResult(
        actions_taken=(
            {
                "type": payload.action_type.value,
                "status": "success",
                "task_count": len(result.tasks),
                "requested_count": len(payload.tasks),
                "tasks": result.tasks,
                "skipped": result.skipped,
            },
        ),
        provider_references=refs,
    )


def _create_many_todoist_subtasks(
    payload: ActionPayload,
    context: ActionExecutionContext,
) -> ActionExecutionResult:
    assert isinstance(payload, CreateManyTodoistSubtasksPayload)
    result = create_many_subtasks(
        settings=context.settings,
        parent_id=payload.parent_task_id,
        tasks=[_task_write_dict(task) for task in payload.tasks],
        existing_tasks=list(context.tasks),
    )
    refs = _task_refs_many(result.tasks)
    if result.error:
        return ActionExecutionResult(
            errors=(result.error,),
            provider_references=refs,
            partial_mutation=bool(result.tasks),
        )
    return ActionExecutionResult(
        actions_taken=(
            {
                "type": payload.action_type.value,
                "status": "success",
                "parent_task_id": payload.parent_task_id,
                "parent_task_title": payload.parent_task_title,
                "section_name": payload.section_name,
                "task_count": len(result.tasks),
                "requested_count": len(payload.tasks),
                "tasks": result.tasks,
                "skipped": result.skipped,
            },
        ),
        provider_references=refs,
    )


def _create_calendar_event(
    payload: ActionPayload,
    context: ActionExecutionContext,
) -> ActionExecutionResult:
    assert isinstance(payload, CreateCalendarEventPayload)
    target_events = _events_on_date(context.calendar_events, payload.start)
    result = create_calendar_event(
        settings=context.settings,
        title=payload.title,
        start=payload.start.astimezone(context.local_now.tzinfo),
        end=payload.end.astimezone(context.local_now.tzinfo),
        existing_events=target_events,
        allow_conflicts=payload.allow_conflicts,
        description=payload.description,
    )
    if result.error:
        return ActionExecutionResult(errors=(result.error,))
    actions: list[dict[str, Any]] = [
        {"type": payload.action_type.value, "status": "success", "event": result.event}
    ]
    refs = list(_event_refs(result.event))

    dual_write_project = _dual_write_project(payload)
    if dual_write_project:
        content = _todoist_content_for_calendar_event(payload.title, dual_write_project)
        section_name = LIFE_AREA_TO_TODOIST_SECTION.get(dual_write_project)
        section_id = _section_id(context, section_name)
        task_result = create_task(
            settings=context.settings,
            content=content,
            project_id=_project_id_for_category(context.tasks, dual_write_project),
            project_name=TODOIST_INBOX_PROJECT_NAME,
            section_id=section_id,
            section_name=section_name,
            due_string=payload.start.date().isoformat(),
            labels=[],
            priority=4,
        )
        if task_result.task:
            refs.extend(_task_refs(task_result.task))
        if task_result.error:
            return ActionExecutionResult(
                actions_taken=tuple(actions),
                errors=(task_result.error,),
                provider_references=tuple(refs),
                partial_mutation=True,
            )
        proposed = TodoistTaskSpec(
            content=content,
            project_name=TODOIST_INBOX_PROJECT_NAME,
            section_id=section_id,
            section_name=section_name,
            due_string=payload.start.date().isoformat(),
            labels=(),
            priority=4,
            project_category=dual_write_project,
            classification_source="rule",
        )
        actions.append(
            {
                "type": PendingActionType.CREATE_TODOIST_TASK.value,
                "status": "success",
                "task": _created_task_metadata(
                    proposed,
                    task_result.task,
                    section_id,
                    section_name,
                ),
                "source": "dual_write_calendar_commitment",
            }
        )
    return ActionExecutionResult(
        actions_taken=tuple(actions),
        provider_references=tuple(refs),
    )


def _update_calendar_event(
    payload: ActionPayload,
    context: ActionExecutionContext,
) -> ActionExecutionResult:
    assert isinstance(payload, UpdateCalendarEventPayload)
    result = update_calendar_event(
        settings=context.settings,
        event_id=payload.event_id,
        title=payload.title,
        start=payload.new_start.astimezone(context.local_now.tzinfo),
        end=payload.new_end.astimezone(context.local_now.tzinfo),
    )
    if result.error:
        return ActionExecutionResult(errors=(result.error,))
    return ActionExecutionResult(
        actions_taken=(
            {
                "type": payload.action_type.value,
                "status": "success",
                "event": result.event,
                "previous_event": {
                    "id": payload.event_id,
                    "title": payload.title,
                    "start": payload.old_start.isoformat(),
                    "end": payload.old_end.isoformat(),
                },
            },
        ),
        provider_references=_event_refs(result.event, fallback_id=payload.event_id),
    )


def _task_write_dict(task: TodoistTaskSpec) -> dict[str, Any]:
    return {
        "content": task.content,
        "project_id": task.project_id,
        "project_name": task.project_name,
        "section_id": task.section_id,
        "section_name": task.section_name,
        "due_string": task.due_string,
        "labels": list(task.labels),
        "priority": task.priority,
    }


def _todoist_section(
    context: ActionExecutionContext,
    task: TodoistTaskSpec,
) -> tuple[str | None, str | None]:
    section_name = task.section_name or LIFE_AREA_TO_TODOIST_SECTION.get(
        task.project_category or ""
    )
    return task.section_id or _section_id(context, section_name), section_name


def _section_id(
    context: ActionExecutionContext,
    section_name: str | None,
) -> str | None:
    if not section_name:
        return None
    result = list_todoist_sections(context.settings)
    return next(
        (item.get("id") for item in result.sections if item.get("name") == section_name),
        None,
    )


def _project_id_for_category(
    tasks: tuple[dict[str, Any], ...],
    category: str | None,
) -> str | None:
    if not category:
        return None
    for task in tasks:
        if task.get("project_name") == TODOIST_INBOX_PROJECT_NAME and task.get("project_id"):
            return str(task["project_id"])
    for task in tasks:
        if task.get("category") == category and task.get("project_id"):
            return str(task["project_id"])
    return None


def _project_name_for_category(category: str | None) -> str | None:
    return TODOIST_INBOX_PROJECT_NAME if category in LIFE_AREA_TO_TODOIST_SECTION else None


def _created_task_metadata(
    proposed: TodoistTaskSpec,
    created: dict[str, Any] | None,
    section_id: str | None,
    section_name: str | None,
) -> dict[str, Any]:
    task = dict(created or {})
    task.update(
        {
            "content": proposed.content,
            "project_category": proposed.project_category,
            "priority": proposed.priority,
            "due_date": proposed.due_string,
            "project_name": proposed.project_name,
            "section_name": section_name,
            "todoist_section_name": section_name,
            "todoist_section_id": section_id,
            "classification_source": proposed.classification_source
            or task.get("classification_source"),
            "resolved_project": proposed.project_category,
        }
    )
    return {key: value for key, value in task.items() if value is not None}


def _events_on_date(
    events: tuple[dict[str, Any], ...],
    target: datetime,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in events:
        try:
            start = datetime.fromisoformat(str(event.get("start") or ""))
        except ValueError:
            continue
        if start.date() == target.date():
            result.append(event)
    return result


def _dual_write_project(payload: CreateCalendarEventPayload) -> str | None:
    if payload.project_category in {"A&M", "XO", "Nebulo", "Freelance"}:
        return payload.project_category
    text = payload.title.casefold()
    if "ashwin" in text or "charlie" in text or re.search(r"\bxo\b", text):
        return "XO"
    if "brandon" in text or "nebulo" in text:
        return "Nebulo"
    if "a&m" in text or "tamu" in text or "advisor" in text:
        return "A&M"
    if any(term in text for term in ("client", "website", "dentist", "realtor")):
        return "Freelance"
    return None


def _todoist_content_for_calendar_event(title: str, project: str) -> str:
    return re.sub(rf"^{re.escape(project)}\s+[—-]\s+", "", title).strip()


def _task_refs(task: dict[str, Any] | None) -> tuple[ProviderTargetReference, ...]:
    task_id = str((task or {}).get("id") or "").strip()
    if not task_id:
        return ()
    return (
        ProviderTargetReference(
            provider="todoist",
            resource_type="task",
            provider_ref=task_id,
        ),
    )


def _task_refs_many(tasks: list[dict[str, Any]]) -> tuple[ProviderTargetReference, ...]:
    return tuple(reference for task in tasks for reference in _task_refs(task))


def _event_refs(
    event: dict[str, Any] | None,
    *,
    fallback_id: str | None = None,
) -> tuple[ProviderTargetReference, ...]:
    event_id = str((event or {}).get("id") or fallback_id or "").strip()
    if not event_id:
        return ()
    return (
        ProviderTargetReference(
            provider="google_calendar",
            resource_type="event",
            provider_ref=event_id,
        ),
    )


default_action_executor_registry = build_default_executor_registry()
