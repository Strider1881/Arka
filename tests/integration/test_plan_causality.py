"""Plan → runtime decision → browser behavior causality (not log-only).

Proves the existing PLAN_REVISED browser-prefs channel actually changes a11y
actions for the same submit task. Uses production
``_apply_plan_browser_prefs`` + ``_browser_submit`` (a11y loop) — the same
path ``_emit_plan_revision`` takes after observation contradictions.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ark_operator.domain.enums import InvoiceDecision, RiskLevel, StepStatus
from ark_operator.domain.models import InvoiceRecord, Plan, Step
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.idempotency import IrreversibleLedger
from ark_operator.runtime.orchestrator import Orchestrator
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from ark_operator.runtime.plan_revision import (
    UI_RENAME,
    Contradiction,
    apply_revision,
    browser_prefs_from_plan,
    propose_revision,
)


def _base_process_plan() -> Plan:
    return Plan(
        id="top-causality",
        steps=[
            Step(
                id="process-invoices",
                description="Process each invoice via portal a11y loop",
                tool="orchestrator",
                args={},
                risk_level=RiskLevel.IRREVERSIBLE,
                status=StepStatus.READY,
            )
        ],
    )


def _click_rationales(store: EventStore, run_id: str) -> list[str]:
    out: list[str] = []
    for ev in store.list_for_run(run_id):
        if ev.type != EventType.TOOL_CALL:
            continue
        payload = ev.payload or {}
        if payload.get("tool") != "browser" or payload.get("action") != "click":
            continue
        out.append(str(payload.get("rationale") or ""))
    return out


def _run_submit_under_plan(
    *,
    plan: Plan,
    live_portal: str,
    tmp_path: Path,
    tag: str,
    invoice_number: str,
) -> tuple[list[str], bool]:
    """Identical task/setup; only ``plan`` (via browser prefs) differs."""
    store = EventStore(tmp_path / f"events-{tag}.db")
    cfg = PipelineConfig(
        portal_base_url=live_portal,
        data_dir=tmp_path / tag,
        headless=True,
        auto_approve=True,
        use_browser_loop=True,
        allow_rpa_repair=False,
    )
    pipe = InvoicePipeline(store, build_default_fake_llm(), cfg)
    run_id = Orchestrator(store).start(f"causality:{tag}")
    # Same tool baseline for both plans; plan prefs must be what flips strategy.
    pipe._setup_tools(run_id, prefer_label_first=True)
    pipe._plan = plan
    pipe._apply_plan_browser_prefs(plan)
    prefer_label = pipe._effective_prefer_label_first()

    inv = InvoiceRecord(
        invoice_number=invoice_number,
        vendor="Northwind Supplies",
        amount=1240.0,
        po_number="PO-501",
        invoice_date="2026-03-01",
        attachment_name=f"{invoice_number}.pdf",
        decision=InvoiceDecision.SUBMIT,
        canonical_vendor="Northwind Supplies",
    )
    ledger = IrreversibleLedger(store, run_id)
    try:
        pipe._browser_submit(run_id, inv, ledger)
    finally:
        pipe.close()

    return _click_rationales(store, run_id), prefer_label


def test_different_plans_produce_different_browser_click_behavior(
    live_portal: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Different plan → different prefer_label_first → different click rationales."""
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")

    plan_label = _base_process_plan()
    assert browser_prefs_from_plan(plan_label) == {}

    contra = Contradiction(
        kind=UI_RENAME,
        reason="Submit control renamed; prefer stable element ids",
        invoice_number="INV-CAUSE-STABLE",
    )
    plan_stable = apply_revision(plan_label, propose_revision(plan_label, contra))
    prefs_stable = browser_prefs_from_plan(plan_stable)
    assert prefs_stable.get("prefer_stable_ids") is True
    assert prefs_stable.get("prefer_label_first") is False

    clicks_label, prefer_label_a = _run_submit_under_plan(
        plan=plan_label,
        live_portal=live_portal,
        tmp_path=tmp_path,
        tag="plan-label",
        invoice_number="INV-CAUSE-LABEL",
    )
    clicks_stable, prefer_label_b = _run_submit_under_plan(
        plan=plan_stable,
        live_portal=live_portal,
        tmp_path=tmp_path,
        tag="plan-stable",
        invoice_number="INV-CAUSE-STABLE",
    )

    # Runtime decision boundary (plan prefs → BrowserLoop prefer_label_first).
    assert prefer_label_a is True, "Plan A (no prefer_stable_ids) keeps label-first"
    assert prefer_label_b is False, "Plan B (prefer_stable_ids) forces id-first"

    # Observable tool/browser behavior difference (not merely PLAN_REVISED logged).
    assert clicks_label, f"Plan A expected click TOOL_CALLs, got {clicks_label!r}"
    assert clicks_stable, f"Plan B expected click TOOL_CALLs, got {clicks_stable!r}"
    assert any("prefer label" in r for r in clicks_label), clicks_label
    assert any("stable id" in r for r in clicks_stable), clicks_stable
    assert not any("prefer label" in r for r in clicks_stable), clicks_stable
    assert clicks_label != clicks_stable
