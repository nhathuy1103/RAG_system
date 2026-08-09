"""Persistence contracts for enterprise identity and organization data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.identity.domain.models import (
    AccessSubject,
    Department,
    FunctionalPermission,
    Group,
    PrincipalContext,
    Role,
    UserDepartmentMembership,
    UserGroupMembership,
    UserProfile,
    UserRoleMembership,
)


class IdentityRepositoryError(RuntimeError):
    """Safe boundary error raised when identity persistence is unavailable."""


class IdentityConflictError(IdentityRepositoryError):
    """A unique identity or organization key already exists."""


class IdentityAccessDeniedError(IdentityRepositoryError):
    """The current principal is inactive or lacks an IAM permission."""


class AuthUserProvisioningError(IdentityRepositoryError):
    """Supabase Auth could not provision an employee account."""


class AuthUserAlreadyExistsError(IdentityConflictError):
    """An Auth identity already exists for the requested email address."""


@dataclass(frozen=True, slots=True)
class AuthUserInput:
    email: str
    temporary_password: str
    full_name: str | None = None


class AuthUserProvisioner(Protocol):
    async def create_employee(self, value: AuthUserInput) -> UUID: ...


@dataclass(frozen=True, slots=True)
class ProfileInput:
    user_id: UUID
    company_user_id: str | None = None
    full_name: str | None = None
    status: str = "ACTIVE"


@dataclass(frozen=True, slots=True)
class OrganizationInput:
    code: str
    name: str
    description: str | None = None
    status: str = "ACTIVE"
    parent_department_id: UUID | None = None


class IdentityRepository(Protocol):
    async def get_principal_context(
        self, user_id: UUID, *, email: str | None
    ) -> PrincipalContext: ...

    async def list_profiles(self, *, limit: int, offset: int) -> tuple[list[UserProfile], int]: ...

    async def upsert_profile(self, value: ProfileInput) -> UserProfile: ...

    async def update_profile(
        self, user_id: UUID, changes: dict[str, object]
    ) -> UserProfile | None: ...

    async def list_roles(self) -> list[Role]: ...

    async def create_role(self, value: OrganizationInput) -> Role: ...

    async def update_role(self, object_id: UUID, changes: dict[str, object]) -> Role | None: ...

    async def list_functional_permissions(self) -> list[FunctionalPermission]: ...

    async def list_role_permissions(self, role_id: UUID) -> list[FunctionalPermission]: ...

    async def assign_role_permission(self, role_id: UUID, permission_id: UUID) -> None: ...

    async def remove_role_permission(self, role_id: UUID, permission_id: UUID) -> None: ...

    async def list_groups(self) -> list[Group]: ...

    async def create_group(self, value: OrganizationInput) -> Group: ...

    async def update_group(self, object_id: UUID, changes: dict[str, object]) -> Group | None: ...

    async def list_departments(self) -> list[Department]: ...

    async def create_department(self, value: OrganizationInput) -> Department: ...

    async def update_department(
        self, object_id: UUID, changes: dict[str, object]
    ) -> Department | None: ...

    async def assign_user_role(self, user_id: UUID, role_id: UUID) -> None: ...

    async def remove_user_role(self, user_id: UUID, role_id: UUID) -> None: ...

    async def list_user_roles(self, user_id: UUID) -> list[UserRoleMembership]: ...

    async def assign_user_group(self, user_id: UUID, group_id: UUID) -> None: ...

    async def remove_user_group(self, user_id: UUID, group_id: UUID) -> None: ...

    async def list_user_groups(self, user_id: UUID) -> list[UserGroupMembership]: ...

    async def assign_user_department(
        self, user_id: UUID, department_id: UUID, *, is_primary: bool
    ) -> None: ...

    async def remove_user_department(self, user_id: UUID, department_id: UUID) -> None: ...

    async def list_user_departments(
        self, user_id: UUID, *, include_inactive: bool
    ) -> list[UserDepartmentMembership]: ...

    async def list_access_subjects(self, subject_type: str | None) -> list[AccessSubject]: ...
