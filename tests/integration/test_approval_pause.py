"""P6: irreversible portal write must not happen before human clearance."""

from __future__ import annotations

from pathlib import Path

import pytest
from ark_operator.events.store import EventStore
from ark_operator.events.types import EventType
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from ark_operator.tools.portal_api import PortalApiTool
from evals.runner import _free_port, _start_portal


def test_no_submit_before_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert result.pending_approval_ids

        # No irreversible write yet
        api = PortalApiTool(base, email="operator@acmecorp.test", password="eval-pass")
        try:
            rows = api.run({"action": "invoices"}).data.get("result") or []
        finally:
            api.close()
        assert not any(r.get("invoice_number") == "INV-1003" for r in rows)

        # Approve and resume
        aid = result.pending_approval_ids[0]
        info = store.decide_approval(aid, "approve", decided_by="test")
        store.append(
            result.run_id,
            EventType.APPROVAL_DECIDED,
            {"approval_id": aid, "decision": "approve", "info": info},
        )
        resumed = InvoicePipeline(store, build_default_fake_llm(), cfg).resume(result.run_id)
        assert resumed.state.value == "COMPLETE"
        api2 = PortalApiTool(base, email="operator@acmecorp.test", password="eval-pass")
        try:
            rows2 = api2.run({"action": "invoices"}).data.get("result") or []
        finally:
            api2.close()
        assert any(
            r.get("invoice_number") == "INV-1003" and r.get("status") == "PENDING_APPROVAL"
            for r in rows2
        )
    finally:
        server.should_exit = True
