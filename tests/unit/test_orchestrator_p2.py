"""P2 AC: scripted FakeLLM/orchestrator run completes, replays, survives kill/resume."""

from pathlib import Path

from ark_operator.domain.enums import RunState
from ark_operator.events.replay import replay_run
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.llm.fake import FakeLLM
from ark_operator.runtime.budgets import Budgets
from ark_operator.runtime.orchestrator import Orchestrator, scripted_demo_handlers
from ark_operator.runtime.stall_detector import StallDetector


def test_scripted_run_completes_and_replays(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    orch = Orchestrator(store, scripted_demo_handlers())
    run_id = orch.start("Process this month's pending vendor invoices.")
    ctx = orch.run_until_idle(run_id)
    assert ctx.state == RunState.COMPLETE
    timeline = replay_run(store, run_id)
    types = [e["type"] for e in timeline]
    assert EventType.RUN_STARTED.value in types
    assert EventType.PLAN_CREATED.value in types
    assert EventType.STEP_COMPLETED.value in types
    assert EventType.VERIFICATION_RESULT.value in types
    assert EventType.RUN_COMPLETED.value in types
    # Replay alone reconstructs timeline
    assert len(timeline) == len(store.list_for_run(run_id))


def test_kill_and_resume_skips_completed_idempotent_step(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    orch = Orchestrator(store, scripted_demo_handlers())
    run_id = orch.start("Process invoices")
    # First pass: complete irreversible step then "crash" before VERIFY
    ctx = orch.resume(run_id)
    ctx.extras["kill_after_step"] = True
    while ctx.state not in (RunState.COMPLETE, RunState.FAILED) and not ctx.pause:
        handler = orch.handlers[ctx.state]
        nxt = handler(ctx)
        if ctx.pause:
            break
        if nxt != ctx.state:
            orch.transition(ctx, nxt)
    assert ctx.pause is True
    assert ctx.extras.get("killed") is True

    # Simulate process restart: new orchestrator, same store — skip completed step
    orch2 = Orchestrator(store, scripted_demo_handlers())
    ctx2 = orch2.run_until_idle(run_id)
    assert ctx2.state == RunState.COMPLETE
    completed = [
        e
        for e in store.list_for_run(run_id)
        if e.type == EventType.STEP_COMPLETED and e.step_id == "step-demo-1"
    ]
    skips = [e for e in store.list_for_run(run_id) if e.type == EventType.IDEMPOTENCY_SKIP]
    assert len(completed) == 1
    assert len(skips) >= 1


def test_fake_llm_and_budgets_stall() -> None:
    llm = FakeLLM(scripts={"ping": {"ok": True}})
    assert llm.complete("ping", {}).content == {"ok": True}
    b = Budgets()
    b.record_step()
    assert b.check() is None
    stall = StallDetector(repeat_limit=3)
    assert stall.observe("a", "o") is False
    assert stall.observe("a", "o") is False
    assert stall.observe("a", "o") is True
