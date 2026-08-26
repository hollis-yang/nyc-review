"""Shared, fail-closed helpers for the isolated P14.1 load environment."""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.p14-load.yml"
PROJECT = "hmdp-p14-load"
DATABASE = "hmdp_p14_load"
REDIS_SENTINEL_KEY = "hmdp:p14:environment"
REDIS_SENTINEL_VALUE = "isolated-load-only"
RABBIT_VHOST = "/hmdp-p14-load"
RABBIT_USER = "p14-load"
RABBIT_PASSWORD = "p14-load-only"
RABBIT_API = "http://127.0.0.1:15683/api"
SPRING_URL = "http://127.0.0.1:18081"
METRICS_URL = "http://127.0.0.1:19091"
AGENT_URL = "http://127.0.0.1:18090"
VOUCHER_ID = 9_140_001
USER_ID_BASE = 9_000_000
DEFAULT_USERS = 2_000


class GuardFailure(RuntimeError):
    """Raised before a command could mutate a non-P14 environment."""


def compose_args(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--file",
        str(COMPOSE_FILE),
        *args,
    ]


def run(
    command: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def compose(*args: str, input_text: str | None = None) -> str:
    return run(compose_args(*args), input_text=input_text).stdout.strip()


def mysql(query: str, *, batch: bool = True) -> str:
    command = [
        "exec",
        "-T",
        "mysql",
        "mysql",
        "-uroot",
        "-pp14-load-only",
        DATABASE,
    ]
    if batch:
        command.extend(["--batch", "--skip-column-names"])
    command.extend(["--execute", query])
    return compose(*command)


def mysql_script(script: str) -> None:
    compose(
        "exec",
        "-T",
        "mysql",
        "mysql",
        "-uroot",
        "-pp14-load-only",
        DATABASE,
        input_text=script,
    )


def redis(*args: str) -> str:
    return compose("exec", "-T", "redis", "redis-cli", "--raw", *args)


def redis_pipe(payload: str) -> str:
    return compose("exec", "-T", "redis", "redis-cli", "--pipe", input_text=payload)


def resp(*parts: str | int) -> str:
    encoded = [str(part).encode("utf-8") for part in parts]
    chunks = [f"*{len(encoded)}\r\n".encode()]
    for part in encoded:
        chunks.extend((f"${len(part)}\r\n".encode(), part, b"\r\n"))
    return b"".join(chunks).decode("utf-8")


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> tuple[int, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=payload, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            content = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            content = raw.decode(errors="replace")
        return error.code, content


def rabbit_request(
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    authorization = base64.b64encode(f"{RABBIT_USER}:{RABBIT_PASSWORD}".encode()).decode()
    status, content = request_json(
        RABBIT_API + path,
        method=method,
        body=body,
        headers={"Authorization": f"Basic {authorization}"},
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f"RabbitMQ API {method} {path} returned {status}: {content}")
    return content


def rabbit_queue(name: str) -> dict[str, Any]:
    vhost = urllib.parse.quote(RABBIT_VHOST, safe="")
    queue = urllib.parse.quote(name, safe="")
    return rabbit_request(f"/queues/{vhost}/{queue}")


def validate_isolated_environment(*, require_spring: bool = True) -> dict[str, Any]:
    if COMPOSE_FILE.name != "docker-compose.p14-load.yml" or PROJECT != "hmdp-p14-load":
        raise GuardFailure("P14.1 compose identity is not the expected isolated project")
    database = mysql("SELECT DATABASE()")
    if database != DATABASE:
        raise GuardFailure(f"Expected database {DATABASE!r}, received {database!r}")
    sentinel = redis("GET", REDIS_SENTINEL_KEY)
    if sentinel != REDIS_SENTINEL_VALUE:
        raise GuardFailure("Redis isolation sentinel is missing; refusing to mutate keys")
    overview = rabbit_request("/overview")
    if RABBIT_VHOST not in {item["name"] for item in rabbit_request("/vhosts")}:
        raise GuardFailure(f"RabbitMQ vhost {RABBIT_VHOST} does not exist")
    active = mysql(
        "SELECT CONCAT(data_version, '|', profile, '|', shop_count) "
        "FROM tb_data_import WHERE active=1 ORDER BY imported_at DESC LIMIT 1"
    )
    if "|p13-full|5000" not in active:
        raise GuardFailure(f"Expected the 5,000-shop P13 checkpoint, received {active!r}")
    result: dict[str, Any] = {
        "project": PROJECT,
        "database": database,
        "redisSentinel": sentinel,
        "rabbitVersion": overview.get("rabbitmq_version"),
        "activeDataset": active,
    }
    if require_spring:
        status, health = request_json(f"{METRICS_URL}/actuator/health")
        if status != 200 or not isinstance(health, dict) or health.get("status") != "UP":
            raise GuardFailure(f"Spring load health is not UP: HTTP {status} {health}")
        result["springHealth"] = health.get("status")
    return result


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

