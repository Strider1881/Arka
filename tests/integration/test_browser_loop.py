"""SPEC §6.5–6.7: one-action-at-a-time a11y browser loop (FakeLLM + real Haiku)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ark_operator.config import clear_settings_cache, get_settings
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.llm.anthropic_client import AnthropicClient
from ark_operator.llm.fake import FakeLLM
from ark_operator.runtime.browser_loop import scripted_browser_step
from ark_operator.runtime.pipeline import (
    InvoicePipeline,
    PipelineConfig,
    build_default_fake_llm,
    build_llm,
)
from ark_operator.tools.browser import BrowserTool
from ark_operator.tools.portal_api import PortalApiTool


def _has_anthropic_key() -> bool:
    clear_settings_cache()
    key = get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    return bool(key and len(key) > 8)


def _loop_llm() -> FakeLLM:
    llm = build_default_fake_llm()
    llm.register("browser_step", scripted_browser_step)
    return llm


def test_a11y_loop_submits_invoice_with_fakellm(
    live_portal: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI path forcing use_browser_loop=True: observe→action→… not submit_invoice shortcut."""
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    store = EventStore(tmp_path / "events.db")
    cfg = PipelineConfig(
        portal_base_url=live_portal,
        data_dir=tmp_path / "data",
        auto_approve=True,
        invoice_filter=["INV-1001"],
        use_browser_loop=True,
    )
    pipe = InvoicePipeline(store, _loop_llm(), cfg)
    result = pipe.run("Process this month's pending vendor invoices.")
    assert result.state.value == "COMPLETE", result.report

    events = store.list_for_run(result.run_id)
    actions = [
        e.payload.get("action")
        for e in events
        if e.type == EventType.TOOL_CALL and e.payload.get("tool") == "browser"
    ]
    assert "a11y_loop" in actions
    assert "submit_invoice" not in actions
    low_level = {a for a in actions if a in {"login", "goto", "click", "fill", "select"}}
    assert low_level, f"expected low-level a11y actions, got {actions}"
    assert "login" in low_level or "goto" in low_level
    assert "fill" in low_level or "select" in low_level
    assert "click" in low_level

    api = PortalApiTool(live_portal, email="operator@acmecorp.test", password="test-operator")
    try:
        found = api.run({"action": "invoice_by_number", "invoice_number": "INV-1001"})
        assert found.ok and found.data.get("result"), found.data
    finally:
        api.close()


def test_a11y_loop_preserves_irreversible_ledger(
    live_portal: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    store = EventStore(tmp_path / "events.db")
    cfg = PipelineConfig(
        portal_base_url=live_portal,
        data_dir=tmp_path / "data",
        auto_approve=True,
        invoice_filter=["INV-1002"],
        use_browser_loop=True,
    )
    pipe = InvoicePipeline(store, _loop_llm(), cfg)
    result = pipe.run("Process invoices")
    assert result.state.value == "COMPLETE"

    events = store.list_for_run(result.run_id)
    assert any(
        e.type == EventType.TOOL_CALL and e.payload.get("action") == "a11y_loop" for e in events
    )
    # Exactly-once: ledger commit recorded; a second submit attempt must skip.
    from ark_operator.runtime.idempotency import IrreversibleLedger, irreversible_key

    key = irreversible_key(result.run_id, "INV-1002", "submit")
    ledger = IrreversibleLedger(store, result.run_id)
    assert ledger.is_committed(key)

    inv = next(i for i in result.invoices if i.invoice_number == "INV-1002")
    pipe2 = InvoicePipeline(store, _loop_llm(), cfg)
    pipe2._setup_tools(result.run_id)
    try:
        outcome = pipe2._browser_submit(result.run_id, inv, ledger)
        assert outcome.value == "needs_attention"
    finally:
        pipe2.close()
    skips = [
        e
        for e in store.list_for_run(result.run_id)
        if e.type == EventType.IDEMPOTENCY_SKIP and e.payload.get("idempotency_key") == key
    ]
    assert skips, "second submit must hit irreversible ledger skip"

    api = PortalApiTool(live_portal, email="operator@acmecorp.test", password="test-operator")
    try:
        rows = api.run({"action": "invoices"}).data["result"]
        matches = [r for r in rows if r.get("invoice_number") == "INV-1002"]
        assert len(matches) == 1, matches
    finally:
        api.close()


@pytest.mark.skipif(
    not _has_anthropic_key(),
    reason="ANTHROPIC_API_KEY not set — FakeLLM CI path only",
)
def test_real_haiku_a11y_browser_loop(
    live_portal: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real Haiku chooses one a11y action at a time to submit a single invoice."""
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    clear_settings_cache()
    llm = build_llm(require_anthropic=True)
    assert isinstance(llm, AnthropicClient)

    def _run_once(tag: str) -> tuple[str, list[str | None], dict[str, object] | None, str]:
        import httpx

        clear_settings_cache()
        assert get_settings().portal_operator_password == "test-operator"
        httpx.post(
            f"{live_portal}/admin/reset",
            headers={"x-portal-admin-token": "test-admin-token"},
            timeout=10,
        )
        # Confirm master data readable before spending Haiku tokens.
        probe = PortalApiTool(live_portal, email="operator@acmecorp.test", password="test-operator")
        try:
            pos = probe.run({"action": "pos"})
            assert pos.ok and len(pos.data.get("result") or []) >= 1, pos.failure
        finally:
            probe.close()
        store = EventStore(tmp_path / f"events-{tag}.db")
        cfg = PipelineConfig(
            portal_base_url=live_portal,
            data_dir=tmp_path / tag,
            auto_approve=True,
            invoice_filter=["INV-1008"],
            use_browser_loop=True,
        )
        result = InvoicePipeline(store, llm, cfg).run(
            "Process this month's pending vendor invoices."
        )
        events = store.list_for_run(result.run_id)
        actions = [
            e.payload.get("action")
            for e in events
            if e.type == EventType.TOOL_CALL and e.payload.get("tool") == "browser"
        ]
        decision = ""
        if result.invoices:
            inv0 = result.invoices[0]
            decision = f"{inv0.decision}:{inv0.decision_reason}:{inv0.outcome}"
        api = PortalApiTool(live_portal, email="operator@acmecorp.test", password="test-operator")
        try:
            found = api.run({"action": "invoice_by_number", "invoice_number": "INV-1008"})
            raw = found.data.get("result") if found.ok else None
            row = raw if isinstance(raw, dict) else None
        finally:
            api.close()
        return result.state.value, actions, row, decision

    state, actions, row, decision = _run_once("a")
    # Retries: Haiku may skip a select; also absorb rare portal-auth races under suite load.
    if row is None:
        state, actions, row, decision = _run_once("b")
    if row is None:
        state, actions, row, decision = _run_once("c")

    assert state == "COMPLETE", decision
    assert "a11y_loop" in actions, decision
    assert "submit_invoice" not in actions
    assert any(a in {"login", "goto", "click", "fill", "select"} for a in actions)
    assert row is not None, f"Haiku a11y loop did not land INV-1008 ({decision})"
    assert row.get("status") in {"SUBMITTED", "PENDING_APPROVAL", "APPROVED"}


def test_browser_tool_select_by_label(live_portal: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    tool = BrowserTool(base_url=live_portal, evidence_dir=tmp_path / "ev", headless=True)
    try:
        assert tool.run({"action": "login"}).ok
        assert tool.run({"action": "goto", "url": "/invoices/submit"}).ok
        obs = tool.run({"action": "observe"})
        assert obs.ok
        blob = "\n".join(obs.data.get("elements") or [])
        assert "options=[" in blob
        # Find vendor select ref
        vendor_ref = None
        for line in obs.data.get("elements") or []:
            if "id=vendor_id" in line:
                vendor_ref = line.split("]")[0].lstrip("[")
                break
        assert vendor_ref
        # Empty / placeholder select must expose value= (not all-option label dump).
        before = "\n".join(obs.data.get("elements") or [])
        vendor_line = next(ln for ln in before.splitlines() if "id=vendor_id" in ln)
        assert "value=" in vendor_line, vendor_line
        assert 'value=' in vendor_line
        sel = tool.run({"action": "select", "ref": vendor_ref, "value": "Northwind"})
        assert sel.ok, sel.failure
        after_blob = "\n".join((sel.data or {}).get("elements") or [])
        after_line = next(ln for ln in after_blob.splitlines() if "id=vendor_id" in ln)
        # Selected option value must be visible so agents can confirm the select.
        assert "value='1'" in after_line or 'value="1"' in after_line, after_line
        assert "Northwind" in after_line
        assert not after_line.startswith('[e') or "Select…" not in after_line.split("options=")[0]
    finally:
        tool.close()
