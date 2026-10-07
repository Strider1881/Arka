"""Pure fold + exactly-once irreversible ledger."""

from __future__ import annotations

from pathlib import Path

from ark_operator.domain.enums import RunState
from ark_operator.events.replay import fold_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.idempotency import IrreversibleLedger, irreversible_key


def test_fold_is_pure_and_deterministic(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = store.new_run_id()
    store.append(run_id, EventType.RUN_STARTED, {"goal": "Process invoices"})
    store.append(run_id, EventType.STATE_CHANGED, {"state": "UNDERSTAND"})
    store.append(run_id, EventType.STATE_CHANGED, {"state": "PLAN"})
    store.append(run_id, EventType.STATE_CHANGED, {"state": "EXECUTE"})
    store.append(
        run_id,
        EventType.STEP_COMPLETED,
        {
            "idempotency_key": f"{run_id}:INV-1001:submit",
            "irreversible": True,
            "ok": True,
            "decision": "submit",
            "canonical_vendor": "Northwind Supplies",
            "invoice_number": "INV-1001",
        },
        step_id="INV-1001:act",
    )
    a = fold_run(store, run_id)
    b = fold_run(store, run_id)
    assert a == b
    assert a.state == RunState.EXECUTE
    assert a.goal == "Process invoices"
    assert irreversible_key(run_id, "INV-1001") in a.irreversible_keys
    assert "Northwind Supplies|INV-1001" in a.seen_duplicate_keys


def test_ledger_exactly_once(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = store.new_run_id()
    store.append(run_id, EventType.RUN_STARTED, {"goal": "x"})
    ledger = IrreversibleLedger(store, run_id)
    key = irreversible_key(run_id, "INV-9")
    assert not ledger.is_committed(key)
    ledger.commit(key, result={"invoice_number": "INV-9"})
    assert ledger.is_committed(key)
    # Second commit overwrites idempotency row but remains committed once
    ledger.commit(key, result={"invoice_number": "INV-9", "again": True})
    snap = fold_run(store, run_id)
    assert key in snap.irreversible_keys
