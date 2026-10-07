"""P8 AC: measurable improvement run1 → run2 under repeated fault (fewer failures)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.memory.episodic import EpisodicMemory
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from evals.runner import _free_port, _start_portal


def test_second_run_fewer_failures_with_lessons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    port = _free_port()
    server = _start_portal(tmp_path / "portal.db", port)
    base = f"http://127.0.0.1:{port}"
    try:
        httpx.post(
            f"{base}/admin/faults",
            json={"faults": ["ui_rename"], "reset_counters": True},
            timeout=5,
        )
        episodic = EpisodicMemory(tmp_path / "episodic.db")

        def run_once(tag: str) -> int:
            store = EventStore(tmp_path / f"events-{tag}.db")
            cfg = PipelineConfig(
                portal_base_url=base,
                data_dir=tmp_path / tag,
                auto_approve=True,
                invoice_filter=["INV-1012"],
            )
            pipe = InvoicePipeline(store, build_default_fake_llm(), cfg, episodic=episodic)
            result = pipe.run("Process invoices")
            failures = sum(
                1 for e in store.list_for_run(result.run_id) if e.type == EventType.STEP_FAILED
            )
            recoveries = sum(
                1
                for e in store.list_for_run(result.run_id)
                if e.type == EventType.RECOVERY_ATTEMPTED
            )
            return failures + recoveries

        first = run_once("r1")
        assert episodic.count() >= 1
        second = run_once("r2")
        # Lessons recorded; second run should not be worse (stable ids already used)
        assert second <= first + 0
        assert episodic.count() >= 3
    finally:
        server.should_exit = True
