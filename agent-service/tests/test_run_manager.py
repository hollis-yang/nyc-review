import asyncio

import pytest

from app.config import Settings
from app.domain.models import AgentActionStatus, AgentMode, AgentRunCreateRequest, RunStatus
from app.model_gateway import HeuristicModelGateway
from app.runs.store import SQLiteRunStore
from app.runtime import AgentRuntime


async def wait_for_terminal(runtime: AgentRuntime, run_id: str):
    for _ in range(100):
        snapshot = await runtime.run_manager.get(run_id)
        if snapshot.status in {
            RunStatus.WAITING_CONFIRMATION,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        }:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError("Agent run did not finish")


async def test_run_manager_persists_multi_agent_result_and_events():
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(
                mode=AgentMode.MULTI,
                query="Quiet vegan dinner in Midtown for 2 under $120",
            )
        )
        snapshot = await wait_for_terminal(runtime, created.run_id)

        assert snapshot.status is RunStatus.WAITING_CONFIRMATION
        assert snapshot.result is not None
        assert snapshot.result.verification.valid is True
        assert snapshot.result.metadata["constraints"]["party_size"] == 2
        completed_agents = {event.agent for event in snapshot.events if event.event == "agent.completed"}
        assert {"Supervisor", "Discovery", "Evidence", "Itinerary", "Verifier"} <= completed_agents
        favorites = [
            action for action in snapshot.actions if action.action_type.value == "favorite_shop"
        ]
        assert len(favorites) == len(snapshot.result.candidates.candidates)
        assert {action.payload["shopId"] for action in favorites} == {
            candidate.shop_id for candidate in snapshot.result.candidates.candidates
        }
        assert sum(
            action.action_type.value == "save_itinerary" for action in snapshot.actions
        ) == 1
        model_span = next(
            span
            for span in await runtime.run_manager.trace(created.run_id, "")
            if span.operation == "model.extract_constraints"
        )
        assert model_span.attributes["requestedProvider"] == "heuristic"
        assert model_span.attributes["effectiveProvider"] == "heuristic"
        assert model_span.attributes["fallbackUsed"] is False
    finally:
        await runtime.close()


async def test_user_can_approve_and_reject_persisted_actions():
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(query="A quiet dinner in Midtown"),
            "test-token",
        )
        snapshot = await wait_for_terminal(runtime, created.run_id)
        favorite = next(
            action for action in snapshot.actions if action.action_type.value == "favorite_shop"
        )
        itinerary = next(
            action for action in snapshot.actions if action.action_type.value == "save_itinerary"
        )

        after_approval = await runtime.run_manager.approve_action(
            created.run_id,
            favorite.action_id,
            "test-token",
        )
        approved = next(
            action for action in after_approval.actions if action.action_id == favorite.action_id
        )
        assert approved.status.value == "completed"
        assert after_approval.status is RunStatus.WAITING_CONFIRMATION

        after_rejection = await runtime.run_manager.reject_action(
            created.run_id,
            itinerary.action_id,
            "test-token",
        )
        rejected = next(
            action for action in after_rejection.actions if action.action_id == itinerary.action_id
        )
        assert rejected.status.value == "rejected"
        assert after_rejection.status is RunStatus.WAITING_CONFIRMATION
        assert any(event.event == "action.completed" for event in after_rejection.events)
        assert any(event.event == "action.rejected" for event in after_rejection.events)

        final_snapshot = after_rejection
        for action in final_snapshot.actions:
            if action.status.value == "proposed":
                final_snapshot = await runtime.run_manager.reject_action(
                    created.run_id,
                    action.action_id,
                    "test-token",
                )
        assert final_snapshot.status is RunStatus.COMPLETED
    finally:
        await runtime.close()


async def test_concurrent_approval_executes_an_action_only_once():
    class BlockingActionGateway:
        def __init__(self):
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def preferences(self, authorization):
            return {}

        async def available_vouchers(self, shop_id, authorization):
            return []

        async def execute(self, run_id, action, authorization):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return {"status": "completed"}

    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    gateway = BlockingActionGateway()
    runtime.action_service._gateway = gateway
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(query="A quiet dinner in Midtown"),
            "test-token",
        )
        snapshot = await wait_for_terminal(runtime, created.run_id)
        action = snapshot.actions[0]
        other_action = snapshot.actions[1]

        first = asyncio.create_task(
            runtime.run_manager.approve_action(created.run_id, action.action_id, "test-token")
        )
        await asyncio.wait_for(gateway.started.wait(), timeout=1)
        with pytest.raises(ValueError, match="already being executed"):
            await runtime.run_manager.approve_action(
                created.run_id,
                action.action_id,
                "test-token",
            )
        with pytest.raises(ValueError, match="already being executed"):
            await runtime.run_manager.approve_action(
                created.run_id,
                other_action.action_id,
                "test-token",
            )
        with pytest.raises(ValueError, match="cannot be cancelled"):
            await runtime.run_manager.cancel(created.run_id, "test-token")
        gateway.release.set()
        completed = await first

        assert gateway.calls == 1
        assert completed is not None
        assert next(
            item for item in completed.actions if item.action_id == action.action_id
        ).status.value == "completed"
        assert not any(event.event == "run.cancelled" for event in completed.events)
    finally:
        gateway.release.set()
        await runtime.close()


async def test_cancelled_run_cannot_execute_or_change_actions():
    class CountingActionGateway:
        def __init__(self):
            self.calls = 0

        async def preferences(self, authorization):
            return {}

        async def available_vouchers(self, shop_id, authorization):
            return []

        async def execute(self, run_id, action, authorization):
            self.calls += 1
            return {"status": "completed"}

    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    gateway = CountingActionGateway()
    runtime.action_service._gateway = gateway
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(query="A quiet dinner in Midtown"),
            "test-token",
        )
        snapshot = await wait_for_terminal(runtime, created.run_id)
        action = snapshot.actions[0]
        cancelled = await runtime.run_manager.cancel(created.run_id, "test-token")

        assert cancelled.status is RunStatus.CANCELLED
        with pytest.raises(ValueError, match="cancelled run"):
            await runtime.run_manager.approve_action(
                created.run_id,
                action.action_id,
                "test-token",
            )
        with pytest.raises(ValueError, match="cancelled run"):
            await runtime.run_manager.reject_action(
                created.run_id,
                action.action_id,
                "test-token",
            )
        await runtime.run_manager._finalize_action_state(created.run_id)
        unchanged = await runtime.run_manager.get(created.run_id)
        assert unchanged.status is RunStatus.CANCELLED
        assert gateway.calls == 0
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "interrupted_status",
    [AgentActionStatus.APPROVED, AgentActionStatus.EXECUTING],
)
async def test_restart_returns_interrupted_actions_to_one_retryable_state(
    tmp_path,
    interrupted_status,
):
    settings = Settings(run_store_path=str(tmp_path / "agent-runs.sqlite3"))
    runtime = await AgentRuntime.create(settings)
    created = await runtime.run_manager.create(
        AgentRunCreateRequest(query="A quiet dinner in Midtown"),
        "test-token",
    )
    snapshot = await wait_for_terminal(runtime, created.run_id)
    action = snapshot.actions[0]
    await runtime.run_manager._store.update_action(
        created.run_id,
        action.action_id,
        interrupted_status,
    )
    await runtime.run_manager._store.set_status(created.run_id, RunStatus.TOOL_RUNNING)
    await runtime.close()

    recovered_runtime = await AgentRuntime.create(settings)
    recovered = await recovered_runtime.run_manager.get_owned(created.run_id, "test-token")
    assert recovered is not None
    recovered_action = next(
        item for item in recovered.actions if item.action_id == action.action_id
    )
    assert recovered.status is RunStatus.WAITING_CONFIRMATION
    assert recovered_action.status is AgentActionStatus.FAILED
    assert "service restart" in (recovered_action.error or "")
    assert sum(
        event.event == "action.failed" and event.details.get("recovery") == "service_restart"
        for event in recovered.events
    ) == 1
    await recovered_runtime.close()

    restarted_runtime = await AgentRuntime.create(settings)
    restarted = await restarted_runtime.run_manager.get_owned(created.run_id, "test-token")
    assert restarted is not None
    assert sum(
        event.event == "action.failed" and event.details.get("recovery") == "service_restart"
        for event in restarted.events
    ) == 1
    completed = await restarted_runtime.run_manager.approve_action(
        created.run_id,
        action.action_id,
        "test-token",
    )
    assert completed is not None
    assert next(
        item for item in completed.actions if item.action_id == action.action_id
    ).status is AgentActionStatus.COMPLETED
    await restarted_runtime.close()


@pytest.mark.parametrize(
    ("runtime_field", "new_value"),
    [
        ("data_version", "nyc-real-v1-new-snapshot"),
        ("dataset_sha256", "new-dataset-sha256"),
    ],
)
async def test_action_approval_rejects_a_run_from_a_stale_dataset_identity(
    runtime_field,
    new_value,
):
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(query="A quiet dinner in Midtown"),
            "test-token",
        )
        snapshot = await wait_for_terminal(runtime, created.run_id)
        action = snapshot.actions[0]

        setattr(runtime, runtime_field, new_value)

        with pytest.raises(ValueError, match="different dataset version"):
            await runtime.run_manager.approve_action(
                created.run_id,
                action.action_id,
                "test-token",
            )

        unchanged = await runtime.run_manager.get(created.run_id)
        assert unchanged.actions[0].status.value == "proposed"
    finally:
        await runtime.close()


async def test_run_history_is_isolated_by_hashed_authorization():
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    try:
        first = await runtime.run_manager.create(
            AgentRunCreateRequest(query="Dinner in Midtown"),
            "token-a",
        )
        second = await runtime.run_manager.create(
            AgentRunCreateRequest(query="Coffee in Chelsea"),
            "token-b",
        )
        await wait_for_terminal(runtime, first.run_id)
        await wait_for_terminal(runtime, second.run_id)

        first_history = await runtime.run_manager.list_runs("token-a")
        second_history = await runtime.run_manager.list_runs("token-b")

        assert [item.run_id for item in first_history] == [first.run_id]
        assert [item.run_id for item in second_history] == [second.run_id]
        assert await runtime.run_manager.list_runs("") == []
        metrics = await runtime.run_manager.metrics()
        assert metrics["runs"]["waiting_confirmation"] == 2
        assert metrics["actions"]["proposed"] == 8
        assert metrics["traces"]["count"] > 0
        assert metrics["traces"]["failures"] == 0
        assert await runtime.run_manager.get_owned(first.run_id, "token-b") is None
        trace = await runtime.run_manager.trace(first.run_id, "token-a")
        assert trace is not None
        assert {span.operation for span in trace} >= {
            "model.extract_constraints",
            "discovery",
            "run.total",
        }
    finally:
        await runtime.close()


async def test_anonymous_session_run_is_securely_claimed_after_sign_in():
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    owner_session = "anonymous-browser-session-a"
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(query="A quiet dinner in Midtown"),
            "",
            owner_session,
        )
        snapshot = await wait_for_terminal(runtime, created.run_id)
        action = snapshot.actions[0]

        assert await runtime.run_manager.get_owned(
            created.run_id, "", "anonymous-browser-session-b"
        ) is None
        assert await runtime.run_manager.get_owned(
            created.run_id, "signed-in-token", "anonymous-browser-session-b"
        ) is None

        claimed = await runtime.run_manager.get_owned(
            created.run_id, "signed-in-token", owner_session
        )
        assert claimed is not None
        assert [item.run_id for item in await runtime.run_manager.list_runs("signed-in-token")] == [
            created.run_id
        ]
        assert await runtime.run_manager.get_owned(created.run_id, "", owner_session) is None
        assert await runtime.run_manager.get_owned(
            created.run_id, "another-user-token", owner_session
        ) is None

        approved = await runtime.run_manager.approve_action(
            created.run_id,
            action.action_id,
            "signed-in-token",
            owner_session,
        )
        assert approved is not None
        assert next(
            item for item in approved.actions if item.action_id == action.action_id
        ).status.value == "completed"
    finally:
        await runtime.close()


async def test_single_agent_baseline_uses_same_response_contract():
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(
                mode=AgentMode.SINGLE,
                query="An accessible cafe in Chelsea",
            )
        )
        snapshot = await wait_for_terminal(runtime, created.run_id)

        assert snapshot.status is RunStatus.WAITING_CONFIRMATION
        assert snapshot.result is not None
        assert snapshot.result.mode is AgentMode.SINGLE
        assert any(event.agent == "Single Agent" for event in snapshot.events)
        assert snapshot.result.evidence.evidence
    finally:
        await runtime.close()


async def test_requested_result_limit_controls_candidates_and_actions():
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(query="Show the top 2 dinner places in Midtown")
        )
        snapshot = await wait_for_terminal(runtime, created.run_id)

        assert snapshot.result.metadata["constraints"]["result_limit"] == 2
        assert len(snapshot.result.candidates.candidates) == 2
        assert sum(action.action_type.value == "favorite_shop" for action in snapshot.actions) == 2
        assert sum(action.action_type.value == "save_itinerary" for action in snapshot.actions) == 1
    finally:
        await runtime.close()


async def test_cancel_propagates_to_a_model_call_without_waiting_for_a_deadline():
    class BlockingGateway:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.never = asyncio.Event()

        async def extract_constraints(self, request):
            self.started.set()
            try:
                await self.never.wait()
            finally:
                self.cancelled.set()

    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    gateway = BlockingGateway()
    runtime.run_manager._model_gateway = gateway
    try:
        created = await runtime.run_manager.create(
            AgentRunCreateRequest(query="A request that waits for the model"),
            "cancel-owner",
        )
        await asyncio.wait_for(gateway.started.wait(), timeout=1)
        cancelled = await runtime.run_manager.cancel(created.run_id, "cancel-owner")
        await asyncio.wait_for(gateway.cancelled.wait(), timeout=2)

        assert cancelled.status is RunStatus.CANCELLED
        assert cancelled.actions == []
        assert any(event.event == "run.cancelled" for event in cancelled.events)
    finally:
        await runtime.close()


async def test_runtime_close_cancels_active_runs_without_orphan_tasks():
    class BlockingGateway:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def extract_constraints(self, request):
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()

    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    gateway = BlockingGateway()
    runtime.run_manager._model_gateway = gateway
    await runtime.run_manager.create(AgentRunCreateRequest(query="Wait until shutdown"))
    await asyncio.wait_for(gateway.started.wait(), timeout=1)

    await runtime.close()

    await asyncio.wait_for(gateway.cancelled.wait(), timeout=2)
    assert runtime.run_manager._tasks == {}


async def test_multiple_runs_execute_concurrently_and_remain_owner_isolated():
    class ConcurrentGateway:
        def __init__(self, expected: int):
            self.expected = expected
            self.active = 0
            self.maximum_active = 0
            self.gate = asyncio.Event()
            self.delegate = HeuristicModelGateway()

        async def extract_constraints(self, request):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            if self.active == self.expected:
                self.gate.set()
            try:
                await asyncio.wait_for(self.gate.wait(), timeout=1)
                return await self.delegate.extract_constraints(request)
            finally:
                self.active -= 1

    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    gateway = ConcurrentGateway(expected=3)
    runtime.run_manager._model_gateway = gateway
    try:
        created = [
            await runtime.run_manager.create(
                AgentRunCreateRequest(query=f"Top 2 dinner choices in Midtown request {index}"),
                f"owner-{index}",
            )
            for index in range(3)
        ]
        snapshots = await asyncio.gather(
            *(wait_for_terminal(runtime, item.run_id) for item in created)
        )

        assert gateway.maximum_active == 3
        assert all(snapshot.status is RunStatus.WAITING_CONFIRMATION for snapshot in snapshots)
        for index, item in enumerate(created):
            assert await runtime.run_manager.get_owned(item.run_id, f"owner-{index}") is not None
            assert await runtime.run_manager.get_owned(item.run_id, "another-owner") is None
    finally:
        await runtime.close()


async def test_restart_recovers_only_unfinished_read_only_run(tmp_path):
    run_store_path = tmp_path / "p14-recovery.sqlite3"
    store = SQLiteRunStore(str(run_store_path))
    request = AgentRunCreateRequest(query="Top 2 cafes in Astoria")
    run_id = "p14-recoverable-run"
    await store.create(run_id, request)
    await store.close()

    runtime = await AgentRuntime.create(Settings(run_store_path=str(run_store_path)))
    try:
        snapshot = await wait_for_terminal(runtime, run_id)

        assert snapshot.status is RunStatus.WAITING_CONFIRMATION
        assert any(event.event == "run.recovered" for event in snapshot.events)
        assert snapshot.actions
    finally:
        await runtime.close()
