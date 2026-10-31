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


def test_image_refresh_item_endpoint_is_scoped_to_authenticated_user(monkeypatch, repository):
    from app.api import dependencies as routes
    from app.api.routes import items as item_routes
    from app.models.domain import ClothingItemRecord
    item = ClothingItemRecord(id="owned", user_id="owner", image_url="https://example.test/old",
                              category="Tops", color="Blue", season="Summer", style="Casual", occasion="Everyday")
    repository.add_item(item)
    monkeypatch.setattr(routes, "repository", repository)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "owner")
    monkeypatch.setattr(item_routes, "signed_item", lambda item, request: item.model_copy(update={"image_url": "https://example.test/fresh"}))
    client = TestClient(app)
    response = client.get("/api/v1/items/owned")
    assert response.status_code == 200
    assert response.json()["image_url"] == "https://example.test/fresh"
    assert client.get("/api/v1/items/missing").status_code == 404
    monkeypatch.setattr(routes, "current_user_id", lambda request: "another-user")
    assert client.get("/api/v1/items/owned").status_code == 404
