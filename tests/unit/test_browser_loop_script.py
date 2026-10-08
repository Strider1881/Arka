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
    # Fixture obs does not update values; script uses history-since-nav to advance.
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


def test_script_refills_after_form_wipe() -> None:
    """After TRANSIENT reopen, observation shows empty fields — refill despite history."""
    empty_obs = (
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
    # Prior fills + failed click + recovery goto (as browser_loop records).
    history = [
        {"action": "goto", "url": "/invoices/submit", "rationale": "open submit form"},
        {
            "action": "select",
            "ref": "e0",
            "value": "Northwind Supplies",
            "rationale": "set vendor_id",
        },
        {
            "action": "fill",
            "ref": "e1",
            "text": "INV-1001",
            "rationale": "set invoice_number",
        },
        {"action": "select", "ref": "e2", "value": "PO-501", "rationale": "set po_id"},
        {"action": "fill", "ref": "e3", "text": "1240.00", "rationale": "set amount"},
        {
            "action": "fill",
            "ref": "e4",
            "text": "2026-03-01",
            "rationale": "set invoice_date",
        },
        {
            "action": "fill",
            "ref": "e5",
            "text": "INV-1001.pdf",
            "rationale": "set attachment_name",
        },
        {
            "action": "click",
            "ref": "e6",
            "rationale": "stable id submit-invoice-button",
            "error": "flaky_500",
        },
        {
            "action": "goto",
            "url": "/invoices/submit",
            "rationale": "reopen submit form after TRANSIENT",
            "recovered": "TRANSIENT",
        },
    ]
    choice = scripted_browser_step(
        {
            "observation": empty_obs,
            "fields": fields,
            "history": json.dumps(history),
            "hints": "- Prefer stable element ids",
        }
    )
    assert choice["action"] in {"select", "fill"}
    assert "set " in str(choice.get("rationale") or "")


def test_script_done_on_detail() -> None:
    choice = scripted_browser_step(
        {
            "observation": (
                "title: Invoice INV-1001\nurl: http://x/invoices/42\n"
                "banners: Invoice INV-1001 recorded as SUBMITTED."
            ),
            "fields": json.dumps({"invoice_number": "INV-1001"}),
            "history": "[]",
            "hints": "",
        }
    )
    assert choice["action"] == "done"


def test_script_not_done_on_other_invoice_detail() -> None:
    choice = scripted_browser_step(
        {
            "observation": (
                "title: Invoice INV-1001\nurl: http://x/invoices/1\n"
                "banners: Invoice INV-1001 recorded as SUBMITTED."
            ),
            "fields": json.dumps({"invoice_number": "INV-1002"}),
            "history": "[]",
            "hints": "",
        }
    )
    assert choice["action"] != "done"
