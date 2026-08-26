#!/usr/bin/env python3
"""Exercise the production seckill Lua script against isolated Redis keys.

This test never calls Spring or RabbitMQ. It proves the atomic reservation
boundary (stock, one-user-one-order and pending publisher records) with real
concurrent Redis execution, then removes only the generated P14 keys.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LUA = ROOT / "src/main/resources/seckill.lua"


def redis_command(args: list[str], *, host: str, port: int, database: int) -> str:
    command = ["redis-cli", "--raw", "-h", host, "-p", str(port), "-n", str(database), *args]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--database", type=int, default=0)
    parser.add_argument("--stock", type=int, default=50)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--unique-users", type=int, default=80)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--voucher-id", default=f"914{int(time.time())}{os.getpid()}")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.stock < 1 or args.requests < 1 or args.unique_users < 1 or args.workers < 1:
        parser.error("stock, requests, unique-users and workers must be positive")
    connection = {"host": args.host, "port": args.port, "database": args.database}
    stock_key = f"seckill:stock:{args.voucher_id}"
    order_key = f"seckill:order:{args.voucher_id}"
    pending_index = "seckill:pending:orders"
    order_ids = [f"{args.voucher_id}{index:06d}" for index in range(args.requests)]
    pending_keys = [f"seckill:pending:order:{order_id}" for order_id in order_ids]

    if redis_command(["PING"], **connection) != "PONG":
        raise RuntimeError("Redis did not answer PONG")
    if redis_command(["EXISTS", stock_key, order_key], **connection) != "0":
        raise RuntimeError("Generated P14 Redis keys already exist; choose another --voucher-id")

    redis_command(["SET", stock_key, str(args.stock)], **connection)
    started = time.perf_counter()

    def reserve(index: int) -> int:
        user_id = f"p14-user-{index % args.unique_users}"
        output = redis_command(
            [
                "--eval",
                str(LUA),
                ",",
                args.voucher_id,
                user_id,
                order_ids[index],
                str(int(time.time() * 1_000)),
            ],
            **connection,
        )
        return int(output)

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            results = list(executor.map(reserve, range(args.requests)))
        elapsed_ms = round((time.perf_counter() - started) * 1_000, 3)
        succeeded_ids = [order_id for order_id, code in zip(order_ids, results, strict=True) if code == 0]
        remaining_stock = int(redis_command(["GET", stock_key], **connection))
        unique_orders = int(redis_command(["SCARD", order_key], **connection))
        indexed_pending = sum(
            redis_command(["ZSCORE", pending_index, order_id], **connection) != ""
            for order_id in succeeded_ids
        )
        pending_hashes = sum(
            redis_command(["EXISTS", key], **connection) == "1"
            for key in (f"seckill:pending:order:{order_id}" for order_id in succeeded_ids)
        )
        expected_successes = min(args.stock, args.unique_users)
        report = {
            "status": "ok",
            "voucherId": args.voucher_id,
            "requests": args.requests,
            "uniqueUsers": args.unique_users,
            "initialStock": args.stock,
            "accepted": results.count(0),
            "outOfStock": results.count(1),
            "duplicateUser": results.count(2),
            "remainingStock": remaining_stock,
            "uniqueOrderUsers": unique_orders,
            "pendingIndexRecords": indexed_pending,
            "pendingHashes": pending_hashes,
            "durationMs": elapsed_ms,
            "invariants": {
                "noOversell": results.count(0) == expected_successes
                and remaining_stock == args.stock - expected_successes,
                "oneOrderPerUser": unique_orders == results.count(0),
                "noReservationLoss": indexed_pending == pending_hashes == results.count(0),
            },
        }
        if not all(report["invariants"].values()):
            report["status"] = "failed"
        encoded = json.dumps(report, indent=2, sort_keys=True)
        print(encoded)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
        return 0 if report["status"] == "ok" else 1
    finally:
        redis_command(["DEL", stock_key, order_key, *pending_keys], **connection)
        if order_ids:
            redis_command(["ZREM", pending_index, *order_ids], **connection)


if __name__ == "__main__":
    raise SystemExit(main())
