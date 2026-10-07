"""Portal seed data and human-usable page smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "acmecorp-procure"


def test_login_and_dashboard(auth_client: TestClient) -> None:
    r = auth_client.get("/dashboard")
    assert r.status_code == 200
    assert "Dashboard" in r.text
    assert "AcmeCorp" in r.text


def test_seed_vendors_and_pos(auth_client: TestClient) -> None:
    vendors = auth_client.get("/api/vendors").json()
    assert len(vendors) == 8
    by_name = {v["name"]: v for v in vendors}
    assert by_name["Pied Piper Cloud"]["status"] == "BLOCKED"
    assert "Northwind Supply Co" in by_name["Northwind Supplies"]["aliases"]

    pos = auth_client.get("/api/pos").json()
    assert len(pos) == 12
    numbers = {p["po_number"] for p in pos}
    assert numbers == {f"PO-{n}" for n in range(501, 513)}


def test_pages_render(auth_client: TestClient) -> None:
    for path in ("/vendors", "/pos", "/pos/PO-501", "/invoices", "/invoices/submit", "/approvals"):
        r = auth_client.get(path)
        assert r.status_code == 200, path


def test_submit_under_threshold(auth_client: TestClient) -> None:
    import re

    vendors = {v["name"]: v["id"] for v in auth_client.get("/api/vendors").json()}
    form = auth_client.get("/invoices/submit")
    assert 'id="submit-invoice-button"' in form.text
    assert "Submit invoice" in form.text

    po_match = re.search(r'<option value="(\d+)">PO-501\b', form.text)
    assert po_match
    po_id = po_match.group(1)
    r = auth_client.post(
        "/invoices/submit",
        data={
            "vendor_id": str(vendors["Northwind Supplies"]),
            "invoice_number": "INV-TEST-1",
            "po_id": po_id,
            "amount": "1240.00",
            "invoice_date": "2026-03-01",
            "attachment_name": "INV-TEST-1.pdf",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = auth_client.get(r.headers["location"])
    assert "SUBMITTED" in detail.text


def test_submit_over_threshold_queues_approval(auth_client: TestClient) -> None:
    vendors = {v["name"]: v["id"] for v in auth_client.get("/api/vendors").json()}
    form = auth_client.get("/invoices/submit").text
    import re

    po_match = re.search(r'<option value="(\d+)">PO-503\b', form)
    assert po_match
    r = auth_client.post(
        "/invoices/submit",
        data={
            "vendor_id": str(vendors["Initech Systems"]),
            "invoice_number": "INV-BIG",
            "po_id": po_match.group(1),
            "amount": "12400.00",
            "invoice_date": "2026-03-03",
            "attachment_name": "INV-BIG.pdf",
        },
        follow_redirects=True,
    )
    assert "PENDING_APPROVAL" in r.text
    approvals = auth_client.get("/approvals")
    assert "INV-BIG" in approvals.text


def test_expected_outcomes_file_complete() -> None:
    data = json.loads((ROOT / "company_world" / "expected_outcomes.json").read_text())
    assert len(data["invoices"]) == 12
    numbers = {i["invoice_number"] for i in data["invoices"]}
    assert numbers == {f"INV-{n}" for n in range(1001, 1013)}


def test_knowledge_files_exist() -> None:
    knowledge = ROOT / "company_world" / "knowledge"
    expected = {
        "invoice_processing_sop.md",
        "approval_policy.md",
        "tolerance_policy.md",
        "vendor_policy.md",
        "duplicates_policy.md",
        "escalation.md",
        "security_policy.md",
    }
    assert expected <= {p.name for p in knowledge.glob("*.md")}
