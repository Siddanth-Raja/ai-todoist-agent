"""SID-261 reviewed conversational capture adapter.

The adapter translates a deliberately small, reviewed set of College conversation
updates into the published ``college-event/1.0`` contract.  It owns no persistence:
SID-151 remains authoritative for opt-in, bindings, review context and lifecycle;
SID-250 remains authoritative for events, claims, revisions and receipts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, Callable, Literal
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .college_domain import (
    COLLEGE_EVENT_VERSION,
    CollegeCommandIdentity,
    CollegeDomainError,
    CollegeDomainService,
    CollegeScope,
)
from .conversation_context import (
    CommandIdentity,
    ContextScope,
    ContextStoreError,
    SharedConversationContextService,
)


CAPTURE_SCOPE = "college-operational"
CAPTURE_SCOPE_VERSION = "1"
MAX_MESSAGE_CHARS = 4_000
SURFACES = {"chatgpt", "app"}


class CollegeCaptureError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TrustedCollegeCaptureContext:
    """Server-created principal, permissions, and reviewed referent aliases."""

    actor_id: str
    workspace_id: str
    allowed_section_ids: frozenset[str] | None = None
    allow_cross_course: bool = False
    binding_ids_by_conversation: dict[str, tuple[str, ...]] = field(default_factory=dict)
    reviewed_referents: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.actor_id.strip() or not self.workspace_id.strip():
            raise CollegeCaptureError("invalid_auth_context", "Trusted College identity is incomplete.")


@dataclass(frozen=True)
class CollegeCaptureRequest:
    command_id: str
    idempotency_key: str
    message: str
    source_surface: Literal["chatgpt", "app"]
    conversation_id: str
    asserted_at: datetime
    timezone_name: str
    binding_id: str | None = None
    explicitly_selected_binding: bool = False
    capture_scope: str = CAPTURE_SCOPE
    scope_version: str = CAPTURE_SCOPE_VERSION


@dataclass(frozen=True)
class CollegeAssessmentRequest:
    command_id: str
    idempotency_key: str
    authorized_scope: dict[str, Any]
    horizon: dict[str, Any]
    timezone_name: str
    valid_through: datetime
    baseline: dict[str, Any] | None = None
    window: dict[str, Any] | None = None


@dataclass(frozen=True)
class CollegeLifecycleRequest:
    command_id: str
    idempotency_key: str
    operation: Literal["correct_claim", "undo_update", "forget_claim", "remove_raw_evidence"]
    claim_id: str | None = None
    expected_revision: int | None = None
    value: Any = None
    evidence_id: str | None = None
    reason: str = "user_requested"


@dataclass(frozen=True)
class CollegeQuestionDispositionRequest:
    command_id: str
    idempotency_key: str
    question_id: str
    prompt_key: str
    disposition: Literal["asked", "answered", "deferred"]
    expected_revision: int | None
    conversation_id: str | None = None
    answer_summary: str | None = None


class CollegeCaptureAdapter:
    """One capture boundary shared by ChatGPT and equivalent app surfaces."""

    def __init__(
        self,
        *,
        context_service: SharedConversationContextService,
        college_service: CollegeDomainService,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        before_apply: Callable[[], None] | None = None,
        receive_only: bool = False,
    ) -> None:
        self.context_service = context_service
        self.college_service = college_service
        self.clock = clock
        self.before_apply = before_apply
        self.receive_only = receive_only

    def record_college_update(
        self,
        auth: TrustedCollegeCaptureContext,
        request: CollegeCaptureRequest | CollegeAssessmentRequest | CollegeLifecycleRequest
        | CollegeQuestionDispositionRequest,
    ) -> dict[str, Any]:
        if isinstance(request, CollegeCaptureRequest):
            return self._capture(auth, request)
        if isinstance(request, CollegeAssessmentRequest):
            return self._assessment(auth, request)
        if isinstance(request, CollegeLifecycleRequest):
            return self._lifecycle(auth, request)
        if isinstance(request, CollegeQuestionDispositionRequest):
            return self._question_disposition(auth, request)
        raise CollegeCaptureError("invalid_request", "Unsupported College update request.")

    @staticmethod
    def _scopes(auth: TrustedCollegeCaptureContext) -> tuple[ContextScope, CollegeScope]:
        return (
            ContextScope(auth.actor_id, auth.workspace_id),
            CollegeScope(auth.actor_id, auth.workspace_id),
        )

    def _capture(
        self, auth: TrustedCollegeCaptureContext, request: CollegeCaptureRequest
    ) -> dict[str, Any]:
        self._validate_capture_request(request)
        context_scope, college_scope = self._scopes(auth)
        self._require_opt_in(context_scope, request.capture_scope, request.scope_version)
        binding = self._resolve_binding(auth, context_scope, request)
        if binding is None:
            return self._save_for_review(
                context_scope,
                request,
                reason="ambiguous_course_identity",
                prompt="Which reviewed course and term does this update belong to?",
            )
        section_id = str(binding["section_id"])
        self._authorize_sections(auth, {section_id})
        events = self._events(auth, college_scope, request, section_id)
        if not events:
            return self._save_for_review(
                context_scope,
                request,
                reason="ambiguous_consequential_claim",
                prompt="What College fact should I record from that update?",
                binding_id=str(binding["binding_id"]),
            )
        subjects = {str(event["subject_ref"]) for event in events}
        self._authorize_subjects(auth, college_scope, section_id, subjects)
        if self.before_apply is not None:
            self.before_apply()
        identity = CollegeCommandIdentity(request.command_id, request.idempotency_key)
        try:
            receipt = (
                self.college_service.receive_update(college_scope, identity, events)
                if self.receive_only
                else self.college_service.record_update(college_scope, identity, events)
            )
        except CollegeDomainError as exc:
            raise CollegeCaptureError(exc.code, str(exc)) from exc
        return self._acknowledgment(receipt)

    def _assessment(
        self, auth: TrustedCollegeCaptureContext, request: CollegeAssessmentRequest
    ) -> dict[str, Any]:
        _, college_scope = self._scopes(auth)
        scope_kind = request.authorized_scope.get("kind")
        subjects = {str(value) for value in request.authorized_scope.get("subject_ids", [])}
        if scope_kind == "cross_course" and not auth.allow_cross_course:
            raise CollegeCaptureError("scope_not_authorized", "Cross-course assessment is not authorized.")
        if scope_kind == "course":
            self._authorize_sections(auth, subjects)
        identity = CollegeCommandIdentity(request.command_id, request.idempotency_key)
        try:
            receipt = self.college_service.request_assessment(
                college_scope,
                identity,
                authorized_scope=request.authorized_scope,
                horizon=request.horizon,
                timezone_name=request.timezone_name,
                valid_through=request.valid_through,
                baseline=request.baseline,
                window=request.window,
            )
        except CollegeDomainError as exc:
            raise CollegeCaptureError(exc.code, str(exc)) from exc
        return self._acknowledgment(receipt)

    def _lifecycle(
        self, auth: TrustedCollegeCaptureContext, request: CollegeLifecycleRequest
    ) -> dict[str, Any]:
        _, college_scope = self._scopes(auth)
        if request.operation == "remove_raw_evidence" and not auth.allow_cross_course:
            raise CollegeCaptureError(
                "scope_not_authorized",
                "Raw-evidence removal requires authorized cross-course lifecycle scope.",
            )
        if request.claim_id is not None:
            self._authorize_claim(auth, college_scope, request.claim_id)
        identity = CollegeCommandIdentity(request.command_id, request.idempotency_key)
        try:
            if request.operation == "correct_claim":
                if request.claim_id is None or request.expected_revision is None:
                    raise CollegeCaptureError("invalid_lifecycle_request", "Claim and revision are required.")
                receipt = self.college_service.correct_claim(
                    college_scope, identity, claim_id=request.claim_id,
                    expected_revision=request.expected_revision, value=request.value,
                    reason=request.reason,
                )
            elif request.operation == "undo_update":
                if request.claim_id is None or request.expected_revision is None:
                    raise CollegeCaptureError("invalid_lifecycle_request", "Claim and revision are required.")
                receipt = self.college_service.undo_update(
                    college_scope, identity, claim_id=request.claim_id,
                    expected_revision=request.expected_revision, reason=request.reason,
                )
            elif request.operation == "forget_claim":
                if request.claim_id is None:
                    raise CollegeCaptureError("invalid_lifecycle_request", "Claim is required.")
                receipt = self.college_service.forget_claim(
                    college_scope, identity, claim_id=request.claim_id, reason=request.reason,
                )
            else:
                if request.evidence_id is None:
                    raise CollegeCaptureError("invalid_lifecycle_request", "Evidence is required.")
                receipt = self.college_service.remove_raw_evidence(
                    college_scope, identity, evidence_id=request.evidence_id,
                    reason=request.reason,
                )
        except CollegeDomainError as exc:
            raise CollegeCaptureError(exc.code, str(exc)) from exc
        return self._acknowledgment(receipt)

    def _question_disposition(
        self,
        auth: TrustedCollegeCaptureContext,
        request: CollegeQuestionDispositionRequest,
    ) -> dict[str, Any]:
        context_scope, _ = self._scopes(auth)
        try:
            receipt = self.context_service.set_question_disposition(
                context_scope,
                CommandIdentity(request.command_id, request.idempotency_key),
                question_id=request.question_id,
                prompt_key=request.prompt_key,
                disposition=request.disposition,
                expected_revision=request.expected_revision,
                answer_summary=request.answer_summary,
                conversation_id=request.conversation_id,
            )
        except ContextStoreError as exc:
            raise CollegeCaptureError(exc.code, str(exc)) from exc
        return self._context_acknowledgment(
            receipt,
            message=f"Clarification marked {request.disposition}.",
        )

    @staticmethod
    def _validate_capture_request(request: CollegeCaptureRequest) -> None:
        if not request.command_id.strip() or not request.idempotency_key.strip():
            raise CollegeCaptureError("invalid_command_identity", "Command identity is required.")
        if request.source_surface not in SURFACES:
            raise CollegeCaptureError("invalid_surface", "Unsupported conversation surface.")
        if not request.conversation_id.strip():
            raise CollegeCaptureError("conversation_required", "Conversation identity is required.")
        if not request.message.strip() or len(request.message) > MAX_MESSAGE_CHARS:
            raise CollegeCaptureError("invalid_message", "The College update is empty or too large.")
        if request.asserted_at.tzinfo is None:
            raise CollegeCaptureError("timezone_required", "Assertion time must include a timezone.")
        try:
            ZoneInfo(request.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise CollegeCaptureError("invalid_timezone", "An IANA timezone is required.") from exc

    def _require_opt_in(self, scope: ContextScope, capture_scope: str, version: str) -> None:
        active = any(
            item["scope"] == capture_scope
            and item["scope_version"] == version
            and item["capture_enabled"]
            and item["revoked_at"] is None
            for item in self.context_service.inspect_consents(scope)
        )
        if not active:
            raise CollegeCaptureError(
                "capture_not_authorized", "Exact-scope active College capture opt-in is required."
            )

    def _resolve_binding(
        self,
        auth: TrustedCollegeCaptureContext,
        scope: ContextScope,
        request: CollegeCaptureRequest,
    ) -> dict[str, Any] | None:
        if request.binding_id is not None:
            binding = self.context_service.get_course_binding(
                scope, request.binding_id, at=request.asserted_at
            )
            if binding is None:
                raise CollegeCaptureError("binding_not_found", "Reviewed course binding was not found.")
            if not binding["valid"]:
                raise CollegeCaptureError("binding_not_valid", "Reviewed course binding is expired or revoked.")
            if (
                binding["conversation_id"] not in {None, request.conversation_id}
                and not request.explicitly_selected_binding
            ):
                raise CollegeCaptureError("binding_not_authorized", "Binding does not match this conversation.")
            return binding
        candidates = []
        for binding_id in auth.binding_ids_by_conversation.get(request.conversation_id, ()):
            binding = self.context_service.get_course_binding(scope, binding_id, at=request.asserted_at)
            if binding is not None and binding["valid"]:
                candidates.append(binding)
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _authorize_sections(
        auth: TrustedCollegeCaptureContext, section_ids: set[str]
    ) -> None:
        if auth.allowed_section_ids is not None and not section_ids.issubset(auth.allowed_section_ids):
            raise CollegeCaptureError("scope_not_authorized", "College section is not authorized.")

    def _authorize_subjects(
        self,
        auth: TrustedCollegeCaptureContext,
        scope: CollegeScope,
        section_id: str,
        subject_ids: set[str],
    ) -> None:
        state = self.college_service.inspect_state(scope)
        identities = {str(item["canonical_id"]): item for item in state["identities"]}
        for subject_id in subject_ids:
            identity = identities.get(subject_id)
            if identity is None:
                raise CollegeCaptureError("subject_not_found", "Reviewed College subject was not found.")
            parents = self._json_list(identity.get("parent_ids_json"))
            if subject_id != section_id and section_id not in parents:
                raise CollegeCaptureError("scope_not_authorized", "College subject is outside the binding.")

    def _authorize_claim(
        self,
        auth: TrustedCollegeCaptureContext,
        scope: CollegeScope,
        claim_id: str,
    ) -> None:
        state = self.college_service.inspect_state(scope)
        claim = next(
            (item for item in state["claims"] if str(item["claim_id"]) == claim_id),
            None,
        )
        if claim is None:
            raise CollegeCaptureError("claim_not_found", "College claim was not found.")
        if auth.allowed_section_ids is None:
            return
        subject_id = str(claim["subject_id"])
        identities = {str(item["canonical_id"]): item for item in state["identities"]}
        parents = set(self._json_list(identities.get(subject_id, {}).get("parent_ids_json")))
        if subject_id not in auth.allowed_section_ids and not (parents & auth.allowed_section_ids):
            raise CollegeCaptureError("scope_not_authorized", "College claim is outside the authorized scope.")

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            import json
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        return []

    def _events(
        self,
        auth: TrustedCollegeCaptureContext,
        scope: CollegeScope,
        request: CollegeCaptureRequest,
        section_id: str,
    ) -> list[dict[str, Any]]:
        message = " ".join(request.message.strip().split())
        lowered = message.casefold().rstrip(".")
        date = request.asserted_at.astimezone(ZoneInfo(request.timezone_name)).date().isoformat()
        evidence = [{
            "evidence_id": f"conversation:{request.source_surface}:{request.conversation_id}:{request.command_id}",
            "retained_attestation": True,
        }]
        events: list[tuple[str, str, dict[str, Any], list[str]]] = []

        calc = re.fullmatch(
            r"calc covered (.+?) today; there was (?:a|an) (.+?) and (?:a|an) (.+)",
            lowered,
        )
        if calc:
            topic, check, warning = calc.groups()
            entries = [
                self._observation("topic", "topic_covered", topic, request),
                self._observation(
                    "check", "assessment_observed",
                    {"kind": check.replace(" ", "_"), "status": "occurred", "outcome": "unknown"},
                    request,
                ),
                self._observation("announcement", "announcement_reported", warning, request),
            ]
            session_id = self._stable_id("session", section_id, date, request.command_id)
            payload = self._session_payload(session_id, date, request, entries)
            fields = [self._observation_field(session_id, item) for item in entries]
            events.append(("course_progress_recorded", section_id, payload, fields))

        derivatives = re.fullmatch(
            r"we covered (.+?); i(?:'m| am) lost on (.+)", lowered
        )
        if derivatives:
            topic, need = derivatives.groups()
            session_id = self._stable_id("session", section_id, date, request.command_id)
            entry = self._observation("topic", "topic_covered", topic, request)
            events.append((
                "course_progress_recorded", section_id,
                self._session_payload(session_id, date, request, [entry]),
                [self._observation_field(session_id, entry)],
            ))
            events.append((
                "study_need_recorded", section_id,
                {"statement": need, "resolution": "open", "topic": topic},
                ["learning_need"],
            ))

        mixed = re.fullmatch(
            r"topic 4 individual is submitted but needs work; team started, no group chat",
            lowered,
        )
        if mixed:
            individual = self._referent(auth, "topic 4 individual")
            team = self._referent(auth, "team")
            if individual is None or team is None or individual == team:
                return []
            events.append((
                "completion_submission_recorded", individual,
                {"submission": "submitted"}, ["submission"],
            ))
            individual_session = self._stable_id("session", individual, date, request.command_id)
            individual_entry = self._observation(
                "work-concern", "coordination_blocker",
                {"impediment": "needs work", "resolution": "unknown"}, request,
            )
            events.append((
                "course_progress_recorded", individual,
                self._session_payload(individual_session, date, request, [individual_entry]),
                [self._observation_field(individual_session, individual_entry)],
            ))
            events.append((
                "completion_submission_recorded", team,
                {"completion": "in_progress"}, ["completion"],
            ))
            team_session = self._stable_id("session", team, date, request.command_id)
            team_entry = self._observation(
                "group-chat", "coordination_blocker",
                {"impediment": "no group chat", "resolution": "open"}, request,
            )
            events.append((
                "course_progress_recorded", team,
                self._session_payload(team_session, date, request, [team_entry]),
                [self._observation_field(team_session, team_entry)],
            ))

        claims = self.college_service.inspect_state(scope)["claims"]
        source_key = hashlib.sha256(
            f"{auth.actor_id}\0{request.asserted_at.isoformat()}\0{lowered}".encode()
        ).hexdigest()
        result = []
        for ordinal, (event_type, subject_id, payload, fields) in enumerate(events):
            event_id = self._stable_id("event", request.command_id, str(ordinal))
            result.append({
                "schema_version": COLLEGE_EVENT_VERSION,
                "event_id": event_id,
                "event_type": event_type,
                "subject_ref": subject_id,
                "payload": payload,
                "expected_revisions": [
                    {
                        "subject_id": subject_id,
                        "field": name,
                        "revision": self._expected_revision(
                            claims, subject_id, name, event_id
                        ),
                    }
                    for name in fields
                ],
                "source_class": "user_confirmed",
                "source_actor": "authenticated_user",
                "source_surface_hint": f"{request.source_surface}:{request.conversation_id}",
                "asserted_at": request.asserted_at,
                "evidence": evidence,
                "certainty": "confirmed",
                "freshness": {"state": "fresh", "observed_at": request.asserted_at.isoformat()},
                "supersedes_event_ids": [],
                "action_intent": "no_provider_action",
                "source_independence_key": source_key,
            })
        return result

    @staticmethod
    def _expected_revision(
        claims: list[dict[str, Any]], subject_id: str, field: str, event_id: str
    ) -> int | str:
        exact = [
            int(claim["revision"])
            for claim in claims
            if str(claim["subject_id"]) == subject_id
            and str(claim["field"]) == field
            and str(claim["event_id"]) == event_id
        ]
        if exact:
            prior = min(exact) - 1
            return prior if prior else "absent"
        current = [
            int(claim["revision"])
            for claim in claims
            if str(claim["subject_id"]) == subject_id
            and str(claim["field"]) == field
        ]
        return max(current) if current else "absent"

    @staticmethod
    def _referent(auth: TrustedCollegeCaptureContext, alias: str) -> str | None:
        exact = [
            value for key, value in auth.reviewed_referents.items()
            if key.casefold().strip() == alias.casefold().strip()
        ]
        return exact[0] if len(set(exact)) == 1 else None

    @staticmethod
    def _stable_id(kind: str, *parts: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(("pcos", kind, *parts))))

    @staticmethod
    def _observation(
        name: str, kind: str, value: Any, request: CollegeCaptureRequest
    ) -> dict[str, Any]:
        return {
            "observation_id": name,
            "kind": kind,
            "value": value,
            "source_class": "user_confirmed",
            "source_actor": "authenticated_user",
            "asserted_at": request.asserted_at.isoformat(),
            "certainty": "confirmed",
        }

    @staticmethod
    def _session_payload(
        session_id: str,
        date: str,
        request: CollegeCaptureRequest,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "payload_kind": "session_observation",
            "session_id": session_id,
            "session_date": date,
            "timezone": request.timezone_name,
            "date_precision": "date",
            "entries": entries,
        }

    @staticmethod
    def _observation_field(session_id: str, entry: dict[str, Any]) -> str:
        return f"session:{session_id}:{entry['observation_id']}:{entry['kind']}"

    def _save_for_review(
        self,
        scope: ContextScope,
        request: CollegeCaptureRequest,
        *,
        reason: str,
        prompt: str,
        binding_id: str | None = None,
    ) -> dict[str, Any]:
        item_id = self._stable_id("review", request.command_id)
        try:
            receipt = self.context_service.capture_context(
                scope,
                CommandIdentity(request.command_id, request.idempotency_key),
                item_id=item_id,
                capture_scope=request.capture_scope,
                scope_version=request.scope_version,
                context_kind="operational_attestation",
                content={"reported_update": request.message, "review_reason": reason},
                source_identity=f"{request.source_surface}:{request.conversation_id}",
                source_authority="authenticated_user_report",
                asserted_at=request.asserted_at,
                conversation_id=request.conversation_id,
                binding_id=binding_id,
                raw_content=request.message,
                certainty="unknown",
                attestation={
                    "subject_ref": binding_id or "unresolved-course",
                    "field": "college_update",
                    "normalized_value": "needs_review",
                    "source_verified": True,
                },
            )
        except ContextStoreError as exc:
            raise CollegeCaptureError(exc.code, str(exc)) from exc
        question_id = self._stable_id("question", request.command_id)
        try:
            question_receipt = self.context_service.set_question_disposition(
                scope,
                CommandIdentity(
                    f"{request.command_id}:question",
                    f"{request.idempotency_key}:question",
                ),
                question_id=question_id,
                prompt_key=reason,
                disposition="asked",
                expected_revision=None,
                conversation_id=request.conversation_id,
            )
        except ContextStoreError as exc:
            raise CollegeCaptureError(exc.code, str(exc)) from exc
        return {
            "outcome": "saved_for_review",
            "acknowledgment": "Saved your report for review; I did not treat the ambiguous detail as confirmed.",
            "receipt_id": receipt["receipt_id"],
            "receipt_state": receipt["state"],
            "delivery_disposition": receipt["delivery_disposition"],
            "review": {
                "reason": reason,
                "prompt": prompt,
                "item_id": item_id,
                "question_id": question_id,
                "question_receipt_id": question_receipt["receipt_id"],
            },
            "provider_actions": [],
        }

    @staticmethod
    def _context_acknowledgment(
        receipt: dict[str, Any], *, message: str
    ) -> dict[str, Any]:
        return {
            "outcome": "applied" if receipt["state"] == "applied" else "saved_for_review",
            "acknowledgment": message,
            "receipt_id": receipt["receipt_id"],
            "receipt_state": receipt["state"],
            "delivery_disposition": receipt["delivery_disposition"],
            "status_lookup": {
                "service": "sid-151",
                "command_id": receipt["command_id"],
            },
            "provider_actions": [],
        }

    @staticmethod
    def _acknowledgment(receipt: dict[str, Any]) -> dict[str, Any]:
        state = str(receipt["state"])
        if state == "applied":
            outcome = "applied"
            message = "Recorded that College update. No provider record was changed."
        elif state == "needs_review":
            outcome = "saved_for_review"
            message = "Saved the update for review without treating the uncertain part as confirmed."
        elif state in {"received", "queued", "running"}:
            outcome = "pending"
            message = "Received the update; application is still pending."
        elif state == "retryable_failure":
            outcome = "uncertain"
            message = "The final outcome is uncertain; check this receipt before retrying."
        else:
            outcome = "rejected"
            message = "The update was not applied."
        return {
            "outcome": outcome,
            "acknowledgment": message,
            "receipt_id": receipt.get("receipt_id"),
            "receipt_state": state,
            "canonical_version": receipt.get("canonical_version"),
            "affected_ids": receipt.get("affected_ids", []),
            "review_refs": receipt.get("review_refs", []),
            "delivery_disposition": "duplicate" if receipt.get("duplicate") else "new",
            "status_lookup": {
                "operation": "get_update_status",
                "command_id": receipt.get("command_id"),
            },
            "lifecycle_affordances": ["correct_claim", "undo_update", "forget_claim"],
            "provider_actions": [],
        }


__all__ = [
    "CAPTURE_SCOPE",
    "CAPTURE_SCOPE_VERSION",
    "CollegeAssessmentRequest",
    "CollegeCaptureAdapter",
    "CollegeCaptureError",
    "CollegeCaptureRequest",
    "CollegeLifecycleRequest",
    "CollegeQuestionDispositionRequest",
    "TrustedCollegeCaptureContext",
]
