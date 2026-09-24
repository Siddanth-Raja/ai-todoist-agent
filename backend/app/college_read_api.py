"""Authenticated HTTP exposure for the two SID-260 College reads.

Run independently with ``uvicorn app.college_read_api:app``.  Keeping this
surface separate avoids modifying the externally paused SID-249 application
entrypoint while retaining the repository's FastAPI and bearer-key convention.
"""

from __future__ import annotations

from datetime import datetime
import hmac
import os
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request

from .college_reads import (
    CollegeReadError,
    CollegeReadService,
    CollegeStateReadRequest,
    CollegeStatusReadRequest,
    TrustedCollegeContext,
)
from .config import get_settings


FORBIDDEN_IDENTITY_FIELDS = {"actor_id", "workspace_id", "actor", "workspace"}
STATE_QUERY_FIELDS = {
    "scope", "course_id", "horizon_start", "horizon_end", "timezone", "limit", "cursor",
}
STATUS_QUERY_FIELDS = {"command_id", "idempotency_key", "receipt_id"}


class CollegeReadAuthenticator:
    """Bind the bearer credential to server-configured College identity."""

    def __init__(
        self,
        *,
        api_key: str | None,
        actor_id: str | None,
        workspace_id: str | None,
        allowed_course_ids: frozenset[str] | None = None,
        allow_cross_course: bool = True,
    ) -> None:
        self.api_key = api_key
        self.actor_id = actor_id
        self.workspace_id = workspace_id
        self.allowed_course_ids = allowed_course_ids
        self.allow_cross_course = allow_cross_course

    @classmethod
    def from_environment(cls) -> "CollegeReadAuthenticator":
        raw_courses = os.getenv("COLLEGE_ALLOWED_COURSE_IDS")
        allowed_courses = None
        if raw_courses is not None:
            allowed_courses = frozenset(
                value.strip() for value in raw_courses.split(",") if value.strip()
            )
        return cls(
            api_key=get_settings().agent_api_key,
            actor_id=os.getenv("COLLEGE_ACTOR_ID"),
            workspace_id=os.getenv("COLLEGE_WORKSPACE_ID"),
            allowed_course_ids=allowed_courses,
            allow_cross_course=os.getenv("COLLEGE_ALLOW_CROSS_COURSE", "false").lower()
            in {"1", "true", "yes"},
        )

    def authenticate(self, authorization: str | None) -> TrustedCollegeContext:
        if not self.api_key or not self.actor_id or not self.workspace_id:
            raise HTTPException(status_code=401, detail="College read authentication is not configured")
        expected = f"Bearer {self.api_key}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return TrustedCollegeContext(
            actor_id=self.actor_id,
            workspace_id=self.workspace_id,
            allowed_course_ids=self.allowed_course_ids,
            allow_cross_course=self.allow_cross_course,
        )


def _reject_spoofing(request: Request, allowed_fields: set[str]) -> None:
    supplied = set(request.query_params.keys())
    forbidden = supplied & FORBIDDEN_IDENTITY_FIELDS
    forbidden_headers = {
        name for name in ("x-actor-id", "x-workspace-id") if name in request.headers
    }
    if forbidden or forbidden_headers:
        raise HTTPException(status_code=400, detail="Actor and workspace are server-bound")
    unexpected = supplied - allowed_fields
    if unexpected:
        raise HTTPException(status_code=400, detail="Unexpected request fields")


def _http_error(exc: CollegeReadError) -> HTTPException:
    if exc.code in {"store_unavailable"}:
        return HTTPException(status_code=503, detail={"code": exc.code, "message": str(exc)})
    if exc.code in {"scope_not_authorized"}:
        return HTTPException(status_code=403, detail={"code": exc.code, "message": str(exc)})
    if exc.code in {"snapshot_changed"}:
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})


def create_college_read_app(
    *,
    service: CollegeReadService | None = None,
    authenticator: CollegeReadAuthenticator | None = None,
) -> FastAPI:
    read_service = service or CollegeReadService()
    auth_service = authenticator or CollegeReadAuthenticator.from_environment()
    application = FastAPI(
        title="PCOS College Reads",
        description="Least-privilege, side-effect-free College state and receipt reads.",
        version="1.0.0",
    )

    def trusted_context(
        authorization: Annotated[str | None, Header()] = None,
    ) -> TrustedCollegeContext:
        return auth_service.authenticate(authorization)

    @application.get(
        "/college/state",
        operation_id="get_college_state",
        summary="Read a bounded recorded College snapshot",
    )
    def get_college_state(
        request: Request,
        scope: Annotated[str, Query(pattern="^(course|cross_course)$")],
        horizon_start: datetime,
        horizon_end: datetime,
        timezone: Annotated[str, Query(min_length=1, max_length=64)],
        course_id: Annotated[list[str] | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        trusted: TrustedCollegeContext = Depends(trusted_context),
    ) -> dict:
        _reject_spoofing(request, STATE_QUERY_FIELDS)
        try:
            return read_service.get_college_state(
                trusted,
                CollegeStateReadRequest(
                    scope=scope,
                    horizon_start=horizon_start,
                    horizon_end=horizon_end,
                    timezone_name=timezone,
                    course_ids=tuple(course_id or ()),
                    limit=limit,
                    cursor=cursor,
                ),
            )
        except CollegeReadError as exc:
            raise _http_error(exc) from exc

    @application.get(
        "/college/update-status",
        operation_id="get_update_status",
        summary="Read one durable College command receipt",
    )
    def get_update_status(
        request: Request,
        command_id: Annotated[str | None, Query(max_length=128)] = None,
        idempotency_key: Annotated[str | None, Query(max_length=128)] = None,
        receipt_id: Annotated[str | None, Query(max_length=128)] = None,
        trusted: TrustedCollegeContext = Depends(trusted_context),
    ) -> dict:
        _reject_spoofing(request, STATUS_QUERY_FIELDS)
        try:
            return read_service.get_update_status(
                trusted,
                CollegeStatusReadRequest(
                    command_id=command_id,
                    idempotency_key=idempotency_key,
                    receipt_id=receipt_id,
                ),
            )
        except CollegeReadError as exc:
            raise _http_error(exc) from exc

    return application


app = create_college_read_app()


__all__ = ["CollegeReadAuthenticator", "app", "create_college_read_app"]
