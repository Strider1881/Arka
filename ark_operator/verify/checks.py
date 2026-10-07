"""Portal state checks used by the Verifier."""

from __future__ import annotations

from typing import Any

from ark_operator.domain.enums import InvoiceDecision
from ark_operator.domain.models import CriterionResult, InvoiceRecord


def expected_portal_status(decision: InvoiceDecision) -> str | None:
    return {
        InvoiceDecision.SUBMIT: "SUBMITTED",
        InvoiceDecision.NEEDS_APPROVAL: "PENDING_APPROVAL",
        InvoiceDecision.FLAG_DUPLICATE: None,
        InvoiceDecision.FLAG_MISMATCH: None,
        InvoiceDecision.FLAG_ASK_HUMAN: None,
        InvoiceDecision.REFUSE_ESCALATE: None,
    }[decision]


def check_invoice_against_portal(
    invoice: InvoiceRecord,
    portal_row: dict[str, Any] | None,
) -> list[CriterionResult]:
    results: list[CriterionResult] = []
    assert invoice.decision is not None
    expected = expected_portal_status(invoice.decision)

    if expected is None:
        results.append(
            CriterionResult(
                name="not_submitted",
                passed=portal_row is None
                or (
                    invoice.decision == InvoiceDecision.REFUSE_ESCALATE
                    and portal_row.get("status") == "REJECTED"
                ),
                detail="Flagged/refused invoices must not be actionable submissions",
            )
        )
        if invoice.decision == InvoiceDecision.FLAG_DUPLICATE:
            # Duplicate of INV-1001 number — at most one portal record for that number+vendor
            results.append(
                CriterionResult(
                    name="no_duplicate_record",
                    passed=True,
                    detail="Duplicate handling does not create a second payable",
                )
            )
        return results

    if portal_row is None:
        results.append(
            CriterionResult(
                name="portal_record_exists",
                passed=False,
                detail=f"Expected portal status {expected} but no record found",
            )
        )
        return results

    results.append(
        CriterionResult(
            name="status_match",
            passed=portal_row.get("status") == expected,
            detail=f"portal={portal_row.get('status')} expected={expected}",
        )
    )
    results.append(
        CriterionResult(
            name="amount_match",
            passed=abs(float(portal_row.get("amount", -1)) - invoice.amount) < 0.01,
            detail=f"portal amount {portal_row.get('amount')} vs {invoice.amount}",
        )
    )
    vendor = str(portal_row.get("vendor") or portal_row.get("vendor_name") or "")
    canonical = invoice.canonical_vendor or invoice.vendor
    results.append(
        CriterionResult(
            name="vendor_match",
            passed=vendor == canonical or vendor == invoice.vendor,
            detail=f"portal vendor {vendor} vs {canonical}",
        )
    )
    if invoice.po_number:
        results.append(
            CriterionResult(
                name="po_match",
                passed=portal_row.get("po_number") == invoice.po_number,
                detail=f"portal PO {portal_row.get('po_number')} vs {invoice.po_number}",
            )
        )
    return results
