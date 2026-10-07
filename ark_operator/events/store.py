"""Append-only SQLite event log (stdlib sqlite3)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ark_operator.events.types import EventRecord, EventType


class EventStore:
    """Persists events; run state is derived by folding (SPEC §6.1)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    ts TEXT NOT NULL,
                    type TEXT NOT NULL,
                    step_id TEXT,
                    payload TEXT NOT NULL,
                    UNIQUE(run_id, seq)
                );
                CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);

                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    step_id TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    step_id TEXT,
                    prompt TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decided_by TEXT,
                    decided_at TEXT
                );
                """
            )

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def append(
        self,
        run_id: str,
        event_type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        step_id: str | None = None,
    ) -> EventRecord:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            seq = int(row["m"]) + 1
            ts = datetime.now(UTC).isoformat()
            et = EventType(event_type) if not isinstance(event_type, EventType) else event_type
            body = payload or {}
            cur = conn.execute(
                """
                    INSERT INTO events (run_id, seq, ts, type, step_id, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                (run_id, seq, ts, et.value, step_id, json.dumps(body)),
            )
            conn.commit()
            return EventRecord(
                id=int(cur.lastrowid),
                run_id=run_id,
                seq=seq,
                ts=ts,
                type=et,
                step_id=step_id,
                payload=body,
            )

    def list_for_run(self, run_id: str) -> list[EventRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, seq, ts, type, step_id, payload
                FROM events WHERE run_id = ? ORDER BY seq ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            EventRecord(
                id=r["id"],
                run_id=r["run_id"],
                seq=r["seq"],
                ts=r["ts"],
                type=EventType(r["type"]),
                step_id=r["step_id"],
                payload=json.loads(r["payload"]),
            )
            for r in rows
        ]

    def latest_state(self, run_id: str) -> str | None:
        for ev in reversed(self.list_for_run(run_id)):
            if ev.type == EventType.STATE_CHANGED:
                return str(ev.payload.get("state"))
            if ev.type == EventType.RUN_COMPLETED:
                return "COMPLETE"
            if ev.type == EventType.RUN_FAILED:
                return "FAILED"
        return None

    def completed_idempotency_keys(self, run_id: str) -> set[str]:
        keys: set[str] = set()
        for ev in self.list_for_run(run_id):
            if ev.type in (EventType.STEP_COMPLETED, EventType.IDEMPOTENCY_SKIP):
                key = ev.payload.get("idempotency_key")
                if key:
                    keys.add(str(key))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key FROM idempotency WHERE run_id = ?", (run_id,)
            ).fetchall()
            for r in rows:
                keys.add(str(r["key"]))
        return keys

    def remember_idempotent(
        self, key: str, run_id: str, result: dict[str, Any], *, step_id: str | None = None
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO idempotency
                    (key, run_id, step_id, result_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        run_id,
                        step_id,
                        json.dumps(result),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                conn.commit()

    def get_idempotent(self, key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM idempotency WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        return json.loads(row["result_json"])

    def save_approval(
        self,
        approval_id: str,
        run_id: str,
        prompt: str,
        *,
        step_id: str = "",
        options: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                    INSERT OR REPLACE INTO approvals
                    (id, run_id, step_id, prompt, options_json, context_json, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
                    """,
                (
                    approval_id,
                    run_id,
                    step_id,
                    prompt,
                    json.dumps(options or ["approve", "reject"]),
                    json.dumps(context or {}),
                ),
            )
            conn.commit()

    def decide_approval(
        self, approval_id: str, decision: str, *, decided_by: str = "human"
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            if not row:
                return None
            status = "APPROVED" if decision.lower() in ("approve", "approved") else "REJECTED"
            ts = datetime.now(UTC).isoformat()
            conn.execute(
                """
                    UPDATE approvals SET status = ?, decided_by = ?, decided_at = ?
                    WHERE id = ?
                    """,
                (status, decided_by, ts, approval_id),
            )
            conn.commit()
            return {
                "id": approval_id,
                "run_id": row["run_id"],
                "step_id": row["step_id"],
                "status": status,
                "context": json.loads(row["context_json"]),
            }

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "step_id": row["step_id"],
            "prompt": row["prompt"],
            "options": json.loads(row["options_json"]),
            "context": json.loads(row["context_json"]),
            "status": row["status"],
            "decided_by": row["decided_by"],
            "decided_at": row["decided_at"],
        }

    def pending_approvals(self, run_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE status = 'PENDING' AND run_id = ?",
                    (run_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM approvals WHERE status = 'PENDING'").fetchall()
        return [
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "step_id": r["step_id"],
                "prompt": r["prompt"],
                "options": json.loads(r["options_json"]),
                "context": json.loads(r["context_json"]),
                "status": r["status"],
            }
            for r in rows
        ]

    def list_run_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT run_id FROM events ORDER BY MIN(id)").fetchall()
        return [str(r["run_id"]) for r in rows]
