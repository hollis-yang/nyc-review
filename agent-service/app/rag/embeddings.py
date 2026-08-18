from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx


class EmbeddingService(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingService:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout_seconds: float = 20.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._timeout_seconds = timeout_seconds

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/embeddings",
                headers=headers,
                json={
                    "model": self._model,
                    "input": texts,
                    "dimensions": self._dimensions,
                },
            )
            response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [row["embedding"] for row in rows]
        if len(vectors) != len(texts):
            raise ValueError("Embedding provider returned a different number of vectors than inputs.")
        if any(len(vector) != self._dimensions for vector in vectors):
            raise ValueError("Embedding provider returned an unexpected vector dimension.")
        return vectors


class DeterministicHashEmbeddingService:
    """Dependency-free test embedding; production must use a configured model provider."""

    def __init__(self, dimensions: int = 64):
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]
