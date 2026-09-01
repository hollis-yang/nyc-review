#!/usr/bin/env python3
"""Execute one paid, end-to-end M3 production canary and reject fallback."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


EXPECTED_DATASET_SHA256 = "0bb014f6a2e0608a6437c09fc32ac0a6f0791599e988099466e80d272750f238"
EXPECTED_RETRIEVAL_VERSION = "p12-rag-v1"
EXPECTED_REWRITE_MODEL = "gpt-4o-mini-2024-07-18"


def _request(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Agent canary request failed: {type(exc).__name__}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify(base_url: str) -> dict[str, Any]:
    health = _request(f"{base_url.rstrip('/')}/health")
    _require(health.get("status") == "ok", "Agent health is not ok.")
    _require(health.get("rag") == "qdrant", "Agent is not using Qdrant.")
    _require(health.get("globalRetrieval") == "enabled", "Global retrieval is disabled.")
    _require(health.get("queryRewrite") == "openai", "OpenAI query rewrite is disabled.")
    _require(health.get("reranker") == "disabled", "The rejected M4 reranker is enabled.")

    response = _request(
        f"{base_url.rstrip('/')}/v1/agent/runs/preview",
        {
            "mode": "single",
            "constraints": {
                "query": "想找曼哈顿中城安静、适合约会、而且有纯素选择的餐厅，不要吵闹的酒吧",
                "latitude": 40.7549,
                "longitude": -73.9840,
                "neighborhood": "Midtown",
                "party_size": 2,
                "budget_cents": 12000,
                "result_limit": 5,
            },
        },
    )
    metadata = response.get("metadata") or {}
    index_stats = metadata.get("ragIndexStats") or {}
    retrieval = metadata.get("retrieval") or {}
    candidates_metadata = retrieval.get("candidates") or {}

    _require(metadata.get("indexedDocuments") == 145_000, "Runtime indexed-document count mismatch.")
    _require(metadata.get("datasetSha256") == EXPECTED_DATASET_SHA256, "Runtime dataset identity mismatch.")
    _require(
        metadata.get("retrievalVersion") == EXPECTED_RETRIEVAL_VERSION,
        "Runtime retrieval version mismatch.",
    )
    _require(
        index_stats
        == {
            "total": 145_000,
            "upserted": 0,
            "unchanged": 145_000,
            "deleted": 0,
        },
        "Production startup did not perform an exact read-only index reuse.",
    )
    _require(
        candidates_metadata.get("candidateDiscoveryMode") == "global-hybrid",
        "Canary did not use global-hybrid candidate discovery.",
    )
    _require(
        candidates_metadata.get("queryRewriteProvider") == "openai"
        and candidates_metadata.get("queryRewriteEffectiveProvider") == "openai",
        "Canary did not use the requested OpenAI rewrite provider.",
    )
    _require(
        candidates_metadata.get("queryRewriteModel") == EXPECTED_REWRITE_MODEL
        and candidates_metadata.get("queryRewriteEffectiveModel") == EXPECTED_REWRITE_MODEL,
        "Canary rewrite model identity mismatch.",
    )
    _require(
        candidates_metadata.get("queryRewriteFallback") is False,
        "Canary silently fell back from LLM query rewrite.",
    )
    _require(
        int(candidates_metadata.get("queryRewriteCount") or 0) >= 1,
        "Canary produced no LLM query rewrites.",
    )
    _require(
        int(candidates_metadata.get("queryRewriteNetworkRequests") or 0) >= 1
        or candidates_metadata.get("queryRewriteCacheHit") is True,
        "Canary neither called the rewrite provider nor reused a verified cache entry.",
    )
    _require(
        candidates_metadata.get("globalDenseAvailable") is True
        and candidates_metadata.get("globalSparseAvailable") is True,
        "Canary did not execute both dense and sparse global retrieval.",
    )
    _require(
        not candidates_metadata.get("globalQueryVariantFailedIds")
        and not candidates_metadata.get("globalQueryVariantTimedOutIds"),
        "One or more canary query variants failed or timed out.",
    )

    candidates = ((response.get("candidates") or {}).get("candidates") or [])
    evidence = ((response.get("evidence") or {}).get("evidence") or [])
    _require(bool(candidates), "Canary returned no merchants.")
    _require(
        len({item.get("shop_id") for item in candidates}) == len(candidates),
        "Canary returned duplicate merchants.",
    )
    _require(
        all(item.get("citations") for item in evidence),
        "Canary evidence coverage is incomplete.",
    )
    _require((response.get("verification") or {}).get("valid") is True, "Canary verification failed.")

    return {
        "status": "ok",
        "candidateCount": len(candidates),
        "evidenceMerchantCount": len(evidence),
        "rewriteCount": candidates_metadata.get("queryRewriteCount"),
        "queryVariantCount": candidates_metadata.get("globalQueryVariantCount"),
        "queryRewriteLatencyMs": candidates_metadata.get("queryRewriteLatencyMs"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8090")
    args = parser.parse_args()
    try:
        result = verify(args.url)
    except RuntimeError as exc:
        print(f"M3 runtime canary failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
