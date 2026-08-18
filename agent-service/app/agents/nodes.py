from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.domain.models import (
    ShopCandidate,
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


class SingleAgent:
    """Single-agent baseline that uses the same tools and structured contracts."""

    def __init__(self, tools: ShopToolService, rag: RagService, itinerary: ItineraryService):
        self._tools = tools
        self._rag = rag
        self._itinerary = itinerary

    async def run(self, state: AgentState) -> dict:
        constraints = state["constraints"]
        candidates = await self._tools.search(constraints)
        evidence = await self._rag.retrieve(constraints, candidates)
        itinerary = await self._itinerary.plan(constraints, candidates)
        return {
            "candidates": candidates,
            "evidence": evidence,
            "itinerary": itinerary,
            "events": ["single_agent:read_tools_completed"],
        }


class VerifierAgent:
    async def run(self, state: AgentState) -> dict:
        candidate_ids = {candidate.shop_id for candidate in state["candidates"].candidates}
        evidence_ids = {
            item.shop_id
            for item in state["evidence"].evidence
            if item.citations
        }
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

        visit_time = state["constraints"].visit_time
        if visit_time:
            for candidate in state["candidates"].candidates:
                if candidate.business_hours and not is_shop_open(candidate, visit_time):
                    issues.append(
                        VerificationIssue(
                            code="CLOSED_AT_VISIT_TIME",
                            message="Published business hours do not include the requested visit time.",
                            shop_id=candidate.shop_id,
                        )
                    )

        desired_tags = set(state["constraints"].desired_tags)
        for candidate in state["candidates"].candidates:
            missing_tags = sorted(desired_tags - set(candidate.tags))
            if missing_tags:
                issues.append(
                    VerificationIssue(
                        code="MISSING_DESIRED_TAGS",
                        message="Candidate is missing requested tags: " + ", ".join(missing_tags),
                        shop_id=candidate.shop_id,
                    )
                )

            expected_category = state["constraints"].category
            if expected_category and candidate.category != expected_category:
                issues.append(
                    VerificationIssue(
                        code="CATEGORY_MISMATCH",
                        message="Candidate does not match the requested category.",
                        shop_id=candidate.shop_id,
                    )
                )

            expected_neighborhood = state["constraints"].neighborhood
            if expected_neighborhood and candidate.neighborhood != expected_neighborhood:
                issues.append(
                    VerificationIssue(
                        code="NEIGHBORHOOD_MISMATCH",
                        message="Candidate does not match the requested neighborhood.",
                        shop_id=candidate.shop_id,
                    )
                )

        report = VerificationReport(
            valid=not issues and bool(candidate_ids),
            issues=issues,
            verified_shop_ids=sorted(candidate_ids) if not issues else [],
        )
        return {"verification": report, "events": ["verifier:checks_completed"]}


def is_shop_open(candidate: ShopCandidate, visit_time: str) -> bool:
    try:
        moment = datetime.fromisoformat(visit_time.replace("Z", "+00:00"))
        timezone = ZoneInfo(candidate.timezone or "America/New_York")
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone)
        else:
            moment = moment.astimezone(timezone)
    except (ValueError, KeyError):
        return False

    current_day = moment.isoweekday()
    current_time = moment.time().replace(tzinfo=None)
    hours_by_day = {item.day_of_week: item for item in candidate.business_hours}
    today = hours_by_day.get(current_day)
    if today and not today.closed and today.open_time and today.close_time:
        opening = time.fromisoformat(today.open_time)
        closing = time.fromisoformat(today.close_time)
        if today.closes_next_day:
            if current_time >= opening:
                return True
        elif opening <= current_time < closing:
            return True

    previous_day = 7 if current_day == 1 else current_day - 1
    previous = hours_by_day.get(previous_day)
    if (
        previous
        and not previous.closed
        and previous.closes_next_day
        and previous.close_time
        and current_time < time.fromisoformat(previous.close_time)
    ):
        return True
    return False
