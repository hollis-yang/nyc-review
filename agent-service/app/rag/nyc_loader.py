from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import chain, groupby
from pathlib import Path

from app.rag.display_text import clean_display_text
from app.rag.models import RagDocument


def load_generated_documents(data_directory: Path) -> list[RagDocument]:
    """Compatibility wrapper for tests and small local datasets."""

    return list(iter_generated_documents(data_directory))


def iter_generated_documents(data_directory: Path) -> Iterator[RagDocument]:
    """Yield RAG documents without loading the large review file into memory."""

    shops = _read_json(data_directory / "shops.json")
    blogs = _read_json(data_directory / "blogs.json")
    blog_comments = _read_json(data_directory / "blog_comments.json")
    subcategory_path = data_directory / "shop_subcategories.json"
    subcategories = {
        item["id"]: item for item in _read_json(subcategory_path)
    } if subcategory_path.is_file() else {}
    shops_by_id = {shop["id"]: shop for shop in shops}
    blogs_by_id = {blog["id"]: blog for blog in blogs}

    for shop in shops:
        common = _shop_document_fields(shop, subcategories)
        identity_provenance = _identity_fact_provenance(shop)
        yield RagDocument(
            document_id=f"shop_identity_fact:{shop['id']}",
            shop_id=shop["id"],
            content_type="shop_identity_fact",
            document_kind="fact",
            source_id=f"shop:{shop['id']}:identity",
            text=_identity_fact_text(shop, common),
            evidence_tags=[],
            data_version=shop.get("dataVersion"),
            untrusted_content=False,
            **identity_provenance,
            **common,
            **_shop_provenance(shop),
        )
        attribute_synthetic = shop.get("sourceType") in (None, "MOCK", "LEGACY") or bool(
            {"avgPriceCents", "priceLevel", "score", "tags"}
            & set(shop.get("syntheticFields") or [])
        )
        yield RagDocument(
            document_id=f"shop_attribute_fact:{shop['id']}",
            shop_id=shop["id"],
            content_type="shop_attribute_fact",
            document_kind="fact",
            source_id=f"shop:{shop['id']}:attributes",
            text=_attribute_fact_text(shop),
            evidence_tags=shop.get("tags") or [],
            data_version=shop.get("dataVersion"),
            untrusted_content=False,
            content_source_type=(
                "SYNTHETIC"
                if shop.get("sourceType") in (None, "MOCK", "LEGACY")
                else "MIXED" if attribute_synthetic else (shop.get("sourceType") or "PUBLIC_SOURCE")
            ),
            content_source_name=(
                "HMDP deterministic NYC generator"
                if shop.get("sourceType") in (None, "MOCK", "LEGACY")
                else "HMDP resolved merchant catalog"
            ),
            synthetic=attribute_synthetic,
            **common,
            **_shop_provenance(shop),
        )
        yield RagDocument(
            document_id=f"shop:{shop['id']}",
            shop_id=shop["id"],
            content_type="shop_description",
            document_kind="evidence",
            source_id=f"shop:{shop['id']}",
            text=clean_display_text(shop["description"]),
            evidence_tags=shop.get("tags") or [],
            data_version=shop.get("dataVersion"),
            untrusted_content=False,
            **common,
            **_content_provenance(shop, field_name="description"),
            **_shop_provenance(shop),
        )

    reviews = _iter_json_array(data_directory / "shop_reviews.json")
    first_review = next(reviews, None)
    if first_review is not None:
        review_rows = chain([first_review], reviews)
        if _has_thread_shape(first_review):
            yield from _iter_review_threads(review_rows, shops_by_id)
        elif any(
            str(shop.get("dataVersion") or "").startswith("nyc-real-") for shop in shops
        ):
            raise ValueError("nyc-real datasets require hierarchical shop review fields.")
        else:
            for review in review_rows:
                yield _flat_review_document(review, shops_by_id)

    for blog in blogs:
        shop = shops_by_id[blog["shopId"]]
        yield RagDocument(
            document_id=f"blog:{blog['id']}",
            shop_id=blog["shopId"],
            content_type="blog",
            document_kind="evidence",
            source_id=f"blog:{blog['id']}",
            # The card title is presentation metadata. Index the actual post body
            # so citations read like evidence instead of repeating a templated title.
            text=clean_display_text(blog["content"]),
            created_at=blog.get("createTime"),
            category=_category_name(shop["typeId"]),
            borough=shop.get("borough"),
            neighborhood=shop["neighborhood"],
            shop_name=shop.get("name"),
            avg_price_cents=shop.get("avgPriceCents"),
            score=(shop.get("score") / 10 if shop.get("score") is not None else None),
            evidence_tags=shop.get("tags") or [],
            data_version=shop.get("dataVersion"),
            untrusted_content=True,
            **_record_content_provenance(blog, shop, content_kind="blog"),
            **_shop_provenance(shop),
        )
    for comment in blog_comments:
        blog = blogs_by_id[comment["blogId"]]
        shop = shops_by_id[blog["shopId"]]
        is_nested = bool(comment.get("parentId"))
        yield RagDocument(
            document_id=f"blog_comment:{comment['id']}",
            shop_id=shop["id"],
            content_type="nested_comment" if is_nested else "blog_comment",
            document_kind="evidence",
            source_id=f"blog_comment:{comment['id']}",
            text=clean_display_text(comment["content"]),
            created_at=comment.get("createTime"),
            category=_category_name(shop["typeId"]),
            borough=shop.get("borough"),
            neighborhood=shop["neighborhood"],
            shop_name=shop.get("name"),
            avg_price_cents=shop.get("avgPriceCents"),
            score=(shop.get("score") / 10 if shop.get("score") is not None else None),
            data_version=shop.get("dataVersion"),
            untrusted_content=True,
            **_record_content_provenance(comment, shop, content_kind="blog comment"),
            **_shop_provenance(shop),
        )


def _flat_review_document(review: dict, shops_by_id: dict[int, dict]) -> RagDocument:
    shop = shops_by_id[review["shopId"]]
    source_type = str(review.get("sourceType") or "SYNTHETIC")
    synthetic = source_type == "SYNTHETIC"
    return RagDocument(
        document_id=f"shop_review:{review['id']}",
        shop_id=review["shopId"],
        content_type="shop_review",
        document_kind="evidence",
        source_id=f"shop_review:{review['id']}",
        text=clean_display_text(review["content"]),
        created_at=review.get("createTime"),
        language=review.get("language") or "en",
        category=_category_name(shop["typeId"]),
        borough=shop.get("borough"),
        neighborhood=shop["neighborhood"],
        shop_name=shop.get("name"),
        avg_price_cents=shop.get("avgPriceCents"),
        score=(shop.get("score") / 10 if shop.get("score") is not None else None),
        evidence_tags=review.get("evidenceTags") or [],
        data_version=shop.get("dataVersion"),
        untrusted_content=True,
        content_source_type=source_type,
        content_source_name=(
            "HMDP synthetic review generator" if synthetic else "HMDP user-submitted review"
        ),
        synthetic=synthetic,
        root_id=review.get("rootId") or review["id"],
        max_depth=0,
        sentiment=review.get("sentiment"),
        topic_tags=review.get("topicTags") or [],
        security_test=bool(review.get("securityTest", False)),
        **_shop_provenance(shop),
    )


def _iter_review_threads(
    reviews: Iterator[dict],
    shops_by_id: dict[int, dict],
) -> Iterator[RagDocument]:
    seen_root_ids: set[int] = set()
    for raw_root_id, grouped_rows in groupby(reviews, key=lambda item: item.get("rootId")):
        if not isinstance(raw_root_id, int) or raw_root_id <= 0:
            raise ValueError("Hierarchical shop reviews require a positive rootId.")
        if raw_root_id in seen_root_ids:
            raise ValueError("Hierarchical shop reviews must be grouped by rootId for streaming.")
        seen_root_ids.add(raw_root_id)
        rows = list(grouped_rows)
        yield _review_thread_document(raw_root_id, rows, shops_by_id)


def _review_thread_document(
    root_id: int,
    rows: list[dict],
    shops_by_id: dict[int, dict],
) -> RagDocument:
    if not rows:
        raise ValueError(f"Review thread {root_id} is empty.")
    rows_by_id = {row.get("id"): row for row in rows}
    if len(rows_by_id) != len(rows) or None in rows_by_id:
        raise ValueError(f"Review thread {root_id} contains missing or duplicate IDs.")
    roots = [
        row
        for row in rows
        if row.get("id") == root_id and row.get("parentId") in (None, 0)
    ]
    if len(roots) != 1:
        raise ValueError(f"Review thread {root_id} must contain exactly one root review.")
    root = roots[0]
    shop_id = root.get("shopId")
    if shop_id not in shops_by_id:
        raise ValueError(f"Review thread {root_id} references unknown shop {shop_id}.")
    for row in rows:
        depth = row.get("depth")
        if not isinstance(depth, int) or depth < 0 or depth > 2:
            raise ValueError(f"Review {row.get('id')} depth must be between 0 and 2.")
        if row.get("rootId") != root_id or row.get("shopId") != shop_id:
            raise ValueError(f"Review thread {root_id} mixes roots or shops.")
        if row is root:
            if depth != 0:
                raise ValueError(f"Root review {root_id} must have depth 0.")
            continue
        parent = rows_by_id.get(row.get("parentId"))
        if parent is None or parent.get("depth") != depth - 1:
            raise ValueError(f"Review {row.get('id')} has an invalid parent/depth relationship.")

    ordered = sorted(rows, key=lambda row: (row["depth"], row["id"]))
    source_types = {str(row.get("sourceType") or "SYNTHETIC") for row in ordered}
    fully_synthetic = source_types == {"SYNTHETIC"}
    shop = shops_by_id[shop_id]
    if str(shop.get("dataVersion") or "").startswith("nyc-real-") and not fully_synthetic:
        raise ValueError(f"nyc-real review thread {root_id} must contain only SYNTHETIC reviews.")
    evidence_tags = sorted(
        {
            tag
            for row in ordered
            for tag in (row.get("evidenceTags") or [])
            if isinstance(tag, str) and tag
        }
    )
    topic_tags = sorted(
        {
            tag
            for row in ordered
            for tag in (row.get("topicTags") or [])
            if isinstance(tag, str) and tag
        }
    )
    return RagDocument(
        document_id=f"shop_review_thread:{root_id}",
        shop_id=shop_id,
        content_type="shop_review_thread",
        document_kind="evidence",
        source_id=f"shop_review_thread:{root_id}",
        text="\n".join(_review_thread_line(row) for row in ordered),
        created_at=root.get("createTime"),
        language=root.get("language") or "en",
        category=_category_name(shop["typeId"]),
        borough=shop.get("borough"),
        neighborhood=shop["neighborhood"],
        shop_name=shop.get("name"),
        avg_price_cents=shop.get("avgPriceCents"),
        score=(shop.get("score") / 10 if shop.get("score") is not None else None),
        evidence_tags=evidence_tags,
        data_version=shop.get("dataVersion"),
        untrusted_content=True,
        content_source_type="SYNTHETIC" if fully_synthetic else "MIXED",
        content_source_name="HMDP synthetic review generator" if fully_synthetic else "HMDP reviews",
        synthetic=fully_synthetic,
        root_id=root_id,
        max_depth=max(row["depth"] for row in ordered),
        reply_count=len(ordered) - 1,
        sentiment=root.get("sentiment"),
        topic_tags=topic_tags,
        security_test=any(bool(row.get("securityTest", False)) for row in ordered),
        **_shop_provenance(shop),
    )


def _review_thread_line(review: dict) -> str:
    return clean_display_text(review.get("content"))


def _has_thread_shape(review: dict) -> bool:
    return "rootId" in review or "depth" in review or "replyToUserId" in review


def _iter_json_array(path: Path, chunk_size: int = 64 * 1024) -> Iterator[dict]:
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    finished = False
    with path.open(encoding="utf-8") as handle:
        while not finished:
            chunk = handle.read(chunk_size)
            eof = chunk == ""
            buffer += chunk
            while True:
                buffer = buffer.lstrip()
                if not started:
                    if not buffer:
                        break
                    if buffer[0] != "[":
                        raise ValueError(f"Expected a JSON list in {path}")
                    buffer = buffer[1:]
                    started = True
                    continue
                buffer = buffer.lstrip()
                if buffer.startswith("]"):
                    buffer = buffer[1:]
                    finished = True
                    break
                if buffer.startswith(","):
                    buffer = buffer[1:]
                    continue
                if not buffer:
                    break
                try:
                    value, end = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    if eof:
                        raise ValueError(f"Malformed JSON list in {path}") from None
                    break
                if not isinstance(value, dict):
                    raise ValueError(f"Expected JSON objects in {path}")
                yield value
                buffer = buffer[end:]
            if eof:
                break
    if not started or not finished or buffer.strip():
        raise ValueError(f"Malformed JSON list in {path}")


def _read_json(path: Path) -> list[dict]:
    value = list(_iter_json_array(path))
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


def _shop_document_fields(shop: dict, subcategories: dict[int, dict]) -> dict:
    subcategory = subcategories.get(shop.get("subcategoryId")) or {}
    score = shop.get("score")
    return {
        "category": _category_name(shop["typeId"]),
        "subcategory": subcategory.get("name"),
        "borough": shop.get("borough"),
        "neighborhood": shop.get("neighborhood"),
        "shop_name": shop.get("name"),
        "avg_price_cents": shop.get("avgPriceCents"),
        "score": (score / 10 if score is not None else None),
    }


def _identity_fact_text(shop: dict, common: dict) -> str:
    parts = [
        str(shop.get("name") or "NYC merchant"),
        str(common.get("category") or ""),
        str(common.get("subcategory") or ""),
        str(shop.get("neighborhood") or ""),
        str(shop.get("borough") or ""),
        str(shop.get("address") or ""),
    ]
    return ". ".join(part for part in parts if part) + "."


def _attribute_fact_text(shop: dict) -> str:
    parts: list[str] = []
    tags = [str(tag).replace("_", " ") for tag in shop.get("tags") or []]
    if tags:
        parts.append("Features: " + ", ".join(tags))
    price = shop.get("avgPriceCents")
    if isinstance(price, int) and price > 0:
        parts.append(f"Estimated per-person or per-visit price: ${price / 100:g}")
    price_range = shop.get("priceRangeText")
    if price_range:
        parts.append(f"Published price range: {price_range}")
    score = shop.get("score")
    if score is not None:
        parts.append(f"Platform rating: {score / 10:g} out of 5")
    status = shop.get("businessStatus")
    if status:
        parts.append(f"Business status: {str(status).replace('_', ' ').lower()}")
    return ". ".join(parts or ["Merchant catalog attributes are available"]) + "."


def _content_provenance(shop: dict, field_name: str) -> dict:
    synthetic = field_name in set(shop.get("syntheticFields") or []) or (
        shop.get("sourceType") in (None, "MOCK", "LEGACY")
    )
    if synthetic:
        return _synthetic_content_provenance("HMDP deterministic NYC generator")
    return {
        "content_source_type": shop.get("sourceType") or "PUBLIC_SOURCE",
        "content_source_name": shop.get("sourceName"),
        "content_source_url": shop.get("sourceUrl"),
        "synthetic": False,
    }


def _identity_fact_provenance(shop: dict) -> dict:
    if shop.get("sourceType") in (None, "MOCK", "LEGACY"):
        return _synthetic_content_provenance("HMDP deterministic NYC generator")
    return {
        "content_source_type": shop.get("sourceType") or "PUBLIC_SOURCE",
        "content_source_name": shop.get("sourceName"),
        "content_source_url": shop.get("sourceUrl"),
        "synthetic": False,
    }


def _synthetic_content_provenance(source_name: str) -> dict:
    return {
        "content_source_type": "SYNTHETIC",
        "content_source_name": source_name,
        "content_source_url": None,
        "synthetic": True,
    }


def _record_content_provenance(record: dict, shop: dict, *, content_kind: str) -> dict:
    """Preserve the record's content source instead of inferring it from the shop.

    Historical generated fixtures did not carry a source field, so they retain
    the old synthetic fallback. P8 real-only bundles are stricter: every seeded
    blog and blog comment must explicitly declare SYNTHETIC.
    """

    raw_source_type = record.get("sourceType")
    real_only = str(shop.get("dataVersion") or "").startswith("nyc-real-")
    if real_only and raw_source_type != "SYNTHETIC":
        record_id = record.get("id")
        raise ValueError(
            f"nyc-real {content_kind} {record_id} must declare sourceType=SYNTHETIC."
        )
    if real_only and record.get("dataVersion") != shop.get("dataVersion"):
        record_id = record.get("id")
        raise ValueError(
            f"nyc-real {content_kind} {record_id} must match the merchant dataVersion."
        )

    source_type = str(raw_source_type or "SYNTHETIC").upper()
    if source_type == "SYNTHETIC":
        return _synthetic_content_provenance(f"HMDP synthetic {content_kind} generator")
    if source_type == "USER_SUBMITTED":
        return {
            "content_source_type": source_type,
            "content_source_name": "HMDP user-submitted content",
            "content_source_url": None,
            "synthetic": False,
        }
    return {
        "content_source_type": source_type,
        "content_source_name": f"HMDP {content_kind}",
        "content_source_url": None,
        "synthetic": False,
    }


def _shop_provenance(shop: dict) -> dict:
    return {
        "shop_source_type": shop.get("sourceType") or "MOCK",
        "shop_external_id": shop.get("externalId"),
        "shop_source_name": shop.get("sourceName"),
        "shop_source_url": shop.get("sourceUrl"),
        "shop_source_fetched_at": shop.get("sourceFetchedAt"),
        "synthetic_fields": shop.get("syntheticFields") or [],
    }
