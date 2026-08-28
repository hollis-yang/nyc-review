#!/usr/bin/env python3
"""Move isolated load-test dead letters back to the durable order exchange."""

from __future__ import annotations

import argparse
import base64
import json
import urllib.parse

from common import RABBIT_VHOST, rabbit_request, validate_isolated_environment

ERROR_QUEUE = "nyc-review.voucher.order.error.queue"
ORDER_EXCHANGE = "nyc-review.voucher.order.exchange"
ORDER_ROUTING_KEY = "voucher.order.accepted"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-vhost", required=True)
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()
    if args.confirm_vhost != RABBIT_VHOST:
        parser.error(f"--confirm-vhost must equal {RABBIT_VHOST}")
    if args.batch < 1 or args.batch > 1_000:
        parser.error("batch must be between 1 and 1,000")
    validate_isolated_environment(require_spring=False)

    vhost = urllib.parse.quote(RABBIT_VHOST, safe="")
    queue = urllib.parse.quote(ERROR_QUEUE, safe="")
    messages = rabbit_request(
        f"/queues/{vhost}/{queue}/get",
        method="POST",
        body={
            "count": args.batch,
            "ackmode": "ack_requeue_false",
            "encoding": "auto",
            "truncate": 100_000,
        },
    )
    published = 0
    for message in messages:
        payload = message["payload"]
        if message.get("payload_encoding") == "base64":
            payload = base64.b64decode(payload).decode("utf-8")
        properties = message.get("properties") or {}
        safe_properties = {
            "content_type": properties.get("content_type") or "application/json",
            "delivery_mode": 2,
        }
        if properties.get("message_id"):
            safe_properties["message_id"] = properties["message_id"]
        result = rabbit_request(
            f"/exchanges/{vhost}/{urllib.parse.quote(ORDER_EXCHANGE, safe='')}/publish",
            method="POST",
            body={
                "properties": safe_properties,
                "routing_key": ORDER_ROUTING_KEY,
                "payload": payload,
                "payload_encoding": "string",
            },
        )
        if not result.get("routed"):
            raise RuntimeError("Dead-letter replay was not routed; stopping without consuming more")
        published += 1
    print(json.dumps({"status": "ok", "consumed": len(messages), "published": published}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
