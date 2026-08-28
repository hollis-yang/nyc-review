#!/usr/bin/env python3
"""Run fail-closed RabbitMQ, MySQL or Redis drills in the isolated stack."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import (
    PROJECT,
    RABBIT_VHOST,
    ROOT,
    SPRING_URL,
    VOUCHER_ID,
    compose,
    rabbit_queue,
    request_json,
    validate_isolated_environment,
    write_json,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPORTS = ROOT / "reports/p14-1/failures"


def run_script(name: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_DIR / name), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def wait_for_environment(timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            validate_isolated_environment()
            return
        except Exception as error:  # noqa: BLE001 - the dependency is intentionally recovering
            last_error = error
            time.sleep(2)
    raise RuntimeError(f"P14.1 environment did not recover: {last_error}")


def send_seckill_requests(count: int) -> list[dict]:
    def request(index: int) -> dict:
        try:
            status, body = request_json(
                f"{SPRING_URL}/voucher-order/seckill/{VOUCHER_ID}",
                method="POST",
                headers={"authorization": f"p14-load-{index + 1:06d}"},
                timeout=20,
            )
            return {"index": index, "httpStatus": status, "body": body}
        except Exception as error:  # noqa: BLE001 - failures are drill observations
            return {"index": index, "httpStatus": 0, "error": str(error)}

    with ThreadPoolExecutor(max_workers=count) as executor:
        return list(executor.map(request, range(count)))


def prepare(users: int, stock: int) -> None:
    run_script("prepare_fixtures.py", "--users", str(users), "--stock", str(stock))


def rabbit_drill() -> dict:
    prepare(20, 10)
    compose("stop", "rabbitmq")
    try:
        responses = send_seckill_requests(20)
    finally:
        compose("start", "rabbitmq")
    wait_for_environment()
    consistency = run_script(
        "validate_orders.py",
        "--initial-stock",
        "10",
        "--wait-seconds",
        "90",
        "--output",
        str(REPORTS / "rabbitmq-consistency.json"),
    )
    return {
        "component": "rabbitmq",
        "responses": responses,
        "consistency": json.loads(consistency.stdout),
    }


def mysql_drill() -> dict:
    prepare(5, 5)
    compose("stop", "mysql")
    try:
        responses = send_seckill_requests(5)
        deadline = time.monotonic() + 35
        error_messages = 0
        while time.monotonic() < deadline and error_messages < 5:
            error_messages = int(
                rabbit_queue("nyc-review.voucher.order.error.queue").get("messages") or 0
            )
            if error_messages < 5:
                time.sleep(1)
    finally:
        compose("start", "mysql")
    wait_for_environment()
    replay = run_script(
        "replay_error_queue.py",
        "--confirm-vhost",
        RABBIT_VHOST,
        "--batch",
        "100",
    )
    consistency = run_script(
        "validate_orders.py",
        "--initial-stock",
        "5",
        "--wait-seconds",
        "90",
        "--output",
        str(REPORTS / "mysql-consistency.json"),
    )
    return {
        "component": "mysql",
        "responses": responses,
        "deadLettersBeforeReplay": error_messages,
        "replay": json.loads(replay.stdout),
        "consistency": json.loads(consistency.stdout),
    }


def redis_drill() -> dict:
    prepare(5, 5)
    compose("stop", "redis")
    try:
        responses = send_seckill_requests(5)
    finally:
        compose("start", "redis")
    wait_for_environment()
    consistency = run_script(
        "validate_orders.py",
        "--initial-stock",
        "5",
        "--wait-seconds",
        "15",
        "--output",
        str(REPORTS / "redis-consistency.json"),
    )
    return {
        "component": "redis",
        "responses": responses,
        "consistency": json.loads(consistency.stdout),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=("rabbitmq", "mysql", "redis"))
    parser.add_argument("--confirm-project", required=True)
    args = parser.parse_args()
    if args.confirm_project != PROJECT:
        parser.error(f"--confirm-project must equal {PROJECT}")
    validate_isolated_environment()
    drill = {"rabbitmq": rabbit_drill, "mysql": mysql_drill, "redis": redis_drill}[
        args.component
    ]
    report = drill()
    report["status"] = "ok" if report["consistency"].get("status") == "ok" else "failed"
    write_json(REPORTS / f"{args.component}.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
