"""Each fault injection mode toggles and is verified (SPEC §2.2)."""

from __future__ import annotations

import re
import time
from typing import Any

import pytest
from company_world.portal.faults import fault_state
from fastapi.testclient import TestClient


def _enable(client: TestClient, faults: list[str], **extra: Any) -> None:
    payload = {"faults": faults, "reset_counters": True, **extra}
    r = client.post("/admin/faults", json=payload)
    assert r.status_code == 200
    assert set(r.json()["enabled"]) == set(faults)


def _vendor_po_ids(auth_client: TestClient, vendor: str, po_number: str) -> tuple[str, str]:
    vendors = {v["name"]: v["id"] for v in auth_client.get("/api/vendors").json()}
    form = auth_client.get("/invoices/submit").text
    po_match = re.search(rf'<option value="(\d+)">{re.escape(po_number)}\b', form)
    assert po_match, po_number
    return str(vendors[vendor]), po_match.group(1)


def test_admin_faults_require_auth(client: TestClient) -> None:
    assert client.get("/admin/faults").status_code == 401
    assert client.post("/admin/faults", json={"faults": []}).status_code == 401


def test_admin_faults_get_and_set(auth_client: TestClient) -> None:
    r = auth_client.get("/admin/faults")
    assert r.status_code == 200
    assert "valid_faults" in r.json()
    _enable(auth_client, ["latency", "ui_rename"])
    assert set(auth_client.get("/admin/faults").json()["enabled"]) == {"latency", "ui_rename"}
    _enable(auth_client, [])
    assert auth_client.get("/admin/faults").json()["enabled"] == []


def test_fault_latency(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(time, "sleep", fake_sleep)
    fault_state.rng_seed = 1
    _enable(auth_client, ["latency"], rng_seed=1)
    r = auth_client.get("/dashboard")
    assert r.status_code == 200
    assert slept, "latency fault should sleep"
    assert 1.0 <= slept[0] <= 4.0


def test_fault_flaky_500(auth_client: TestClient) -> None:
    _enable(auth_client, ["flaky_500"], flaky_force=True)
    vendor_id, po_id = _vendor_po_ids(auth_client, "Globex Industrial", "PO-502")
    data = {
        "vendor_id": vendor_id,
        "invoice_number": "INV-FLAKY",
        "po_id": po_id,
        "amount": "3980.00",
        "invoice_date": "2026-03-02",
        "attachment_name": "x.pdf",
    }
    first = auth_client.post("/invoices/submit", data=data, follow_redirects=False)
    assert first.status_code == 500
    assert "flaky_500" in first.json()["detail"]
    second = auth_client.post("/invoices/submit", data=data, follow_redirects=False)
    assert second.status_code == 303


def test_fault_session_expiry(auth_client: TestClient) -> None:
    _enable(auth_client, ["session_expiry"], session_expiry_n=3)
    # N=3 => first 3 authenticated requests OK; 4th expires
    for i in range(3):
        r = auth_client.get("/dashboard")
        assert r.status_code == 200, f"request {i + 1}"
    expired = auth_client.get("/dashboard", follow_redirects=False)
    assert expired.status_code in (303, 302)
    assert "/login" in expired.headers.get("location", "")


def test_fault_ui_rename(auth_client: TestClient) -> None:
    before = auth_client.get("/invoices/submit")
    assert 'id="submit-invoice-button"' in before.text
    assert ">Submit invoice<" in before.text

    _enable(auth_client, ["ui_rename"])
    after = auth_client.get("/invoices/submit")
    assert 'id="submit-invoice-button"' in after.text
    assert 'id="vendor_id"' in after.text
    assert 'id="invoice_number"' in after.text
    assert 'id="submit-invoice-button">Transmit document</button>' in after.text
    assert "Supplier" in after.text
    assert 'id="submit-invoice-button">Submit invoice</button>' not in after.text


def test_fault_duplicate_submit_guard(auth_client: TestClient) -> None:
    _enable(auth_client, ["duplicate_submit_guard"])
    vendor_id, po_id = _vendor_po_ids(auth_client, "Umbrella Corp", "PO-508")
    data = {
        "vendor_id": vendor_id,
        "invoice_number": "INV-DUPGUARD",
        "po_id": po_id,
        "amount": "4999.00",
        "invoice_date": "2026-03-08",
        "attachment_name": "d.pdf",
    }
    first = auth_client.post("/invoices/submit", data=data, follow_redirects=False)
    assert first.status_code == 303
    second = auth_client.post("/invoices/submit", data=data, follow_redirects=True)
    assert second.status_code == 200
    assert "Duplicate submit blocked" in second.text
    assert 'id="submit-banner"' in second.text


def test_faults_env_parsed_on_app_create(portal_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAULTS", "ui_rename,latency")
    from company_world.portal.app import create_app

    app = create_app(reset_db=True)
    client = TestClient(app)
    client.post(
        "/login",
        data={"email": "operator@acmecorp.test", "password": "test-operator"},
        follow_redirects=False,
    )
    enabled = set(client.get("/admin/faults").json()["enabled"])
    assert enabled == {"ui_rename", "latency"}
