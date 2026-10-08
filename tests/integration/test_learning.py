"""P8 AC: measurable improvement run1 → run2 under repeated fault (lesson content)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.memory.episodic import EpisodicMemory
from ark_operator.memory.lesson_policy import prefer_label_first_from_lessons
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from company_world.portal.db import reset_database
from evals.runner import EVAL_ADMIN_TOKEN, _free_port, _start_portal


def test_second_run_fewer_recoveries_with_lessons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under ui_rename: run1 explores labels (recovers); run2 applies stable-id lesson content."""
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", EVAL_ADMIN_TOKEN)
    port = _free_port()
    db_path = tmp_path / "portal.db"
    server = _start_portal(db_path, port)
    base = f"http://127.0.0.1:{port}"
    headers = {"x-portal-admin-token": EVAL_ADMIN_TOKEN}
    try:
        episodic = EpisodicMemory(tmp_path / "episodic.db")

        def run_once(tag: str, *, use_loop: bool = True) -> tuple[int, list]:
            reset_database(db_path, operator_password="eval-pass", manager_password="eval-manager")
            httpx.post(
                f"{base}/admin/faults",
                headers=headers,
                json={"faults": ["ui_rename"], "reset_counters": True},
                timeout=5,
            )
            store = EventStore(tmp_path / f"events-{tag}.db")
            cfg = PipelineConfig(
                portal_base_url=base,
                data_dir=tmp_path / tag,
                auto_approve=True,
                invoice_filter=["INV-1012"],
                use_browser_loop=use_loop,
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

        # Empty lessons → label_first strategy from content policy.
        assert prefer_label_first_from_lessons([]) is True
        first, revs1 = run_once("r1")
        assert episodic.count() >= 1
        assert first >= 1, "run1 should recover from renamed Submit label"
        lessons = episodic.retrieve("stable", top_k=3)
        assert lessons, "distill must record UI recovery lesson content"
        assert prefer_label_first_from_lessons(lessons) is False
        assert revs1, "run1 must emit observation-driven PLAN_REVISED (UI_RENAME)"
        assert revs1[0].payload.get("reason")
        assert revs1[0].payload.get("next_steps")
        second, _revs2 = run_once("r2")
        assert second < first, f"run2 should improve: first={first} second={second}"
        assert any("stable" in str(x.get("lesson", "")).lower() for x in lessons)
    finally:
        server.should_exit = True
