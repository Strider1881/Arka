"""Resume must re-seed duplicate keys so INV-1004 still flags after crash."""

from __future__ import annotations

from pathlib import Path

import pytest
from ark_operator.domain.enums import InvoiceDecision
from ark_operator.events.store import EventStore
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from evals.runner import _free_port, _start_portal


def test_resume_keeps_duplicate_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    port = _free_port()
    server = _start_portal(tmp_path / "portal.db", port)
    base = f"http://127.0.0.1:{port}"
    try:
        store = EventStore(tmp_path / "events.db")
        cfg = PipelineConfig(
            portal_base_url=base,
            data_dir=tmp_path / "run",
            auto_approve=True,
            invoice_filter=["INV-1001", "INV-1004"],
            crash_after_invoices=1,
        )
        pipe = InvoicePipeline(store, build_default_fake_llm(), cfg)
        partial = pipe.run("Process invoices")
        assert partial.state.value == "EXECUTE"
        # Simulate process restart: new pipeline, same event store
        cfg2 = PipelineConfig(
            portal_base_url=base,
            data_dir=tmp_path / "run",
            auto_approve=True,
            invoice_filter=["INV-1001", "INV-1004"],
        )
        resumed = InvoicePipeline(store, build_default_fake_llm(), cfg2).resume(partial.run_id)
        assert resumed.state.value == "COMPLETE"
        by_stem = {Path(i.attachment_name or "").stem: i.decision for i in resumed.invoices}
        assert by_stem["INV-1001"] == InvoiceDecision.SUBMIT
        assert by_stem["INV-1004"] == InvoiceDecision.FLAG_DUPLICATE
    finally:
        server.should_exit = True
