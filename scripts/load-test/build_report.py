#!/usr/bin/env python3
"""Aggregate accepted load-test evidence without exposing runtime credentials."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import ROOT, write_json

REPORTS = ROOT / "reports/load-test"
STAGE_LIMITS = {
    "smoke": (750, 1_500),
    "read": (300, 800),
    "seckill": (750, 1_500),
    "duplicate": (750, 1_500),
    "mixed": (500, 1_200),
    "endurance": (500, 1_200),
}


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Required load-test evidence is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def metric_value(metrics: dict, name: str, key: str, default=0):
    return (metrics.get(name) or {}).get(key, default)


def summarize_stage(name: str) -> dict:
    stage_dir = REPORTS / name
    metrics = load_json(stage_dir / "k6-summary.json")["metrics"]
    p95_limit, p99_limit = STAGE_LIMITS[name]
    p95 = metric_value(metrics, "http_req_duration", "p(95)")
    p99 = metric_value(metrics, "http_req_duration", "p(99)")
    technical_error_rate = metric_value(metrics, "technical_errors", "value")
    http_error_rate = metric_value(metrics, "http_req_failed", "value")
    dropped = metric_value(metrics, "dropped_iterations", "count")
    failed_checks = metric_value(metrics, "checks", "fails")
    consistency_path = stage_dir / "consistency.json"
    consistency = load_json(consistency_path) if consistency_path.is_file() else None
    consistency_ok = consistency is None or (
        consistency.get("status") == "ok"
        and all((consistency.get("invariants") or {}).values())
    )
    accepted = (
        technical_error_rate < 0.01
        and http_error_rate < 0.01
        and dropped == 0
        and failed_checks == 0
        and p95 < p95_limit
        and p99 < p99_limit
        and consistency_ok
    )
    return {
        "accepted": accepted,
        "requests": metric_value(metrics, "http_reqs", "count"),
        "requestsPerSecond": round(metric_value(metrics, "http_reqs", "rate"), 3),
        "latencyMs": {
            "average": round(metric_value(metrics, "http_req_duration", "avg"), 3),
            "p95": round(p95, 3),
            "p99": round(p99, 3),
            "maximum": round(metric_value(metrics, "http_req_duration", "max"), 3),
        },
        "limitsMs": {"p95": p95_limit, "p99": p99_limit},
        "technicalErrorRate": technical_error_rate,
        "httpErrorRate": http_error_rate,
        "droppedIterations": dropped,
        "failedChecks": failed_checks,
        "business": {
            "accepted": metric_value(metrics, "business_accepted", "count"),
            "duplicate": metric_value(metrics, "business_duplicate", "count"),
            "outOfStock": metric_value(metrics, "business_out_of_stock", "count"),
        },
        "consistency": consistency,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORTS / "accepted-results.json",
    )
    args = parser.parse_args()
    stages = {name: summarize_stage(name) for name in STAGE_LIMITS}
    agent = load_json(REPORTS / "agent-soak.json")
    agent_accepted = (
        agent.get("status") == "ok"
        and agent.get("failed") == 0
        and agent.get("completed") == agent.get("runs")
        and agent.get("verified") == agent.get("runs")
        and agent.get("fallbackRuns") == 0
        and agent.get("p95Ms", 0) < 2_000
    )
    failures = {
        name: load_json(REPORTS / "failures" / f"{name}.json")
        for name in ("rabbitmq", "mysql", "redis")
    }
    failure_acceptance = {
        name: report.get("status") == "ok"
        and (report.get("consistency") or {}).get("status") == "ok"
        for name, report in failures.items()
    }
    report = {
        "status": (
            "accepted"
            if all(stage["accepted"] for stage in stages.values())
            and agent_accepted
            and all(failure_acceptance.values())
            else "failed"
        ),
        "dataset": "nyc-real-v5-8b645404-m20260824|p13-full|5000",
        "environment": "nyc-review-p14-load",
        "stages": stages,
        "agent": {
            "accepted": agent_accepted,
            "runs": agent.get("runs"),
            "completed": agent.get("completed"),
            "verified": agent.get("verified"),
            "failed": agent.get("failed"),
            "fallbackRuns": agent.get("fallbackRuns"),
            "concurrency": agent.get("observedConcurrency"),
            "meanMs": agent.get("meanMs"),
            "p95Ms": agent.get("p95Ms"),
        },
        "failureRecovery": failure_acceptance,
    }
    write_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
