from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.domain.models import (
    AgentRunCreated,
    AgentRunCreateRequest,
    AgentRunRequest,
    AgentRunResponse,
    AgentRunSnapshot,
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
    return await manager.create(payload, authorization or "")


@router.get("/v1/agent/runs/{run_id}", response_model=AgentRunSnapshot)
async def get_run(run_id: str, request: Request):
    snapshot = await request.app.state.agent_runtime.run_manager.get(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return snapshot


@router.get("/v1/agent/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
):
    manager = request.app.state.agent_runtime.run_manager
    if await manager.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return StreamingResponse(
        manager.event_stream(run_id, after),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/v1/agent/runs/{run_id}/cancel", response_model=AgentRunSnapshot)
async def cancel_run(run_id: str, request: Request):
    snapshot = await request.app.state.agent_runtime.run_manager.cancel(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return snapshot
