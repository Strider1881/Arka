"""Proof table must label work units by process identity (file stem), not document number."""

from __future__ import annotations

from pathlib import Path

from ark_operator.domain.enums import Confidence, InvoiceDecision, InvoiceOutcome
from ark_operator.domain.models import InvoiceRecord, VerificationResult
from ark_operator.events.store import EventStore
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm


def test_proof_rows_use_attachment_stem_for_duplicate_document_number(tmp_path: Path) -> None:
    """INV-1004.pdf extracts as INV-1001; proof must still show INV-1004 as its own row id."""
    store = EventStore(tmp_path / "events.db")
    pipe = InvoicePipeline(
        store, build_default_fake_llm(), PipelineConfig(data_dir=tmp_path / "data")
    )

    original = InvoiceRecord(
        invoice_number="INV-1001",
        vendor="Northwind Supplies",
        amount=1240.0,
        po_number="PO-501",
        attachment_name="INV-1001.pdf",
        decision=InvoiceDecision.SUBMIT,
        decision_reason="Matches PO",
        outcome=InvoiceOutcome.COMPLETED,
    )
    duplicate = InvoiceRecord(
        invoice_number="INV-1001",  # extracted document number (same as original)
        vendor="Northwind Supplies",
        amount=1240.0,
        po_number="PO-501",
        attachment_name="INV-1004.pdf",
        decision=InvoiceDecision.FLAG_DUPLICATE,
        decision_reason="Duplicate of an already-seen invoice number",
        outcome=InvoiceOutcome.FLAGGED,
    )

    report = pipe._build_report(
        "run-proof-id",
        [original, duplicate],
        VerificationResult(passed=True, confidence=Confidence.HIGH, overall_notes="ok"),
    )

    ids = [line.invoice_number for line in report.invoices]
    assert ids == ["INV-1001", "INV-1004"]
    assert duplicate.process_identity() == "INV-1004"
    assert original.process_identity() == "INV-1001"
    # Flagged duplicate must appear under its process id, not the shared document number.
    assert report.needs_attention == ["INV-1004"]
