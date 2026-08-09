from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.shared.text_utils import compute_checksum_bytes


@dataclass(frozen=True)
class DocumentSource:
    document_id: str
    owner_id: str
    tenant_id: str
    title: str
    content: bytes
    version: int = 1
    mime_type: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def extension(self) -> str:
        return Path(self.title).suffix.lower().lstrip(".")

    @property
    def checksum(self) -> str:
        return compute_checksum_bytes(self.content)

    @property
    def size_bytes(self) -> int:
        return len(self.content)


__all__ = ["DocumentSource"]
