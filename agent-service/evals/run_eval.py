from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.config import Settings
from app.domain.models import AgentMode, AgentRunCreateRequest, RunStatus
from app.runtime import AgentRuntime


async def wait_for_result(runtime: AgentRuntime, run_id: str):
    for _ in range(1_000):
        snapshot = await runtime.run_manager.get(run_id)
        if snapshot.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
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
    cited_ids = {
        item.shop_id for item in result.evidence.evidence if item.citations
    }
    expected_tags = set(case.get("expectedTags") or [])
    extracted_tags = set(constraints.get("desired_tags") or [])
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
            round(len(candidate_ids & cited_ids) / len(candidate_ids), 3)
            if candidate_ids
            else 0
        ),
        "validShopIds": all(shop_id > 0 for shop_id in candidate_ids),
        "candidateCount": len(candidate_ids),
        "latencyMs": latency_ms,
        "modelProvider": result.metadata.get("modelProvider"),
        "model": result.metadata.get("model"),
    }


async def main() -> None:
    cases_path = Path(__file__).with_name("cases.json")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    runtime = await AgentRuntime.create(Settings(run_store_path=":memory:"))
    try:
        results = []
        for case in cases:
            for mode in (AgentMode.SINGLE, AgentMode.MULTI):
                results.append(await evaluate_case(runtime, case, mode))
        print(json.dumps(results, indent=2))
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
