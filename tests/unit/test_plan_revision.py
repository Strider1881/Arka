"""Observation-driven PLAN_REVISED (not cosmetic description tweaks)."""

from __future__ import annotations

from ark_operator.domain.enums import RiskLevel, StepStatus
from ark_operator.domain.models import Plan, Step
from ark_operator.runtime.plan_revision import (
    AUTH_EXPIRED,
    MISSING_PO,
    UI_RENAME,
    WRONG_PAGE,
    apply_revision,
    detect_from_browser_observation,
    detect_missing_po,
    propose_revision,
    revision_event_payload,
)


def _base_plan() -> Plan:
    return Plan(
        id="top-1",
        steps=[
            Step(
                id="process-invoices",
                description="Process each invoice",
                tool="orchestrator",
                args={},
                risk_level=RiskLevel.IRREVERSIBLE,
                status=StepStatus.READY,
            )
        ],
    )


def test_detect_ui_rename_from_label_recovery() -> None:
    c = detect_from_browser_observation(
        url="http://x/invoices/42",
        recovered_from_label=True,
        ok=True,
        invoice_number="INV-1012",
    )
    assert c is not None
    assert c.kind == UI_RENAME
    prop = propose_revision(_base_plan(), c)
    assert "stable" in prop.reason.lower() or "renamed" in prop.reason.lower()
    assert any("stable" in s.lower() or "re-resolve" in s.lower() for s in prop.next_steps)
    revised = apply_revision(_base_plan(), prop)
    assert revised.revision == 1
    assert revised.steps[0].args.get("prefer_stable_ids") is True
    payload = revision_event_payload(revised, prop)
    assert payload["reason"]
    assert payload["next_steps"]
    assert payload["kind"] == UI_RENAME


def test_detect_wrong_page_still_on_submit() -> None:
    c = detect_from_browser_observation(
        url="http://x/invoices/submit",
        ok=False,
        invoice_number="INV-1001",
    )
    assert c is not None
    assert c.kind == WRONG_PAGE
    prop = propose_revision(_base_plan(), c)
    assert any("goto" in s.lower() or "submit" in s.lower() for s in prop.next_steps)
    revised = apply_revision(_base_plan(), prop)
    assert revised.steps[0].args.get("recover_wrong_page") is True


def test_detect_auth_expired_on_login_url() -> None:
    c = detect_from_browser_observation(url="http://x/login", ok=False, invoice_number="INV-1011")
    assert c is not None
    assert c.kind == AUTH_EXPIRED
    prop = propose_revision(_base_plan(), c)
    assert any("login" in s.lower() for s in prop.next_steps)
    revised = apply_revision(_base_plan(), prop)
    assert revised.steps[0].args.get("relogin_on_auth_expired") is True


def test_detect_missing_po_inserts_ask_step() -> None:
    c = detect_missing_po(
        invoice_number="INV-1006",
        po_number="",
        decision="flag_ask_human",
    )
    assert c is not None
    assert c.kind == MISSING_PO
    prop = propose_revision(_base_plan(), c)
    assert any("ask" in s.lower() for s in prop.next_steps)
    revised = apply_revision(_base_plan(), prop)
    ask = next(s for s in revised.steps if s.id == "INV-1006:ask")
    assert ask.tool == "ask_human"
    assert ask.args.get("reason") == "missing_po"


def test_no_contradiction_on_happy_landing() -> None:
    assert (
        detect_from_browser_observation(
            url="http://x/invoices/7",
            ok=True,
            recovered_from_label=False,
        )
        is None
    )


def test_missing_po_skipped_when_po_present() -> None:
    assert detect_missing_po(invoice_number="INV-1001", po_number="PO-501") is None
