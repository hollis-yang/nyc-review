#!/usr/bin/env python3
"""Fail-closed verification for the frozen M3 production Qdrant collection."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
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


def _request(
    base_url: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
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
        raise RuntimeError(
            f"Qdrant request failed for {path}: {type(exc).__name__}"
        ) from exc
    if result.get("status") not in {None, "ok"}:
        raise RuntimeError(f"Qdrant returned a non-ok status for {path}.")
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _safe_text(value: Any, *, limit: int = 500) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _optimizer_status(value: Any) -> str:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, dict):
        if value.get("error"):
            return "error"
        return "unknown"
    return str(value or "unknown").casefold()


def _safe_collection_state(collection: dict[str, Any]) -> dict[str, Any]:
    optimizer = collection.get("optimizer_status")
    update_queue = collection.get("update_queue")
    queue_length = (
        int(update_queue.get("length", 0) or 0)
        if isinstance(update_queue, dict) and "length" in update_queue
        else None
    )
    state: dict[str, Any] = {
        "status": str(collection.get("status") or "unknown").casefold(),
        "optimizerStatus": _optimizer_status(optimizer),
        "updateQueueLength": queue_length,
        "pointsCount": int(collection.get("points_count", 0) or 0),
        "indexedVectorsCount": int(collection.get("indexed_vectors_count", 0) or 0),
        "segmentsCount": int(collection.get("segments_count", 0) or 0),
    }
    if isinstance(optimizer, dict) and optimizer.get("error"):
        state["optimizerError"] = _safe_text(optimizer["error"])
    return state


def _safe_optimization(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"status": "unavailable"}
    progress = item.get("progress") or {}
    safe_progress = {
        key: progress[key]
        for key in ("name", "done", "total", "duration_sec")
        if isinstance(progress, dict) and key in progress
    }
    result: dict[str, Any] = {
        "optimizer": _safe_text(item.get("optimizer") or "unknown", limit=100),
        "status": _safe_text(item.get("status") or "unknown", limit=100),
        "segmentCount": len(item.get("segments") or []),
    }
    if safe_progress:
        result["progress"] = safe_progress
    return result


def _safe_readiness_diagnostics(
    base_url: str,
    collection_state: dict[str, Any],
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {"collection": collection_state}
    try:
        result = (
            _request(
                base_url,
                f"/collections/{COLLECTION}/optimizations?with=queued",
            ).get("result")
            or {}
        )
        summary = result.get("summary") if isinstance(result, dict) else None
        running = result.get("running") if isinstance(result, dict) else None
        queued = result.get("queued") if isinstance(result, dict) else None
        diagnostics["optimizations"] = {
            "summary": summary if isinstance(summary, dict) else {},
            "running": [_safe_optimization(item) for item in (running or [])[:8]],
            "queued": [_safe_optimization(item) for item in (queued or [])[:8]],
            "runningCount": len(running or []),
            "queuedCount": len(queued or []),
        }
    except RuntimeError as exc:
        diagnostics["optimizations"] = {"requestError": _safe_text(exc)}
    return diagnostics


def wait_until_ready(
    base_url: str,
    *,
    wait_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if wait_seconds < 0:
        raise ValueError("wait_seconds cannot be negative.")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive.")

    deadline = monotonic() + wait_seconds
    previous_state: dict[str, Any] | None = None
    latest_state: dict[str, Any] = {"status": "unavailable"}
    while True:
        try:
            collection = (
                _request(base_url, f"/collections/{COLLECTION}").get("result") or {}
            )
            latest_state = _safe_collection_state(collection)
        except RuntimeError as exc:
            collection = {}
            latest_state = {
                "status": "unavailable",
                "requestError": _safe_text(exc),
            }

        if latest_state != previous_state:
            print(
                "M3 Qdrant readiness: " + json.dumps(latest_state, sort_keys=True),
                file=sys.stderr,
            )
            if latest_state.get("status") == "grey":
                print(
                    "M3 Qdrant is grey; waiting without sending an optimizer-triggering update.",
                    file=sys.stderr,
                )
            previous_state = latest_state

        status = latest_state.get("status")
        optimizer_ready = latest_state.get("optimizerStatus") == "ok"
        queue_empty = latest_state.get("updateQueueLength") == 0
        if status == "green" and optimizer_ready and queue_empty:
            return collection

        if status == "red":
            diagnostics = _safe_readiness_diagnostics(base_url, latest_state)
            raise RuntimeError(
                "M3 collection entered red state: "
                + json.dumps(diagnostics, sort_keys=True)
            )
        if latest_state.get("optimizerStatus") == "error":
            diagnostics = _safe_readiness_diagnostics(base_url, latest_state)
            raise RuntimeError(
                "M3 collection optimizer entered error state: "
                + json.dumps(diagnostics, sort_keys=True)
            )

        now = monotonic()
        if now >= deadline:
            diagnostics = _safe_readiness_diagnostics(base_url, latest_state)
            raise RuntimeError(
                f"M3 collection did not become ready within {wait_seconds:g} seconds: "
                + json.dumps(diagnostics, sort_keys=True)
            )
        sleep(min(poll_seconds, deadline - now))


def verify(
    base_url: str,
    *,
    wait_seconds: float = 0,
    poll_seconds: float = 2,
) -> dict[str, Any]:
    root = _request(base_url, "/")
    _require(root.get("version") == QDRANT_VERSION, "Unexpected Qdrant server version.")

    collection = wait_until_ready(
        base_url,
        wait_seconds=wait_seconds,
        poll_seconds=poll_seconds,
    )
    _require(collection.get("status") == "green", "M3 collection is not green.")
    _require(
        collection.get("optimizer_status") == "ok",
        "M3 collection optimizer is not ready.",
    )
    _require(
        collection.get("points_count") == POINTS, "M3 collection point count mismatch."
    )
    _require(
        (collection.get("update_queue") or {}).get("length", 0) == 0,
        "M3 update queue is not empty.",
    )

    config = collection.get("config") or {}
    params = config.get("params") or {}
    dense = (params.get("vectors") or {}).get("dense") or {}
    lexical = (params.get("sparse_vectors") or {}).get("lexical") or {}
    _require(dense.get("size") == 1024, "M3 dense vector dimension mismatch.")
    _require(
        str(dense.get("distance", "")).casefold() == "cosine",
        "M3 dense distance mismatch.",
    )
    _require(
        str(lexical.get("modifier", "")).casefold() == "idf",
        "M3 sparse modifier mismatch.",
    )
    _require(
        config.get("quantization_config") is None,
        "M3 snapshot unexpectedly uses quantization.",
    )

    payload_schema = collection.get("payload_schema") or {}
    for field, expected_type in PAYLOAD_SCHEMA.items():
        actual_type = (payload_schema.get(field) or {}).get("data_type")
        _require(
            actual_type == expected_type, f"M3 payload index mismatch for {field}."
        )

    count_result = _request(
        base_url,
        f"/collections/{COLLECTION}/points/count",
        {"exact": True},
    )
    _require(
        (count_result.get("result") or {}).get("count") == POINTS,
        "Exact point count mismatch.",
    )

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
    parser.add_argument("--wait-seconds", type=float, default=0)
    parser.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args()
    if args.wait_seconds < 0:
        parser.error("--wait-seconds cannot be negative")
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    try:
        result = verify(
            args.url,
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
        )
    except RuntimeError as exc:
        print(f"M3 Qdrant verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
