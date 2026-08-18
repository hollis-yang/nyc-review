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
                error TEXT
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
                "INSERT INTO agent_runs(run_id, owner_key, mode, query, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    owner_key,
                    request.mode.value,
                    request.query,
                    RunStatus.CREATED.value,
                    now,
                    now,
                ),
            )
            self._connection.commit()

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

    async def events_after(self, run_id: str, sequence: int) -> list[AgentRunEvent]:
        async with self._lock:
            rows = self._connection.execute(
                "SELECT event_json FROM agent_run_events "
                "WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, sequence),
            ).fetchall()
        return [AgentRunEvent.model_validate_json(row["event_json"]) for row in rows]

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
        action_counts: dict[str, int] = {}
        for row in action_rows:
            status = AgentActionProposal.model_validate_json(row["action_json"]).status.value
            action_counts[status] = action_counts.get(status, 0) + 1
        return {
            "runs": {row["status"]: row["count"] for row in run_rows},
            "actions": action_counts,
            "events": event_count,
        }

    async def close(self) -> None:
        async with self._lock:
            self._connection.close()
