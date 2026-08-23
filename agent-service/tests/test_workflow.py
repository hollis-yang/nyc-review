from app.domain.models import (
    AgentMode,
    AgentRunRequest,
    CandidateSet,
    EvidencePack,
    ShopCandidate,
    ShopEvidence,
    UserConstraints,
)
from app.graph.workflow import WorkflowServices, build_multi_agent_graph, build_single_agent_graph
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


async def test_verifier_accepts_explicitly_relaxed_unknown_price_without_treating_it_as_zero():
    class UnknownPriceShopService:
        async def search(self, constraints: UserConstraints) -> CandidateSet:
            return CandidateSet(
                candidates=[
                    ShopCandidate(
                        shop_id=998,
                        name="Unknown Price Fixture",
                        category="Food & Dining",
                        neighborhood="Midtown",
                        latitude=40.7614,
                        longitude=-73.9776,
                        avg_price_cents=None,
                        score=4.5,
                    )
                ],
                relaxed_constraints=["budget"],
            )

    workflow = build_multi_agent_graph(
        WorkflowServices(
            shops=UnknownPriceShopService(),
            rag=InMemoryRagService(),
            itinerary=HaversineItineraryService(),
        )
    )
    state = await workflow.ainvoke(
        {
            "request": AgentRunRequest(
                constraints=UserConstraints(query="Dinner under $100", budget_cents=10_000)
            ),
            "events": [],
        }
    )

    assert state["itinerary"].stops[0].estimated_cost_cents is None
    assert state["itinerary"].total_estimated_cost_cents is None
    assert state["verification"].valid is True
    assert not any(issue.code == "COST_UNAVAILABLE" for issue in state["verification"].issues)


async def test_verifier_does_not_repeat_tag_failures_after_discovery_relaxes_tags():
    class RelaxedTagShopService:
        async def search(self, constraints: UserConstraints) -> CandidateSet:
            return CandidateSet(
                candidates=[
                    ShopCandidate(
                        shop_id=996,
                        name="Closest Match Fixture",
                        category="Food & Dining",
                        neighborhood="Midtown",
                        latitude=40.7614,
                        longitude=-73.9776,
                        avg_price_cents=3_500,
                        score=4.3,
                        tags=["good_for_groups"],
                    )
                ],
                relaxed_constraints=["desired_tags"],
            )

    workflow = build_multi_agent_graph(
        WorkflowServices(
            shops=RelaxedTagShopService(),
            rag=InMemoryRagService(),
            itinerary=HaversineItineraryService(),
        )
    )
    state = await workflow.ainvoke(
        {
            "request": AgentRunRequest(
                constraints=UserConstraints(
                    query="Quiet budget dinner in Midtown",
                    desired_tags=["quiet", "budget_friendly"],
                )
            ),
            "events": [],
        }
    )

    assert state["verification"].valid is True
    assert not any(
        issue.code == "MISSING_DESIRED_TAGS" for issue in state["verification"].issues
    )


async def test_verifier_accepts_friendly_neighborhood_inside_official_nta_label():
    class CompoundNeighborhoodShopService:
        async def search(self, constraints: UserConstraints) -> CandidateSet:
            return CandidateSet(
                candidates=[
                    ShopCandidate(
                        shop_id=997,
                        name="Official NTA Fixture",
                        category="Food & Dining",
                        neighborhood="Midtown-Times Square",
                        latitude=40.7614,
                        longitude=-73.9776,
                        avg_price_cents=None,
                        score=4.2,
                    )
                ]
            )

    workflow = build_multi_agent_graph(
        WorkflowServices(
            shops=CompoundNeighborhoodShopService(),
            rag=InMemoryRagService(),
            itinerary=HaversineItineraryService(),
        )
    )
    state = await workflow.ainvoke(
        {
            "request": AgentRunRequest(
                constraints=UserConstraints(
                    query="Dinner in Midtown",
                    neighborhood="Midtown",
                    category="Food & Dining",
                )
            ),
            "events": [],
        }
    )

    assert state["verification"].valid is True
    assert not any(
        issue.code == "NEIGHBORHOOD_MISMATCH" for issue in state["verification"].issues
    )


async def test_verifier_rejects_evidence_entries_without_citations():
    class SingleShopService:
        async def search(self, constraints: UserConstraints) -> CandidateSet:
            return CandidateSet(
                candidates=[
                    ShopCandidate(
                        shop_id=999,
                        name="Missing Evidence Fixture",
                        category="Food & Dining",
                        neighborhood="Chelsea",
                        latitude=40.7465,
                        longitude=-74.0014,
                        avg_price_cents=4_000,
                        score=4.5,
                    )
                ]
            )

    class EmptyCitationRagService:
        async def retrieve(
            self,
            constraints: UserConstraints,
            candidates: CandidateSet,
        ) -> EvidencePack:
            return EvidencePack(evidence=[ShopEvidence(shop_id=999, citations=[])])

    workflow = build_multi_agent_graph(
        WorkflowServices(
            shops=SingleShopService(),
            rag=EmptyCitationRagService(),
            itinerary=HaversineItineraryService(),
        )
    )
    state = await workflow.ainvoke(
        {
            "request": AgentRunRequest(
                constraints=UserConstraints(query="A result that has no cited evidence")
            ),
            "events": [],
        }
    )

    assert state["verification"].valid is False
    assert any(issue.code == "MISSING_EVIDENCE" for issue in state["verification"].issues)


async def test_single_agent_graph_uses_same_verifier_contract():
    workflow = build_single_agent_graph(
        WorkflowServices(
            shops=MockShopToolService(),
            rag=InMemoryRagService(),
            itinerary=HaversineItineraryService(),
        )
    )
    request = AgentRunRequest(
        mode=AgentMode.SINGLE,
        constraints=UserConstraints(query="Quiet dinner in Midtown", desired_tags=["quiet"]),
    )

    state = await workflow.ainvoke({"request": request, "events": []})

    assert state["verification"].valid is True
    assert "single_agent:read_tools_completed" in state["events"]
