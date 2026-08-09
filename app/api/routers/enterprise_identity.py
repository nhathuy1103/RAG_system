"""Enterprise API v1 identity and organization routes."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.enterprise import (
    get_auth_user_provisioner,
    get_identity_service,
    require_manage_access_policy,
    require_manage_department,
    require_manage_group,
    require_manage_role,
    require_manage_user,
)
from app.api.schemas.auth import CurrentUser
from app.api.schemas.enterprise import (
    AccessSubjectResponse,
    AssignmentRequest,
    DepartmentResponse,
    EmployeeProvisionRequest,
    EmployeeProvisionResponse,
    FunctionalPermissionResponse,
    GroupResponse,
    OperationResponse,
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
    PrincipalResponse,
    ProfileCreateRequest,
    ProfileListResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    RoleResponse,
    UserDepartmentMembershipResponse,
    UserGroupMembershipResponse,
    UserRoleMembershipResponse,
)
from app.identity.application.services import IdentityService
from app.identity.domain.models import PrincipalContext
from app.identity.ports.repositories import (
    AuthUserInput,
    AuthUserProvisioner,
    OrganizationInput,
    ProfileInput,
)

router = APIRouter(prefix="/api/v1", tags=["enterprise-identity"])


@router.get("/me", response_model=PrincipalResponse)
async def get_principal(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> PrincipalResponse:
    try:
        user_id = UUID(current_user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token subject is not a valid UUID",
        ) from exc
    principal = await service.current_principal(user_id, email=current_user.email)
    return _principal_response(principal)


@router.get("/users", response_model=ProfileListResponse)
async def list_users(
    _principal: Annotated[PrincipalContext, Depends(require_manage_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProfileListResponse:
    items, total = await service.list_profiles(limit=limit, offset=offset)
    return ProfileListResponse(
        items=[ProfileResponse.model_validate(item) for item in items],
        total_count=total,
        limit=limit,
        offset=offset,
    )


@router.post("/users", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_user_profile(
    payload: ProfileCreateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> ProfileResponse:
    profile = await service.create_profile(ProfileInput(**payload.model_dump()))
    return ProfileResponse.model_validate(profile)


@router.post(
    "/users/provision",
    response_model=EmployeeProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def provision_employee(
    payload: EmployeeProvisionRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
    provisioner: Annotated[AuthUserProvisioner, Depends(get_auth_user_provisioner)],
) -> EmployeeProvisionResponse:
    user_id = await provisioner.create_employee(
        AuthUserInput(
            email=payload.email,
            temporary_password=payload.temporary_password,
            full_name=payload.full_name,
        )
    )
    profile = await service.create_profile(
        ProfileInput(
            user_id=user_id,
            company_user_id=payload.company_user_id,
            full_name=payload.full_name,
            status="ACTIVE",
        )
    )
    return EmployeeProvisionResponse(
        **ProfileResponse.model_validate(profile).model_dump(),
        email=payload.email,
    )


@router.patch("/users/{user_id}", response_model=ProfileResponse)
async def update_user_profile(
    user_id: UUID,
    payload: ProfileUpdateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> ProfileResponse:
    profile = await service.update_profile(user_id, payload.model_dump(exclude_unset=True))
    if profile is None:
        raise HTTPException(status_code=404, detail="User profile not found")
    return ProfileResponse.model_validate(profile)


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[RoleResponse]:
    return [RoleResponse.model_validate(item) for item in await service.list_roles()]


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: OrganizationCreateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> RoleResponse:
    role = await service.create_role(_organization_input(payload, include_parent=False))
    return RoleResponse.model_validate(role)


@router.get("/functional-permissions", response_model=list[FunctionalPermissionResponse])
async def list_functional_permissions(
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[FunctionalPermissionResponse]:
    return [
        FunctionalPermissionResponse.model_validate(item)
        for item in await service.list_functional_permissions()
    ]


@router.post("/roles/{role_id}/permissions", response_model=OperationResponse)
async def assign_role_permission(
    role_id: UUID,
    payload: AssignmentRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OperationResponse:
    await service.assign_role_permission(role_id, payload.object_id)
    return OperationResponse(message="Functional permission assigned")


@router.get(
    "/roles/{role_id}/permissions",
    response_model=list[FunctionalPermissionResponse],
)
async def list_role_permissions(
    role_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[FunctionalPermissionResponse]:
    return [
        FunctionalPermissionResponse.model_validate(item)
        for item in await service.list_role_permissions(role_id)
    ]


@router.delete("/roles/{role_id}/permissions/{permission_id}", response_model=OperationResponse)
async def remove_role_permission(
    role_id: UUID,
    permission_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OperationResponse:
    await service.remove_role_permission(role_id, permission_id)
    return OperationResponse(message="Functional permission assignment removed")


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: UUID,
    payload: OrganizationUpdateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> RoleResponse:
    changes = payload.model_dump(exclude_unset=True, exclude={"parent_department_id"})
    role = await service.update_role(role_id, changes)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return RoleResponse.model_validate(role)


@router.get("/groups", response_model=list[GroupResponse])
async def list_groups(
    _principal: Annotated[PrincipalContext, Depends(require_manage_group)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[GroupResponse]:
    return [GroupResponse.model_validate(item) for item in await service.list_groups()]


@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: OrganizationCreateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_group)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> GroupResponse:
    group = await service.create_group(_organization_input(payload, include_parent=False))
    return GroupResponse.model_validate(group)


@router.patch("/groups/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: UUID,
    payload: OrganizationUpdateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_group)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> GroupResponse:
    changes = payload.model_dump(exclude_unset=True, exclude={"parent_department_id"})
    group = await service.update_group(group_id, changes)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return GroupResponse.model_validate(group)


@router.get("/departments", response_model=list[DepartmentResponse])
async def list_departments(
    _principal: Annotated[PrincipalContext, Depends(require_manage_department)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[DepartmentResponse]:
    return [DepartmentResponse.model_validate(item) for item in await service.list_departments()]


@router.post("/departments", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: OrganizationCreateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_department)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DepartmentResponse:
    department = await service.create_department(_organization_input(payload, include_parent=True))
    return DepartmentResponse.model_validate(department)


@router.patch("/departments/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: UUID,
    payload: OrganizationUpdateRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_department)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DepartmentResponse:
    department = await service.update_department(
        department_id, payload.model_dump(exclude_unset=True)
    )
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return DepartmentResponse.model_validate(department)


@router.post("/users/{user_id}/roles", response_model=OperationResponse)
async def assign_role(
    user_id: UUID,
    payload: AssignmentRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OperationResponse:
    await service.assign_role(user_id, payload.object_id)
    return OperationResponse(message="Role assigned")


@router.get("/users/{user_id}/roles", response_model=list[UserRoleMembershipResponse])
async def list_user_roles(
    user_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[UserRoleMembershipResponse]:
    return [
        UserRoleMembershipResponse.model_validate(item)
        for item in await service.list_user_roles(user_id)
    ]


@router.delete("/users/{user_id}/roles/{role_id}", response_model=OperationResponse)
async def remove_role(
    user_id: UUID,
    role_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_role)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OperationResponse:
    await service.remove_role(user_id, role_id)
    return OperationResponse(message="Role assignment removed")


@router.post("/users/{user_id}/groups", response_model=OperationResponse)
async def assign_group(
    user_id: UUID,
    payload: AssignmentRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_group)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OperationResponse:
    await service.assign_group(user_id, payload.object_id)
    return OperationResponse(message="Group assigned")


@router.get("/users/{user_id}/groups", response_model=list[UserGroupMembershipResponse])
async def list_user_groups(
    user_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_group)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[UserGroupMembershipResponse]:
    return [
        UserGroupMembershipResponse.model_validate(item)
        for item in await service.list_user_groups(user_id)
    ]


@router.delete("/users/{user_id}/groups/{group_id}", response_model=OperationResponse)
async def remove_group(
    user_id: UUID,
    group_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_group)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OperationResponse:
    await service.remove_group(user_id, group_id)
    return OperationResponse(message="Group assignment removed")


@router.post("/users/{user_id}/departments", response_model=OperationResponse)
async def assign_department(
    user_id: UUID,
    payload: AssignmentRequest,
    _principal: Annotated[PrincipalContext, Depends(require_manage_department)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OperationResponse:
    await service.assign_department(user_id, payload.object_id, is_primary=payload.is_primary)
    return OperationResponse(message="Department assigned")


@router.get(
    "/users/{user_id}/departments",
    response_model=list[UserDepartmentMembershipResponse],
)
async def list_user_departments(
    user_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_department)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
    include_inactive: bool = Query(default=False),
) -> list[UserDepartmentMembershipResponse]:
    return [
        UserDepartmentMembershipResponse.model_validate(item)
        for item in await service.list_user_departments(user_id, include_inactive=include_inactive)
    ]


@router.delete("/users/{user_id}/departments/{department_id}", response_model=OperationResponse)
async def remove_department(
    user_id: UUID,
    department_id: UUID,
    _principal: Annotated[PrincipalContext, Depends(require_manage_department)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OperationResponse:
    await service.remove_department(user_id, department_id)
    return OperationResponse(message="Department assignment removed")


@router.get("/access-subjects", response_model=list[AccessSubjectResponse])
async def list_access_subjects(
    _principal: Annotated[PrincipalContext, Depends(require_manage_access_policy)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
    subject_type: Annotated[
        Literal["USER", "ROLE", "GROUP", "DEPARTMENT"] | None,
        Query(alias="type"),
    ] = None,
) -> list[AccessSubjectResponse]:
    return [
        AccessSubjectResponse.model_validate(item)
        for item in await service.list_access_subjects(subject_type)
    ]


def _principal_response(principal: PrincipalContext) -> PrincipalResponse:
    return PrincipalResponse(
        user_id=principal.user_id,
        email=principal.email,
        status=principal.status,
        roles=[RoleResponse.model_validate(role) for role in principal.roles],
        permissions=sorted(principal.permissions),
        group_ids=list(principal.group_ids),
        department_ids=list(principal.department_ids),
    )


def _organization_input(
    payload: OrganizationCreateRequest, *, include_parent: bool
) -> OrganizationInput:
    return OrganizationInput(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        parent_department_id=payload.parent_department_id if include_parent else None,
    )
