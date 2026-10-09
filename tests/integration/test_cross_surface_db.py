"""A3: CLI and UI share OPERATOR_DB_PATH so approve/status work cross-surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from ark_operator.api.app import create_operator_app, get_store
from ark_operator.cli import _resolve_approval_id, _store
from ark_operator.config import clear_settings_cache, get_settings
from ark_operator.events.replay import fold_working_state
from ark_operator.events.types import EventType
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from evals.runner import _free_port, _start_portal
from fastapi.testclient import TestClient


def test_cli_and_ui_share_operator_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    db_path = tmp_path / "shared" / "operator.db"
    data_dir = tmp_path / "shared"
    monkeypatch.setenv("OPERATOR_DB_PATH", str(db_path))
    monkeypatch.setenv("OPERATOR_DATA_DIR", str(data_dir))
    clear_settings_cache()

    port = _free_port()
    server = _start_portal(tmp_path / "portal.db", port)
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("PORTAL_BASE_URL", base)
    clear_settings_cache()

    try:
        assert Path(get_settings().operator_db_path) == db_path
        ui_store = get_store()
        assert Path(ui_store.path) == db_path
        cli_store = _store()
        assert Path(cli_store.path) == db_path

        cfg = PipelineConfig(
            portal_base_url=base,
            data_dir=data_dir / "runs",
            auto_approve=None,
            invoice_filter=["INV-1003"],
        )
        # UI-started run (shared EventStore).
        result = InvoicePipeline(ui_store, build_default_fake_llm(), cfg).run("Process invoices")
        assert result.state.value == "AWAIT_APPROVAL"
        run_id = result.run_id

        # CLI status against the same DB — must not be empty INTAKE on a different file.
        working = fold_working_state(cli_store, run_id)
        assert working.state == "AWAIT_APPROVAL"
        assert working.pending_approvals

        approval_id = _resolve_approval_id(cli_store, run_id, "INV-1003")
        assert approval_id
        info = cli_store.decide_approval(approval_id, "approve", decided_by="cli")
        assert info
        cli_store.append(
            run_id,
            EventType.APPROVAL_DECIDED,
            {"approval_id": approval_id, "decision": "approve", "info": info},
        )

        # Resume on the shared store (same path UI would use).
        resumed = InvoicePipeline(get_store(), build_default_fake_llm(), cfg).resume(run_id)
        assert resumed.state.value == "COMPLETE"

        app = create_operator_app()
        client = TestClient(app)
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        assert b"Proof" in r.content or b"Verified" in r.content or b"INV-1003" in r.content
    finally:
        server.should_exit = True
        clear_settings_cache()
