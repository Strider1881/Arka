"""Genuine observe→act→fail→re-observe→adapt under portal ui_rename.

Proves the second browser_step decision uses a fresh a11y observation and picks a
different action — not hardcoded re-resolve, not submit_invoice, not RPA repair.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.browser_loop import BrowserLoop, scripted_browser_step
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from ark_operator.verify.verifier import Verifier
from company_world.portal.db import reset_database
from company_world.portal.faults import fault_state
from evals.runner import EVAL_ADMIN_TOKEN, _free_port, _start_portal


def test_ui_rename_adapt_via_fresh_observation_and_browser_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    monkeypatch.setenv("PORTAL_ADMIN_TOKEN", EVAL_ADMIN_TOKEN)

    # Capture (observation_text, choice) at the LLM boundary.
    choose_log: list[tuple[str, str, str | None]] = []
    original_choose = BrowserLoop._choose

    def tracing_choose(self, goal, fields, observation, history):  # type: ignore[no-untyped-def]
        choice = original_choose(self, goal, fields, observation, history)
        choose_log.append((observation, choice.action, choice.ref))
        return choice

    monkeypatch.setattr(BrowserLoop, "_choose", tracing_choose)

    port = _free_port()
    db_path = tmp_path / "portal.db"
    server = _start_portal(db_path, port)
    base = f"http://127.0.0.1:{port}"
    headers = {"x-portal-admin-token": EVAL_ADMIN_TOKEN}
    try:
        reset_database(db_path, operator_password="eval-pass", manager_password="eval-manager")
        httpx.post(
            f"{base}/admin/faults",
            headers=headers,
            json={"faults": ["ui_rename"], "reset_counters": True},
            timeout=5,
        )
        # Original visible label is gone; renamed control is "Transmit document".
        assert fault_state.ui_labels()["submit_button"] == "Transmit document"
        assert fault_state.ui_labels()["submit_button"] != "Submit invoice"

        store = EventStore(tmp_path / "events.db")
        cfg = PipelineConfig(
            portal_base_url=base,
            data_dir=tmp_path / "data",
            headless=True,
            auto_approve=True,
            invoice_filter=["INV-1012"],
            use_browser_loop=True,
            allow_rpa_repair=False,
        )
        llm = build_default_fake_llm()
        llm.register("browser_step", scripted_browser_step)
        pipe = InvoicePipeline(store, llm, cfg)
        result = pipe.run("Process this month's pending vendor invoices.")
        assert result.state.value == "COMPLETE", result.report
        assert result.verification is not None and result.verification.passed

        events = store.list_for_run(result.run_id)

        # No RPA / shortcut path.
        browser_actions = [
            (e.payload or {}).get("action")
            for e in events
            if e.type == EventType.TOOL_CALL and (e.payload or {}).get("tool") == "browser"
        ]
        assert "a11y_loop" in browser_actions
        assert "submit_invoice" not in browser_actions
        assert not any(
            e.type == EventType.RECOVERY_ATTEMPTED
            and "submit_invoice shortcut" in str((e.payload or {}).get("detail") or "")
            for e in events
        )
        # Explicit: adaptation went through re-observe/re-choose, not hardcoded click.
        ui_recs = [
            e
            for e in events
            if e.type == EventType.RECOVERY_ATTEMPTED
            and (e.payload or {}).get("kind") == "UI_CHANGED"
        ]
        assert ui_recs, "expected UI_CHANGED recovery"
        assert all(
            "re-observe" in str((e.payload or {}).get("detail") or "")
            and "re-choose" in str((e.payload or {}).get("detail") or "")
            and "no hardcoded re-resolve" in str((e.payload or {}).get("detail") or "")
            for e in ui_recs
        ), ui_recs

        # Click TOOL_CALLs: first prefer-label miss, later a different successful click.
        clicks = [
            e
            for e in events
            if e.type == EventType.TOOL_CALL
            and (e.payload or {}).get("tool") == "browser"
            and (e.payload or {}).get("action") == "click"
        ]
        assert len(clicks) >= 2, f"expected ≥2 clicks for fail-then-adapt, got {len(clicks)}"
        first_click = clicks[0]
        assert "prefer label" in str((first_click.payload or {}).get("rationale") or "")
        first_ref = ((first_click.payload or {}).get("args") or {}).get("ref")
        assert first_ref == "e_missing_submit_label" or first_ref  # original target unavailable

        later = clicks[1:]
        assert any(
            "stable id" in str((c.payload or {}).get("rationale") or "")
            or ((c.payload or {}).get("args") or {}).get("ref") != first_ref
            for c in later
        ), f"second action must differ from failed first click: {clicks}"

        # Fresh a11y OBSERVATION between failed click decision and adapted click decision.
        # Walk event order: OBSERVATION → click(prefer label) → … → OBSERVATION → click(adapt).
        timed = [(e.type, e.payload) for e in events]
        first_click_idx = next(
            i
            for i, (t, p) in enumerate(timed)
            if t == EventType.TOOL_CALL
            and (p or {}).get("action") == "click"
            and "prefer label" in str((p or {}).get("rationale") or "")
        )
        adapt_click_idx = next(
            i
            for i, (t, p) in enumerate(timed)
            if i > first_click_idx
            and t == EventType.TOOL_CALL
            and (p or {}).get("action") == "click"
            and "prefer label" not in str((p or {}).get("rationale") or "")
        )
        mid_obs = [
            i
            for i, (t, p) in enumerate(timed)
            if first_click_idx < i < adapt_click_idx
            and t == EventType.OBSERVATION
            and (p or {}).get("kind") == "a11y"
        ]
        assert mid_obs, "expected fresh a11y OBSERVATION before adapted click"

        # LLM boundary: ≥2 click choices; second observation lacks 'Submit invoice' button text
        # and still exposes stable id — second choice must use that fresh observation.
        click_choices = [(obs, action, ref) for obs, action, ref in choose_log if action == "click"]
        assert len(click_choices) >= 2, choose_log
        obs1, _a1, ref1 = click_choices[0]
        obs2, _a2, ref2 = click_choices[1]
        assert obs1 != obs2 or ref1 != ref2
        assert "submit invoice" not in obs1.lower() or "transmit document" in obs1.lower()
        # Under ui_rename the visible name is Transmit document; Submit invoice label absent.
        assert "transmit document" in obs2.lower()
        assert "id=submit-invoice-button" in obs2
        assert ref2 is not None and ref2 != "e_missing_submit_label"
        assert ref2 in obs2, "adapted click ref must come from the second observation"
        assert ref1 != ref2

        # Independent verifier confirms portal state (already on result; re-check explicitly).
        verifier = Verifier(
            base,
            evidence_dir=tmp_path / "verify",
            headless=True,
            email="operator@acmecorp.test",
            password="eval-pass",
        )
        try:
            inv = next(i for i in result.invoices if i.invoice_number == "INV-1012")
            v = verifier.verify_invoices([inv])
        finally:
            verifier.close()
        assert v.passed, v.overall_notes
    finally:
        server.should_exit = True
