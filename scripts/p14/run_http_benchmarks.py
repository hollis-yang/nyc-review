#!/usr/bin/env python3
"""Measure P14 map/list latency without interrupting slow application requests."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scenario:
    name: str
    path: str
    p95_limit_ms: float
    max_items: int


SCENARIOS = (
    Scenario(
        "map_borough_clusters",
        "/shop/map?west=-74.26&south=40.49&east=-73.68&north=40.92&zoom=10",
        300,
        500,
    ),
    Scenario(
        "map_neighborhood_clusters",
        "/shop/map?west=-74.05&south=40.68&east=-73.85&north=40.88&zoom=13&typeIds=1,2,3",
        300,
        500,
    ),
    Scenario(
        "map_shop_markers",
        "/shop/map?west=-73.997&south=40.748&east=-73.975&north=40.765&zoom=17&typeIds=1,2",
        500,
        500,
    ),
    Scenario("shop_list", "/shop/of/type?typeId=1&current=1&sortBy=rating", 500, 50),
)


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * quantile))
    return round(ordered[index], 3)


def request_once(base_url: str, scenario: Scenario, token: str) -> tuple[float, int, str | None]:
    request = urllib.request.Request(base_url.rstrip("/") + scenario.path)
    if token:
        request.add_header("authorization", token)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read()
        status = error.code
    duration_ms = (time.perf_counter() - started) * 1_000
    if status != 200:
        return duration_ms, 0, f"HTTP {status}"
    try:
        body = json.loads(raw)
        if body.get("success") is False:
            return duration_ms, 0, str(body.get("errorMsg") or "API returned success=false")
        data = body.get("data")
        if scenario.name.startswith("map_"):
            item_count = len((data or {}).get("items") or [])
        else:
            item_count = len(data or [])
    except (TypeError, ValueError, AttributeError) as error:
        return duration_ms, 0, f"invalid JSON contract: {error}"
    return duration_ms, item_count, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--authorization", default="")
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.requests < 1 or args.warmup < 0 or args.concurrency < 1:
        parser.error("requests and concurrency must be positive; warmup must be non-negative")

    report: dict = {"status": "ok", "baseUrl": args.base_url, "scenarios": {}}
    for scenario in SCENARIOS:
        for _ in range(args.warmup):
            _, _, error = request_once(args.base_url, scenario, args.authorization)
            if error:
                raise RuntimeError(f"{scenario.name} warmup failed: {error}")
        durations: list[float] = []
        counts: list[int] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [
                executor.submit(request_once, args.base_url, scenario, args.authorization)
                for _ in range(args.requests)
            ]
            for future in as_completed(futures):
                duration, count, error = future.result()
                durations.append(duration)
                counts.append(count)
                if error:
                    errors.append(error)
        p95 = percentile(durations, 0.95)
        passed = not errors and p95 <= scenario.p95_limit_ms and max(counts, default=0) <= scenario.max_items
        report["scenarios"][scenario.name] = {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "p50Ms": percentile(durations, 0.50),
            "p95Ms": p95,
            "meanMs": round(statistics.fmean(durations), 3),
            "thresholdMs": scenario.p95_limit_ms,
            "maxItems": max(counts, default=0),
            "itemLimit": scenario.max_items,
            "errors": errors[:10],
            "passed": passed,
        }
        if not passed:
            report["status"] = "failed"

    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
