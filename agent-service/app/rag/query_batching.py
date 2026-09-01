from __future__ import annotations

from app.rag.embeddings import (
    EmbeddingService,
    EmbeddingValidationError,
    _HttpEmbeddingService,
    _validate_input_text,
)


def supports_query_batch(service: EmbeddingService) -> bool:
    """Return whether the provider can batch queries without changing index code."""

    return isinstance(service, _HttpEmbeddingService)


async def embed_query_batch(
    service: EmbeddingService,
    texts: list[str],
) -> list[list[float]] | None:
    """Batch HTTP query embeddings and populate the provider's existing LRU cache.

    Query batching is deliberately isolated from ``embeddings.py`` because it
    changes online query scheduling, not the document transform that identifies
    a frozen Qdrant index. Unsupported adapters return ``None`` so callers retain
    the original per-query behavior.
    """

    if not supports_query_batch(service):
        return None
    if not texts:
        return []

    results: list[list[float] | None] = [None] * len(texts)
    missing_indices: list[int] = []
    missing_prepared: list[str] = []
    missing_keys: list[str] = []
    for index, text in enumerate(texts):
        _validate_input_text(text)
        cache_key = service._query_cache_key(text)
        cached = service._query_cache_get(cache_key)
        if cached is not None:
            service._increment_usage(query_cache_hits=1)
            results[index] = cached
            continue
        missing_indices.append(index)
        missing_prepared.append(f"{service.metadata.query_prefix}{text}")
        missing_keys.append(cache_key)

    if missing_prepared:
        vectors = await service._embed_many(missing_prepared, input_type="query")
        for index, cache_key, vector in zip(
            missing_indices,
            missing_keys,
            vectors,
            strict=True,
        ):
            service._query_cache_put(cache_key, vector)
            results[index] = list(vector)

    if any(vector is None for vector in results):
        raise EmbeddingValidationError("Query embedding batch returned an incomplete result.")
    return [list(vector) for vector in results if vector is not None]
