"""Run state machine (SPEC §6.2) with crash-safe resume via event store."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ark_operator.domain.enums import TERMINAL_STATES, RiskLevel, RunState, StepStatus
from ark_operator.domain.models import Goal, Plan, RunReport, Step, WorkingState
from ark_operator.events.replay import fold_working_state
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.budgets import Budgets
from ark_operator.runtime.fsm import IllegalTransition, assert_legal
from ark_operator.runtime.stall_detector import StallDetector


class PhaseHandler(Protocol):
    def __call__(self, ctx: RunContext) -> RunState: ...


@dataclass
class RunContext:
    run_id: str
    store: EventStore
    goal: Goal
    state: RunState
    plan: Plan | None = None
    budgets: Budgets = field(default_factory=Budgets)
    stall: StallDetector = field(default_factory=StallDetector)
    working: WorkingState | None = None
    report: RunReport | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    pause: bool = False  # set True to stop loop (await approval / kill checkpoint)


class Orchestrator:
    """Run-id allocator + optional scripted phase driver (tests / helpers).

    Hiring demo production path: ``InvoicePipeline`` owns Understand→Plan→Execute→
    Verify→Report via the FSM. ``Orchestrator.start()`` is used only to allocate a
    ``run_id`` and append ``RUN_STARTED``. ``run_until_idle`` + phase handlers are
    retained for unit tests (``scripted_demo_handlers``) — they are **not** the
    measured invoice operator control plane. See DECISIONS.md.
    """

    def __init__(
        self,
        store: EventStore,
        handlers: dict[RunState, PhaseHandler] | None = None,
    ) -> None:
        self.store = store
        self.handlers: dict[RunState, PhaseHandler] = handlers or {}

    def register(self, state: RunState, handler: PhaseHandler) -> None:
        self.handlers[state] = handler

    def start(self, request: str) -> str:
        """Start a new run; return run_id."""
        run_id = self.store.new_run_id()
        self.store.append(
            run_id,
            EventType.RUN_STARTED,
            {"goal": request},
        )
        self._set_state(run_id, RunState.INTAKE)
        return run_id

    def resume(self, run_id: str) -> RunContext:
        """Build context from folded events for crash-safe resume."""
        events = self.store.list_for_run(run_id)
        if not events:
            raise KeyError(f"Unknown run_id={run_id}")
        goal_text = ""
        for ev in events:
            if ev.type == EventType.RUN_STARTED:
                goal_text = str(ev.payload.get("goal", ""))
                break
        working = fold_working_state(self.store, run_id)
        state = RunState(working.state)
        plan = _restore_plan(events)
        ctx = RunContext(
            run_id=run_id,
            store=self.store,
            goal=Goal(text=goal_text or "(unknown)"),
            state=state,
            plan=plan,
            working=working,
        )
        # Restore completed idempotency keys into extras for handlers
        ctx.extras["completed_keys"] = self.store.completed_idempotency_keys(run_id)
        return ctx

    def transition(self, ctx: RunContext, new_state: RunState) -> None:
        try:
            assert_legal(ctx.state, new_state)
        except IllegalTransition:
            raise
        ctx.state = new_state
        self._set_state(ctx.run_id, new_state)

    def _set_state(self, run_id: str, state: RunState) -> None:
        self.store.append(run_id, EventType.STATE_CHANGED, {"state": state.value})

    def run_until_idle(self, run_id: str, *, max_transitions: int = 500) -> RunContext:
        """Advance the state machine until terminal, pause, or budget exhaustion."""
        ctx = self.resume(run_id)
        steps = 0
        while ctx.state not in TERMINAL_STATES and not ctx.pause and steps < max_transitions:
            handler = self.handlers.get(ctx.state)
            if handler is None:
                self.store.append(
                    ctx.run_id,
                    EventType.RUN_FAILED,
                    {"reason": f"No handler for state {ctx.state}"},
                )
                self.transition(ctx, RunState.FAILED)
                break
            status = ctx.budgets.check()
            if status == "warning":
                ctx.budgets.mark_warned()
                self.store.append(
                    ctx.run_id,
                    EventType.BUDGET_WARNING,
                    {"ratios": ctx.budgets.ratios()},
                )
            if status == "exhausted":
                self.store.append(
                    ctx.run_id,
                    EventType.RUN_FAILED,
                    {"reason": "budget exhausted", "ratios": ctx.budgets.ratios()},
                )
                self.transition(ctx, RunState.FAILED)
                break

            next_state = handler(ctx)
            ctx.budgets.record_step()
            steps += 1
            if ctx.pause:
                break
            if next_state != ctx.state:
                self.transition(ctx, next_state)
            elif ctx.state in TERMINAL_STATES:
                break
            # same-state loop (e.g. EXECUTE processing next step) continues
        ctx.working = fold_working_state(self.store, run_id)
        return ctx

    def should_skip_step(self, ctx: RunContext, step: Step) -> bool:
        key = step.idempotency_key or step.id
        completed = ctx.extras.get("completed_keys") or set()
        if key in completed or self.store.get_idempotent(key) is not None:
            self.store.append(
                ctx.run_id,
                EventType.IDEMPOTENCY_SKIP,
                {"idempotency_key": key, "step_id": step.id},
                step_id=step.id,
            )
            return True
        return False


def scripted_demo_handlers(
    *,
    on_execute_step: Callable[[RunContext, Step], None] | None = None,
) -> dict[RunState, PhaseHandler]:
    """
    Minimal FakeLLM-friendly handlers for P2 AC:
    INTAKE -> UNDERSTAND -> PLAN -> EXECUTE (one scripted step) -> VERIFY -> REPORT -> COMPLETE
    Supports kill/resume via idempotency on the execute step.
    """

    def intake(ctx: RunContext) -> RunState:
        return RunState.UNDERSTAND

    def understand(ctx: RunContext) -> RunState:
        ctx.store.append(
            ctx.run_id,
            EventType.INTERPRETATION_CREATED,
            {
                "intended_outcome": "Process pending vendor invoices",
                "assumptions": ["Demo scripted path"],
            },
        )
        return RunState.PLAN

    def plan(ctx: RunContext) -> RunState:
        step = Step(
            id="step-demo-1",
            description="Scripted demo step",
            tool="noop",
            args={},
            risk_level=RiskLevel.READ,
            status=StepStatus.READY,
            idempotency_key=f"{ctx.run_id}:step-demo-1",
        )
        ctx.plan = Plan(steps=[step])
        ctx.store.append(
            ctx.run_id,
            EventType.PLAN_CREATED,
            {"plan_id": ctx.plan.id, "steps": [step.model_dump(mode="json")]},
        )
        ctx.extras["demo_step_done"] = False
        return RunState.EXECUTE

    def execute(ctx: RunContext) -> RunState:
        assert ctx.plan is not None
        step = ctx.plan.steps[0]

        key = step.idempotency_key or step.id
        completed = ctx.extras.get("completed_keys") or set()
        if key in completed or ctx.store.get_idempotent(key) is not None:
            ctx.store.append(
                ctx.run_id,
                EventType.IDEMPOTENCY_SKIP,
                {"idempotency_key": key, "step_id": step.id},
                step_id=step.id,
            )
            return RunState.VERIFY

        ctx.store.append(
            ctx.run_id,
            EventType.STEP_STARTED,
            {"idempotency_key": step.idempotency_key},
            step_id=step.id,
        )
        if on_execute_step:
            on_execute_step(ctx, step)
        else:
            ctx.store.append(
                ctx.run_id,
                EventType.TOOL_CALL,
                {"tool": "noop", "args": {}},
                step_id=step.id,
            )
            obs = {"summary": "noop ok", "success": True}
            ctx.store.append(ctx.run_id, EventType.OBSERVATION, obs, step_id=step.id)

        result = {"ok": True, "summary": "demo step complete"}
        ctx.store.remember_idempotent(step.idempotency_key, ctx.run_id, result, step_id=step.id)
        ctx.store.append(
            ctx.run_id,
            EventType.STEP_COMPLETED,
            {"idempotency_key": step.idempotency_key, **result},
            step_id=step.id,
        )
        completed = ctx.extras.setdefault("completed_keys", set())
        if isinstance(completed, set):
            completed.add(step.idempotency_key)

        # Kill switch: crash after irreversible step committed, before VERIFY
        if ctx.extras.get("kill_after_step") and not ctx.extras.get("killed"):
            ctx.extras["killed"] = True
            ctx.pause = True
            return RunState.EXECUTE

        return RunState.VERIFY

    def verify(ctx: RunContext) -> RunState:
        ctx.store.append(ctx.run_id, EventType.VERIFICATION_STARTED, {})
        ctx.store.append(
            ctx.run_id,
            EventType.VERIFICATION_RESULT,
            {"passed": True, "confidence": "HIGH"},
        )
        return RunState.REPORT

    def report(ctx: RunContext) -> RunState:
        ctx.report = RunReport(run_id=ctx.run_id, summary="Scripted demo run completed.")
        ctx.store.append(
            ctx.run_id,
            EventType.REPORT_CREATED,
            ctx.report.model_dump(mode="json"),
        )
        ctx.store.append(ctx.run_id, EventType.RUN_COMPLETED, {"ok": True})
        return RunState.COMPLETE

    return {
        RunState.INTAKE: intake,
        RunState.UNDERSTAND: understand,
        RunState.PLAN: plan,
        RunState.EXECUTE: execute,
        RunState.VERIFY: verify,
        RunState.REPORT: report,
    }


def action_hash(name: str, args: dict[str, Any]) -> str:
    blob = f"{name}:{sorted(args.items())}"
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _restore_plan(events: list[Any]) -> Plan | None:
    from ark_operator.events.types import EventRecord

    plan: Plan | None = None
    for ev in events:
        assert isinstance(ev, EventRecord)
        if ev.type in (EventType.PLAN_CREATED, EventType.PLAN_REVISED):
            steps_data = ev.payload.get("steps") or []
            steps = [Step.model_validate(s) for s in steps_data]
            plan = Plan(
                id=str(ev.payload.get("plan_id", "plan-1")),
                steps=steps,
                revision=int(ev.payload.get("revision", 0)),
            )
    return plan
