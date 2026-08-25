from __future__ import annotations

from pydantic import BaseModel, Field


class RagDocument(BaseModel):
    document_id: str
    shop_id: int = Field(gt=0)
    content_type: str
    document_kind: str = "evidence"
    source_id: str
    text: str = Field(min_length=1)
    created_at: str | None = None
    language: str = "en"
    category: str | None = None
    subcategory: str | None = None
    borough: str | None = None
    neighborhood: str | None = None
    shop_name: str | None = None
    avg_price_cents: int | None = Field(default=None, ge=0)
    score: float | None = Field(default=None, ge=0, le=5)
    evidence_tags: list[str] = Field(default_factory=list)
    data_version: str | None = None
    dataset_sha256: str | None = None
    retrieval_version: str = "p12-rag-v1"
    untrusted_content: bool = True
    content_source_type: str = "SYNTHETIC"
    content_source_name: str | None = None
    content_source_url: str | None = None
    synthetic: bool = True
    shop_source_type: str = "MOCK"
    shop_external_id: str | None = None
    shop_source_name: str | None = None
    shop_source_url: str | None = None
    shop_source_fetched_at: str | None = None
    synthetic_fields: list[str] = Field(default_factory=list)
    root_id: int | None = None
    max_depth: int | None = Field(default=None, ge=0, le=2)
    reply_count: int = Field(default=0, ge=0)
    sentiment: str | None = None
    topic_tags: list[str] = Field(default_factory=list)
    security_test: bool = False
    content_sha256: str | None = None
