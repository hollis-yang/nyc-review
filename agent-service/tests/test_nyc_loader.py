import importlib.util
import sys
import tempfile
from pathlib import Path

from app.rag.nyc_loader import load_generated_documents

GENERATOR_PATH = Path(__file__).parents[2] / "scripts" / "mock-data-generator" / "generate.py"
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
