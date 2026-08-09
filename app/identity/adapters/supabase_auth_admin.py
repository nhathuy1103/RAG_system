"""Server-only Supabase Auth administration for employee provisioning."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from uuid import UUID

import httpx2 as httpx

from app.identity.ports.repositories import (
    AuthUserAlreadyExistsError,
    AuthUserInput,
    AuthUserProvisioner,
    AuthUserProvisioningError,
)

LOGGER = logging.getLogger(__name__)


class SupabaseAuthAdminProvisioner(AuthUserProvisioner):
    """Create confirmed email/password users through the trusted Auth Admin API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def create_employee(self, value: AuthUserInput) -> UUID:
        try:
            response = await self._client.post(
                "/admin/users",
                json={
                    "email": value.email,
                    "password": value.temporary_password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": value.full_name} if value.full_name else {},
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {409, 422}:
                raise AuthUserAlreadyExistsError(
                    "An account already exists for this email address"
                ) from exc
            LOGGER.exception("Supabase Auth employee provisioning failed")
            raise AuthUserProvisioningError(
                "Employee authentication account could not be created"
            ) from exc
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            LOGGER.exception("Supabase Auth employee provisioning failed")
            raise AuthUserProvisioningError(
                "Employee authentication service is unavailable"
            ) from exc

        payload = response.json()
        if not isinstance(payload, Mapping) or payload.get("id") is None:
            raise AuthUserProvisioningError("Supabase Auth returned an invalid user response")
        try:
            return UUID(str(payload["id"]))
        except ValueError as exc:
            raise AuthUserProvisioningError(
                "Supabase Auth returned an invalid user identifier"
            ) from exc
