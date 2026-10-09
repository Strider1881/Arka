"""A1 golden: after operator approve + portal PENDING_APPROVAL, report is coherent."""

from __future__ import annotations

from pathlib import Path

import pytest
from ark_operator.domain.enums import InvoiceOutcome
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from evals.runner import _free_port, _start_portal


def test_inv1003_submitted_awaiting_manager_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    port = _free_port()
    server = _start_portal(tmp_path / "portal.db", port)
    base = f"http://127.0.0.1:{port}"
    try:
        store = EventStore(tmp_path / "events.db")
        cfg = PipelineConfig(
            portal_base_url=base,
            data_dir=tmp_path / "run",
            auto_approve=None,
            invoice_filter=["INV-1003"],
        )
        result = InvoicePipeline(store, build_default_fake_llm(), cfg).run("Process invoices")
        assert result.state.value == "AWAIT_APPROVAL"
        aid = result.pending_approval_ids[0]
        info = store.decide_approval(aid, "approve", decided_by="test")
        store.append(
            result.run_id,
            EventType.APPROVAL_DECIDED,
            {"approval_id": aid, "decision": "approve", "info": info},
        )
        resumed = InvoicePipeline(store, build_default_fake_llm(), cfg).resume(result.run_id)
        assert resumed.state.value == "COMPLETE"
        assert resumed.verification and resumed.verification.passed
        assert resumed.report is not None
        line = next(i for i in resumed.report.invoices if i.invoice_number == "INV-1003")
        assert line.outcome == InvoiceOutcome.SUBMITTED_AWAITING_MANAGER
        assert line.verified is True
        inv = next(i for i in resumed.invoices if i.invoice_number == "INV-1003")
        assert inv.outcome == InvoiceOutcome.SUBMITTED_AWAITING_MANAGER
    finally:
        server.should_exit = True
