from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import (
    AgentActionStatus,
    AgentMode,
    AgentRunCreated,
    AgentRunCreateRequest,
    AgentRunRequest,
    AgentRunResponse,
    AgentRunSnapshot,
    AgentTraceSpan,
    RunStatus,
)
from app.model_gateway import ModelGateway
from app.request_context import request_authorization
from app.runs.store import SQLiteRunStore
from app.security import PromptGuard

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
    def __init__(
        self,
        runtime,
        store: SQLiteRunStore,
        model_gateway: ModelGateway,
        *,
        max_recovery_attempts: int = 2,
    ):
        self._runtime = runtime
        self._store = store
        self._model_gateway = model_gateway
        self._max_recovery_attempts = max_recovery_attempts
        self._tasks: dict[str, asyncio.Task] = {}

    async def create(
        self,
        request: AgentRunCreateRequest,
        authorization: str = "",
        owner_session: str = "",
    ) -> AgentRunCreated:
        PromptGuard.validate(request.query)
        run_id = str(uuid4())
        await self._store.create(
            run_id,
            request,
            self._creation_owner_key(authorization, owner_session),
        )
        await self._store.append_event(
            run_id,
            event="run.created",
            status="completed",
            message="Run created from a natural-language request.",
        )
        self._schedule(run_id, request, authorization)
        return AgentRunCreated(
            run_id=run_id,
            status=RunStatus.CREATED,
            stream_url=f"/v1/agent/runs/{run_id}/events",
        )

    async def recover(self) -> int:
        interrupted_actions = await self._store.recover_interrupted_actions()
        for run_id, action in interrupted_actions:
            await self._store.append_event(
                run_id,
                event="action.failed",
                agent="Action Executor",
                status="failed",
                message=action.error or "Action recovery requires another approval.",
                details={
                    "actionId": action.action_id,
                    "actionType": action.action_type.value,
                    "recovery": "service_restart",
                },
            )
        recovered = await self._store.recoverable_runs(self._max_recovery_attempts)
        for run_id, request in recovered:
            await self._store.append_event(
                run_id,
                event="run.recovered",
                agent="Supervisor",
                status="running",
                message="Resuming an interrupted read-only Agent run from durable state.",
            )
            self._schedule(run_id, request, "")
        return len(recovered) + len({run_id for run_id, _ in interrupted_actions})

    def _schedule(self, run_id: str, request: AgentRunCreateRequest, authorization: str) -> None:
        task = asyncio.create_task(self._execute(run_id, request, authorization))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))

    async def get(self, run_id: str) -> AgentRunSnapshot | None:
        return await self._store.get(run_id)

    async def get_owned(
        self,
        run_id: str,
        authorization: str,
        owner_session: str = "",
    ) -> AgentRunSnapshot | None:
        if not await self._owns_run(run_id, authorization, owner_session):
            return None
        return await self._store.get(run_id)

    async def trace(
        self,
        run_id: str,
        authorization: str,
        owner_session: str = "",
    ) -> list[AgentTraceSpan] | None:
        if not await self._owns_run(run_id, authorization, owner_session):
            return None
        return await self._store.spans(run_id)

    async def list_runs(self, authorization: str, limit: int = 10) -> list[AgentRunSnapshot]:
        if not authorization:
            return []
        return await self._store.list_runs(self._owner_key(authorization), limit)

    async def metrics(self) -> dict:
        return await self._store.metrics()

    async def cancel(
        self,
        run_id: str,
        authorization: str = "",
        owner_session: str = "",
    ) -> AgentRunSnapshot | None:
        snapshot = await self.get_owned(run_id, authorization, owner_session)
        if snapshot is None:
            return None
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        cancelled, current_status = await self._store.cancel_run(run_id)
        if not cancelled:
            if current_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                return await self._store.get(run_id)
            raise ValueError("An approved action is executing and cannot be cancelled.")
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
        owner_session: str = "",
    ) -> AgentRunSnapshot | None:
        if not authorization:
            raise PermissionError("Sign in before approving an Agent action.")
        snapshot = await self.get_owned(run_id, authorization, owner_session)
        if snapshot is None:
            return None
        if snapshot.status is RunStatus.CANCELLED:
            raise ValueError("A cancelled run cannot execute actions.")
        run_metadata = snapshot.result.metadata if snapshot.result is not None else {}
        run_data_version = run_metadata.get("dataVersion")
        run_dataset_sha256 = run_metadata.get("datasetSha256")
        if (
            run_data_version != self._runtime.data_version
            or run_dataset_sha256 != self._runtime.dataset_sha256
        ):
            raise ValueError(
                "This Agent run belongs to a different dataset version. "
                "Create a new recommendation before approving actions."
            )
        action = await self._store.get_action(run_id, action_id)
        if action is None:
            raise KeyError(action_id)
        if action.status is AgentActionStatus.COMPLETED:
            return snapshot
        if action.status is AgentActionStatus.REJECTED:
            raise ValueError("A rejected action cannot be approved.")
        if action.status in {AgentActionStatus.APPROVED, AgentActionStatus.EXECUTING}:
            raise ValueError("This action is already being executed.")

        claimed = await self._store.transition_action(
            run_id,
            action_id,
            {AgentActionStatus.PROPOSED, AgentActionStatus.FAILED},
            AgentActionStatus.EXECUTING,
            expected_run_statuses={
                RunStatus.WAITING_CONFIRMATION,
                RunStatus.COMPLETED,
            },
            run_status=RunStatus.TOOL_RUNNING,
        )
        if not claimed:
            latest_snapshot = await self._store.get(run_id)
            if latest_snapshot is not None and latest_snapshot.status is RunStatus.CANCELLED:
                raise ValueError("A cancelled run cannot execute actions.")
            latest = await self._store.get_action(run_id, action_id)
            if latest is None:
                raise KeyError(action_id)
            if latest.status is AgentActionStatus.COMPLETED:
                return latest_snapshot
            if latest.status is AgentActionStatus.REJECTED:
                raise ValueError("A rejected action cannot be approved.")
            raise ValueError("This action is already being executed.")
        await self._store.append_event(
            run_id,
            event="action.approved",
            agent="Action Executor",
            status="completed",
            message="User approved a proposed action.",
            details={"actionId": action_id, "actionType": action.action_type.value},
        )
        await self._store.append_event(
            run_id,
            event="action.started",
            agent="Action Executor",
            status="running",
            message="Executing the approved action through Spring.",
            details={"actionId": action_id, "actionType": action.action_type.value},
        )
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        try:
            result = await self._runtime.action_service.execute(run_id, action, authorization)
            duration_ms = round((time.perf_counter() - started) * 1_000, 3)
            await self._record_span(
                run_id,
                f"action.{action.action_type.value}",
                "Action Executor",
                "action",
                "completed",
                started_at,
                duration_ms,
                {"actionId": action_id},
            )
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
                details={
                    "actionId": action_id,
                    "actionType": action.action_type.value,
                    "durationMs": duration_ms,
                },
            )
        except Exception as exc:  # noqa: BLE001 - persists controlled action failures
            message = str(exc) or exc.__class__.__name__
            duration_ms = round((time.perf_counter() - started) * 1_000, 3)
            await self._record_span(
                run_id,
                f"action.{action.action_type.value}",
                "Action Executor",
                "action",
                "failed",
                started_at,
                duration_ms,
                {"actionId": action_id},
                error=message,
            )
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
                details={
                    "actionId": action_id,
                    "actionType": action.action_type.value,
                    "durationMs": duration_ms,
                },
            )
        await self._finalize_action_state(run_id)
        return await self._store.get(run_id)

    async def reject_action(
        self,
        run_id: str,
        action_id: str,
        authorization: str = "",
        owner_session: str = "",
    ) -> AgentRunSnapshot | None:
        snapshot = await self.get_owned(run_id, authorization, owner_session)
        if snapshot is None:
            return None
        if snapshot.status is RunStatus.CANCELLED:
            raise ValueError("A cancelled run cannot change actions.")
        action = await self._store.get_action(run_id, action_id)
        if action is None:
            raise KeyError(action_id)
        if action.status is AgentActionStatus.COMPLETED:
            raise ValueError("A completed action cannot be rejected.")
        if action.status is AgentActionStatus.EXECUTING:
            raise ValueError("An executing action cannot be rejected.")
        if action.status is AgentActionStatus.REJECTED:
            return snapshot
        rejected = await self._store.transition_action(
            run_id,
            action_id,
            {AgentActionStatus.PROPOSED, AgentActionStatus.FAILED},
            AgentActionStatus.REJECTED,
            expected_run_statuses={
                RunStatus.WAITING_CONFIRMATION,
                RunStatus.COMPLETED,
            },
        )
        if not rejected:
            latest_snapshot = await self._store.get(run_id)
            if latest_snapshot is not None and latest_snapshot.status is RunStatus.CANCELLED:
                raise ValueError("A cancelled run cannot change actions.")
            latest = await self._store.get_action(run_id, action_id)
            if latest is None:
                raise KeyError(action_id)
            if latest.status is AgentActionStatus.REJECTED:
                return latest_snapshot
            if latest.status is AgentActionStatus.COMPLETED:
                raise ValueError("A completed action cannot be rejected.")
            raise ValueError("An executing action cannot be rejected.")
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

    async def event_stream(
        self,
        run_id: str,
        after: int = 0,
        authorization: str = "",
        owner_session: str = "",
    ) -> AsyncIterator[str]:
        if not await self._owns_run(run_id, authorization, owner_session):
            return
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
                    f'data: {{"runId":"{run_id}","status":"{snapshot.status.value}"}}\n\n'
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
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        status = "completed"
        error: str | None = None
        try:
            await self._store.increment_attempt(run_id)
            await self._execute_pipeline(run_id, create_request, authorization)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - converts boundary errors into durable state
            status = "failed"
            error = str(exc) or exc.__class__.__name__
            await self._fail_run(run_id, error)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1_000, 3)
            await self._record_span(
                run_id,
                "run.total",
                "Supervisor",
                "run",
                status,
                started_at,
                duration_ms,
                {"mode": create_request.mode.value},
                error=error,
            )
            request_authorization.reset(token)

    async def _execute_pipeline(
        self,
        run_id: str,
        create_request: AgentRunCreateRequest,
        authorization: str,
    ) -> None:
        await self._store.set_status(run_id, RunStatus.PLANNING)
        await self._store.append_event(
            run_id,
            event="model.started",
            agent="Supervisor",
            status="running",
            message="Extracting structured constraints from natural language.",
        )
        model_started_at = datetime.now(UTC)
        model_started = time.perf_counter()
        extraction = await self._model_gateway.extract_constraints(create_request)
        model_duration = round((time.perf_counter() - model_started) * 1_000, 3)
        await self._record_span(
            run_id,
            "model.extract_constraints",
            "Supervisor",
            "model",
            "completed",
            model_started_at,
            model_duration,
            {
                "requestedProvider": extraction.requested_provider or extraction.provider,
                "effectiveProvider": extraction.provider,
                "provider": extraction.provider,
                "model": extraction.model,
                "fallbackUsed": extraction.fallback_used,
                "fallbackReason": extraction.fallback_reason,
                "finishReason": extraction.finish_reason,
                "inputTokens": extraction.input_tokens,
                "outputTokens": extraction.output_tokens,
                "reasoningTokens": extraction.reasoning_tokens,
                "responseContentLength": extraction.response_content_length,
            },
        )

        preference_started_at = datetime.now(UTC)
        preference_started = time.perf_counter()
        personalization = await self._runtime.action_service.preferences(authorization)
        preference_duration = round((time.perf_counter() - preference_started) * 1_000, 3)
        await self._record_span(
            run_id,
            "tool.user_preferences",
            "Supervisor",
            "tool",
            "completed",
            preference_started_at,
            preference_duration,
            {"memoryCount": len(personalization.get("memories") or [])},
        )
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
                "requestedProvider": extraction.requested_provider or extraction.provider,
                "effectiveProvider": extraction.provider,
                "provider": extraction.provider,
                "model": extraction.model,
                "fallbackUsed": extraction.fallback_used,
                "fallbackReason": extraction.fallback_reason,
                "finishReason": extraction.finish_reason,
                "durationMs": model_duration,
                "inputTokens": extraction.input_tokens,
                "outputTokens": extraction.output_tokens,
                "reasoningTokens": extraction.reasoning_tokens,
                "responseContentLength": extraction.response_content_length,
                "constraints": extraction.constraints.model_dump(mode="json"),
                "personalization": personalization,
            },
        )
        await self._store.set_status(run_id, RunStatus.TOOL_RUNNING)
        workflow = self._runtime.workflows[create_request.mode]
        request = AgentRunRequest(mode=create_request.mode, constraints=extraction.constraints)
        accumulated: dict = {
            "request": request,
            "events": [],
            "traces": [],
            "traceId": run_id,
        }
        async for chunk in workflow.astream(
            {"request": request, "events": [], "traces": []},
            stream_mode="updates",
        ):
            for node_name, update in chunk.items():
                if not update:
                    continue
                duration_ms = 0.0
                for key, value in update.items():
                    if key == "events":
                        accumulated["events"].extend(value)
                    elif key == "traces":
                        accumulated["traces"].extend(value)
                        for trace in value:
                            duration_ms = float(trace.get("duration_ms") or 0)
                            await self._store.record_span(
                                AgentTraceSpan.model_validate({**trace, "run_id": run_id})
                            )
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
                    details={"node": node_name, "durationMs": duration_ms},
                )

        result = self._response(create_request.mode, accumulated, extraction, personalization)
        action_started_at = datetime.now(UTC)
        action_started = time.perf_counter()
        actions = (
            await self._runtime.action_service.propose(run_id, result, authorization)
            if result.verification.valid
            else []
        )
        action_duration = round((time.perf_counter() - action_started) * 1_000, 3)
        await self._record_span(
            run_id,
            "action.plan",
            "Action Planner",
            "action",
            "completed",
            action_started_at,
            action_duration,
            {"proposalCount": len(actions)},
        )
        await self._store.add_actions(run_id, actions)
        if actions:
            await self._store.set_status(run_id, RunStatus.WAITING_CONFIRMATION, result=result)
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
                message=(
                    "Verified recommendation is ready."
                    if result.verification.valid
                    else "The run completed without proposing write actions because required checks failed."
                ),
                details={"valid": result.verification.valid},
            )

    async def _fail_run(self, run_id: str, message: str) -> None:
        await self._store.set_status(run_id, RunStatus.FAILED, error=message)
        await self._store.append_event(
            run_id,
            event="run.failed",
            status="failed",
            message=message,
        )

    async def _record_span(
        self,
        run_id: str,
        operation: str,
        agent: str,
        kind: str,
        status: str,
        started_at: datetime,
        duration_ms: float,
        attributes: dict,
        *,
        error: str | None = None,
    ) -> None:
        await self._store.record_span(
            AgentTraceSpan(
                span_id=str(uuid4()),
                run_id=run_id,
                operation=operation,
                agent=agent,
                kind=kind,
                status=status,
                started_at=started_at,
                duration_ms=duration_ms,
                attributes=attributes,
                error=error,
            )
        )

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
                AgentActionStatus.FAILED,
            }
            for action in snapshot.actions
        )
        next_status = RunStatus.WAITING_CONFIRMATION if unresolved else RunStatus.COMPLETED
        if snapshot.status is RunStatus.CANCELLED:
            return
        transitioned = await self._store.transition_status(
            run_id,
            {snapshot.status},
            next_status,
        )
        if not transitioned:
            return
        if not unresolved and snapshot.status is not RunStatus.COMPLETED:
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

    @staticmethod
    def _anonymous_owner_key(owner_session: str) -> str:
        if not owner_session:
            return ""
        return hashlib.sha256(f"anonymous-session:{owner_session}".encode()).hexdigest()

    @classmethod
    def _creation_owner_key(cls, authorization: str, owner_session: str) -> str:
        return cls._owner_key(authorization) or cls._anonymous_owner_key(owner_session)

    async def _owns_run(
        self,
        run_id: str,
        authorization: str,
        owner_session: str,
    ) -> bool:
        authenticated_owner = self._owner_key(authorization)
        if authenticated_owner and await self._store.owner_matches(run_id, authenticated_owner):
            return True

        anonymous_owner = self._anonymous_owner_key(owner_session)
        if anonymous_owner and await self._store.owner_matches(run_id, anonymous_owner):
            if not authenticated_owner:
                return True
            if await self._store.claim_owner(run_id, anonymous_owner, authenticated_owner):
                return True
            return await self._store.owner_matches(run_id, authenticated_owner)

        if not authenticated_owner and not anonymous_owner:
            return await self._store.owner_matches(run_id, "")
        return False

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
                "traceId": state.get("traceId"),
                "adapter": self._runtime.adapter_name,
                "rag": self._runtime.rag_name,
                "indexedDocuments": self._runtime.indexed_documents,
                "dataVersion": self._runtime.data_version,
                "datasetSha256": self._runtime.dataset_sha256,
                "sourceCounts": self._runtime.source_counts,
                "ragIndexStats": self._runtime.rag_index_stats,
                "retrievalVersion": self._runtime.retrieval_version,
                "retrieval": {
                    "candidates": state["candidates"].retrieval_metadata,
                    "evidence": state["evidence"].retrieval_metadata,
                },
                "modelProvider": extraction.provider,
                "modelRequestedProvider": extraction.requested_provider or extraction.provider,
                "model": extraction.model,
                "promptVersion": extraction.prompt_version,
                "modelFallbackUsed": extraction.fallback_used,
                "modelFallbackReason": extraction.fallback_reason,
                "modelFinishReason": extraction.finish_reason,
                "modelResponseContentLength": extraction.response_content_length,
                "tokenUsage": {
                    "input": extraction.input_tokens,
                    "output": extraction.output_tokens,
                    "reasoning": extraction.reasoning_tokens,
                },
                "constraints": extraction.constraints.model_dump(mode="json"),
                "personalization": personalization or {},
            },
        )
