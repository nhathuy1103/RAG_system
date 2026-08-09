"""Document domain models and file validation rules."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID
from zipfile import BadZipFile, ZipFile

MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTS_PER_UPLOAD = 20
MAX_ORIGINAL_FILENAME_LENGTH = 255
MAX_STORAGE_FILENAME_LENGTH = 200
DOCUMENT_STORAGE_BUCKET = "documents"

MIME_TYPE_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
}

OFFICE_CONTENT_FOLDERS = {
    ".docx": "word/",
    ".pptx": "ppt/",
    ".xlsx": "xl/",
}


class DocumentFileValidationError(ValueError):
    """A safe file-level validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ValidatedDocumentFile:
    """A fully validated file ready to persist."""

    original_filename: str
    storage_filename: str
    mime_type: str
    size_bytes: int
    content_hash: str
    content: bytes


@dataclass(frozen=True, slots=True)
class Document:
    """Document metadata persisted in Postgres."""

    id: UUID
    owner_id: UUID
    notebook_id: UUID
    original_filename: str
    storage_bucket: str
    storage_object_path: str
    mime_type: str
    size_bytes: int
    content_hash: str | None
    status: str
    error_message: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    normalized_content_hash: str | None = None
    normalization_version: str | None = None
    loose_content_signature: str | None = None
    canonical_document_id: UUID | None = None
    version_group_id: UUID | None = None
    version_number: int = 1
    effective_from: date | None = None
    effective_to: date | None = None
    supersedes_document_id: UUID | None = None
    is_current: bool = True
    quality_status: str = "unreviewed"


def _basename(filename: str) -> str:
    normalized_separators = filename.replace("\\", "/")
    return PurePosixPath(normalized_separators).name


def sanitize_storage_filename(filename: str) -> str:
    """Build a human-readable, path-safe storage filename."""
    basename = unicodedata.normalize("NFKC", _basename(filename)).strip()
    suffix = PurePosixPath(basename).suffix.lower()
    stem = basename[: -len(suffix)] if suffix else basename

    safe_characters = [
        character if character.isalnum() or character in "._-" else "_" for character in stem
    ]
    safe_stem = re.sub(r"_+", "_", "".join(safe_characters)).strip("._-")
    if not safe_stem:
        safe_stem = "file"

    available_stem_length = MAX_STORAGE_FILENAME_LENGTH - len(suffix)
    safe_stem = safe_stem[:available_stem_length].rstrip("._-") or "file"
    return f"{safe_stem}{suffix}"


def _validate_office_archive(content: bytes, required_folder: str) -> None:
    try:
        with ZipFile(BytesIO(content)) as archive:
            names = archive.namelist()
    except BadZipFile as exc:
        raise DocumentFileValidationError(
            "INVALID_FILE_CONTENT",
            "Office document is not a valid ZIP-based file",
        ) from exc

    if "[Content_Types].xml" not in names or not any(
        name.startswith(required_folder) for name in names
    ):
        raise DocumentFileValidationError(
            "INVALID_FILE_CONTENT",
            "Office document content does not match its file extension",
        )


def validate_document_file(filename: str, content: bytes) -> ValidatedDocumentFile:
    """Validate size, extension and file signature, then derive metadata."""
    original_filename = _basename(filename)
    if not 1 <= len(original_filename.strip()) <= MAX_ORIGINAL_FILENAME_LENGTH:
        raise DocumentFileValidationError(
            "INVALID_FILENAME",
            "Filename must contain 1 to 255 characters",
        )
    if not content:
        raise DocumentFileValidationError("EMPTY_FILE", "File must not be empty")
    if len(content) > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentFileValidationError(
            "FILE_TOO_LARGE",
            "File exceeds the 10 MiB limit",
        )

    normalized_filename = unicodedata.normalize("NFKC", original_filename).strip()
    extension = PurePosixPath(normalized_filename).suffix.lower()
    mime_type = MIME_TYPE_BY_EXTENSION.get(extension)
    if mime_type is None:
        raise DocumentFileValidationError(
            "UNSUPPORTED_FILE_TYPE",
            "Supported formats are PDF, DOCX, PPTX, XLSX, CSV, MD, HTML and TXT",
        )

    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise DocumentFileValidationError(
            "INVALID_FILE_CONTENT",
            "PDF signature is invalid",
        )
    if extension in OFFICE_CONTENT_FOLDERS:
        _validate_office_archive(content, OFFICE_CONTENT_FOLDERS[extension])
    if extension in {".csv", ".md", ".markdown", ".html", ".htm", ".txt"}:
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentFileValidationError(
                "INVALID_FILE_CONTENT",
                "Text-based documents must use UTF-8 encoding",
            ) from exc

    return ValidatedDocumentFile(
        original_filename=original_filename,
        storage_filename=sanitize_storage_filename(original_filename),
        mime_type=mime_type,
        size_bytes=len(content),
        content_hash=sha256(content).hexdigest(),
        content=content,
    )
