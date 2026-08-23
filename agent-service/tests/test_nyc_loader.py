import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

from app.rag.nyc_loader import load_generated_documents

GENERATOR_PATH = Path(__file__).parents[2] / "scripts" / "mock-data-generator" / "generate.py"
SNAPSHOT_PATH = Path(__file__).parents[2] / "data" / "sources" / "nyc-open-data-restaurants-2026-08-23.json"
sys.path.insert(0, str(GENERATOR_PATH.parent))
SPEC = importlib.util.spec_from_file_location("agent_test_nyc_generator", GENERATOR_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = GENERATOR
SPEC.loader.exec_module(GENERATOR)


def test_generated_nyc_content_is_loadable_as_rag_documents():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        GENERATOR.generate_dataset("small", 20260817, output)

        documents = load_generated_documents(output)
        import_manifest = json.loads((output / "import_manifest.json").read_text())

        assert len(documents) == 36 + 144 + 48 + 96
        assert {document.content_type for document in documents} == {
            "shop_description",
            "shop_review",
            "blog",
            "blog_comment",
            "nested_comment",
        }
        assert all(document.shop_id > 0 for document in documents)
        assert all(document.source_id for document in documents)
        assert {document.shop_id for document in documents} == set(import_manifest["shopIds"])
        assert {document.data_version for document in documents} == {import_manifest["dataVersion"]}
        assert {document.content_source_type for document in documents} == {"SYNTHETIC"}
        assert {document.shop_source_type for document in documents} == {"MOCK"}
        assert all(document.synthetic_fields for document in documents)


def test_hybrid_shop_provenance_is_written_to_rag_payloads(tmp_path):
    GENERATOR.generate_dataset(
        "small",
        20260817,
        tmp_path,
        real_shops_path=SNAPSHOT_PATH,
    )

    documents = load_generated_documents(tmp_path)
    public_documents = [
        document for document in documents if document.shop_source_type == "NYC_OPEN_DATA"
    ]

    assert public_documents
    assert all(document.content_source_type == "SYNTHETIC" for document in public_documents)
    assert all(document.shop_external_id.startswith("43nn-pn8j:") for document in public_documents)
    assert all(document.shop_source_url for document in public_documents)
    assert all("reviews" in document.synthetic_fields for document in public_documents)


def test_real_shop_description_and_hierarchical_synthetic_review_keep_distinct_provenance(
    tmp_path,
):
    shops = [
        {
            "id": 501,
            "typeId": 4,
            "neighborhood": "Flushing Meadows-Corona Park",
            "description": "A public cultural institution profile.",
            "sourceType": "OPENSTREETMAP",
            "externalId": "node:501",
            "sourceName": "OpenStreetMap contributors",
            "sourceUrl": "https://www.openstreetmap.org/node/501",
            "sourceFetchedAt": "2026-08-23T12:00:00Z",
            "syntheticFields": ["images", "reviews"],
            "dataVersion": "nyc-real-v1",
        }
    ]
    reviews = [
        {
            "id": 700,
            "shopId": 501,
            "userId": 1,
            "rootId": 700,
            "parentId": 0,
            "depth": 0,
            "replyToUserId": None,
            "rating": 5,
            "content": "A synthetic top-level review about accessibility.",
            "language": "en",
            "sentiment": "POSITIVE",
            "topicTags": ["accessibility"],
            "evidenceTags": ["wheelchair_accessible"],
            "sourceType": "SYNTHETIC",
            "securityTest": False,
            "createTime": "2026-08-01T12:00:00Z",
        },
        {
            "id": 701,
            "shopId": 501,
            "userId": 2,
            "rootId": 700,
            "parentId": 700,
            "depth": 1,
            "replyToUserId": 1,
            "rating": None,
            "content": "[Synthetic demo reply] A reply with useful context.",
            "language": "en",
            "sentiment": "NEUTRAL",
            "topicTags": ["accessibility"],
            "evidenceTags": [],
            "sourceType": "SYNTHETIC",
            "securityTest": False,
            "createTime": "2026-08-01T13:00:00Z",
        },
        {
            "id": 702,
            "shopId": 501,
            "userId": 1,
            "rootId": 700,
            "parentId": 701,
            "depth": 2,
            "replyToUserId": 2,
            "rating": None,
            "content": "A synthetic final reply.",
            "language": "en",
            "sentiment": "POSITIVE",
            "topicTags": ["service"],
            "evidenceTags": [],
            "sourceType": "SYNTHETIC",
            "securityTest": True,
            "createTime": "2026-08-01T14:00:00Z",
        },
    ]
    for filename, value in (
        ("shops.json", shops),
        ("shop_reviews.json", reviews),
        ("blogs.json", []),
        ("blog_comments.json", []),
    ):
        (tmp_path / filename).write_text(json.dumps(value), encoding="utf-8")

    documents = load_generated_documents(tmp_path)

    assert len(documents) == 2
    description = next(document for document in documents if document.content_type == "shop_description")
    thread = next(document for document in documents if document.content_type == "shop_review_thread")
    assert description.content_source_type == "OPENSTREETMAP"
    assert description.content_source_name == "OpenStreetMap contributors"
    assert description.content_source_url == "https://www.openstreetmap.org/node/501"
    assert description.synthetic is False
    assert thread.content_source_type == "SYNTHETIC"
    assert thread.synthetic is True
    assert thread.root_id == 700
    assert thread.max_depth == 2
    assert thread.reply_count == 2
    assert thread.security_test is True
    assert thread.topic_tags == ["accessibility", "service"]
    assert "top-level review" in thread.text
    assert "useful context" in thread.text
    assert "final reply" in thread.text
    assert "Synthetic demo" not in thread.text
    assert "Level" not in thread.text


def test_real_only_blogs_and_comments_use_declared_synthetic_content_source(tmp_path):
    shop = {
        "id": 501,
        "typeId": 4,
        "neighborhood": "Flushing Meadows-Corona Park",
        "description": "A public cultural institution profile.",
        "sourceType": "OPENSTREETMAP",
        "externalId": "node:501",
        "sourceName": "OpenStreetMap contributors",
        "sourceUrl": "https://www.openstreetmap.org/node/501",
        "sourceFetchedAt": "2026-08-23T12:00:00Z",
        "syntheticFields": ["images", "reviews", "blogs"],
        "dataVersion": "nyc-real-v1",
    }
    blog = {
        "id": 800,
        "shopId": 501,
        "title": "Synthetic visit note",
        "content": "Generated blog evidence.",
        "sourceType": "SYNTHETIC",
        "dataVersion": "nyc-real-v1",
        "createTime": "2026-08-02T12:00:00Z",
    }
    comment = {
        "id": 900,
        "blogId": 800,
        "parentId": 0,
        "content": "Generated discussion evidence.",
        "sourceType": "SYNTHETIC",
        "dataVersion": "nyc-real-v1",
        "createTime": "2026-08-03T12:00:00Z",
    }
    for filename, value in (
        ("shops.json", [shop]),
        ("shop_reviews.json", []),
        ("blogs.json", [blog]),
        ("blog_comments.json", [comment]),
    ):
        (tmp_path / filename).write_text(json.dumps(value), encoding="utf-8")

    documents = load_generated_documents(tmp_path)
    seeded_content = [
        document
        for document in documents
        if document.content_type in {"blog", "blog_comment"}
    ]

    assert len(seeded_content) == 2
    assert {document.content_source_type for document in seeded_content} == {"SYNTHETIC"}
    assert all(document.synthetic for document in seeded_content)


def test_loader_preserves_user_submitted_blog_and_comment_provenance(tmp_path):
    shop = {
        "id": 42,
        "typeId": 1,
        "neighborhood": "Midtown",
        "description": "A test shop.",
        "sourceType": "MOCK",
        "externalId": "mock:42",
        "sourceName": "HMDP",
        "syntheticFields": ["description", "images", "reviews"],
        "dataVersion": "nyc-mock-v2",
    }
    blog = {
        "id": 80,
        "shopId": 42,
        "title": "A user note",
        "content": "Submitted through the product API.",
        "sourceType": "USER_SUBMITTED",
    }
    comment = {
        "id": 90,
        "blogId": 80,
        "parentId": 0,
        "content": "A user response.",
        "sourceType": "USER_SUBMITTED",
    }
    for filename, value in (
        ("shops.json", [shop]),
        ("shop_reviews.json", []),
        ("blogs.json", [blog]),
        ("blog_comments.json", [comment]),
    ):
        (tmp_path / filename).write_text(json.dumps(value), encoding="utf-8")

    documents = load_generated_documents(tmp_path)
    submitted = [
        document
        for document in documents
        if document.content_type in {"blog", "blog_comment"}
    ]

    assert len(submitted) == 2
    assert {document.content_source_type for document in submitted} == {"USER_SUBMITTED"}
    assert all(not document.synthetic for document in submitted)


@pytest.mark.parametrize(
    ("filename", "invalid_source", "message"),
    [
        ("blogs.json", "USER_SUBMITTED", "nyc-real blog 800"),
        ("blog_comments.json", None, "nyc-real blog comment 900"),
    ],
)
def test_real_only_loader_rejects_non_synthetic_or_unlabeled_seed_content(
    tmp_path,
    filename,
    invalid_source,
    message,
):
    shop = {
        "id": 501,
        "typeId": 4,
        "neighborhood": "Flushing Meadows-Corona Park",
        "description": "A public cultural institution profile.",
        "sourceType": "OPENSTREETMAP",
        "externalId": "node:501",
        "sourceName": "OpenStreetMap contributors",
        "sourceUrl": "https://www.openstreetmap.org/node/501",
        "sourceFetchedAt": "2026-08-23T12:00:00Z",
        "syntheticFields": ["images", "reviews", "blogs"],
        "dataVersion": "nyc-real-v1",
    }
    blog = {
        "id": 800,
        "shopId": 501,
        "title": "Synthetic visit note",
        "content": "Generated blog evidence.",
        "sourceType": "SYNTHETIC",
        "dataVersion": "nyc-real-v1",
        "createTime": "2026-08-02T12:00:00Z",
    }
    comment = {
        "id": 900,
        "blogId": 800,
        "parentId": 0,
        "content": "Generated discussion evidence.",
        "sourceType": "SYNTHETIC",
        "dataVersion": "nyc-real-v1",
        "createTime": "2026-08-03T12:00:00Z",
    }
    target = blog if filename == "blogs.json" else comment
    if invalid_source is None:
        target.pop("sourceType")
    else:
        target["sourceType"] = invalid_source
    for output_name, value in (
        ("shops.json", [shop]),
        ("shop_reviews.json", []),
        ("blogs.json", [blog]),
        ("blog_comments.json", [comment]),
    ):
        (tmp_path / output_name).write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_generated_documents(tmp_path)


def test_real_only_loader_rejects_seed_content_from_another_data_version(tmp_path):
    shop = {
        "id": 501,
        "typeId": 4,
        "neighborhood": "Flushing Meadows-Corona Park",
        "description": "A public cultural institution profile.",
        "sourceType": "OPENSTREETMAP",
        "externalId": "node:501",
        "sourceName": "OpenStreetMap contributors",
        "sourceUrl": "https://www.openstreetmap.org/node/501",
        "sourceFetchedAt": "2026-08-23T12:00:00Z",
        "syntheticFields": ["images", "reviews", "blogs"],
        "dataVersion": "nyc-real-v1",
    }
    blog = {
        "id": 800,
        "shopId": 501,
        "title": "Synthetic visit note",
        "content": "Generated blog evidence.",
        "sourceType": "SYNTHETIC",
        "dataVersion": "nyc-real-other-version",
    }
    for filename, value in (
        ("shops.json", [shop]),
        ("shop_reviews.json", []),
        ("blogs.json", [blog]),
        ("blog_comments.json", []),
    ):
        (tmp_path / filename).write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="must match the merchant dataVersion"):
        load_generated_documents(tmp_path)
