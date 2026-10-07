"""P3 AC: browser tool drives real portal; secrets never in logs/events."""

from __future__ import annotations

from pathlib import Path

from ark_operator.tools.browser import BrowserTool
from ark_operator.tools.secrets import portal_operator_credentials


def test_browser_login_and_refs(live_portal: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    tool = BrowserTool(base_url=live_portal, evidence_dir=tmp_path / "ev", headless=True)
    try:
        login = tool.run({"action": "login"})
        assert login.ok, login.failure
        obs = tool.run({"action": "observe"})
        assert obs.ok
        elements = obs.data.get("elements") or []
        assert any("[e" in line for line in elements)
        # Navigate to submit form and ensure stable ids present in a11y summary
        tool.run({"action": "goto", "url": "/invoices/submit"})
        obs2 = tool.run({"action": "observe"})
        blob = "\n".join(obs2.data.get("elements") or [])
        assert "submit-invoice-button" in blob or "vendor_id" in blob
        password = portal_operator_credentials().password
        assert password not in str(obs.data)
        assert password not in str(obs2.data)
        assert password not in str(login.data)
    finally:
        tool.close()


def test_browser_submit_invoice(live_portal: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    tool = BrowserTool(base_url=live_portal, evidence_dir=tmp_path / "ev", headless=True)
    try:
        res = tool.run(
            {
                "action": "submit_invoice",
                "vendor": "Northwind Supplies",
                "invoice_number": "INV-BROWSER-1",
                "po_number": "PO-501",
                "amount": 1240.0,
                "invoice_date": "2026-03-01",
                "attachment_name": "INV-BROWSER-1.pdf",
            }
        )
        assert res.ok, res.failure
        assert "SUBMITTED" in (res.data.get("url") or "") or "/invoices/" in (
            res.data.get("url") or ""
        )
    finally:
        tool.close()
