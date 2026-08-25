from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import UserConstraints
from app.rag.lexical import canonical_tags, expand_query, lexical_tokens


class RetrievalPlan(BaseModel):
    original_query: str
    expanded_query: str
    lexical_terms: list[str] = Field(default_factory=list)
    category: str | None = None
    neighborhood: str | None = None
    desired_tags: list[str] = Field(default_factory=list)
    semantic_tags: list[str] = Field(default_factory=list)
    data_version: str | None = None
    dataset_sha256: str | None = None
    retrieval_version: str


def build_retrieval_plan(
    constraints: UserConstraints,
    *,
    retrieval_version: str,
    data_version: str | None = None,
    dataset_sha256: str | None = None,
) -> RetrievalPlan:
    canonical_terms = [
        constraints.category or "",
        constraints.neighborhood or "",
        *constraints.desired_tags,
    ]
    expanded = expand_query(constraints.query, canonical_terms)
    semantic_tags = canonical_tags(expanded, constraints.desired_tags)
    return RetrievalPlan(
        original_query=constraints.query,
        expanded_query=expanded,
        lexical_terms=list(dict.fromkeys(lexical_tokens(expanded))),
        category=constraints.category,
        neighborhood=constraints.neighborhood,
        desired_tags=constraints.desired_tags,
        semantic_tags=semantic_tags,
        data_version=data_version,
        dataset_sha256=dataset_sha256,
        retrieval_version=retrieval_version,
    )
