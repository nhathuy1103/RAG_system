from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies.enterprise import (
    get_auth_user_provisioner,
    get_identity_service,
    require_manage_user,
)
from app.api.enterprise_errors import install_enterprise_error_contract
from app.api.routers import enterprise_identity
from app.identity.domain.models import PrincipalContext, UserProfile
from app.identity.ports.repositories import AuthUserInput, ProfileInput

ADMIN_ID = UUID("10000000-0000-0000-0000-000000000001")
EMPLOYEE_ID = UUID("20000000-0000-0000-0000-000000000002")


class ProvisionerStub:
    def __init__(self) -> None:
        self.created: AuthUserInput | None = None

    async def create_employee(self, value: AuthUserInput) -> UUID:
        self.created = value
        return EMPLOYEE_ID


class IdentityServiceStub:
    def __init__(self) -> None:
        self.profile: ProfileInput | None = None

    async def create_profile(self, value: ProfileInput) -> UserProfile:
        self.profile = value
        now = datetime(2026, 8, 9, tzinfo=UTC)
        return UserProfile(
            user_id=value.user_id,
            company_user_id=value.company_user_id,
            full_name=value.full_name,
            status=value.status,
            created_at=now,
            updated_at=now,
        )


def make_app(provisioner: ProvisionerStub, service: IdentityServiceStub) -> FastAPI:
    app = FastAPI()
    install_enterprise_error_contract(app)
    app.include_router(enterprise_identity.router)
    app.dependency_overrides[get_auth_user_provisioner] = lambda: provisioner
    app.dependency_overrides[get_identity_service] = lambda: service
    app.dependency_overrides[require_manage_user] = lambda: PrincipalContext(
        user_id=ADMIN_ID,
        email="admin@example.test",
        status="ACTIVE",
        permissions=frozenset({"MANAGE_USER"}),
    )
    return app


@pytest.mark.anyio
async def test_admin_provisions_active_employee_profile() -> None:
    provisioner = ProvisionerStub()
    service = IdentityServiceStub()
    transport = httpx.ASGITransport(app=make_app(provisioner, service))

    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.post(
            "/api/v1/users/provision",
            json={
                "email": " Employee@Example.Test ",
                "temporary_password": "temporary-password",
                "company_user_id": "EMP-001",
                "full_name": "Employee One",
            },
        )

    assert response.status_code == 201
    assert response.json()["user_id"] == str(EMPLOYEE_ID)
    assert response.json()["email"] == "employee@example.test"
    assert response.json()["status"] == "ACTIVE"
    assert provisioner.created == AuthUserInput(
        email="employee@example.test",
        temporary_password="temporary-password",
        full_name="Employee One",
    )
    assert service.profile == ProfileInput(
        user_id=EMPLOYEE_ID,
        company_user_id="EMP-001",
        full_name="Employee One",
        status="ACTIVE",
    )


@pytest.mark.anyio
async def test_rejects_short_temporary_password_before_provisioning() -> None:
    provisioner = ProvisionerStub()
    service = IdentityServiceStub()
    transport = httpx.ASGITransport(app=make_app(provisioner, service))

    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.post(
            "/api/v1/users/provision",
            json={"email": "employee@example.test", "temporary_password": "short"},
        )

    assert response.status_code == 422
    assert provisioner.created is None
    assert service.profile is None
