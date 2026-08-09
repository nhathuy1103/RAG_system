from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.pipeline.documents.domain.source import DocumentSource
from app.pipeline.shared.errors import AppError

DEFAULT_EXTENSIONS = (
    "pdf",
    "docx",
    "txt",
    "pptx",
    "xlsx",
    "csv",
    "md",
    "markdown",
    "html",
    "htm",
)

DEFAULT_MIME_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/csv",
    "text/markdown",
    "text/html",
    "application/octet-stream",
)

EXPECTED_MIME_BY_EXTENSION = {
    "txt": {"text/plain"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "pdf": {"application/pdf"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "csv": {"text/csv", "text/plain"},
    "md": {"text/markdown", "text/plain"},
    "markdown": {"text/markdown", "text/plain"},
    "html": {"text/html"},
    "htm": {"text/html"},
}


@dataclass(frozen=True)
class DocumentValidationConfig:
    allowed_extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    allowed_mime_types: tuple[str, ...] = DEFAULT_MIME_TYPES
    max_file_size_bytes: int = 10 * 1024 * 1024


def guess_extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def validate_document_source(
    source: DocumentSource,
    config: DocumentValidationConfig | None = None,
) -> None:
    effective = config or DocumentValidationConfig()
    extension = source.extension
    if extension not in effective.allowed_extensions:
        raise AppError(
            "unsupported_file",
            "File extension is not supported.",
            status_code=415,
        )
    if source.size_bytes <= 0:
        raise AppError(
            "validation_error",
            "Empty files are not valid for ingestion.",
        )
    if source.size_bytes > effective.max_file_size_bytes:
        raise AppError(
            "file_size_limit_exceeded",
            "File size exceeds the configured limit.",
        )
    if source.mime_type is None:
        return
    if (
        source.mime_type not in effective.allowed_mime_types
        and source.mime_type != "application/octet-stream"
    ):
        raise AppError(
            "validation_error",
            "Detected MIME type is not allowed.",
        )
    expected_mimes = EXPECTED_MIME_BY_EXTENSION.get(extension, set())
    if (
        expected_mimes
        and source.mime_type != "application/octet-stream"
        and source.mime_type not in expected_mimes
    ):
        raise AppError(
            "validation_error",
            "File extension and detected MIME type do not match.",
        )


__all__ = [
    "DEFAULT_EXTENSIONS",
    "DEFAULT_MIME_TYPES",
    "DocumentValidationConfig",
    "guess_extension",
    "validate_document_source",
]
