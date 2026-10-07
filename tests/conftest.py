"""Shared fixtures for company_world portal tests."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
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


@pytest.fixture
def live_portal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Start a real uvicorn portal on an ephemeral port for Playwright tests."""
    db = tmp_path / "live_portal.db"
    monkeypatch.setenv("PORTAL_DB_PATH", str(db))
    monkeypatch.setenv("PORTAL_OPERATOR_PASSWORD", "test-operator")
    monkeypatch.setenv("PORTAL_MANAGER_PASSWORD", "test-manager")
    monkeypatch.setenv("PORTAL_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("FAULTS", "")
    fault_state.enabled = set()
    fault_state.flaky_test_force = False
    fault_state.session_request_counts.clear()
    fault_state.flaky_fired.clear()
    fault_state.submitted_fingerprints.clear()

    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()

    app = create_app(reset_db=True)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            r = httpx.get(f"{base}/health", timeout=0.5)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("Portal failed to start")
    yield base
    server.should_exit = True
    thread.join(timeout=5)
