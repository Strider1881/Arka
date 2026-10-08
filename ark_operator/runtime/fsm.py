"""Explicit run state machine — illegal transitions raise (SPEC §6.2)."""

from __future__ import annotations

from ark_operator.domain.enums import RunState
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType

ALLOWED: dict[RunState, frozenset[RunState]] = {
    RunState.INTAKE: frozenset({RunState.UNDERSTAND, RunState.FAILED}),
    RunState.UNDERSTAND: frozenset({RunState.CLARIFY, RunState.PLAN, RunState.FAILED}),
    RunState.CLARIFY: frozenset({RunState.PLAN, RunState.AWAIT_APPROVAL, RunState.FAILED}),
    RunState.PLAN: frozenset({RunState.EXECUTE, RunState.FAILED}),
    RunState.EXECUTE: frozenset(
        {
            RunState.EXECUTE,
            RunState.AWAIT_APPROVAL,
            RunState.VERIFY,
            RunState.PLAN,
            RunState.REPORT,  # budget / stall honest partial exit
            RunState.FAILED,
            RunState.ESCALATED,
        }
    ),
    # PLAN: resume after CLARIFY pause; EXECUTE: resume after mid-run approval pause.
    RunState.AWAIT_APPROVAL: frozenset(
        {RunState.EXECUTE, RunState.PLAN, RunState.FAILED, RunState.ESCALATED}
    ),
    RunState.VERIFY: frozenset({RunState.REPAIR, RunState.REPORT, RunState.FAILED}),
    RunState.REPAIR: frozenset({RunState.EXECUTE, RunState.REPORT, RunState.FAILED}),
    RunState.REPORT: frozenset({RunState.COMPLETE, RunState.FAILED}),
    RunState.COMPLETE: frozenset(),
    RunState.ESCALATED: frozenset(),
    RunState.FAILED: frozenset(),
}


class IllegalTransition(ValueError):
    """Raised when a phase attempts a transition not in ALLOWED."""


def assert_legal(src: RunState, dst: RunState) -> None:
    if src == dst:
        return
    allowed = ALLOWED.get(src, frozenset())
    if dst not in allowed:
        raise IllegalTransition(f"Illegal transition {src.value} -> {dst.value}")


class StateMachine:
    """Append-only state changes via the event store; never mutates in place silently."""

    def __init__(
        self, store: EventStore, run_id: str, *, initial: RunState = RunState.INTAKE
    ) -> None:
        self.store = store
        self.run_id = run_id
        self._state = initial

    @property
    def state(self) -> RunState:
        return self._state

    @classmethod
    def from_fold(cls, store: EventStore, run_id: str, current: RunState) -> StateMachine:
        return cls(store, run_id, initial=current)

    def transition(self, new_state: RunState) -> RunState:
        assert_legal(self._state, new_state)
        if new_state != self._state:
            self.store.append(
                self.run_id,
                EventType.STATE_CHANGED,
                {"state": new_state.value, "from": self._state.value},
            )
            self._state = new_state
        return self._state
