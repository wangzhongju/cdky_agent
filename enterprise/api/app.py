from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from enterprise.api.schemas import (
    ApprovalDecisionRequest,
    SessionCreateRequest,
    SessionMessageRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from enterprise.governance.audit import AuditService
from enterprise.governance.health import HealthService
from enterprise.governance.metrics import MetricsService
from enterprise.governance.prometheus_metrics import (
    api_request_latency_ms,
    api_requests_total,
    inflight_requests,
    metrics_payload,
)
from enterprise.governance.rate_limit import RateLimitService
from enterprise.governance.tracing import current_trace_id, setup_tracer, trace_context_middleware
from enterprise.session.service import SessionService
from enterprise.storage.init_db import init_storage
from enterprise.engine.stream_events import event_to_dict
from utils.config_handler import enterprise_conf


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_storage()
    setup_tracer()
    app.state.session_service = SessionService()
    app.state.audit_service = AuditService()
    app.state.rate_limit_service = RateLimitService()
    app.state.metrics_service = MetricsService()
    app.state.health_service = HealthService()
    yield


app = FastAPI(title="Enterprise Agent API", version="3.0.0", lifespan=lifespan)
allowed_origins = enterprise_conf.get("web", {}).get(
    "allowed_origins",
    ["http://127.0.0.1:3000", "http://localhost:3000"],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(trace_context_middleware)


@app.middleware("http")
async def governance_middleware(request: Request, call_next):
    if request.url.path in {"/healthz", "/v1/metrics", "/metrics"}:
        return await call_next(request)

    actor = request.headers.get("x-api-key", "anonymous")
    trace_id = current_trace_id()
    start = time.time()

    rate_limit_service: RateLimitService = app.state.rate_limit_service
    metrics_service: MetricsService = app.state.metrics_service
    audit_service: AuditService = app.state.audit_service
    rate_limit_service.check(actor)
    metrics_service.incr("requests_total")
    inflight_requests.inc()

    try:
        response = await call_next(request)
        latency_ms = int((time.time() - start) * 1000)
        metrics_service.incr("requests_success")
        api_requests_total.labels(method=request.method, path=request.url.path, status="success").inc()
        api_request_latency_ms.labels(method=request.method, path=request.url.path).observe(latency_ms)
        audit_service.log(
            event_type="api_request",
            actor=actor,
            trace_id=trace_id,
            target=f"{request.method} {request.url.path}",
            payload={"query": dict(request.query_params)},
            status="SUCCESS",
            latency_ms=latency_ms,
        )
        return response
    except Exception as exc:
        latency_ms = int((time.time() - start) * 1000)
        metrics_service.incr("requests_failed")
        api_requests_total.labels(method=request.method, path=request.url.path, status="failed").inc()
        api_request_latency_ms.labels(method=request.method, path=request.url.path).observe(latency_ms)
        audit_service.log(
            event_type="api_request",
            actor=actor,
            trace_id=trace_id,
            target=f"{request.method} {request.url.path}",
            payload={"query": dict(request.query_params)},
            status="FAILED",
            error=str(exc),
            latency_ms=latency_ms,
        )
        raise
    finally:
        inflight_requests.dec()


@app.get("/healthz")
def healthz(deep: bool = False):
    if not deep:
        return {"status": "ok"}
    health_service: HealthService = app.state.health_service
    result = health_service.check()
    if result["status"] != "ok":
        raise HTTPException(status_code=503, detail=result)
    return result


@app.get("/v1/metrics")
def metrics_snapshot():
    metrics_service: MetricsService = app.state.metrics_service
    return metrics_service.get_snapshot()


@app.get("/metrics")
def prometheus_metrics():
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)


@app.post("/v2/sessions")
def create_session(req: SessionCreateRequest):
    session_service: SessionService = app.state.session_service
    return session_service.create_session(title=req.title, user_id=req.user_id, metadata=req.metadata)


@app.get("/v2/sessions")
def list_sessions(user_id: str | None = None):
    session_service: SessionService = app.state.session_service
    return session_service.list_sessions(user_id=user_id)


@app.get("/v2/sessions/{session_id}")
def get_session(session_id: str):
    session_service: SessionService = app.state.session_service
    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/v2/sessions/{session_id}/messages")
def get_session_messages(session_id: str):
    session_service: SessionService = app.state.session_service
    return session_service.get_messages(session_id)


@app.post("/v2/sessions/{session_id}/messages/stream")
async def stream_session_messages(session_id: str, req: SessionMessageRequest, request: Request):
    session_service: SessionService = app.state.session_service
    actor = request.headers.get("x-api-key", "anonymous")
    trace_id = req.trace_id or current_trace_id()

    async def event_stream():
        try:
            async for event in session_service.stream(
                session_id=session_id,
                prompt=req.message,
                resume=req.resume,
                trace_id=trace_id,
                actor=actor,
            ):
                yield f"data: {json.dumps(event_to_dict(event), ensure_ascii=False)}\n\n"
        except KeyError:
            yield 'data: {"type":"error","message":"session not found"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/v2/skills")
def list_skills():
    session_service: SessionService = app.state.session_service
    return session_service.list_skills()


@app.get("/v2/tools")
def list_tools():
    session_service: SessionService = app.state.session_service
    return session_service.list_tools()


@app.post("/v2/users")
def create_user(req: UserCreateRequest):
    session_service: SessionService = app.state.session_service
    try:
        return session_service.create_user(
            username=req.username,
            display_name=req.display_name,
            note=req.note,
            default_model=req.default_model,
            preferences=req.preferences,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/v2/users")
def list_users():
    session_service: SessionService = app.state.session_service
    return session_service.list_users()


@app.get("/v2/users/{user_id}")
def get_user(user_id: str):
    session_service: SessionService = app.state.session_service
    user = session_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@app.patch("/v2/users/{user_id}")
def update_user(user_id: str, req: UserUpdateRequest):
    session_service: SessionService = app.state.session_service
    user = session_service.update_user(
        user_id,
        display_name=req.display_name,
        note=req.note,
        default_model=req.default_model,
        preferences=req.preferences,
    )
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@app.get("/v2/approvals")
def list_approvals(status: str = "pending"):
    session_service: SessionService = app.state.session_service
    return session_service.list_approvals(status=status)


@app.post("/v2/approvals/{approval_id}/decision")
async def decide_approval(approval_id: str, req: ApprovalDecisionRequest):
    session_service: SessionService = app.state.session_service
    try:
        return await session_service.decide_approval(approval_id, approved=req.approved)
    except KeyError:
        raise HTTPException(status_code=404, detail="approval not found")
