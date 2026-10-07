"""API health endpoint smoke test."""

from ark_operator.api.app import app
from fastapi.testclient import TestClient


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["status"] == "ok"
    assert body["phase"] in {"P0", "P9"}
