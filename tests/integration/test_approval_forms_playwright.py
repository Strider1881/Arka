"""A4: plain form POST approve/reject works with and without JavaScript."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import uvicorn
from ark_operator.api.app import create_operator_app, get_store
from ark_operator.config import clear_settings_cache
from ark_operator.events.types import EventType
from ark_operator.runtime.pipeline import InvoicePipeline, PipelineConfig, build_default_fake_llm
from evals.runner import _free_port, _start_portal
from playwright.sync_api import sync_playwright


def _serve(app: object, host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.05)
    return server


@pytest.mark.parametrize("java_script_enabled", [False, True])
def test_approval_form_post_js_and_nojs(
    java_script_enabled: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    db_path = tmp_path / "operator.db"
    monkeypatch.setenv("OPERATOR_DB_PATH", str(db_path))
    monkeypatch.setenv("OPERATOR_DATA_DIR", str(tmp_path))
    clear_settings_cache()

    portal_port = _free_port()
    portal = _start_portal(tmp_path / "portal.db", portal_port)
    portal_base = f"http://127.0.0.1:{portal_port}"
    monkeypatch.setenv("PORTAL_BASE_URL", portal_base)
    clear_settings_cache()

    ui_port = _free_port()
    app = create_operator_app()
    ui = _serve(app, "127.0.0.1", ui_port)
    try:
        store = get_store()
        cfg = PipelineConfig(
            portal_base_url=portal_base,
            data_dir=tmp_path / "runs",
            auto_approve=None,
            invoice_filter=["INV-1003"],
        )
        result = InvoicePipeline(store, build_default_fake_llm(), cfg).run("Process invoices")
        assert result.state.value == "AWAIT_APPROVAL"
        run_id = result.run_id
        aid = result.pending_approval_ids[0]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(java_script_enabled=java_script_enabled)
            # Short viewport: approval card must still be actionable above the fold.
            page = context.new_page()
            page.set_viewport_size({"width": 1280, "height": 640})
            page.goto(f"http://127.0.0.1:{ui_port}/runs/{run_id}", wait_until="domcontentloaded")
            # With JS on, SSE may reload once on AWAIT_APPROVAL — wait for the form.
            form = page.locator('form[action*="/approvals/"]')
            form.first.wait_for(state="visible", timeout=15000)
            assert form.count() >= 1
            box = form.first.bounding_box()
            assert box is not None
            assert box["y"] + min(box["height"], 40) < 640  # actions visible in viewport
            with page.expect_navigation(timeout=15000):
                form.first.locator('button[value="approve"]').click()
            # Form POST must decide the approval (303 back to run).
            decided = [
                e for e in get_store().list_for_run(run_id) if e.type == EventType.APPROVAL_DECIDED
            ]
            assert decided
            assert aid  # seeded approval id from pipeline pause
            browser.close()
    finally:
        ui.should_exit = True
        portal.should_exit = True
        clear_settings_cache()
