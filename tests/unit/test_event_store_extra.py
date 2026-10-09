"""Extra event-store paths for coverage (latest_state, approvals, list_run_ids)."""

from __future__ import annotations

from pathlib import Path

from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType


def test_store_helpers(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = store.new_run_id()
    store.append(run_id, EventType.RUN_STARTED, {"goal": "g"})
    store.append(run_id, EventType.STATE_CHANGED, {"state": "EXECUTE"})
    assert store.latest_state(run_id) == "EXECUTE"
    store.append(run_id, EventType.RUN_COMPLETED, {"ok": True})
    assert store.latest_state(run_id) == "COMPLETE"

    store.save_approval("a1", run_id, "Approve?", options=["approve", "reject"], context={"x": 1})
    assert store.get_approval("a1") is not None
    assert store.pending_approvals(run_id)
    assert store.decide_approval("missing", "approve") is None
    info = store.decide_approval("a1", "approve")
    assert info is not None
    assert info["status"] == "APPROVED"
    assert not store.pending_approvals(run_id)
    assert store.pending_approvals() == []
    # Single-shot: second decide must not overwrite or re-arm resume.
    assert store.decide_approval("a1", "reject") is None
    assert store.get_approval("a1")["status"] == "APPROVED"
    assert run_id in store.list_run_ids()

    run2 = store.new_run_id()
    store.append(run2, EventType.RUN_STARTED, {"goal": "g2"})
    store.append(run2, EventType.RUN_FAILED, {"reason": "x"})
    assert store.latest_state(run2) == "FAILED"
