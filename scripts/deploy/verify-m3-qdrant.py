#!/usr/bin/env python3
"""Fail-closed verification for the frozen M3 production Qdrant collection."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


COLLECTION = "nyc_review_content_v3_dashscope_qwen37_1024_v1"
POINTS = 145_000
QDRANT_VERSION = "1.19.0"
DATA_VERSION = "nyc-real-v5-8b645404-m20260824"
DATASET_SHA256 = "0bb014f6a2e0608a6437c09fc32ac0a6f0791599e988099466e80d272750f238"
EMBEDDING_IDENTITY = "732f1c0dcbcb6155a99794809c0d8f8dc26385ec844c1c5f42fc0b55529fc511"
EMBEDDING_VERSION = "qwen3.7-text-embedding-1024-m1-v1"
RETRIEVAL_VERSION = "p12-rag-v1"
INDEX_SCOPE = (
    f"{DATA_VERSION}:{DATASET_SHA256}:{EMBEDDING_IDENTITY}:{RETRIEVAL_VERSION}"
)
IDENTITY_FIELDS = {
    "data_version": DATA_VERSION,
    "dataset_sha256": DATASET_SHA256,
    "embedding_identity": EMBEDDING_IDENTITY,
    "embedding_version": EMBEDDING_VERSION,
    "retrieval_version": RETRIEVAL_VERSION,
    "index_scope": INDEX_SCOPE,
}
PAYLOAD_SCHEMA = {
    "shop_id": "integer",
    "data_version": "keyword",
    "dataset_sha256": "keyword",
    "content_type": "keyword",
    "document_kind": "keyword",
    "category": "keyword",
    "borough": "keyword",
    "neighborhood": "keyword",
    "security_test": "bool",
    "retrieval_version": "keyword",
    "shop_external_id": "keyword",
    "root_id": "integer",
    "index_scope": "keyword",
    "embedding_identity": "keyword",
    "embedding_version": "keyword",
}


def _request(base_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Qdrant request failed for {path}: {type(exc).__name__}") from exc
    if result.get("status") not in {None, "ok"}:
        raise RuntimeError(f"Qdrant returned a non-ok status for {path}.")
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify(base_url: str) -> dict[str, Any]:
    root = _request(base_url, "/")
    _require(root.get("version") == QDRANT_VERSION, "Unexpected Qdrant server version.")

    collection = _request(base_url, f"/collections/{COLLECTION}").get("result") or {}
    _require(collection.get("status") == "green", "M3 collection is not green.")
    _require(collection.get("optimizer_status") == "ok", "M3 collection optimizer is not ready.")
    _require(collection.get("points_count") == POINTS, "M3 collection point count mismatch.")
    _require((collection.get("update_queue") or {}).get("length", 0) == 0, "M3 update queue is not empty.")

    config = collection.get("config") or {}
    params = config.get("params") or {}
    dense = (params.get("vectors") or {}).get("dense") or {}
    lexical = (params.get("sparse_vectors") or {}).get("lexical") or {}
    _require(dense.get("size") == 1024, "M3 dense vector dimension mismatch.")
    _require(str(dense.get("distance", "")).casefold() == "cosine", "M3 dense distance mismatch.")
    _require(str(lexical.get("modifier", "")).casefold() == "idf", "M3 sparse modifier mismatch.")
    _require(config.get("quantization_config") is None, "M3 snapshot unexpectedly uses quantization.")

    payload_schema = collection.get("payload_schema") or {}
    for field, expected_type in PAYLOAD_SCHEMA.items():
        actual_type = (payload_schema.get(field) or {}).get("data_type")
        _require(actual_type == expected_type, f"M3 payload index mismatch for {field}.")

    count_result = _request(
        base_url,
        f"/collections/{COLLECTION}/points/count",
        {"exact": True},
    )
    _require((count_result.get("result") or {}).get("count") == POINTS, "Exact point count mismatch.")

    for field, value in IDENTITY_FIELDS.items():
        result = _request(
            base_url,
            f"/collections/{COLLECTION}/points/count",
            {
                "filter": {
                    "must": [
                        {
                            "key": field,
                            "match": {"value": value},
                        }
                    ]
                },
                "exact": True,
            },
        )
        count = (result.get("result") or {}).get("count")
        _require(count == POINTS, f"M3 identity coverage mismatch for {field}.")

    return {
        "status": "ok",
        "qdrantVersion": QDRANT_VERSION,
        "collection": COLLECTION,
        "points": POINTS,
        "dimensions": 1024,
        "embeddingIdentity": EMBEDDING_IDENTITY,
        "retrievalVersion": RETRIEVAL_VERSION,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    try:
        result = verify(args.url)
    except RuntimeError as exc:
        print(f"M3 Qdrant verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
