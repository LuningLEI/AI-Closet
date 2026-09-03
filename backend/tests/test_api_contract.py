from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_mutation_requires_login_when_strict_auth_is_enabled() -> None:
    response = TestClient(app).patch("/api/v1/preferences", json={"nickname": "New name"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Login required for write operations."


def test_signed_url_contract_is_exposed() -> None:
    response = TestClient(app).get("/api/v1/storage/signed-url-contract")

    assert response.status_code == 200
    assert response.json()["expires_in_seconds"] > 0
    assert "fresh signed image url" in response.json()["refresh_strategy"].lower()
