from __future__ import annotations

import importlib.util
import json
import unittest
import urllib.error
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).with_name("verify-m3-runtime.py")
SPEC = importlib.util.spec_from_file_location("verify_m3_runtime", SCRIPT_PATH)
assert SPEC and SPEC.loader
VERIFY_M3_RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY_M3_RUNTIME)


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


class VerifyM3RuntimeDiagnosticsTest(unittest.TestCase):
    def test_http_error_identifies_preview_and_redacts_bounded_json_detail(
        self,
    ) -> None:
        secret = "sk-super-secret-value-123456789"
        body = json.dumps(
            {
                "detail": {
                    "message": f"Provider rejected Bearer {secret}",
                    "api_key": secret,
                    "input": {"query": "must not echo the request"},
                    "safe": "authorization=top-secret " + "diagnostic text " * 60,
                    "unlabelled": "z" * 64,
                },
                "responseHeaderCopy": "must-not-be-read",
            }
        ).encode()
        error = urllib.error.HTTPError(
            url="https://request-url.example/secret-path",
            code=422,
            msg="Unprocessable Entity",
            hdrs={"X-Secret": "response-header-secret"},
            fp=BytesIO(body),
        )

        with (
            patch.object(
                VERIFY_M3_RUNTIME.urllib.request,
                "urlopen",
                side_effect=error,
            ),
            self.assertRaisesRegex(
                RuntimeError, "canary preview request failed"
            ) as raised,
        ):
            VERIFY_M3_RUNTIME._request(
                "preview",
                "https://request-url.example/secret-path",
                {"secret": "request-secret"},
            )

        message = str(raised.exception)
        self.assertIn("HTTP status=422", message)
        self.assertIn(f"reason={json.dumps(HTTPStatus(422).phrase)}", message)
        self.assertIn("detail=", message)
        self.assertIn("[redacted]", message)
        self.assertIn("[truncated]", message)
        for forbidden in (
            secret,
            "top-secret",
            "must not echo the request",
            "request-secret",
            "request-url.example",
            "response-header-secret",
            "must-not-be-read",
        ):
            self.assertNotIn(forbidden, message)
        detail = message.split(" detail=", 1)[1]
        json.loads(detail)
        self.assertLessEqual(len(detail), VERIFY_M3_RUNTIME.MAX_DETAIL_JSON_CHARACTERS)

    def test_url_error_identifies_health_without_exposing_reason_or_url(self) -> None:
        error = urllib.error.URLError(
            "connection to https://private.example failed with token=transport-secret"
        )

        with (
            patch.object(
                VERIFY_M3_RUNTIME.urllib.request,
                "urlopen",
                side_effect=error,
            ),
            self.assertRaisesRegex(
                RuntimeError, "canary health request failed"
            ) as raised,
        ):
            VERIFY_M3_RUNTIME._request("health", "https://private.example/health")

        message = str(raised.exception)
        self.assertIn("transport=URLError", message)
        self.assertIn("reasonType=str", message)
        self.assertNotIn("private.example", message)
        self.assertNotIn("transport-secret", message)

    def test_invalid_success_json_identifies_preview_without_echoing_body(self) -> None:
        invalid_body = b'{"detail":"Bearer sk-invalid-json-secret"'

        with (
            patch.object(
                VERIFY_M3_RUNTIME.urllib.request,
                "urlopen",
                return_value=_Response(invalid_body),
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "canary preview response failed: invalid JSON",
            ) as raised,
        ):
            VERIFY_M3_RUNTIME._request("preview", "http://127.0.0.1:8090/preview")

        self.assertNotIn("sk-invalid-json-secret", str(raised.exception))

    def test_rewrite_failure_reports_allowlisted_bounded_observed_diagnostics(
        self,
    ) -> None:
        secret = "sk-rewrite-secret-value-123456789"
        health = {
            "status": "ok",
            "rag": "qdrant",
            "globalRetrieval": "enabled",
            "queryRewrite": "openai",
            "reranker": "disabled",
        }
        candidates_metadata = {
            "candidateDiscoveryMode": "global-hybrid",
            "queryRewriteProvider": "openai",
            "queryRewriteEffectiveProvider": "disabled",
            "queryRewriteModel": "gpt-4o-mini-2024-07-18",
            "queryRewriteEffectiveModel": "rules-only",
            "queryRewriteFallback": True,
            "queryRewriteFallbackReason": "negation-not-preserved",
            "queryRewriteCount": 0,
            "queryRewriteNetworkRequests": 1,
            "queryRewriteCacheHit": False,
            "queryRewriteLatencyMs": 123.45678,
            "queryRewriteSemanticTags": [f"Bearer {secret}"],
            "authorization": secret,
        }
        preview = {
            "metadata": {
                "indexedDocuments": 145_000,
                "datasetSha256": VERIFY_M3_RUNTIME.EXPECTED_DATASET_SHA256,
                "retrievalVersion": VERIFY_M3_RUNTIME.EXPECTED_RETRIEVAL_VERSION,
                "ragIndexStats": {
                    "total": 145_000,
                    "upserted": 0,
                    "unchanged": 145_000,
                    "deleted": 0,
                },
                "retrieval": {"candidates": candidates_metadata},
            }
        }

        with (
            patch.object(
                VERIFY_M3_RUNTIME,
                "_request",
                side_effect=[health, preview],
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "did not use the requested OpenAI rewrite provider",
            ) as raised,
        ):
            VERIFY_M3_RUNTIME.verify("http://127.0.0.1:8090")

        message = str(raised.exception)
        self.assertNotIn(secret, message)
        observed = message.split(" observedRewrite=", 1)[1]
        self.assertLessEqual(
            len(observed),
            VERIFY_M3_RUNTIME.MAX_REWRITE_DIAGNOSTICS_CHARACTERS,
        )
        diagnostics = json.loads(observed)
        self.assertEqual(
            set(diagnostics),
            set(VERIFY_M3_RUNTIME._REWRITE_DIAGNOSTIC_FIELDS),
        )
        self.assertEqual(
            diagnostics,
            {
                "requestedProvider": "openai",
                "effectiveProvider": "disabled",
                "requestedModel": "gpt-4o-mini-2024-07-18",
                "effectiveModel": "rules-only",
                "fallback": True,
                "fallbackReason": "negation-not-preserved",
                "count": 0,
                "networkRequests": 1,
                "cacheHit": False,
                "latencyMs": 123.457,
            },
        )

    def test_rewrite_diagnostics_redact_and_bound_allowlisted_values(self) -> None:
        secret = "sk-super-secret-rewrite-value-123456789"
        metadata = {
            "queryRewriteProvider": f"Bearer {secret}",
            "queryRewriteEffectiveProvider": "provider " * 10_000,
            "queryRewriteModel": secret,
            "queryRewriteEffectiveModel": {"secret": secret},
            "queryRewriteFallback": "true",
            "queryRewriteFallbackReason": "authorization=" + secret,
            "queryRewriteCount": 10**100,
            "queryRewriteNetworkRequests": -1,
            "queryRewriteCacheHit": False,
            "queryRewriteLatencyMs": float("inf"),
            "requestBody": secret,
        }

        rendered = VERIFY_M3_RUNTIME._safe_rewrite_diagnostics(metadata)

        self.assertLessEqual(
            len(rendered),
            VERIFY_M3_RUNTIME.MAX_REWRITE_DIAGNOSTICS_CHARACTERS,
        )
        self.assertNotIn(secret, rendered)
        diagnostics = json.loads(rendered)
        self.assertEqual(
            set(diagnostics),
            set(VERIFY_M3_RUNTIME._REWRITE_DIAGNOSTIC_FIELDS),
        )
        self.assertEqual(diagnostics["requestedProvider"], "[redacted]")
        self.assertIn("[truncated]", diagnostics["effectiveProvider"])
        self.assertEqual(diagnostics["requestedModel"], "[redacted]")
        self.assertIsNone(diagnostics["effectiveModel"])
        self.assertIsNone(diagnostics["fallback"])
        self.assertEqual(diagnostics["fallbackReason"], "[redacted]")
        self.assertIsNone(diagnostics["count"])
        self.assertIsNone(diagnostics["networkRequests"])
        self.assertFalse(diagnostics["cacheHit"])
        self.assertIsNone(diagnostics["latencyMs"])

        metadata["queryRewriteLatencyMs"] = 10**400
        overflow_rendered = VERIFY_M3_RUNTIME._safe_rewrite_diagnostics(metadata)
        self.assertIsNone(json.loads(overflow_rendered)["latencyMs"])

    def test_malformed_rewrite_count_still_reports_safe_diagnostics(self) -> None:
        health = {
            "status": "ok",
            "rag": "qdrant",
            "globalRetrieval": "enabled",
            "queryRewrite": "openai",
            "reranker": "disabled",
        }
        candidates_metadata = {
            "candidateDiscoveryMode": "global-hybrid",
            "queryRewriteProvider": "openai",
            "queryRewriteEffectiveProvider": "openai",
            "queryRewriteModel": "gpt-4o-mini-2024-07-18",
            "queryRewriteEffectiveModel": "gpt-4o-mini-2024-07-18",
            "queryRewriteFallback": False,
            "queryRewriteCount": "not-an-integer",
            "queryRewriteNetworkRequests": 1,
            "queryRewriteCacheHit": False,
            "queryRewriteLatencyMs": 10.0,
        }
        preview = {
            "metadata": {
                "indexedDocuments": 145_000,
                "datasetSha256": VERIFY_M3_RUNTIME.EXPECTED_DATASET_SHA256,
                "retrievalVersion": VERIFY_M3_RUNTIME.EXPECTED_RETRIEVAL_VERSION,
                "ragIndexStats": {
                    "total": 145_000,
                    "upserted": 0,
                    "unchanged": 145_000,
                    "deleted": 0,
                },
                "retrieval": {"candidates": candidates_metadata},
            }
        }

        with (
            patch.object(
                VERIFY_M3_RUNTIME,
                "_request",
                side_effect=[health, preview],
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "Canary produced no LLM query rewrites",
            ) as raised,
        ):
            VERIFY_M3_RUNTIME.verify("http://127.0.0.1:8090")

        message = str(raised.exception)
        self.assertIn("observedRewrite=", message)
        observed = json.loads(message.split(" observedRewrite=", 1)[1])
        self.assertIsNone(observed["count"])


if __name__ == "__main__":
    unittest.main()
