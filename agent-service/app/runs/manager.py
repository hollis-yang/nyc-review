from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import uuid4

from app.domain.models import (
    AgentActionStatus,
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

STREAM_TERMINAL_STATUSES = {
    RunStatus.WAITING_CONFIRMATION,
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
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
        await self._store.create(run_id, request, self._owner_key(authorization))
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

    async def list_runs(self, authorization: str, limit: int = 10) -> list[AgentRunSnapshot]:
        if not authorization:
            return []
        return await self._store.list_runs(self._owner_key(authorization), limit)

    async def metrics(self) -> dict:
        return await self._store.metrics()

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

    async def approve_action(
        self,
        run_id: str,
        action_id: str,
        authorization: str,
    ) -> AgentRunSnapshot | None:
        snapshot = await self._store.get(run_id)
        if snapshot is None:
            return None
        action = await self._store.get_action(run_id, action_id)
        if action is None:
            raise KeyError(action_id)
        if action.status is AgentActionStatus.COMPLETED:
            return snapshot
        if action.status is AgentActionStatus.REJECTED:
            raise ValueError("A rejected action cannot be approved.")
        if action.status in {AgentActionStatus.APPROVED, AgentActionStatus.EXECUTING}:
            raise ValueError("This action is already being executed.")

        await self._store.update_action(run_id, action_id, AgentActionStatus.APPROVED)
        await self._store.append_event(
            run_id,
            event="action.approved",
            agent="Action Executor",
            status="completed",
            message="User approved a proposed action.",
            details={"actionId": action_id, "actionType": action.action_type.value},
        )
        await self._store.set_status(run_id, RunStatus.TOOL_RUNNING)
        await self._store.update_action(run_id, action_id, AgentActionStatus.EXECUTING)
        await self._store.append_event(
            run_id,
            event="action.started",
            agent="Action Executor",
            status="running",
            message="Executing the approved action through Spring.",
            details={"actionId": action_id, "actionType": action.action_type.value},
        )
        try:
            result = await self._runtime.action_service.execute(run_id, action, authorization)
            await self._store.update_action(
                run_id,
                action_id,
                AgentActionStatus.COMPLETED,
                result=result,
            )
            await self._store.append_event(
                run_id,
                event="action.completed",
                agent="Action Executor",
                status="completed",
                message="Approved action completed and was recorded in the audit log.",
                details={"actionId": action_id, "actionType": action.action_type.value},
            )
        except Exception as exc:  # noqa: BLE001 - action boundary persists controlled failures
            message = str(exc) or exc.__class__.__name__
            await self._store.update_action(
                run_id,
                action_id,
                AgentActionStatus.FAILED,
                error=message,
            )
            await self._store.append_event(
                run_id,
                event="action.failed",
                agent="Action Executor",
                status="failed",
                message=message,
                details={"actionId": action_id, "actionType": action.action_type.value},
            )
        await self._finalize_action_state(run_id)
        return await self._store.get(run_id)

    async def reject_action(self, run_id: str, action_id: str) -> AgentRunSnapshot | None:
        snapshot = await self._store.get(run_id)
        if snapshot is None:
            return None
        action = await self._store.get_action(run_id, action_id)
        if action is None:
            raise KeyError(action_id)
        if action.status is AgentActionStatus.COMPLETED:
            raise ValueError("A completed action cannot be rejected.")
        if action.status is AgentActionStatus.EXECUTING:
            raise ValueError("An executing action cannot be rejected.")
        if action.status is not AgentActionStatus.REJECTED:
            await self._store.update_action(run_id, action_id, AgentActionStatus.REJECTED)
            await self._store.append_event(
                run_id,
                event="action.rejected",
                agent="Action Executor",
                status="rejected",
                message="User rejected a proposed action. No write was performed.",
                details={"actionId": action_id, "actionType": action.action_type.value},
            )
        await self._finalize_action_state(run_id)
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
            if snapshot.status in STREAM_TERMINAL_STATUSES:
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
            personalization = await self._runtime.action_service.preferences(authorization)
            preference_updates = {}
            if extraction.constraints.category is None and personalization.get("category"):
                preference_updates["category"] = personalization["category"]
            if extraction.constraints.neighborhood is None and personalization.get("neighborhood"):
                preference_updates["neighborhood"] = personalization["neighborhood"]
            if preference_updates:
                extraction = replace(
                    extraction,
                    constraints=extraction.constraints.model_copy(update=preference_updates),
                )
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
                    "personalization": personalization,
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

            result = self._response(
                create_request.mode,
                accumulated,
                extraction,
                personalization,
            )
            actions = await self._runtime.action_service.propose(run_id, result, authorization)
            await self._store.add_actions(run_id, actions)
            if actions:
                await self._store.set_status(
                    run_id,
                    RunStatus.WAITING_CONFIRMATION,
                    result=result,
                )
                await self._store.append_event(
                    run_id,
                    event="run.waiting_confirmation",
                    agent="Action Planner",
                    status="waiting_confirmation",
                    message="Recommendation is ready. Optional actions require your approval.",
                    details={"valid": result.verification.valid, "actionCount": len(actions)},
                )
            else:
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

    async def _finalize_action_state(self, run_id: str) -> None:
        snapshot = await self._store.get(run_id)
        if snapshot is None:
            return
        unresolved = any(
            action.status
            in {
                AgentActionStatus.PROPOSED,
                AgentActionStatus.APPROVED,
                AgentActionStatus.EXECUTING,
            }
            for action in snapshot.actions
        )
        next_status = RunStatus.WAITING_CONFIRMATION if unresolved else RunStatus.COMPLETED
        await self._store.set_status(run_id, next_status)
        if not unresolved:
            await self._store.append_event(
                run_id,
                event="run.completed",
                status="completed",
                message="All proposed actions have been resolved.",
                details={
                    "completedActions": sum(
                        action.status is AgentActionStatus.COMPLETED for action in snapshot.actions
                    ),
                    "rejectedActions": sum(
                        action.status is AgentActionStatus.REJECTED for action in snapshot.actions
                    ),
                    "failedActions": sum(
                        action.status is AgentActionStatus.FAILED for action in snapshot.actions
                    ),
                },
            )

    @staticmethod
    def _owner_key(authorization: str) -> str:
        if not authorization:
            return ""
        return hashlib.sha256(authorization.encode("utf-8")).hexdigest()

    def _response(
        self,
        mode: AgentMode,
        state: dict,
        extraction,
        personalization: dict | None = None,
    ) -> AgentRunResponse:
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
                "personalization": personalization or {},
            },
        )
