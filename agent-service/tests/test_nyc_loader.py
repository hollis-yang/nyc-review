import importlib.util
import json
import sys
import tempfile
from pathlib import Path

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
