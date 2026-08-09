from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.enterprise import get_identity_service
from app.api.routers import enterprise_identity
from app.api.schemas.auth import CurrentUser
from app.identity.application.services import IdentityService
from app.identity.domain.models import (
    Department,
    FunctionalPermission,
    Group,
    PrincipalContext,
    Role,
    UserDepartmentMembership,
    UserGroupMembership,
    UserRoleMembership,
)

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
ROLE_ID = UUID("20000000-0000-0000-0000-000000000002")
PERMISSION_ID = UUID("30000000-0000-0000-0000-000000000003")
GROUP_ID = UUID("40000000-0000-0000-0000-000000000004")
DEPARTMENT_ID = UUID("50000000-0000-0000-0000-000000000005")
MEMBERSHIP_ID = UUID("60000000-0000-0000-0000-000000000006")
NOW = datetime(2026, 8, 9, tzinfo=UTC)


class IdentityProjectionStub:
    def __init__(self, *permissions: str) -> None:
        self.permissions = frozenset(permissions)
        self.include_inactive: bool | None = None

    async def current_principal(
        self, user_id: UUID, *, email: str | None = None
    ) -> PrincipalContext:
        return PrincipalContext(
            user_id=user_id,
            email=email,
            status="ACTIVE",
            permissions=self.permissions,
        )

    async def list_role_permissions(self, role_id: UUID) -> list[FunctionalPermission]:
        assert role_id == ROLE_ID
        return [
            FunctionalPermission(
                id=PERMISSION_ID,
                code="MANAGE_USER",
                name="Manage users",
                description=None,
                created_at=NOW,
            )
        ]

    async def list_user_roles(self, user_id: UUID) -> list[UserRoleMembership]:
        assert user_id == USER_ID
        role = Role(ROLE_ID, "ADMIN", "Administrator", None, "ACTIVE")
        return [
            UserRoleMembership(
                id=MEMBERSHIP_ID,
                user_id=user_id,
                role_id=ROLE_ID,
                role=role,
                assigned_at=NOW,
            )
        ]

    async def list_user_groups(self, user_id: UUID) -> list[UserGroupMembership]:
        assert user_id == USER_ID
        group = Group(GROUP_ID, "HR", "Human Resources", None, "ACTIVE")
        return [
            UserGroupMembership(
                id=MEMBERSHIP_ID,
                user_id=user_id,
                group_id=GROUP_ID,
                group=group,
                joined_at=NOW,
            )
        ]

    async def list_user_departments(
        self, user_id: UUID, *, include_inactive: bool = False
    ) -> list[UserDepartmentMembership]:
        assert user_id == USER_ID
        self.include_inactive = include_inactive
        department = Department(
            DEPARTMENT_ID,
            "ENGINEERING",
            "Engineering",
            None,
            "ACTIVE",
        )
        return [
            UserDepartmentMembership(
                id=MEMBERSHIP_ID,
                user_id=user_id,
                department_id=DEPARTMENT_ID,
                department=department,
                is_primary=True,
                start_at=NOW,
            )
        ]


def _app(service: IdentityProjectionStub) -> FastAPI:
    app = FastAPI()
    app.include_router(enterprise_identity.router)

    async def current_user() -> CurrentUser:
        return CurrentUser(id=str(USER_ID), email="admin@example.test", user_role="user")

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_identity_service] = lambda: cast(IdentityService, service)
    return app


@pytest.mark.anyio
async def test_iam_projection_endpoints_return_ids_needed_for_removal() -> None:
    service = IdentityProjectionStub("MANAGE_ROLE", "MANAGE_GROUP", "MANAGE_DEPARTMENT")
    transport = httpx.ASGITransport(app=_app(service))

    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        role_permissions = await client.get(f"/api/v1/roles/{ROLE_ID}/permissions")
        roles = await client.get(f"/api/v1/users/{USER_ID}/roles")
        groups = await client.get(f"/api/v1/users/{USER_ID}/groups")
        departments = await client.get(
            f"/api/v1/users/{USER_ID}/departments?include_inactive=true"
        )

    assert role_permissions.status_code == 200
    assert role_permissions.json()[0]["id"] == str(PERMISSION_ID)
    assert roles.json()[0]["role_id"] == str(ROLE_ID)
    assert roles.json()[0]["role"]["code"] == "ADMIN"
    assert groups.json()[0]["group_id"] == str(GROUP_ID)
    assert departments.json()[0]["department_id"] == str(DEPARTMENT_ID)
    assert departments.json()[0]["is_primary"] is True
    assert service.include_inactive is True


@pytest.mark.anyio
async def test_membership_projection_endpoints_enforce_their_own_management_scope() -> None:
    service = IdentityProjectionStub("MANAGE_GROUP")
    transport = httpx.ASGITransport(app=_app(service))

    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as client:
        role_response = await client.get(f"/api/v1/users/{USER_ID}/roles")
        group_response = await client.get(f"/api/v1/users/{USER_ID}/groups")
        department_response = await client.get(f"/api/v1/users/{USER_ID}/departments")

    assert role_response.status_code == 403
    assert group_response.status_code == 200
    assert department_response.status_code == 403

