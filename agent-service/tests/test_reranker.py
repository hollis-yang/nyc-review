from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.domain.models import BusinessHours, ShopCandidate
from app.rag.reranker import (
    CircuitState,
    DisabledReranker,
    HeuristicRerankerAdapter,
    HttpCrossEncoderReranker,
    MerchantRerankTextBuilder,
    RerankCandidate,
    RerankerConfigurationError,
    RerankEvidence,
    RerankStatus,
    rerank_input_fingerprint,
)

BASE_URL = "https://rerank.example.test/v1"
SECRET = "rerank-secret-must-not-leak"


def _shop(shop_id: int, name: str | None = None) -> ShopCandidate:
    return ShopCandidate(
        shop_id=shop_id,
        name=name or f"Fixture {shop_id}",
        category="Restaurants",
        subcategory="Japanese",
        borough="Queens",
        neighborhood="Flushing",
        latitude=40.759,
        longitude=-73.83,
        avg_price_cents=3_000,
        score=4.6,
        rating_count=120,
        distance_meters=850,
        price_range_text="$$",
        tags=["quiet", "date_night", "quiet"],
        source_type="NYC_OPEN_DATA",
        external_id=f"fixture:{shop_id}",
        source_name="NYC fixture",
        data_version="test-v1",
        synthetic_fields=["reviews"],
        business_hours=[
            BusinessHours(
                day_of_week=5,
                open_time="17:00:00",
                close_time="23:00:00",
            )
        ],
    )


def _evidence(
    shop_id: int,
    document_id: str,
    *,
    rank: int,
    root_id: int | None,
    excerpt: str | None = None,
    security_test: bool = False,
) -> RerankEvidence:
    return RerankEvidence(
        rank=rank,
        shop_id=shop_id,
        document_id=document_id,
        source_id=f"source:{document_id}",
        root_id=root_id,
        content_type="shop_review",
        excerpt=excerpt or f"Evidence for {document_id}",
        source_type="SYNTHETIC",
        source_name="Generated fixture",
        synthetic=True,
        security_test=security_test,
    )


def _candidates(count: int = 2) -> tuple[RerankCandidate, ...]:
    builder = MerchantRerankTextBuilder()
    return tuple(
        RerankCandidate(
            shop_id=index,
            original_rank=index,
            rerank_text=builder.build(
                _shop(index),
                [_evidence(index, f"document-{index}", rank=1, root_id=index)],
            ),
        )
        for index in range(1, count + 1)
    )


def _service(client: httpx.AsyncClient, **updates: Any) -> HttpCrossEncoderReranker:
    values: dict[str, Any] = {
        "provider": "dashscope",
        "base_url": BASE_URL,
        "api_key": SECRET,
        "model": "qwen3-rerank",
        "instruct": "Rank NYC merchants by relevance to the user's constraints.",
        "client": client,
        "input_cost_per_million_tokens": 0.5,
    }
    values.update(updates)
    return HttpCrossEncoderReranker(**values)


def _success(request: httpx.Request, scores: list[float]) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={
            "results": [
                {"index": index, "relevance_score": score}
                for index, score in enumerate(scores)
            ],
            "model": "qwen3-rerank",
            "usage": {"total_tokens": 100},
        },
    )


def test_builder_is_frozen_deterministic_and_provenance_safe():
    builder = MerchantRerankTextBuilder(
        max_characters=512,
        max_evidence=2,
        max_evidence_characters=64,
    )
    shop = _shop(7)
    evidence = [
        _evidence(7, "same-root-lower", rank=2, root_id=10),
        _evidence(7, "security-secret", rank=3, root_id=11, security_test=True),
        _evidence(7, "same-root-winner", rank=1, root_id=10, excerpt="x" * 200),
        _evidence(7, "second-root", rank=4, root_id=12),
    ]

    first = builder.build(shop, evidence)
    second = builder.build(shop, list(reversed(evidence)))

    assert first == second
    assert first.document_ids == ("same-root-winner", "second-root")
    assert first.root_ids == (10, 12)
    assert "security-secret" not in first.text
    assert "same-root-lower" not in first.text
    assert "synthetic=true" in first.text
    assert "untrusted=true" in first.text
    assert len(first.text) <= 512
    assert first.truncated
    assert len(first.input_sha256) == 64
    with pytest.raises(ValidationError, match="frozen"):
        first.text = "mutated"  # type: ignore[misc]


def test_builder_rejects_cross_merchant_evidence():
    with pytest.raises(ValueError, match="cross merchant"):
        MerchantRerankTextBuilder().build(
            _shop(1),
            [_evidence(2, "wrong-shop", rank=1, root_id=1)],
        )


def test_builder_can_disable_evidence_without_leaking_document_text():
    result = MerchantRerankTextBuilder(max_evidence=0).build(
        _shop(1),
        [_evidence(1, "excluded", rank=1, root_id=1, excerpt="private excerpt")],
    )

    assert result.evidence_provenance == ()
    assert "private excerpt" not in result.text


async def test_disabled_and_heuristic_adapters_preserve_contract():
    candidates = _candidates()
    disabled = await DisabledReranker().rerank("quiet dinner", tuple(reversed(candidates)))
    assert disabled.ordered_shop_ids == (1, 2)
    assert disabled.trace.status is RerankStatus.DISABLED
    assert all(item.score is None for item in disabled.scores)

    heuristic = HeuristicRerankerAdapter(
        lambda _query, rows: {row.shop_id: float(row.shop_id) for row in rows}
    )
    reranked = await heuristic.rerank("quiet dinner", candidates)
    assert reranked.ordered_shop_ids == (2, 1)
    assert reranked.trace.status is RerankStatus.APPLIED
    assert heuristic.usage_snapshot().success_count == 1


async def test_http_batch_success_trace_cost_and_cache_are_bounded():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success(request, [0.1, 0.9])

    candidates = _candidates()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _service(client)
        first = await service.rerank("quiet date restaurant", candidates)
        second = await service.rerank("quiet date restaurant", candidates)
        await service.aclose()
        assert not client.is_closed

    assert first.ordered_shop_ids == (2, 1)
    assert first.trace.status is RerankStatus.APPLIED
    assert first.trace.network_requests == 1
    assert first.trace.tokens == 100
    assert first.trace.estimated_cost_usd == pytest.approx(0.00005)
    assert first.trace.input_fingerprint == rerank_input_fingerprint(
        "quiet date restaurant", candidates
    )
    assert first.trace.as_metadata()["rerankerInputFingerprint"] == first.trace.input_fingerprint
    assert not first.trace.cache_hit
    assert second.ordered_shop_ids == first.ordered_shop_ids
    assert second.trace.cache_hit
    assert second.trace.network_requests == 0
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert requests[0].url == httpx.URL(f"{BASE_URL}/reranks")
    assert requests[0].headers["authorization"] == f"Bearer {SECRET}"
    assert body["top_n"] == 2
    assert body["instruct"] == "Rank NYC merchants by relevance to the user's constraints."
    assert "return_documents" not in body
    assert body["documents"] == [item.rerank_text.text for item in candidates]
    assert SECRET not in first.model_dump_json()
    usage = service.usage_snapshot()
    assert usage.network_requests == 1
    assert usage.cache_hits == 1
    assert usage.success_count == 2


@pytest.mark.parametrize(
    ("results", "reason"),
    [
        pytest.param(
            [{"index": 0, "relevance_score": 0.8}],
            "missing-score",
            id="missing",
        ),
        pytest.param(
            [
                {"index": 0, "relevance_score": 0.8},
                {"index": 0, "relevance_score": 0.7},
            ],
            "duplicate-score",
            id="duplicate",
        ),
        pytest.param(
            [
                {"index": 0, "relevance_score": 0.8},
                {"index": 2, "relevance_score": 0.7},
            ],
            "extra-score",
            id="extra",
        ),
        pytest.param(
            [
                {"index": 0, "relevance_score": math.nan},
                {"index": 1, "relevance_score": 0.7},
            ],
            "invalid-score",
            id="nan",
        ),
        pytest.param(
            [
                {"index": 0, "relevance_score": math.inf},
                {"index": 1, "relevance_score": 0.7},
            ],
            "invalid-score",
            id="infinity",
        ),
        pytest.param(
            [
                {"index": 0, "relevance_score": -0.001},
                {"index": 1, "relevance_score": 0.7},
            ],
            "invalid-score",
            id="below-zero",
        ),
        pytest.param(
            [
                {"index": 0, "relevance_score": 1.001},
                {"index": 1, "relevance_score": 0.7},
            ],
            "invalid-score",
            id="above-one",
        ),
    ],
)
async def test_http_rejects_incomplete_or_non_finite_score_batch(
    results: list[dict[str, Any]],
    reason: str,
):
    def handler(request: httpx.Request) -> httpx.Response:
        # Construct raw provider bytes so deliberately non-standard NaN/Infinity
        # values reach the contract validator instead of httpx's JSON encoder.
        return httpx.Response(
            200,
            request=request,
            content=json.dumps(
                {"results": results, "usage": {"total_tokens": 10}}
            ).encode(),
            headers={"content-type": "application/json"},
        )

    candidates = _candidates()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _service(client).rerank("quiet dinner", candidates)

    assert result.ordered_shop_ids == (1, 2)
    assert result.trace.status is RerankStatus.UNAVAILABLE
    assert result.trace.fallback_used
    assert result.trace.fallback_reason == reason
    assert result.trace.failures == 1


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param(None, id="missing"),
        pytest.param({}, id="empty"),
        pytest.param({"total_tokens": -1}, id="negative"),
        pytest.param({"total_tokens": True}, id="boolean"),
        pytest.param({"total_tokens": 1.5}, id="float"),
        pytest.param({"total_tokens": "10"}, id="string"),
    ],
)
async def test_http_requires_strict_total_tokens_and_never_caches_invalid_usage(
    usage: dict[str, Any] | None,
):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload: dict[str, Any] = {
            "results": [
                {"index": 0, "relevance_score": 0.1},
                {"index": 1, "relevance_score": 0.9},
            ]
        }
        if usage is not None:
            payload["usage"] = usage
        return httpx.Response(200, request=request, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _service(client)
        first = await service.rerank("quiet dinner", _candidates())
        second = await service.rerank("quiet dinner", _candidates())

    assert first.trace.fallback_reason == "invalid-usage"
    assert second.trace.fallback_reason == "invalid-usage"
    assert not first.trace.cache_hit
    assert not second.trace.cache_hit
    assert first.trace.tokens == 0
    assert calls == 2
    assert service.usage_snapshot().network_requests == 2


async def test_http_accepts_missing_response_model_but_rejects_mismatch():
    responses = [
        {
            "results": [
                {"index": 0, "relevance_score": 0.1},
                {"index": 1, "relevance_score": 0.9},
            ],
            "usage": {"total_tokens": 10},
        },
        {
            "model": "unexpected-reranker",
            "results": [
                {"index": 0, "relevance_score": 0.1},
                {"index": 1, "relevance_score": 0.9},
            ],
            "usage": {"total_tokens": 10},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=responses.pop(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _service(client, cache_size=0)
        without_model = await service.rerank("query one", _candidates())
        mismatched_model = await service.rerank("query two", _candidates())

    assert without_model.trace.status is RerankStatus.APPLIED
    assert without_model.ordered_shop_ids == (2, 1)
    assert mismatched_model.trace.status is RerankStatus.UNAVAILABLE
    assert mismatched_model.trace.fallback_reason == "model-mismatch"
    assert mismatched_model.ordered_shop_ids == (1, 2)


@pytest.mark.parametrize("status_code", [401, 403])
async def test_http_authorization_errors_fail_closed(status_code: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request, text="credential details")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _service(client)
        with pytest.raises(RerankerConfigurationError, match="authorization failed") as caught:
            await service.rerank("quiet dinner", _candidates())

    assert SECRET not in str(caught.value)
    assert "credential details" not in str(caught.value)
    assert service.usage_snapshot().failure_count == 1


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [(429, "rate-limited"), (500, "provider-http-error")],
)
async def test_transient_http_errors_signal_original_order_fallback(
    status_code: int,
    reason: str,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _service(client).rerank("quiet dinner", _candidates())

    assert result.ordered_shop_ids == (1, 2)
    assert result.trace.fallback_reason == reason
    assert result.trace.network_requests == 1


async def test_timeout_signals_fallback_without_cancelling_caller():
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return _success(request, [0.8, 0.7])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _service(client, timeout_seconds=0.001).rerank(
            "quiet dinner", _candidates()
        )

    assert result.trace.fallback_reason == "timeout"
    assert result.trace.network_requests == 1
    assert result.ordered_shop_ids == (1, 2)


async def test_semaphore_queue_timeout_is_not_a_provider_request_or_circuit_failure():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success(request, [0.8, 0.7])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _service(
            client,
            max_concurrency=1,
            timeout_seconds=0.001,
            circuit_failure_threshold=1,
        )
        await service._semaphore.acquire()
        try:
            result = await service.rerank("quiet dinner", _candidates())
        finally:
            service._semaphore.release()

    assert result.trace.fallback_reason == "queue-timeout"
    assert result.trace.network_requests == 0
    assert result.trace.failures == 1
    assert result.trace.circuit_state is CircuitState.CLOSED
    assert service.usage_snapshot().network_requests == 0
    assert calls == 0


async def test_retry_is_counted_and_success_remains_a_single_batch():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, request=request)
        return _success(request, [0.1, 0.9])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _service(
            client,
            max_retries=1,
            retry_backoff_seconds=0,
        ).rerank("quiet dinner", _candidates())

    assert result.ordered_shop_ids == (2, 1)
    assert result.trace.network_requests == 2
    assert result.trace.retries == 1
    assert result.trace.failures == 1


async def test_http_concurrency_limit_bounds_in_flight_batches():
    active = 0
    maximum_active = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _success(request, [0.8, 0.7])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _service(client, max_concurrency=1)
        await asyncio.gather(
            service.rerank("query one", _candidates()),
            service.rerank("query two", _candidates()),
        )

    assert maximum_active == 1


async def test_circuit_breaker_opens_and_suppresses_new_network_requests():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _service(client, circuit_failure_threshold=2)
        first = await service.rerank("query one", _candidates())
        second = await service.rerank("query two", _candidates())
        third = await service.rerank("query three", _candidates())

    assert first.trace.circuit_state is CircuitState.CLOSED
    assert second.trace.circuit_state is CircuitState.OPEN
    assert third.trace.circuit_state is CircuitState.OPEN
    assert third.trace.fallback_reason == "circuit-open"
    assert third.trace.network_requests == 0
    assert calls == 2


def test_batch_contract_rejects_duplicate_and_non_contiguous_original_ranks():
    first, second = _candidates()
    with pytest.raises(ValueError, match="duplicate shops"):
        rerank_input_fingerprint("query", (first, first))
    with pytest.raises(ValueError, match="contiguous"):
        rerank_input_fingerprint(
            "query",
            (first, second.model_copy(update={"original_rank": 3})),
        )
