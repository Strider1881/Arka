"""Replay a run timeline from the event store alone."""

from __future__ import annotations

from typing import Any

from ark_operator.domain.enums import RunState
from ark_operator.domain.models import WorkingState
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventRecord, EventType


def replay_run(store: EventStore, run_id: str) -> list[dict[str, Any]]:
    """Render a run's timeline from events."""
    timeline: list[dict[str, Any]] = []
    for ev in store.list_for_run(run_id):
        timeline.append(
            {
                "seq": ev.seq,
                "ts": ev.ts,
                "type": ev.type.value,
                "step_id": ev.step_id,
                "payload": ev.payload,
            }
        )
    return timeline


def fold_working_state(store: EventStore, run_id: str) -> WorkingState:
    """Derive compact working state by folding events."""
    state = WorkingState(run_id=run_id, state=RunState.INTAKE.value)
    completed: list[str] = []
    pending: list[str] = []
    for ev in store.list_for_run(run_id):
        _apply(state, ev, completed, pending)
    state.completed_steps = completed
    state.pending_steps = pending
    return state


def _apply(
    state: WorkingState,
    ev: EventRecord,
    completed: list[str],
    pending: list[str],
) -> None:
    if ev.type == EventType.RUN_STARTED:
        state.goal = str(ev.payload.get("goal", ""))
        state.state = RunState.INTAKE.value
    elif ev.type == EventType.STATE_CHANGED:
        state.state = str(ev.payload.get("state", state.state))
    elif ev.type == EventType.STEP_STARTED and ev.step_id:
        if ev.step_id not in pending:
            pending.append(ev.step_id)
    elif ev.type == EventType.STEP_COMPLETED and ev.step_id:
        if ev.step_id in pending:
            pending.remove(ev.step_id)
        if ev.step_id not in completed:
            completed.append(ev.step_id)
    elif ev.type == EventType.STEP_FAILED and ev.step_id:
        if ev.step_id in pending:
            pending.remove(ev.step_id)
    elif ev.type == EventType.APPROVAL_REQUESTED:
        aid = str(ev.payload.get("approval_id", ""))
        if aid and aid not in state.pending_approvals:
            state.pending_approvals.append(aid)
    elif ev.type == EventType.APPROVAL_DECIDED:
        aid = str(ev.payload.get("approval_id", ""))
        if aid in state.pending_approvals:
            state.pending_approvals.remove(aid)
    elif ev.type == EventType.RUN_COMPLETED:
        state.state = RunState.COMPLETE.value
    elif ev.type == EventType.RUN_FAILED:
        state.state = RunState.FAILED.value
    elif ev.type == EventType.REPORT_CREATED:
        note = str(ev.payload.get("summary", ""))
        if note:
            state.notes.append(note)
