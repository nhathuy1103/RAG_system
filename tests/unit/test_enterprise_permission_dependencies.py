from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.api.dependencies.enterprise import (
    require_governance_access,
    require_manage_document,
    require_manage_report,
    require_upload_document,
    require_view_analytics,
)
from app.api.schemas.auth import CurrentUser
from app.identity.application.services import IdentityService
from app.identity.domain.models import PrincipalContext

USER_ID = UUID("10000000-0000-0000-0000-000000000001")


class PermissionIdentityStub:
    def __init__(self, *permissions: str) -> None:
        self._permissions = frozenset(permissions)

    async def current_principal(
        self,
        user_id: UUID,
        *,
        email: str | None = None,
    ) -> PrincipalContext:
        return PrincipalContext(
            user_id=user_id,
            email=email,
            status="ACTIVE",
            permissions=self._permissions,
        )


def _user(*, role: str = "user") -> CurrentUser:
    return CurrentUser(id=str(USER_ID), email="user@example.test", user_role=role)


@pytest.mark.anyio
async def test_upload_permission_does_not_grant_document_management() -> None:
    service = PermissionIdentityStub("UPLOAD_DOCUMENT")
    identity_service = cast(IdentityService, service)

    principal = await require_upload_document(_user(), identity_service)
    assert principal.user_id == USER_ID

    with pytest.raises(HTTPException) as caught:
        await require_manage_document(_user(), identity_service)
    assert caught.value.status_code == 403


@pytest.mark.anyio
async def test_manage_document_can_upload_but_legacy_admin_role_does_not_bypass_iam() -> None:
    manager = PermissionIdentityStub("MANAGE_DOCUMENT")
    manager_service = cast(IdentityService, manager)
    assert (await require_upload_document(_user(), manager_service)).user_id == USER_ID

    no_permissions = PermissionIdentityStub()
    empty_service = cast(IdentityService, no_permissions)
    with pytest.raises(HTTPException) as caught:
        await require_manage_document(_user(role="admin"), empty_service)
    assert caught.value.status_code == 403


@pytest.mark.anyio
async def test_governance_read_requires_view_audit_exactly() -> None:
    audit_service = cast(IdentityService, PermissionIdentityStub("VIEW_AUDIT"))
    assert (await require_governance_access(_user(), audit_service)).user_id == USER_ID

    for unrelated_permission in ("MANAGE_DOCUMENT", "MANAGE_USER", "VIEW_ANALYTICS"):
        unrelated_service = cast(
            IdentityService,
            PermissionIdentityStub(unrelated_permission),
        )
        with pytest.raises(HTTPException) as caught:
            await require_governance_access(_user(), unrelated_service)
        assert caught.value.status_code == 403


@pytest.mark.anyio
async def test_analytics_and_report_management_use_separate_permissions() -> None:
    analytics_service = cast(IdentityService, PermissionIdentityStub("VIEW_ANALYTICS"))
    report_service = cast(IdentityService, PermissionIdentityStub("MANAGE_REPORT"))

    assert (await require_view_analytics(_user(), analytics_service)).user_id == USER_ID
    assert (await require_manage_report(_user(), report_service)).user_id == USER_ID

    with pytest.raises(HTTPException) as analytics_denied:
        await require_view_analytics(_user(), report_service)
    assert analytics_denied.value.status_code == 403

    with pytest.raises(HTTPException) as report_denied:
        await require_manage_report(_user(), analytics_service)
    assert report_denied.value.status_code == 403
