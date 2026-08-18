import json

from app.config import Settings
from app.domain.models import AgentRunRequest, UserConstraints
from app.runtime import AgentRuntime


def _write_json(path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


async def test_multi_agent_runtime_uses_qdrant_citations(tmp_path):
    shops = []
    reviews = []
    blogs = []
    comments = []
    for offset, shop_id in enumerate((101, 102, 103), start=1):
        shops.append(
            {
                "id": shop_id,
                "typeId": 1,
                "neighborhood": "Midtown",
                "name": f"NYC Fixture {shop_id}",
                "x": -73.9776 + offset * 0.001,
                "y": 40.7614 + offset * 0.001,
                "avgPriceCents": 4000 + offset * 100,
                "score": 45 + offset,
                "tags": ["quiet", "vegan_options"],
                "description": f"A quiet fictional NYC restaurant number {shop_id}.",
            }
        )
        reviews.append(
            {
                "id": offset,
                "shopId": shop_id,
                "content": "The quiet tables and vegan options matched the listing.",
                "evidenceTags": ["quiet", "vegan_options"],
                "createTime": "2026-08-01T12:00:00Z",
            }
        )
        blogs.append(
            {
                "id": offset,
                "shopId": shop_id,
                "title": "A practical visit",
                "content": "We verified the listed accessibility and price details.",
                "createTime": "2026-08-02T12:00:00Z",
            }
        )
        comments.append(
            {
                "id": offset,
                "blogId": offset,
                "parentId": 0 if offset == 1 else 1,
                "content": "A first-party mock discussion reply.",
                "createTime": "2026-08-03T12:00:00Z",
            }
        )
    _write_json(tmp_path / "shops.json", shops)
    _write_json(tmp_path / "shop_reviews.json", reviews)
    _write_json(tmp_path / "blogs.json", blogs)
    _write_json(tmp_path / "blog_comments.json", comments)

    runtime = await AgentRuntime.create(
        Settings(
            adapter="mock",
            rag_adapter="qdrant",
            qdrant_location=":memory:",
            rag_data_directory=tmp_path,
            embedding_provider="hash",
        )
    )
    try:
        state = await runtime.workflow.ainvoke(
            {
                "request": AgentRunRequest(
                    constraints=UserConstraints(
                        query="quiet vegan dinner near MoMA",
                        neighborhood="Midtown",
                        category="Food & Dining",
                        desired_tags=["quiet", "vegan_options"],
                    )
                ),
                "events": [],
            }
        )

        assert runtime.indexed_documents == 12
        assert state["verification"].valid is True
        assert all(item.citations for item in state["evidence"].evidence)
        assert {
            citation.content_type for item in state["evidence"].evidence for citation in item.citations
        } <= {"shop_description", "shop_review", "blog", "blog_comment", "nested_comment"}
    finally:
        await runtime.close()
