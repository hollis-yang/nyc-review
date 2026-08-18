from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.domain.models import AgentRunRequest, AgentRunResponse, RunStatus

router = APIRouter()


def get_workflow(request: Request):
    return request.app.state.agent_runtime.workflow


WorkflowDependency = Annotated[Any, Depends(get_workflow)]


@router.post("/v1/agent/runs/preview", response_model=AgentRunResponse)
async def preview_run(payload: AgentRunRequest, request: Request, workflow: WorkflowDependency):
    if payload.mode.value != "multi":
        raise HTTPException(status_code=400, detail="The first scaffold currently supports multi mode only.")
    state = await workflow.ainvoke({"request": payload, "events": []})
    runtime = request.app.state.agent_runtime
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
        },
    )
