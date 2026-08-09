"""End-to-end tests for the local authentication diagnostic."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.api.dependencies import auth
from app.api.dependencies.auth import get_current_user
from app.api.dependencies.repositories import get_notebook_repository
from app.api.main import create_app
from app.api.schemas.auth import CurrentUser
from app.bootstrap.settings import Settings
from app.notebooks.domain.models import Notebook

NOTEBOOK_ROW = Notebook(
    id=UUID("10000000-0000-0000-0000-000000000001"),
    owner_id=UUID("20000000-0000-0000-0000-000000000002"),
    title="Notebook",
    description="Mô tả notebook",
    created_at=datetime(2026, 7, 24, tzinfo=UTC),
    updated_at=datetime(2026, 7, 24, tzinfo=UTC),
)


class FakeNotebookRepository:
    async def list_owned(self) -> list[Notebook]:
        return [NOTEBOOK_ROW]

    async def create(self, title: str, description: str = "") -> Notebook:
        return Notebook(
            id=NOTEBOOK_ROW.id,
            owner_id=NOTEBOOK_ROW.owner_id,
            title=title,
            description=description,
            created_at=NOTEBOOK_ROW.created_at,
            updated_at=NOTEBOOK_ROW.updated_at,
        )

    async def update(
        self,
        notebook_id: UUID,
        changes: dict[str, str],
    ) -> Notebook | None:
        if notebook_id != NOTEBOOK_ROW.id:
            return None
        return Notebook(
            id=NOTEBOOK_ROW.id,
            owner_id=NOTEBOOK_ROW.owner_id,
            title=changes.get("title", NOTEBOOK_ROW.title),
            description=changes.get("description", NOTEBOOK_ROW.description),
            created_at=NOTEBOOK_ROW.created_at,
            updated_at=NOTEBOOK_ROW.updated_at,
        )


def make_settings(environment: str = "development") -> Settings:
    return Settings.model_validate(
        {
            "app_env": environment,
            "supabase_url": "https://example.supabase.co",
            "ingestion_worker_enabled": False,
        }
    )


def test_health_routes_are_available() -> None:
    with TestClient(create_app(make_settings())) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ok"}


def test_debug_route_requires_bearer_token() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/debug/supabase-user")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_debug_route_verifies_supabase_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FakeSigningKey:
        def __init__(self) -> None:
            self.key = private_key.public_key()

    class FakeJwkClient:
        def get_signing_key_from_jwt(self, _token: str) -> FakeSigningKey:
            return FakeSigningKey()

    def fake_get_jwk_client(_jwks_url: str) -> FakeJwkClient:
        return FakeJwkClient()

    monkeypatch.setattr(auth, "_get_jwk_client", fake_get_jwk_client)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "verified-user",
            "email": "verified@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "iss": "https://example.supabase.co/auth/v1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )

    with TestClient(create_app(make_settings())) as client:
        response = client.get(
            "/debug/supabase-user",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "verified-user",
        "email": "verified@example.com",
        "role": "authenticated",
    }


def test_debug_route_returns_verified_identity() -> None:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="user-123",
        email="user@example.com",
        role="authenticated",
    )

    with TestClient(app) as client:
        response = client.get(
            "/debug/supabase-user",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "user-123",
        "email": "user@example.com",
        "role": "authenticated",
    }


def test_debug_route_is_absent_in_production() -> None:
    with TestClient(create_app(make_settings("production"))) as client:
        response = client.get("/debug/supabase-user")

    assert response.status_code == 404


def test_notebook_routes_use_authenticated_repository() -> None:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(NOTEBOOK_ROW.owner_id),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_notebook_repository] = FakeNotebookRepository

    with TestClient(app) as client:
        list_response = client.get("/notebooks")
        create_response = client.post(
            "/notebooks",
            json={
                "title": "  Notebook mới  ",
                "description": "  Mô tả mới  ",
            },
        )

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == str(NOTEBOOK_ROW.id)
    assert list_response.json()[0]["description"] == "Mô tả notebook"
    assert create_response.status_code == 201
    assert create_response.json()["title"] == "Notebook mới"
    assert create_response.json()["description"] == "Mô tả mới"


def test_notebook_create_rejects_client_owner_id() -> None:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(NOTEBOOK_ROW.owner_id),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_notebook_repository] = FakeNotebookRepository

    with TestClient(app) as client:
        response = client.post(
            "/notebooks",
            json={
                "title": "Notebook",
                "owner_id": "30000000-0000-0000-0000-000000000003",
            },
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("payload", "expected_title", "expected_description"),
    [
        ({"title": "  Tên mới  "}, "Tên mới", NOTEBOOK_ROW.description),
        ({"description": "  Mô tả mới  "}, NOTEBOOK_ROW.title, "Mô tả mới"),
        ({"description": ""}, NOTEBOOK_ROW.title, ""),
    ],
)
def test_notebook_patch_accepts_either_field(
    payload: dict[str, str],
    expected_title: str,
    expected_description: str,
) -> None:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(NOTEBOOK_ROW.owner_id),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_notebook_repository] = FakeNotebookRepository

    with TestClient(app) as client:
        response = client.patch(f"/notebooks/{NOTEBOOK_ROW.id}", json=payload)

    assert response.status_code == 200
    assert response.json()["title"] == expected_title
    assert response.json()["description"] == expected_description


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None},
        {"description": None},
        {"title": "   "},
        {"unknown": "value"},
    ],
)
def test_notebook_patch_rejects_invalid_payload(payload: dict[str, object]) -> None:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(NOTEBOOK_ROW.owner_id),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_notebook_repository] = FakeNotebookRepository

    with TestClient(app) as client:
        response = client.patch(f"/notebooks/{NOTEBOOK_ROW.id}", json=payload)

    assert response.status_code == 422


def test_notebook_patch_returns_not_found() -> None:
    app = create_app(make_settings())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=str(NOTEBOOK_ROW.owner_id),
        email="user@example.com",
        role="authenticated",
    )
    app.dependency_overrides[get_notebook_repository] = FakeNotebookRepository
    missing_id = UUID("30000000-0000-0000-0000-000000000003")

    with TestClient(app) as client:
        response = client.patch(
            f"/notebooks/{missing_id}",
            json={"title": "Tên mới"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Notebook not found"}
