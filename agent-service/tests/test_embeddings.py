from __future__ import annotations

import asyncio
import json
import math

import httpx
import pytest

from app.rag.embeddings import (
    EmbeddingBudgetExceeded,
    EmbeddingMetadata,
    EmbeddingProviderError,
    EmbeddingUsage,
    EmbeddingValidationError,
    OpenAICompatibleEmbeddingService,
    QwenNativeEmbeddingService,
)
from app.rag.query_batching import embed_query_batch

DIMENSIONS = 3
QWEN_DIMENSIONS = 256
OPENAI_BASE_URL = "https://api.openai.test/v1"
QWEN_COMPATIBLE_BASE_URL = "https://workspace-id.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
QWEN_NATIVE_URL = (
    "https://workspace-id.ap-southeast-1.maas.aliyuncs.com/api/v1/"
    "services/embeddings/text-embedding/text-embedding"
)
_MISSING = object()


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def _openai_response(
    request: httpx.Request,
    vectors: list[list[float]],
    *,
    total_tokens: int = 1,
    indices: list[int] | None = None,
    model: object = "text-embedding-3-small",
) -> httpx.Response:
    row_indices = indices if indices is not None else list(range(len(vectors)))
    payload = {
        "data": [
            {"index": index, "embedding": vector} for index, vector in zip(row_indices, vectors, strict=True)
        ],
        "usage": {"total_tokens": total_tokens},
    }
    if model is not _MISSING:
        payload["model"] = model
    return httpx.Response(
        200,
        request=request,
        headers={"content-type": "application/json"},
        # Deliberately permit NaN/Infinity so validation is exercised even for a
        # provider that emits technically non-standard JSON.
        content=json.dumps(payload, allow_nan=True).encode(),
    )


def _qwen_response(
    request: httpx.Request,
    vectors: list[list[float]],
    *,
    total_tokens: int = 1,
    indices: list[int] | None = None,
    model: object = _MISSING,
) -> httpx.Response:
    row_indices = indices if indices is not None else list(range(len(vectors)))
    payload = {
        "output": {
            "embeddings": [
                {"text_index": index, "embedding": vector}
                for index, vector in zip(row_indices, vectors, strict=True)
            ]
        },
        "usage": {"total_tokens": total_tokens},
    }
    if model is not _MISSING:
        payload["model"] = model
    return httpx.Response(
        200,
        request=request,
        headers={"content-type": "application/json"},
        content=json.dumps(payload, allow_nan=True).encode(),
    )


def _qwen_vector(first: float = 1.0) -> list[float]:
    return [first, 0.5, 0.25, *([0.125] * (QWEN_DIMENSIONS - 3))]


def _openai_service(
    client: httpx.AsyncClient | None = None,
    **overrides,
) -> OpenAICompatibleEmbeddingService:
    options = {
        "base_url": OPENAI_BASE_URL,
        "api_key": "openai-test-key",
        "model": "text-embedding-3-small",
        "dimensions": DIMENSIONS,
        "max_retries": 0,
        "client": client,
    }
    options.update(overrides)
    return OpenAICompatibleEmbeddingService(**options)


def _qwen_service(
    client: httpx.AsyncClient | None = None,
    **overrides,
) -> QwenNativeEmbeddingService:
    options = {
        "base_url": QWEN_COMPATIBLE_BASE_URL,
        "api_key": "qwen-test-key",
        "model": "qwen3.7-text-embedding",
        "dimensions": QWEN_DIMENSIONS,
        "max_retries": 0,
        "client": client,
    }
    options.update(overrides)
    return QwenNativeEmbeddingService(**options)


async def test_openai_request_contract_prefixes_and_response_index_order():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = _body(request)
        vectors = [[float(position + 1), 0.5, 0.25] for position, _ in enumerate(payload["input"])]
        # Providers are allowed to return rows out of order when indices are present.
        return _openai_response(
            request,
            list(reversed(vectors)),
            total_tokens=11,
            indices=list(reversed(range(len(vectors)))),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(
            client,
            query_prefix="query: ",
            document_prefix="document: ",
        )
        query = await service.embed_query("coffee")
        documents = await service.embed_documents(["alpha", "beta"])

    assert query == [1.0, 0.5, 0.25]
    assert documents == [[1.0, 0.5, 0.25], [2.0, 0.5, 0.25]]
    assert len(requests) == 2
    assert requests[0].url == httpx.URL(f"{OPENAI_BASE_URL}/embeddings")
    assert requests[0].headers["authorization"] == "Bearer openai-test-key"
    assert _body(requests[0]) == {
        "model": "text-embedding-3-small",
        "input": ["query: coffee"],
        "dimensions": DIMENSIONS,
        "encoding_format": "float",
    }
    assert _body(requests[1])["input"] == ["document: alpha", "document: beta"]
    assert service.metadata.query_mode == "plain"
    assert service.metadata.document_mode == "plain"
    assert service.usage_snapshot().total_tokens == 22


@pytest.mark.parametrize(
    "response_model",
    [
        pytest.param(_MISSING, id="missing"),
        pytest.param(None, id="null"),
        pytest.param(7, id="non-string"),
        pytest.param("text-embedding-3-large", id="different-model"),
    ],
)
async def test_openai_requires_the_requested_model_in_success_responses(response_model):
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_response(
            request,
            [[1.0, 0.5, 0.25]],
            total_tokens=3,
            model=response_model,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client)
        with pytest.raises(EmbeddingValidationError, match="invalid embedding response"):
            await service.embed_query("coffee")

    assert service.usage_snapshot().total_tokens == 3
    assert service.usage_snapshot().failure_count == 1


async def test_qwen_request_contract_distinguishes_query_and_document_modes():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        texts = _body(request)["input"]["texts"]
        return _qwen_response(request, [_qwen_vector() for _ in texts])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _qwen_service(
            client,
            query_prefix="q: ",
            document_prefix="d: ",
            query_instruct="Retrieve a relevant NYC place",
        )
        await service.embed_query("安静的咖啡馆")
        await service.embed_documents(["Cafe one", "Cafe two"])

    assert [request.url for request in requests] == [
        httpx.URL(QWEN_NATIVE_URL),
        httpx.URL(QWEN_NATIVE_URL),
    ]
    assert all(request.headers["authorization"] == "Bearer qwen-test-key" for request in requests)
    query_payload = _body(requests[0])
    document_payload = _body(requests[1])
    assert query_payload == {
        "model": "qwen3.7-text-embedding",
        "input": {"texts": ["q: 安静的咖啡馆"]},
        "parameters": {
            "dimension": QWEN_DIMENSIONS,
            "output_type": "dense",
            "text_type": "query",
            "instruct": "Retrieve a relevant NYC place",
        },
    }
    assert document_payload == {
        "model": "qwen3.7-text-embedding",
        "input": {"texts": ["d: Cafe one", "d: Cafe two"]},
        "parameters": {
            "dimension": QWEN_DIMENSIONS,
            "output_type": "dense",
            "text_type": "document",
        },
    }
    assert service.metadata.query_mode == "query+instruct"
    assert service.metadata.document_mode == "document"


async def test_qwen_accepts_a_matching_response_model_when_exposed():
    def handler(request: httpx.Request) -> httpx.Response:
        return _qwen_response(
            request,
            [_qwen_vector()],
            model="qwen3.7-text-embedding",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _qwen_service(client)
        vector = await service.embed_query("coffee")

    assert vector == _qwen_vector()


@pytest.mark.parametrize(
    "response_model",
    [
        pytest.param(None, id="null"),
        pytest.param(7, id="non-string"),
        pytest.param("text-embedding-v4", id="different-model"),
    ],
)
async def test_qwen_rejects_a_drifted_response_model_when_exposed(response_model):
    def handler(request: httpx.Request) -> httpx.Response:
        return _qwen_response(
            request,
            [_qwen_vector()],
            total_tokens=3,
            model=response_model,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _qwen_service(client)
        with pytest.raises(EmbeddingValidationError, match="invalid embedding response"):
            await service.embed_query("coffee")

    assert service.usage_snapshot().total_tokens == 3
    assert service.usage_snapshot().failure_count == 1


async def test_qwen_caps_batches_at_twenty_and_preserves_global_input_order():
    batch_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        batch_payloads.append(payload)
        texts = payload["input"]["texts"]
        vectors = [
            _qwen_vector(float(int(text.removeprefix("doc-")) + 1)) for text in texts
        ]
        return _qwen_response(
            request,
            list(reversed(vectors)),
            indices=list(reversed(range(len(texts)))),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _qwen_service(client, batch_size=100, max_concurrency=2)
        vectors = await service.embed_documents([f"doc-{index}" for index in range(21)])

    assert sorted(len(payload["input"]["texts"]) for payload in batch_payloads) == [1, 20]
    assert [vector[0] for vector in vectors] == [float(index + 1) for index in range(21)]
    assert all(len(vector) == QWEN_DIMENSIONS for vector in vectors)
    assert service.usage_snapshot().network_requests == 2
    assert service.usage_snapshot().input_texts == 21


async def test_failed_batch_cancels_and_drains_inflight_sibling_requests():
    all_started = asyncio.Event()
    release = asyncio.Event()
    started: set[str] = set()
    cancelled: set[str] = set()

    async def handler(request: httpx.Request) -> httpx.Response:
        text = _body(request)["input"][0]
        started.add(text)
        if len(started) == 3:
            all_started.set()
        await all_started.wait()
        if text == "fail":
            return httpx.Response(401, request=request, json={"error": {"code": "denied"}})
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.add(text)
            raise
        return _openai_response(request, [[1.0, 0.5, 0.25]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, batch_size=1, max_concurrency=3)
        try:
            with pytest.raises(EmbeddingProviderError):
                await service.embed_documents(["fail", "sibling-one", "sibling-two"])
        finally:
            release.set()

    assert started == {"fail", "sibling-one", "sibling-two"}
    assert cancelled == {"sibling-one", "sibling-two"}


async def test_query_cache_normalizes_keys_returns_copies_and_can_be_cleared():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _openai_response(request, [[1.0, 0.5, 0.25]], total_tokens=2)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, query_cache_size=2, query_cache_ttl_seconds=60)
        first = await service.embed_query("  Café   Near ME  ")
        first[0] = 999.0
        cached = await service.embed_query("café near me")
        service.clear_query_cache()
        uncached = await service.embed_query("café near me")

    assert cached == [1.0, 0.5, 0.25]
    assert uncached == [1.0, 0.5, 0.25]
    assert calls == 2
    assert service.usage_snapshot().query_cache_hits == 1
    assert service.usage_snapshot().network_requests == 2
    assert service.usage_snapshot().total_tokens == 4


async def test_query_batch_uses_one_provider_request_and_primes_individual_cache():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        texts = _body(request)["input"]
        vectors = [
            [float(index + 1), 0.5, 0.25]
            for index, _text in enumerate(texts)
        ]
        return _openai_response(request, vectors, total_tokens=7)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(
            client,
            query_prefix="query: ",
            query_cache_size=8,
            query_cache_ttl_seconds=60,
        )
        vectors = await embed_query_batch(service, ["quiet dinner", "step-free cafe"])
        cached = await service.embed_query("  QUIET   DINNER  ")

    assert vectors == [[1.0, 0.5, 0.25], [2.0, 0.5, 0.25]]
    assert cached == vectors[0]
    assert len(requests) == 1
    assert _body(requests[0])["input"] == [
        "query: quiet dinner",
        "query: step-free cafe",
    ]
    usage = service.usage_snapshot()
    assert usage.network_requests == 1
    assert usage.input_texts == 2
    assert usage.query_cache_hits == 1


async def test_query_cache_evicts_least_recently_used_entry():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _openai_response(request, [[float(calls), 0.5, 0.25]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, query_cache_size=1, query_cache_ttl_seconds=60)
        await service.embed_query("first")
        await service.embed_query("second")
        result = await service.embed_query("first")

    assert result == [3.0, 0.5, 0.25]
    assert calls == 3
    assert service.usage_snapshot().query_cache_hits == 0


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
async def test_retryable_http_statuses_are_retried(status_code: int):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                status_code,
                request=request,
                headers={"retry-after": "0"},
                json={"error": {"code": "rate_limit_exceeded"}},
            )
        return _openai_response(request, [[1.0, 0.5, 0.25]], total_tokens=3)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, max_retries=1)
        vector = await service.embed_query("coffee")

    assert vector == [1.0, 0.5, 0.25]
    assert calls == 2
    assert service.usage_snapshot().network_requests == 2
    assert service.usage_snapshot().retry_count == 1
    assert service.usage_snapshot().failure_count == 1
    assert service.usage_snapshot().total_tokens == 3


@pytest.mark.parametrize("status_code", [401, 403])
async def test_authentication_and_authorization_errors_are_not_retried(status_code: int):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status_code,
            request=request,
            headers={"x-request-id": "req-safe-id"},
            json={"error": {"message": "denied"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, max_retries=3)
        with pytest.raises(EmbeddingProviderError) as caught:
            await service.embed_query("coffee")

    assert calls == 1
    assert caught.value.provider == "openai"
    assert caught.value.status_code == status_code
    assert caught.value.request_id == "req-safe-id"
    assert caught.value.retryable is False
    assert service.usage_snapshot().retry_count == 0
    assert service.usage_snapshot().failure_count == 1


async def test_quota_exhaustion_429_is_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            request=request,
            headers={"retry-after": "0"},
            json={"error": {"code": "insufficient_quota"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, max_retries=3)
        with pytest.raises(EmbeddingProviderError) as caught:
            await service.embed_query("coffee")

    assert calls == 1
    assert caught.value.retryable is False
    assert caught.value.status_code == 429
    assert service.usage_snapshot().retry_count == 0


async def test_network_errors_are_retried_without_exposing_transport_details():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary failure with internal transport details", request=request)
        return _openai_response(request, [[1.0, 0.5, 0.25]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, max_retries=1)
        vector = await service.embed_query("coffee")

    assert vector == [1.0, 0.5, 0.25]
    assert calls == 2
    assert service.usage_snapshot().retry_count == 1
    assert service.usage_snapshot().failure_count == 1


@pytest.mark.parametrize(
    ("vectors", "indices"),
    [
        pytest.param([[1.0, 0.5, 0.25]], [0], id="count"),
        pytest.param(
            [[1.0, 0.5, 0.25], [2.0, 0.5, 0.25]],
            [0, 0],
            id="duplicate-index",
        ),
        pytest.param(
            [[1.0, 0.5, 0.25], [2.0, 0.5, 0.25]],
            [0.5, 1],
            id="fractional-index",
        ),
        pytest.param([[1.0, 0.5], [2.0, 0.5, 0.25]], [0, 1], id="dimension"),
        pytest.param([[math.nan, 0.5, 0.25], [2.0, 0.5, 0.25]], [0, 1], id="nan"),
        pytest.param([[math.inf, 0.5, 0.25], [2.0, 0.5, 0.25]], [0, 1], id="infinity"),
        pytest.param([[True, 0.5, 0.25], [2.0, 0.5, 0.25]], [0, 1], id="boolean"),
        pytest.param([[0.0, 0.0, 0.0], [2.0, 0.5, 0.25]], [0, 1], id="zero"),
    ],
)
async def test_openai_rejects_invalid_vector_responses(vectors, indices):
    def handler(request: httpx.Request) -> httpx.Response:
        return _openai_response(request, vectors, indices=indices)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client)
        with pytest.raises(EmbeddingValidationError):
            await service.embed_documents(["one", "two"])

    assert service.usage_snapshot().failure_count == 1
    assert service.usage_snapshot().total_tokens == 1


async def test_qwen_rejects_invalid_text_indices():
    def handler(request: httpx.Request) -> httpx.Response:
        return _qwen_response(
            request,
            [_qwen_vector(1.0), _qwen_vector(2.0)],
            indices=[1, 1],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _qwen_service(client)
        with pytest.raises(EmbeddingValidationError):
            await service.embed_documents(["one", "two"])


async def test_empty_document_batch_does_not_call_provider():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client)
        assert await service.embed_documents([]) == []

    assert service.usage_snapshot() == EmbeddingUsage()


@pytest.mark.parametrize("empty_text", ["", "   ", "\n\t"])
async def test_empty_or_whitespace_inputs_are_rejected_before_provider_call(empty_text: str):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("empty input must be rejected before a provider request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, query_prefix="query: ", document_prefix="document: ")
        with pytest.raises(EmbeddingValidationError, match="cannot be empty"):
            await service.embed_query(empty_text)
        with pytest.raises(EmbeddingValidationError, match="cannot be empty"):
            await service.embed_documents([empty_text])

    assert service.usage_snapshot().network_requests == 0


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"total_tokens": 0},
        {"total_tokens": -1},
        {"total_tokens": True},
        {"total_tokens": 1.5},
        {"total_tokens": "1"},
    ],
)
async def test_success_response_requires_strict_positive_integer_token_usage(usage):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "data": [{"index": 0, "embedding": [1.0, 0.5, 0.25]}],
        }
        if usage is not None:
            payload["usage"] = usage
        return httpx.Response(200, request=request, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client)
        with pytest.raises(EmbeddingValidationError, match="invalid embedding response"):
            await service.embed_query("coffee")

    assert service.usage_snapshot().total_tokens == 0
    assert service.usage_snapshot().failure_count == 1


def test_api_key_is_required_for_both_paid_providers():
    with pytest.raises(ValueError, match="openai embedding API key is required"):
        _openai_service(api_key="   ")
    with pytest.raises(ValueError, match="qwen embedding API key is required"):
        _qwen_service(api_key="")


def test_qwen_rejects_dimensions_outside_the_official_model_contract():
    with pytest.raises(ValueError, match="dimensions must be one of"):
        _qwen_service(dimensions=64)


def test_embedding_metadata_identity_captures_semantic_contract_without_secrets():
    base = EmbeddingMetadata(
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1_024,
        version="2026-08",
        query_mode="plain",
        document_mode="plain",
    )
    changed_mode = EmbeddingMetadata(
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1_024,
        version="2026-08",
        query_mode="query",
        document_mode="document",
    )

    assert base.identity == base.identity
    assert base.identity != changed_mode.identity
    assert base.as_dict()["identity"] == base.identity
    assert "api_key" not in base.as_dict()


async def test_qwen_instruction_changes_embedding_identity():
    first = _qwen_service(query_instruct="Retrieve relevant NYC businesses")
    second = _qwen_service(query_instruct="Retrieve semantically similar passages")

    try:
        assert first.metadata.identity != second.metadata.identity
    finally:
        await first.aclose()
        await second.aclose()


async def test_usage_accounts_for_retried_inputs_and_supports_deltas():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request, headers={"retry-after": "0"})
        return _openai_response(request, [[1.0, 0.5, 0.25]], total_tokens=7)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, max_retries=1)
        before = service.usage_snapshot()
        await service.embed_documents(["abcd"])
        after = service.usage_snapshot()

    assert after.delta(before).as_dict() == after.as_dict()
    assert after.network_requests == 2
    assert after.input_texts == 2
    assert after.input_characters == 8
    assert after.total_tokens == 7
    assert after.retry_count == 1
    assert after.failure_count == 1
    assert after.latency_ms >= 0


async def test_exhausted_retries_count_each_failed_request_once():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request, headers={"retry-after": "0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, max_retries=1)
        with pytest.raises(EmbeddingProviderError) as caught:
            await service.embed_query("coffee")

    assert caught.value.retryable is True
    assert calls == 2
    assert service.usage_snapshot().network_requests == 2
    assert service.usage_snapshot().retry_count == 1
    assert service.usage_snapshot().failure_count == 2


async def test_observed_usage_blocks_a_request_that_would_exceed_token_budget():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _openai_response(request, [[1.0, 0.5, 0.25]], total_tokens=2)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, max_total_tokens=15)
        await service.embed_documents(["ab"])
        with pytest.raises(EmbeddingBudgetExceeded):
            await service.embed_documents(["abcdefghij"])

    assert calls == 1
    assert service.usage_snapshot().network_requests == 1


async def test_concurrent_batches_reserve_budget_before_dispatch():
    release = asyncio.Event()
    cancelled = asyncio.Event()
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        text = _body(request)["input"][0]
        calls.append(text)
        if text == "ab":
            return _openai_response(request, [[1.0, 0.5, 0.25]], total_tokens=2)
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _openai_response(request, [[1.0, 0.5, 0.25]], total_tokens=2)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(
            client,
            batch_size=1,
            max_concurrency=2,
            max_total_tokens=30,
        )
        await service.embed_documents(["ab"])
        try:
            with pytest.raises(EmbeddingBudgetExceeded):
                await service.embed_documents(["abcdefghij", "klmnopqrst"])
        finally:
            release.set()

    assert calls == ["ab", "abcdefghij"]
    assert cancelled.is_set()
    assert service.usage_snapshot().network_requests == 2
    assert service.usage_snapshot().total_tokens == 2
    assert service._reserved_tokens == 0


async def test_service_owned_client_is_closed_and_injected_client_is_not():
    owned_service = _openai_service()
    owned_client = owned_service._client
    assert owned_client.is_closed is False
    await owned_service.aclose()
    assert owned_client.is_closed is True

    injected_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None))
    injected_service = _openai_service(injected_client)
    await injected_service.aclose()
    assert injected_client.is_closed is False
    await injected_client.aclose()


async def test_provider_error_and_metadata_do_not_leak_api_key_or_response_body():
    secret = "sk-secret-that-must-never-appear"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {secret}"
        return httpx.Response(
            403,
            request=request,
            headers={"x-request-id": "safe-request-id"},
            json={"error": {"message": f"provider echoed {secret}"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client, api_key=secret, max_retries=2)
        with pytest.raises(EmbeddingProviderError) as caught:
            await service.embed_query("coffee")

    exposed = " ".join(
        (
            str(caught.value),
            repr(caught.value),
            repr(service),
            repr(service.metadata),
            repr(service.metadata.as_dict()),
            repr(service.usage_snapshot()),
        )
    )
    assert secret not in exposed
    assert "provider echoed" not in exposed
    assert caught.value.request_id == "safe-request-id"


@pytest.mark.parametrize("bad_value", [None, 7, object()])
async def test_document_inputs_must_be_strings(bad_value):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid input must be rejected before a provider request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = _openai_service(client)
        with pytest.raises(TypeError, match="inputs must be strings"):
            await service.embed_documents([bad_value])
