from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Any

from .project_brain import project_brain_service
from .project_registry import ProjectRegistrySnapshot, project_registry_service


class ProjectQuestionKind(StrEnum):
    OVERVIEW = "overview"
    NEXT_MOVE = "next_move"
    BLOCKERS = "blockers"
    WORK_PACKAGES = "work_packages"
    PEOPLE = "people"


@dataclass(frozen=True)
class ProjectChatGrounding:
    answer: str
    question_kind: ProjectQuestionKind
    canonical_project_key: str | None = None
    warnings: tuple[str, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()


class ProjectChatGroundingService:
    def __init__(
        self,
        *,
        registry_service=project_registry_service,
        brain_service=project_brain_service,
    ):
        self.registry_service = registry_service
        self.brain_service = brain_service

    def ground(
        self,
        message: str,
        *,
        settings: Any,
        current_time: datetime | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> ProjectChatGrounding | None:
        kind = _question_kind(message)
        if kind is None:
            return None

        registry = self.registry_service.snapshot()
        matches = _matching_project_keys(message, registry)
        context_key = _context_project_key(conversation_context, registry)
        if len(matches) > 1:
            return _clarification(kind, registry, "I found more than one project in that question.")
        if _has_explicit_unknown_target(message, registry):
            return _clarification(kind, registry, "I could not resolve the named project.")
        if matches:
            project_key = matches[0]
        elif context_key:
            project_key = context_key
        elif kind == ProjectQuestionKind.NEXT_MOVE and not _has_project_cue(message):
            return None
        else:
            return _clarification(kind, registry, "Which project do you mean?")

        project = self.brain_service.get_project(
            project_key,
            settings=settings,
            current_time=current_time,
        )
        if project is None:
            return _clarification(kind, registry, "I could not resolve that canonical project.")
        return _answer_from_snapshot(kind, project)


def _question_kind(message: str) -> ProjectQuestionKind | None:
    text = " ".join(message.lower().replace("’", "'").split())
    if not _looks_like_read_question(text):
        return None
    if any(
        phrase in text
        for phrase in (
            "who is involved",
            "who's involved",
            "who works on",
            "people involved",
            "attached context",
        )
    ):
        return ProjectQuestionKind.PEOPLE
    if any(phrase in text for phrase in ("work package", "feature option", "project option", "options right now")):
        return ProjectQuestionKind.WORK_PACKAGES
    if any(
        phrase in text
        for phrase in ("what's blocking", "what is blocking", "blockers", "blocked by", "dependencies")
    ):
        return ProjectQuestionKind.BLOCKERS
    if any(
        phrase in text
        for phrase in ("what should i work on", "next move", "current action", "work on next", "do next")
    ):
        return ProjectQuestionKind.NEXT_MOVE
    if any(
        phrase in text
        for phrase in (
            "what's going on",
            "what is going on",
            "project status",
            "status of",
            "overview",
            "update on",
            "where does",
        )
    ):
        return ProjectQuestionKind.OVERVIEW
    return None


def _looks_like_read_question(text: str) -> bool:
    if re.match(r"^(add|create|delete|move|schedule|update)\b", text) or re.search(
        r"\b(?:can|could|would) you (?:add|create|delete|move|schedule|update)\b",
        text,
    ):
        return False
    return bool(
        text.endswith("?")
        or re.match(r"^(what|who|how|where|which|is|are|can|could|tell|show|give)\b", text)
    )


def _matching_project_keys(message: str, registry: ProjectRegistrySnapshot) -> list[str]:
    normalized = _normalized_words(message)
    matches: set[str] = set()
    for alias, key in registry.aliases.items():
        if key == "needs-classification":
            continue
        if re.search(rf"(?:^| ){re.escape(alias.replace('-', ' '))}(?: |$)", normalized):
            matches.add(key)
    for project in registry.projects:
        if project.get("system_state"):
            continue
        name = _normalized_words(str(project.get("name") or ""))
        if name and re.search(rf"(?:^| ){re.escape(name)}(?: |$)", normalized):
            matches.add(str(project["key"]))
    return sorted(matches)


def _normalized_words(value: str) -> str:
    text = value.lower().replace("&", " and ").replace("_", " ").replace("-", " ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _context_project_key(
    conversation_context: dict[str, Any] | None,
    registry: ProjectRegistrySnapshot,
) -> str | None:
    if not isinstance(conversation_context, dict):
        return None
    reference = conversation_context.get("canonical_project_key")
    if not isinstance(reference, str):
        return None
    project = registry.get_project_definition(reference)
    return str(project["key"]) if project else None


def _has_project_cue(message: str) -> bool:
    text = _normalized_words(message)
    return bool(
        re.search(r"\b(project|for|within)\b", text)
        or re.search(r"\b(next move|current action)\b", text)
    )


def _has_explicit_unknown_target(
    message: str,
    registry: ProjectRegistrySnapshot,
) -> bool:
    text = _normalized_words(message)
    target_patterns = (
        r"\b(?:for|with|status of|update on) (.+?)(?: right now| now)?$",
        r"\b(?:what is|what s|whats) blocking (.+?)(?: right now| now)?$",
        r"\bwhat are (?:my )?(.+?) feature options(?: right now| now)?$",
        r"\bshow (.+?) work packages(?: right now| now)?$",
        r"\bwork packages for (.+?)(?: right now| now)?$",
        r"\bwhere does (.+?) stand(?: right now| now)?$",
        r"\bwho works on (.+?)(?: right now| now)?$",
        r"\bwhat is the (.+?) next move(?: right now| now)?$",
    )
    deictic_targets = {"it", "this", "this project", "the project", "me", "my work", "us"}
    for pattern in target_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        target = match.group(1).strip()
        if target in deictic_targets:
            return False
        if registry.get_project_definition(target) is not None:
            return False
        return not any(
            _normalized_words(str(project.get("name") or "")) == target
            for project in registry.projects
            if not project.get("system_state")
        )
    return False


def _clarification(
    kind: ProjectQuestionKind,
    registry: ProjectRegistrySnapshot,
    prefix: str,
) -> ProjectChatGrounding:
    names = [
        str(project["name"])
        for project in registry.projects
        if not project.get("system_state")
    ]
    return ProjectChatGrounding(
        answer=f"{prefix} Choose one canonical project: {', '.join(names)}.",
        question_kind=kind,
    )


def _answer_from_snapshot(
    kind: ProjectQuestionKind,
    project: dict[str, Any],
) -> ProjectChatGrounding:
    diagnostic = _as_dict(project.get("linear_diagnostic"))
    degraded = not diagnostic or diagnostic.get("status") != "connected"
    warning = _diagnostic_warning(diagnostic) if degraded else None

    if kind in {ProjectQuestionKind.BLOCKERS, ProjectQuestionKind.WORK_PACKAGES} and degraded:
        label = "blocker state" if kind == ProjectQuestionKind.BLOCKERS else "work-package state"
        return ProjectChatGrounding(
            answer=f"{project['name']}'s Linear {label} is unknown. {warning}",
            question_kind=kind,
            canonical_project_key=str(project["key"]),
            warnings=(warning,) if warning else (),
        )

    if kind == ProjectQuestionKind.BLOCKERS:
        answer, evidence = _blocker_answer(project)
    elif kind == ProjectQuestionKind.NEXT_MOVE:
        answer, evidence = _next_move_answer(project)
    elif kind == ProjectQuestionKind.WORK_PACKAGES:
        answer, evidence = _packages_answer(project)
    elif kind == ProjectQuestionKind.PEOPLE:
        answer, evidence = _people_answer(project)
    else:
        answer, evidence = _overview_answer(project, include_linear_state=not degraded)

    if degraded and warning:
        answer = f"{answer} Linear state is degraded: {warning}"
    return ProjectChatGrounding(
        answer=answer,
        question_kind=kind,
        canonical_project_key=str(project["key"]),
        warnings=(warning,) if warning else (),
        evidence=evidence,
    )


def _blocker_answer(project: dict[str, Any]) -> tuple[str, tuple[dict[str, Any], ...]]:
    summary = _as_dict(project.get("dependency_summary"))
    active = int(summary.get("active_dependency_count") or 0)
    blocked = int(summary.get("active_blocked_work_count") or 0)
    review = int(summary.get("needs_review_dependency_count") or 0)
    evidence = tuple(
        item
        for item in (_as_dict(value) for value in project.get("dependency_evidence") or ())
        if item.get("evaluation_state") in {"active", "needs_review"}
    )
    if not active and not review:
        return f"{project['name']} has no current explicit Linear dependency blockers.", evidence

    parts = [f"{project['name']} has {active} active dependencies affecting {blocked} blocked work items"]
    if review:
        label = "dependency needs" if review == 1 else "dependencies need"
        parts.append(f"and {review} {label} review")
    examples = [_dependency_example(item) for item in evidence[:3]]
    suffix = f" Evidence: {'; '.join(examples)}." if examples else ""
    return " ".join(parts) + "." + suffix, evidence


def _dependency_example(evidence: dict[str, Any]) -> str:
    blocked = _as_dict(evidence.get("blocked_work"))
    blocking = _as_dict(evidence.get("blocking_work"))
    blocked_label = blocked.get("provider_identifier") or blocked.get("title") or blocked.get("provider_record_id")
    blocking_label = blocking.get("provider_identifier") or blocking.get("title") or blocking.get("provider_record_id")
    state = str(evidence.get("evaluation_state") or "unknown").replace("_", " ")
    provider = evidence.get("relationship_provider") or "unknown provider"
    return f"{blocked_label} is blocked by {blocking_label} ({state}, {provider})"


def _next_move_answer(project: dict[str, Any]) -> tuple[str, tuple[dict[str, Any], ...]]:
    recommendation = str(project.get("next_recommendation") or "No canonical next move is available.")
    return f"{project['name']}: {recommendation}", ({"next_recommendation": recommendation},)


def _packages_answer(project: dict[str, Any]) -> tuple[str, tuple[dict[str, Any], ...]]:
    packages = tuple(_as_dict(value) for value in project.get("work_packages") or ())
    if not packages:
        return f"Project Brain has no current Linear work packages for {project['name']}.", packages
    details = []
    for package in packages:
        action = _as_dict(package.get("next_action"))
        action_label = action.get("provider_identifier") or action.get("title")
        next_text = f" next: {action_label}" if action_label else " no executable next action"
        availability = str(package.get("availability_state") or "unknown").replace("_", " ")
        provider = package.get("provider") or "unknown provider"
        details.append(f"{package.get('title')} ({provider}, {availability};{next_text})")
    return f"{project['name']} feature options: {'; '.join(details)}.", packages


def _people_answer(project: dict[str, Any]) -> tuple[str, tuple[dict[str, Any], ...]]:
    people = tuple(str(person) for person in project.get("people") or ())
    memories = tuple(_as_dict(value) for value in project.get("memories") or ())
    people_text = ", ".join(people) if people else "no people are attached"
    context_titles = [str(memory.get("title")) for memory in memories if memory.get("title")]
    context_text = f" Attached context: {', '.join(context_titles)}." if context_titles else ""
    evidence = tuple({"person": person} for person in people) + memories
    return f"Project Brain shows {people_text} for {project['name']}.{context_text}", evidence


def _overview_answer(
    project: dict[str, Any],
    *,
    include_linear_state: bool,
) -> tuple[str, tuple[dict[str, Any], ...]]:
    summary = _as_dict(project.get("dependency_summary"))
    active = int(summary.get("active_dependency_count") or 0)
    blocked = int(summary.get("active_blocked_work_count") or 0)
    packages = tuple(_as_dict(value) for value in project.get("work_packages") or ())
    recommendation = str(project.get("next_recommendation") or "No canonical next move is available.")
    answer = (
        f"{project['name']} is {project.get('status') or 'unknown'}. "
        f"Project Brain's next move is: {recommendation}"
    )
    if include_linear_state:
        answer += (
            f" It has {active} active dependencies affecting {blocked} blocked work items and "
            f"{len(packages)} current Linear work packages."
        )
    return answer, ({"next_recommendation": recommendation, "dependency_summary": summary}, *packages)


def _diagnostic_warning(diagnostic: dict[str, Any]) -> str:
    if diagnostic.get("message"):
        return str(diagnostic["message"])
    status = str(diagnostic.get("status") or "unknown").replace("_", " ")
    return f"Linear provider state is {status}."


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


project_chat_grounding_service = ProjectChatGroundingService()
