from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.pipeline.documents.domain.parsed import ParsedDocument
from app.pipeline.indexing.domain.chunk import Chunk
from app.pipeline.indexing.domain.chunking_strategies import (
    ContentAwareChunkStrategy,
    StrategyConfig,
    StructureAwareRecursiveChunkStrategy,
)
from app.pipeline.shared.text_utils import compute_checksum_text

DEFAULT_STRATEGY = "structure_recursive"
CONTENT_AWARE_STRATEGY = "content_aware"
SUPPORTED_STRATEGIES = (DEFAULT_STRATEGY, CONTENT_AWARE_STRATEGY)


class ChunkerSettings(Protocol):
    @property
    def chunk_size(self) -> int: ...

    @property
    def chunk_overlap(self) -> int: ...

    @property
    def chunking_strategy(self) -> str: ...


@dataclass(frozen=True)
class ChunkData:
    chunk_id: str
    chunk_index: int
    text: str
    embedding_text: str
    search_text: str
    page_number: int | None
    section_title: str | None
    checksum: str
    document_id: str
    document_version: int
    section_id: str | None
    offset_start: int
    offset_end: int
    strategy: str
    strategy_version: str
    config_checksum: str
    content_checksum: str
    source_block_ids: tuple[str, ...]
    table_identity: str | None
    metadata: dict[str, Any]


def default_config(
    *,
    chunk_size: int = 256,
    overlap: int = 32,
) -> StrategyConfig:
    return StrategyConfig(
        chunk_size=chunk_size,
        overlap=overlap,
        chunk_size_unit="whitespace_tokens",
        overlap_unit="whitespace_tokens",
        boundary_priority=("paragraph", "sentence", "token"),
        table_atomicity=True,
        section_hard_boundary=True,
        page_metadata_policy="first_source_token",
        oversize_table_policy="atomic_table_oversize_exception",
        config_version="structure-v1",
    )


def canonical_config(
    config: StrategyConfig | None = None,
    *,
    strategy: str = DEFAULT_STRATEGY,
) -> dict[str, object]:
    effective = config or default_config()
    return effective.canonical_contract(strategy)


def chunk_parsed_document(
    document_id: str,
    version: int,
    parsed: ParsedDocument,
    config: StrategyConfig | None = None,
    *,
    strategy: str = DEFAULT_STRATEGY,
) -> list[ChunkData]:
    effective = config or default_config()
    logical = parsed.to_logical_document()
    logical.id = document_id
    logical.version = version
    if strategy == DEFAULT_STRATEGY:
        splitter = StructureAwareRecursiveChunkStrategy(effective)
    elif strategy == CONTENT_AWARE_STRATEGY:
        splitter = ContentAwareChunkStrategy(effective)
    else:
        raise ValueError(f"Unsupported chunking strategy: {strategy}")
    rich_chunks = splitter.split(logical)
    return [_project_chunk(chunk, index, version) for index, chunk in enumerate(rich_chunks)]


def _project_chunk(chunk: Chunk, index: int, version: int) -> ChunkData:
    metadata = dict(chunk.metadata)
    metadata.pop("created_time", None)
    block_ids = tuple(
        item for item in str(metadata.get("source_block_ids") or "").split(",") if item
    )
    table_identity = block_ids[0] if metadata.get("table_atomic") and block_ids else None
    content_checksum = compute_checksum_text(chunk.text)
    embedding_text = str(metadata.get("embedding_text") or chunk.text).strip()
    search_text = str(metadata.get("search_text") or chunk.text).strip()
    return ChunkData(
        chunk_id=chunk.id,
        chunk_index=index,
        text=chunk.text,
        embedding_text=embedding_text,
        search_text=search_text,
        page_number=chunk.page_number,
        section_title=chunk.heading,
        checksum=content_checksum,
        document_id=chunk.document_id,
        document_version=version,
        section_id=chunk.section_id,
        offset_start=chunk.offset_start,
        offset_end=chunk.offset_end,
        strategy=chunk.strategy_name,
        strategy_version=chunk.strategy_version,
        config_checksum=str(metadata["config_checksum"]),
        content_checksum=content_checksum,
        source_block_ids=block_ids,
        table_identity=table_identity,
        metadata=metadata,
    )


class Chunker:
    """Production chunker with a configurable structure-aware strategy."""

    def __init__(
        self,
        chunk_size: int,
        overlap: int,
        *,
        strategy_name: str = DEFAULT_STRATEGY,
    ) -> None:
        self.strategy_name = strategy_name
        self.config = default_config(
            chunk_size=chunk_size,
            overlap=overlap,
        )

    @classmethod
    def structure_recursive(
        cls,
        *,
        chunk_size: int = 256,
        overlap: int = 32,
    ) -> Chunker:
        return cls(chunk_size, overlap, strategy_name=DEFAULT_STRATEGY)

    @classmethod
    def content_aware(
        cls,
        *,
        chunk_size: int = 256,
        overlap: int = 32,
    ) -> Chunker:
        return cls(chunk_size, overlap, strategy_name=CONTENT_AWARE_STRATEGY)

    @classmethod
    def from_settings(cls, settings: ChunkerSettings) -> Chunker:
        return cls(
            chunk_size=int(settings.chunk_size),
            overlap=int(settings.chunk_overlap),
            strategy_name=str(settings.chunking_strategy),
        )

    def chunk(
        self,
        document_id: str,
        version: int,
        parsed: ParsedDocument,
    ) -> list[ChunkData]:
        return chunk_parsed_document(
            document_id,
            version,
            parsed,
            self.config,
            strategy=self.strategy_name,
        )


__all__ = [
    "CONTENT_AWARE_STRATEGY",
    "DEFAULT_STRATEGY",
    "SUPPORTED_STRATEGIES",
    "ChunkData",
    "Chunker",
    "canonical_config",
    "chunk_parsed_document",
    "default_config",
]
