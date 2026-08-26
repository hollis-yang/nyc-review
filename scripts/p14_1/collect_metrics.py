#!/usr/bin/env python3
"""Capture a reproducible JVM, Redis, RabbitMQ, MySQL and container snapshot."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from common import (
    METRICS_URL,
    ROOT,
    compose,
    mysql,
    rabbit_queue,
    rabbit_request,
    redis,
    request_json,
    run,
    validate_isolated_environment,
    write_json,
)

METRIC_NAMES = (
    "http.server.requests",
    "jvm.memory.used",
    "jvm.gc.pause",
    "jvm.threads.live",
    "hikaricp.connections.active",
    "hikaricp.connections.pending",
    "lettuce.command.completion",
    "rabbitmq.listener",
)


def parse_info(raw: str) -> dict[str, str | int | float]:
    result: dict[str, str | int | float] = {}
    wanted = {
        "connected_clients",
        "blocked_clients",
        "used_memory",
        "used_memory_peak",
        "instantaneous_ops_per_sec",
        "rejected_connections",
        "total_error_replies",
        "keyspace_hits",
        "keyspace_misses",
    }
    for line in raw.splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        name, value = line.split(":", 1)
        if name not in wanted:
            continue
        cleaned = value.strip()
        try:
            result[name] = int(cleaned)
        except ValueError:
            try:
                result[name] = float(cleaned)
            except ValueError:
                result[name] = cleaned
    return result


def spring_metrics() -> dict:
    metrics: dict = {}
    for name in METRIC_NAMES:
        status, body = request_json(f"{METRICS_URL}/actuator/metrics/{name}")
        if status == 200:
            metrics[name] = body
    with urllib.request.urlopen(f"{METRICS_URL}/actuator/prometheus", timeout=10) as response:
        prometheus_lines = len(response.read().splitlines())
    metrics["prometheusLines"] = prometheus_lines
    return metrics


def mysql_status() -> dict[str, int | str]:
    names = (
        "Threads_connected",
        "Threads_running",
        "Connections",
        "Aborted_connects",
        "Created_tmp_disk_tables",
        "Innodb_buffer_pool_reads",
        "Innodb_buffer_pool_read_requests",
        "Innodb_row_lock_waits",
        "Innodb_row_lock_time",
        "Slow_queries",
        "Questions",
    )
    raw = mysql(
        "SHOW GLOBAL STATUS WHERE Variable_name IN ("
        + ",".join(f"'{name}'" for name in names)
        + ")"
    )
    result: dict[str, int | str] = {}
    for line in raw.splitlines():
        name, value = line.split("\t", 1)
        result[name] = int(value) if value.isdigit() else value
    deadlocks = mysql(
        "SELECT COUNT(*) FROM performance_schema.events_transactions_history_long "
        "WHERE STATE='ROLLED BACK'"
    )
    result["rolledBackTransactionsInHistory"] = int(deadlocks or 0)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="snapshot")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/p14-1/metrics-snapshot.json",
    )
    args = parser.parse_args()
    environment = validate_isolated_environment()
    queue_names = ("hmdp.voucher.order.queue", "hmdp.voucher.order.error.queue")
    container_ids = [line for line in compose("ps", "-q").splitlines() if line]
    docker_stats = []
    if container_ids:
        raw_stats = run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                *container_ids,
            ]
        ).stdout
        docker_stats = [json.loads(line) for line in raw_stats.splitlines() if line]
    report = {
        "status": "ok",
        "label": args.label,
        "environment": environment,
        "spring": spring_metrics(),
        "redis": parse_info(redis("INFO")),
        "rabbitmq": {
            "overview": rabbit_request("/overview"),
            "queues": {name: rabbit_queue(name) for name in queue_names},
        },
        "mysql": mysql_status(),
        "containers": docker_stats,
    }
    write_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
