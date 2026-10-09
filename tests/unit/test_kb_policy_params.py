"""B1: Policy params load from knowledge markdown; rules.yaml is permissions-only."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from ark_operator.domain.enums import InvoiceDecision
from ark_operator.domain.models import InvoiceRecord
from ark_operator.policy.engine import PolicyEngine
from ark_operator.policy.kb_params import assert_rules_permissions_only, load_policy_params


def test_load_policy_params_from_knowledge() -> None:
    params = load_policy_params()
    assert params.approval_threshold_usd == 5000.0
    assert params.tolerance_pct == 2.0
    assert "Pied Piper Cloud" in params.blocked_vendors
    assert params.vendor_aliases.get("Northwind Supply Co") == "Northwind Supplies"


def test_rules_yaml_permissions_only() -> None:
    rules = yaml.safe_load(Path("ark_operator/policy/rules.yaml").read_text(encoding="utf-8"))
    assert_rules_permissions_only(rules)
    assert "tool_permissions" in rules
    assert "approval_threshold_usd" not in rules


def test_assert_rules_rejects_kb_keys() -> None:
    with pytest.raises(ValueError, match="permissions-only"):
        assert_rules_permissions_only({"approval_threshold_usd": 1, "tool_permissions": {}})


def test_threshold_change_in_kb_changes_decision(tmp_path: Path) -> None:
    """Raising the KB threshold above INV-1003 amount clears the approval gate."""
    src = Path("company_world/knowledge")
    dst = tmp_path / "knowledge"
    dst.mkdir()
    for name in (
        "approval_policy.md",
        "tolerance_policy.md",
        "vendor_policy.md",
        "duplicates_policy.md",
        "escalation.md",
        "invoice_processing_sop.md",
        "security_policy.md",
    ):
        text = (src / name).read_text(encoding="utf-8")
        if name == "approval_policy.md":
            text = text.replace("$5,000.00", "$20,000.00").replace("$5,000", "$20,000")
        (dst / name).write_text(text, encoding="utf-8")

    engine = PolicyEngine(knowledge_dir=dst)
    assert engine.threshold == 20000.0
    engine.po_amounts["PO-503"] = 12400.0
    engine.vendor_by_po["PO-503"] = "Initech Systems"
    inv = InvoiceRecord(
        invoice_number="INV-1003",
        vendor="Initech Systems",
        amount=12400.0,
        po_number="PO-503",
    )
    decided = engine.decide_invoice(inv)
    assert decided.decision == InvoiceDecision.SUBMIT
