from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.domain.models import CandidateSet, EvidencePack, UserConstraints
from app.rag.candidate_discovery import (
    GlobalHybridCandidateDiscovery,
    _pre_rerank_metadata,
    _reranker_query,
    _reranker_trace_metadata,
)
from app.rag.lexical import expand_query
from app.rag.query_rewriter import (
    MAX_QUERY_CHARACTERS,
    HardConstraintEcho,
    QueryRewritePlan,
    QueryRewriteProvider,
    QueryRewriteTrace,
    RewriteUsage,
)
from app.rag.reranker import (
    CandidateReranker,
    RerankCandidate,
    RerankStatus,
)
from evals.rag_v2.contract import sha256_json

M4_REPLAY_VERSION = "m4-frozen-candidates-evidence-replay-v1"
M4_REWRITE_REPLAY_VERSION = "m4-frozen-query-rewrite-replay-v1"
M4_PERFORMANCE_SCOPE = "reranker-isolation-with-frozen-candidates-and-evidence"
M4_ARTIFACT_SCHEMA_VERSION = 1


def deterministic_rule_query(constraints: UserConstraints) -> str:
    """Reproduce the exact rule query passed by Candidate Discovery."""

    return expand_query(
        constraints.query,
        [constraints.category or "", constraints.neighborhood or "", *constraints.desired_tags],
    )


def user_constraints_payload(constraints: UserConstraints) -> dict[str, Any]:
    return constraints.model_dump(mode="json", by_alias=True)


def rewrite_plan_semantic_identity(plan: QueryRewritePlan) -> dict[str, Any]:
    """Bind stable semantics/provider identity while excluding dynamic usage."""

    trace = plan.trace
    return {
        "version": M4_REWRITE_REPLAY_VERSION,
        "language": plan.language,
        "original": plan.original.model_dump(mode="json", by_alias=True),
        "rule": plan.rule.model_dump(mode="json", by_alias=True),
        "rewrites": [item.model_dump(mode="json", by_alias=True) for item in plan.rewrites],
        "retrievalQueries": list(plan.retrieval_queries),
        "semanticTags": list(plan.semantic_tags),
        "excludedTags": list(plan.excluded_tags),
        "hardConstraints": plan.hard_constraints.model_dump(mode="json", by_alias=True),
        "providerIdentity": {
            "requestedProvider": trace.requested_provider,
            "requestedModel": trace.requested_model,
            "effectiveProvider": trace.provider,
            "effectiveModel": trace.model,
            "promptVersion": trace.prompt_version,
        },
    }


def rewrite_plan_semantic_identity_sha256(plan: QueryRewritePlan) -> str:
    return sha256_json(rewrite_plan_semantic_identity(plan))


def m4_replay_implementation_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def frozen_rewrite_artifact(
    plan: QueryRewritePlan,
    *,
    case_id: str,
    constraints: UserConstraints,
    rule_query: str,
) -> dict[str, Any]:
    normalized_case_id = case_id.strip()
    if not normalized_case_id:
        raise ValueError("M4 frozen rewrite artifact requires a case ID.")
    _validate_plan_request(plan, constraints=constraints, rule_query=rule_query)
    artifact = {
        "schemaVersion": M4_ARTIFACT_SCHEMA_VERSION,
        "version": M4_REWRITE_REPLAY_VERSION,
        "caseId": normalized_case_id,
        "constraints": user_constraints_payload(constraints),
        "constraintsSha256": sha256_json(user_constraints_payload(constraints)),
        "ruleQuerySha256": sha256_json(rule_query),
        "plan": plan.model_dump(mode="json", by_alias=True),
        "semanticPlanSha256": rewrite_plan_semantic_identity_sha256(plan),
    }
    artifact["captureEnvelopeSha256"] = sha256_json(artifact)
    validate_frozen_rewrite_artifact(artifact)
    return _deep_copy(artifact)


def validate_frozen_rewrite_artifact(
    value: Any,
    *,
    expected_case_id: str | None = None,
    expected_constraints: UserConstraints | None = None,
    expected_rule_query: str | None = None,
) -> QueryRewritePlan:
    if not isinstance(value, Mapping):
        raise ValueError("M4 frozen rewrite artifact must be an object.")
    artifact = _deep_copy(dict(value))
    if (
        artifact.get("schemaVersion") != M4_ARTIFACT_SCHEMA_VERSION
        or artifact.get("version") != M4_REWRITE_REPLAY_VERSION
    ):
        raise ValueError("M4 frozen rewrite artifact uses an unsupported schema.")
    case_id = artifact.get("caseId")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("M4 frozen rewrite artifact has no case ID.")
    if expected_case_id is not None and case_id != expected_case_id:
        raise ValueError("M4 frozen rewrite artifact case ID mismatch.")
    constraints = UserConstraints.model_validate(artifact.get("constraints"))
    constraints_payload = user_constraints_payload(constraints)
    if artifact.get("constraintsSha256") != sha256_json(constraints_payload):
        raise ValueError("M4 frozen rewrite artifact constraints SHA is invalid.")
    if expected_constraints is not None and constraints_payload != user_constraints_payload(
        expected_constraints
    ):
        raise ValueError("M4 frozen rewrite artifact constraints mismatch.")
    rule_query = expected_rule_query or deterministic_rule_query(constraints)
    if artifact.get("ruleQuerySha256") != sha256_json(rule_query):
        raise ValueError("M4 frozen rewrite artifact rule-query SHA is invalid.")
    plan = QueryRewritePlan.model_validate(artifact.get("plan"))
    _validate_plan_request(plan, constraints=constraints, rule_query=rule_query)
    if artifact.get("semanticPlanSha256") != rewrite_plan_semantic_identity_sha256(plan):
        raise ValueError("M4 frozen rewrite semantic/provider identity SHA is invalid.")
    envelope = dict(artifact)
    observed_sha = envelope.pop("captureEnvelopeSha256", None)
    if observed_sha != sha256_json(envelope):
        raise ValueError("M4 frozen rewrite capture-envelope SHA is invalid.")
    return plan.model_copy(deep=True)


class RecordingQueryRewriter:
    """Eval-only wrapper recording the exact plan used to generate a captured pool."""

    def __init__(self, inner: QueryRewriteProvider) -> None:
        self._inner = inner
        self._plans: dict[tuple[str, str], QueryRewritePlan] = {}
        self._lock = asyncio.Lock()

    async def rewrite(
        self, constraints: UserConstraints, *, rule_query: str | None = None
    ) -> QueryRewritePlan:
        exact_rule = rule_query or deterministic_rule_query(constraints)
        plan = await self._inner.rewrite(constraints, rule_query=exact_rule)
        _validate_plan_request(plan, constraints=constraints, rule_query=exact_rule)
        async with self._lock:
            self._plans[_request_key(constraints, exact_rule)] = plan.model_copy(deep=True)
        return plan

    def artifact_for_case(
        self,
        *,
        case_id: str,
        constraints: UserConstraints,
        rule_query: str | None = None,
    ) -> dict[str, Any]:
        exact_rule = rule_query or deterministic_rule_query(constraints)
        plan = self._plans.get(_request_key(constraints, exact_rule))
        if plan is None:
            raise ValueError(f"M4 capture did not record the plan used by case {case_id}.")
        return frozen_rewrite_artifact(
            plan,
            case_id=case_id,
            constraints=constraints,
            rule_query=exact_rule,
        )

    def usage_snapshot(self) -> RewriteUsage:
        return self._inner.usage_snapshot()

    def reset(self) -> None:
        # Scored capture must not accidentally reuse an artifact from warmup.
        self._plans.clear()
        self._inner.reset()

    def clear_cache(self) -> None:
        # Cache maintenance must never erase an already recorded artifact.
        self._inner.clear_cache()

    async def aclose(self) -> None:
        await self._inner.aclose()


class FrozenQueryRewriter:
    """Zero-network replay retained for upstream audit; formal M4 bypasses retrieval."""

    def __init__(self, cases: Sequence[Mapping[str, Any]]) -> None:
        rows = frozen_replay_contract_rows(cases)
        self._by_request: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        for case, row in zip(cases, rows, strict=True):
            artifact = _case_artifact(case)["rewritePlan"]
            self._by_request[(row["constraintsSha256"], row["ruleQuerySha256"])] = (
                row["id"],
                _deep_copy(artifact),
            )

    async def rewrite(
        self, constraints: UserConstraints, *, rule_query: str | None = None
    ) -> QueryRewritePlan:
        exact_rule = rule_query or deterministic_rule_query(constraints)
        frozen = self._by_request.get(_request_key(constraints, exact_rule))
        if frozen is None:
            raise ValueError("M4 frozen replay has no exact constraints/rule binding.")
        plan = validate_frozen_rewrite_artifact(
            frozen[1], expected_constraints=constraints, expected_rule_query=exact_rule
        )
        captured = plan.trace
        return plan.model_copy(
            update={
                "trace": QueryRewriteTrace(
                    requested_provider=captured.requested_provider,
                    requested_model=captured.requested_model,
                    provider="frozen-replay",
                    model="frozen-replay",
                    prompt_version=captured.prompt_version,
                    rewrite_count=len(plan.rewrites),
                    network_requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0.0,
                    cache_hit=False,
                    fallback_used=False,
                    fallback_reason=None,
                    response_content_length=0,
                )
            },
            deep=True,
        )

    def usage_snapshot(self) -> RewriteUsage:
        return RewriteUsage()

    def reset(self) -> None:
        return None

    def clear_cache(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class RecordingGlobalHybridCandidateDiscovery(GlobalHybridCandidateDiscovery):
    """Capture exact inputs at the production pre-rerank boundary for M4 Eval."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._m4_records: dict[tuple[str, str], dict[str, Any]] = {}
        self._m4_lock = asyncio.Lock()

    async def _rank_fusion_pool(
        self,
        constraints: UserConstraints,
        fusion_pool: CandidateSet,
        *,
        limit: int,
        discovery_started: float,
        hard_constraints: UserConstraints,
        excluded_tags: tuple[str, ...],
        aggregation: Any,
    ) -> CandidateSet:
        rerank_query = _reranker_query(constraints)
        rerank_candidates = self._rerank_candidates(
            fusion_pool,
            aggregation,
            limit=self._reranker_candidate_limit,
        )
        pre_metadata = _pre_rerank_metadata(
            fusion_pool,
            rerank_query=rerank_query,
            rerank_candidates=rerank_candidates,
        )
        ranked = await super()._rank_fusion_pool(
            constraints,
            fusion_pool,
            limit=limit,
            discovery_started=discovery_started,
            hard_constraints=hard_constraints,
            excluded_tags=excluded_tags,
            aggregation=aggregation,
        )
        # Freeze evidence for the complete pool during the same capture invocation.
        evidence = await self._rag.retrieve(hard_constraints, fusion_pool)
        record = {
            "preRerankCandidateSet": fusion_pool.model_dump(mode="json", by_alias=True),
            "rerankQuery": rerank_query,
            "rerankCandidates": [item.model_dump(mode="json", by_alias=True) for item in rerank_candidates],
            "preRerankMetadata": _deep_copy(pre_metadata),
            "evidencePack": evidence.model_dump(mode="json", by_alias=True),
            "controlFinalCandidateSet": ranked.model_dump(mode="json", by_alias=True),
        }
        key = _request_key(hard_constraints, deterministic_rule_query(hard_constraints))
        async with self._m4_lock:
            self._m4_records[key] = _deep_copy(record)
        return ranked

    def reset_capture(self) -> None:
        self._m4_records.clear()

    def artifact_for_case(
        self,
        *,
        case_id: str,
        constraints: UserConstraints,
        rewrite_artifact: Mapping[str, Any],
    ) -> dict[str, Any]:
        rule_query = deterministic_rule_query(constraints)
        record = self._m4_records.get(_request_key(constraints, rule_query))
        if record is None:
            raise ValueError(f"M4 capture did not record frozen candidates for {case_id}.")
        return build_frozen_case_artifact(
            case_id=case_id,
            constraints=constraints,
            rewrite_artifact=rewrite_artifact,
            pre_rerank_candidate_set=CandidateSet.model_validate(record["preRerankCandidateSet"]),
            rerank_query=str(record["rerankQuery"]),
            rerank_candidates=tuple(
                RerankCandidate.model_validate(item) for item in record["rerankCandidates"]
            ),
            evidence_pack=EvidencePack.model_validate(record["evidencePack"]),
            control_final_candidate_set=CandidateSet.model_validate(record["controlFinalCandidateSet"]),
        )


def build_frozen_case_artifact(
    *,
    case_id: str,
    constraints: UserConstraints,
    rewrite_artifact: Mapping[str, Any],
    pre_rerank_candidate_set: CandidateSet,
    rerank_query: str,
    rerank_candidates: Sequence[RerankCandidate],
    evidence_pack: EvidencePack,
    control_final_candidate_set: CandidateSet,
) -> dict[str, Any]:
    """Build the canonical, fully self-hashed M4 isolation boundary."""

    artifact = {
        "schemaVersion": M4_ARTIFACT_SCHEMA_VERSION,
        "version": M4_REPLAY_VERSION,
        "performanceScope": M4_PERFORMANCE_SCOPE,
        "caseId": case_id,
        "constraints": user_constraints_payload(constraints),
        "constraintsSha256": sha256_json(user_constraints_payload(constraints)),
        "ruleQuerySha256": sha256_json(deterministic_rule_query(constraints)),
        "rewritePlan": _deep_copy(dict(rewrite_artifact)),
        "preRerankCandidateSet": pre_rerank_candidate_set.model_dump(mode="json", by_alias=True),
        "rerankQuery": rerank_query,
        "rerankCandidates": [item.model_dump(mode="json", by_alias=True) for item in rerank_candidates],
        "preRerankMetadata": _pre_rerank_metadata(
            pre_rerank_candidate_set,
            rerank_query=rerank_query,
            rerank_candidates=tuple(rerank_candidates),
        ),
        "evidencePack": evidence_pack.model_dump(mode="json", by_alias=True),
        "controlFinalCandidateSet": control_final_candidate_set.model_dump(mode="json", by_alias=True),
    }
    artifact.update(_component_hashes(artifact))
    artifact["artifactSha256"] = sha256_json(artifact)
    validate_frozen_case_artifact(
        artifact,
        expected_case_id=case_id,
        expected_constraints=constraints,
    )
    return _deep_copy(artifact)


class FrozenCandidateDiscovery:
    """Replay one frozen candidate/evidence boundary and isolate reranker impact."""

    def __init__(
        self,
        cases: Sequence[Mapping[str, Any]],
        *,
        reranker: CandidateReranker | None,
    ) -> None:
        rows = frozen_replay_contract_rows(cases)
        self._reranker = reranker
        self._by_request: dict[tuple[str, str], dict[str, Any]] = {}
        for case, row in zip(cases, rows, strict=True):
            artifact = _deep_copy(_case_artifact(case))
            self._by_request[(row["constraintsSha256"], row["ruleQuerySha256"])] = artifact

    async def discover(
        self,
        constraints: UserConstraints,
        *,
        limit: int,
    ) -> CandidateSet:
        if limit != 10:
            raise ValueError("M4 frozen candidate replay requires final Top-10.")
        artifact = self._artifact_for_constraints(constraints)
        pool = CandidateSet.model_validate(artifact["preRerankCandidateSet"])
        rerank_candidates = tuple(
            RerankCandidate.model_validate(item) for item in artifact["rerankCandidates"]
        )
        metadata = _formal_replay_metadata(artifact)
        if self._reranker is None:
            final = CandidateSet.model_validate(artifact["controlFinalCandidateSet"])
            metadata["finalCandidates"] = len(final.candidates)
            metadata.update(
                _reranker_trace_metadata(
                    None,
                    enabled=False,
                    candidate_count=len(rerank_candidates),
                )
            )
            return final.model_copy(update={"retrieval_metadata": metadata}, deep=True)

        started = time.perf_counter()
        result = await self._reranker.rerank(
            str(artifact["rerankQuery"]),
            rerank_candidates,
        )
        if result.trace.status is not RerankStatus.APPLIED:
            raise ValueError("M4 learned reranker did not apply to its frozen batch.")
        expected_input = str(artifact["preRerankMetadata"]["rerankerInputFingerprint"])
        if (
            result.trace.input_fingerprint != expected_input
            or result.trace.candidate_count != len(rerank_candidates)
            or result.trace.network_requests != 1
            or result.trace.retries != 0
            or result.trace.failures != 0
            or result.trace.fallback_used
        ):
            raise ValueError("M4 learned reranker trace violates the frozen batch contract.")
        inputs_by_id = {item.shop_id: item for item in rerank_candidates}
        ordered_ids = list(result.ordered_shop_ids)
        if (
            len(ordered_ids) != len(inputs_by_id)
            or len(ordered_ids) != len(set(ordered_ids))
            or set(ordered_ids) != set(inputs_by_id)
            or any(
                score.input_sha256 != inputs_by_id[score.shop_id].rerank_text.input_sha256
                for score in result.scores
            )
        ):
            raise ValueError("M4 reranker output changed the frozen candidate/input universe.")
        candidates_by_id = {item.shop_id: item for item in pool.candidates}
        ordered = [candidates_by_id[shop_id] for shop_id in ordered_ids]
        metadata.update(_reranker_trace_metadata(result, enabled=True))
        metadata["finalCandidates"] = min(limit, len(ordered))
        metadata["rerankerLatencyMs"] = round(
            max(float(metadata["rerankerLatencyMs"]), (time.perf_counter() - started) * 1_000),
            3,
        )
        return pool.model_copy(
            update={"candidates": ordered[:limit], "retrieval_metadata": metadata},
            deep=True,
        )

    def _artifact_for_constraints(self, constraints: UserConstraints) -> dict[str, Any]:
        rule_query = deterministic_rule_query(constraints)
        artifact = self._by_request.get(_request_key(constraints, rule_query))
        if artifact is None:
            raise ValueError("M4 frozen candidate replay has no exact constraints binding.")
        validate_frozen_case_artifact(artifact, expected_constraints=constraints)
        return _deep_copy(artifact)

    def reset_capture(self) -> None:
        return None


class FrozenRagService:
    """Return only captured evidence for the current frozen final ranking."""

    def __init__(self, cases: Sequence[Mapping[str, Any]]) -> None:
        frozen_replay_contract_rows(cases)
        self._by_request = {
            (
                str(_case_artifact(case)["constraintsSha256"]),
                str(_case_artifact(case)["ruleQuerySha256"]),
            ): _deep_copy(_case_artifact(case))
            for case in cases
        }

    async def rank_candidates(
        self,
        constraints: UserConstraints,
        candidates: CandidateSet,
        *,
        limit: int,
    ) -> CandidateSet:
        raise RuntimeError("M4 formal replay must never invoke online candidate ranking.")

    async def retrieve(
        self,
        constraints: UserConstraints,
        candidates: CandidateSet,
    ) -> EvidencePack:
        key = _request_key(constraints, deterministic_rule_query(constraints))
        artifact = self._by_request.get(key)
        if artifact is None:
            raise ValueError("M4 frozen evidence replay has no exact constraints binding.")
        validate_frozen_case_artifact(artifact, expected_constraints=constraints)
        pack = EvidencePack.model_validate(artifact["evidencePack"])
        by_shop = {item.shop_id: item for item in pack.evidence}
        requested_ids = [item.shop_id for item in candidates.candidates]
        if any(shop_id not in by_shop for shop_id in requested_ids):
            raise ValueError("M4 frozen evidence is incomplete for the final candidate set.")
        return EvidencePack(
            evidence=[by_shop[shop_id].model_copy(deep=True) for shop_id in requested_ids],
            retrieval_metadata={
                "retrievalVersion": "m4-frozen-evidence-replay-v1",
                "shops": len(requested_ids),
                "citations": sum(len(by_shop[shop_id].citations) for shop_id in requested_ids),
                "rankingCacheHit": False,
                "denseAvailable": True,
                "embeddingFallback": False,
                "latencyMs": 0.0,
                "executionMode": "frozen-replay",
            },
        )


def validate_frozen_case_artifact(
    value: Any,
    *,
    expected_case_id: str | None = None,
    expected_constraints: UserConstraints | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("M4 frozen candidate artifact must be an object.")
    artifact = _deep_copy(dict(value))
    if (
        artifact.get("schemaVersion") != M4_ARTIFACT_SCHEMA_VERSION
        or artifact.get("version") != M4_REPLAY_VERSION
        or artifact.get("performanceScope") != M4_PERFORMANCE_SCOPE
    ):
        raise ValueError("M4 frozen candidate artifact uses an unsupported schema/scope.")
    case_id = artifact.get("caseId")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("M4 frozen candidate artifact has no case ID.")
    if expected_case_id is not None and case_id != expected_case_id:
        raise ValueError("M4 frozen candidate artifact case ID mismatch.")
    constraints = UserConstraints.model_validate(artifact.get("constraints"))
    constraints_payload = user_constraints_payload(constraints)
    if artifact.get("constraintsSha256") != sha256_json(constraints_payload):
        raise ValueError("M4 frozen candidate artifact constraints SHA is invalid.")
    if expected_constraints is not None and constraints_payload != user_constraints_payload(
        expected_constraints
    ):
        raise ValueError("M4 frozen candidate artifact constraints mismatch.")
    rule_query = deterministic_rule_query(constraints)
    if artifact.get("ruleQuerySha256") != sha256_json(rule_query):
        raise ValueError("M4 frozen candidate artifact rule-query SHA is invalid.")
    validate_frozen_rewrite_artifact(
        artifact.get("rewritePlan"),
        expected_case_id=case_id,
        expected_constraints=constraints,
        expected_rule_query=rule_query,
    )

    pool = CandidateSet.model_validate(artifact.get("preRerankCandidateSet"))
    if not 1 <= len(pool.candidates) <= 30:
        raise ValueError("M4 frozen candidate pool must contain 1..30 merchants.")
    pool_shop_ids = [item.shop_id for item in pool.candidates]
    pool_external_ids = [item.external_id for item in pool.candidates]
    if (
        any(not item for item in pool_external_ids)
        or len(pool_shop_ids) != len(set(pool_shop_ids))
        or len(pool_external_ids) != len(set(pool_external_ids))
    ):
        raise ValueError("M4 frozen candidate pool identities are invalid.")
    rerank_query = artifact.get("rerankQuery")
    if not isinstance(rerank_query, str) or not rerank_query.strip():
        raise ValueError("M4 frozen artifact has no reranker query.")
    rerank_candidates = tuple(
        RerankCandidate.model_validate(item) for item in (artifact.get("rerankCandidates") or [])
    )
    if (
        len(rerank_candidates) != len(pool.candidates)
        or [item.original_rank for item in rerank_candidates] != list(range(1, len(rerank_candidates) + 1))
        or [item.shop_id for item in rerank_candidates] != pool_shop_ids
    ):
        raise ValueError("M4 frozen reranker inputs do not exactly align with the pool.")
    expected_pre_metadata = _pre_rerank_metadata(
        pool,
        rerank_query=rerank_query,
        rerank_candidates=rerank_candidates,
    )
    if artifact.get("preRerankMetadata") != expected_pre_metadata:
        raise ValueError("M4 frozen pre-rerank metadata/input fingerprint is invalid.")

    evidence = EvidencePack.model_validate(artifact.get("evidencePack"))
    if [item.shop_id for item in evidence.evidence] != pool_shop_ids:
        raise ValueError("M4 frozen evidence must cover the complete pool in pool order.")
    pool_by_shop_id = {item.shop_id: item for item in pool.candidates}
    citation_ids: list[str] = []
    for evidence_item in evidence.evidence:
        candidate = pool_by_shop_id[evidence_item.shop_id]
        for citation in evidence_item.citations:
            if citation.shop_id != evidence_item.shop_id:
                raise ValueError("M4 frozen citation owner differs from its evidence merchant.")
            if citation.shop_external_id != candidate.external_id:
                raise ValueError("M4 frozen citation external ID differs from its candidate merchant.")
            if citation.security_test:
                raise ValueError("M4 frozen evidence contains a security-test citation.")
            if not citation.citation_id or not citation.source_id:
                raise ValueError("M4 frozen evidence contains a citation without a stable identity.")
            citation_ids.append(citation.citation_id)
    if len(citation_ids) != len(set(citation_ids)):
        raise ValueError("M4 frozen evidence contains duplicate citation identities.")
    final = CandidateSet.model_validate(artifact.get("controlFinalCandidateSet"))
    final_shop_ids = [item.shop_id for item in final.candidates]
    final_ids = [item.external_id for item in final.candidates]
    if (
        len(final_ids) != min(10, len(pool.candidates))
        or any(not item for item in final_ids)
        or len(final_shop_ids) != len(set(final_shop_ids))
        or len(final_ids) != len(set(final_ids))
        or not set(final_shop_ids) <= set(pool_shop_ids)
        or not set(final_ids) <= set(pool_external_ids)
        or any(
            item.model_dump(mode="json", by_alias=True)
            != pool_by_shop_id[item.shop_id].model_dump(mode="json", by_alias=True)
            for item in final.candidates
        )
    ):
        raise ValueError("M4 frozen heuristic final ranking is invalid.")

    expected_hashes = _component_hashes(artifact)
    if any(artifact.get(field) != digest for field, digest in expected_hashes.items()):
        raise ValueError("M4 frozen candidate artifact component SHA is invalid.")
    envelope = dict(artifact)
    observed_sha = envelope.pop("artifactSha256", None)
    if observed_sha != sha256_json(envelope):
        raise ValueError("M4 frozen candidate artifact envelope SHA is invalid.")
    return artifact


def frozen_replay_contract_rows(
    cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_requests: set[tuple[str, str]] = set()
    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen_ids:
            raise ValueError("M4 replay suite contains a missing/duplicate case ID.")
        seen_ids.add(case_id)
        constraints = UserConstraints.model_validate(case.get("constraints"))
        artifact = validate_frozen_case_artifact(
            _case_artifact(case),
            expected_case_id=case_id,
            expected_constraints=constraints,
        )
        request_key = (
            str(artifact["constraintsSha256"]),
            str(artifact["ruleQuerySha256"]),
        )
        if request_key in seen_requests:
            raise ValueError("M4 replay suite contains a duplicate constraints/rule request.")
        seen_requests.add(request_key)
        rows.append(
            {
                "id": case_id,
                "constraintsSha256": request_key[0],
                "ruleQuerySha256": request_key[1],
                "semanticPlanSha256": str(artifact["rewritePlan"]["semanticPlanSha256"]),
                "rewriteCaptureEnvelopeSha256": str(artifact["rewritePlan"]["captureEnvelopeSha256"]),
                "candidatePoolSha256": str(artifact["candidatePoolSha256"]),
                "rerankerInputSha256": str(artifact["rerankerInputSha256"]),
                "evidencePackSha256": str(artifact["evidencePackSha256"]),
                "controlOrderSha256": str(artifact["controlOrderSha256"]),
                "artifactSha256": str(artifact["artifactSha256"]),
            }
        )
    if not rows:
        raise ValueError("M4 frozen replay requires at least one case.")
    return rows


def frozen_replay_contract_sha256(cases: Sequence[Mapping[str, Any]]) -> str:
    return sha256_json(frozen_replay_contract_rows(cases))


def replay_metadata_for_case(case: Mapping[str, Any]) -> dict[str, Any]:
    artifact = validate_frozen_case_artifact(
        _case_artifact(case),
        expected_case_id=str(case.get("id") or ""),
        expected_constraints=UserConstraints.model_validate(case.get("constraints")),
    )
    rewrite = validate_frozen_rewrite_artifact(artifact["rewritePlan"])
    control_final = CandidateSet.model_validate(artifact["controlFinalCandidateSet"])
    return {
        "version": M4_REPLAY_VERSION,
        "status": "frozen-replay",
        "performanceScope": M4_PERFORMANCE_SCOPE,
        "caseId": artifact["caseId"],
        "constraintsSha256": artifact["constraintsSha256"],
        "ruleQuerySha256": artifact["ruleQuerySha256"],
        "semanticPlanSha256": artifact["rewritePlan"]["semanticPlanSha256"],
        "rewriteCaptureEnvelopeSha256": artifact["rewritePlan"]["captureEnvelopeSha256"],
        "candidatePoolSha256": artifact["candidatePoolSha256"],
        "rerankerInputSha256": artifact["rerankerInputSha256"],
        "evidencePackSha256": artifact["evidencePackSha256"],
        "controlOrderSha256": artifact["controlOrderSha256"],
        "controlFinalExternalIds": [item.external_id for item in control_final.candidates],
        "artifactSha256": artifact["artifactSha256"],
        "requestedProvider": rewrite.trace.requested_provider,
        "requestedModel": rewrite.trace.requested_model,
        "effectiveProvider": "frozen-replay",
        "effectiveModel": "frozen-replay",
        "promptVersion": rewrite.trace.prompt_version,
        "logicalInvocations": 0,
        "networkRequests": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "estimatedCostUsd": 0.0,
        "fallback": False,
    }


def _formal_replay_metadata(artifact: Mapping[str, Any]) -> dict[str, Any]:
    rewrite = validate_frozen_rewrite_artifact(artifact["rewritePlan"])
    pool = CandidateSet.model_validate(artifact["preRerankCandidateSet"])
    base = _deep_copy(pool.retrieval_metadata)
    zero_counts = {
        "globalQueryVariantPartialFailureIds": [],
        "globalQueryVariantTimedOutIds": [],
        "globalQueryVariantFailedIds": [],
        "structuredFallback": False,
        "globalFallback": False,
        "candidateRankingFallback": False,
        "candidateRankingFallbackReason": None,
        "identityConflicts": 0,
        "identityConflictShopIds": [],
        "identityMismatches": 0,
        "hydrationFailed": 0,
        "globalDenseRejectedPoints": 0,
        "globalSparseRejectedPoints": 0,
    }
    base.update(zero_counts)
    base.update(_deep_copy(artifact["preRerankMetadata"]))
    for field in (
        "globalDenseLatencyMs",
        "globalSparseLatencyMs",
        "globalEmbeddingLatencyMs",
        "queryRewriteLatencyMs",
    ):
        base[field] = 0.0
    base.update(
        {
            "globalRetrievalEnabled": True,
            "candidateDiscoveryMode": "m4-frozen-candidate-replay",
            "candidatePool": len(pool.candidates),
            "finalCandidates": 0,
            "queryRewriteEnabled": True,
            "queryRewriteExecutionMode": "frozen-replay",
            "queryRewriteLogicalInvocations": 0,
            "queryRewriteProvider": rewrite.trace.requested_provider,
            "queryRewriteEffectiveProvider": "frozen-replay",
            "queryRewriteModel": rewrite.trace.requested_model,
            "queryRewriteEffectiveModel": "frozen-replay",
            "queryRewritePromptVersion": rewrite.trace.prompt_version,
            "queryRewriteLanguage": rewrite.language,
            "queryRewriteCount": len(rewrite.rewrites),
            "queryRewriteNetworkRequests": 0,
            "queryRewriteInputTokens": 0,
            "queryRewriteOutputTokens": 0,
            "queryRewriteCacheHit": False,
            "queryRewriteFallback": False,
            "queryRewriteFallbackReason": None,
            "queryRewriteLatencyMs": 0.0,
            "queryRewriteSemanticTags": list(rewrite.semantic_tags),
            "queryRewriteExcludedTags": list(rewrite.excluded_tags),
            "m4PerformanceScope": M4_PERFORMANCE_SCOPE,
            "m4ReplayArtifactSha256": artifact["artifactSha256"],
        }
    )
    stage_latency = dict(base.get("candidateDiscoveryLatencyMs") or {})
    for field in (
        "structured",
        "global",
        "queryRewrite",
        "aggregation",
        "hydration",
        "fusion",
        "candidateRanking",
        "total",
    ):
        stage_latency[field] = 0.0
    base["candidateDiscoveryLatencyMs"] = stage_latency
    return base


def _component_hashes(artifact: Mapping[str, Any]) -> dict[str, str]:
    final = CandidateSet.model_validate(artifact["controlFinalCandidateSet"])
    return {
        "candidatePoolSha256": sha256_json(artifact["preRerankCandidateSet"]),
        "rerankerInputSha256": sha256_json(
            {
                "query": artifact["rerankQuery"],
                "candidates": artifact["rerankCandidates"],
                "metadata": artifact["preRerankMetadata"],
            }
        ),
        "evidencePackSha256": sha256_json(artifact["evidencePack"]),
        "controlOrderSha256": sha256_json([item.external_id for item in final.candidates]),
    }


def _case_artifact(case: Mapping[str, Any]) -> dict[str, Any]:
    metadata = case.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("M4 schema-v5 case has no metadata object.")
    artifact = metadata.get("frozenM4ReplayArtifact")
    if not isinstance(artifact, Mapping):
        raise ValueError("M4 schema-v5 case has no frozen replay artifact.")
    return dict(artifact)


def _validate_plan_request(
    plan: QueryRewritePlan,
    *,
    constraints: UserConstraints,
    rule_query: str,
) -> None:
    if plan.original.text != constraints.query:
        raise ValueError("M4 rewrite plan changed the original query.")
    if plan.hard_constraints != HardConstraintEcho.from_constraints(constraints):
        raise ValueError("M4 rewrite plan changed hard constraints.")
    normalized_rule = rule_query.strip()[:MAX_QUERY_CHARACTERS].rstrip()
    if plan.rule.text != normalized_rule:
        raise ValueError("M4 rewrite plan changed the deterministic rule query.")
    if plan.trace.fallback_used:
        raise ValueError("M4 capture may not freeze a rewrite fallback.")


def _request_key(constraints: UserConstraints, rule_query: str) -> tuple[str, str]:
    return (
        sha256_json(user_constraints_payload(constraints)),
        sha256_json(rule_query),
    )


def _deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value))
