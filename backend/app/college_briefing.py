"""Shared SID-147 presentation over the recorded SID-250 College assessment.

This module deliberately consumes only the SID-260 read contract.  It does not
rebuild College attention from claims, refresh a provider, produce an
assessment, or maintain a second College truth store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from .college_reads import (
    CollegeReadError,
    CollegeReadService,
    CollegeStateReadRequest,
    TrustedCollegeContext,
)


COLLEGE_BRIEF_VERSION = "college-brief/1.0"
DECISIVE_CATEGORIES = {
    "current_conflicts_blockers",
    "required_obligations",
    "preparation_pressure",
    "material_unknowns",
    "learning_needs",
    "coordination_blockers",
}
CHANGE_CATEGORIES = {"relevant_changes"}
WAIT_CATEGORIES = {"optional_recommended_opportunities"}


class CollegeBriefItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_id: str
    subject_label: str
    category: str
    categories: tuple[str, ...] = ()
    summary: str
    certainty: str
    due_lower_bound: str | None = None
    evidence_refs: tuple[str, ...]
    source_order: int = Field(..., ge=0)


class CollegeCoverageGap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    account_id: str | None = None
    availability: str
    completeness: str
    freshness: str
    reason: str
    material_to_scope: bool
    evidence_ref: str | None = None


class CollegeBriefProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["college-brief/1.0"] = COLLEGE_BRIEF_VERSION
    scope: Literal["course", "cross_course"]
    course_ids: tuple[str, ...] = ()
    scope_label: str
    assessment_status: str
    assessed_at: datetime | None = None
    valid_through: datetime | None = None
    opening: str
    primary: CollegeBriefItem | None = None
    decisive_items: tuple[CollegeBriefItem, ...] = ()
    session_changes: tuple[CollegeBriefItem, ...] = ()
    safe_to_wait: tuple[CollegeBriefItem, ...] = ()
    coverage_gaps: tuple[CollegeCoverageGap, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    complete_for_scope: bool = False
    whole_college_reassurance: bool = False
    ordinary_read_side_effect_free: Literal[True] = True
    assessment_requested: Literal[False] = False
    provider_refresh_performed: Literal[False] = False
    interaction_cursor_advanced: Literal[False] = False


@dataclass(frozen=True)
class CollegeBriefRequest:
    evaluated_at: datetime
    timezone_name: str
    scope: Literal["course", "cross_course"] = "cross_course"
    course_ids: tuple[str, ...] = ()
    horizon_end: datetime | None = None


class CollegeBriefingService:
    """Turn one recorded assessment into bounded natural-language presentation."""

    def __init__(
        self,
        *,
        read_service_factory: Callable[[], CollegeReadService] = CollegeReadService,
    ) -> None:
        self.read_service_factory = read_service_factory

    def build(
        self,
        auth: TrustedCollegeContext | None,
        request: CollegeBriefRequest,
    ) -> CollegeBriefProjection:
        if request.evaluated_at.tzinfo is None:
            raise ValueError("College brief time must be timezone-aware.")
        scope_label = self._scope_label(request.scope, request.course_ids)
        if auth is None:
            return self._unavailable(
                request,
                scope_label,
                "unconfigured",
                "College reads are not configured for this application surface.",
            )

        horizon_end = request.horizon_end or request.evaluated_at + timedelta(days=1)
        read_request = CollegeStateReadRequest(
            scope=request.scope,
            course_ids=request.course_ids,
            horizon_start=request.evaluated_at,
            horizon_end=horizon_end,
            timezone_name=request.timezone_name,
            limit=50,
        )
        try:
            response, records = self._read_all(auth, read_request)
        except CollegeReadError as exc:
            return self._unavailable(request, scope_label, exc.code, str(exc))

        identities = {
            str(item["canonical_id"]): item
            for item in records
            if item.get("record_type") == "identity"
        }
        assessments = [
            item for item in records if item.get("record_type") == "assessment"
        ]
        current = [
            item for item in assessments if item.get("assessment_status") == "ready"
        ]
        assessment = max(
            current,
            key=lambda item: (str(item.get("assessed_at") or ""), str(item.get("assessment_id") or "")),
            default=None,
        )
        status = str(response.get("assessment_status") or "missing")
        if status == "missing" and response.get("status") in {"uninitialized", "not_found"}:
            status = str(response["status"])
        if assessment is None:
            return self._noncurrent(
                request,
                scope_label,
                status,
                assessments,
                response,
            )

        projected = tuple(
            self._item(item, identities, index)
            for index, item in enumerate(assessment.get("attention_items") or [])
            if isinstance(item, dict)
        )
        decisive = tuple(item for item in projected if item.category in DECISIVE_CATEGORIES)[:5]
        changes = tuple(item for item in projected if item.category in CHANGE_CATEGORIES)[:3]
        waiting = tuple(item for item in projected if item.category in WAIT_CATEGORIES)[:3]
        gaps = self._coverage_gaps(assessment, response)
        evidence = tuple(dict.fromkeys(
            ref
            for item in (*decisive, *changes, *waiting)
            for ref in item.evidence_refs
        ))[:16]
        complete = not any(item.material_to_scope for item in gaps)
        primary = decisive[0] if decisive else None
        if primary is not None:
            opening = primary.summary
        elif gaps:
            opening = (
                f"No decisive College item is recorded for {scope_label}, but material coverage gaps prevent reassurance."
            )
        elif changes:
            opening = f"No College action is recorded for {scope_label}; recent session context is available below."
        else:
            opening = f"No decisive College action is recorded for {scope_label} in this assessment window."
        if request.scope == "course":
            opening += " This is course-scoped and does not describe the rest of College."

        return CollegeBriefProjection(
            scope=request.scope,
            course_ids=request.course_ids,
            scope_label=scope_label,
            assessment_status="ready",
            assessed_at=_datetime(assessment.get("assessed_at")),
            valid_through=_datetime(assessment.get("valid_through")),
            opening=opening,
            primary=primary,
            decisive_items=decisive,
            session_changes=changes,
            safe_to_wait=waiting,
            coverage_gaps=gaps,
            evidence_refs=evidence,
            diagnostics=tuple(_diagnostic_text(item) for item in response.get("diagnostics") or ()),
            complete_for_scope=complete,
            whole_college_reassurance=request.scope == "cross_course" and complete,
        )

    def request_then_build(
        self,
        *,
        assessment_command: Callable[[], Any],
        auth: TrustedCollegeContext | None,
        request: CollegeBriefRequest,
    ) -> CollegeBriefProjection:
        """Run an explicitly selected assessment command, then perform a normal read.

        Surface reads never call this method.  The command remains the SID-250/261
        write boundary; this service still does not produce an assessment itself.
        """

        assessment_command()
        return self.build(auth, request)

    def _read_all(
        self,
        auth: TrustedCollegeContext,
        request: CollegeStateReadRequest,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        service = self.read_service_factory()
        response = service.get_college_state(auth, request)
        records = list(response.get("records") or ())
        cursor = (response.get("pagination") or {}).get("next_cursor")
        while cursor:
            page = service.get_college_state(
                auth,
                CollegeStateReadRequest(
                    scope=request.scope,
                    course_ids=request.course_ids,
                    horizon_start=request.horizon_start,
                    horizon_end=request.horizon_end,
                    timezone_name=request.timezone_name,
                    limit=request.limit,
                    cursor=str(cursor),
                ),
            )
            records.extend(page.get("records") or ())
            cursor = (page.get("pagination") or {}).get("next_cursor")
        return response, records

    @staticmethod
    def _item(
        item: dict[str, Any], identities: dict[str, dict[str, Any]], index: int,
    ) -> CollegeBriefItem:
        subject_id = str(item.get("subject_id") or "unknown")
        attributes = (identities.get(subject_id) or {}).get("attributes") or {}
        label = str(
            attributes.get("label")
            or attributes.get("name")
            or attributes.get("title")
            or subject_id
        )
        category = str(item.get("category") or "material_unknowns")
        value = item.get("summary")
        field = str(item.get("field") or "")
        claim_value = None
        if isinstance(value, str) and ": " in value:
            encoded = (
                value[len(field) + 2:]
                if field and value.startswith(f"{field}: ")
                else value.split(": ", 1)[1]
            )
            try:
                claim_value = json.loads(encoded)
            except (TypeError, ValueError):
                claim_value = encoded
        summary = _natural_summary(
            label=label,
            category=category,
            field=field,
            value=claim_value,
            original=str(value or "Recorded College attention needs review."),
            due_lower=item.get("due_lower_bound"),
        )
        return CollegeBriefItem(
            subject_id=subject_id,
            subject_label=label,
            category=category,
            categories=tuple(str(value) for value in item.get("categories") or (category,)),
            summary=summary,
            certainty=str(item.get("certainty") or "unknown"),
            due_lower_bound=(str(item["due_lower_bound"]) if item.get("due_lower_bound") else None),
            evidence_refs=tuple(str(ref) for ref in item.get("evidence_refs") or ()),
            source_order=index,
        )

    @staticmethod
    def _coverage_gaps(
        assessment: dict[str, Any], response: dict[str, Any],
    ) -> tuple[CollegeCoverageGap, ...]:
        by_key: dict[tuple[str, str | None], CollegeCoverageGap] = {}
        coverage = assessment.get("coverage") or []
        for item in coverage:
            if not isinstance(item, dict):
                continue
            bounds = item.get("bounds") or item.get("declared_scope") or {}
            material = bool(bounds.get("material_to_scope", False))
            availability = str(item.get("availability") or "unknown")
            completeness = str(item.get("completeness") or "unknown")
            freshness = str(item.get("freshness") or "unknown")
            if availability == "healthy" and completeness == "complete" and freshness == "fresh":
                continue
            provider = str(item.get("provider") or "unknown")
            account = str(item.get("account_id")) if item.get("account_id") else None
            by_key[(provider, account)] = CollegeCoverageGap(
                provider=provider,
                account_id=account,
                availability=availability,
                completeness=completeness,
                freshness=freshness,
                reason=str(item.get("reason") or item.get("omission_reason") or "coverage_incomplete"),
                material_to_scope=material,
                evidence_ref=(str(item.get("coverage_id")) if item.get("coverage_id") else None),
            )
        for item in assessment.get("omissions") or ():
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider") or "unknown")
            account = str(item.get("account_id")) if item.get("account_id") else None
            if (provider, account) not in by_key:
                by_key[(provider, account)] = CollegeCoverageGap(
                    provider=provider,
                    account_id=account,
                    availability="unknown",
                    completeness="unknown",
                    freshness="unknown",
                    reason=str(item.get("reason") or "no_coverage_record"),
                    material_to_scope=True,
                )
        for item in response.get("coverage_expectations") or ():
            if not isinstance(item, dict) or str(item.get("provider", "")).lower() != "blinn":
                continue
            provider = "blinn"
            account = str(item.get("account_id")) if item.get("account_id") else None
            key = (provider, account)
            if key not in by_key:
                by_key[key] = CollegeCoverageGap(
                    provider=provider,
                    account_id=account,
                    availability=str(item.get("availability") or "pending"),
                    completeness=str(item.get("completeness") or "unknown"),
                    freshness=str(item.get("freshness") or "unknown"),
                    reason=str(item.get("reason") or "administrator_approval"),
                    material_to_scope=False,
                )
        return tuple(by_key.values())[:8]

    @staticmethod
    def _scope_label(scope: str, course_ids: tuple[str, ...]) -> str:
        if scope == "course":
            return ", ".join(course_ids) if course_ids else "the requested course"
        return "the cross-course view"

    def _noncurrent(
        self,
        request: CollegeBriefRequest,
        scope_label: str,
        status: str,
        assessments: list[dict[str, Any]],
        response: dict[str, Any],
    ) -> CollegeBriefProjection:
        latest = max(
            assessments,
            key=lambda item: (str(item.get("assessed_at") or ""), str(item.get("assessment_id") or "")),
            default=None,
        )
        honest_status = str((latest or {}).get("assessment_status") or status or "missing")
        language = {
            "missing": "No recorded assessment is available.",
            "queued": "The requested assessment is queued; no current conclusion is available yet.",
            "running": "The requested assessment is still running; no current conclusion is available yet.",
            "failed": "The recorded assessment failed; no current conclusion is available.",
            "expired": "The latest recorded assessment has expired and is not presented as current.",
            "invalidated": "The latest recorded assessment was invalidated by newer state and is not presented as current.",
            "uninitialized": "The College store is not initialized for this read.",
            "not_found": "No authorized College state is available for this scope.",
        }.get(honest_status, "No current recorded assessment is available.")
        opening = f"{language} This read did not refresh providers or produce another assessment."
        if request.scope == "course":
            opening += " This is course-scoped and cannot reassure the rest of College."
        return CollegeBriefProjection(
            scope=request.scope,
            course_ids=request.course_ids,
            scope_label=scope_label,
            assessment_status=honest_status,
            assessed_at=_datetime((latest or {}).get("assessed_at")),
            valid_through=_datetime((latest or {}).get("valid_through")),
            opening=opening,
            coverage_gaps=self._coverage_gaps(latest or {}, response),
            diagnostics=tuple(_diagnostic_text(item) for item in response.get("diagnostics") or ()),
        )

    @staticmethod
    def _unavailable(
        request: CollegeBriefRequest, scope_label: str, status: str, message: str,
    ) -> CollegeBriefProjection:
        return CollegeBriefProjection(
            scope=request.scope,
            course_ids=request.course_ids,
            scope_label=scope_label,
            assessment_status=status,
            opening=f"College state is unavailable for {scope_label}. {message}",
            diagnostics=(message,),
        )


def college_context_from_environment() -> TrustedCollegeContext | None:
    actor = os.getenv("COLLEGE_ACTOR_ID")
    workspace = os.getenv("COLLEGE_WORKSPACE_ID")
    if not actor or not workspace:
        return None
    raw_courses = os.getenv("COLLEGE_ALLOWED_COURSE_IDS")
    courses = None
    if raw_courses is not None:
        courses = frozenset(value.strip() for value in raw_courses.split(",") if value.strip())
    return TrustedCollegeContext(
        actor_id=actor,
        workspace_id=workspace,
        allowed_course_ids=courses,
        allow_cross_course=os.getenv("COLLEGE_ALLOW_CROSS_COURSE", "false").lower()
        in {"1", "true", "yes"},
    )


def _natural_summary(
    *, label: str, category: str, field: str, value: Any, original: str,
    due_lower: Any,
) -> str:
    if category == "current_conflicts_blockers":
        return f"{label} has conflicting recorded evidence that needs review."
    if category == "required_obligations":
        return f"{label} is a required obligation{f' due {due_lower}' if due_lower else ''}."
    if category == "preparation_pressure":
        return f"{label} still needs preparation before{f' {due_lower}' if due_lower else ' its required work'}."
    if category == "material_unknowns":
        if label.startswith("coverage:"):
            return original
        return f"{label} has a material uncertainty that could change the conclusion."
    if category == "learning_needs":
        detail = _plain_value(value)
        return (
            f"Learning is still needed for {label}{f': {detail}' if detail else ''}. "
            "Finished work remains a separate recorded fact."
        )
    if category == "coordination_blockers":
        return f"{label} has a recorded coordination blocker."
    if category == "optional_recommended_opportunities":
        return f"{label} is optional or recommended; it does not block today's closure."
    if field.startswith("session:"):
        detail = _plain_value(value)
        return f"{label} has a recorded session change{f': {detail}' if detail else ''}."
    if "consumes capacity" in original:
        return f"{label} is a selected commitment and consumes time even though its provider marks the time free."
    detail = _plain_value(value)
    return f"{label} changed{f': {detail}' if detail else ''}."


def _plain_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("statement", "title", "value", "status", "kind"):
            if isinstance(value.get(key), str):
                return str(value[key])
    return ""


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _diagnostic_text(value: Any) -> str:
    if isinstance(value, dict):
        return ": ".join(str(item) for item in (value.get("code"), value.get("provider")) if item)
    return str(value)


college_briefing_service = CollegeBriefingService()
