"""Standalone authenticated HTTP surface for SID-261 ``record_college_update``."""

from __future__ import annotations

from datetime import datetime
import hmac
import json
import os
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException

from .college_capture import (
    CollegeAssessmentRequest,
    CollegeCaptureAdapter,
    CollegeCaptureError,
    CollegeCaptureRequest,
    CollegeLifecycleRequest,
    CollegeQuestionDispositionRequest,
    TrustedCollegeCaptureContext,
)
from .college_domain import CollegeDomainService
from .config import get_settings
from .conversation_context import SharedConversationContextService


FORBIDDEN_FIELDS = {"actor", "actor_id", "workspace", "workspace_id"}
ALLOWED_OPERATIONS = {
    "capture", "request_assessment", "correct_claim", "undo_update",
    "forget_claim", "remove_raw_evidence",
    "set_question_disposition",
}


class CollegeCaptureAuthenticator:
    def __init__(
        self,
        *,
        api_key: str | None,
        actor_id: str | None,
        workspace_id: str | None,
        allowed_section_ids: frozenset[str] | None = None,
        allow_cross_course: bool = False,
        binding_ids_by_conversation: dict[str, tuple[str, ...]] | None = None,
        reviewed_referents: dict[str, str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.actor_id = actor_id
        self.workspace_id = workspace_id
        self.allowed_section_ids = allowed_section_ids
        self.allow_cross_course = allow_cross_course
        self.binding_ids_by_conversation = binding_ids_by_conversation or {}
        self.reviewed_referents = reviewed_referents or {}

    @classmethod
    def from_environment(cls) -> "CollegeCaptureAuthenticator":
        raw_sections = os.getenv("COLLEGE_ALLOWED_SECTION_IDS")
        allowed_sections = None
        if raw_sections is not None:
            allowed_sections = frozenset(
                value.strip() for value in raw_sections.split(",") if value.strip()
            )
        bindings = cls._json_mapping(os.getenv("COLLEGE_BINDINGS_BY_CONVERSATION_JSON"), lists=True)
        referents = cls._json_mapping(os.getenv("COLLEGE_REVIEWED_REFERENTS_JSON"), lists=False)
        return cls(
            api_key=get_settings().agent_api_key,
            actor_id=os.getenv("COLLEGE_ACTOR_ID"),
            workspace_id=os.getenv("COLLEGE_WORKSPACE_ID"),
            allowed_section_ids=allowed_sections,
            allow_cross_course=os.getenv("COLLEGE_ALLOW_CROSS_COURSE", "false").lower()
            in {"1", "true", "yes"},
            binding_ids_by_conversation=bindings,
            reviewed_referents=referents,
        )

    @staticmethod
    def _json_mapping(raw: str | None, *, lists: bool) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise CollegeCaptureError("invalid_server_configuration", "College mapping is invalid.") from exc
        if not isinstance(value, dict):
            raise CollegeCaptureError("invalid_server_configuration", "College mapping is invalid.")
        if lists:
            if not all(isinstance(item, list) for item in value.values()):
                raise CollegeCaptureError("invalid_server_configuration", "Binding mapping is invalid.")
            return {str(key): tuple(map(str, item)) for key, item in value.items()}
        if not all(isinstance(item, str) for item in value.values()):
            raise CollegeCaptureError("invalid_server_configuration", "Referent mapping is invalid.")
        return {str(key): str(item) for key, item in value.items()}

    def authenticate(self, authorization: str | None) -> TrustedCollegeCaptureContext:
        if not self.api_key or not self.actor_id or not self.workspace_id:
            raise HTTPException(status_code=401, detail="College capture authentication is not configured")
        expected = f"Bearer {self.api_key}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return TrustedCollegeCaptureContext(
            actor_id=self.actor_id,
            workspace_id=self.workspace_id,
            allowed_section_ids=self.allowed_section_ids,
            allow_cross_course=self.allow_cross_course,
            binding_ids_by_conversation=self.binding_ids_by_conversation,
            reviewed_referents=self.reviewed_referents,
        )


def _datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise CollegeCaptureError("invalid_request", f"{field} must be an ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CollegeCaptureError("invalid_request", f"{field} must be an ISO timestamp.") from exc
    return parsed


def _request(
    payload: dict[str, Any],
) -> CollegeCaptureRequest | CollegeAssessmentRequest | CollegeLifecycleRequest | CollegeQuestionDispositionRequest:
    if FORBIDDEN_FIELDS & set(payload):
        raise CollegeCaptureError("server_identity_forbidden", "Actor and workspace are server-bound.")
    operation = str(payload.get("operation", "capture"))
    if operation not in ALLOWED_OPERATIONS:
        raise CollegeCaptureError("invalid_operation", "Unsupported College update operation.")
    command_id = str(payload.get("command_id", ""))
    idempotency_key = str(payload.get("idempotency_key", ""))
    if operation == "capture":
        allowed = {
            "operation", "command_id", "idempotency_key", "message", "source_surface",
            "conversation_id", "asserted_at", "timezone", "binding_id",
            "explicitly_selected_binding", "capture_scope", "scope_version",
        }
        if set(payload) - allowed:
            raise CollegeCaptureError("unexpected_request_field", "Unexpected capture request fields.")
        return CollegeCaptureRequest(
            command_id=command_id,
            idempotency_key=idempotency_key,
            message=str(payload.get("message", "")),
            source_surface=str(payload.get("source_surface", "")),
            conversation_id=str(payload.get("conversation_id", "")),
            asserted_at=_datetime(payload.get("asserted_at"), "asserted_at"),
            timezone_name=str(payload.get("timezone", "")),
            binding_id=str(payload["binding_id"]) if payload.get("binding_id") else None,
            explicitly_selected_binding=bool(payload.get("explicitly_selected_binding", False)),
            capture_scope=str(payload.get("capture_scope", "college-operational")),
            scope_version=str(payload.get("scope_version", "1")),
        )
    if operation == "request_assessment":
        allowed = {
            "operation", "command_id", "idempotency_key", "authorized_scope",
            "horizon", "timezone", "valid_through", "baseline", "window",
        }
        if set(payload) - allowed:
            raise CollegeCaptureError("unexpected_request_field", "Unexpected assessment fields.")
        return CollegeAssessmentRequest(
            command_id=command_id,
            idempotency_key=idempotency_key,
            authorized_scope=dict(payload.get("authorized_scope") or {}),
            horizon=dict(payload.get("horizon") or {}),
            timezone_name=str(payload.get("timezone", "")),
            valid_through=_datetime(payload.get("valid_through"), "valid_through"),
            baseline=payload.get("baseline"),
            window=payload.get("window"),
        )
    if operation == "set_question_disposition":
        allowed = {
            "operation", "command_id", "idempotency_key", "question_id",
            "prompt_key", "disposition", "expected_revision", "conversation_id",
            "answer_summary",
        }
        if set(payload) - allowed:
            raise CollegeCaptureError("unexpected_request_field", "Unexpected question fields.")
        disposition = str(payload.get("disposition", ""))
        if disposition not in {"asked", "answered", "deferred"}:
            raise CollegeCaptureError("invalid_request", "Unsupported question disposition.")
        return CollegeQuestionDispositionRequest(
            command_id=command_id,
            idempotency_key=idempotency_key,
            question_id=str(payload.get("question_id", "")),
            prompt_key=str(payload.get("prompt_key", "")),
            disposition=disposition,
            expected_revision=payload.get("expected_revision"),
            conversation_id=str(payload["conversation_id"])
            if payload.get("conversation_id") else None,
            answer_summary=str(payload["answer_summary"])
            if payload.get("answer_summary") else None,
        )
    allowed = {
        "operation", "command_id", "idempotency_key", "claim_id",
        "expected_revision", "value", "evidence_id", "reason",
    }
    if set(payload) - allowed:
        raise CollegeCaptureError("unexpected_request_field", "Unexpected lifecycle fields.")
    return CollegeLifecycleRequest(
        command_id=command_id,
        idempotency_key=idempotency_key,
        operation=operation,
        claim_id=str(payload["claim_id"]) if payload.get("claim_id") else None,
        expected_revision=payload.get("expected_revision"),
        value=payload.get("value"),
        evidence_id=str(payload["evidence_id"]) if payload.get("evidence_id") else None,
        reason=str(payload.get("reason", "user_requested")),
    )


def _http_error(exc: CollegeCaptureError) -> HTTPException:
    if exc.code in {"capture_not_authorized", "scope_not_authorized", "binding_not_authorized"}:
        status = 403
    elif exc.code in {"binding_not_found", "subject_not_found", "claim_not_found"}:
        status = 404
    elif exc.code in {"idempotency_payload_conflict", "revision_conflict"}:
        status = 409
    elif exc.code == "invalid_server_configuration":
        status = 503
    else:
        status = 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _default_adapter() -> CollegeCaptureAdapter:
    return CollegeCaptureAdapter(
        context_service=SharedConversationContextService(),
        college_service=CollegeDomainService(),
    )


def create_college_capture_app(
    *,
    adapter: CollegeCaptureAdapter | None = None,
    authenticator: CollegeCaptureAuthenticator | None = None,
) -> FastAPI:
    auth_service = authenticator or CollegeCaptureAuthenticator.from_environment()
    application = FastAPI(
        title="PCOS College Capture",
        description="Reviewed receipt-backed College conversational capture without provider mutations.",
        version="1.0.0",
    )

    def trusted_context(
        authorization: Annotated[str | None, Header()] = None,
    ) -> TrustedCollegeCaptureContext:
        return auth_service.authenticate(authorization)

    @application.post(
        "/college/update",
        operation_id="record_college_update",
        summary="Record or review one authorized College update",
    )
    def record_college_update(
        payload: Annotated[dict[str, Any], Body()],
        trusted: TrustedCollegeCaptureContext = Depends(trusted_context),
    ) -> dict[str, Any]:
        try:
            parsed = _request(payload)
            return (adapter or _default_adapter()).record_college_update(trusted, parsed)
        except CollegeCaptureError as exc:
            raise _http_error(exc) from exc

    return application


app = create_college_capture_app()


__all__ = [
    "CollegeCaptureAuthenticator", "app", "create_college_capture_app",
]
