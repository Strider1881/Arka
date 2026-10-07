"""Pure fold of events → run snapshot (no hidden mutable globals)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ark_operator.domain.enums import RunState
from ark_operator.domain.models import WorkingState
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventRecord, EventType


@dataclass(frozen=True)
class RunSnapshot:
    """Immutable view derived solely by folding the event log."""

    run_id: str
    state: RunState
    goal: str = ""
    completed_steps: tuple[str, ...] = ()
    pending_steps: tuple[str, ...] = ()
    pending_approvals: tuple[str, ...] = ()
    irreversible_keys: frozenset[str] = field(default_factory=frozenset)
    seen_duplicate_keys: frozenset[str] = field(default_factory=frozenset)
    invoice_decisions: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_working_state(self) -> WorkingState:
        return WorkingState(
            run_id=self.run_id,
            state=self.state.value,
            goal=self.goal,
            completed_steps=list(self.completed_steps),
            pending_steps=list(self.pending_steps),
            pending_approvals=list(self.pending_approvals),
            notes=list(self.notes),
        )


def replay_run(store: EventStore, run_id: str) -> list[dict[str, Any]]:
    """Render a run's timeline from events."""
    return [
        {
            "seq": ev.seq,
            "ts": ev.ts,
            "type": ev.type.value,
            "step_id": ev.step_id,
            "payload": ev.payload,
        }
        for ev in store.list_for_run(run_id)
    ]


@dataclass
class _FoldAcc:
    state: RunState = RunState.INTAKE
    goal: str = ""
    completed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    irreversible: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    decisions: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def fold_run(store: EventStore, run_id: str) -> RunSnapshot:
    """Pure fold: events → RunSnapshot. Deterministic and side-effect free."""
    acc = _FoldAcc()
    for ev in store.list_for_run(run_id):
        _apply(ev, acc)
    return RunSnapshot(
        run_id=run_id,
        state=acc.state,
        goal=acc.goal,
        completed_steps=tuple(acc.completed),
        pending_steps=tuple(acc.pending),
        pending_approvals=tuple(acc.approvals),
        irreversible_keys=frozenset(acc.irreversible),
        seen_duplicate_keys=frozenset(acc.seen),
        invoice_decisions=dict(acc.decisions),
        notes=tuple(acc.notes),
    )


def _apply(ev: EventRecord, acc: _FoldAcc) -> None:
    if ev.type == EventType.RUN_STARTED:
        acc.goal = str(ev.payload.get("goal", ""))
        acc.state = RunState.INTAKE
        return
    if ev.type == EventType.STATE_CHANGED:
        raw = str(ev.payload.get("state", acc.state.value))
        if raw in RunState._value2member_map_:
            acc.state = RunState(raw)
        return
    if ev.type == EventType.STEP_STARTED and ev.step_id:
        if ev.step_id not in acc.pending:
            acc.pending.append(ev.step_id)
        return
    if ev.type == EventType.STEP_COMPLETED:
        if ev.step_id and ev.step_id in acc.pending:
            acc.pending.remove(ev.step_id)
        if ev.step_id and ev.step_id not in acc.completed:
            acc.completed.append(ev.step_id)
        key = ev.payload.get("idempotency_key")
        if key and ev.payload.get("irreversible") and ev.payload.get("ok"):
            acc.irreversible.add(str(key))
        decision = ev.payload.get("decision")
        file_id = (ev.step_id or "").split(":")[0] if ev.step_id else ""
        if decision and file_id:
            acc.decisions[file_id] = str(decision)
            if decision in {"submit", "needs_approval"}:
                vendor = str(ev.payload.get("canonical_vendor") or ev.payload.get("vendor") or "")
                inv_no = str(ev.payload.get("invoice_number") or "")
                if vendor and inv_no:
                    acc.seen.add(f"{vendor}|{inv_no}")
        return
    if ev.type == EventType.STEP_FAILED and ev.step_id:
        if ev.step_id in acc.pending:
            acc.pending.remove(ev.step_id)
        return
    if ev.type == EventType.APPROVAL_REQUESTED:
        aid = str(ev.payload.get("approval_id", ""))
        if aid and aid not in acc.approvals:
            acc.approvals.append(aid)
        return
    if ev.type == EventType.APPROVAL_DECIDED:
        aid = str(ev.payload.get("approval_id", ""))
        if aid in acc.approvals:
            acc.approvals.remove(aid)
        return
    if ev.type == EventType.IDEMPOTENCY_SKIP:
        key = ev.payload.get("idempotency_key")
        if key and ev.payload.get("irreversible"):
            acc.irreversible.add(str(key))
        return
    if ev.type == EventType.RUN_COMPLETED:
        acc.state = RunState.COMPLETE
        return
    if ev.type == EventType.RUN_FAILED:
        acc.state = RunState.FAILED
        return
    if ev.type == EventType.REPORT_CREATED:
        note = str(ev.payload.get("summary", ""))
        if note:
            acc.notes.append(note)


def fold_working_state(store: EventStore, run_id: str) -> WorkingState:
    """Backward-compatible wrapper around fold_run."""
    return fold_run(store, run_id).to_working_state()
