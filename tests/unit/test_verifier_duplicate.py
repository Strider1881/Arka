"""Verifier must not rubber-stamp FLAG_DUPLICATE (P7 / P3 integrity)."""

from __future__ import annotations

from ark_operator.domain.enums import InvoiceDecision
from ark_operator.domain.models import InvoiceRecord
from ark_operator.verify.checks import check_invoice_against_portal


def test_duplicate_fails_when_duplicate_file_submitted() -> None:
    inv = InvoiceRecord(
        invoice_number="INV-1001",
        vendor="Northwind Supplies",
        amount=1240.0,
        po_number="PO-501",
        attachment_name="INV-1004.pdf",
        decision=InvoiceDecision.FLAG_DUPLICATE,
        canonical_vendor="Northwind Supplies",
    )
    rows = [
        {
            "invoice_number": "INV-1001",
            "vendor": "Northwind Supplies",
            "amount": 1240.0,
            "status": "SUBMITTED",
            "attachment_name": "INV-1001.pdf",
        },
        {
            "invoice_number": "INV-1001",
            "vendor": "Northwind Supplies",
            "amount": 1240.0,
            "status": "SUBMITTED",
            "attachment_name": "INV-1004.pdf",
        },
    ]
    results = check_invoice_against_portal(inv, rows[1], all_rows_for_number=rows)
    assert results
    assert results[0].passed is False


def test_duplicate_passes_when_only_original_exists() -> None:
    inv = InvoiceRecord(
        invoice_number="INV-1001",
        vendor="Northwind Supplies",
        amount=1240.0,
        po_number="PO-501",
        attachment_name="INV-1004.pdf",
        decision=InvoiceDecision.FLAG_DUPLICATE,
        canonical_vendor="Northwind Supplies",
    )
    rows = [
        {
            "invoice_number": "INV-1001",
            "vendor": "Northwind Supplies",
            "amount": 1240.0,
            "status": "SUBMITTED",
            "attachment_name": "INV-1001.pdf",
        }
    ]
    results = check_invoice_against_portal(inv, rows[0], all_rows_for_number=rows)
    assert results[0].passed is True
