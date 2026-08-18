from app.domain.models import (
    AgentMode,
    AgentRunRequest,
    CandidateSet,
    ShopCandidate,
    UserConstraints,
)
from app.graph.workflow import WorkflowServices, build_multi_agent_graph
from app.tools.services import HaversineItineraryService, InMemoryRagService, MockShopToolService


async def test_multi_agent_graph_runs_parallel_branches_and_verifies_results():
    workflow = build_multi_agent_graph(
        WorkflowServices(
            shops=MockShopToolService(),
            rag=InMemoryRagService(),
            itinerary=HaversineItineraryService(),
        )
    )
    request = AgentRunRequest(
        mode=AgentMode.MULTI,
        constraints=UserConstraints(
            query="Quiet dinner near MoMA with vegan options",
            latitude=40.7614,
            longitude=-73.9776,
            neighborhood="Midtown",
            category="Food & Dining",
            party_size=4,
            budget_cents=20_000,
            desired_tags=["quiet", "vegan_options"],
        ),
    )

    state = await workflow.ainvoke({"request": request, "events": []})

    assert state["verification"].valid is True
    assert state["candidates"].candidates
    assert state["evidence"].evidence
    assert state["itinerary"].stops
    assert "evidence:citations_ready" in state["events"]
    assert "itinerary:draft_ready" in state["events"]
    assert all(
        citation.untrusted_content for item in state["evidence"].evidence for citation in item.citations
    )


async def test_verifier_rejects_candidates_that_exceed_total_budget():
    class OverBudgetShopService:
        async def search(self, constraints: UserConstraints) -> CandidateSet:
            return CandidateSet(
                candidates=[
                    ShopCandidate(
                        shop_id=999,
                        name="Over Budget Fixture",
                        category="Food & Dining",
                        neighborhood="Midtown",
                        latitude=40.7614,
                        longitude=-73.9776,
                        avg_price_cents=5_000,
                        score=4.5,
                        tags=[],
                    )
                ]
            )

    workflow = build_multi_agent_graph(
        WorkflowServices(
            shops=OverBudgetShopService(),
            rag=InMemoryRagService(),
            itinerary=HaversineItineraryService(),
        )
    )
    request = AgentRunRequest(
        constraints=UserConstraints(
            query="Dinner under a very small total budget",
            party_size=4,
            budget_cents=15_000,
        )
    )

    state = await workflow.ainvoke({"request": request, "events": []})

    assert state["verification"].valid is False
    assert any(issue.code == "BUDGET_EXCEEDED" for issue in state["verification"].issues)
