from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from app.config import Settings
from app.domain.models import AgentMode, AgentRunCreateRequest, RunStatus
from app.runtime import AgentRuntime

EVAL_DIRECTORY = Path(__file__).resolve().parent


async def wait_for_result(runtime: AgentRuntime, run_id: str):
    for _ in range(1_000):
        snapshot = await runtime.run_manager.get(run_id)
        if snapshot.status in {
            RunStatus.WAITING_CONFIRMATION,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            return snapshot
        await asyncio.sleep(0.01)
    raise TimeoutError(f"Run {run_id} did not reach a terminal state")


async def evaluate_case(runtime: AgentRuntime, case: dict, mode: AgentMode) -> dict:
    started = time.perf_counter()
    created = await runtime.run_manager.create(
        AgentRunCreateRequest(mode=mode, query=case["query"])
    )
    snapshot = await wait_for_result(runtime, created.run_id)
    latency_ms = round((time.perf_counter() - started) * 1_000, 2)
    if snapshot.result is None:
        return {
            "case": case["id"],
            "mode": mode.value,
            "completed": False,
            "latencyMs": latency_ms,
            "error": snapshot.error,
        }

    result = snapshot.result
    constraints = result.metadata.get("constraints") or {}
    candidate_ids = {candidate.shop_id for candidate in result.candidates.candidates}
    cited_ids = {item.shop_id for item in result.evidence.evidence if item.citations}
    expected_tags = set(case.get("expectedTags") or [])
    extracted_tags = set(constraints.get("desired_tags") or [])
    trace = await runtime.run_manager.trace(created.run_id, "") or []
    return {
        "case": case["id"],
        "mode": mode.value,
        "completed": True,
        "verified": result.verification.valid,
        "constraintMatch": (
            constraints.get("category") == case.get("expectedCategory")
            and constraints.get("neighborhood") == case.get("expectedNeighborhood")
            and expected_tags <= extracted_tags
        ),
        "citationCoverage": (
            round(len(candidate_ids & cited_ids) / len(candidate_ids), 3) if candidate_ids else 0
        ),
        "validShopIds": all(shop_id > 0 for shop_id in candidate_ids),
        "candidateCount": len(candidate_ids),
        "latencyMs": latency_ms,
        "modelProvider": result.metadata.get("modelProvider"),
        "model": result.metadata.get("model"),
        "actionProposalCount": len(snapshot.actions),
        "relaxedConstraints": result.candidates.relaxed_constraints,
        "traceSpanCount": len(trace),
        "traceFailureCount": sum(span.status == "failed" for span in trace),
    }


def summarize(results: list[dict], mode: AgentMode) -> dict:
    selected = [item for item in results if item["mode"] == mode.value]
    completed = [item for item in selected if item.get("completed")]
    divisor = max(1, len(selected))
    completed_divisor = max(1, len(completed))
    latencies = sorted(float(item["latencyMs"]) for item in selected)
    return {
        "cases": len(selected),
        "completionRate": round(len(completed) / divisor, 3),
        "verificationRate": round(
            sum(bool(item.get("verified")) for item in completed) / completed_divisor, 3
        ),
        "constraintMatchRate": round(
            sum(bool(item.get("constraintMatch")) for item in completed) / completed_divisor, 3
        ),
        "meanCitationCoverage": round(
            statistics.fmean(float(item.get("citationCoverage") or 0) for item in completed)
            if completed
            else 0,
            3,
        ),
        "p95LatencyMs": percentile(latencies, 0.95),
        "meanActionProposals": round(
            statistics.fmean(int(item.get("actionProposalCount") or 0) for item in completed)
            if completed
            else 0,
            2,
        ),
        "traceFailureCount": sum(int(item.get("traceFailureCount") or 0) for item in selected),
    }


def evaluate_gate(summary: dict, gate: dict) -> list[str]:
    failures = []
    comparisons = {
        "completionRate": "minCompletionRate",
        "verificationRate": "minVerificationRate",
        "constraintMatchRate": "minConstraintMatchRate",
        "meanCitationCoverage": "minMeanCitationCoverage",
    }
    for metric, threshold in comparisons.items():
        if float(summary[metric]) < float(gate[threshold]):
            failures.append(f"{metric}={summary[metric]} is below {gate[threshold]}")
    if float(summary["p95LatencyMs"]) > float(gate["maxP95LatencyMs"]):
        failures.append(
            f"p95LatencyMs={summary['p95LatencyMs']} exceeds {gate['maxP95LatencyMs']}"
        )
    if int(summary["traceFailureCount"]) > int(gate["maxTraceFailures"]):
        failures.append(
            f"traceFailureCount={summary['traceFailureCount']} exceeds {gate['maxTraceFailures']}"
        )
    return failures


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * quantile)))
    return round(values[index], 2)


async def run(output: Path | None = None) -> tuple[dict, bool]:
    cases = json.loads((EVAL_DIRECTORY / "cases.json").read_text(encoding="utf-8"))
    gate = json.loads((EVAL_DIRECTORY / "quality_gate.json").read_text(encoding="utf-8"))
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    try:
        results = []
        for case in cases:
            for mode in (AgentMode.SINGLE, AgentMode.MULTI):
                results.append(await evaluate_case(runtime, case, mode))
        summaries = {
            mode.value: summarize(results, mode) for mode in (AgentMode.SINGLE, AgentMode.MULTI)
        }
        failures = evaluate_gate(summaries[AgentMode.MULTI.value], gate)
        report = {
            "qualityGate": {"passed": not failures, "failures": failures, "thresholds": gate},
            "summary": summaries,
            "results": results,
        }
        rendered = json.dumps(report, indent=2)
        print(rendered)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        return report, not failures
    finally:
        await runtime.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic P4 Agent quality gate.")
    parser.add_argument("--output", type=Path, help="Optional JSON report destination.")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Report quality-gate failures without returning a failing exit code.",
    )
    args = parser.parse_args()
    _, passed = await run(args.output)
    if not passed and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
