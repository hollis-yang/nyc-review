from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.domain.models import (
    ShopCandidate,
    VerificationIssue,
    VerificationReport,
)
from app.graph.state import AgentState
from app.tools.services import ItineraryService, RagService, ShopToolService, neighborhood_matches


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
    def __init__(self, tools: ShopToolService, rag: RagService, final_limit: int):
        self._tools = tools
        self._rag = rag
        self._final_limit = final_limit

    async def run(self, state: AgentState) -> dict:
        candidate_pool = await self._tools.search(state["constraints"])
        candidates = await _rank_candidates(
            self._rag,
            state["constraints"],
            candidate_pool,
            limit=self._final_limit,
        )
        return {
            "candidates": candidates,
            "events": ["discovery:candidate_pool_ready", "discovery:hybrid_ranked"],
            "_trace_attributes": candidates.retrieval_metadata,
        }


class EvidenceAgent:
    def __init__(self, rag: RagService):
        self._rag = rag

    async def run(self, state: AgentState) -> dict:
        evidence = await self._rag.retrieve(state["constraints"], state["candidates"])
        return {
            "evidence": evidence,
            "events": ["evidence:citations_ready", "evidence:deduplicated"],
            "_trace_attributes": evidence.retrieval_metadata,
        }


class ItineraryAgent:
    def __init__(self, itinerary: ItineraryService):
        self._itinerary = itinerary

    async def run(self, state: AgentState) -> dict:
        draft = await self._itinerary.plan(state["constraints"], state["candidates"])
        return {"itinerary": draft, "events": ["itinerary:draft_ready"]}


class SingleAgent:
    """Single-agent baseline that uses the same tools and structured contracts."""

    def __init__(
        self,
        tools: ShopToolService,
        rag: RagService,
        itinerary: ItineraryService,
        final_limit: int,
    ):
        self._tools = tools
        self._rag = rag
        self._itinerary = itinerary
        self._final_limit = final_limit

    async def run(self, state: AgentState) -> dict:
        constraints = state["constraints"]
        candidate_pool = await self._tools.search(constraints)
        candidates = await _rank_candidates(
            self._rag,
            constraints,
            candidate_pool,
            limit=self._final_limit,
        )
        evidence = await self._rag.retrieve(constraints, candidates)
        itinerary = await self._itinerary.plan(constraints, candidates)
        return {
            "candidates": candidates,
            "evidence": evidence,
            "itinerary": itinerary,
            "events": ["single_agent:read_tools_completed"],
            "_trace_attributes": {
                **candidates.retrieval_metadata,
                **evidence.retrieval_metadata,
            },
        }


class VerifierAgent:
    async def run(self, state: AgentState) -> dict:
        candidate_rows = state["candidates"].candidates
        candidate_ids = {candidate.shop_id for candidate in candidate_rows}
        evidence_ids = {
            item.shop_id
            for item in state["evidence"].evidence
            if item.citations
        }
        itinerary_ids = {stop.shop_id for stop in state["itinerary"].stops}
        issues: list[VerificationIssue] = []

        if len(candidate_ids) != len(candidate_rows):
            issues.append(
                VerificationIssue(
                    code="DUPLICATE_SHOP",
                    message="The recommendation contains a duplicate shop ID.",
                )
            )
        external_ids = [candidate.external_id for candidate in candidate_rows if candidate.external_id]
        if len(external_ids) != len(set(external_ids)):
            issues.append(
                VerificationIssue(
                    code="DUPLICATE_MERCHANT",
                    message="The recommendation contains the same source merchant more than once.",
                )
            )

        evidence_by_shop = {item.shop_id: item for item in state["evidence"].evidence}
        seen_citations: set[str] = set()
        seen_excerpts: set[tuple[int, str]] = set()
        citation_dataset_hashes: set[str] = set()
        for evidence in state["evidence"].evidence:
            for citation in evidence.citations:
                normalized_excerpt = " ".join(citation.excerpt.casefold().split())
                if citation.shop_id != evidence.shop_id or citation.shop_id not in candidate_ids:
                    issues.append(
                        VerificationIssue(
                            code="CITATION_SHOP_MISMATCH",
                            message="Citation is attached to the wrong merchant.",
                            shop_id=evidence.shop_id,
                        )
                    )
                excerpt_key = (citation.shop_id, normalized_excerpt)
                if citation.citation_id in seen_citations or (
                    normalized_excerpt and excerpt_key in seen_excerpts
                ):
                    issues.append(
                        VerificationIssue(
                            code="DUPLICATE_CITATION",
                            message="The same evidence was selected more than once.",
                            shop_id=evidence.shop_id,
                        )
                    )
                seen_citations.add(citation.citation_id)
                if normalized_excerpt:
                    seen_excerpts.add(excerpt_key)
                if citation.security_test:
                    issues.append(
                        VerificationIssue(
                            code="SECURITY_TEST_EVIDENCE",
                            message="Security-test content must not be returned as evidence.",
                            shop_id=evidence.shop_id,
                        )
                    )
                candidate = next(
                    (item for item in candidate_rows if item.shop_id == citation.shop_id), None
                )
                if (
                    candidate is not None
                    and candidate.data_version
                    and citation.data_version != candidate.data_version
                ):
                    issues.append(
                        VerificationIssue(
                            code="CITATION_VERSION_MISMATCH",
                            message="Citation belongs to another data version.",
                            shop_id=evidence.shop_id,
                        )
                    )
                if citation.dataset_sha256:
                    citation_dataset_hashes.add(citation.dataset_sha256)
        if len(citation_dataset_hashes) > 1:
            issues.append(
                VerificationIssue(
                    code="MIXED_CITATION_DATASETS",
                    message="Citations mix multiple dataset snapshots.",
                )
            )

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
        budget_relaxed = "budget" in state["candidates"].relaxed_constraints
        if budget is not None and not budget_relaxed:
            for stop in state["itinerary"].stops:
                if stop.estimated_cost_cents is None:
                    issues.append(
                        VerificationIssue(
                            code="COST_UNAVAILABLE",
                            message="No price is available for budget verification.",
                            shop_id=stop.shop_id,
                        )
                    )
                elif stop.estimated_cost_cents > budget:
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
        tags_relaxed = "desired_tags" in state["candidates"].relaxed_constraints
        for candidate in state["candidates"].candidates:
            if candidate.business_status != "OPERATIONAL":
                issues.append(
                    VerificationIssue(
                        code="BUSINESS_NOT_OPERATIONAL",
                        message="Candidate is not currently operational.",
                        shop_id=candidate.shop_id,
                    )
                )
            missing_tags = sorted(desired_tags - set(candidate.tags))
            if missing_tags and not tags_relaxed:
                issues.append(
                    VerificationIssue(
                        code="MISSING_DESIRED_TAGS",
                        message="Candidate is missing requested tags: " + ", ".join(missing_tags),
                        shop_id=candidate.shop_id,
                    )
                )
            evidence = evidence_by_shop.get(candidate.shop_id)
            unsupported_tags = sorted(
                desired_tags - set(evidence.supported_tags if evidence is not None else [])
            )
            if unsupported_tags and not tags_relaxed:
                issues.append(
                    VerificationIssue(
                        code="UNSUPPORTED_DESIRED_TAGS",
                        message="Retrieved evidence does not support requested tags: "
                        + ", ".join(unsupported_tags),
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
            if expected_neighborhood and not neighborhood_matches(
                candidate.neighborhood,
                expected_neighborhood,
            ):
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


async def _rank_candidates(
    rag: RagService,
    constraints,
    candidate_pool,
    *,
    limit: int,
):
    """Keep lightweight/custom RAG adapters compatible with the P12 contract."""

    ranker = getattr(rag, "rank_candidates", None)
    if ranker is not None:
        return await ranker(constraints, candidate_pool, limit=limit)
    return candidate_pool.model_copy(
        update={
            "candidates": candidate_pool.candidates[:limit],
            "retrieval_metadata": {
                "retrievalVersion": "legacy-adapter",
                "candidatePool": len(candidate_pool.candidates),
                "finalCandidates": min(limit, len(candidate_pool.candidates)),
            },
        }
    )


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
