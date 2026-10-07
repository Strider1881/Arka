"""P4 AC: policy decisions match expected_outcomes for all 12 invoices (FakeLLM path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ark_operator.domain.models import InvoiceRecord
from ark_operator.policy.engine import PolicyEngine
from ark_operator.tools.pdf_extract import PdfExtractTool

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "company_world" / "inbox"
EXPECTED = json.loads((ROOT / "company_world" / "expected_outcomes.json").read_text())


@pytest.fixture
def engine(live_portal: str, monkeypatch: pytest.MonkeyPatch) -> PolicyEngine:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    from ark_operator.tools.portal_api import PortalApiTool

    api = PortalApiTool(live_portal, email="operator@acmecorp.test", password="test-operator")
    try:
        vendors = api.run({"action": "vendors"}).data["result"]
        pos = api.run({"action": "pos"}).data["result"]
    finally:
        api.close()
    eng = PolicyEngine()
    eng.load_portal_master(vendors, pos)
    return eng


def test_all_twelve_decisions_match_expected(engine: PolicyEngine) -> None:
    pdf = PdfExtractTool()
    expected_by_number = {i["invoice_number"]: i for i in EXPECTED["invoices"]}
    # Process in order so INV-1001 registers before INV-1004 duplicate
    for n in range(1001, 1013):
        file_id = f"INV-{n}"
        path = INBOX / f"{file_id}.pdf"
        extracted = pdf.run({"path": str(path)})
        assert extracted.ok, extracted.failure
        inv = InvoiceRecord.model_validate(extracted.data["invoice"])
        inv.security_finding = bool(extracted.data.get("security_finding"))
        decided = engine.decide_invoice(inv)
        exp = expected_by_number[file_id]
        assert decided.decision is not None
        assert decided.decision.value == exp["decision"], (
            f"{file_id}: got {decided.decision.value} ({decided.decision_reason}) "
            f"expected {exp['decision']} (extracted no={inv.invoice_number})"
        )
        if file_id == "INV-1004":
            assert inv.invoice_number == "INV-1001"
        if file_id == "INV-1010":
            assert inv.security_finding is True


def test_irreversible_requires_clearance(engine: PolicyEngine) -> None:
    inv = InvoiceRecord(
        invoice_number="INV-X",
        vendor="Pied Piper Cloud",
        amount=100.0,
        po_number="PO-509",
    )
    decided = engine.decide_invoice(inv)
    clearance, rule = engine.clearance_for_submit(decided)
    assert clearance.value == "DENY"
    assert "blocked" in rule
