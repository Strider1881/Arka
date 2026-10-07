"""Portal state checks used by the Verifier."""

from __future__ import annotations

from typing import Any

from ark_operator.domain.enums import InvoiceDecision, InvoiceOutcome
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
    *,
    all_rows_for_number: list[dict[str, Any]] | None = None,
) -> list[CriterionResult]:
    results: list[CriterionResult] = []
    if invoice.decision is None:
        return [
            CriterionResult(
                name="has_decision",
                passed=False,
                detail="Invoice missing decision before verification",
            )
        ]
    expected = expected_portal_status(invoice.decision)
    rows = list(all_rows_for_number or ([] if portal_row is None else [portal_row]))

    # Human rejected an over-threshold invoice: no portal write is the correct outcome.
    if (
        invoice.decision == InvoiceDecision.NEEDS_APPROVAL
        and invoice.outcome == InvoiceOutcome.REFUSED
    ):
        results.append(
            CriterionResult(
                name="rejected_not_submitted",
                passed=portal_row is None,
                detail=(
                    "Approval rejected — no portal row"
                    if portal_row is None
                    else f"Unexpected portal status {portal_row.get('status')}"
                ),
            )
        )
        return results

    if expected is None:
        if invoice.decision == InvoiceDecision.FLAG_DUPLICATE:
            # Original row for the shared invoice number may exist; the duplicate
            # *file* must not create its own portal submission (attachment check).
            attachment = invoice.attachment_name
            if attachment:
                leaked = any(str(r.get("attachment_name") or "") == attachment for r in rows)
                results.append(
                    CriterionResult(
                        name="duplicate_not_resubmitted",
                        passed=not leaked,
                        detail=(
                            f"Duplicate file {attachment} must not appear as a portal attachment"
                            if leaked
                            else f"No portal row for duplicate file {attachment}"
                        ),
                    )
                )
            else:
                # Fall back: more than one portal row for the number means a re-submit.
                results.append(
                    CriterionResult(
                        name="duplicate_not_resubmitted",
                        passed=len(rows) <= 1,
                        detail=f"portal rows for number={len(rows)} (want ≤1)",
                    )
                )
            return results
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
