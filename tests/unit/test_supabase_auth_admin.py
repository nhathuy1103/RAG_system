from __future__ import annotations

from uuid import UUID

import httpx2 as httpx
import pytest

from app.identity.adapters.supabase_auth_admin import SupabaseAuthAdminProvisioner
from app.identity.ports.repositories import AuthUserAlreadyExistsError, AuthUserInput

USER_ID = UUID("10000000-0000-0000-0000-000000000001")


@pytest.mark.anyio
async def test_provisions_confirmed_employee_with_server_only_auth_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/v1/admin/users"
        assert request.headers["apikey"] == "service-role-key"
        assert request.headers["authorization"] == "Bearer service-role-key"
        assert request.content
        payload = request.read().decode()
        assert '"email":"employee@example.test"' in payload
        assert '"email_confirm":true' in payload
        assert '"full_name":"Employee One"' in payload
        return httpx.Response(200, json={"id": str(USER_ID)})

    async with httpx.AsyncClient(
        base_url="https://project.supabase.co/auth/v1",
        headers={
            "apikey": "service-role-key",
            "Authorization": "Bearer service-role-key",
        },
        transport=httpx.MockTransport(handler),
    ) as client:
        user_id = await SupabaseAuthAdminProvisioner(client).create_employee(
            AuthUserInput(
                email="employee@example.test",
                temporary_password="temporary-password",
                full_name="Employee One",
            )
        )

    assert user_id == USER_ID


@pytest.mark.anyio
async def test_maps_duplicate_auth_identity_to_conflict() -> None:
    async with httpx.AsyncClient(
        base_url="https://project.supabase.co/auth/v1",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(422, json={"msg": "User already registered"})
        ),
    ) as client:
        with pytest.raises(AuthUserAlreadyExistsError):
            await SupabaseAuthAdminProvisioner(client).create_employee(
                AuthUserInput(
                    email="employee@example.test",
                    temporary_password="temporary-password",
                )
            )
