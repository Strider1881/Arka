"""Event store append/fold/idempotency tests."""

from pathlib import Path

from ark_operator.events.replay import fold_working_state, replay_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType


def test_append_and_replay(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    run_id = store.new_run_id()
    store.append(run_id, EventType.RUN_STARTED, {"goal": "hello"})
    store.append(run_id, EventType.STATE_CHANGED, {"state": "UNDERSTAND"})
    store.append(run_id, EventType.STEP_STARTED, {}, step_id="s1")
    store.append(run_id, EventType.STEP_COMPLETED, {"idempotency_key": "k1"}, step_id="s1")
    timeline = replay_run(store, run_id)
    assert len(timeline) == 4
    assert timeline[0]["type"] == "RUN_STARTED"
    working = fold_working_state(store, run_id)
    assert working.goal == "hello"
    assert "s1" in working.completed_steps


def test_idempotency_remember(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    run_id = store.new_run_id()
    store.remember_idempotent("k1", run_id, {"ok": True}, step_id="s1")
    assert store.get_idempotent("k1") == {"ok": True}
