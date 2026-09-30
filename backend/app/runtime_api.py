"""Synthetic HTTP composition. No provider, legacy app, MCP or OAuth exposure.

Use the explicit CLI factory. Never import this through app.main. Existing
College handlers receive a server-only credential after session authorization;
no caller credential is forwarded and no global principal is mutated.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import secrets
import threading
from http.cookies import SimpleCookie
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .runtime_store import RuntimeStore, RuntimeRefusal
from .runtime_auth import OwnerAuth
from .runtime_auth import digest

LOG = logging.getLogger("pcos.runtime")
COOKIE = "pcos_session"
MAX_BODY = 131072


def create_runtime_app(config, *, backup=None):
    import os
    # Must precede imports of config/storage: synthetic startup never loads .env.
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise RuntimeRefusal("dotenv_must_be_disabled_before_import")
    os.environ["PCOS_SYNTHETIC_RUNTIME"] = "1"
    store = RuntimeStore(config)
    auth = OwnerAuth(store)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite-owner")
    pending = threading.BoundedSemaphore(16)
    server_key = secrets.token_urlsafe(32)
    rates = {}

    async def owned(function):
        if not pending.acquire(blocking=False):
            raise RuntimeRefusal("write_queue_full")
        future = asyncio.get_running_loop().run_in_executor(executor, function)
        # Cancellation does not release admission before the accepted work finishes.
        future.add_done_callback(lambda _: pending.release())
        return await asyncio.shield(future)

    @asynccontextmanager
    async def lifespan(app):
        task = None
        try:
            await owned(store.start)
            # Lazy construction avoids any schema initialization at import.
            app.state.surface = build_surface(store, server_key)
            task = asyncio.create_task(maintain())
            yield
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await owned(store.close)
            executor.shutdown(wait=True)

    async def maintain():
        last_backup = 0
        while True:
            await asyncio.sleep(900)
            try:
                await owned(store.maintenance)
            except Exception:
                store.accepting = False
                LOG.warning("retention_maintenance_failed")
                return
            if backup is not None:
                vault, recipient = backup
                try:
                    await owned(lambda: vault.sync(store))
                    import time
                    if time.time()-last_backup >= 86400:
                        await owned(lambda: vault.backup(store, recipient))
                        last_backup = time.time()
                except Exception:
                    LOG.warning("backup_maintenance_pending")

    app = FastAPI(title="PCOS synthetic runtime", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.post("/runtime/login")
    async def login(request: Request):
        payload = await request.json()
        if set(payload) != {"password"} or not isinstance(payload["password"], str) or len(payload["password"]) > 1024:
            return JSONResponse({"code":"invalid_login"}, status_code=400)
        token, csrf = await owned(lambda: auth.login(payload["password"]))
        response = JSONResponse({"csrf":csrf, **session_binding(token)})
        response.set_cookie(COOKIE, token, httponly=True, secure=config.origin.startswith("https:"), samesite="strict", max_age=604800, path="/")
        return response

    def session_binding(token):
        row = auth.verify(token)
        return {"environment_id":config.environment_id, "actor_id":config.actor_id,
                "workspace_id":config.workspace_id, "auth_generation":row["auth_generation"]}

    @app.get("/runtime/session")
    async def session(request: Request):
        # Read-only validation; no renewal and no replacement CSRF credential.
        return session_binding(request.cookies.get(COOKIE))

    @app.get("/today")
    async def today():
        from .runtime_integration import retained_today
        return retained_today(store)

    @app.get("/activity")
    @app.get("/morning-state")
    async def unsupported_parent():
        return JSONResponse({"code":"provider_parent_disabled", "detail":"This parent view requires providers; only retained synthetic College state is available."},status_code=503)

    @app.post("/runtime/logout")
    async def logout(request: Request):
        await owned(lambda: auth.logout(request.cookies[COOKIE]))
        response = JSONResponse({"status":"logged_out", "clear_local_journal":True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.post("/runtime/renew")
    async def renew(request: Request):
        await owned(lambda: auth.renew(request.cookies[COOKIE], request.headers.get("x-csrf-token", "")))
        return {"status":"renewed"}

    @app.get("/runtime/diagnostics")
    async def diagnostics():
        return store.diagnostics()

    @app.get("/health/live")
    async def live():
        return {"status":"ok"}

    @app.get("/health/ready")
    async def ready():
        try:
            store.verify()
            ok = store.accepting
        except Exception:
            ok = False
        return JSONResponse({"status":"ok" if ok else "unavailable"}, status_code=200 if ok else 503)

    @app.api_route("/college/{rest:path}", methods=["GET","POST"])
    async def college(request: Request, rest: str):
        # Forward only to the explicit College route allowlist, with the same graph.
        path = request.url.path
        allowed = {("GET","/college/state"), ("GET","/college/update-status"),
                   ("POST","/college/update"), ("GET","/college/surface/consent"),
                   ("POST","/college/surface/consent"), ("GET","/college/surface/context"),
                   ("POST","/college/surface/context"), ("GET","/college/surface/bindings"),
                   ("GET","/college/surface/update-status")}
        if (request.method,path) not in allowed:
            return JSONResponse({"code":"route_not_enabled"},status_code=404)
        body = await request.body()
        if request.method == "POST":
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return JSONResponse({"code":"invalid_request"},status_code=400)
            if path == "/college/update" and payload.get("source_surface") == "chatgpt":
                return JSONResponse({"code":"chatgpt_transport_not_enabled"},status_code=403)
            if path == "/college/update" and payload.get("operation") == "request_assessment":
                from .runtime_integration import retained_assessment
                def assess():
                    with store.write_gate():
                        auth.verify(request.cookies.get(COOKIE), csrf=request.headers.get("x-csrf-token", ""))
                        return retained_assessment(store, payload)
                return await owned(assess)
            if path == "/college/update" and payload.get("operation", "capture") == "capture" and store.diagnostics()["capture_disabled_for_recovery"]:
                return JSONResponse({"code":"empty_recovery_capture_disabled"},status_code=403)
            if path == "/college/surface/consent" and payload.get("operation") == "grant":
                if store.diagnostics()["capture_disabled_for_recovery"]:
                    return JSONResponse({"code":"empty_recovery_capture_disabled"},status_code=403)
        async def dispatch():
            scope = dict(request.scope)
            scope["headers"] = [(b"authorization",f"Bearer {server_key}".encode()), (b"content-type",b"application/json")]
            sent = False
            messages = []
            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type":"http.request","body":body,"more_body":False}
                return {"type":"http.disconnect"}
            async def send(message):
                messages.append(message)
            await app.state.surface(scope,receive,send)
            status = next(m["status"] for m in messages if m["type"] == "http.response.start")
            content = b"".join(m.get("body",b"") for m in messages if m["type"] == "http.response.body")
            result = json.loads(content)
            if path == "/college/surface/consent" and request.method == "GET" and store.diagnostics()["capture_disabled_for_recovery"]:
                result["active"] = False
                result["runtime_capture_blocked"] = "recovery_reenrollment_required"
            if request.method == "POST" and result.get("receipt_state") == "retryable_failure":
                store.accepting = False
            return JSONResponse(result,status_code=status)
        if request.method == "POST":
            def mutate():
                with store.write_gate():
                    # Gate covers authentication and consent check through receipt commit.
                    auth.verify(request.cookies.get(COOKIE), csrf=request.headers.get("x-csrf-token", ""))
                    return asyncio.run(dispatch())
            return await owned(mutate)
        return await dispatch()

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        import time
        began = time.monotonic()
        response = None
        try:
            if request.client and request.client.host not in {"127.0.0.1","::1","testclient"}:
                raise RuntimeRefusal("direct_network_denied")
            from urllib.parse import urlsplit
            if request.headers.get("host") not in {urlsplit(config.origin).netloc, "127.0.0.1:8017"}:
                raise RuntimeRefusal("host_denied")
            if request.headers.get("origin") not in {None,config.origin}:
                raise RuntimeRefusal("origin_denied")
            if request.method not in {"GET","POST"}:
                raise RuntimeRefusal("method_denied")
            if request.method == "POST":
                if request.headers.get("origin") != config.origin:
                    raise RuntimeRefusal("origin_required")
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise RuntimeRefusal("body_too_large")
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            public = request.url.path in {"/runtime/login","/health/live","/health/ready"}
            if not public:
                auth.verify(request.cookies.get(COOKIE), csrf=request.headers.get("x-csrf-token", "") if request.method == "POST" else None)
                import time
                rate_key = (digest(request.cookies[COOKIE]), request.method)
                now = time.monotonic()
                for stale in [key for key, value in rates.items() if now-value[0] >= 60]:
                    del rates[stale]
                start, count = rates.get(rate_key, (now, 0))
                if now-start >= 60:
                    start, count = now, 0
                if count >= (30 if request.method == "POST" else 120):
                    raise RuntimeRefusal("request_rate_limited")
                rates[rate_key] = (start, count+1)
            response = await call_next(request)
        except RuntimeRefusal as exc:
            code = str(exc)
            status = 503 if code.startswith(("runtime_", "durable_", "database_")) else 429 if code in {"write_queue_full","login_rate_limited","request_rate_limited","session_limit_reached"} else 413 if code == "body_too_large" else 401 if code.startswith(("authentication","session")) else 403
            response = JSONResponse({"code":code},status_code=status)
            if status == 429:
                response.headers["Retry-After"] = "60"
        except (ValueError,TypeError,KeyError):
            response = JSONResponse({"code":"invalid_request"},status_code=400)
        except Exception:
            store.accepting = False
            response = JSONResponse({"code":"runtime_unavailable"},status_code=503)
        response.headers["Cache-Control"] = "private, no-store"
        # No paths/queries, content, credentials, or exception text in logs.
        duration = time.monotonic()-began
        bucket = "under_1s" if duration < 1 else "under_5s" if duration < 5 else "over_5s"
        LOG.info("request_completed id=%s status=%d duration=%s",secrets.token_hex(8),response.status_code,bucket)
        return response
    return app


def build_surface(store, server_key):
    from .college_capture_api import CollegeCaptureAuthenticator, create_college_capture_app
    from .college_read_api import CollegeReadAuthenticator
    from .college_surface_api import create_college_surface_app
    from .college_reads import CollegeReadService
    from .college_capture import CollegeCaptureAdapter
    from .conversation_context import SharedConversationContextService
    from .college_domain import CollegeDomainService
    config = store.config
    reader_auth = CollegeReadAuthenticator(api_key=server_key, actor_id=config.actor_id, workspace_id=config.workspace_id, allow_cross_course=True)
    writer_auth = CollegeCaptureAuthenticator(api_key=server_key, actor_id=config.actor_id, workspace_id=config.workspace_id, allow_cross_course=True)
    context = SharedConversationContextService()
    domain = CollegeDomainService()
    adapter = CollegeCaptureAdapter(context_service=context, college_service=domain)
    return create_college_surface_app(read_auth=reader_auth,capture_auth=writer_auth,
        read_service=CollegeReadService(config.database),context_service=context,
        capture_app=create_college_capture_app(adapter=adapter,authenticator=writer_auth))
