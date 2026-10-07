"""Exactly-once ledger for irreversible portal writes."""

from __future__ import annotations

from typing import Any

from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.security.redact import redact_payload


def irreversible_key(run_id: str, invoice_number: str, action: str = "submit") -> str:
    return f"{run_id}:{invoice_number}:{action}"


class IrreversibleLedger:
    """
    Exactly-once semantics for portal submits.

    A write is committed only after the tool reports success. Resume skips any
    key already present in the ledger (event-sourced + idempotency table).
    """

    def __init__(self, store: EventStore, run_id: str) -> None:
        self.store = store
        self.run_id = run_id

    def is_committed(self, key: str) -> bool:
        cached = self.store.get_idempotent(key)
        if cached and cached.get("ok") and cached.get("irreversible"):
            return True
        for ev in self.store.list_for_run(self.run_id):
            if ev.type == EventType.STEP_COMPLETED and ev.payload.get("idempotency_key") == key:
                if ev.payload.get("irreversible") and ev.payload.get("ok"):
                    return True
        return False

    def commit(self, key: str, *, result: dict[str, Any], step_id: str | None = None) -> None:
        safe = redact_payload({**result, "ok": True, "irreversible": True, "terminal": True})
        assert isinstance(safe, dict)
        self.store.remember_idempotent(key, self.run_id, safe, step_id=step_id)
        self.store.append(
            self.run_id,
            EventType.STEP_COMPLETED,
            {
                "idempotency_key": key,
                "irreversible": True,
                "ok": True,
                "result": safe,
            },
            step_id=step_id,
        )
