"""Document and upload routes."""

import logging
from contextlib import suppress
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.services import get_document_service
from app.api.schemas.auth import CurrentUser
from app.api.schemas.documents import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadBatchResponse,
    DocumentUploadItemResponse,
)
from app.documents.application.services import (
    DocumentPreviewNotFoundError,
    DocumentPreviewStorageError,
    DocumentPreviewUnsupportedError,
    DocumentService,
    DocumentUploadError,
)
from app.documents.domain.models import (
    MAX_DOCUMENT_SIZE_BYTES,
    MAX_DOCUMENTS_PER_UPLOAD,
)
from app.documents.ports.repositories import DocumentRepositoryError
from app.notebooks.ports.repositories import NotebookRepositoryError

LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notebooks/{notebook_id}/documents",
    tags=["documents"],
)


def to_document_response(document: object) -> DocumentResponse:
    return DocumentResponse.model_validate(document, from_attributes=True)


DocumentStatus = Literal["uploading", "uploaded", "processing", "ready", "failed"]


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    notebook_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    document_status: Annotated[
        DocumentStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    """List documents from a user-owned notebook."""
    try:
        notebook_exists = await service.notebook_exists(notebook_id)
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    if not notebook_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found",
        )

    try:
        documents, total_count = await service.list_documents(
            notebook_id,
            status=document_status,
            limit=limit,
            offset=offset,
        )
    except DocumentRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Document storage is unavailable",
        ) from exc

    return DocumentListResponse(
        items=[to_document_response(document) for document in documents],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=DocumentUploadBatchResponse)
async def upload_documents(
    notebook_id: UUID,
    files: Annotated[list[UploadFile], File(description="One to twenty files")],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentUploadBatchResponse:
    """Upload one or more files independently into a user-owned notebook."""
    if len(files) > MAX_DOCUMENTS_PER_UPLOAD:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"At most {MAX_DOCUMENTS_PER_UPLOAD} files may be uploaded at once",
        )

    try:
        owner_id = UUID(current_user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token subject is not a valid UUID",
        ) from exc

    try:
        notebook_exists = await service.notebook_exists(notebook_id)
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    if not notebook_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found",
        )

    results: list[DocumentUploadItemResponse] = []
    for upload in files:
        filename = upload.filename or ""
        try:
            try:
                content = await upload.read(MAX_DOCUMENT_SIZE_BYTES + 1)
            except OSError:
                LOGGER.exception("Could not read uploaded file %r", filename)
                results.append(
                    DocumentUploadItemResponse(
                        filename=filename,
                        error_code="FILE_READ_FAILED",
                        error_message="Could not read uploaded file",
                    )
                )
                continue

            try:
                outcome = await service.upload_file(
                    owner_id,
                    notebook_id,
                    filename,
                    content,
                )
                results.append(
                    DocumentUploadItemResponse(
                        filename=filename,
                        document=to_document_response(outcome.document),
                        duplicate=outcome.is_duplicate,
                    )
                )
            except DocumentUploadError as exc:
                results.append(
                    DocumentUploadItemResponse(
                        filename=filename,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )
        finally:
            with suppress(OSError):
                await upload.close()

    succeeded_count = sum(item.document is not None for item in results)
    return DocumentUploadBatchResponse(
        total_count=len(results),
        succeeded_count=succeeded_count,
        failed_count=len(results) - succeeded_count,
        items=results,
    )


@router.get("/{document_id}/preview")
async def preview_document(
    notebook_id: UUID,
    document_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> Response:
    """Return an authenticated inline preview of an owned PDF document."""
    try:
        notebook_exists = await service.notebook_exists(notebook_id)
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    if not notebook_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found",
        )

    try:
        preview = await service.get_document_preview(notebook_id, document_id)
    except DocumentPreviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        ) from exc
    except DocumentPreviewUnsupportedError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Preview is currently supported for PDF documents only",
        ) from exc
    except (DocumentPreviewStorageError, DocumentRepositoryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Document preview is unavailable",
        ) from exc

    encoded_filename = quote(preview.filename, safe="")
    return Response(
        content=preview.content,
        media_type=preview.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    notebook_id: UUID,
    document_id: UUID,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentDeleteResponse:
    """Soft-delete (archive) a user-owned document; storage/vectors are kept."""
    try:
        notebook_exists = await service.notebook_exists(notebook_id)
    except NotebookRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notebook storage is unavailable",
        ) from exc
    if not notebook_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found",
        )

    try:
        deleted = await service.delete_document(notebook_id, document_id)
    except DocumentRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Document storage is unavailable",
        ) from exc
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return DocumentDeleteResponse(
        message="Document archived successfully",
        document_id=document_id,
    )
