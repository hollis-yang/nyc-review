from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EmbeddingProfile:
    profile_id: str
    provider: str
    model: str
    dimensions: int
    version: str
    price_usd_per_million_tokens: float
    max_cost_usd: float
    collection: str
    provider_batch_limit: int
    api_flavor: str
    query_mode: str
    document_mode: str

    @property
    def max_total_tokens(self) -> int | None:
        if self.price_usd_per_million_tokens <= 0:
            return None
        return int(self.max_cost_usd / self.price_usd_per_million_tokens * 1_000_000)

    def as_dict(self) -> dict:
        return asdict(self)


PROFILES = {
    "hash64": EmbeddingProfile(
        profile_id="hash64",
        provider="hash",
        model="deterministic-token-sha256",
        dimensions=64,
        version="hash-v1",
        price_usd_per_million_tokens=0.0,
        max_cost_usd=0.0,
        collection="hmdp_content_v2",
        provider_batch_limit=2_048,
        api_flavor="local-deterministic",
        query_mode="symmetric",
        document_mode="symmetric",
    ),
    "openai-small-1024": EmbeddingProfile(
        profile_id="openai-small-1024",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1_024,
        version="text-embedding-3-small-1024-m1-v1",
        price_usd_per_million_tokens=0.02,
        max_cost_usd=0.50,
        collection="nyc_review_content_v3_openai_te3_small_1024_v1",
        provider_batch_limit=2_048,
        api_flavor="openai-v1",
        query_mode="plain",
        document_mode="plain",
    ),
    "openai-large-1024": EmbeddingProfile(
        profile_id="openai-large-1024",
        provider="openai",
        model="text-embedding-3-large",
        dimensions=1_024,
        version="text-embedding-3-large-1024-m1-v1",
        price_usd_per_million_tokens=0.13,
        max_cost_usd=2.25,
        collection="nyc_review_content_v3_openai_te3_large_1024_v1",
        provider_batch_limit=2_048,
        api_flavor="openai-v1",
        query_mode="plain",
        document_mode="plain",
    ),
    "qwen37-1024": EmbeddingProfile(
        profile_id="qwen37-1024",
        provider="qwen",
        model="qwen3.7-text-embedding",
        dimensions=1_024,
        version="qwen3.7-text-embedding-1024-m1-v1",
        price_usd_per_million_tokens=0.07,
        max_cost_usd=1.25,
        collection="nyc_review_content_v3_dashscope_qwen37_1024_v1",
        provider_batch_limit=20,
        api_flavor="dashscope-native",
        query_mode="query",
        document_mode="document",
    ),
}


def profile(profile_id: str) -> EmbeddingProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown embedding profile: {profile_id}") from exc
