import asyncio

from app.config import Settings
from app.domain.models import AgentMode, AgentRunCreateRequest, RunStatus
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
        assert {action.action_type.value for action in snapshot.actions} == {
            "favorite_shop",
            "save_itinerary",
        }
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
        favorite, itinerary = snapshot.actions

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
        assert after_rejection.status is RunStatus.COMPLETED
        assert any(event.event == "action.completed" for event in after_rejection.events)
        assert any(event.event == "action.rejected" for event in after_rejection.events)
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
        assert metrics["actions"]["proposed"] == 4
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
