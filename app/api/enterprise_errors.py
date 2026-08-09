"""Versioned API error contract and request correlation helpers."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import cast
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.documents.application.enterprise_services import EnterpriseDocumentValidationError
from app.documents.domain.enterprise_models import EnterpriseDocumentStateError
from app.documents.ports.enterprise_repositories import (
    EnterpriseDocumentAccessDeniedError,
    EnterpriseDocumentConflictError,
    EnterpriseDocumentRepositoryError,
)
from app.documents.ports.source_signing import SourceSigningError
from app.governance.application.services import GovernanceValidationError
from app.governance.ports.repositories import (
    GovernanceAccessDeniedError,
    GovernanceConflictError,
    GovernanceRepositoryError,
)
from app.identity.application.services import IdentityValidationError
from app.identity.ports.repositories import (
    IdentityAccessDeniedError,
    IdentityConflictError,
    IdentityRepositoryError,
)

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def request_trace_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else str(uuid4())


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    supplied = request.headers.get("X-Request-ID")
    request_id = supplied if supplied and REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def _error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    trace_id = request_trace_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "trace_id": trace_id,
            }
        },
        headers={"X-Request-ID": trace_id},
    )


async def versioned_http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_exception = cast(StarletteHTTPException, exc)
    if request.url.path.startswith("/api/v1"):
        detail = http_exception.detail
        if isinstance(detail, dict):
            code = str(detail.get("code", f"HTTP_{http_exception.status_code}"))
            message = str(detail.get("message", "Request failed"))
        else:
            code = f"HTTP_{http_exception.status_code}"
            message = str(detail)
        response = _error(request, http_exception.status_code, code, message)
        for key, value in (http_exception.headers or {}).items():
            response.headers[key] = value
        return response
    return JSONResponse(
        status_code=http_exception.status_code,
        content={"detail": jsonable_encoder(http_exception.detail)},
        headers=http_exception.headers,
    )


async def versioned_validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)
    if request.url.path.startswith("/api/v1"):
        return _error(
            request,
            422,
            "REQUEST_VALIDATION_FAILED",
            "Request payload or parameters are invalid",
        )
    return JSONResponse(
        status_code=422, content={"detail": jsonable_encoder(validation_error.errors())}
    )


async def enterprise_domain_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(
        exc,
        (IdentityValidationError, EnterpriseDocumentValidationError, GovernanceValidationError),
    ):
        return _error(request, 422, exc.code, exc.message)
    if isinstance(exc, EnterpriseDocumentStateError):
        return _error(request, 409, exc.code, exc.message)
    if isinstance(
        exc,
        (IdentityConflictError, EnterpriseDocumentConflictError, GovernanceConflictError),
    ):
        return _error(request, 409, "OPERATION_CONFLICT", str(exc))
    if isinstance(
        exc,
        (
            IdentityAccessDeniedError,
            EnterpriseDocumentAccessDeniedError,
            GovernanceAccessDeniedError,
        ),
    ):
        return _error(request, 403, "ACCESS_DENIED", str(exc))
    if isinstance(
        exc,
        (
            IdentityRepositoryError,
            EnterpriseDocumentRepositoryError,
            GovernanceRepositoryError,
            SourceSigningError,
        ),
    ):
        return _error(request, 502, "UPSTREAM_STORAGE_UNAVAILABLE", str(exc))
    return _error(request, 500, "INTERNAL_ERROR", "Unexpected server error")


ENTERPRISE_DOMAIN_EXCEPTIONS: tuple[type[Exception], ...] = (
    IdentityValidationError,
    IdentityAccessDeniedError,
    IdentityConflictError,
    IdentityRepositoryError,
    EnterpriseDocumentValidationError,
    EnterpriseDocumentAccessDeniedError,
    EnterpriseDocumentStateError,
    EnterpriseDocumentConflictError,
    EnterpriseDocumentRepositoryError,
    GovernanceValidationError,
    GovernanceAccessDeniedError,
    GovernanceConflictError,
    GovernanceRepositoryError,
    SourceSigningError,
)


def install_enterprise_error_contract(app: object) -> None:
    """Install v1-aware handlers while preserving the legacy HTTP error shape."""
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")
    app.add_exception_handler(HTTPException, versioned_http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, versioned_http_exception_handler)
    app.add_exception_handler(RequestValidationError, versioned_validation_exception_handler)
    for exception_type in ENTERPRISE_DOMAIN_EXCEPTIONS:
        app.add_exception_handler(exception_type, enterprise_domain_exception_handler)
