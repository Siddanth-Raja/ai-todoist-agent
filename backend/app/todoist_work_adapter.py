from datetime import date, datetime
from typing import Any

from .planner import enrich_task
from .project_registry import ProjectRegistrySnapshot
from .work_domain import (
    NormalizedWorkItem,
    WorkEffortSize,
    WorkEnergy,
    WorkPriority,
    WorkStatus,
)


TODOIST_PROVIDER = "todoist"


class TodoistWorkAdapter:
    def adapt_many(
        self,
        tasks: list[dict[str, Any]],
        *,
        registry: ProjectRegistrySnapshot,
        today: date,
    ) -> list[NormalizedWorkItem]:
        work_items = [
            self.adapt_task(task, registry=registry, today=today)
            for task in tasks
            if task.get("content") and task.get("id") is not None
        ]
        return self._apply_hierarchy(work_items)

    def adapt_task(
        self,
        task: dict[str, Any],
        *,
        registry: ProjectRegistrySnapshot,
        today: date,
    ) -> NormalizedWorkItem:
        enriched = enrich_task(task, today)
        completed = bool(
            enriched.get("completed")
            or enriched.get("is_completed")
            or enriched.get("checked")
        )
        original_priority = enriched.get("todoist_priority")
        priority_source = (
            original_priority
            if original_priority is not None
            else enriched.get("priority")
        )
        section_name = str(
            enriched.get("todoist_section_name")
            or enriched.get("section_name")
            or ""
        ).strip()
        canonical_project_id = (
            registry.resolve_provider_project_id(
                provider=TODOIST_PROVIDER,
                resource_type="section",
                provider_ref=section_name,
            )
            if section_name
            else None
        )
        explicitly_completable = _explicitly_completable(enriched)
        original_status = str(
            enriched.get("status") or ("completed" if completed else "active")
        )
        status = _normalized_status(original_status, completed=completed)
        due_date, due_at = _due_values(enriched)

        return NormalizedWorkItem(
            provider=TODOIST_PROVIDER,
            provider_record_id=str(enriched["id"]),
            canonical_project_id=canonical_project_id,
            title=str(enriched.get("content") or "").strip(),
            description=str(enriched.get("description") or "").strip(),
            status=status,
            original_provider_status=original_status,
            priority=normalize_todoist_priority(priority_source),
            original_provider_priority=original_priority,
            due_date=due_date,
            due_at=due_at,
            parent_provider_record_id=(
                str(enriched["parent_id"])
                if enriched.get("parent_id") is not None
                else None
            ),
            is_container=False,
            is_executable=status == WorkStatus.OPEN,
            explicitly_completable=explicitly_completable,
            is_blocked=False,
            dependencies=(),
            created_at=_parse_datetime(enriched.get("created_at")),
            updated_at=_parse_datetime(enriched.get("updated_at")),
            provider_url=str(enriched.get("url")) if enriched.get("url") else None,
            provider_reference=(
                str(enriched.get("project_id"))
                if enriched.get("project_id") is not None
                else None
            ),
            estimated_duration_minutes=_positive_int(
                enriched.get("estimated_duration")
            ),
            energy_requirement=_work_energy(enriched.get("energy_level")),
            effort_size=_effort_size(enriched),
            context_requirements=_context_requirements(enriched.get("labels") or []),
            provider_metadata=enriched,
        )

    @staticmethod
    def _apply_hierarchy(
        work_items: list[NormalizedWorkItem],
    ) -> list[NormalizedWorkItem]:
        active_children_by_parent: dict[str, list[NormalizedWorkItem]] = {}
        for item in work_items:
            if (
                item.parent_provider_record_id
                and item.status == WorkStatus.OPEN
            ):
                active_children_by_parent.setdefault(
                    item.parent_provider_record_id,
                    [],
                ).append(item)

        normalized: list[NormalizedWorkItem] = []
        for item in work_items:
            has_active_children = bool(
                active_children_by_parent.get(item.provider_record_id)
            )
            is_container = has_active_children and not item.explicitly_completable
            is_executable = item.status == WorkStatus.OPEN and not is_container
            normalized.append(
                item.model_copy(
                    update={
                        "is_container": is_container,
                        "is_executable": is_executable,
                    }
                )
            )
        return normalized


def normalize_todoist_priority(value: Any) -> WorkPriority:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return WorkPriority.NONE
    if priority <= 0:
        return WorkPriority.NONE
    if priority >= 4:
        return WorkPriority.URGENT
    return WorkPriority(priority)


def _normalized_status(original_status: str, *, completed: bool) -> WorkStatus:
    if completed:
        return WorkStatus.COMPLETED
    if original_status.strip().lower() in {"canceled", "cancelled", "deleted"}:
        return WorkStatus.CANCELED
    return WorkStatus.OPEN


def _explicitly_completable(task: dict[str, Any]) -> bool:
    labels = {str(label).strip().lower() for label in task.get("labels") or []}
    if {"completeable", "completable", "leaf-task"} & labels:
        return True
    text = f"{task.get('content') or ''} {task.get('description') or ''}".lower()
    return "[completeable]" in text or "[completable]" in text


def _due_values(task: dict[str, Any]) -> tuple[date | None, datetime | None]:
    due = task.get("due") if isinstance(task.get("due"), dict) else {}
    datetime_value = due.get("datetime")
    if datetime_value:
        due_at = _parse_datetime(datetime_value)
        if due_at:
            return due_at.date(), due_at
    due_date_value = task.get("due_date") or due.get("date")
    if due_date_value:
        try:
            return date.fromisoformat(str(due_date_value)[:10]), None
        except ValueError:
            pass
    return None, None


def _effort_size(task: dict[str, Any]) -> WorkEffortSize | None:
    duration = _positive_int(task.get("estimated_duration"))
    if duration is None:
        return None
    if duration >= 90:
        return WorkEffortSize.LARGE
    if duration >= 30:
        return WorkEffortSize.MEDIUM
    return WorkEffortSize.SMALL


def _context_requirements(labels: list[Any]) -> tuple[str, ...]:
    requirements: list[str] = []
    for raw_label in labels:
        label = str(raw_label).strip()
        prefix, separator, value = label.partition(":")
        if separator and prefix.strip().lower() in {"context", "environment"}:
            requirement = value.strip()
            if requirement:
                requirements.append(requirement)
    return tuple(dict.fromkeys(requirements))


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _work_energy(value: Any) -> WorkEnergy | None:
    try:
        return WorkEnergy(str(value).strip().lower())
    except ValueError:
        return None


todoist_work_adapter = TodoistWorkAdapter()
