from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
import unicodedata
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Literal, Protocol

import httpx

EmbeddingInputType = Literal["query", "document"]
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_QWEN37_SUPPORTED_DIMENSIONS = frozenset({256, 512, 768, 1_024, 1_536, 2_048, 2_560})


@dataclass(frozen=True)
class EmbeddingMetadata:
    provider: str
    model: str
    dimensions: int
    version: str
    query_mode: str
    document_mode: str
    query_prefix: str = ""
    document_prefix: str = ""
    query_instruction_sha256: str = ""

    @property
    def identity(self) -> str:
        payload = "\x1f".join(
            (
                self.provider,
                self.model,
                str(self.dimensions),
                self.version,
                self.query_mode,
                self.document_mode,
                self.query_prefix,
                self.document_prefix,
                self.query_instruction_sha256,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, str | int]:
        return {**asdict(self), "identity": self.identity}


@dataclass(frozen=True)
class EmbeddingUsage:
    network_requests: int = 0
    input_texts: int = 0
    input_characters: int = 0
    total_tokens: int = 0
    retry_count: int = 0
    failure_count: int = 0
    query_cache_hits: int = 0
    latency_ms: float = 0.0

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)

    def delta(self, previous: EmbeddingUsage) -> EmbeddingUsage:
        return EmbeddingUsage(
            **{
                field: getattr(self, field) - getattr(previous, field)
                for field in self.__dataclass_fields__
            }
        )


class EmbeddingError(RuntimeError):
    """Base class for safe-to-aggregate embedding failures."""


class EmbeddingProviderError(EmbeddingError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retryable: bool,
        status_code: int | None = None,
        request_id: str | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code
        self.request_id = request_id


class EmbeddingValidationError(EmbeddingError):
    pass


class EmbeddingBudgetExceeded(EmbeddingError):
    pass


class EmbeddingService(Protocol):
    @property
    def metadata(self) -> EmbeddingMetadata: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def usage_snapshot(self) -> EmbeddingUsage: ...

    def clear_query_cache(self) -> None: ...

    async def aclose(self) -> None: ...


class _HttpEmbeddingService:
    def __init__(
        self,
        *,
        metadata: EmbeddingMetadata,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
        batch_size: int,
        provider_batch_limit: int,
        max_concurrency: int,
        max_batch_characters: int,
        query_cache_size: int,
        query_cache_ttl_seconds: float,
        max_total_tokens: int | None,
        client: httpx.AsyncClient | None,
    ):
        if not api_key.strip():
            raise ValueError(f"{metadata.provider} embedding API key is required.")
        if timeout_seconds <= 0:
            raise ValueError("Embedding timeout must be positive.")
        if max_retries < 0:
            raise ValueError("Embedding max retries cannot be negative.")
        if batch_size < 1 or provider_batch_limit < 1:
            raise ValueError("Embedding batch sizes must be positive.")
        if max_concurrency < 1:
            raise ValueError("Embedding max concurrency must be positive.")
        if max_batch_characters < 1:
            raise ValueError("Embedding character budget must be positive.")
        if query_cache_size < 0 or query_cache_ttl_seconds < 0:
            raise ValueError("Embedding query cache bounds cannot be negative.")
        if max_total_tokens is not None and max_total_tokens < 1:
            raise ValueError("Embedding token budget must be positive when configured.")

        self._metadata = metadata
        self._api_key = api_key
        self._max_retries = max_retries
        self._batch_size = min(batch_size, provider_batch_limit)
        self._max_batch_characters = max_batch_characters
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._query_cache_size = query_cache_size
        self._query_cache_ttl_seconds = query_cache_ttl_seconds
        self._query_cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
        self._max_total_tokens = max_total_tokens
        self._reserved_tokens = 0
        self._successful_input_characters = 0
        self._usage = EmbeddingUsage()
        self._owns_client = client is None
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(timeout_seconds, 10.0),
            pool=min(timeout_seconds, 10.0),
        )
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    @property
    def dimensions(self) -> int:
        return self._metadata.dimensions

    def usage_snapshot(self) -> EmbeddingUsage:
        return self._usage

    def clear_query_cache(self) -> None:
        self._query_cache.clear()

    async def embed_query(self, text: str) -> list[float]:
        _validate_input_text(text)
        prepared = f"{self._metadata.query_prefix}{text}"
        cache_key = self._query_cache_key(text)
        cached = self._query_cache_get(cache_key)
        if cached is not None:
            self._increment_usage(query_cache_hits=1)
            return cached
        vectors = await self._embed_many([prepared], input_type="query")
        vector = vectors[0]
        self._query_cache_put(cache_key, vector)
        return list(vector)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        for text in texts:
            _validate_input_text(text)
        prepared = [f"{self._metadata.document_prefix}{text}" for text in texts]
        return await self._embed_many(prepared, input_type="document")

    async def _embed_many(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
    ) -> list[list[float]]:
        if not texts:
            return []
        batches = list(self._batches(texts))
        tasks = [
            asyncio.create_task(
                self._request_with_retries(batch, input_type=input_type)
            )
            for batch in batches
        ]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:
            # asyncio.gather propagates a child's exception without cancelling its
            # siblings. Explicitly drain cancellation so queued provider calls do
            # not continue spending after this logical embedding operation fails.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [vector for batch in results for vector in batch]

    def _batches(self, texts: list[str]):
        batch: list[str] = []
        characters = 0
        for text in texts:
            if not isinstance(text, str):
                raise TypeError("Embedding inputs must be strings.")
            if len(text) > self._max_batch_characters:
                raise EmbeddingValidationError(
                    "One embedding input exceeds the configured character budget."
                )
            if batch and (
                len(batch) >= self._batch_size
                or characters + len(text) > self._max_batch_characters
            ):
                yield batch
                batch = []
                characters = 0
            batch.append(text)
            characters += len(text)
        if batch:
            yield batch

    async def _request_with_retries(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
    ) -> list[list[float]]:
        async with self._budget_reservation(texts, input_type=input_type), self._semaphore:
            for attempt in range(self._max_retries + 1):
                started = time.perf_counter()
                self._increment_usage(
                    network_requests=1,
                    input_texts=len(texts),
                    input_characters=sum(len(text) for text in texts),
                )
                try:
                    response = await self._post(texts, input_type=input_type)
                except httpx.RequestError as exc:
                    self._increment_usage(
                        failure_count=1,
                        latency_ms=(time.perf_counter() - started) * 1_000,
                    )
                    if attempt >= self._max_retries:
                        raise EmbeddingProviderError(
                            f"{self.metadata.provider} embedding request failed after retries.",
                            provider=self.metadata.provider,
                            retryable=True,
                        ) from exc
                    self._increment_usage(retry_count=1)
                    await asyncio.sleep(self._backoff_seconds(attempt, None))
                    continue

                elapsed_ms = (time.perf_counter() - started) * 1_000
                retryable_response = (
                    response.status_code in _RETRYABLE_STATUS_CODES
                    and not _is_quota_exhausted(response)
                )
                if retryable_response and attempt < self._max_retries:
                    self._increment_usage(failure_count=1, latency_ms=elapsed_ms)
                    self._increment_usage(retry_count=1)
                    await asyncio.sleep(self._backoff_seconds(attempt, response))
                    continue
                if response.is_error:
                    self._increment_usage(failure_count=1, latency_ms=elapsed_ms)
                    raise EmbeddingProviderError(
                        f"{self.metadata.provider} embedding request returned HTTP "
                        f"{response.status_code}.",
                        provider=self.metadata.provider,
                        retryable=retryable_response,
                        status_code=response.status_code,
                        request_id=_request_id(response),
                    )

                try:
                    payload = response.json()
                    total_tokens = _strict_total_tokens(payload)
                except (KeyError, TypeError, ValueError) as exc:
                    self._increment_usage(failure_count=1, latency_ms=elapsed_ms)
                    raise EmbeddingValidationError(
                        f"{self.metadata.provider} returned an invalid embedding response."
                    ) from exc
                self._increment_usage(total_tokens=total_tokens, latency_ms=elapsed_ms)
                self._successful_input_characters += sum(len(text) for text in texts)
                try:
                    vectors = self._parse_vectors(payload, len(texts))
                    _validate_vectors(vectors, len(texts), self.dimensions)
                except (KeyError, TypeError, ValueError) as exc:
                    # A successful provider response is billable even when its
                    # vector payload violates our contract. Keep the reported
                    # tokens in the ledger before rejecting the response.
                    self._increment_usage(failure_count=1)
                    raise EmbeddingValidationError(
                        f"{self.metadata.provider} returned an invalid embedding response."
                    ) from exc
                if (
                    self._max_total_tokens is not None
                    and self._usage.total_tokens > self._max_total_tokens
                ):
                    raise EmbeddingBudgetExceeded(
                        f"{self.metadata.provider} embedding token budget was exceeded."
                    )
                return vectors
        raise AssertionError("unreachable")

    @asynccontextmanager
    async def _budget_reservation(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
    ):
        if self._max_total_tokens is None:
            yield
            return
        remaining = (
            self._max_total_tokens
            - self._usage.total_tokens
            - self._reserved_tokens
        )
        if remaining <= 0:
            raise EmbeddingBudgetExceeded(
                f"{self.metadata.provider} embedding token budget is exhausted."
            )
        characters = sum(map(len, texts))
        byte_upper_bound = self._request_token_upper_bound(texts, input_type=input_type)
        if self._usage.total_tokens and self._successful_input_characters:
            observed_ratio = self._usage.total_tokens / self._successful_input_characters
            observed_projection = math.ceil(characters * observed_ratio * 1.2)
        else:
            observed_projection = 0
        projected = max(1, byte_upper_bound, observed_projection)
        if projected > remaining:
            raise EmbeddingBudgetExceeded(
                f"{self.metadata.provider} embedding request would exceed its token budget."
            )
        self._reserved_tokens += projected
        try:
            yield
        finally:
            self._reserved_tokens -= projected

    def _request_token_upper_bound(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
    ) -> int:
        del input_type
        # Both providers tokenize UTF-8 text. Reserving every byte plus a small
        # per-input special-token allowance is intentionally conservative and
        # protects the very first request before an observed token ratio exists.
        return sum(len(text.encode("utf-8")) + 8 for text in texts)

    def _increment_usage(self, **increments: int | float) -> None:
        values = self._usage.as_dict()
        for key, increment in increments.items():
            values[key] += increment
        self._usage = EmbeddingUsage(**values)

    def _query_cache_key(self, text: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", text).split()).casefold()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"{self.metadata.identity}:{digest}"

    def _query_cache_get(self, key: str) -> list[float] | None:
        item = self._query_cache.get(key)
        if item is None:
            return None
        expires_at, vector = item
        if expires_at <= time.monotonic():
            self._query_cache.pop(key, None)
            return None
        self._query_cache.move_to_end(key)
        return list(vector)

    def _query_cache_put(self, key: str, vector: list[float]) -> None:
        if self._query_cache_size == 0 or self._query_cache_ttl_seconds == 0:
            return
        self._query_cache[key] = (
            time.monotonic() + self._query_cache_ttl_seconds,
            list(vector),
        )
        self._query_cache.move_to_end(key)
        while len(self._query_cache) > self._query_cache_size:
            self._query_cache.popitem(last=False)

    @staticmethod
    def _backoff_seconds(attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(max(float(retry_after), 0.0), 30.0)
                except ValueError:
                    try:
                        parsed = parsedate_to_datetime(retry_after)
                        return min(max(parsed.timestamp() - time.time(), 0.0), 30.0)
                    except (TypeError, ValueError):
                        pass
        return min(0.5 * (2**attempt), 8.0)

    async def _post(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
    ) -> httpx.Response:
        raise NotImplementedError

    def _parse_vectors(
        self,
        payload: dict[str, Any],
        expected_count: int,
    ) -> list[list[float]]:
        raise NotImplementedError

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class OpenAICompatibleEmbeddingService(_HttpEmbeddingService):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        *,
        version: str | None = None,
        batch_size: int = 64,
        max_concurrency: int = 2,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
        max_batch_characters: int = 250_000,
        query_cache_size: int = 512,
        query_cache_ttl_seconds: float = 900.0,
        query_prefix: str = "",
        document_prefix: str = "",
        max_total_tokens: int | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        super().__init__(
            metadata=EmbeddingMetadata(
                provider="openai",
                model=model,
                dimensions=dimensions,
                version=version or model,
                query_mode="plain",
                document_mode="plain",
                query_prefix=query_prefix,
                document_prefix=document_prefix,
            ),
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            batch_size=batch_size,
            provider_batch_limit=2_048,
            max_concurrency=max_concurrency,
            max_batch_characters=max_batch_characters,
            query_cache_size=query_cache_size,
            query_cache_ttl_seconds=query_cache_ttl_seconds,
            max_total_tokens=max_total_tokens,
            client=client,
        )

    async def _post(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
    ) -> httpx.Response:
        del input_type
        return await self._client.post(
            f"{self._base_url}/embeddings",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self.metadata.model,
                "input": texts,
                "dimensions": self.dimensions,
                "encoding_format": "float",
            },
        )

    def _parse_vectors(
        self,
        payload: dict[str, Any],
        expected_count: int,
    ) -> list[list[float]]:
        _validate_response_model(
            payload,
            expected_model=self.metadata.model,
            required=True,
        )
        rows = payload["data"]
        indices = [_strict_response_index(item["index"]) for item in rows]
        if sorted(indices) != list(range(expected_count)):
            raise ValueError("Embedding provider returned invalid indices.")
        ordered = sorted(rows, key=lambda item: _strict_response_index(item["index"]))
        return [item["embedding"] for item in ordered]


class QwenNativeEmbeddingService(_HttpEmbeddingService):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "qwen3.7-text-embedding",
        dimensions: int = 1_024,
        *,
        version: str | None = None,
        batch_size: int = 20,
        max_concurrency: int = 2,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
        max_batch_characters: int = 250_000,
        query_cache_size: int = 512,
        query_cache_ttl_seconds: float = 900.0,
        query_prefix: str = "",
        document_prefix: str = "",
        query_instruct: str = "",
        max_total_tokens: int | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        if dimensions not in _QWEN37_SUPPORTED_DIMENSIONS:
            supported = ", ".join(map(str, sorted(_QWEN37_SUPPORTED_DIMENSIONS)))
            raise ValueError(
                f"qwen3.7-text-embedding dimensions must be one of: {supported}."
            )
        self._endpoint = _qwen_native_endpoint(base_url)
        self._query_instruct = query_instruct.strip()
        query_mode = "query+instruct" if self._query_instruct else "query"
        super().__init__(
            metadata=EmbeddingMetadata(
                provider="qwen",
                model=model,
                dimensions=dimensions,
                version=version or model,
                query_mode=query_mode,
                document_mode="document",
                query_prefix=query_prefix,
                document_prefix=document_prefix,
                query_instruction_sha256=(
                    hashlib.sha256(self._query_instruct.encode("utf-8")).hexdigest()
                    if self._query_instruct
                    else ""
                ),
            ),
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            batch_size=batch_size,
            provider_batch_limit=20,
            max_concurrency=max_concurrency,
            max_batch_characters=max_batch_characters,
            query_cache_size=query_cache_size,
            query_cache_ttl_seconds=query_cache_ttl_seconds,
            max_total_tokens=max_total_tokens,
            client=client,
        )

    async def _post(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
    ) -> httpx.Response:
        parameters: dict[str, Any] = {
            "dimension": self.dimensions,
            "output_type": "dense",
            "text_type": input_type,
        }
        if input_type == "query" and self._query_instruct:
            parameters["instruct"] = self._query_instruct
        return await self._client.post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self.metadata.model,
                "input": {"texts": texts},
                "parameters": parameters,
            },
        )

    def _parse_vectors(
        self,
        payload: dict[str, Any],
        expected_count: int,
    ) -> list[list[float]]:
        _validate_response_model(
            payload,
            expected_model=self.metadata.model,
            required=False,
        )
        rows = payload["output"]["embeddings"]
        indices = [_strict_response_index(item["text_index"]) for item in rows]
        if sorted(indices) != list(range(expected_count)):
            raise ValueError("Embedding provider returned invalid text indices.")
        ordered = sorted(
            rows,
            key=lambda item: _strict_response_index(item["text_index"]),
        )
        return [item["embedding"] for item in ordered]

    def _request_token_upper_bound(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
    ) -> int:
        reserved = super()._request_token_upper_bound(texts, input_type=input_type)
        if input_type == "query" and self._query_instruct:
            reserved += len(self._query_instruct.encode("utf-8")) + 8
        return reserved


class DeterministicHashEmbeddingService:
    """Dependency-free test embedding; production must use a configured model provider."""

    def __init__(self, dimensions: int = 64, *, version: str = "hash-v1"):
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self._metadata = EmbeddingMetadata(
            provider="hash",
            model="deterministic-token-sha256",
            dimensions=dimensions,
            version=version,
            query_mode="symmetric",
            document_mode="symmetric",
        )

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    @property
    def dimensions(self) -> int:
        return self._metadata.dimensions

    async def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def usage_snapshot(self) -> EmbeddingUsage:
        return EmbeddingUsage()

    def clear_query_cache(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]


def _qwen_native_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    suffix = "/services/embeddings/text-embedding/text-embedding"
    if normalized.endswith(suffix):
        return normalized
    if normalized.endswith("/compatible-mode/v1"):
        normalized = normalized[: -len("/compatible-mode/v1")] + "/api/v1"
    elif not normalized.endswith("/api/v1"):
        raise ValueError(
            "Qwen base URL must end in /compatible-mode/v1, /api/v1, or the native endpoint."
        )
    return f"{normalized}{suffix}"


def _request_id(response: httpx.Response) -> str | None:
    for key in ("x-request-id", "request-id"):
        if value := response.headers.get(key):
            return value
    try:
        payload = response.json()
    except ValueError:
        return None
    value = payload.get("request_id") or payload.get("id")
    return str(value) if value else None


def _is_quota_exhausted(response: httpx.Response) -> bool:
    if response.status_code != 429:
        return False
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return False
    return str(error.get("code") or "").casefold() in {
        "insufficient_quota",
        "billing_hard_limit_reached",
    }


def _validate_vectors(vectors: Any, expected_count: int, dimensions: int) -> None:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise ValueError("Embedding provider returned a different vector count than requested.")
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise ValueError("Embedding provider returned an unexpected vector dimension.")
        if not all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            for value in vector
        ):
            raise ValueError("Embedding provider returned a non-finite vector value.")
        if not any(float(value) != 0.0 for value in vector):
            raise ValueError("Embedding provider returned an all-zero vector.")


def _validate_input_text(text: Any) -> None:
    if not isinstance(text, str):
        raise TypeError("Embedding inputs must be strings.")
    if not text.strip():
        raise EmbeddingValidationError("Embedding inputs cannot be empty.")


def _validate_response_model(
    payload: dict[str, Any],
    *,
    expected_model: str,
    required: bool,
) -> None:
    if "model" not in payload:
        if required:
            raise KeyError("Embedding response is missing its model identifier.")
        return
    model = payload["model"]
    if not isinstance(model, str) or model != expected_model:
        raise ValueError("Embedding response model does not match the requested model.")


def _strict_total_tokens(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise TypeError("Embedding response must be an object.")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise TypeError("Embedding response is missing usage.")
    value = usage.get("total_tokens")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Embedding response has invalid token usage.")
    return value


def _strict_response_index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Embedding provider returned a non-integer index.")
    return value
