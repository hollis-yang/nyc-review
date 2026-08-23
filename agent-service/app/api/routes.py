import hashlib
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.domain.models import (
    AgentRunCreated,
    AgentRunCreateRequest,
    AgentRunRequest,
    AgentRunResponse,
    AgentRunSnapshot,
    AgentTraceSpan,
    RunStatus,
)

router = APIRouter()


@router.post("/v1/agent/runs/preview", response_model=AgentRunResponse)
async def preview_run(payload: AgentRunRequest, request: Request):
    runtime = request.app.state.agent_runtime
    selected_workflow = runtime.workflows[payload.mode]
    state = await selected_workflow.ainvoke({"request": payload, "events": []})
    return AgentRunResponse(
        mode=payload.mode,
        status=RunStatus.COMPLETED,
        candidates=state["candidates"],
        evidence=state["evidence"],
        itinerary=state["itinerary"],
        verification=state["verification"],
        summary=state["summary"],
        metadata={
            "events": state["events"],
            "adapter": runtime.adapter_name,
            "rag": runtime.rag_name,
            "indexedDocuments": runtime.indexed_documents,
            "dataVersion": runtime.data_version,
            "datasetSha256": runtime.dataset_sha256,
            "sourceCounts": runtime.source_counts,
            "ragIndexStats": runtime.rag_index_stats,
        },
    )


@router.post(
    "/v1/agent/runs",
    response_model=AgentRunCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(
    payload: AgentRunCreateRequest,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    manager = request.app.state.agent_runtime.run_manager
    runtime = request.app.state.agent_runtime
    limiter_key = authorization or (request.client.host if request.client else "anonymous")
    limiter_key = hashlib.sha256(limiter_key.encode("utf-8")).hexdigest()
    if not runtime.rate_limiter.allow(limiter_key):
        raise HTTPException(status_code=429, detail="Agent run rate limit exceeded.")
    try:
        return await manager.create(payload, authorization or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/v1/agent/runs", response_model=list[AgentRunSnapshot])
async def list_runs(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    return await request.app.state.agent_runtime.run_manager.list_runs(
        authorization or "",
        limit,
    )


@router.get("/v1/agent/metrics")
async def agent_metrics(
    request: Request,
    metrics_token: Annotated[str | None, Header(alias="x-metrics-token")] = None,
):
    expected = request.app.state.agent_runtime.metrics_token
    if expected and metrics_token != expected:
        raise HTTPException(status_code=401, detail="A valid metrics token is required.")
    return await request.app.state.agent_runtime.run_manager.metrics()


@router.get("/v1/agent/runs/{run_id}", response_model=AgentRunSnapshot)
async def get_run(
    run_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    snapshot = await request.app.state.agent_runtime.run_manager.get_owned(
        run_id, authorization or ""
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return snapshot


@router.get("/v1/agent/runs/{run_id}/trace", response_model=list[AgentTraceSpan])
async def get_run_trace(
    run_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    trace = await request.app.state.agent_runtime.run_manager.trace(
        run_id, authorization or ""
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return trace


@router.get("/v1/agent/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    after: Annotated[int, Query(ge=0)] = 0,
):
    manager = request.app.state.agent_runtime.run_manager
    if await manager.get_owned(run_id, authorization or "") is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return StreamingResponse(
        manager.event_stream(run_id, after, authorization or ""),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/v1/agent/runs/{run_id}/cancel", response_model=AgentRunSnapshot)
async def cancel_run(
    run_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    snapshot = await request.app.state.agent_runtime.run_manager.cancel(
        run_id, authorization or ""
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return snapshot


@router.post(
    "/v1/agent/runs/{run_id}/actions/{action_id}/approve",
    response_model=AgentRunSnapshot,
)
async def approve_action(
    run_id: str,
    action_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    try:
        snapshot = await request.app.state.agent_runtime.run_manager.approve_action(
            run_id,
            action_id,
            authorization or "",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent action not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return snapshot


@router.post(
    "/v1/agent/runs/{run_id}/actions/{action_id}/reject",
    response_model=AgentRunSnapshot,
)
async def reject_action(
    run_id: str,
    action_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    try:
        snapshot = await request.app.state.agent_runtime.run_manager.reject_action(
            run_id, action_id, authorization or ""
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent action not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return snapshot
