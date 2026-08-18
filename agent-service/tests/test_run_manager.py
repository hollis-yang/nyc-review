import asyncio

from app.config import Settings
from app.domain.models import AgentMode, AgentRunCreateRequest, RunStatus
from app.runtime import AgentRuntime


async def wait_for_terminal(runtime: AgentRuntime, run_id: str):
    for _ in range(100):
        snapshot = await runtime.run_manager.get(run_id)
        if snapshot.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
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

        assert snapshot.status is RunStatus.COMPLETED
        assert snapshot.result is not None
        assert snapshot.result.verification.valid is True
        assert snapshot.result.metadata["constraints"]["party_size"] == 2
        completed_agents = {event.agent for event in snapshot.events if event.event == "agent.completed"}
        assert {"Supervisor", "Discovery", "Evidence", "Itinerary", "Verifier"} <= completed_agents
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

        assert snapshot.status is RunStatus.COMPLETED
        assert snapshot.result is not None
        assert snapshot.result.mode is AgentMode.SINGLE
        assert any(event.agent == "Single Agent" for event in snapshot.events)
        assert snapshot.result.evidence.evidence
    finally:
        await runtime.close()
