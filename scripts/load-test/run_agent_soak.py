#!/usr/bin/env python3
"""Run concurrent multi-Agent requests and measure completion without client deadlines."""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

TERMINAL = {"waiting_confirmation", "completed", "failed", "cancelled"}
PROMPTS = (
    "Recommend wheelchair-accessible cafés in Astoria with outdoor seating. Give me the five best matches.",
    "Show the top 3 quiet dinner places in Midtown for two people.",
    "Find 4 late-night bars in the East Village that are good for groups.",
    "推荐五家位于 Flushing、适合朋友聚会的餐厅。",
    "List 2 fitness and wellness places in Chelsea.",
    "Give me the 3 best beauty and personal care options in Williamsburg.",
)


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * quantile))
    return round(ordered[index], 3)


def request_json(
    method: str,
    url: str,
    token: str,
    owner_session: str,
    body: dict | None = None,
) -> dict:
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=payload, method=method)
    request.add_header("Content-Type", "application/json")
    request.add_header("x-agent-session", owner_session)
    if token:
        request.add_header("authorization", token)
    try:
        # Intentionally no socket deadline: cancellation belongs to the Run API,
        # not a hidden client timeout.
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {error.read().decode(errors='replace')}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--authorization", default="")
    parser.add_argument("--runs", type=int, default=18)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--poll-interval", type=float, default=0.25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1 or args.concurrency < 1 or args.poll_interval <= 0:
        parser.error("runs, concurrency and poll-interval must be positive")

    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def run_once(index: int) -> dict:
        nonlocal active, maximum_active
        owner_session = f"agent-soak-{uuid4()}"
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        started = time.perf_counter()
        try:
            created = request_json(
                "POST",
                args.base_url.rstrip("/") + "/v1/agent/runs",
                args.authorization,
                owner_session,
                {"mode": "multi", "query": PROMPTS[index % len(PROMPTS)]},
            )
            run_id = created["run_id"]
            while True:
                snapshot = request_json(
                    "GET",
                    args.base_url.rstrip("/") + f"/v1/agent/runs/{run_id}",
                    args.authorization,
                    owner_session,
                )
                if snapshot["status"] in TERMINAL:
                    break
                time.sleep(args.poll_interval)
            result = snapshot.get("result") or {}
            return {
                "runId": run_id,
                "status": snapshot["status"],
                "durationMs": round((time.perf_counter() - started) * 1_000, 3),
                "verified": (result.get("verification") or {}).get("valid", False),
                "candidateCount": len((result.get("candidates") or {}).get("candidates") or []),
                "modelFallbackUsed": (result.get("metadata") or {}).get("modelFallbackUsed"),
            }
        finally:
            with lock:
                active -= 1

    records = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(run_once, index) for index in range(args.runs)]
        for future in as_completed(futures):
            records.append(future.result())

    durations = [record["durationMs"] for record in records]
    failed = [record for record in records if record["status"] == "failed"]
    report = {
        "status": "ok" if not failed else "failed",
        "runs": args.runs,
        "requestedConcurrency": args.concurrency,
        "observedConcurrency": maximum_active,
        "completed": len(records) - len(failed),
        "failed": len(failed),
        "verified": sum(bool(record["verified"]) for record in records),
        "fallbackRuns": sum(bool(record["modelFallbackUsed"]) for record in records),
        "p50Ms": percentile(durations, 0.50),
        "p95Ms": percentile(durations, 0.95),
        "meanMs": round(statistics.fmean(durations), 3),
        "records": sorted(records, key=lambda item: item["runId"]),
    }
    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
