import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.domain.models import AgentRunRequest, UserConstraints
from app.runtime import AgentRuntime, _validate_data_directory

GENERATOR_PATH = Path(__file__).parents[2] / "scripts" / "mock-data-generator" / "generate.py"
sys.path.insert(0, str(GENERATOR_PATH.parent))
SPEC = importlib.util.spec_from_file_location("runtime_test_nyc_generator", GENERATOR_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = GENERATOR
SPEC.loader.exec_module(GENERATOR)


def _write_json(path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_real_only_bundle(
    path: Path,
    *,
    first_source_type: str = "OPENSTREETMAP",
    image_mode: str | None = None,
) -> None:
    shops = []
    for type_id in range(1, 7):
        shops.append(
            {
                "id": type_id,
                "typeId": type_id,
                "name": f"Real merchant {type_id}",
                "sourceType": first_source_type if type_id == 1 else "OPENSTREETMAP",
                "externalId": f"node:{type_id}",
                "sourceName": "OpenStreetMap contributors",
                "sourceUrl": f"https://www.openstreetmap.org/node/{type_id}",
                "sourceFetchedAt": "2026-08-23T12:00:00Z",
                "syntheticFields": (
                    ["reviews"] if image_mode in {"merchant", "illustrative_missing"}
                    else ["images", "reviews"]
                ),
                "dataVersion": "nyc-real-v1",
            }
        )
    values = {
        "shops.json": shops,
        "shop_reviews.json": [],
        "blogs.json": [],
        "blog_comments.json": [],
    }
    if image_mode is not None:
        values["shop_images.json"] = [
            {
                "id": type_id,
                "shopId": type_id,
                "imageType": "MERCHANT_SPECIFIC" if image_mode == "merchant" else "ILLUSTRATIVE",
                "matchType": "OFFICIAL_SITE_IMAGE" if image_mode == "merchant" else "CATEGORY_FALLBACK",
                "url": f"https://images.example/{type_id}.jpg",
            }
            for type_id in range(1, 7)
        ]
    dataset_files = {}
    for filename, value in values.items():
        _write_json(path / filename, value)
        dataset_files[filename] = {
            "sha256": hashlib.sha256((path / filename).read_bytes()).hexdigest()
        }
    dataset_sha256 = hashlib.sha256(
        json.dumps(dataset_files, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    source_counts = {"OPENSTREETMAP": 6}
    if first_source_type != "OPENSTREETMAP":
        source_counts = {first_source_type: 1, "OPENSTREETMAP": 5}
    shop_ids = list(range(1, 7))
    _write_json(
        path / "import_manifest.json",
        {
            "dataVersion": "nyc-real-v1",
            "merchantIdentityMode": "REAL_ONLY",
            "datasetFiles": dataset_files,
            "datasetSha256": dataset_sha256,
            "shopIds": shop_ids,
            "shopIdsSha256": hashlib.sha256(
                json.dumps(shop_ids, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "provenance": {
                "merchantIdentityMode": "REAL_ONLY",
                "mockShops": 0 if first_source_type != "MOCK" else 1,
                "realShops": 6 if first_source_type != "MOCK" else 5,
                "sourceCounts": source_counts,
            },
        },
    )


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

        assert runtime.indexed_documents == 18
        assert state["verification"].valid is True
        assert all(item.citations for item in state["evidence"].evidence)
        assert {
            citation.content_type for item in state["evidence"].evidence for citation in item.citations
        } <= {
            "shop_identity_fact",
            "shop_attribute_fact",
            "shop_description",
            "shop_review",
            "blog",
            "blog_comment",
            "nested_comment",
        }
    finally:
        await runtime.close()


def test_dataset_identity_rejects_tampered_generated_file(tmp_path):
    GENERATOR.generate_dataset("small", 20260817, tmp_path)
    reviews_path = tmp_path / "shop_reviews.json"
    reviews = json.loads(reviews_path.read_text())
    reviews[0]["content"] = "tampered after manifest generation"
    _write_json(reviews_path, reviews)

    with pytest.raises(ValueError, match="checksum"):
        _validate_data_directory(tmp_path)


def test_real_only_dataset_requires_traceable_non_mock_merchants_in_all_six_categories(tmp_path):
    _write_real_only_bundle(tmp_path)

    data_version, dataset_sha256, source_counts = _validate_data_directory(tmp_path)

    assert data_version == "nyc-real-v1"
    assert dataset_sha256
    assert source_counts == {"OPENSTREETMAP": 6}


def test_real_only_dataset_accepts_merchant_images_without_synthetic_image_disclosure(tmp_path):
    _write_real_only_bundle(tmp_path, image_mode="merchant")

    data_version, dataset_sha256, source_counts = _validate_data_directory(tmp_path)

    assert data_version == "nyc-real-v1"
    assert dataset_sha256
    assert source_counts == {"OPENSTREETMAP": 6}


def test_real_only_dataset_requires_disclosure_for_illustrative_images(tmp_path):
    _write_real_only_bundle(tmp_path, image_mode="illustrative_missing")

    with pytest.raises(ValueError, match="illustrative images"):
        _validate_data_directory(tmp_path)


def test_real_only_dataset_rejects_a_mock_merchant_even_when_manifest_matches(tmp_path):
    _write_real_only_bundle(tmp_path, first_source_type="MOCK")

    with pytest.raises(ValueError, match="non-real merchant sources"):
        _validate_data_directory(tmp_path)


def test_real_only_dataset_rejects_an_unapproved_source_label(tmp_path):
    _write_real_only_bundle(tmp_path, first_source_type="FAKE_REAL")

    with pytest.raises(ValueError, match="non-real merchant sources"):
        _validate_data_directory(tmp_path)
