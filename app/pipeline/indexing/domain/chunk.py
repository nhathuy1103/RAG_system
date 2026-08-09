from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

METADATA_VERSION = "1.0"
CHUNK_VERSION = "1.0"


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    page_number: int | None
    section_id: str | None
    heading: str | None
    parent_chunk: str | None
    children: tuple[str, ...]
    text: str
    offset_start: int
    offset_end: int
    token_count: int
    character_count: int
    language: str
    metadata: dict[str, Any]
    strategy_name: str
    strategy_version: str
    chunk_version: str
    confidence: float | None
    created_at: datetime
    updated_at: datetime


__all__ = ["CHUNK_VERSION", "METADATA_VERSION", "Chunk"]
