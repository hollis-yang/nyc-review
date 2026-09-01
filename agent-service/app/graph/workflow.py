from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    DiscoveryAgent,
    EvidenceAgent,
    ItineraryAgent,
    SingleAgent,
    SupervisorAgent,
    VerifierAgent,
)
from app.graph.state import AgentState
from app.rag.candidate_discovery import CandidateDiscovery, LegacyCandidateDiscovery
from app.tools.services import ItineraryService, RagService, ShopToolService


@dataclass(frozen=True)
class WorkflowServices:
    shops: ShopToolService
    rag: RagService
    itinerary: ItineraryService
    final_candidate_limit: int = 5
    candidate_discovery: CandidateDiscovery | None = None

    def resolved_candidate_discovery(self) -> CandidateDiscovery:
        return self.candidate_discovery or LegacyCandidateDiscovery(self.shops, self.rag)


def traced_node(name: str, agent: str, operation):
    async def invoke(state: AgentState) -> dict:
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        try:
            update = await operation(state)
        except Exception:
            raise
        duration_ms = round((time.perf_counter() - started) * 1_000, 3)
        attributes = update.pop("_trace_attributes", {})
        update["traces"] = [
            {
                "span_id": str(uuid4()),
                "operation": name,
                "agent": agent,
                "kind": "agent",
                "status": "completed",
                "started_at": started_at.isoformat(),
                "duration_ms": duration_ms,
                "attributes": attributes,
            }
        ]
        return update

    return invoke


def build_multi_agent_graph(services: WorkflowServices):
    supervisor = SupervisorAgent()
    discovery = DiscoveryAgent(
        services.resolved_candidate_discovery(),
        services.final_candidate_limit,
    )
    evidence = EvidenceAgent(services.rag)
    itinerary = ItineraryAgent(services.itinerary)
    verifier = VerifierAgent()

    graph = StateGraph(AgentState)
    graph.add_node("supervisor_plan", traced_node("supervisor_plan", "Supervisor", supervisor.plan))
    graph.add_node("discovery", traced_node("discovery", "Discovery", discovery.run))
    graph.add_node("evidence", traced_node("evidence", "Evidence", evidence.run))
    graph.add_node("itinerary", traced_node("itinerary", "Itinerary", itinerary.run))
    graph.add_node("verifier", traced_node("verifier", "Verifier", verifier.run))
    graph.add_node(
        "supervisor_finalize",
        traced_node("supervisor_finalize", "Supervisor", supervisor.finalize),
    )

    graph.add_edge(START, "supervisor_plan")
    graph.add_edge("supervisor_plan", "discovery")
    graph.add_edge("discovery", "evidence")
    graph.add_edge("discovery", "itinerary")
    graph.add_edge("evidence", "verifier")
    graph.add_edge("itinerary", "verifier")
    graph.add_edge("verifier", "supervisor_finalize")
    graph.add_edge("supervisor_finalize", END)
    return graph.compile()


def build_single_agent_graph(services: WorkflowServices):
    supervisor = SupervisorAgent()
    single = SingleAgent(
        services.resolved_candidate_discovery(),
        services.rag,
        services.itinerary,
        services.final_candidate_limit,
    )
    verifier = VerifierAgent()

    graph = StateGraph(AgentState)
    graph.add_node("supervisor_plan", traced_node("supervisor_plan", "Supervisor", supervisor.plan))
    graph.add_node("single_agent", traced_node("single_agent", "Single Agent", single.run))
    graph.add_node("verifier", traced_node("verifier", "Verifier", verifier.run))
    graph.add_node(
        "supervisor_finalize",
        traced_node("supervisor_finalize", "Supervisor", supervisor.finalize),
    )

    graph.add_edge(START, "supervisor_plan")
    graph.add_edge("supervisor_plan", "single_agent")
    graph.add_edge("single_agent", "verifier")
    graph.add_edge("verifier", "supervisor_finalize")
    graph.add_edge("supervisor_finalize", END)
    return graph.compile()
