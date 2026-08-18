from __future__ import annotations

from app.domain.models import (
    VerificationIssue,
    VerificationReport,
)
from app.graph.state import AgentState
from app.tools.services import ItineraryService, RagService, ShopToolService


class SupervisorAgent:
    async def plan(self, state: AgentState) -> dict:
        request = state["request"]
        return {
            "constraints": request.constraints,
            "events": ["supervisor:constraints_accepted"],
        }

    async def finalize(self, state: AgentState) -> dict:
        verification = state["verification"]
        candidate_count = len(state["candidates"].candidates)
        if verification.valid:
            summary = (
                f"Verified {candidate_count} NYC candidates with cited evidence and itinerary estimates."
            )
        else:
            summary = (
                f"Generated {candidate_count} candidates, but verification found "
                f"{len(verification.issues)} issue(s)."
            )
        return {"summary": summary, "events": ["supervisor:response_finalized"]}


class DiscoveryAgent:
    def __init__(self, tools: ShopToolService):
        self._tools = tools

    async def run(self, state: AgentState) -> dict:
        candidates = await self._tools.search(state["constraints"])
        return {"candidates": candidates, "events": ["discovery:candidates_ready"]}


class EvidenceAgent:
    def __init__(self, rag: RagService):
        self._rag = rag

    async def run(self, state: AgentState) -> dict:
        evidence = await self._rag.retrieve(state["constraints"], state["candidates"])
        return {"evidence": evidence, "events": ["evidence:citations_ready"]}


class ItineraryAgent:
    def __init__(self, itinerary: ItineraryService):
        self._itinerary = itinerary

    async def run(self, state: AgentState) -> dict:
        draft = await self._itinerary.plan(state["constraints"], state["candidates"])
        return {"itinerary": draft, "events": ["itinerary:draft_ready"]}


class VerifierAgent:
    async def run(self, state: AgentState) -> dict:
        candidate_ids = {candidate.shop_id for candidate in state["candidates"].candidates}
        evidence_ids = {item.shop_id for item in state["evidence"].evidence}
        itinerary_ids = {stop.shop_id for stop in state["itinerary"].stops}
        issues: list[VerificationIssue] = []

        missing_evidence = candidate_ids - evidence_ids
        missing_itinerary = candidate_ids - itinerary_ids
        for shop_id in sorted(missing_evidence):
            issues.append(
                VerificationIssue(
                    code="MISSING_EVIDENCE",
                    message="Candidate has no cited evidence.",
                    shop_id=shop_id,
                )
            )
        for shop_id in sorted(missing_itinerary):
            issues.append(
                VerificationIssue(
                    code="MISSING_ITINERARY_STOP",
                    message="Candidate is absent from the itinerary calculation.",
                    shop_id=shop_id,
                )
            )

        budget = state["constraints"].budget_cents
        if budget is not None:
            for stop in state["itinerary"].stops:
                if stop.estimated_cost_cents > budget:
                    issues.append(
                        VerificationIssue(
                            code="BUDGET_EXCEEDED",
                            message="Estimated cost exceeds the user's total budget.",
                            shop_id=stop.shop_id,
                        )
                    )

        report = VerificationReport(
            valid=not issues and bool(candidate_ids),
            issues=issues,
            verified_shop_ids=sorted(candidate_ids) if not issues else [],
        )
        return {"verification": report, "events": ["verifier:checks_completed"]}
