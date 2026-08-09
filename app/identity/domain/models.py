"""Enterprise identity, organization and functional authorization models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class IdentityStatus(StrEnum):
    """Lifecycle shared by profiles and organization objects."""

    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class UserProfile:
    """Business profile linked one-to-one with a Supabase Auth user."""

    user_id: UUID
    company_user_id: str | None
    full_name: str | None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Role:
    id: UUID
    code: str
    name: str
    description: str | None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Group:
    id: UUID
    code: str
    name: str
    description: str | None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Department:
    id: UUID
    code: str
    name: str
    description: str | None
    status: str
    parent_department_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FunctionalPermission:
    id: UUID
    code: str
    name: str
    description: str | None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserRoleMembership:
    """A user's direct role assignment with its display projection."""

    id: UUID
    user_id: UUID
    role_id: UUID
    role: Role
    assigned_by: UUID | None = None
    assigned_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserGroupMembership:
    """A user's direct group membership with its display projection."""

    id: UUID
    user_id: UUID
    group_id: UUID
    group: Group
    added_by: UUID | None = None
    joined_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserDepartmentMembership:
    """A current or historical department membership and its organization data."""

    id: UUID
    user_id: UUID
    department_id: UUID
    department: Department
    is_primary: bool
    start_at: datetime
    end_at: datetime | None = None
    assigned_by: UUID | None = None


@dataclass(frozen=True, slots=True)
class AccessSubject:
    id: UUID
    subject_type: str
    user_id: UUID | None = None
    role_id: UUID | None = None
    group_id: UUID | None = None
    department_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """Current, request-scoped authorization context resolved by the database."""

    user_id: UUID
    email: str | None
    status: str
    roles: tuple[Role, ...] = ()
    permissions: frozenset[str] = field(default_factory=frozenset)
    group_ids: tuple[UUID, ...] = ()
    department_ids: tuple[UUID, ...] = ()

    def has_permission(self, permission_code: str) -> bool:
        return permission_code in self.permissions
