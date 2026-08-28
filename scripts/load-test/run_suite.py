#!/usr/bin/env python3
"""Run reproducible load-test stages and preserve every raw result."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from common import (
    ROOT,
    VOUCHER_ID,
    compose_args,
    validate_isolated_environment,
    write_json,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPORTS = ROOT / "reports/load-test"


@dataclass(frozen=True)
class Stage:
    name: str
    script: str
    users: int
    stock: int
    environment: dict[str, str]
    validates_orders: bool


STAGES = {
    "smoke": Stage(
        "smoke",
        "seckill_burst.js",
        10,
        5,
        {"ITERATIONS": "10", "VUS": "10", "MAX_DURATION": "45s"},
        True,
    ),
    "read": Stage(
        "read",
        "read_baseline.js",
        10,
        5,
        {"RATE": "50", "DURATION": "3m", "PRE_ALLOCATED_VUS": "50", "MAX_VUS": "200"},
        False,
    ),
    "seckill": Stage(
        "seckill",
        "seckill_burst.js",
        1_000,
        500,
        {"ITERATIONS": "1000", "VUS": "250", "MAX_DURATION": "2m"},
        True,
    ),
    "duplicate": Stage(
        "duplicate",
        "duplicate_order.js",
        200,
        200,
        {"UNIQUE_USERS": "200", "REPEATS": "5", "VUS": "100"},
        True,
    ),
    "mixed": Stage(
        "mixed",
        "mixed_workload.js",
        2_000,
        500,
        {"RATE": "50", "DURATION": "10m", "PRE_ALLOCATED_VUS": "75", "MAX_VUS": "300"},
        True,
    ),
    "endurance": Stage(
        "endurance",
        "mixed_workload.js",
        2_000,
        1_000,
        {"RATE": "50", "DURATION": "30m", "PRE_ALLOCATED_VUS": "75", "MAX_VUS": "300"},
        True,
    ),
}


def run_checked(command: list[str]) -> str:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise RuntimeError(f"Command failed with exit code {completed.returncode}: {command}")
    return completed.stdout


def python_script(name: str, *args: str) -> str:
    return run_checked([sys.executable, str(SCRIPT_DIR / name), *args])


def run_stage(stage: Stage) -> dict:
    stage_dir = REPORTS / stage.name
    stage_dir.mkdir(parents=True, exist_ok=True)
    python_script(
        "prepare_fixtures.py",
        "--users",
        str(stage.users),
        "--stock",
        str(stage.stock),
        "--tokens-output",
        str(REPORTS / "runtime/tokens.json"),
    )
    python_script(
        "collect_metrics.py",
        "--label",
        f"{stage.name}-before",
        "--output",
        str(stage_dir / "metrics-before.json"),
    )
    command = compose_args("run", "--rm")
    environment = {
        "BASE_URL": "http://spring:8081",
        "VOUCHER_ID": str(VOUCHER_ID),
        "TOKENS_FILE": "/workspace/reports/runtime/tokens.json",
        **stage.environment,
    }
    for name, value in environment.items():
        command.extend(["--env", f"{name}={value}"])
    summary_path = f"/workspace/reports/{stage.name}/k6-summary.json"
    command.extend(
        [
            "k6",
            "run",
            f"--summary-export={summary_path}",
            f"/workspace/scripts/{stage.script}",
        ]
    )
    output = run_checked(command)
    (stage_dir / "k6-output.txt").write_text(output, encoding="utf-8")
    consistency = None
    if stage.validates_orders:
        consistency = json.loads(
            python_script(
                "validate_orders.py",
                "--initial-stock",
                str(stage.stock),
                "--wait-seconds",
                "60",
                "--output",
                str(stage_dir / "consistency.json"),
            )
        )
    python_script(
        "collect_metrics.py",
        "--label",
        f"{stage.name}-after",
        "--output",
        str(stage_dir / "metrics-after.json"),
    )
    return {
        "name": stage.name,
        "status": "ok",
        "users": stage.users,
        "stock": stage.stock,
        "k6Summary": str(stage_dir / "k6-summary.json"),
        "consistency": consistency,
    }


def quick_stage(stage: Stage) -> Stage:
    environment = dict(stage.environment)
    if stage.script == "read_baseline.js":
        environment.update({"RATE": "20", "DURATION": "15s", "PRE_ALLOCATED_VUS": "20"})
    elif stage.script == "mixed_workload.js":
        environment.update({"RATE": "20", "DURATION": "20s", "PRE_ALLOCATED_VUS": "25"})
    return Stage(
        stage.name,
        stage.script,
        min(stage.users, 200),
        min(stage.stock, 100),
        environment,
        stage.validates_orders,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=(*STAGES, "all"),
        help="Run one visible checkpoint or the complete ordered suite",
    )
    parser.add_argument("--quick", action="store_true", help="Use short developer durations")
    args = parser.parse_args()
    environment = validate_isolated_environment()
    selected = list(STAGES.values()) if args.stage == "all" else [STAGES[args.stage]]
    results = []
    for configured in selected:
        stage = quick_stage(configured) if args.quick else configured
        results.append(run_stage(stage))
    report = {"status": "ok", "environment": environment, "stages": results}
    write_json(REPORTS / "suite-summary.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
