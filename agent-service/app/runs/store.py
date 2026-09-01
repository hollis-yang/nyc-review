from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import (
    AgentActionProposal,
    AgentActionStatus,
    AgentMode,
    AgentRunCreateRequest,
    AgentRunEvent,
    AgentRunResponse,
    AgentRunSnapshot,
    AgentTraceSpan,
    RunStatus,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class SQLiteRunStore:
    def __init__(self, location: str):
        if location != ":memory:":
            Path(location).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(location, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                request_json TEXT,
                attempt INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS agent_run_events (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence),
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
            );
            CREATE TABLE IF NOT EXISTS agent_run_actions (
                run_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                action_json TEXT NOT NULL,
                PRIMARY KEY (run_id, action_id),
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
            );
            CREATE TABLE IF NOT EXISTS agent_run_spans (
                span_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                agent TEXT,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                attributes_json TEXT NOT NULL,
                error TEXT,
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_run_spans_run_time
                ON agent_run_spans(run_id, started_at);
            """
        )
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(agent_runs)").fetchall()
        }
        if "owner_key" not in columns:
            self._connection.execute(
                "ALTER TABLE agent_runs ADD COLUMN owner_key TEXT NOT NULL DEFAULT ''"
            )
        if "request_json" not in columns:
            self._connection.execute("ALTER TABLE agent_runs ADD COLUMN request_json TEXT")
        if "attempt" not in columns:
            self._connection.execute(
                "ALTER TABLE agent_runs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0"
            )
        self._connection.commit()

    async def create(
        self,
        run_id: str,
        request: AgentRunCreateRequest,
        owner_key: str = "",
    ) -> None:
        now = utc_now().isoformat()
        async with self._lock:
            self._connection.execute(
                "INSERT INTO agent_runs(run_id, owner_key, mode, query, status, created_at, updated_at, "
                "request_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    owner_key,
                    request.mode.value,
                    request.query,
                    RunStatus.CREATED.value,
                    now,
                    now,
                    request.model_dump_json(),
                ),
            )
            self._connection.commit()

    async def increment_attempt(self, run_id: str) -> int:
        async with self._lock:
            self._connection.execute(
                "UPDATE agent_runs SET attempt = attempt + 1, updated_at = ? WHERE run_id = ?",
                (utc_now().isoformat(), run_id),
            )
            row = self._connection.execute(
                "SELECT attempt FROM agent_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            self._connection.commit()
            return int(row["attempt"])

    async def set_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        result: AgentRunResponse | None = None,
        error: str | None = None,
    ) -> None:
        now = utc_now().isoformat()
        result_json = result.model_dump_json() if result is not None else None
        async with self._lock:
            cursor = self._connection.execute(
                "UPDATE agent_runs SET status = ?, updated_at = ?, "
                "result_json = COALESCE(?, result_json), error = ? WHERE run_id = ?",
                (status.value, now, result_json, error, run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)
            self._connection.commit()

    async def append_event(
        self,
        run_id: str,
        *,
        event: str,
        status: str,
        message: str,
        agent: str | None = None,
        details: dict | None = None,
    ) -> AgentRunEvent:
        async with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                "FROM agent_run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            item = AgentRunEvent(
                sequence=int(row["next_sequence"]),
                event=event,
                agent=agent,
                status=status,
                message=message,
                created_at=utc_now(),
                details=details or {},
            )
            self._connection.execute(
                "INSERT INTO agent_run_events(run_id, sequence, event_json) VALUES (?, ?, ?)",
                (run_id, item.sequence, item.model_dump_json()),
            )
            self._connection.execute(
                "UPDATE agent_runs SET updated_at = ? WHERE run_id = ?",
                (item.created_at.isoformat(), run_id),
            )
            self._connection.commit()
            return item

    async def get(self, run_id: str) -> AgentRunSnapshot | None:
        async with self._lock:
            row = self._connection.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            event_rows = self._connection.execute(
                "SELECT event_json FROM agent_run_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
            action_rows = self._connection.execute(
                "SELECT action_json FROM agent_run_actions WHERE run_id = ? ORDER BY rowid",
                (run_id,),
            ).fetchall()
        return AgentRunSnapshot(
            run_id=row["run_id"],
            mode=AgentMode(row["mode"]),
            query=row["query"],
            status=RunStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            events=[AgentRunEvent.model_validate_json(item["event_json"]) for item in event_rows],
            actions=[
                AgentActionProposal.model_validate_json(item["action_json"])
                for item in action_rows
            ],
            result=(
                AgentRunResponse.model_validate(json.loads(row["result_json"]))
                if row["result_json"]
                else None
            ),
            error=row["error"],
        )

    async def add_actions(self, run_id: str, actions: list[AgentActionProposal]) -> None:
        if not actions:
            return
        now = utc_now()
        async with self._lock:
            for action in actions:
                item = action.model_copy(update={"created_at": now, "updated_at": now})
                self._connection.execute(
                    "INSERT OR IGNORE INTO agent_run_actions(run_id, action_id, action_json) "
                    "VALUES (?, ?, ?)",
                    (run_id, item.action_id, item.model_dump_json()),
                )
            self._connection.commit()

    async def get_action(self, run_id: str, action_id: str) -> AgentActionProposal | None:
        async with self._lock:
            row = self._connection.execute(
                "SELECT action_json FROM agent_run_actions WHERE run_id = ? AND action_id = ?",
                (run_id, action_id),
            ).fetchone()
        return AgentActionProposal.model_validate_json(row["action_json"]) if row else None

    async def update_action(
        self,
        run_id: str,
        action_id: str,
        status: AgentActionStatus,
        *,
        result: dict | None = None,
        error: str | None = None,
    ) -> AgentActionProposal:
        async with self._lock:
            row = self._connection.execute(
                "SELECT action_json FROM agent_run_actions WHERE run_id = ? AND action_id = ?",
                (run_id, action_id),
            ).fetchone()
            if row is None:
                raise KeyError(action_id)
            current = AgentActionProposal.model_validate_json(row["action_json"])
            item = current.model_copy(
                update={
                    "status": status,
                    "result": result if result is not None else current.result,
                    "error": error,
                    "updated_at": utc_now(),
                }
            )
            self._connection.execute(
                "UPDATE agent_run_actions SET action_json = ? WHERE run_id = ? AND action_id = ?",
                (item.model_dump_json(), run_id, action_id),
            )
            self._connection.commit()
        return item

    async def transition_action(
        self,
        run_id: str,
        action_id: str,
        expected: set[AgentActionStatus],
        status: AgentActionStatus,
        *,
        expected_run_statuses: set[RunStatus] | None = None,
        run_status: RunStatus | None = None,
    ) -> bool:
        """Atomically transition an action and, when requested, its parent run."""
        async with self._lock:
            if expected_run_statuses is not None:
                run_row = self._connection.execute(
                    "SELECT status FROM agent_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if run_row is None:
                    raise KeyError(run_id)
                if RunStatus(run_row["status"]) not in expected_run_statuses:
                    return False
            row = self._connection.execute(
                "SELECT action_json FROM agent_run_actions WHERE run_id = ? AND action_id = ?",
                (run_id, action_id),
            ).fetchone()
            if row is None:
                raise KeyError(action_id)
            current = AgentActionProposal.model_validate_json(row["action_json"])
            if current.status not in expected:
                return False
            now = utc_now()
            item = current.model_copy(
                update={
                    "status": status,
                    "error": None,
                    "updated_at": now,
                }
            )
            self._connection.execute(
                "UPDATE agent_run_actions SET action_json = ? WHERE run_id = ? AND action_id = ?",
                (item.model_dump_json(), run_id, action_id),
            )
            if run_status is not None:
                self._connection.execute(
                    "UPDATE agent_runs SET status = ?, updated_at = ?, error = NULL WHERE run_id = ?",
                    (run_status.value, now.isoformat(), run_id),
                )
            self._connection.commit()
        return True

    async def transition_status(
        self,
        run_id: str,
        expected: set[RunStatus],
        status: RunStatus,
    ) -> bool:
        """Compare-and-set a run status without overwriting a concurrent terminal decision."""
        async with self._lock:
            row = self._connection.execute(
                "SELECT status FROM agent_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            if RunStatus(row["status"]) not in expected:
                return False
            self._connection.execute(
                "UPDATE agent_runs SET status = ?, updated_at = ?, error = NULL WHERE run_id = ?",
                (status.value, utc_now().isoformat(), run_id),
            )
            self._connection.commit()
        return True

    async def cancel_run(self, run_id: str) -> tuple[bool, RunStatus]:
        """Cancel a run unless it is terminal or an approved write is in flight."""
        terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
        async with self._lock:
            row = self._connection.execute(
                "SELECT status FROM agent_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current_status = RunStatus(row["status"])
            if current_status in terminal:
                return False, current_status
            action_rows = self._connection.execute(
                "SELECT action_json FROM agent_run_actions WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            action_in_flight = any(
                AgentActionProposal.model_validate_json(item["action_json"]).status
                in {AgentActionStatus.APPROVED, AgentActionStatus.EXECUTING}
                for item in action_rows
            )
            if action_in_flight:
                return False, current_status
            self._connection.execute(
                "UPDATE agent_runs SET status = ?, updated_at = ?, error = NULL WHERE run_id = ?",
                (RunStatus.CANCELLED.value, utc_now().isoformat(), run_id),
            )
            self._connection.commit()
        return True, RunStatus.CANCELLED

    async def recover_interrupted_actions(self) -> list[tuple[str, AgentActionProposal]]:
        """Return interrupted writes to an explicit, user-retryable state after restart."""
        recovered: list[tuple[str, AgentActionProposal]] = []
        affected_runs: set[str] = set()
        recovery_error = (
            "Action execution was interrupted by a service restart. "
            "Approve it again to reconcile or retry the idempotent action."
        )
        async with self._lock:
            rows = self._connection.execute(
                "SELECT run_id, action_json FROM agent_run_actions ORDER BY rowid"
            ).fetchall()
            for row in rows:
                current = AgentActionProposal.model_validate_json(row["action_json"])
                if current.status not in {
                    AgentActionStatus.APPROVED,
                    AgentActionStatus.EXECUTING,
                }:
                    continue
                item = current.model_copy(
                    update={
                        "status": AgentActionStatus.FAILED,
                        "error": recovery_error,
                        "updated_at": utc_now(),
                    }
                )
                self._connection.execute(
                    "UPDATE agent_run_actions SET action_json = ? "
                    "WHERE run_id = ? AND action_id = ?",
                    (item.model_dump_json(), row["run_id"], item.action_id),
                )
                recovered.append((row["run_id"], item))
                affected_runs.add(row["run_id"])
            now = utc_now().isoformat()
            for run_id in affected_runs:
                self._connection.execute(
                    "UPDATE agent_runs SET status = ?, updated_at = ?, error = NULL "
                    "WHERE run_id = ? AND status != ?",
                    (
                        RunStatus.WAITING_CONFIRMATION.value,
                        now,
                        run_id,
                        RunStatus.CANCELLED.value,
                    ),
                )
            self._connection.commit()
        return recovered

    async def events_after(self, run_id: str, sequence: int) -> list[AgentRunEvent]:
        async with self._lock:
            rows = self._connection.execute(
                "SELECT event_json FROM agent_run_events "
                "WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, sequence),
            ).fetchall()
        return [AgentRunEvent.model_validate_json(row["event_json"]) for row in rows]

    async def record_span(self, span: AgentTraceSpan) -> None:
        async with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO agent_run_spans(span_id, run_id, operation, agent, kind, "
                "status, started_at, duration_ms, attributes_json, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    span.span_id,
                    span.run_id,
                    span.operation,
                    span.agent,
                    span.kind,
                    span.status,
                    span.started_at.isoformat(),
                    span.duration_ms,
                    json.dumps(span.attributes, separators=(",", ":"), sort_keys=True),
                    span.error,
                ),
            )
            self._connection.commit()

    async def spans(self, run_id: str) -> list[AgentTraceSpan]:
        async with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM agent_run_spans WHERE run_id = ? ORDER BY started_at, rowid",
                (run_id,),
            ).fetchall()
        return [
            AgentTraceSpan(
                span_id=row["span_id"],
                run_id=row["run_id"],
                operation=row["operation"],
                agent=row["agent"],
                kind=row["kind"],
                status=row["status"],
                started_at=datetime.fromisoformat(row["started_at"]),
                duration_ms=float(row["duration_ms"]),
                attributes=json.loads(row["attributes_json"]),
                error=row["error"],
            )
            for row in rows
        ]

    async def owner_matches(self, run_id: str, owner_key: str) -> bool:
        async with self._lock:
            row = self._connection.execute(
                "SELECT owner_key FROM agent_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row is not None and row["owner_key"] == owner_key

    async def claim_owner(
        self,
        run_id: str,
        current_owner_key: str,
        authenticated_owner_key: str,
    ) -> bool:
        """Atomically attach an anonymous browser-session run to its signed-in owner."""
        async with self._lock:
            cursor = self._connection.execute(
                "UPDATE agent_runs SET owner_key = ?, updated_at = ? "
                "WHERE run_id = ? AND owner_key = ?",
                (
                    authenticated_owner_key,
                    utc_now().isoformat(),
                    run_id,
                    current_owner_key,
                ),
            )
            self._connection.commit()
        return cursor.rowcount == 1

    async def recoverable_runs(
        self,
        max_attempts: int,
    ) -> list[tuple[str, AgentRunCreateRequest]]:
        if max_attempts <= 0:
            return []
        async with self._lock:
            rows = self._connection.execute(
                "SELECT r.run_id, r.mode, r.query, r.request_json FROM agent_runs r "
                "WHERE r.status IN (?, ?, ?) AND r.attempt < ? "
                "AND NOT EXISTS (SELECT 1 FROM agent_run_actions a WHERE a.run_id = r.run_id) "
                "ORDER BY r.created_at",
                (
                    RunStatus.CREATED.value,
                    RunStatus.PLANNING.value,
                    RunStatus.TOOL_RUNNING.value,
                    max_attempts,
                ),
            ).fetchall()
        result = []
        for row in rows:
            if row["request_json"]:
                request = AgentRunCreateRequest.model_validate_json(row["request_json"])
            else:
                request = AgentRunCreateRequest(mode=AgentMode(row["mode"]), query=row["query"])
            result.append((row["run_id"], request))
        return result

    async def list_runs(self, owner_key: str, limit: int = 10) -> list[AgentRunSnapshot]:
        async with self._lock:
            rows = self._connection.execute(
                "SELECT run_id FROM agent_runs WHERE owner_key = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (owner_key, max(1, min(limit, 50))),
            ).fetchall()
        snapshots = []
        for row in rows:
            snapshot = await self.get(row["run_id"])
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    async def metrics(self) -> dict:
        async with self._lock:
            run_rows = self._connection.execute(
                "SELECT status, COUNT(*) AS count FROM agent_runs GROUP BY status"
            ).fetchall()
            action_rows = self._connection.execute(
                "SELECT action_json FROM agent_run_actions"
            ).fetchall()
            event_count = self._connection.execute(
                "SELECT COUNT(*) AS count FROM agent_run_events"
            ).fetchone()["count"]
            span_rows = self._connection.execute(
                "SELECT operation, status, duration_ms, attributes_json FROM agent_run_spans"
            ).fetchall()
        action_counts: dict[str, int] = {}
        for row in action_rows:
            status = AgentActionProposal.model_validate_json(row["action_json"]).status.value
            action_counts[status] = action_counts.get(status, 0) + 1
        durations = sorted(float(row["duration_ms"]) for row in span_rows)
        operations: dict[str, dict[str, int | float]] = {}
        input_tokens = 0
        output_tokens = 0
        reasoning_tokens = 0
        for row in span_rows:
            operation = operations.setdefault(
                row["operation"], {"count": 0, "failures": 0, "totalDurationMs": 0.0}
            )
            operation["count"] += 1
            operation["failures"] += int(row["status"] == "failed")
            operation["totalDurationMs"] = round(
                float(operation["totalDurationMs"]) + float(row["duration_ms"]), 3
            )
            attributes = json.loads(row["attributes_json"])
            input_tokens += int(attributes.get("inputTokens") or 0)
            output_tokens += int(attributes.get("outputTokens") or 0)
            reasoning_tokens += int(attributes.get("reasoningTokens") or 0)
        return {
            "runs": {row["status"]: row["count"] for row in run_rows},
            "actions": action_counts,
            "events": event_count,
            "traces": {
                "count": len(span_rows),
                "failures": sum(row["status"] == "failed" for row in span_rows),
                "p50DurationMs": percentile(durations, 0.50),
                "p95DurationMs": percentile(durations, 0.95),
                "operations": operations,
            },
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "reasoning": reasoning_tokens,
            },
        }

    async def close(self) -> None:
        async with self._lock:
            self._connection.close()


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * quantile)))
    return round(values[index], 3)
