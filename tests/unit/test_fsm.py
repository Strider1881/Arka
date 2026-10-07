"""Illegal transitions and legal paths for the run state machine."""

from __future__ import annotations

from pathlib import Path

import pytest
from ark_operator.domain.enums import RunState
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.fsm import ALLOWED, IllegalTransition, StateMachine, assert_legal


def test_illegal_transition_raises() -> None:
    with pytest.raises(IllegalTransition):
        assert_legal(RunState.COMPLETE, RunState.EXECUTE)
    with pytest.raises(IllegalTransition):
        assert_legal(RunState.INTAKE, RunState.VERIFY)


def test_all_allowed_edges_are_legal() -> None:
    for src, dsts in ALLOWED.items():
        for dst in dsts:
            assert_legal(src, dst)


def test_state_machine_persists_via_events(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = store.new_run_id()
    store.append(run_id, EventType.RUN_STARTED, {"goal": "x"})
    sm = StateMachine(store, run_id, initial=RunState.INTAKE)
    sm.transition(RunState.UNDERSTAND)
    sm.transition(RunState.PLAN)
    sm.transition(RunState.EXECUTE)
    with pytest.raises(IllegalTransition):
        sm.transition(RunState.REPORT)
    states = [
        e.payload["state"] for e in store.list_for_run(run_id) if e.type == EventType.STATE_CHANGED
    ]
    assert states == ["UNDERSTAND", "PLAN", "EXECUTE"]
