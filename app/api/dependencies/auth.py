"""Supabase JWT authentication dependency."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from app.api.schemas.auth import CurrentUser
from app.bootstrap.settings import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache(maxsize=8)
def _get_jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_access_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> str:
    """Extract the Bearer token for downstream user-scoped adapters."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Missing Bearer token")
    return credentials.credentials


async def get_current_user(
    access_token: Annotated[str, Depends(get_access_token)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    """Validate a Supabase access token and return its safe identity claims."""
    if settings.supabase_issuer is None or settings.supabase_jwks_url is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication is not configured",
        )

    try:
        signing_key = _get_jwk_client(settings.supabase_jwks_url).get_signing_key_from_jwt(
            access_token
        )
        payload = jwt.decode(
            access_token,
            signing_key.key,
            algorithms=["ES256", "RS256", "EdDSA"],
            audience=settings.supabase_jwt_audience,
            issuer=settings.supabase_issuer,
            options={
                "require": ["exp", "iat", "sub", "aud", "iss"],
            },
            leeway=30,
        )
    except (InvalidTokenError, PyJWKClientError) as exc:
        raise _unauthorized("Invalid or expired access token") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _unauthorized("Access token has no valid subject")

    email = payload.get("email")
    role = payload.get("role")
    user_role = payload.get("user_role")
    return CurrentUser(
        id=subject,
        email=email if isinstance(email, str) else None,
        role=role if isinstance(role, str) else None,
        user_role=user_role if isinstance(user_role, str) else None,
    )


async def require_admin(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Gate admin routes on the user_role JWT claim. Needs the Custom Access
    Token Hook enabled in Supabase Dashboard, else always 403."""
    if current_user.user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
