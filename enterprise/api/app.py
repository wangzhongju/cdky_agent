from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from enterprise.a2a.runtime import A2ARuntime
from enterprise.api.schemas import (
    ApprovalDecisionRequest,
    ChatResumeRequest,
    ChatStreamRequest,
    SkillPatchRequest,
    TaskCreateRequest,
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
from enterprise.governance.tracing import (
    current_trace_id,
    setup_tracer,
    trace_context_middleware,
)
from enterprise.orchestrator.service import OrchestratorService
from enterprise.storage.init_db import init_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_storage()
    setup_tracer()

    orchestrator_service = OrchestratorService()
    a2a_runtime = A2ARuntime(orchestrator_service)
    a2a_runtime.start()

    app.state.orchestrator_service = orchestrator_service
    app.state.a2a_runtime = a2a_runtime
    app.state.audit_service = AuditService()
    app.state.rate_limit_service = RateLimitService()
    app.state.metrics_service = MetricsService()
    app.state.health_service = HealthService()

    yield
    a2a_runtime.stop()


app = FastAPI(title="Enterprise Agent API", version="2.0.0", lifespan=lifespan)
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
        response.headers["x-trace-id"] = trace_id
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


@app.post("/v1/chat/stream")
async def chat_stream(req: ChatStreamRequest, request: Request):
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    actor = request.headers.get("x-api-key", "anonymous")
    generator = orchestrator_service.stream_chat(
        message=req.message,
        session_id=req.session_id,
        trace_id=req.trace_id or current_trace_id(),
        actor=actor,
        permission_mode=req.permission_mode,
    )
    response = StreamingResponse(generator, media_type="application/x-ndjson")
    response.headers["x-trace-id"] = req.trace_id or current_trace_id()
    return response


@app.post("/v1/chat/resume")
async def chat_resume(req: ChatResumeRequest, request: Request):
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    actor = request.headers.get("x-api-key", "anonymous")
    generator = orchestrator_service.resume_chat(
        session_id=req.session_id,
        trace_id=req.trace_id or current_trace_id(),
        actor=actor,
    )
    response = StreamingResponse(generator, media_type="application/x-ndjson")
    response.headers["x-trace-id"] = req.trace_id or current_trace_id()
    return response


@app.post("/v1/approvals/{approval_id}")
def decide_approval(approval_id: str, req: ApprovalDecisionRequest):
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    result = orchestrator_service.decide_approval(approval_id, req.decision)
    if not result:
        raise HTTPException(status_code=404, detail="approval not found")
    return result


@app.post("/v1/tasks")
def create_task(req: TaskCreateRequest):
    a2a_runtime: A2ARuntime = app.state.a2a_runtime
    return a2a_runtime.submit_task(
        goal=req.goal,
        constraints=req.constraints,
        context_ref=req.context_ref,
        input_data=req.input,
        trace_id=req.trace_id or current_trace_id(),
        permission_mode=req.permission_mode or "default",
    )


@app.get("/v1/tasks/{task_id}")
def get_task(task_id: str):
    a2a_runtime: A2ARuntime = app.state.a2a_runtime
    task = a2a_runtime.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@app.get("/v1/skills")
def list_skills():
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    return orchestrator_service.list_skills()


@app.patch("/v1/skills/{skill_id}")
def patch_skill(skill_id: str, req: SkillPatchRequest):
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    ok = orchestrator_service.set_skill_enabled(skill_id, req.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="skill not found")
    return {"skill_id": skill_id, "enabled": req.enabled}


@app.get("/v1/capabilities")
def list_capabilities():
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    return orchestrator_service.list_capabilities()


@app.get("/v1/sessions")
def list_sessions(limit: int = 20):
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    return orchestrator_service.list_sessions(limit=limit)


@app.get("/v1/sessions/{session_id}")
def get_session(session_id: str):
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    session = orchestrator_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/v1/sessions/{session_id}/messages")
def get_session_messages(session_id: str):
    orchestrator_service: OrchestratorService = app.state.orchestrator_service
    session = orchestrator_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return JSONResponse(content=orchestrator_service.list_session_messages(session_id))
