#!/usr/bin/env python3
"""Create isolated load-test users, auth tokens and one resettable voucher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    DEFAULT_USERS,
    ROOT,
    USER_ID_BASE,
    VOUCHER_ID,
    mysql_script,
    redis,
    redis_pipe,
    resp,
    validate_isolated_environment,
    write_json,
)


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_user_sql(user_count: int, stock: int) -> str:
    statements = [
        "SET NAMES utf8mb4;",
        "START TRANSACTION;",
        f"DELETE FROM tb_voucher_order WHERE voucher_id={VOUCHER_ID};",
        f"DELETE FROM tb_seckill_voucher WHERE voucher_id={VOUCHER_ID};",
        f"DELETE FROM tb_voucher WHERE id={VOUCHER_ID};",
        f"DELETE FROM tb_user_info WHERE user_id BETWEEN {USER_ID_BASE} AND {USER_ID_BASE + user_count - 1};",
        f"DELETE FROM tb_user WHERE id BETWEEN {USER_ID_BASE} AND {USER_ID_BASE + user_count - 1};",
    ]
    for offset in range(0, user_count, 250):
        rows = []
        for index in range(offset, min(offset + 250, user_count)):
            user_id = USER_ID_BASE + index
            phone = f"199{index:08d}"
            rows.append(
                f"({user_id},{sql_quote(phone)},'',{sql_quote(f'P14 Load User {index + 1}')},'',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        statements.append(
            "INSERT INTO tb_user (id,phone,password,nick_name,icon,create_time,update_time) VALUES\n"
            + ",\n".join(rows)
            + ";"
        )
    statements.extend(
        [
            (
                "INSERT INTO tb_voucher "
                "(id,shop_id,title,sub_title,rules,pay_value,actual_value,type,status,"
                "source_type,data_version,create_time,update_time) "
                f"VALUES ({VOUCHER_ID},1,'Load Test Voucher','Isolated load test only',"
                "'Never use outside the isolated load-test environment',100,1000,1,1,"
                "'SYNTHETIC','p14-load-v1',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);"
            ),
            (
                "INSERT INTO tb_seckill_voucher "
                "(voucher_id,stock,create_time,begin_time,end_time,update_time) "
                f"VALUES ({VOUCHER_ID},{stock},CURRENT_TIMESTAMP,"
                "CURRENT_TIMESTAMP - INTERVAL 1 DAY,"
                "CURRENT_TIMESTAMP + INTERVAL 30 DAY,CURRENT_TIMESTAMP);"
            ),
            "COMMIT;",
        ]
    )
    return "\n".join(statements) + "\n"


def reset_redis(user_count: int, stock: int) -> None:
    patterns = (
        "login:token:p14-load-*",
        "seckill:pending:order:*",
    )
    keys: list[str] = []
    for pattern in patterns:
        output = redis("--scan", "--pattern", pattern)
        keys.extend(line for line in output.splitlines() if line)
    fixed = [f"seckill:stock:{VOUCHER_ID}", f"seckill:order:{VOUCHER_ID}"]
    if keys or fixed:
        redis("DEL", *fixed, *keys)
    redis("DEL", "seckill:pending:orders")

    commands = [resp("SET", f"seckill:stock:{VOUCHER_ID}", stock)]
    for index in range(user_count):
        user_id = USER_ID_BASE + index
        token = f"p14-load-{index + 1:06d}"
        key = f"login:token:{token}"
        commands.append(
            resp(
                "HSET",
                key,
                "id",
                user_id,
                "nickName",
                f"P14 Load User {index + 1}",
                "icon",
                "",
            )
        )
        commands.append(resp("EXPIRE", key, 86_400))
    result = redis_pipe("".join(commands))
    if "errors: 0" not in result:
        raise RuntimeError(f"Redis fixture import failed: {result}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--stock", type=int, default=500)
    parser.add_argument(
        "--tokens-output",
        type=Path,
        default=ROOT / "reports/load-test/runtime/tokens.json",
    )
    args = parser.parse_args()
    if args.users < 1 or args.users > 10_000 or args.stock < 1 or args.stock > args.users:
        parser.error("users must be 1-10,000 and stock must be between 1 and users")

    environment = validate_isolated_environment()
    mysql_script(build_user_sql(args.users, args.stock))
    reset_redis(args.users, args.stock)
    tokens = [
        {"userId": USER_ID_BASE + index, "token": f"p14-load-{index + 1:06d}"}
        for index in range(args.users)
    ]
    write_json(args.tokens_output, tokens)
    print(
        json.dumps(
            {
                "status": "ok",
                "environment": environment,
                "users": args.users,
                "stock": args.stock,
                "voucherId": VOUCHER_ID,
                "tokens": str(args.tokens_output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
