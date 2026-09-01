#!/usr/bin/env python3
"""Execute one paid, end-to-end M3 production canary and reject fallback."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.request
from http import HTTPStatus
from typing import Any

EXPECTED_DATASET_SHA256 = (
    "0bb014f6a2e0608a6437c09fc32ac0a6f0791599e988099466e80d272750f238"
)
EXPECTED_RETRIEVAL_VERSION = "p12-rag-v1"
EXPECTED_REWRITE_MODEL = "gpt-4o-mini-2024-07-18"
MAX_ERROR_BODY_BYTES = 4_096
MAX_DETAIL_JSON_CHARACTERS = 1_024
MAX_DETAIL_TEXT_CHARACTERS = 256
MAX_DETAIL_ITEMS = 8
MAX_DETAIL_DEPTH = 4
_SENSITIVE_KEY_PARTS = (
    "apikey",
    "authorization",
    "body",
    "cookie",
    "credential",
    "input",
    "password",
    "request",
    "secret",
    "token",
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:sk|rk|pk)-[a-z0-9_-]{8,}\b"),
    re.compile(
        r"(?i)\b(api[_ -]?key|authorization|cookie|credential|password|secret|token)"
        r"\b\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\b[a-z0-9_./+=-]{32,}\b"),
)


def _request(
    stage: str, url: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
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
    except urllib.error.HTTPError as exc:
        try:
            reason = HTTPStatus(exc.code).phrase
        except ValueError:
            reason = "Unknown HTTP status"
        detail = _safe_http_error_detail(exc)
        raise RuntimeError(
            f"Agent canary {stage} request failed: HTTP status={exc.code} "
            f"reason={json.dumps(reason, ensure_ascii=False)} detail={detail}"
        ) from None
    except urllib.error.URLError as exc:
        reason_type = type(exc.reason).__name__
        raise RuntimeError(
            f"Agent canary {stage} request failed: transport=URLError "
            f"reasonType={reason_type}"
        ) from None
    except TimeoutError:
        raise RuntimeError(
            f"Agent canary {stage} request failed: transport=TimeoutError"
        ) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError(
            f"Agent canary {stage} response failed: invalid JSON"
        ) from None


def _safe_http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        raw = error.read(MAX_ERROR_BODY_BYTES + 1)
    except (AttributeError, OSError, ValueError):
        return "null"
    if not raw:
        return "null"
    if len(raw) > MAX_ERROR_BODY_BYTES:
        return '{"truncated":true}'
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "null"
    if not isinstance(payload, dict) or "detail" not in payload:
        return "null"
    sanitized = _redact_json(payload["detail"])
    rendered = json.dumps(
        sanitized, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if len(rendered) <= MAX_DETAIL_JSON_CHARACTERS:
        return rendered
    preview_size = min(512, MAX_DETAIL_JSON_CHARACTERS // 2)
    truncated = json.dumps(
        {"preview": rendered[:preview_size], "truncated": True},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        truncated
        if len(truncated) <= MAX_DETAIL_JSON_CHARACTERS
        else '{"truncated":true}'
    )


def _redact_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_DETAIL_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[non-finite]"
    if isinstance(value, str):
        return _redact_text(value, max_characters=MAX_DETAIL_TEXT_CHARACTERS)
    if isinstance(value, list):
        redacted = [
            _redact_json(item, depth=depth + 1) for item in value[:MAX_DETAIL_ITEMS]
        ]
        if len(value) > MAX_DETAIL_ITEMS:
            redacted.append("[truncated]")
        return redacted
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        items = list(value.items())
        for raw_key, item in items[:MAX_DETAIL_ITEMS]:
            key = _redact_text(str(raw_key), max_characters=64)
            normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
            redacted[key] = (
                "[redacted]"
                if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS)
                else _redact_json(item, depth=depth + 1)
            )
        if len(items) > MAX_DETAIL_ITEMS:
            redacted["[truncated]"] = True
        return redacted
    return f"[{type(value).__name__}]"


def _redact_text(value: str, *, max_characters: int) -> str:
    sanitized = " ".join(value.split())
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    if len(sanitized) <= max_characters:
        return sanitized
    suffix = "...[truncated]"
    return sanitized[: max(0, max_characters - len(suffix))] + suffix


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify(base_url: str) -> dict[str, Any]:
    health = _request("health", f"{base_url.rstrip('/')}/health")
    _require(health.get("status") == "ok", "Agent health is not ok.")
    _require(health.get("rag") == "qdrant", "Agent is not using Qdrant.")
    _require(
        health.get("globalRetrieval") == "enabled", "Global retrieval is disabled."
    )
    _require(
        health.get("queryRewrite") == "openai", "OpenAI query rewrite is disabled."
    )
    _require(
        health.get("reranker") == "disabled", "The rejected M4 reranker is enabled."
    )

    response = _request(
        "preview",
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

    _require(
        metadata.get("indexedDocuments") == 145_000,
        "Runtime indexed-document count mismatch.",
    )
    _require(
        metadata.get("datasetSha256") == EXPECTED_DATASET_SHA256,
        "Runtime dataset identity mismatch.",
    )
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
        and candidates_metadata.get("queryRewriteEffectiveModel")
        == EXPECTED_REWRITE_MODEL,
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

    candidates = (response.get("candidates") or {}).get("candidates") or []
    evidence = (response.get("evidence") or {}).get("evidence") or []
    _require(bool(candidates), "Canary returned no merchants.")
    _require(
        len({item.get("shop_id") for item in candidates}) == len(candidates),
        "Canary returned duplicate merchants.",
    )
    _require(
        all(item.get("citations") for item in evidence),
        "Canary evidence coverage is incomplete.",
    )
    _require(
        (response.get("verification") or {}).get("valid") is True,
        "Canary verification failed.",
    )

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
