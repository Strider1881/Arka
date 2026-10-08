"""P8 AC: measurable improvement run1 → run2 under repeated fault (fewer recoveries)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.memory.episodic import EpisodicMemory
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from company_world.portal.db import reset_database
from evals.runner import _free_port, _start_portal


def test_second_run_fewer_recoveries_with_lessons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under ui_rename: run1 explores labels (recovers via stable id); run2 uses lessons."""
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    port = _free_port()
    db_path = tmp_path / "portal.db"
    server = _start_portal(db_path, port)
    base = f"http://127.0.0.1:{port}"
    try:
        episodic = EpisodicMemory(tmp_path / "episodic.db")

        def run_once(tag: str) -> int:
            # Fresh portal each run so submit success is comparable; lessons persist.
            reset_database(db_path, operator_password="eval-pass", manager_password="eval-manager")
            httpx.post(
                f"{base}/admin/faults",
                json={"faults": ["ui_rename"], "reset_counters": True},
                timeout=5,
            )
            store = EventStore(tmp_path / f"events-{tag}.db")
            cfg = PipelineConfig(
                portal_base_url=base,
                data_dir=tmp_path / tag,
                auto_approve=True,
                invoice_filter=["INV-1012"],
            )
            pipe = InvoicePipeline(store, build_default_fake_llm(), cfg, episodic=episodic)
            result = pipe.run("Process invoices")
            assert result.state.value == "COMPLETE", result.report
            events = store.list_for_run(result.run_id)
            recoveries = sum(1 for e in events if e.type == EventType.RECOVERY_ATTEMPTED)
            revisions = [
                e
                for e in events
                if e.type == EventType.PLAN_REVISED and e.payload.get("kind") == "UI_RENAME"
            ]
            return recoveries, revisions

        first, revs1 = run_once("r1")
        assert episodic.count() >= 1
        assert first >= 1, "run1 should recover from renamed Submit label"
        assert revs1, "run1 must emit observation-driven PLAN_REVISED (UI_RENAME)"
        assert revs1[0].payload.get("reason")
        assert revs1[0].payload.get("next_steps")
        second, _revs2 = run_once("r2")
        assert second < first, f"run2 should improve: first={first} second={second}"
        assert episodic.count() >= 3
        lessons = episodic.retrieve("stable", top_k=3)
        assert any("stable" in str(x.get("lesson", "")).lower() for x in lessons)
    finally:
        server.should_exit = True
