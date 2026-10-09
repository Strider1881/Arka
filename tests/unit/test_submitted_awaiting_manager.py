"""A1: INV-1003 report outcome SUBMITTED_AWAITING_MANAGER + coherent verified."""

from __future__ import annotations

from pathlib import Path

from ark_operator.domain.enums import (
    Confidence,
    InvoiceDecision,
    InvoiceOutcome,
    outcome_label,
)
from ark_operator.domain.models import InvoiceRecord, VerificationResult
from ark_operator.events.store import EventStore
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm


def test_outcome_label_for_manager_queue() -> None:
    assert (
        outcome_label(InvoiceOutcome.SUBMITTED_AWAITING_MANAGER)
        == "Submitted, awaiting manager approval"
    )


def test_build_report_marks_awaiting_manager_verified_when_global_pass(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    pipe = InvoicePipeline(
        store, build_default_fake_llm(), PipelineConfig(data_dir=tmp_path / "data")
    )
    inv = InvoiceRecord(
        invoice_number="INV-1003",
        vendor="Initech Systems",
        amount=12400.0,
        po_number="PO-503",
        attachment_name="INV-1003.pdf",
        decision=InvoiceDecision.NEEDS_APPROVAL,
        decision_reason="Above threshold",
        outcome=InvoiceOutcome.SUBMITTED_AWAITING_MANAGER,
    )
    report = pipe._build_report(
        "run-a1",
        [inv],
        VerificationResult(passed=True, confidence=Confidence.HIGH, overall_notes="ok"),
    )
    line = report.invoices[0]
    assert line.outcome == InvoiceOutcome.SUBMITTED_AWAITING_MANAGER
    assert line.verified is True
    assert "INV-1003" not in report.needs_attention


def test_build_report_sabotage_unverified_when_global_fail(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    pipe = InvoicePipeline(
        store, build_default_fake_llm(), PipelineConfig(data_dir=tmp_path / "data")
    )
    inv = InvoiceRecord(
        invoice_number="INV-1003",
        vendor="Initech Systems",
        amount=12400.0,
        po_number="PO-503",
        attachment_name="INV-1003.pdf",
        decision=InvoiceDecision.NEEDS_APPROVAL,
        decision_reason="Above threshold",
        outcome=InvoiceOutcome.SUBMITTED_AWAITING_MANAGER,
    )
    report = pipe._build_report(
        "run-a1-sab",
        [inv],
        VerificationResult(passed=False, confidence=Confidence.LOW, overall_notes="sabotage"),
    )
    # Global fail remaps success-class claims; awaiting-manager must not claim verified.
    line = report.invoices[0]
    assert line.outcome == InvoiceOutcome.NEEDS_ATTENTION
    assert line.verified is False
    assert "INV-1003" in report.needs_attention
