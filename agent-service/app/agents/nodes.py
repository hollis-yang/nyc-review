from __future__ import annotations

from app.domain.business_hours import is_shop_open
from app.domain.models import (
    VerificationIssue,
    VerificationReport,
    VerificationSeverity,
)
from app.graph.state import AgentState
from app.rag.candidate_discovery import CandidateDiscovery
from app.tools.services import ItineraryService, RagService, neighborhood_matches

HARD_DESIRED_TAGS = {"wheelchair_accessible"}


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
    def __init__(self, discovery: CandidateDiscovery, final_limit: int):
        self._discovery = discovery
        self._final_limit = final_limit

    async def run(self, state: AgentState) -> dict:
        candidates = await self._discovery.discover(
            state["constraints"],
            limit=min(self._final_limit, state["constraints"].result_limit),
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
        discovery: CandidateDiscovery,
        rag: RagService,
        itinerary: ItineraryService,
        final_limit: int,
    ):
        self._discovery = discovery
        self._rag = rag
        self._itinerary = itinerary
        self._final_limit = final_limit

    async def run(self, state: AgentState) -> dict:
        constraints = state["constraints"]
        candidates = await self._discovery.discover(
            constraints,
            limit=min(self._final_limit, constraints.result_limit),
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

        if not candidate_ids:
            issues.append(
                VerificationIssue(
                    code="NO_CANDIDATES",
                    message="No merchant satisfied the required constraints.",
                )
            )

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
                            severity=VerificationSeverity.WARNING,
                        )
                    )
                elif stop.estimated_cost_cents > budget:
                    issues.append(
                        VerificationIssue(
                            code="BUDGET_EXCEEDED",
                            message="Estimated cost exceeds the user's total budget.",
                            shop_id=stop.shop_id,
                            severity=VerificationSeverity.WARNING,
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
                            severity=VerificationSeverity.WARNING,
                        )
                    )

        desired_tags = set(state["constraints"].desired_tags)
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
            missing_hard_tags = sorted(set(missing_tags) & HARD_DESIRED_TAGS)
            missing_soft_tags = sorted(set(missing_tags) - HARD_DESIRED_TAGS)
            if missing_hard_tags:
                issues.append(
                    VerificationIssue(
                        code="MISSING_DESIRED_TAGS",
                        message="Candidate is missing required tags: "
                        + ", ".join(missing_hard_tags),
                        shop_id=candidate.shop_id,
                    )
                )
            if missing_soft_tags:
                issues.append(
                    VerificationIssue(
                        code="MISSING_DESIRED_TAGS",
                        message="Candidate is missing preferred tags: "
                        + ", ".join(missing_soft_tags),
                        shop_id=candidate.shop_id,
                        severity=VerificationSeverity.WARNING,
                    )
                )
            evidence = evidence_by_shop.get(candidate.shop_id)
            unsupported_tags = sorted(
                desired_tags - set(evidence.supported_tags if evidence is not None else [])
            )
            if unsupported_tags:
                issues.append(
                    VerificationIssue(
                        code="UNSUPPORTED_DESIRED_TAGS",
                        message="Retrieved evidence does not support requested tags: "
                        + ", ".join(unsupported_tags),
                        shop_id=candidate.shop_id,
                        severity=VerificationSeverity.WARNING,
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

        has_errors = any(issue.severity is VerificationSeverity.ERROR for issue in issues)
        report = VerificationReport(
            valid=not has_errors and bool(candidate_ids),
            issues=issues,
            verified_shop_ids=sorted(candidate_ids) if not has_errors else [],
        )
        return {"verification": report, "events": ["verifier:checks_completed"]}
