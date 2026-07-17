from __future__ import annotations

from datetime import datetime
from typing import Any

from .project_registry import ProjectRegistrySnapshot, project_registry_service
from .recommendation_service import RecommendationContext, WorkRecommendation, recommendation_service
from .todoist_tools import LIFE_AREA_TO_TODOIST_SECTION, TodoistReadResult, life_area_for_todoist_section, list_active_tasks
from .todoist_work_adapter import TodoistWorkAdapter, todoist_work_adapter
from .work_domain import NormalizedWorkItem


LIFE_AREAS = ("A&M", "XO", "Nebulo", "Freelance", "Personal", "Misc")


class TasksProjectionService:
    def __init__(self, *, todoist_adapter: TodoistWorkAdapter = todoist_work_adapter) -> None:
        self.todoist_adapter = todoist_adapter

    def build(
        self,
        *,
        settings: Any,
        current_time: datetime | None = None,
    ) -> dict[str, Any]:
        local_now = _local_now(current_time, settings.local_tz)
        todoist_result = list_active_tasks(settings)
        return self.project(
            todoist_result=todoist_result,
            registry=project_registry_service.snapshot(),
            current_time=local_now,
        )

    def project(
        self,
        *,
        todoist_result: TodoistReadResult,
        registry: ProjectRegistrySnapshot,
        current_time: datetime,
    ) -> dict[str, Any]:
        work_items = self.todoist_adapter.adapt_many(
            todoist_result.tasks,
            registry=registry,
            today=current_time.date(),
        )
        work_by_id = {item.provider_record_id: item for item in work_items}
        grouped: dict[str, list[NormalizedWorkItem]] = {area: [] for area in LIFE_AREAS}
        for item in work_items:
            grouped[_life_area(item)].append(item)

        provider_status = _provider_status(todoist_result)
        unavailable = provider_status == "unavailable"
        sections = [
            {
                "name": LIFE_AREA_TO_TODOIST_SECTION[area],
                "tasks": [_task_item(item, LIFE_AREA_TO_TODOIST_SECTION[area]) for item in grouped[area]],
            }
            for area in LIFE_AREAS
        ]
        recommendations = [
            self._area_projection(
                area=area,
                work_items=grouped[area],
                work_by_id=work_by_id,
                current_time=current_time,
                unavailable=unavailable,
            )
            for area in LIFE_AREAS
        ]
        return {
            "sections": sections,
            "recommendations": recommendations,
            "computed_at": current_time.isoformat(),
            "provider": {
                "name": "todoist",
                "status": provider_status,
                "message": todoist_result.error,
            },
            "errors": [todoist_result.error] if todoist_result.error else [],
        }

    @staticmethod
    def _area_projection(
        *,
        area: str,
        work_items: list[NormalizedWorkItem],
        work_by_id: dict[str, NormalizedWorkItem],
        current_time: datetime,
        unavailable: bool,
    ) -> dict[str, Any]:
        section_name = LIFE_AREA_TO_TODOIST_SECTION[area]
        if unavailable:
            return {
                "area": area,
                "section_name": section_name,
                "task_count": 0,
                "state": "unavailable",
                "recommendation": None,
            }

        recommendation = recommendation_service.recommend_current_action(
            work_items,
            context=RecommendationContext(current_time=current_time),
        )
        return {
            "area": area,
            "section_name": section_name,
            "task_count": len(work_items),
            "state": "recommended" if recommendation else "empty",
            "recommendation": (
                _recommendation_payload(recommendation, work_by_id, section_name)
                if recommendation
                else None
            ),
        }


def _local_now(current_time: datetime | None, local_tz: Any) -> datetime:
    if current_time is None:
        return datetime.now(local_tz)
    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=local_tz)
    return current_time.astimezone(local_tz)


def _provider_status(result: TodoistReadResult) -> str:
    if not result.error:
        return "available"
    return "degraded" if result.tasks else "unavailable"


def _life_area(item: NormalizedWorkItem) -> str:
    task = item.provider_metadata
    section_name = str(task.get("todoist_section_name") or task.get("section_name") or "").strip()
    area = life_area_for_todoist_section(section_name)
    if area in LIFE_AREAS:
        return area
    category = str(task.get("category") or task.get("project_category") or "").strip()
    return category if category in LIFE_AREAS else "Misc"


def _recommendation_payload(
    recommendation: WorkRecommendation,
    work_by_id: dict[str, NormalizedWorkItem],
    section_name: str,
) -> dict[str, Any]:
    selected = work_by_id[recommendation.selected_work.provider_record_id]
    alternatives = []
    for alternative in recommendation.considered_alternatives:
        alternative_item = work_by_id[alternative.work.provider_record_id]
        alternatives.append(
            {
                "provider": alternative.work.provider,
                "provider_record_id": alternative.work.provider_record_id,
                "title": alternative.work.title,
                "task": _task_item(alternative_item, section_name),
                "score": alternative.score,
                "action": alternative.action.value,
            }
        )
    return {
        "provider": recommendation.selected_work.provider,
        "provider_record_id": recommendation.selected_work.provider_record_id,
        "title": recommendation.selected_work.title,
        "task": _task_item(selected, section_name),
        "action": recommendation.action.value,
        "score": recommendation.score,
        "explanation": recommendation.explanation,
        "evidence": [item.model_dump(mode="json") for item in recommendation.evidence],
        "alternatives": alternatives,
        "computed_at": recommendation.computed_at.isoformat(),
        "context": recommendation.context.model_dump(mode="json"),
    }


def _task_item(item: NormalizedWorkItem, section: str) -> dict[str, Any]:
    task = item.provider_metadata
    return {
        "id": item.provider_record_id,
        "content": item.title,
        "description": item.description or None,
        "section": section,
        "parent_id": item.parent_provider_record_id,
        "project_name": task.get("project_name"),
        "section_name": task.get("section_name"),
        "category": task.get("category") or task.get("project_category") or _life_area(item),
        "todoist_section_name": task.get("todoist_section_name") or task.get("section_name"),
        "todoist_section_id": task.get("todoist_section_id") or task.get("section_id"),
        "classification_source": task.get("classification_source") or "fallback",
        "due": task.get("due") if isinstance(task.get("due"), dict) else None,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "due_status": task.get("due_status"),
        "priority": task.get("priority"),
        "todoist_priority": task.get("todoist_priority"),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "completed": item.status.value == "completed",
        "labels": task.get("labels") or [],
        "url": item.provider_url,
    }


tasks_projection_service = TasksProjectionService()
