from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from app.domain.models import (
    AgentMode,
    AgentRunCreated,
    AgentRunCreateRequest,
    AgentRunRequest,
    AgentRunResponse,
    AgentRunSnapshot,
    RunStatus,
)
from app.model_gateway import ModelGateway
from app.request_context import request_authorization
from app.runs.store import SQLiteRunStore

NODE_PRESENTATION = {
    "supervisor_plan": ("Supervisor", "Interpreted constraints and delegated the plan."),
    "discovery": ("Discovery", "Found candidates through the read-only shop tool."),
    "evidence": ("Evidence", "Retrieved first-party RAG evidence and citations."),
    "itinerary": ("Itinerary", "Calculated distance and budget estimates."),
    "single_agent": ("Single Agent", "Completed discovery, evidence, and itinerary tools."),
    "verifier": ("Verifier", "Checked candidate IDs, citations, and constraints."),
    "supervisor_finalize": ("Supervisor", "Prepared the verified response."),
}


class AgentRunManager:
    def __init__(self, runtime, store: SQLiteRunStore, model_gateway: ModelGateway):
        self._runtime = runtime
        self._store = store
        self._model_gateway = model_gateway
        self._tasks: dict[str, asyncio.Task] = {}

    async def create(
        self,
        request: AgentRunCreateRequest,
        authorization: str = "",
    ) -> AgentRunCreated:
        run_id = str(uuid4())
        await self._store.create(run_id, request)
        await self._store.append_event(
            run_id,
            event="run.created",
            status="completed",
            message="Run created from a natural-language request.",
        )
        task = asyncio.create_task(self._execute(run_id, request, authorization))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
        return AgentRunCreated(
            run_id=run_id,
            status=RunStatus.CREATED,
            stream_url=f"/v1/agent/runs/{run_id}/events",
        )

    async def get(self, run_id: str) -> AgentRunSnapshot | None:
        return await self._store.get(run_id)

    async def cancel(self, run_id: str) -> AgentRunSnapshot | None:
        snapshot = await self._store.get(run_id)
        if snapshot is None:
            return None
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        if snapshot.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            await self._store.set_status(run_id, RunStatus.CANCELLED)
            await self._store.append_event(
                run_id,
                event="run.cancelled",
                status="cancelled",
                message="Run cancelled by the user.",
            )
        return await self._store.get(run_id)

    async def event_stream(self, run_id: str, after: int = 0) -> AsyncIterator[str]:
        last_sequence = max(0, after)
        while True:
            snapshot = await self._store.get(run_id)
            if snapshot is None:
                return
            events = await self._store.events_after(run_id, last_sequence)
            for item in events:
                last_sequence = item.sequence
                yield (
                    f"id: {item.sequence}\n"
                    f"event: {item.event}\n"
                    f"data: {item.model_dump_json()}\n\n"
                )
            if snapshot.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                yield (
                    "event: stream.closed\n"
                    f"data: {{\"runId\":\"{run_id}\",\"status\":\"{snapshot.status.value}\"}}\n\n"
                )
                return
            await asyncio.sleep(0.15)

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._store.close()

    async def _execute(
        self,
        run_id: str,
        create_request: AgentRunCreateRequest,
        authorization: str,
    ) -> None:
        token = request_authorization.set(authorization)
        try:
            await self._store.set_status(run_id, RunStatus.PLANNING)
            await self._store.append_event(
                run_id,
                event="model.started",
                agent="Supervisor",
                status="running",
                message="Extracting structured constraints from natural language.",
            )
            extraction = await self._model_gateway.extract_constraints(create_request)
            await self._store.append_event(
                run_id,
                event="model.completed",
                agent="Supervisor",
                status="completed",
                message="Structured constraints are ready.",
                details={
                    "provider": extraction.provider,
                    "model": extraction.model,
                    "fallbackUsed": extraction.fallback_used,
                    "constraints": extraction.constraints.model_dump(mode="json"),
                },
            )
            await self._store.set_status(run_id, RunStatus.TOOL_RUNNING)
            workflow = self._runtime.workflows[create_request.mode]
            request = AgentRunRequest(mode=create_request.mode, constraints=extraction.constraints)
            accumulated: dict = {"request": request, "events": []}
            async for chunk in workflow.astream(
                {"request": request, "events": []},
                stream_mode="updates",
            ):
                for node_name, update in chunk.items():
                    if not update:
                        continue
                    for key, value in update.items():
                        if key == "events":
                            accumulated["events"].extend(value)
                        else:
                            accumulated[key] = value
                    agent, message = NODE_PRESENTATION.get(
                        node_name,
                        (node_name.replace("_", " ").title(), "Agent step completed."),
                    )
                    await self._store.append_event(
                        run_id,
                        event="agent.completed",
                        agent=agent,
                        status="completed",
                        message=message,
                        details={"node": node_name},
                    )

            result = self._response(create_request.mode, accumulated, extraction)
            await self._store.set_status(run_id, RunStatus.COMPLETED, result=result)
            await self._store.append_event(
                run_id,
                event="run.completed",
                status="completed",
                message="Verified recommendation is ready.",
                details={"valid": result.verification.valid},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - boundary converts failures into persisted run state
            message = str(exc) or exc.__class__.__name__
            await self._store.set_status(run_id, RunStatus.FAILED, error=message)
            await self._store.append_event(
                run_id,
                event="run.failed",
                status="failed",
                message=message,
            )
        finally:
            request_authorization.reset(token)

    def _response(self, mode: AgentMode, state: dict, extraction) -> AgentRunResponse:
        return AgentRunResponse(
            mode=mode,
            status=RunStatus.COMPLETED,
            candidates=state["candidates"],
            evidence=state["evidence"],
            itinerary=state["itinerary"],
            verification=state["verification"],
            summary=state["summary"],
            metadata={
                "events": state["events"],
                "adapter": self._runtime.adapter_name,
                "rag": self._runtime.rag_name,
                "indexedDocuments": self._runtime.indexed_documents,
                "dataVersion": self._runtime.data_version,
                "datasetSha256": self._runtime.dataset_sha256,
                "modelProvider": extraction.provider,
                "model": extraction.model,
                "promptVersion": extraction.prompt_version,
                "modelFallbackUsed": extraction.fallback_used,
                "constraints": extraction.constraints.model_dump(mode="json"),
            },
        )
