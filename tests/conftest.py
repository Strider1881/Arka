"""Shared fixtures for company_world portal tests."""

from __future__ import annotations

import pytest
from company_world.portal.app import create_app
from company_world.portal.faults import fault_state
from fastapi.testclient import TestClient


@pytest.fixture
def portal_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.db"))
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    monkeypatch.setenv("PORTAL_MANAGER_PASSWORD", "test-manager")
    monkeypatch.setenv("PORTAL_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("FAULTS", "")
    monkeypatch.delenv("SESSION_EXPIRY_N", raising=False)
    fault_state.enabled = set()
    fault_state.session_expiry_n = 5
    fault_state.session_request_counts.clear()
    fault_state.flaky_fired.clear()
    fault_state.submitted_fingerprints.clear()
    fault_state.flaky_test_force = False
    fault_state.rng_seed = None


@pytest.fixture
def client(portal_env: None) -> TestClient:
    app = create_app(reset_db=True)
    return TestClient(app)


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    response = client.post(
        "/login",
        data={"email": "operator@acmecorp.test", "password": "test-operator"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


@pytest.fixture
def manager_client(client: TestClient) -> TestClient:
    response = client.post(
        "/login",
        data={"email": "priya.nair@acmecorp.test", "password": "test-manager"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client
