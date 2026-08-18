from __future__ import annotations

from pydantic import BaseModel, Field


class RagDocument(BaseModel):
    document_id: str
    shop_id: int = Field(gt=0)
    content_type: str
    source_id: str
    text: str = Field(min_length=1)
    created_at: str | None = None
    language: str = "en"
    category: str | None = None
    neighborhood: str | None = None
    evidence_tags: list[str] = Field(default_factory=list)
    data_version: str | None = None
    untrusted_content: bool = True
