"""Use-case facade for enterprise identity administration."""

from __future__ import annotations

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
from app.identity.ports.repositories import IdentityRepository, OrganizationInput, ProfileInput


class IdentityValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class IdentityService:
    def __init__(self, repository: IdentityRepository) -> None:
        self._repository = repository

    async def current_principal(
        self, user_id: UUID, *, email: str | None = None
    ) -> PrincipalContext:
        return await self._repository.get_principal_context(user_id, email=email)

    async def list_profiles(self, *, limit: int, offset: int) -> tuple[list[UserProfile], int]:
        return await self._repository.list_profiles(limit=limit, offset=offset)

    async def create_profile(self, value: ProfileInput) -> UserProfile:
        return await self._repository.upsert_profile(value)

    async def update_profile(self, user_id: UUID, changes: dict[str, object]) -> UserProfile | None:
        return await self._repository.update_profile(user_id, self._validated_changes(changes))

    async def list_roles(self) -> list[Role]:
        return await self._repository.list_roles()

    async def create_role(self, value: OrganizationInput) -> Role:
        return await self._repository.create_role(self._normalized_organization(value))

    async def update_role(self, object_id: UUID, changes: dict[str, object]) -> Role | None:
        return await self._repository.update_role(object_id, self._validated_changes(changes))

    async def list_functional_permissions(self) -> list[FunctionalPermission]:
        return await self._repository.list_functional_permissions()

    async def list_role_permissions(self, role_id: UUID) -> list[FunctionalPermission]:
        return await self._repository.list_role_permissions(role_id)

    async def assign_role_permission(self, role_id: UUID, permission_id: UUID) -> None:
        await self._repository.assign_role_permission(role_id, permission_id)

    async def remove_role_permission(self, role_id: UUID, permission_id: UUID) -> None:
        await self._repository.remove_role_permission(role_id, permission_id)

    async def list_groups(self) -> list[Group]:
        return await self._repository.list_groups()

    async def create_group(self, value: OrganizationInput) -> Group:
        return await self._repository.create_group(self._normalized_organization(value))

    async def update_group(self, object_id: UUID, changes: dict[str, object]) -> Group | None:
        return await self._repository.update_group(object_id, self._validated_changes(changes))

    async def list_departments(self) -> list[Department]:
        return await self._repository.list_departments()

    async def create_department(self, value: OrganizationInput) -> Department:
        return await self._repository.create_department(self._normalized_organization(value))

    async def update_department(
        self, object_id: UUID, changes: dict[str, object]
    ) -> Department | None:
        return await self._repository.update_department(object_id, self._validated_changes(changes))

    async def assign_role(self, user_id: UUID, role_id: UUID) -> None:
        await self._repository.assign_user_role(user_id, role_id)

    async def remove_role(self, user_id: UUID, role_id: UUID) -> None:
        await self._repository.remove_user_role(user_id, role_id)

    async def list_user_roles(self, user_id: UUID) -> list[UserRoleMembership]:
        return await self._repository.list_user_roles(user_id)

    async def assign_group(self, user_id: UUID, group_id: UUID) -> None:
        await self._repository.assign_user_group(user_id, group_id)

    async def remove_group(self, user_id: UUID, group_id: UUID) -> None:
        await self._repository.remove_user_group(user_id, group_id)

    async def list_user_groups(self, user_id: UUID) -> list[UserGroupMembership]:
        return await self._repository.list_user_groups(user_id)

    async def assign_department(
        self, user_id: UUID, department_id: UUID, *, is_primary: bool
    ) -> None:
        await self._repository.assign_user_department(user_id, department_id, is_primary=is_primary)

    async def remove_department(self, user_id: UUID, department_id: UUID) -> None:
        await self._repository.remove_user_department(user_id, department_id)

    async def list_user_departments(
        self, user_id: UUID, *, include_inactive: bool = False
    ) -> list[UserDepartmentMembership]:
        return await self._repository.list_user_departments(
            user_id, include_inactive=include_inactive
        )

    async def list_access_subjects(self, subject_type: str | None) -> list[AccessSubject]:
        return await self._repository.list_access_subjects(subject_type)

    @staticmethod
    def _normalized_organization(value: OrganizationInput) -> OrganizationInput:
        code = value.code.strip().upper()
        name = value.name.strip()
        if not code or not name:
            raise IdentityValidationError(
                "INVALID_ORGANIZATION", "Organization code and name are required"
            )
        return OrganizationInput(
            code=code,
            name=name,
            description=value.description,
            status=value.status,
            parent_department_id=value.parent_department_id,
        )

    @staticmethod
    def _validated_changes(changes: dict[str, object]) -> dict[str, object]:
        normalized = dict(changes)
        if "description" in normalized and normalized["description"] is None:
            normalized["description"] = ""
        for key in ("code", "name", "full_name"):
            value = normalized.get(key)
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    raise IdentityValidationError("INVALID_UPDATE", f"{key} must not be empty")
                normalized[key] = value.upper() if key == "code" else value
        return normalized
