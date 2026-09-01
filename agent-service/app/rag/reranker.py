from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol, TypeAlias

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models import EvidenceCitation, ShopCandidate
from app.rag.display_text import clean_display_text

DEFAULT_RERANKER_VERSION = "m4-cross-encoder-v1"
MAX_RERANK_CANDIDATES = 100
MAX_RERANK_QUERY_CHARACTERS = 4_000
MAX_RERANK_TEXT_CHARACTERS = 12_000
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class RerankStatus(StrEnum):
    APPLIED = "applied"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


class RerankEvidence(_FrozenModel):
    """One bounded evidence excerpt eligible for an external reranker."""

    rank: int = Field(ge=1)
    shop_id: int = Field(gt=0)
    document_id: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=300)
    root_id: int | None = Field(default=None, gt=0)
    content_type: str = Field(min_length=1, max_length=80)
    document_kind: str = Field(default="evidence", min_length=1, max_length=80)
    excerpt: str = Field(min_length=1, max_length=10_000)
    untrusted_content: bool = True
    source_type: str = Field(default="SYNTHETIC", min_length=1, max_length=80)
    source_name: str | None = Field(default=None, max_length=300)
    synthetic: bool = True
    security_test: bool = False

    @field_validator(
        "document_id",
        "source_id",
        "content_type",
        "document_kind",
        "excerpt",
        "source_type",
        "source_name",
    )
    @classmethod
    def _strip_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Rerank evidence strings cannot be blank.")
        return stripped

    @classmethod
    def from_citation(cls, citation: EvidenceCitation, *, rank: int) -> RerankEvidence:
        return cls(
            rank=rank,
            shop_id=citation.shop_id,
            document_id=citation.citation_id,
            source_id=citation.source_id,
            root_id=citation.root_id,
            content_type=citation.content_type,
            document_kind=citation.document_kind,
            excerpt=citation.excerpt,
            untrusted_content=citation.untrusted_content,
            source_type=citation.source_type,
            source_name=citation.source_name,
            synthetic=citation.synthetic,
            security_test=citation.security_test,
        )


class RerankEvidenceProvenance(_FrozenModel):
    document_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    root_id: int | None = Field(default=None, gt=0)
    content_type: str = Field(min_length=1)
    document_kind: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_name: str | None = None
    synthetic: bool
    untrusted_content: bool


class MerchantRerankText(_FrozenModel):
    shop_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=MAX_RERANK_TEXT_CHARACTERS)
    evidence_provenance: tuple[RerankEvidenceProvenance, ...] = ()
    truncated: bool = False
    input_sha256: str = Field(pattern=_SHA256_PATTERN)

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(item.document_id for item in self.evidence_provenance)

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(item.source_id for item in self.evidence_provenance)

    @property
    def root_ids(self) -> tuple[int, ...]:
        return tuple(item.root_id for item in self.evidence_provenance if item.root_id is not None)


class RerankCandidate(_FrozenModel):
    shop_id: int = Field(gt=0)
    original_rank: int = Field(ge=1, le=MAX_RERANK_CANDIDATES)
    rerank_text: MerchantRerankText

    @model_validator(mode="after")
    def _matching_shop(self) -> RerankCandidate:
        if self.rerank_text.shop_id != self.shop_id:
            raise ValueError("Rerank candidate and text shop IDs must match.")
        return self


class RerankScore(_FrozenModel):
    shop_id: int = Field(gt=0)
    original_rank: int = Field(ge=1)
    rank: int = Field(ge=1)
    score: float | None = None
    input_sha256: str = Field(pattern=_SHA256_PATTERN)


class RerankTrace(_FrozenModel):
    status: RerankStatus
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    candidate_count: int = Field(ge=0, le=MAX_RERANK_CANDIDATES)
    input_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    latency_ms: float = Field(default=0.0, ge=0)
    network_requests: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    retries: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    fallback_used: bool = False
    fallback_reason: str | None = Field(default=None, max_length=80)
    cache_hit: bool = False
    circuit_state: CircuitState = CircuitState.CLOSED

    @model_validator(mode="after")
    def _consistent_fallback(self) -> RerankTrace:
        if self.status is RerankStatus.UNAVAILABLE and not self.fallback_used:
            raise ValueError("Unavailable reranking must expose a fallback signal.")
        if self.fallback_used != (self.fallback_reason is not None):
            raise ValueError("fallback_used and fallback_reason must agree.")
        return self

    def as_metadata(self) -> dict[str, str | int | float | bool | None]:
        """Return the stable CandidateSet metadata names consumed by M4 Eval."""

        return {
            "rerankerStatus": self.status.value,
            "rerankerProvider": self.provider,
            "rerankerModel": self.model,
            "rerankerVersion": self.version,
            "rerankerCandidates": self.candidate_count,
            "rerankerInputFingerprint": self.input_fingerprint,
            "rerankerLatencyMs": round(self.latency_ms, 3),
            "rerankerNetworkRequests": self.network_requests,
            "rerankerTokens": self.tokens,
            "rerankerEstimatedCostUsd": self.estimated_cost_usd,
            "rerankerRetries": self.retries,
            "rerankerFailures": self.failures,
            "rerankerFallback": self.fallback_used,
            "rerankerFallbackReason": self.fallback_reason,
            "rerankerCacheHit": self.cache_hit,
            "rerankerCircuitState": self.circuit_state.value,
        }


class RerankResult(_FrozenModel):
    scores: tuple[RerankScore, ...]
    trace: RerankTrace

    @model_validator(mode="after")
    def _complete_batch(self) -> RerankResult:
        if len(self.scores) != self.trace.candidate_count:
            raise ValueError("Rerank trace candidate count does not match scores.")
        shop_ids = [item.shop_id for item in self.scores]
        ranks = [item.rank for item in self.scores]
        original_ranks = [item.original_rank for item in self.scores]
        if len(shop_ids) != len(set(shop_ids)):
            raise ValueError("Rerank results cannot contain duplicate shops.")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("Rerank results must be ordered with contiguous ranks.")
        if len(original_ranks) != len(set(original_ranks)):
            raise ValueError("Rerank results cannot contain duplicate original ranks.")
        return self

    @property
    def ordered_shop_ids(self) -> tuple[int, ...]:
        return tuple(item.shop_id for item in self.scores)

    @property
    def score_by_shop(self) -> dict[int, float | None]:
        return {item.shop_id: item.score for item in self.scores}


@dataclass(frozen=True)
class RerankUsage:
    network_requests: int = 0
    tokens: int = 0
    success_count: int = 0
    failure_count: int = 0
    cache_hits: int = 0
    fallback_count: int = 0
    retries: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)

    def delta(self, previous: RerankUsage) -> RerankUsage:
        return RerankUsage(
            **{field: getattr(self, field) - getattr(previous, field) for field in self.__dataclass_fields__}
        )


class CandidateReranker(Protocol):
    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
    ) -> RerankResult: ...

    def usage_snapshot(self) -> RerankUsage: ...

    def reset(self) -> None: ...

    def clear_cache(self) -> None: ...

    async def aclose(self) -> None: ...


class RerankerConfigurationError(RuntimeError):
    """Fail-closed error for credentials or provider authorization."""


class _ProviderScoreError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class MerchantRerankTextBuilder:
    """Create deterministic, provenance-explicit merchant documents."""

    def __init__(
        self,
        *,
        max_characters: int = 4_000,
        max_evidence: int = 2,
        max_evidence_characters: int = 800,
    ) -> None:
        if isinstance(max_characters, bool) or not 256 <= max_characters <= MAX_RERANK_TEXT_CHARACTERS:
            raise ValueError("Rerank text max_characters must be between 256 and 12000.")
        if isinstance(max_evidence, bool) or not 0 <= max_evidence <= 10:
            raise ValueError("Rerank text max_evidence must be between 0 and 10.")
        if (
            isinstance(max_evidence_characters, bool)
            or not 32 <= max_evidence_characters <= 5_000
        ):
            raise ValueError("Evidence max characters must be between 32 and 5000.")
        self._max_characters = max_characters
        self._max_evidence = max_evidence
        self._max_evidence_characters = max_evidence_characters

    def build(
        self,
        candidate: ShopCandidate,
        evidence: Sequence[RerankEvidence | EvidenceCitation] = (),
    ) -> MerchantRerankText:
        prepared = tuple(
            item
            if isinstance(item, RerankEvidence)
            else RerankEvidence.from_citation(item, rank=rank)
            for rank, item in enumerate(evidence, start=1)
        )
        if any(item.shop_id != candidate.shop_id for item in prepared):
            raise ValueError("Rerank evidence cannot cross merchant boundaries.")
        retained = self._retain_evidence(prepared)

        lines = [
            f"name: {_clean(candidate.name)}",
            f"category: {_clean(candidate.category)}",
            f"neighborhood: {_clean(candidate.neighborhood)}",
        ]
        if candidate.subcategory:
            lines.append(f"subcategory: {_clean(candidate.subcategory)}")
        if candidate.borough:
            lines.append(f"borough: {_clean(candidate.borough)}")
        if candidate.avg_price_cents is not None:
            lines.append(f"average_price_cents: {candidate.avg_price_cents}")
        if candidate.price_range_text:
            lines.append(f"price_range: {_clean(candidate.price_range_text)}")
        if candidate.score is not None:
            lines.append(f"rating: {_format_number(candidate.score)}")
        if candidate.rating_count is not None:
            lines.append(f"rating_count: {candidate.rating_count}")
        if candidate.distance_meters is not None:
            lines.append(f"distance_meters: {candidate.distance_meters}")
        tags = sorted({_clean(tag) for tag in candidate.tags if _clean(tag)})
        if tags:
            lines.append(f"canonical_tags: {', '.join(tags)}")

        provenance: list[RerankEvidenceProvenance] = []
        excerpt_truncated = False
        for index, item in enumerate(retained, start=1):
            reference = RerankEvidenceProvenance(
                document_id=item.document_id,
                source_id=item.source_id,
                root_id=item.root_id,
                content_type=item.content_type,
                document_kind=item.document_kind,
                source_type=item.source_type,
                source_name=item.source_name,
                synthetic=item.synthetic,
                untrusted_content=item.untrusted_content,
            )
            provenance.append(reference)
            source_bits = [
                f"document_id={_clean(item.document_id)}",
                f"source_id={_clean(item.source_id)}",
                f"content_type={_clean(item.content_type)}",
                f"source_type={_clean(item.source_type)}",
                f"synthetic={str(item.synthetic).lower()}",
                f"untrusted={str(item.untrusted_content).lower()}",
            ]
            if item.root_id is not None:
                source_bits.append(f"root_id={item.root_id}")
            if item.source_name:
                source_bits.append(f"source_name={_clean(item.source_name)}")
            lines.append(f"evidence_{index}_provenance: {'; '.join(source_bits)}")
            excerpt = _clean(clean_display_text(item.excerpt))
            clipped, was_clipped = _clip(excerpt, self._max_evidence_characters)
            excerpt_truncated = excerpt_truncated or was_clipped
            if clipped:
                lines.append(f"evidence_{index}: {clipped}")

        hours = _business_hours(candidate)
        if hours:
            lines.append(f"business_hours: {hours}")
        merchant_source = _merchant_source(candidate)
        if merchant_source:
            lines.append(f"merchant_provenance: {merchant_source}")

        complete_text = "\n".join(line for line in lines if not line.endswith(": "))
        text, document_truncated = _clip(complete_text, self._max_characters)
        evidence_tuple = tuple(provenance)
        fingerprint = _sha256_json(
            {
                "shopId": candidate.shop_id,
                "text": text,
                "evidenceProvenance": [
                    item.model_dump(mode="json") for item in evidence_tuple
                ],
            }
        )
        return MerchantRerankText(
            shop_id=candidate.shop_id,
            text=text,
            evidence_provenance=evidence_tuple,
            truncated=excerpt_truncated or document_truncated,
            input_sha256=fingerprint,
        )

    def _retain_evidence(self, evidence: Sequence[RerankEvidence]) -> tuple[RerankEvidence, ...]:
        if self._max_evidence == 0:
            return ()
        ordered = sorted(
            (item for item in evidence if not item.security_test),
            key=lambda item: (
                item.rank,
                item.root_id if item.root_id is not None else 2**63 - 1,
                item.document_id,
                item.source_id,
            ),
        )
        retained: list[RerankEvidence] = []
        roots: set[int] = set()
        documents: set[str] = set()
        for item in ordered:
            if item.document_id in documents:
                continue
            if item.root_id is not None and item.root_id in roots:
                continue
            documents.add(item.document_id)
            if item.root_id is not None:
                roots.add(item.root_id)
            retained.append(item)
            if len(retained) >= self._max_evidence:
                break
        return tuple(retained)


def rerank_input_fingerprint(
    query: str,
    candidates: Sequence[RerankCandidate],
) -> str:
    normalized_query = _validated_query(query)
    ordered = _validated_candidates(candidates)
    return _sha256_json(
        {
            "query": normalized_query,
            "candidates": [
                {
                    "shopId": item.shop_id,
                    "originalRank": item.original_rank,
                    "inputSha256": item.rerank_text.input_sha256,
                }
                for item in ordered
            ],
        }
    )


class DisabledReranker:
    def __init__(self, *, version: str = DEFAULT_RERANKER_VERSION) -> None:
        self._version = _required(version, "Reranker version")

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
    ) -> RerankResult:
        started = time.perf_counter()
        ordered = _validated_candidates(candidates)
        fingerprint = rerank_input_fingerprint(query, ordered)
        return _original_order_result(
            ordered,
            trace=RerankTrace(
                status=RerankStatus.DISABLED,
                provider="disabled",
                model="disabled",
                version=self._version,
                candidate_count=len(ordered),
                input_fingerprint=fingerprint,
                latency_ms=_elapsed_ms(started),
            ),
        )

    def usage_snapshot(self) -> RerankUsage:
        return RerankUsage()

    def reset(self) -> None:
        return None

    def clear_cache(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


HeuristicOutput: TypeAlias = Sequence[float] | Mapping[int, float]
HeuristicScorer: TypeAlias = Callable[
    [str, tuple[RerankCandidate, ...]],
    HeuristicOutput | Awaitable[HeuristicOutput],
]


class HeuristicRerankerAdapter:
    """Wrap a local batch scorer without coupling the core to legacy ranking."""

    def __init__(
        self,
        scorer: HeuristicScorer,
        *,
        model: str = "heuristic-multi-signal",
        version: str = DEFAULT_RERANKER_VERSION,
    ) -> None:
        self._scorer = scorer
        self._model = _required(model, "Heuristic model")
        self._version = _required(version, "Reranker version")
        self._usage = RerankUsage()

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
    ) -> RerankResult:
        started = time.perf_counter()
        normalized_query = _validated_query(query)
        ordered = _validated_candidates(candidates)
        fingerprint = rerank_input_fingerprint(normalized_query, ordered)
        try:
            output = self._scorer(normalized_query, ordered)
            if inspect.isawaitable(output):
                output = await output
            scores = _normalize_heuristic_scores(output, ordered)
        except asyncio.CancelledError:
            raise
        except Exception:
            latency = _elapsed_ms(started)
            self._increment_usage(failure_count=1, fallback_count=1, latency_ms=latency)
            return _original_order_result(
                ordered,
                trace=RerankTrace(
                    status=RerankStatus.UNAVAILABLE,
                    provider="heuristic",
                    model=self._model,
                    version=self._version,
                    candidate_count=len(ordered),
                    input_fingerprint=fingerprint,
                    latency_ms=latency,
                    failures=1,
                    fallback_used=True,
                    fallback_reason="heuristic-error",
                ),
            )
        latency = _elapsed_ms(started)
        self._increment_usage(success_count=1, latency_ms=latency)
        return _scored_result(
            ordered,
            scores,
            trace=RerankTrace(
                status=RerankStatus.APPLIED,
                provider="heuristic",
                model=self._model,
                version=self._version,
                candidate_count=len(ordered),
                input_fingerprint=fingerprint,
                latency_ms=latency,
            ),
        )

    def usage_snapshot(self) -> RerankUsage:
        return self._usage

    def reset(self) -> None:
        self._usage = RerankUsage()

    def clear_cache(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def _increment_usage(self, **updates: int | float) -> None:
        self._usage = _updated_usage(self._usage, updates)


class HttpCrossEncoderReranker:
    """One-request Cross-Encoder batch with bounded retries and safe fallback."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        instruct: str,
        version: str = DEFAULT_RERANKER_VERSION,
        endpoint_path: str = "/reranks",
        timeout_seconds: float = 8.0,
        max_concurrency: int = 2,
        max_candidates: int = 30,
        max_retries: int = 0,
        retry_backoff_seconds: float = 0.05,
        cache_size: int = 512,
        cache_ttl_seconds: float = 900.0,
        circuit_failure_threshold: int = 3,
        circuit_recovery_seconds: float = 30.0,
        input_cost_per_million_tokens: float = 0.0,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._provider = _required(provider, "Reranker provider")
        self._base_url = _required(base_url, "Reranker base URL").rstrip("/")
        self._api_key = api_key
        self._model = _required(model, "Reranker model")
        self._instruct = _required(instruct, "Reranker instruction")
        if len(self._instruct) > 2_000:
            raise ValueError("Reranker instruction cannot exceed 2000 characters.")
        self._version = _required(version, "Reranker version")
        if not endpoint_path.startswith("/") or endpoint_path == "/":
            raise ValueError("Reranker endpoint_path must be an absolute URL path.")
        if timeout_seconds <= 0:
            raise ValueError("Reranker timeout must be positive.")
        if isinstance(max_concurrency, bool) or max_concurrency < 1:
            raise ValueError("Reranker max concurrency must be positive.")
        if isinstance(max_candidates, bool) or not 1 <= max_candidates <= MAX_RERANK_CANDIDATES:
            raise ValueError("Reranker max candidates must be between 1 and 100.")
        if isinstance(max_retries, bool) or not 0 <= max_retries <= 2:
            raise ValueError("Reranker max retries must be between 0 and 2.")
        if retry_backoff_seconds < 0:
            raise ValueError("Reranker retry backoff cannot be negative.")
        if cache_size < 0 or cache_ttl_seconds < 0:
            raise ValueError("Reranker cache bounds cannot be negative.")
        if isinstance(circuit_failure_threshold, bool) or circuit_failure_threshold < 1:
            raise ValueError("Circuit failure threshold must be positive.")
        if circuit_recovery_seconds <= 0:
            raise ValueError("Circuit recovery must be positive.")
        if not math.isfinite(input_cost_per_million_tokens) or input_cost_per_million_tokens < 0:
            raise ValueError("Reranker token price must be finite and non-negative.")
        self._endpoint_path = endpoint_path
        self._timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_candidates = max_candidates
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._cache_size = cache_size
        self._cache_ttl_seconds = cache_ttl_seconds
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_recovery_seconds = circuit_recovery_seconds
        self._input_cost_per_million_tokens = input_cost_per_million_tokens
        self._clock = clock
        self._sleeper = sleeper
        self._cache: OrderedDict[str, tuple[float, tuple[float, ...]]] = OrderedDict()
        self._usage = RerankUsage()
        self._circuit_state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._circuit_opened_at = 0.0
        self._half_open_probe = False
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    @property
    def circuit_state(self) -> CircuitState:
        return self._circuit_state

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
    ) -> RerankResult:
        started = time.perf_counter()
        normalized_query = _validated_query(query)
        ordered = _validated_candidates(candidates)
        if len(ordered) > self._max_candidates:
            raise ValueError(
                f"Reranker received {len(ordered)} candidates; configured maximum is {self._max_candidates}."
            )
        fingerprint = rerank_input_fingerprint(normalized_query, ordered)
        if not ordered:
            return _scored_result(
                ordered,
                (),
                trace=self._trace(
                    status=RerankStatus.APPLIED,
                    candidate_count=0,
                    fingerprint=fingerprint,
                    latency_ms=_elapsed_ms(started),
                ),
            )

        cached = self._cache_get(fingerprint)
        if cached is not None:
            latency = _elapsed_ms(started)
            self._increment_usage(cache_hits=1, success_count=1, latency_ms=latency)
            return _scored_result(
                ordered,
                cached,
                trace=self._trace(
                    status=RerankStatus.APPLIED,
                    candidate_count=len(ordered),
                    fingerprint=fingerprint,
                    latency_ms=latency,
                    cache_hit=True,
                ),
            )
        if not self._api_key.strip():
            return self._fallback(
                ordered,
                fingerprint=fingerprint,
                reason="missing-api-key",
                started=started,
                failures=1,
            )
        if not self._acquire_circuit_permission():
            return self._fallback(
                ordered,
                fingerprint=fingerprint,
                reason="circuit-open",
                started=started,
                failures=1,
            )

        network_requests = 0
        retries = 0
        failures = 0
        tokens = 0
        last_reason = "provider-error"
        for attempt in range(self._max_retries + 1):
            request_started = False
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    async with self._semaphore:
                        request_started = True
                        network_requests += 1
                        response = await self._client.post(
                            f"{self._base_url}{self._endpoint_path}",
                            headers={"Authorization": f"Bearer {self._api_key}"},
                            json={
                                "model": self._model,
                                "instruct": self._instruct,
                                "query": normalized_query,
                                "documents": [item.rerank_text.text for item in ordered],
                                "top_n": len(ordered),
                            },
                        )
            except asyncio.CancelledError:
                self._release_half_open_probe()
                raise
            except TimeoutError:
                failures += 1
                if request_started:
                    last_reason = "timeout"
                    self._record_circuit_failure()
                else:
                    last_reason = "queue-timeout"
                    self._release_half_open_probe()
                    break
            except httpx.RequestError:
                last_reason = "network-error"
                failures += 1
                self._record_circuit_failure()
            else:
                if response.status_code in (401, 403):
                    self._release_half_open_probe()
                    latency = _elapsed_ms(started)
                    self._increment_usage(
                        network_requests=network_requests,
                        failure_count=failures + 1,
                        retries=retries,
                        latency_ms=latency,
                    )
                    raise RerankerConfigurationError("Reranker provider authorization failed.")
                if response.status_code == 429:
                    last_reason = "rate-limited"
                    failures += 1
                    self._record_circuit_failure()
                elif 500 <= response.status_code <= 599:
                    last_reason = "provider-http-error"
                    failures += 1
                    self._record_circuit_failure()
                elif response.is_error:
                    last_reason = "provider-http-error"
                    failures += 1
                    self._record_circuit_failure()
                    break
                else:
                    try:
                        payload = response.json()
                        tokens = _provider_tokens(payload)
                        scores = _provider_scores(
                            payload,
                            expected_count=len(ordered),
                            expected_model=self._model,
                        )
                    except _ProviderScoreError as exc:
                        last_reason = exc.reason
                        failures += 1
                        self._record_circuit_failure()
                        break
                    except (TypeError, ValueError):
                        last_reason = "invalid-response"
                        failures += 1
                        self._record_circuit_failure()
                        break
                    self._record_circuit_success()
                    self._cache_put(fingerprint, scores)
                    latency = _elapsed_ms(started)
                    estimated_cost = _estimated_cost(tokens, self._input_cost_per_million_tokens)
                    self._increment_usage(
                        network_requests=network_requests,
                        tokens=tokens,
                        success_count=1,
                        failure_count=failures,
                        retries=retries,
                        estimated_cost_usd=estimated_cost,
                        latency_ms=latency,
                    )
                    return _scored_result(
                        ordered,
                        scores,
                        trace=self._trace(
                            status=RerankStatus.APPLIED,
                            candidate_count=len(ordered),
                            fingerprint=fingerprint,
                            latency_ms=latency,
                            network_requests=network_requests,
                            tokens=tokens,
                            estimated_cost_usd=estimated_cost,
                            retries=retries,
                            failures=failures,
                        ),
                    )

            if attempt < self._max_retries:
                retries += 1
                if self._retry_backoff_seconds:
                    await self._sleeper(self._retry_backoff_seconds * (2**attempt))

        return self._fallback(
            ordered,
            fingerprint=fingerprint,
            reason=last_reason,
            started=started,
            network_requests=network_requests,
            tokens=tokens,
            retries=retries,
            failures=max(1, failures),
        )

    def usage_snapshot(self) -> RerankUsage:
        return self._usage

    def reset(self) -> None:
        self._usage = RerankUsage()

    def clear_cache(self) -> None:
        self._cache.clear()

    def reset_circuit(self) -> None:
        self._circuit_state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._circuit_opened_at = 0.0
        self._half_open_probe = False

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _trace(
        self,
        *,
        status: RerankStatus,
        candidate_count: int,
        fingerprint: str,
        latency_ms: float,
        network_requests: int = 0,
        tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        retries: int = 0,
        failures: int = 0,
        fallback_reason: str | None = None,
        cache_hit: bool = False,
    ) -> RerankTrace:
        return RerankTrace(
            status=status,
            provider=self._provider,
            model=self._model,
            version=self._version,
            candidate_count=candidate_count,
            input_fingerprint=fingerprint,
            latency_ms=latency_ms,
            network_requests=network_requests,
            tokens=tokens,
            estimated_cost_usd=estimated_cost_usd,
            retries=retries,
            failures=failures,
            fallback_used=fallback_reason is not None,
            fallback_reason=fallback_reason,
            cache_hit=cache_hit,
            circuit_state=self._circuit_state,
        )

    def _fallback(
        self,
        candidates: tuple[RerankCandidate, ...],
        *,
        fingerprint: str,
        reason: str,
        started: float,
        network_requests: int = 0,
        tokens: int = 0,
        retries: int = 0,
        failures: int = 1,
    ) -> RerankResult:
        latency = _elapsed_ms(started)
        estimated_cost = _estimated_cost(tokens, self._input_cost_per_million_tokens)
        self._increment_usage(
            network_requests=network_requests,
            tokens=tokens,
            failure_count=failures,
            fallback_count=1,
            retries=retries,
            estimated_cost_usd=estimated_cost,
            latency_ms=latency,
        )
        return _original_order_result(
            candidates,
            trace=self._trace(
                status=RerankStatus.UNAVAILABLE,
                candidate_count=len(candidates),
                fingerprint=fingerprint,
                latency_ms=latency,
                network_requests=network_requests,
                tokens=tokens,
                estimated_cost_usd=estimated_cost,
                retries=retries,
                failures=failures,
                fallback_reason=reason,
            ),
        )

    def _cache_get(self, key: str) -> tuple[float, ...] | None:
        cached = self._cache.get(key)
        if cached is None:
            return None
        expires_at, scores = cached
        if expires_at <= self._clock():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return scores

    def _cache_put(self, key: str, scores: tuple[float, ...]) -> None:
        if self._cache_size == 0 or self._cache_ttl_seconds == 0:
            return
        self._cache[key] = (self._clock() + self._cache_ttl_seconds, scores)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _acquire_circuit_permission(self) -> bool:
        if self._circuit_state is CircuitState.CLOSED:
            return True
        if self._circuit_state is CircuitState.OPEN:
            if self._clock() - self._circuit_opened_at < self._circuit_recovery_seconds:
                return False
            self._circuit_state = CircuitState.HALF_OPEN
            self._half_open_probe = True
            return True
        if self._half_open_probe:
            return False
        self._half_open_probe = True
        return True

    def _record_circuit_failure(self) -> None:
        self._half_open_probe = False
        self._consecutive_failures += 1
        if (
            self._circuit_state is CircuitState.HALF_OPEN
            or self._consecutive_failures >= self._circuit_failure_threshold
        ):
            self._circuit_state = CircuitState.OPEN
            self._circuit_opened_at = self._clock()

    def _record_circuit_success(self) -> None:
        self.reset_circuit()

    def _release_half_open_probe(self) -> None:
        self._half_open_probe = False

    def _increment_usage(self, **updates: int | float) -> None:
        self._usage = _updated_usage(self._usage, updates)


def _provider_scores(
    payload: Any,
    *,
    expected_count: int,
    expected_model: str,
) -> tuple[float, ...]:
    if not isinstance(payload, Mapping):
        raise _ProviderScoreError("invalid-response")
    response_model = payload.get("model")
    if response_model is not None and response_model != expected_model:
        raise _ProviderScoreError("model-mismatch")
    results = payload.get("results")
    if results is None:
        output = payload.get("output")
        results = output.get("results") if isinstance(output, Mapping) else None
    if not isinstance(results, list):
        raise _ProviderScoreError("invalid-response")
    by_index: dict[int, float] = {}
    for item in results:
        if not isinstance(item, Mapping):
            raise _ProviderScoreError("invalid-response")
        index = item.get("index")
        score = item.get("relevance_score")
        if isinstance(index, bool) or not isinstance(index, int):
            raise _ProviderScoreError("invalid-response")
        if index < 0 or index >= expected_count:
            raise _ProviderScoreError("extra-score")
        if index in by_index:
            raise _ProviderScoreError("duplicate-score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise _ProviderScoreError("invalid-score")
        normalized = float(score)
        if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
            raise _ProviderScoreError("invalid-score")
        by_index[index] = normalized
    if len(by_index) != expected_count:
        raise _ProviderScoreError("missing-score")
    return tuple(by_index[index] for index in range(expected_count))


def _provider_tokens(payload: Any) -> int:
    if not isinstance(payload, Mapping):
        raise _ProviderScoreError("invalid-usage")
    usage = payload.get("usage")
    value = usage.get("total_tokens") if isinstance(usage, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _ProviderScoreError("invalid-usage")
    return value


def _normalize_heuristic_scores(
    output: HeuristicOutput,
    candidates: tuple[RerankCandidate, ...],
) -> tuple[float, ...]:
    if isinstance(output, Mapping):
        expected = {item.shop_id for item in candidates}
        actual = set(output)
        if actual != expected or any(isinstance(key, bool) or not isinstance(key, int) for key in actual):
            raise ValueError("Heuristic score mapping must exactly match candidate shop IDs.")
        values = tuple(output[item.shop_id] for item in candidates)
    else:
        if isinstance(output, (str, bytes)) or len(output) != len(candidates):
            raise ValueError("Heuristic score batch must exactly match candidates.")
        values = tuple(output)
    scores: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Heuristic scores must be numeric.")
        score = float(value)
        if not math.isfinite(score):
            raise ValueError("Heuristic scores must be finite.")
        scores.append(score)
    return tuple(scores)


def _validated_candidates(candidates: Sequence[RerankCandidate]) -> tuple[RerankCandidate, ...]:
    if isinstance(candidates, (str, bytes)):
        raise TypeError("Rerank candidates must be a sequence of typed candidates.")
    rows = tuple(candidates)
    if len(rows) > MAX_RERANK_CANDIDATES:
        raise ValueError("Rerank candidate batch cannot exceed 100.")
    if any(not isinstance(item, RerankCandidate) for item in rows):
        raise TypeError("Rerank candidates must use RerankCandidate contracts.")
    shop_ids = [item.shop_id for item in rows]
    original_ranks = [item.original_rank for item in rows]
    if len(shop_ids) != len(set(shop_ids)):
        raise ValueError("Rerank candidate batch cannot contain duplicate shops.")
    if len(original_ranks) != len(set(original_ranks)):
        raise ValueError("Rerank candidate batch cannot contain duplicate original ranks.")
    if set(original_ranks) != set(range(1, len(rows) + 1)):
        raise ValueError("Rerank candidate original ranks must be contiguous from one.")
    return tuple(sorted(rows, key=lambda item: (item.original_rank, item.shop_id)))


def _scored_result(
    candidates: tuple[RerankCandidate, ...],
    scores: Sequence[float],
    *,
    trace: RerankTrace,
) -> RerankResult:
    if len(scores) != len(candidates):
        raise ValueError("Rerank score batch must exactly match candidates.")
    ranked_indices = sorted(
        range(len(candidates)),
        key=lambda index: (-scores[index], candidates[index].original_rank, candidates[index].shop_id),
    )
    return RerankResult(
        scores=tuple(
            RerankScore(
                shop_id=candidates[index].shop_id,
                original_rank=candidates[index].original_rank,
                rank=rank,
                score=float(scores[index]),
                input_sha256=candidates[index].rerank_text.input_sha256,
            )
            for rank, index in enumerate(ranked_indices, start=1)
        ),
        trace=trace,
    )


def _original_order_result(
    candidates: tuple[RerankCandidate, ...],
    *,
    trace: RerankTrace,
) -> RerankResult:
    return RerankResult(
        scores=tuple(
            RerankScore(
                shop_id=item.shop_id,
                original_rank=item.original_rank,
                rank=rank,
                score=None,
                input_sha256=item.rerank_text.input_sha256,
            )
            for rank, item in enumerate(candidates, start=1)
        ),
        trace=trace,
    )


def _business_hours(candidate: ShopCandidate) -> str:
    values = []
    for item in sorted(
        candidate.business_hours,
        key=lambda row: (row.day_of_week, row.open_time or "", row.close_time or ""),
    ):
        if item.closed:
            values.append(f"day={item.day_of_week} closed")
        elif item.open_time and item.close_time:
            suffix = "+1d" if item.closes_next_day else ""
            values.append(f"day={item.day_of_week} {item.open_time}-{item.close_time}{suffix}")
    return "; ".join(values)


def _merchant_source(candidate: ShopCandidate) -> str:
    parts = [f"source_type={_clean(candidate.source_type)}"]
    if candidate.external_id:
        parts.append(f"external_id={_clean(candidate.external_id)}")
    if candidate.source_name:
        parts.append(f"source_name={_clean(candidate.source_name)}")
    if candidate.data_version:
        parts.append(f"data_version={_clean(candidate.data_version)}")
    synthetic_fields = sorted({_clean(item) for item in candidate.synthetic_fields if _clean(item)})
    if synthetic_fields:
        parts.append(f"synthetic_fields={','.join(synthetic_fields)}")
    return "; ".join(parts)


def _validated_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Reranker query cannot be empty.")
    normalized = query.strip()
    if len(normalized) > MAX_RERANK_QUERY_CHARACTERS:
        raise ValueError("Reranker query exceeds 4000 characters.")
    return normalized


def _required(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip()


def _clean(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.split())


def _clip(value: str, maximum: int) -> tuple[str, bool]:
    if len(value) <= maximum:
        return value, False
    clipped = value[: maximum - 1].rstrip()
    return f"{clipped}…", True


def _format_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _estimated_cost(tokens: int, price_per_million: float) -> float:
    return tokens * price_per_million / 1_000_000


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1_000)


def _updated_usage(current: RerankUsage, updates: Mapping[str, int | float]) -> RerankUsage:
    return RerankUsage(
        **{
            field: getattr(current, field) + updates.get(field, 0)
            for field in current.__dataclass_fields__
        }
    )
