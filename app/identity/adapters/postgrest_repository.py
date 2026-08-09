"""User-scoped PostgREST adapter for enterprise IAM administration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx

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
from app.identity.ports.repositories import (
    IdentityAccessDeniedError,
    IdentityConflictError,
    IdentityRepository,
    IdentityRepositoryError,
    OrganizationInput,
    ProfileInput,
)

LOGGER = logging.getLogger(__name__)


class PostgrestIdentityRepository(IdentityRepository):
    """Use RLS-protected public IAM tables and security-definer principal RPC."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_principal_context(self, user_id: UUID, *, email: str | None) -> PrincipalContext:
        payload = await self._rpc("get_principal_context", {})
        if payload is None:
            raise IdentityAccessDeniedError("Enterprise principal is inactive")
        row = self._one_mapping(payload, "principal context")
        roles_value = row.get("roles", [])
        roles: list[Role] = []
        if isinstance(roles_value, list):
            for value in roles_value:
                if isinstance(value, Mapping):
                    roles.append(self._parse_role(value))
        permission_value = row.get("permissions", row.get("functional_permissions", []))
        permissions = (
            frozenset(str(value) for value in permission_value)
            if isinstance(permission_value, list)
            else frozenset()
        )
        return PrincipalContext(
            user_id=UUID(str(row.get("user_id", user_id))),
            email=(str(row["email"]) if row.get("email") is not None else email),
            status=str(row.get("status", "ACTIVE")),
            roles=tuple(roles),
            permissions=permissions,
            group_ids=self._parse_uuid_tuple(row.get("group_ids", [])),
            department_ids=self._parse_uuid_tuple(row.get("department_ids", [])),
        )

    async def list_profiles(self, *, limit: int, offset: int) -> tuple[list[UserProfile], int]:
        response = await self._request(
            "GET",
            "/user_profiles",
            params={
                "select": "*",
                "order": "created_at.desc,user_id.asc",
                "limit": str(limit),
                "offset": str(offset),
            },
            headers={"Prefer": "count=exact"},
        )
        rows = self._rows(response.json(), "profile list")
        return [self._parse_profile(row) for row in rows], self._total_count(
            response.headers.get("content-range"), fallback=len(rows)
        )

    async def upsert_profile(self, value: ProfileInput) -> UserProfile:
        payload = await self._rpc(
            "upsert_user_profile",
            {
                "p_user_id": str(value.user_id),
                "p_company_user_id": value.company_user_id,
                "p_full_name": value.full_name,
                "p_status": value.status,
            },
        )
        return self._parse_profile(self._one_mapping(payload, "profile upsert"))

    async def update_profile(self, user_id: UUID, changes: dict[str, object]) -> UserProfile | None:
        response = await self._request(
            "GET",
            "/user_profiles",
            params={"user_id": f"eq.{user_id}", "select": "*", "limit": "1"},
        )
        rows = self._rows(response.json(), "profile lookup")
        if not rows:
            return None
        current = self._parse_profile(rows[0])
        return await self.upsert_profile(
            ProfileInput(
                user_id=user_id,
                company_user_id=(
                    str(changes["company_user_id"])
                    if changes.get("company_user_id") is not None
                    else None
                    if "company_user_id" in changes
                    else current.company_user_id
                ),
                full_name=(
                    str(changes["full_name"])
                    if changes.get("full_name") is not None
                    else None
                    if "full_name" in changes
                    else current.full_name
                ),
                status=str(changes.get("status", current.status)),
            )
        )

    async def list_roles(self) -> list[Role]:
        return [self._parse_role(row) for row in await self._list_organizations("roles")]

    async def create_role(self, value: OrganizationInput) -> Role:
        return self._parse_role(await self._create_organization("roles", value))

    async def update_role(self, object_id: UUID, changes: dict[str, object]) -> Role | None:
        row = await self._patch_one("roles", "id", object_id, changes)
        return self._parse_role(row) if row is not None else None

    async def list_functional_permissions(self) -> list[FunctionalPermission]:
        response = await self._request(
            "GET",
            "/functional_permissions",
            params={"select": "*", "order": "code.asc,id.asc"},
        )
        return [
            self._parse_functional_permission(row)
            for row in self._rows(response.json(), "functional permission list")
        ]

    async def list_role_permissions(self, role_id: UUID) -> list[FunctionalPermission]:
        response = await self._request(
            "GET",
            "/role_permissions",
            params={
                "role_id": f"eq.{role_id}",
                "select": "permission:functional_permissions(*)",
                "order": "assigned_at.asc,id.asc",
            },
        )
        permissions = [
            self._parse_functional_permission(
                self._related_mapping(row, "permission", "role permission")
            )
            for row in self._rows(response.json(), "role permission list")
        ]
        return sorted(permissions, key=lambda item: (item.code, str(item.id)))

    async def assign_role_permission(self, role_id: UUID, permission_id: UUID) -> None:
        await self._upsert_assignment(
            "role_permissions",
            "role_id,permission_id",
            {"role_id": str(role_id), "permission_id": str(permission_id)},
        )

    async def remove_role_permission(self, role_id: UUID, permission_id: UUID) -> None:
        await self._delete_assignment(
            "role_permissions",
            {"role_id": f"eq.{role_id}", "permission_id": f"eq.{permission_id}"},
        )

    async def list_groups(self) -> list[Group]:
        return [self._parse_group(row) for row in await self._list_organizations("groups")]

    async def create_group(self, value: OrganizationInput) -> Group:
        return self._parse_group(await self._create_organization("groups", value))

    async def update_group(self, object_id: UUID, changes: dict[str, object]) -> Group | None:
        row = await self._patch_one("groups", "id", object_id, changes)
        return self._parse_group(row) if row is not None else None

    async def list_departments(self) -> list[Department]:
        return [
            self._parse_department(row) for row in await self._list_organizations("departments")
        ]

    async def create_department(self, value: OrganizationInput) -> Department:
        return self._parse_department(await self._create_organization("departments", value))

    async def update_department(
        self, object_id: UUID, changes: dict[str, object]
    ) -> Department | None:
        row = await self._patch_one("departments", "id", object_id, changes)
        return self._parse_department(row) if row is not None else None

    async def assign_user_role(self, user_id: UUID, role_id: UUID) -> None:
        await self._upsert_assignment(
            "user_roles", "user_id,role_id", {"user_id": str(user_id), "role_id": str(role_id)}
        )

    async def remove_user_role(self, user_id: UUID, role_id: UUID) -> None:
        await self._delete_assignment(
            "user_roles", {"user_id": f"eq.{user_id}", "role_id": f"eq.{role_id}"}
        )

    async def list_user_roles(self, user_id: UUID) -> list[UserRoleMembership]:
        response = await self._request(
            "GET",
            "/user_roles",
            params={
                "user_id": f"eq.{user_id}",
                "select": "*,role:roles(*)",
                "order": "assigned_at.asc,id.asc",
            },
        )
        memberships = [
            self._parse_user_role_membership(row)
            for row in self._rows(response.json(), "user role membership list")
        ]
        return sorted(memberships, key=lambda item: (item.role.name.casefold(), str(item.id)))

    async def assign_user_group(self, user_id: UUID, group_id: UUID) -> None:
        await self._upsert_assignment(
            "user_groups",
            "user_id,group_id",
            {"user_id": str(user_id), "group_id": str(group_id)},
        )

    async def remove_user_group(self, user_id: UUID, group_id: UUID) -> None:
        await self._delete_assignment(
            "user_groups", {"user_id": f"eq.{user_id}", "group_id": f"eq.{group_id}"}
        )

    async def list_user_groups(self, user_id: UUID) -> list[UserGroupMembership]:
        response = await self._request(
            "GET",
            "/user_groups",
            params={
                "user_id": f"eq.{user_id}",
                "select": "*,group:groups(*)",
                "order": "joined_at.asc,id.asc",
            },
        )
        memberships = [
            self._parse_user_group_membership(row)
            for row in self._rows(response.json(), "user group membership list")
        ]
        return sorted(memberships, key=lambda item: (item.group.name.casefold(), str(item.id)))

    async def assign_user_department(
        self, user_id: UUID, department_id: UUID, *, is_primary: bool
    ) -> None:
        # Department membership is history-bearing. A new assignment creates a
        # new period rather than overwriting a prior (user, department) row.
        await self._request(
            "POST",
            "/user_departments",
            headers={"Prefer": "return=minimal"},
            json={
                "user_id": str(user_id),
                "department_id": str(department_id),
                "is_primary": is_primary,
            },
        )

    async def remove_user_department(self, user_id: UUID, department_id: UUID) -> None:
        await self._request(
            "PATCH",
            "/user_departments",
            params={
                "user_id": f"eq.{user_id}",
                "department_id": f"eq.{department_id}",
                "end_at": "is.null",
            },
            headers={"Prefer": "return=minimal"},
            json={"end_at": datetime.now(UTC).isoformat()},
        )

    async def list_user_departments(
        self, user_id: UUID, *, include_inactive: bool
    ) -> list[UserDepartmentMembership]:
        params = {
            "user_id": f"eq.{user_id}",
            "select": "*,department:departments(*)",
            "order": "is_primary.desc,start_at.asc,id.asc",
        }
        if not include_inactive:
            params["end_at"] = "is.null"
        response = await self._request("GET", "/user_departments", params=params)
        memberships = [
            self._parse_user_department_membership(row)
            for row in self._rows(response.json(), "user department membership list")
        ]
        return sorted(
            memberships,
            key=lambda item: (
                not item.is_primary,
                item.department.name.casefold(),
                str(item.id),
            ),
        )

    async def list_access_subjects(self, subject_type: str | None) -> list[AccessSubject]:
        params = {"select": "*", "order": "subject_type.asc,id.asc"}
        if subject_type is not None:
            params["subject_type"] = f"eq.{subject_type}"
        response = await self._request("GET", "/access_subjects", params=params)
        return [
            self._parse_access_subject(row)
            for row in self._rows(response.json(), "access subject list")
        ]

    async def _list_organizations(self, table: str) -> list[Mapping[str, object]]:
        response = await self._request(
            "GET", f"/{table}", params={"select": "*", "order": "name.asc,id.asc"}
        )
        return self._rows(response.json(), f"{table} list")

    async def _create_organization(
        self, table: str, value: OrganizationInput
    ) -> Mapping[str, object]:
        body: dict[str, object] = {
            "code": value.code,
            "name": value.name,
            "description": value.description or "",
            "status": value.status,
        }
        if table == "departments":
            body["parent_department_id"] = (
                str(value.parent_department_id) if value.parent_department_id else None
            )
        response = await self._request(
            "POST",
            f"/{table}",
            params={"select": "*"},
            headers={"Prefer": "return=representation"},
            json=body,
        )
        return self._one_mapping(response.json(), f"{table} create")

    async def _patch_one(
        self, table: str, key: str, object_id: UUID, changes: dict[str, object]
    ) -> Mapping[str, object] | None:
        response = await self._request(
            "PATCH",
            f"/{table}",
            params={key: f"eq.{object_id}", "select": "*"},
            headers={"Prefer": "return=representation"},
            json=changes,
        )
        rows = self._rows(response.json(), f"{table} update")
        return rows[0] if rows else None

    async def _upsert_assignment(
        self, table: str, conflict_columns: str, body: dict[str, object]
    ) -> None:
        await self._request(
            "POST",
            f"/{table}",
            params={"on_conflict": conflict_columns},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=body,
        )

    async def _delete_assignment(self, table: str, filters: dict[str, str]) -> None:
        await self._request("DELETE", f"/{table}", params=filters)

    async def _rpc(self, name: str, body: dict[str, object]) -> object:
        response = await self._request("POST", f"/rpc/{name}", json=body)
        return response.json()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int | float | bool | None] | None = None,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method, url, params=params, headers=headers, json=json
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise IdentityAccessDeniedError("IAM operation is not permitted") from exc
            if exc.response.status_code == 409:
                raise IdentityConflictError("Identity resource already exists") from exc
            LOGGER.exception("PostgREST IAM request failed: %s %s", method, url)
            raise IdentityRepositoryError("Identity storage is unavailable") from exc
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            LOGGER.exception("PostgREST IAM request failed: %s %s", method, url)
            raise IdentityRepositoryError("Identity storage is unavailable") from exc

    @staticmethod
    def _rows(payload: object, label: str) -> list[Mapping[str, object]]:
        if not isinstance(payload, list) or not all(isinstance(row, Mapping) for row in payload):
            raise IdentityRepositoryError(f"Invalid {label} response")
        return payload

    @classmethod
    def _one_mapping(cls, payload: object, label: str) -> Mapping[str, object]:
        if isinstance(payload, Mapping):
            return payload
        rows = cls._rows(payload, label)
        if len(rows) != 1:
            raise IdentityRepositoryError(f"Invalid {label} response")
        return rows[0]

    @staticmethod
    def _related_mapping(
        row: Mapping[str, object], key: str, label: str
    ) -> Mapping[str, object]:
        value = row.get(key)
        if not isinstance(value, Mapping):
            raise IdentityRepositoryError(f"Invalid {label} response")
        return value

    @staticmethod
    def _parse_uuid_tuple(value: object) -> tuple[UUID, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(UUID(str(item)) for item in value)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        return datetime.fromisoformat(str(value)) if value is not None else None

    @classmethod
    def _parse_profile(cls, row: Mapping[str, object]) -> UserProfile:
        return UserProfile(
            user_id=UUID(str(row["user_id"])),
            company_user_id=(str(row["company_user_id"]) if row.get("company_user_id") else None),
            full_name=(str(row["full_name"]) if row.get("full_name") else None),
            status=str(row["status"]),
            created_at=cls._parse_datetime(row.get("created_at")),
            updated_at=cls._parse_datetime(row.get("updated_at")),
        )

    @classmethod
    def _parse_role(cls, row: Mapping[str, object]) -> Role:
        return Role(
            id=UUID(str(row["id"])),
            code=str(row["code"]),
            name=str(row["name"]),
            description=(str(row["description"]) if row.get("description") else None),
            status=str(row.get("status", "ACTIVE")),
            created_at=cls._parse_datetime(row.get("created_at")),
            updated_at=cls._parse_datetime(row.get("updated_at")),
        )

    @classmethod
    def _parse_group(cls, row: Mapping[str, object]) -> Group:
        return Group(
            id=UUID(str(row["id"])),
            code=str(row["code"]),
            name=str(row["name"]),
            description=(str(row["description"]) if row.get("description") else None),
            status=str(row.get("status", "ACTIVE")),
            created_at=cls._parse_datetime(row.get("created_at")),
            updated_at=cls._parse_datetime(row.get("updated_at")),
        )

    @classmethod
    def _parse_functional_permission(cls, row: Mapping[str, object]) -> FunctionalPermission:
        return FunctionalPermission(
            id=UUID(str(row["id"])),
            code=str(row["code"]),
            name=str(row["name"]),
            description=(str(row["description"]) if row.get("description") else None),
            created_at=cls._parse_datetime(row.get("created_at")),
        )

    @classmethod
    def _parse_user_role_membership(cls, row: Mapping[str, object]) -> UserRoleMembership:
        return UserRoleMembership(
            id=UUID(str(row["id"])),
            user_id=UUID(str(row["user_id"])),
            role_id=UUID(str(row["role_id"])),
            role=cls._parse_role(cls._related_mapping(row, "role", "user role membership")),
            assigned_by=UUID(str(row["assigned_by"])) if row.get("assigned_by") else None,
            assigned_at=cls._parse_datetime(row.get("assigned_at")),
        )

    @classmethod
    def _parse_user_group_membership(cls, row: Mapping[str, object]) -> UserGroupMembership:
        return UserGroupMembership(
            id=UUID(str(row["id"])),
            user_id=UUID(str(row["user_id"])),
            group_id=UUID(str(row["group_id"])),
            group=cls._parse_group(cls._related_mapping(row, "group", "user group membership")),
            added_by=UUID(str(row["added_by"])) if row.get("added_by") else None,
            joined_at=cls._parse_datetime(row.get("joined_at")),
        )

    @classmethod
    def _parse_user_department_membership(
        cls, row: Mapping[str, object]
    ) -> UserDepartmentMembership:
        return UserDepartmentMembership(
            id=UUID(str(row["id"])),
            user_id=UUID(str(row["user_id"])),
            department_id=UUID(str(row["department_id"])),
            department=cls._parse_department(
                cls._related_mapping(row, "department", "user department membership")
            ),
            is_primary=row.get("is_primary") is True,
            start_at=datetime.fromisoformat(str(row["start_at"])),
            end_at=cls._parse_datetime(row.get("end_at")),
            assigned_by=UUID(str(row["assigned_by"])) if row.get("assigned_by") else None,
        )

    @staticmethod
    def _parse_access_subject(row: Mapping[str, object]) -> AccessSubject:
        return AccessSubject(
            id=UUID(str(row["id"])),
            subject_type=str(row["subject_type"]),
            user_id=UUID(str(row["user_id"])) if row.get("user_id") else None,
            role_id=UUID(str(row["role_id"])) if row.get("role_id") else None,
            group_id=UUID(str(row["group_id"])) if row.get("group_id") else None,
            department_id=(UUID(str(row["department_id"])) if row.get("department_id") else None),
        )

    @classmethod
    def _parse_department(cls, row: Mapping[str, object]) -> Department:
        return Department(
            id=UUID(str(row["id"])),
            code=str(row["code"]),
            name=str(row["name"]),
            description=(str(row["description"]) if row.get("description") else None),
            status=str(row.get("status", "ACTIVE")),
            parent_department_id=(
                UUID(str(row["parent_department_id"])) if row.get("parent_department_id") else None
            ),
            created_at=cls._parse_datetime(row.get("created_at")),
            updated_at=cls._parse_datetime(row.get("updated_at")),
        )

    @staticmethod
    def _total_count(content_range: str | None, *, fallback: int) -> int:
        if content_range and "/" in content_range:
            value = content_range.rsplit("/", maxsplit=1)[1]
            if value != "*":
                return int(value)
        return fallback
