"""Verifier uses a fresh Playwright context — cannot share executor cookies."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from ark_operator.domain.enums import InvoiceDecision, InvoiceOutcome
from ark_operator.domain.models import InvoiceRecord
from ark_operator.tools.browser import BrowserTool
from ark_operator.verify.verifier import Verifier
from evals.runner import _free_port, _start_portal


def _run_isolation(tmp_path: Path, base: str) -> None:
    executor = BrowserTool(base_url=base, evidence_dir=tmp_path / "exec", headless=True)
    try:
        login = executor.run({"action": "login"})
        assert login.ok
        assert executor._context is not None  # noqa: SLF001
        exec_ctx_id = id(executor._context)

        verifier = Verifier(
            base,
            evidence_dir=tmp_path / "verify",
            email="operator@acmecorp.test",
            password="eval-pass",
        )
        try:
            inv = InvoiceRecord(
                invoice_number="INV-SABotAGE",
                vendor="Northwind Supplies",
                amount=10.0,
                po_number="PO-501",
                decision=InvoiceDecision.SUBMIT,
                outcome=InvoiceOutcome.COMPLETED,
                canonical_vendor="Northwind Supplies",
            )
            result = verifier.verify_invoices([inv])
            assert result.passed is False
            assert verifier.context_id is not None
            # Verifier context was a different object (destroyed after probe, but id recorded).
            assert "verify-" in verifier.context_id
            assert verifier.context_id != f"verify-{exec_ctx_id}"
            assert verifier.storage_state().get("cookies") is not None
        finally:
            verifier.close()
    finally:
        executor.close()


def test_verifier_context_isolated_from_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "eval-pass")
    port = _free_port()
    server = _start_portal(tmp_path / "portal.db", port)
    base = f"http://127.0.0.1:{port}"
    try:
        # Executor BrowserTool also uses sync Playwright — keep off the asyncio loop.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_run_isolation, tmp_path, base).result(timeout=120)
    finally:
        server.should_exit = True
