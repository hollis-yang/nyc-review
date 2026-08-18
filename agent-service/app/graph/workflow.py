from __future__ import annotations

from dataclasses import dataclass

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
from app.tools.services import ItineraryService, RagService, ShopToolService


@dataclass(frozen=True)
class WorkflowServices:
    shops: ShopToolService
    rag: RagService
    itinerary: ItineraryService


def build_multi_agent_graph(services: WorkflowServices):
    supervisor = SupervisorAgent()
    discovery = DiscoveryAgent(services.shops)
    evidence = EvidenceAgent(services.rag)
    itinerary = ItineraryAgent(services.itinerary)
    verifier = VerifierAgent()

    graph = StateGraph(AgentState)
    graph.add_node("supervisor_plan", supervisor.plan)
    graph.add_node("discovery", discovery.run)
    graph.add_node("evidence", evidence.run)
    graph.add_node("itinerary", itinerary.run)
    graph.add_node("verifier", verifier.run)
    graph.add_node("supervisor_finalize", supervisor.finalize)

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
    single = SingleAgent(services.shops, services.rag, services.itinerary)
    verifier = VerifierAgent()

    graph = StateGraph(AgentState)
    graph.add_node("supervisor_plan", supervisor.plan)
    graph.add_node("single_agent", single.run)
    graph.add_node("verifier", verifier.run)
    graph.add_node("supervisor_finalize", supervisor.finalize)

    graph.add_edge(START, "supervisor_plan")
    graph.add_edge("supervisor_plan", "single_agent")
    graph.add_edge("single_agent", "verifier")
    graph.add_edge("verifier", "supervisor_finalize")
    graph.add_edge("supervisor_finalize", END)
    return graph.compile()
