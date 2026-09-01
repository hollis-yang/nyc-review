from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.rag.reranker import HttpCrossEncoderReranker
from app.runtime import _build_reranker, _qwen_reranker_base_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _global_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "rag_adapter": "qdrant",
        "rag_data_directory": tmp_path,
        "global_retrieval_enabled": True,
        "reranker_provider": "qwen",
    }
    values.update(overrides)
    return Settings(**values)


def test_m4_reranker_defaults_off_and_requires_global_retrieval(tmp_path):
    defaults = Settings()
    assert defaults.reranker_provider == "disabled"
    assert "reranker_max_total_tokens" not in defaults.model_dump()

    with pytest.raises(ValueError, match="requires global retrieval"):
        Settings(reranker_provider="qwen")

    settings = _global_settings(tmp_path)
    assert settings.reranker_model == "qwen3-rerank"
    assert settings.reranker_candidate_limit == 30


def test_m4_reranker_model_and_candidate_bounds_are_validated(tmp_path):
    with pytest.raises(ValueError, match="requires reranker_model=qwen3-rerank"):
        _global_settings(tmp_path, reranker_model="another-model")

    with pytest.raises(ValueError, match="at least max_candidates"):
        _global_settings(tmp_path, max_candidates=10, reranker_candidate_limit=9)

    with pytest.raises(ValueError, match="cannot exceed global retrieval fusion_pool_limit"):
        _global_settings(
            tmp_path,
            global_retrieval_fusion_pool_limit=20,
            reranker_candidate_limit=21,
        )


def test_production_compose_keeps_m4_disabled():
    compose = (PROJECT_ROOT / "compose.production.yml").read_text(encoding="utf-8")
    checker = (PROJECT_ROOT / "scripts/deploy/check-production-config.sh").read_text(
        encoding="utf-8"
    )

    expected = 'NYC_REVIEW_AGENT_RERANKER_PROVIDER: "disabled"'
    assert expected in compose
    assert '"NYC_REVIEW_AGENT_RERANKER_PROVIDER": "disabled"' in checker


def test_qwen_reranker_url_is_derived_only_from_workspace_compatible_url():
    assert _qwen_reranker_base_url(
        "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/"
    ) == "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-api/v1"
    assert _qwen_reranker_base_url(
        "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-api/v1"
    ) == "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-api/v1"

    with pytest.raises(ValueError, match="RERANKER_BASE_URL"):
        _qwen_reranker_base_url("https://api.openai.com/v1")


async def test_runtime_builds_qwen_reranker_from_existing_dashscope_secret(tmp_path):
    reranker = _build_reranker(
        _global_settings(
            tmp_path,
            qwen_embedding_base_url=(
                "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
            ),
            qwen_embedding_api_key="shared-secret",
            reranker_api_key="",
            reranker_version="qwen3-rerank-2026-09-01",
        )
    )
    try:
        assert isinstance(reranker, HttpCrossEncoderReranker)
        assert "shared-secret" not in repr(reranker)
    finally:
        assert reranker is not None
        await reranker.aclose()


def test_runtime_rejects_enabled_qwen_reranker_without_credentials(tmp_path):
    settings = _global_settings(
        tmp_path,
        reranker_base_url="https://workspace.example.test/compatible-api/v1",
        reranker_api_key="",
        qwen_embedding_api_key="",
    )

    with pytest.raises(ValueError, match="requires a configured .* API key"):
        _build_reranker(settings)
