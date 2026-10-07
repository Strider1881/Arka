"""Coverage for policy.risk, decide_tool, evidence helpers."""

from __future__ import annotations

from pathlib import Path

from ark_operator.domain.enums import InvoiceDecision, PolicyDecision, RiskLevel
from ark_operator.domain.models import InvoiceRecord
from ark_operator.policy.engine import PolicyEngine
from ark_operator.policy.risk import risk_to_decision
from ark_operator.verify.browser_verifier import browser_row_mentions
from ark_operator.verify.evidence import collect_evidence, collect_run_evidence


def test_decide_tool_honors_rules_yaml() -> None:
    engine = PolicyEngine()
    decision, rule = engine.decide_tool("browser", RiskLevel.IRREVERSIBLE)
    assert decision == PolicyDecision.REQUIRE_APPROVAL
    assert "IRREVERSIBLE" in rule or "browser" in rule
    decision2, _ = engine.decide_tool("files", RiskLevel.READ)
    assert decision2 == PolicyDecision.ALLOW


def test_risk_to_decision() -> None:
    assert risk_to_decision(RiskLevel.IRREVERSIBLE) == PolicyDecision.REQUIRE_APPROVAL
    assert risk_to_decision("READ") == PolicyDecision.ALLOW
    assert risk_to_decision(RiskLevel.REVERSIBLE_WRITE) == PolicyDecision.ALLOW


def test_decide_invoice_persists_policy_citations() -> None:
    engine = PolicyEngine()
    engine.po_amounts["PO-501"] = 1240.0
    engine.vendor_by_po["PO-501"] = "Northwind Supplies"
    inv = InvoiceRecord(
        invoice_number="INV-1001",
        vendor="Northwind Supplies",
        amount=1240.0,
        po_number="PO-501",
    )
    decided = engine.decide_invoice(inv)
    assert decided.decision == InvoiceDecision.SUBMIT
    assert decided.policy_citations
    assert decided.policy_citations[0].file.endswith(".md")


def test_decide_invoice_vendor_mismatch_cites_sop() -> None:
    engine = PolicyEngine()
    engine.po_amounts["PO-501"] = 1240.0
    engine.vendor_by_po["PO-501"] = "Northwind Supplies"
    inv = InvoiceRecord(
        invoice_number="INV-X",
        vendor="Globex Industrial",
        amount=1240.0,
        po_number="PO-501",
    )
    decided = engine.decide_invoice(inv)
    assert decided.decision == InvoiceDecision.FLAG_MISMATCH
    assert any(c.file == "invoice_processing_sop.md" for c in decided.policy_citations)


def test_browser_row_mentions() -> None:
    rows = [
        {"invoice_number": "INV-1001", "row_text": "INV-1001 | Northwind | SUBMITTED"},
        {"invoice_number": "INV-1008", "row_text": "INV-1008 | Umbrella | SUBMITTED"},
    ]
    assert browser_row_mentions(rows, "INV-1001")
    assert not browser_row_mentions(rows, "INV-9999")
    assert not browser_row_mentions([], "INV-1001")


def test_collect_evidence(tmp_path: Path) -> None:
    assert collect_evidence(tmp_path / "missing") == []
    (tmp_path / "before.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    nested = tmp_path / "repair-1"
    nested.mkdir()
    (nested / "after.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    items = collect_evidence(tmp_path)
    assert len(items) == 2
    assert items[0].kind == "screenshot"
    merged = collect_run_evidence(tmp_path, tmp_path / "missing")
    assert len(merged) == 2
