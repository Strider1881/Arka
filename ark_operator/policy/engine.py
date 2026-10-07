"""Policy and permission decisions: ALLOW / REQUIRE_APPROVAL / DENY (SPEC §8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ark_operator.domain.enums import InvoiceDecision, PolicyDecision, RiskLevel
from ark_operator.domain.models import InvoiceRecord, PolicyCitation

RULES_PATH = Path(__file__).resolve().parent / "rules.yaml"


class PolicyEngine:
    """Evaluate actions and invoice decisions against rules.yaml + seed expectations."""

    def __init__(self, rules_path: Path | None = None) -> None:
        path = rules_path or RULES_PATH
        self.rules: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.threshold = float(self.rules.get("approval_threshold_usd", 5000))
        self.tolerance_pct = float(self.rules.get("tolerance_pct", 2.0))
        self.blocked = set(self.rules.get("blocked_vendors") or [])
        self.aliases: dict[str, str] = dict(self.rules.get("vendor_aliases") or {})
        self.po_amounts: dict[str, float] = {}
        self.vendor_by_po: dict[str, str] = {}
        self.seen_keys: set[str] = set()

    def load_portal_master(self, vendors: list[dict[str, Any]], pos: list[dict[str, Any]]) -> None:
        for v in vendors:
            for alias in v.get("aliases") or []:
                self.aliases[str(alias)] = str(v["name"])
            if v.get("status") == "BLOCKED":
                self.blocked.add(str(v["name"]))
        for po in pos:
            self.po_amounts[str(po["po_number"])] = float(po["amount"])
            self.vendor_by_po[str(po["po_number"])] = str(
                po.get("vendor") or po.get("vendor_name") or ""
            )

    def canonicalize_vendor(self, name: str) -> str:
        return self.aliases.get(name, name)

    def decide_tool(self, tool_name: str, risk: RiskLevel) -> tuple[PolicyDecision, str]:
        perms = self.rules.get("tool_permissions") or {}
        if tool_name in perms:
            mapped = RiskLevel(str(perms[tool_name]))
            risk = mapped
        mapping = self.rules.get("risk_to_decision") or {}
        raw = mapping.get(risk.value, "ALLOW")
        # Honor rules.yaml (IRREVERSIBLE → REQUIRE_APPROVAL). Invoice-level
        # clearance_for_submit() is the second gate used by the pipeline.
        return PolicyDecision(str(raw)), f"risk:{risk.value}|tool:{tool_name}"

    def remember_seen(self, invoice: InvoiceRecord) -> None:
        """Re-seed duplicate detection after resume / idempotency skip."""
        canonical = invoice.canonical_vendor or self.canonicalize_vendor(invoice.vendor)
        if invoice.decision in {
            InvoiceDecision.SUBMIT,
            InvoiceDecision.NEEDS_APPROVAL,
        }:
            self.seen_keys.add(f"{canonical}|{invoice.invoice_number}")

    def decide_invoice(self, invoice: InvoiceRecord) -> InvoiceRecord:
        """Apply company policy to produce InvoiceDecision (deterministic)."""
        out = invoice.model_copy(deep=True)
        canonical = self.canonicalize_vendor(out.vendor)
        out.canonical_vendor = canonical
        citations: list[PolicyCitation] = []

        # Duplicates: same vendor + invoice number seen
        dup_key = f"{canonical}|{out.invoice_number}"
        if dup_key in self.seen_keys:
            out.decision = InvoiceDecision.FLAG_DUPLICATE
            out.decision_reason = "Duplicate vendor+invoice number"
            citations.append(PolicyCitation(file="duplicates_policy.md", section="Definition"))
            out.decision_reason = out.decision_reason
            return out

        if canonical in self.blocked:
            out.decision = InvoiceDecision.REFUSE_ESCALATE
            out.decision_reason = f"Vendor {canonical} is BLOCKED"
            citations.append(PolicyCitation(file="vendor_policy.md", section="Blocked vendors"))
            return out

        if not out.po_number or out.po_number not in self.po_amounts:
            out.decision = InvoiceDecision.FLAG_ASK_HUMAN
            out.decision_reason = "No matching PO"
            citations.append(
                PolicyCitation(file="escalation.md", section="Missing / no matching PO")
            )
            return out

        po_vendor = self.vendor_by_po.get(out.po_number, "")
        if po_vendor and self.canonicalize_vendor(po_vendor) != canonical:
            out.decision = InvoiceDecision.FLAG_MISMATCH
            out.decision_reason = "Vendor does not match PO vendor"
            return out

        po_amount = self.po_amounts[out.po_number]
        if po_amount > 0:
            variance = abs(out.amount - po_amount) / po_amount
            if variance > self.tolerance_pct / 100.0:
                out.decision = InvoiceDecision.FLAG_MISMATCH
                out.decision_reason = (
                    f"Amount variance {variance:.1%} exceeds {self.tolerance_pct}% tolerance"
                )
                citations.append(
                    PolicyCitation(file="tolerance_policy.md", section="Price variance")
                )
                return out

        if out.amount > self.threshold:
            out.decision = InvoiceDecision.NEEDS_APPROVAL
            out.decision_reason = (
                f"Amount ${out.amount:,.2f} above ${self.threshold:,.0f} threshold"
            )
            citations.append(PolicyCitation(file="approval_policy.md", section="Threshold"))
            self.seen_keys.add(dup_key)
            return out

        out.decision = InvoiceDecision.SUBMIT
        out.decision_reason = f"Exact/within-tolerance match to {out.po_number}"
        citations.append(PolicyCitation(file="invoice_processing_sop.md", section="Outcomes"))
        self.seen_keys.add(dup_key)
        return out

    def clearance_for_submit(self, invoice: InvoiceRecord) -> tuple[PolicyDecision, str]:
        """Irreversible submit clearance after three-way match + checks."""
        if invoice.decision == InvoiceDecision.REFUSE_ESCALATE:
            return PolicyDecision.DENY, "blocked_vendor"
        if invoice.decision in {
            InvoiceDecision.FLAG_DUPLICATE,
            InvoiceDecision.FLAG_MISMATCH,
            InvoiceDecision.FLAG_ASK_HUMAN,
        }:
            return PolicyDecision.DENY, "not_cleared_for_submit"
        if invoice.decision == InvoiceDecision.NEEDS_APPROVAL:
            return PolicyDecision.REQUIRE_APPROVAL, "over_threshold"
        if invoice.decision == InvoiceDecision.SUBMIT:
            return PolicyDecision.ALLOW, "three_way_match_ok"
        return PolicyDecision.DENY, "unknown_decision"
