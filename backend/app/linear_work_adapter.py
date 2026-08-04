from datetime import date, datetime
from typing import Any

from .work_domain import (
    NormalizedWorkItem,
    WorkDependency,
    WorkEffortSize,
    WorkPriority,
    WorkStatus,
)


LINEAR_PROVIDER = "linear"
LINEAR_PRIORITY_MAP = {
    0: WorkPriority.NONE,
    4: WorkPriority.LOW,
    3: WorkPriority.MEDIUM,
    2: WorkPriority.HIGH,
    1: WorkPriority.URGENT,
}


class LinearWorkAdapter:
    def adapt_many(self, issues: list[dict[str, Any]]) -> list[NormalizedWorkItem]:
        items = [self.adapt_issue(issue) for issue in issues if _valid_issue(issue)]
        return self._apply_hierarchy(items)

    def adapt_issue(self, issue: dict[str, Any]) -> NormalizedWorkItem:
        if not _valid_issue(issue):
            raise ValueError("Linear issue is missing required identity, title, or workflow state fields")
        state = issue["state"]
        status = normalize_linear_status(state.get("type"))
        dependencies = _dependencies(issue)
        project = issue.get("project") if isinstance(issue.get("project"), dict) else None
        parent = issue.get("parent") if isinstance(issue.get("parent"), dict) else None
        milestone = issue.get("projectMilestone") if isinstance(issue.get("projectMilestone"), dict) else None
        assignee = issue.get("assignee") if isinstance(issue.get("assignee"), dict) else None
        team = issue.get("team") if isinstance(issue.get("team"), dict) else None
        labels = _label_names(issue.get("labels"))
        metadata = {
            "issue_identifier": str(issue["identifier"]),
            "provider_project_id": str(project["id"]) if project and project.get("id") else None,
            "provider_project_name": str(project["name"]) if project and project.get("name") else None,
            "workflow_state": dict(state),
            "priority_label": issue.get("priorityLabel"),
            "parent_issue": dict(parent) if parent else None,
            "project_milestone": dict(milestone) if milestone else None,
            "assignee": dict(assignee) if assignee else None,
            "team": dict(team) if team else None,
            "labels": labels,
            "estimate": issue.get("estimate"),
            "relations": list((issue.get("relations") or {}).get("nodes") or []),
            "inverse_relations": list((issue.get("inverseRelations") or {}).get("nodes") or []),
            "completed_at": issue.get("completedAt"),
            "canceled_at": issue.get("canceledAt"),
            "source": "linear_graphql",
        }
        return NormalizedWorkItem(
            provider=LINEAR_PROVIDER,
            provider_record_id=str(issue["id"]),
            canonical_project_id=None,
            title=str(issue["title"]).strip(),
            description=str(issue.get("description") or "").strip(),
            status=status,
            original_provider_status=str(state["name"]),
            priority=normalize_linear_priority(issue.get("priority")),
            original_provider_priority=issue.get("priority"),
            due_date=_parse_date(issue.get("dueDate")),
            parent_provider_record_id=str(parent["id"]) if parent and parent.get("id") else None,
            is_container=False,
            is_executable=status == WorkStatus.OPEN,
            explicitly_completable=False,
            is_blocked=False,
            dependencies=tuple(dependencies),
            created_at=_parse_datetime(issue.get("createdAt")),
            updated_at=_parse_datetime(issue.get("updatedAt")),
            provider_url=str(issue["url"]) if issue.get("url") else None,
            provider_reference=str(project["id"]) if project and project.get("id") else None,
            effort_size=_linear_effort_size(issue.get("estimate")),
            context_requirements=_context_requirements(labels),
            provider_metadata=metadata,
        )

    @staticmethod
    def _apply_hierarchy(items: list[NormalizedWorkItem]) -> list[NormalizedWorkItem]:
        active_parent_ids = {
            item.parent_provider_record_id
            for item in items
            if item.parent_provider_record_id and item.status == WorkStatus.OPEN
        }
        return [
            item.model_copy(
                update={
                    "is_container": item.provider_record_id in active_parent_ids,
                    "is_executable": item.status == WorkStatus.OPEN and item.provider_record_id not in active_parent_ids,
                }
            )
            for item in items
        ]


def normalize_linear_priority(value: Any) -> WorkPriority:
    try:
        return LINEAR_PRIORITY_MAP[int(value)]
    except (KeyError, TypeError, ValueError):
        return WorkPriority.NONE


def normalize_linear_status(state_type: Any) -> WorkStatus:
    normalized = str(state_type or "").strip().lower()
    if normalized == "completed":
        return WorkStatus.COMPLETED
    if normalized in {"canceled", "cancelled"}:
        return WorkStatus.CANCELED
    return WorkStatus.OPEN


def _dependencies(issue: dict[str, Any]) -> list[WorkDependency]:
    dependencies: list[WorkDependency] = []
    for relation in (issue.get("relations") or {}).get("nodes") or []:
        related = relation.get("relatedIssue") if isinstance(relation, dict) else None
        if str(relation.get("type") or "").lower() == "blocks" and isinstance(related, dict) and related.get("id"):
            dependencies.append(WorkDependency(provider=LINEAR_PROVIDER, provider_record_id=str(related["id"]), dependency_type="blocks"))
    for relation in (issue.get("inverseRelations") or {}).get("nodes") or []:
        blocker = relation.get("issue") if isinstance(relation, dict) else None
        if str(relation.get("type") or "").lower() == "blocks" and isinstance(blocker, dict) and blocker.get("id"):
            dependencies.append(WorkDependency(provider=LINEAR_PROVIDER, provider_record_id=str(blocker["id"]), dependency_type="blocked_by"))
    return dependencies


def _valid_issue(issue: Any) -> bool:
    state = issue.get("state") if isinstance(issue, dict) else None
    return bool(isinstance(issue, dict) and issue.get("id") and issue.get("identifier") and issue.get("title") and isinstance(state, dict) and state.get("name") and state.get("type"))


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _label_names(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [
        str(node["name"]).strip()
        for node in value.get("nodes") or []
        if isinstance(node, dict) and str(node.get("name") or "").strip()
    ]


def _linear_effort_size(value: Any) -> WorkEffortSize | None:
    try:
        estimate = float(value)
    except (TypeError, ValueError):
        return None
    if estimate >= 5:
        return WorkEffortSize.LARGE
    if estimate >= 3:
        return WorkEffortSize.MEDIUM
    if estimate > 0:
        return WorkEffortSize.SMALL
    return None


def _context_requirements(labels: list[str]) -> tuple[str, ...]:
    requirements: list[str] = []
    for label in labels:
        prefix, separator, value = label.partition(":")
        if separator and prefix.strip().lower() in {"context", "environment"}:
            requirement = value.strip()
            if requirement:
                requirements.append(requirement)
    return tuple(dict.fromkeys(requirements))


linear_work_adapter = LinearWorkAdapter()
