#!/usr/bin/env python3
"""Validate Redis/Rabbit/MySQL convergence for the isolated load voucher."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from common import (
    ROOT,
    VOUCHER_ID,
    mysql,
    rabbit_queue,
    redis,
    validate_isolated_environment,
    write_json,
)

ORDER_QUEUE = "nyc-review.voucher.order.queue"
ERROR_QUEUE = "nyc-review.voucher.order.error.queue"


def integer(value: str) -> int:
    return int(value.strip() or 0)


def snapshot(initial_stock: int) -> dict:
    database_row = mysql(
        "SELECT CONCAT("
        f"(SELECT stock FROM tb_seckill_voucher WHERE voucher_id={VOUCHER_ID}),'|',"
        f"COUNT(*),'|',COUNT(DISTINCT user_id),'|',COUNT(DISTINCT id)) "
        f"FROM tb_voucher_order WHERE voucher_id={VOUCHER_ID}"
    )
    db_stock, orders, users, order_ids = [int(value) for value in database_row.split("|")]
    redis_stock = integer(redis("GET", f"seckill:stock:{VOUCHER_ID}"))
    redis_users = integer(redis("SCARD", f"seckill:order:{VOUCHER_ID}"))
    pending = integer(redis("ZCARD", "seckill:pending:orders"))
    order_queue = rabbit_queue(ORDER_QUEUE)
    error_queue = rabbit_queue(ERROR_QUEUE)
    accepted = initial_stock - redis_stock
    return {
        "initialStock": initial_stock,
        "acceptedReservations": accepted,
        "redis": {
            "stock": redis_stock,
            "uniqueUsers": redis_users,
            "pendingPublisherRecords": pending,
        },
        "mysql": {
            "stock": db_stock,
            "orders": orders,
            "uniqueUsers": users,
            "uniqueOrderIds": order_ids,
        },
        "rabbitmq": {
            "ready": int(order_queue.get("messages_ready") or 0),
            "unacknowledged": int(order_queue.get("messages_unacknowledged") or 0),
            "errorQueue": int(error_queue.get("messages") or 0),
        },
    }


def converged(report: dict, *, allow_error_queue: bool) -> bool:
    accepted = report["acceptedReservations"]
    redis_state = report["redis"]
    mysql_state = report["mysql"]
    rabbit = report["rabbitmq"]
    return all(
        (
            accepted >= 0,
            redis_state["uniqueUsers"] == accepted,
            mysql_state["orders"] == accepted,
            mysql_state["uniqueUsers"] == accepted,
            mysql_state["uniqueOrderIds"] == accepted,
            mysql_state["stock"] == report["initialStock"] - accepted,
            redis_state["pendingPublisherRecords"] == 0,
            rabbit["ready"] == 0,
            rabbit["unacknowledged"] == 0,
            allow_error_queue or rabbit["errorQueue"] == 0,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-stock", type=int, required=True)
    parser.add_argument("--wait-seconds", type=float, default=45)
    parser.add_argument("--allow-error-queue", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/p14-1/order-consistency.json",
    )
    args = parser.parse_args()
    if args.initial_stock < 1 or args.wait_seconds < 0:
        parser.error("initial-stock must be positive and wait-seconds non-negative")

    environment = validate_isolated_environment()
    deadline = time.monotonic() + args.wait_seconds
    report = snapshot(args.initial_stock)
    while not converged(report, allow_error_queue=args.allow_error_queue) and time.monotonic() < deadline:
        time.sleep(0.5)
        report = snapshot(args.initial_stock)
    report["environment"] = environment
    report["status"] = (
        "ok" if converged(report, allow_error_queue=args.allow_error_queue) else "failed"
    )
    report["invariants"] = {
        "noOversell": report["acceptedReservations"] <= args.initial_stock,
        "oneOrderPerUser": report["mysql"]["orders"] == report["mysql"]["uniqueUsers"],
        "uniqueOrderIds": report["mysql"]["orders"]
        == report["mysql"]["uniqueOrderIds"],
        "redisAndMySqlAgree": report["mysql"]["orders"]
        == report["acceptedReservations"],
        "databaseStockMatches": report["mysql"]["stock"]
        == args.initial_stock - report["mysql"]["orders"],
        "publisherRecoveryDrained": report["redis"]["pendingPublisherRecords"] == 0,
        "orderQueueDrained": report["rabbitmq"]["ready"] == 0
        and report["rabbitmq"]["unacknowledged"] == 0,
        "errorQueueEmpty": report["rabbitmq"]["errorQueue"] == 0,
    }
    write_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

