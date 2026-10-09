"""Operator UI optional HTTP Basic Auth (deploy gate)."""

from __future__ import annotations

import base64

import pytest
from ark_operator.config import clear_settings_cache
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_ui_ungated_without_basic_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Empty string overrides .env file values (delenv alone still loads env_file).
    monkeypatch.setenv("OPERATOR_UI_BASIC_AUTH_USER", "")
    monkeypatch.setenv("OPERATOR_UI_BASIC_AUTH_PASS", "")
    clear_settings_cache()
    from ark_operator.api.app import create_operator_app

    client = TestClient(create_operator_app())
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200


def test_ui_basic_auth_gates_pages_health_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPERATOR_UI_BASIC_AUTH_USER", "demo")
    monkeypatch.setenv("OPERATOR_UI_BASIC_AUTH_PASS", "s3cret")
    clear_settings_cache()
    from ark_operator.api.app import create_operator_app

    client = TestClient(create_operator_app())
    assert client.get("/health").status_code == 200
    denied = client.get("/")
    assert denied.status_code == 401
    assert "WWW-Authenticate" in denied.headers

    token = base64.b64encode(b"demo:s3cret").decode()
    ok = client.get("/", headers={"Authorization": f"Basic {token}"})
    assert ok.status_code == 200

    bad = client.get(
        "/", headers={"Authorization": "Basic " + base64.b64encode(b"demo:wrong").decode()}
    )
    assert bad.status_code == 401
