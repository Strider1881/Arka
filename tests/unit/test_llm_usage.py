"""LLM_USAGE aggregation for Details view."""

from __future__ import annotations

from pathlib import Path

from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.llm.base import LLMResponse
from ark_operator.llm.fake import FakeLLM
from ark_operator.llm.usage_logger import UsageLoggingLLM
from ark_operator.runtime.llm_usage import emit_llm_usage, summarize_usage


def test_emit_and_summarize(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e.db")
    run_id = "run-usage"
    store.append(run_id, EventType.RUN_STARTED, {"goal": "x"})
    emit_llm_usage(
        store,
        run_id,
        LLMResponse(
            prompt_id="understand",
            content={},
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
        ),
    )
    store.append(run_id, EventType.TOOL_CALL, {"tool": "browser"})
    store.append(run_id, EventType.PLAN_REVISED, {"reason": "ui", "kind": "UI_RENAME"})
    summary = summarize_usage(store.list_for_run(run_id))
    assert summary["tokens_in"] == 100
    assert summary["tokens_out"] == 50
    assert summary["tokens_total"] == 150
    assert summary["cost_usd"] == 0.001
    assert summary["tool_calls"] == 1
    assert summary["plan_revisions"] == 1


def test_usage_logging_llm_wraps_fake(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "e2.db")
    run_id = "run-wrap"
    store.append(run_id, EventType.RUN_STARTED, {"goal": "x"})
    wrapped = UsageLoggingLLM(FakeLLM({}), store, run_id)
    # FakeLLM without script raises PromptNotFound — use a scripted one.
    from ark_operator.runtime.pipeline import build_default_fake_llm

    wrapped = UsageLoggingLLM(build_default_fake_llm(), store, run_id)
    resp = wrapped.complete("understand", {"request": "Process invoices", "knowledge": []})
    assert resp.tokens_in + resp.tokens_out > 0
    types = [e.type for e in store.list_for_run(run_id)]
    assert EventType.LLM_USAGE in types
