"""Retained-only parent reads and explicit assessments for the synthetic owner.

No provider refresh, calendar baseline, client context or interaction cursor.
The immutable retry envelope stores fingerprints only, never context content.
"""
from datetime import datetime, timezone
import hashlib
import json
import uuid
from fastapi.responses import JSONResponse


def retained_today(store):
    from .college_briefing import CollegeBriefingService, CollegeBriefRequest
    from .college_reads import CollegeReadService, TrustedCollegeContext
    now = datetime.now(timezone.utc)
    auth = TrustedCollegeContext(actor_id=store.config.actor_id,
                                 workspace_id=store.config.workspace_id, allow_cross_course=True)
    brief = CollegeBriefingService(read_service_factory=lambda: CollegeReadService(store.config.database)).build(
        auth, CollegeBriefRequest(evaluated_at=now, timezone_name="UTC"))
    return {"now":now.isoformat(), "now_display":"Synthetic local environment",
            "today_remaining_events":[], "current_free_block":None, "must_do":None,
            "personal_reality":None, "reality_attention":[], "life_areas":[],
            "recommendation":{"title":"Synthetic College review", "detail":"Retained College state only. Calendar, tasks, email and other providers are unavailable.",
                              "evidence":[{"signal":"college_attention_projection", "value":brief.model_dump(mode="json"), "score_delta":0, "explanation":"Authorized retained College read"}]},
            "errors":["Provider coverage is unavailable; empty provider sections are not evidence of a clear day."]}


def retained_assessment(store, payload):
    from .college_capture_api import _request
    from .college_capture import CollegeCaptureAdapter, CollegeCaptureError
    from .college_domain import CollegeDomainService, CollegeScope, CollegeCommandIdentity, CollegeDomainError
    from .conversation_context import SharedConversationContextService, ContextScope
    allowed = {"operation", "command_id", "idempotency_key", "authorized_scope", "horizon", "timezone", "valid_through"}
    if set(payload) - allowed:
        return JSONResponse({"code":"untrusted_assessment_input"},status_code=400)
    try:
        request = _request(payload)
        scope = CollegeScope(store.config.actor_id, store.config.workspace_id)
        context_scope = ContextScope(scope.actor_id, scope.workspace_id)
        service, context = CollegeDomainService(), SharedConversationContextService()
        # One fixed authorized retained scope. Provider/calendar inputs stay unknown.
        if request.authorized_scope != {"kind":"cross_course", "subject_ids":[]}:
            return JSONResponse({"code":"scope_not_enabled"},status_code=403)
        request_hash = hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
        with store.connection(readonly=True) as c:
            prior = c.execute("SELECT * FROM runtime_assessment_inputs WHERE command_id=? OR idempotency_key=?", (request.command_id,request.idempotency_key)).fetchone()
            receipt = c.execute("SELECT * FROM college_receipts WHERE actor_id=? AND workspace_id=? AND (command_id=? OR idempotency_key=?)", (scope.actor_id,scope.workspace_id,request.command_id,request.idempotency_key)).fetchone()
        if prior and (prior["command_id"] != request.command_id or prior["idempotency_key"] != request.idempotency_key or prior["request_hash"] != request_hash):
            return JSONResponse({"code":"idempotency_payload_conflict"},status_code=409)
        if receipt and not prior:
            return JSONResponse({"code":"command_identity_conflict"},status_code=409)
        if receipt and receipt["state"] not in {"received", "retryable_failure"}:
            # The original acknowledged result remains recoverable after privacy changes.
            result = service.get_receipt(scope, command_id=request.command_id)
            result["duplicate"] = True
            return JSONResponse(CollegeCaptureAdapter._acknowledgment(result))
        if prior and prior["context_generation"] != context.get_assessment_generation(context_scope):
            return JSONResponse({"code":"assessment_inputs_changed_new_command_required"},status_code=409)
        class RetainedCollegeContext:
            def retrieve_context(self, bound_scope, **kwargs):
                return [item for item in context.retrieve_context(bound_scope, **kwargs)
                        if item.get("scope") == "college-operational" and item.get("scope_version") == "1"
                        and item.get("status") == "active" and not item.get("sensitive")
                        and (not item.get("requires_raw_context") or item.get("raw_source_available"))]

            def get_assessment_generation(self, bound_scope):
                return context.get_assessment_generation(bound_scope)

        snapshot = service.context_snapshot_from_sid151(scope,RetainedCollegeContext(),context_scope,
                    snapshot_id=prior["snapshot_id"] if prior else str(uuid.uuid4()))
        if prior and (prior["snapshot_version"] != snapshot["version"] or prior["context_generation"] != snapshot["assessment_generation"]):
            return JSONResponse({"code":"assessment_inputs_changed_new_command_required"},status_code=409)
        if not prior:
            # Validates horizon, expiry and scope before persisting an immutable identity.
            from zoneinfo import ZoneInfo
            ZoneInfo(request.timezone_name)
            start = datetime.fromisoformat(request.horizon["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(request.horizon["end"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (not request.command_id or not request.idempotency_key or len(request.command_id) > 128
                or len(request.idempotency_key) > 128 or not start.tzinfo or not end.tzinfo
                or not request.valid_through.tzinfo or start >= end
                or not now < request.valid_through <= end or (end-start).total_seconds() > 604800):
                return JSONResponse({"code":"invalid_assessment_window"},status_code=400)
            with store.connection() as c:
                c.execute("INSERT INTO runtime_assessment_inputs VALUES (?,?,?,?,?,?)", (request.command_id,request.idempotency_key,request_hash,snapshot["snapshot_id"],snapshot["version"],snapshot["assessment_generation"]))
        result = service.request_assessment(scope,CollegeCommandIdentity(request.command_id,request.idempotency_key),
                    authorized_scope=request.authorized_scope,horizon=request.horizon,timezone_name=request.timezone_name,
                    valid_through=request.valid_through,baseline=None,window=None,context_snapshot=snapshot)
        return JSONResponse(CollegeCaptureAdapter._acknowledgment(result))
    except (CollegeCaptureError, CollegeDomainError) as exc:
        return JSONResponse({"code":exc.code},status_code=400)
