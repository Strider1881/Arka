"""Unit tests for FakeLLM browser_step script (no Playwright)."""

from __future__ import annotations

import json

from ark_operator.runtime.browser_loop import scripted_browser_step


def test_script_login_on_login_page() -> None:
    login_obs = (
        "title: Login\nurl: http://x/login\n"
        "[e0] input/email \"email\" id=email value=''\n"
        '[e1] button "Sign in" id=login-submit'
    )
    choice = scripted_browser_step(
        {
            "observation": login_obs,
            "fields": "{}",
            "history": "[]",
            "hints": "- prefer stable ids",
        }
    )
    assert choice["action"] == "login"


def test_script_fills_then_submits() -> None:
    obs = (
        "title: Submit\nurl: http://x/invoices/submit\n"
        '[e0] select "vendor" id=vendor_id options=[1:Northwind Supplies]\n'
        "[e1] input/text \"inv\" id=invoice_number value=''\n"
        '[e2] select "po" id=po_id options=[10:PO-501]\n'
        "[e3] input/text \"amt\" id=amount value=''\n"
        "[e4] input/text \"date\" id=invoice_date value=''\n"
        "[e5] input/text \"att\" id=attachment_name value=''\n"
        '[e6] button "Submit invoice" id=submit-invoice-button\n'
    )
    fields = json.dumps(
        {
            "vendor": "Northwind Supplies",
            "invoice_number": "INV-1001",
            "po_number": "PO-501",
            "amount": 1240.0,
            "invoice_date": "2026-03-01",
            "attachment_name": "INV-1001.pdf",
        }
    )
    history: list[dict[str, object]] = []
    # Simulate observation updating after each successful set (ids stable in this fixture).
    for _ in range(12):
        choice = scripted_browser_step(
            {
                "observation": obs,
                "fields": fields,
                "history": json.dumps(history),
                "hints": "- Prefer stable element ids",
            }
        )
        history.append(choice)
        if choice["action"] == "click":
            break
    assert history[0]["action"] == "select"
    assert history[0]["rationale"] == "set vendor_id"
    assert history[-1]["action"] == "click"
    assert history[-1]["ref"] == "e6"
    assert "submit-invoice-button" in str(history[-1]["rationale"])


def test_script_done_on_detail() -> None:
    choice = scripted_browser_step(
        {
            "observation": "title: Invoice\nurl: http://x/invoices/42\nbanners: ok",
            "fields": "{}",
            "history": "[]",
            "hints": "",
        }
    )
    assert choice["action"] == "done"
