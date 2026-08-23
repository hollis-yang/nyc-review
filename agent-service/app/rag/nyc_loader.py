from __future__ import annotations

import json
from pathlib import Path

from app.rag.models import RagDocument


def load_generated_documents(data_directory: Path) -> list[RagDocument]:
    shops = _read_json(data_directory / "shops.json")
    reviews = _read_json(data_directory / "shop_reviews.json")
    blogs = _read_json(data_directory / "blogs.json")
    blog_comments = _read_json(data_directory / "blog_comments.json")
    shops_by_id = {shop["id"]: shop for shop in shops}
    blogs_by_id = {blog["id"]: blog for blog in blogs}
    documents: list[RagDocument] = []

    for shop in shops:
        documents.append(
            RagDocument(
                document_id=f"shop:{shop['id']}",
                shop_id=shop["id"],
                content_type="shop_description",
                source_id=f"shop:{shop['id']}",
                text=shop["description"],
                category=_category_name(shop["typeId"]),
                neighborhood=shop["neighborhood"],
                evidence_tags=shop.get("tags") or [],
                data_version=shop.get("dataVersion"),
                untrusted_content=False,
                **_shop_provenance(shop),
            )
        )
    for review in reviews:
        shop = shops_by_id[review["shopId"]]
        documents.append(
            RagDocument(
                document_id=f"shop_review:{review['id']}",
                shop_id=review["shopId"],
                content_type="shop_review",
                source_id=f"shop_review:{review['id']}",
                text=review["content"],
                created_at=review.get("createTime"),
                category=_category_name(shop["typeId"]),
                neighborhood=shop["neighborhood"],
                evidence_tags=review.get("evidenceTags") or [],
                data_version=shop.get("dataVersion"),
                untrusted_content=True,
                **_shop_provenance(shop),
            )
        )
    for blog in blogs:
        shop = shops_by_id[blog["shopId"]]
        documents.append(
            RagDocument(
                document_id=f"blog:{blog['id']}",
                shop_id=blog["shopId"],
                content_type="blog",
                source_id=f"blog:{blog['id']}",
                text=f"{blog['title']}\n{blog['content']}",
                created_at=blog.get("createTime"),
                category=_category_name(shop["typeId"]),
                neighborhood=shop["neighborhood"],
                evidence_tags=shop.get("tags") or [],
                data_version=shop.get("dataVersion"),
                untrusted_content=True,
                **_shop_provenance(shop),
            )
        )
    for comment in blog_comments:
        blog = blogs_by_id[comment["blogId"]]
        shop = shops_by_id[blog["shopId"]]
        is_nested = bool(comment.get("parentId"))
        documents.append(
            RagDocument(
                document_id=f"blog_comment:{comment['id']}",
                shop_id=shop["id"],
                content_type="nested_comment" if is_nested else "blog_comment",
                source_id=f"blog_comment:{comment['id']}",
                text=comment["content"],
                created_at=comment.get("createTime"),
                category=_category_name(shop["typeId"]),
                neighborhood=shop["neighborhood"],
                data_version=shop.get("dataVersion"),
                untrusted_content=True,
                **_shop_provenance(shop),
            )
        )
    return documents


def _read_json(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"Expected a JSON list in {path}")
    return value


def _category_name(type_id: int) -> str:
    names = {
        1: "Food & Dining",
        2: "Cafes & Desserts",
        3: "Bars & Nightlife",
        4: "Entertainment & Attractions",
        5: "Fitness & Wellness",
        6: "Beauty & Personal Care",
    }
    return names[type_id]


def _shop_provenance(shop: dict) -> dict:
    return {
        "content_source_type": "SYNTHETIC",
        "shop_source_type": shop.get("sourceType") or "MOCK",
        "shop_external_id": shop.get("externalId"),
        "shop_source_name": shop.get("sourceName"),
        "shop_source_url": shop.get("sourceUrl"),
        "shop_source_fetched_at": shop.get("sourceFetchedAt"),
        "synthetic_fields": shop.get("syntheticFields") or [],
    }
