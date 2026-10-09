"""Crash-window heal: portal truth must commit the irreversible ledger without re-POST."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from ark_operator.domain.enums import InvoiceDecision
from ark_operator.domain.models import InvoiceRecord
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.idempotency import IrreversibleLedger, irreversible_key
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig
from ark_operator.tools.base import ToolResult


def test_browser_submit_reconciles_from_portal_without_rewrite(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    run_id = store.new_run_id()
    store.append(run_id, EventType.RUN_STARTED, {"goal": "x"})
    cfg = PipelineConfig(data_dir=tmp_path / "data", use_browser_loop=True)
    pipe = InvoicePipeline(store, MagicMock(), cfg)
    inv = InvoiceRecord(
        invoice_number="INV-RECON-1",
        vendor="Northwind Supplies",
        canonical_vendor="Northwind Supplies",
        amount=100.0,
        po_number="PO-501",
        attachment_name="INV-RECON-1.pdf",
        decision=InvoiceDecision.SUBMIT,
    )
    key = irreversible_key(run_id, inv.invoice_number, "submit")
    ledger = IrreversibleLedger(store, run_id)
    assert not ledger.is_committed(key)

    pipe._portal_api = MagicMock()
    pipe._portal_api.run.return_value = ToolResult(
        ok=True,
        data={
            "result": {
                "invoice_number": "INV-RECON-1",
                "vendor": "Northwind Supplies",
                "attachment_name": "INV-RECON-1.pdf",
                "status": "SUBMITTED",
                "amount": 100.0,
            }
        },
    )
    # If reconcile fails open, browser would be invoked — ensure it is not.
    pipe.registry = MagicMock()
    pipe.registry.get.side_effect = AssertionError("must not call tools after portal reconcile")

    outcome = pipe._browser_submit(run_id, inv, ledger)
    assert outcome.value == "needs_attention"
    assert ledger.is_committed(key)
    cached: dict[str, Any] = store.get_idempotent(key) or {}
    assert cached.get("reconciled_from_portal") is True
    assert any(
        e.type == EventType.IDEMPOTENCY_SKIP and e.payload.get("reconciled_from_portal")
        for e in store.list_for_run(run_id)
    )
