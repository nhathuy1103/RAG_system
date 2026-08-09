from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from pathlib import Path
from uuid import uuid4

CHUNK_SIZE = 64 * 1024
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_WHITESPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_PATH_PART = re.compile(r"[^A-Za-z0-9._-]+")


def compute_checksum_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def compute_checksum_text(content: str) -> str:
    return compute_checksum_bytes(content.encode("utf-8"))


def safe_filename(name: str) -> str:
    stem = _PATH_PART.sub("_", Path(name).name)
    return stem.strip("._") or str(uuid4())


def safe_path_part(value: str) -> str:
    sanitized = _PATH_PART.sub("_", value.strip())
    return sanitized.strip("._") or "unknown"


def build_object_key(
    *,
    tenant_id: str,
    owner_id: str,
    document_id: str,
    version: int,
    original_filename: str,
) -> str:
    return "/".join(
        [
            safe_path_part(tenant_id),
            safe_path_part(owner_id),
            safe_path_part(document_id),
            f"v{version}",
            safe_filename(original_filename),
        ]
    )


def normalize_text(content: str) -> str:
    content = unicodedata.normalize("NFC", content)
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = _CONTROL_CHARS.sub("", content)
    content = _WHITESPACE.sub(" ", content)
    content = _MULTI_NEWLINE.sub("\n\n", content)
    return content.strip()


def sanitize_html_content(content: str) -> str:
    content = re.sub(r"(?is)<script.*?>.*?</script>", " ", content)
    content = re.sub(r"(?is)<style.*?>.*?</style>", " ", content)
    content = re.sub(r"(?is)<br\s*/?>", "\n", content)
    content = re.sub(r"(?is)</p>|</div>|</li>|</tr>|</h[1-6]>", "\n", content)
    content = re.sub(r"(?is)<[^>]+>", " ", content)
    return normalize_text(html.unescape(content))


def detect_language(text: str) -> str:
    lowered = text.lower()
    if any(
        char in lowered
        for char in "ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    ):
        return "vi"
    if re.search(r"[a-zA-Z]", lowered):
        return "en"
    return "unknown"


def detect_prompt_injection_like_content(text: str) -> list[str]:
    warnings: list[str] = []
    lowered = text.lower()
    patterns = {
        "prompt_injection_instruction": [
            "ignore previous instructions",
            "system prompt",
            "developer message",
            "do not follow prior",
            "override instructions",
        ],
        "active_content_reference": [
            "<script",
            "javascript:",
            "vbscript:",
            "macro",
            "powershell -",
        ],
    }
    for warning_code, values in patterns.items():
        if any(value in lowered for value in values):
            warnings.append(warning_code)
    return warnings


def sniff_mime_type(filename: str, first_bytes: bytes) -> str:
    extension = Path(filename).suffix.lower()
    sample = first_bytes.lstrip()
    if sample.startswith(b"%PDF"):
        return "application/pdf"
    if sample.startswith(b"PK\x03\x04"):
        if extension == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if extension == ".pptx":
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        if extension == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    if sample.startswith(b"<"):
        lowered = sample[:512].lower()
        if b"<html" in lowered or b"<!doctype html" in lowered:
            return "text/html"
    if extension == ".csv":
        return "text/csv"
    if extension == ".md":
        return "text/markdown"
    if extension == ".txt":
        return "text/plain"
    return "application/octet-stream"
