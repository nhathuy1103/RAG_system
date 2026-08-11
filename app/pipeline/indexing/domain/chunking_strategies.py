from __future__ import annotations

import json
import re
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256

from app.pipeline.documents.domain.models import (
    BlockType,
    DocumentBlock,
    DocumentSection,
    LogicalDocument,
)
from app.pipeline.indexing.domain.chunk import CHUNK_VERSION, METADATA_VERSION, Chunk
from app.shared.contextual_text import ChunkContext, build_embedding_text, build_search_text

_SENTENCE_TERMINATOR_PATTERN = re.compile(r"[.!?…。！？]+[\"'”’»)\]}]*$")


@dataclass(frozen=True)
class StrategyConfig:
    chunk_size: int = 256
    overlap: int = 32
    max_characters: int = 20000
    table_atomic_max_tokens: int = 384
    table_row_group_target_tokens: int = 220
    chunk_size_unit: str = "whitespace_tokens"
    overlap_unit: str = "whitespace_tokens"
    boundary_priority: tuple[str, ...] = ("paragraph", "sentence", "token")
    table_atomicity: bool = True
    section_hard_boundary: bool = True
    page_metadata_policy: str = "first_source_token"
    oversize_table_policy: str = "atomic_table_oversize_exception"
    config_version: str = "structure-v1"

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive.")
        if self.overlap < 0:
            raise ValueError("overlap must not be negative.")
        if self.overlap >= self.chunk_size:
            raise ValueError("overlap must be smaller than chunk_size.")
        if self.max_characters <= 0:
            raise ValueError("max_characters must be positive.")
        if self.table_atomic_max_tokens <= 0:
            raise ValueError("table_atomic_max_tokens must be positive.")
        if self.table_row_group_target_tokens <= 0:
            raise ValueError("table_row_group_target_tokens must be positive.")

    def canonical_contract(self, strategy: str) -> dict[str, object]:
        contract: dict[str, object] = {
            "boundary_priority": list(self.boundary_priority),
            "chunk_size": self.chunk_size,
            "chunk_size_unit": self.chunk_size_unit,
            "max_characters": self.max_characters,
            "overlap": self.overlap,
            "overlap_unit": self.overlap_unit,
            "oversize_table_policy": self.oversize_table_policy,
            "page_metadata_policy": self.page_metadata_policy,
            "section_hard_boundary": self.section_hard_boundary,
            "strategy": strategy,
            "table_atomicity": self.table_atomicity,
            "version": self.config_version,
        }
        if strategy == ContentAwareChunkStrategy.name:
            contract.update(
                {
                    "table_atomic_max_tokens": self.table_atomic_max_tokens,
                    "table_row_group_target_tokens": self.table_row_group_target_tokens,
                }
            )
        return contract

    def checksum(self, strategy: str) -> str:
        payload = json.dumps(
            self.canonical_contract(strategy),
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()


class StructureAwareRecursiveChunkStrategy:
    """Token-bounded section chunks with atomic handling of table blocks."""

    name = "structure_recursive"
    version = "2.0"

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()

    def split(self, document: LogicalDocument) -> tuple[Chunk, ...]:
        chunks: list[Chunk] = []
        block_by_id = {block.id: block for block in document.blocks}
        section_paths = _section_paths(document.sections)
        sections = _flatten_sections(document.sections) or [
            DocumentSection(
                id="document",
                title=document.title,
                block_ids=[block.id for block in document.blocks],
            )
        ]
        processed: set[str] = set()

        for section in sections:
            section_blocks = [
                block_by_id[block_id]
                for block_id in section.block_ids
                if (
                    block_id in block_by_id
                    and block_id not in processed
                    and block_by_id[block_id].text.strip()
                    and _is_indexable_block(block_by_id[block_id])
                )
            ]
            processed.update(block.id for block in section_blocks)
            chunks.extend(
                self._split_section(
                    document,
                    section,
                    section_blocks,
                    len(chunks),
                    section_path=section_paths.get(section.id, ()),
                )
            )

        remaining = [
            block
            for block in document.blocks
            if block.id not in processed and block.text.strip() and _is_indexable_block(block)
        ]
        if remaining:
            fallback = DocumentSection(
                id="unlinked-blocks",
                title=document.title,
                block_ids=[block.id for block in remaining],
            )
            chunks.extend(
                self._split_section(
                    document,
                    fallback,
                    remaining,
                    len(chunks),
                    section_path=(document.title,),
                )
            )
        return tuple(chunks)

    def _split_section(
        self,
        document: LogicalDocument,
        section: DocumentSection,
        blocks: list[DocumentBlock],
        index_start: int,
        *,
        section_path: tuple[str, ...],
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        text_blocks: list[DocumentBlock] = []

        def flush_text() -> None:
            if not text_blocks:
                return
            units = [(block.text.strip(), block.page, block.id) for block in text_blocks]
            for text, page, block_ids in _pack_structural_units(
                units,
                target_tokens=self.config.chunk_size,
                overlap_tokens=self.config.overlap,
            ):
                chunks.append(
                    self._chunk(
                        document=document,
                        index=index_start + len(chunks),
                        text=text,
                        offset_start=max(document.text.find(text), 0),
                        page_number=page,
                        section_id=section.id,
                        heading=section.title,
                        block_type=BlockType.PARAGRAPH,
                        extra_metadata={
                            "source_block_ids": ",".join(block_ids),
                            "overlap_tokens": self.config.overlap,
                            "table_atomic": False,
                            "section_path": list(section_path),
                        },
                    )
                )
            text_blocks.clear()

        for block in blocks:
            if block.block_type == BlockType.TABLE:
                flush_text()
                chunks.append(
                    self._chunk(
                        document=document,
                        index=index_start + len(chunks),
                        text=block.text,
                        offset_start=max(document.text.find(block.text), 0),
                        page_number=block.page,
                        section_id=section.id,
                        heading=section.title,
                        block_type=BlockType.TABLE,
                        extra_metadata={
                            "source_block_ids": block.id,
                            "overlap_tokens": 0,
                            "table_atomic": True,
                            "table_location": block.metadata.get("location"),
                            "section_path": list(section_path),
                        },
                    )
                )
            else:
                text_blocks.append(block)
        flush_text()
        return chunks

    def _chunk(
        self,
        *,
        document: LogicalDocument,
        index: int,
        text: str,
        offset_start: int,
        page_number: int | None,
        section_id: str | None,
        heading: str | None,
        block_type: BlockType,
        extra_metadata: dict[str, object],
    ) -> Chunk:
        normalized_text = text.strip()
        now = datetime.now(UTC)
        config_checksum = self.config.checksum(self.name)
        content_checksum = sha256(normalized_text.encode("utf-8")).hexdigest()[:12]
        metadata: dict[str, object] = {
            "document_id": document.id,
            "document_version": document.version,
            "chunk_index": index,
            "page": page_number,
            "section": section_id,
            "heading": heading,
            "language": document.language,
            "block_type": block_type,
            "token_count": _estimate_tokens(normalized_text),
            "character_count": len(normalized_text),
            "parser_version": document.parser_info.parser_version,
            "strategy": self.name,
            "strategy_version": self.version,
            "chunk_version": CHUNK_VERSION,
            "metadata_version": METADATA_VERSION,
            "config_checksum": config_checksum,
            "content_checksum": content_checksum,
        }
        metadata.update(extra_metadata)
        raw_section_path = metadata.get("section_path")
        if isinstance(raw_section_path, str):
            section_path = tuple(
                item.strip() for item in raw_section_path.split(">") if item.strip()
            )
        elif isinstance(raw_section_path, Sequence) and not isinstance(raw_section_path, bytes):
            section_path = tuple(
                str(item).strip() for item in raw_section_path if str(item).strip()
            )
        else:
            section_path = ()
        context = ChunkContext(
            title=document.title,
            document_type=str(document.document_type),
            section_title=heading,
            section_path=section_path,
            content_kind=str(block_type),
            table_header=(
                str(metadata["table_header"]).strip() if metadata.get("table_header") else None
            ),
        )
        retrieval_metadata = metadata.get("retrieval_metadata")
        retrieval_values = dict(retrieval_metadata) if isinstance(retrieval_metadata, dict) else {}
        retrieval_values.update(context.as_retrieval_metadata())
        metadata["retrieval_metadata"] = retrieval_values
        metadata["embedding_text"] = build_embedding_text(normalized_text, context)
        metadata["search_text"] = build_search_text(normalized_text, context)
        return Chunk(
            id=(
                f"{document.id}:v{document.version}:{self.name}:{self.version}:"
                f"{config_checksum[:16]}:{index}:{content_checksum}"
            ),
            document_id=document.id,
            page_number=page_number,
            section_id=section_id,
            heading=heading,
            parent_chunk=None,
            children=(),
            text=normalized_text,
            offset_start=offset_start,
            offset_end=offset_start + len(normalized_text),
            token_count=_estimate_tokens(normalized_text),
            character_count=len(normalized_text),
            language=document.language,
            metadata=metadata,
            strategy_name=self.name,
            strategy_version=self.version,
            chunk_version=CHUNK_VERSION,
            confidence=0.9,
            created_at=now,
            updated_at=now,
        )


class ContentAwareChunkStrategy(StructureAwareRecursiveChunkStrategy):
    """Content-aware chunking with table row groups and embedding text context."""

    name = "content_aware"
    version = "1.0"

    def _split_section(
        self,
        document: LogicalDocument,
        section: DocumentSection,
        blocks: list[DocumentBlock],
        index_start: int,
        *,
        section_path: tuple[str, ...],
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        text_blocks: list[DocumentBlock] = []

        def flush_text() -> None:
            if not text_blocks:
                return
            tokens_by_block_id = {block.id: _estimate_tokens(block.text) for block in text_blocks}
            units = [(block.text.strip(), block.page, block.id) for block in text_blocks]
            for text, page, block_ids in _pack_content_aware_text_units(
                units,
                target_tokens=self.config.chunk_size,
                overlap_tokens=self.config.overlap,
            ):
                chunks.append(
                    self._chunk(
                        document=document,
                        index=index_start + len(chunks),
                        text=text,
                        offset_start=max(document.text.find(text), 0),
                        page_number=page,
                        section_id=section.id,
                        heading=section.title,
                        block_type=BlockType.PARAGRAPH,
                        extra_metadata={
                            "source_block_ids": ",".join(block_ids),
                            "overlap_tokens": (
                                self.config.overlap
                                if (
                                    len(block_ids) == 1
                                    and tokens_by_block_id.get(block_ids[0], 0)
                                    > self.config.chunk_size
                                )
                                else 0
                            ),
                            "table_atomic": False,
                            "canonical_content": text,
                            "section_path": list(section_path),
                            "retrieval_metadata": {
                                "content_kind": BlockType.PARAGRAPH,
                                "embedding_context": "document_section",
                            },
                        },
                    )
                )
            text_blocks.clear()

        for block in blocks:
            if block.block_type == BlockType.TABLE:
                flush_text()
                chunks.extend(
                    self._split_table_block(
                        document=document,
                        section=section,
                        block=block,
                        index_start=index_start + len(chunks),
                        section_path=section_path,
                    )
                )
            else:
                text_blocks.append(block)
        flush_text()
        return chunks

    def _split_table_block(
        self,
        *,
        document: LogicalDocument,
        section: DocumentSection,
        block: DocumentBlock,
        index_start: int,
        section_path: tuple[str, ...],
    ) -> list[Chunk]:
        rows = _table_rows(block.text)
        header = _table_header(block, rows)
        header_lines = _table_header_lines(block, rows, header)
        data_rows = _table_data_rows(rows, header)
        token_count = _estimate_tokens(block.text)
        if not rows or token_count <= self.config.table_atomic_max_tokens or len(rows) <= 2:
            return [
                self._chunk(
                    document=document,
                    index=index_start,
                    text=block.text,
                    offset_start=max(document.text.find(block.text), 0),
                    page_number=block.page,
                    section_id=section.id,
                    heading=section.title,
                    block_type=BlockType.TABLE,
                    extra_metadata={
                        "source_block_ids": block.id,
                        "overlap_tokens": 0,
                        "table_atomic": True,
                        "table_data_row_start_ordinal": 0,
                        "table_data_row_end_ordinal": max(len(data_rows) - 1, 0),
                        "table_location": block.metadata.get("location"),
                        "table_header": header,
                        "canonical_content": block.text,
                        "section_path": list(section_path),
                        "retrieval_metadata": {
                            "content_kind": BlockType.TABLE,
                            "embedding_context": "document_section_table_header",
                        },
                    },
                )
            ]

        chunks: list[Chunk] = []
        next_row_ordinal = 0
        for group_index, group_rows in enumerate(
            _table_row_groups(
                rows,
                header=header,
                target_tokens=self.config.table_row_group_target_tokens,
            ),
            start=1,
        ):
            # Every independently retrieved row group must retain its column
            # meaning. Repeating only the table header is structural context,
            # not overlap between source data rows.
            group_text = "\n".join([*header_lines, *group_rows])
            row_start_ordinal = next_row_ordinal
            row_end_ordinal = row_start_ordinal + len(group_rows) - 1
            next_row_ordinal = row_end_ordinal + 1
            chunks.append(
                self._chunk(
                    document=document,
                    index=index_start + len(chunks),
                    text=group_text,
                    offset_start=max(document.text.find(group_text), 0),
                    page_number=block.page,
                    section_id=section.id,
                    heading=section.title,
                    block_type=BlockType.TABLE,
                    extra_metadata={
                        "source_block_ids": block.id,
                        "overlap_tokens": 0,
                        "table_atomic": False,
                        "table_row_group": True,
                        "table_row_group_index": group_index,
                        "table_data_row_start_ordinal": row_start_ordinal,
                        "table_data_row_end_ordinal": row_end_ordinal,
                        "table_location": block.metadata.get("location"),
                        "table_header": header,
                        "table_header_repeated": bool(header_lines),
                        "canonical_content": group_text,
                        "section_path": list(section_path),
                        "retrieval_metadata": {
                            "content_kind": BlockType.TABLE,
                            "embedding_context": "document_section_table_header",
                            "table_row_group_index": group_index,
                        },
                    },
                )
            )
        return chunks


@dataclass(frozen=True)
class _OrderedSection:
    section: DocumentSection
    path: tuple[str, ...]
    parent_id: str | None


class ParentChildStructureChunkStrategy(ContentAwareChunkStrategy):
    """Non-overlapping structural children backed by exact section parents.

    Parent content is materialized once, on the first child in the parent, so
    persistence can restore the complete section without duplicating a large
    JSON value on every vector row. Every child carries the stable parent id
    and its ordinal within that parent.
    """

    name = "parent_child_structure"
    version = "1.0"
    parent_context_version = "section-parent-v1"

    def __init__(self, config: StrategyConfig | None = None) -> None:
        effective = config or StrategyConfig()
        # A stale CHUNK_OVERLAP value must never weaken this strategy's hard
        # no-overlap contract.
        super().__init__(replace(effective, overlap=0))

    def split(self, document: LogicalDocument) -> tuple[Chunk, ...]:
        block_by_id = {block.id: block for block in document.blocks}
        ordered_sections = _ordered_sections(document.sections)
        if not ordered_sections:
            ordered_sections = [
                _OrderedSection(
                    section=DocumentSection(
                        id="document",
                        title=document.title,
                        block_ids=[block.id for block in document.blocks],
                    ),
                    path=(document.title,),
                    parent_id=None,
                )
            ]

        section_by_id = {context.section.id: context for context in ordered_sections}
        partition_by_section = _parent_partition_by_section(ordered_sections)
        processed: set[str] = set()
        raw_chunks: list[tuple[Chunk, str]] = []
        parent_blocks: dict[str, list[DocumentBlock]] = {}
        parent_sections: dict[str, _OrderedSection] = {}

        for context in ordered_sections:
            section = context.section
            partition_section_id = partition_by_section[section.id]
            parent_sections.setdefault(
                partition_section_id,
                section_by_id[partition_section_id],
            )
            section_blocks = [
                block_by_id[block_id]
                for block_id in section.block_ids
                if (
                    block_id in block_by_id
                    and block_id not in processed
                    and block_by_id[block_id].text.strip()
                    and _is_indexable_block(block_by_id[block_id])
                )
            ]
            processed.update(block.id for block in section_blocks)
            parent_blocks.setdefault(partition_section_id, []).extend(section_blocks)
            section_chunks = self._split_section(
                document,
                section,
                section_blocks,
                len(raw_chunks),
                section_path=context.path,
            )
            raw_chunks.extend((chunk, partition_section_id) for chunk in section_chunks)

        remaining = [
            block
            for block in document.blocks
            if block.id not in processed and block.text.strip() and _is_indexable_block(block)
        ]
        if remaining:
            fallback = DocumentSection(
                id="unlinked-blocks",
                title=document.title,
                block_ids=[block.id for block in remaining],
            )
            context = _OrderedSection(
                section=fallback,
                path=(document.title,),
                parent_id=None,
            )
            parent_sections[fallback.id] = context
            parent_blocks[fallback.id] = remaining
            fallback_chunks = self._split_section(
                document,
                fallback,
                remaining,
                len(raw_chunks),
                section_path=context.path,
            )
            raw_chunks.extend((chunk, fallback.id) for chunk in fallback_chunks)

        chunks_by_parent: dict[str, list[Chunk]] = {}
        for chunk, partition_section_id in raw_chunks:
            chunks_by_parent.setdefault(partition_section_id, []).append(chunk)

        annotated: list[Chunk] = []
        for partition_section_id, group in chunks_by_parent.items():
            context = parent_sections[partition_section_id]
            blocks = parent_blocks.get(partition_section_id, [])
            parent_content = "\n\n".join(
                block.text.strip() for block in blocks if block.text.strip()
            )
            parent_checksum = sha256(parent_content.encode("utf-8")).hexdigest()
            parent_id = _parent_chunk_id(
                document,
                context,
                blocks,
                config_checksum=self.config.checksum(self.name),
            )
            page_values = [block.page for block in blocks if block.page is not None]
            holder_chunk_id = group[0].id
            for child_index, chunk in enumerate(group):
                metadata = dict(chunk.metadata)
                metadata.update(
                    {
                        "node_type": "child",
                        "parent_chunk_id": parent_id,
                        "parent_context_holder_source_chunk_id": holder_chunk_id,
                        "parent_context_version": self.parent_context_version,
                        "parent_section_id": context.section.id,
                        "parent_section_title": context.section.title,
                        "parent_section_path": list(context.path),
                        "parent_child_index": child_index,
                        "parent_child_count": len(group),
                        "parent_token_count": _estimate_tokens(parent_content),
                        "parent_content_checksum": parent_checksum,
                        "overlap_tokens": 0,
                    }
                )
                if child_index == 0:
                    metadata["parent_context"] = {
                        "content": parent_content,
                        "content_checksum": parent_checksum,
                        "token_count": _estimate_tokens(parent_content),
                        "source_block_ids": [block.id for block in blocks],
                        "page_start": min(page_values) if page_values else None,
                        "page_end": max(page_values) if page_values else None,
                        "section_id": context.section.id,
                        "section_title": context.section.title,
                        "section_path": list(context.path),
                    }
                annotated.append(
                    replace(
                        chunk,
                        parent_chunk=parent_id,
                        metadata=metadata,
                    )
                )
        return tuple(annotated)


def _ordered_sections(sections: Iterable[DocumentSection]) -> list[_OrderedSection]:
    """Flatten section input while restoring hierarchy from heading levels."""

    flattened = _flatten_sections(sections)
    ordered: list[_OrderedSection] = []
    stack: list[_OrderedSection] = []
    for section in flattened:
        while stack and stack[-1].section.level >= section.level:
            stack.pop()
        title = " ".join((section.title or "").split()).strip()
        path = (*stack[-1].path, title) if stack and title else stack[-1].path if stack else ()
        if not stack and title:
            path = (title,)
        context = _OrderedSection(
            section=section,
            path=path,
            parent_id=stack[-1].section.id if stack else None,
        )
        ordered.append(context)
        stack.append(context)
    return ordered


def _parent_partition_by_section(
    sections: Sequence[_OrderedSection],
) -> dict[str, str]:
    """Choose non-overlapping retrieval parents from the heading hierarchy.

    Multiple root headings each become one parent.  When the document has one
    wrapper/title root, each direct child becomes a parent and the root's own
    preamble remains a small separate parent.  This avoids turning a common
    ``# Document title`` wrapper into one giant retrieval parent.
    """

    by_id = {context.section.id: context for context in sections}
    roots = [context for context in sections if context.parent_id is None]
    root_ids = {context.section.id for context in roots}
    use_direct_children = len(roots) == 1 and any(
        context.parent_id == roots[0].section.id for context in sections
    )

    partitions: dict[str, str] = {}
    for context in sections:
        current = context
        lineage = [current]
        while current.parent_id is not None:
            current = by_id[current.parent_id]
            lineage.append(current)
        root = lineage[-1]
        if not use_direct_children or context.section.id in root_ids:
            partitions[context.section.id] = root.section.id
            continue
        direct_child = next(
            item for item in reversed(lineage[:-1]) if item.parent_id == root.section.id
        )
        partitions[context.section.id] = direct_child.section.id
    return partitions


def _parent_chunk_id(
    document: LogicalDocument,
    context: _OrderedSection,
    blocks: Sequence[DocumentBlock],
    *,
    config_checksum: str,
) -> str:
    identity = "|".join(
        (
            document.id,
            str(document.version),
            context.section.id,
            ">".join(context.path),
            ",".join(block.id for block in blocks),
            config_checksum,
        )
    )
    return (
        f"{document.id}:v{document.version}:parent:{config_checksum[:16]}:"
        f"{sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    )


def _estimate_tokens(text: str) -> int:
    return len([token for token in text.split() if token])


def _is_indexable_block(block: DocumentBlock) -> bool:
    return block.metadata.get("indexable", True) is not False


def _pack_structural_units(
    units: list[tuple[str, int | None, str]],
    *,
    target_tokens: int,
    overlap_tokens: int,
) -> list[tuple[str, int | None, tuple[str, ...]]]:
    stream_parts: list[str] = []
    stream_length = 0
    token_records: list[tuple[str, int | None, str, int, int]] = []
    paragraph_boundaries: set[int] = set()
    sentence_boundaries: set[int] = set()
    for text, page, block_id in units:
        if not text.split():
            continue
        if stream_parts:
            stream_parts.append("\n\n")
            stream_length += 2
        unit_start = stream_length
        stream_parts.append(text)
        stream_length += len(text)
        matches = list(re.finditer(r"\S+", text))
        unit_token_start = len(token_records)
        token_records.extend(
            (
                match.group(0),
                page,
                block_id,
                unit_start + match.start(),
                unit_start + match.end(),
            )
            for match in matches
        )
        paragraph_boundaries.add(len(token_records))
        for token_index, match in enumerate(matches, start=unit_token_start + 1):
            if (
                token_index < len(token_records)
                and _SENTENCE_TERMINATOR_PATTERN.search(match.group(0))
            ):
                sentence_boundaries.add(token_index)

    source_stream = "".join(stream_parts)
    ordered_paragraph_boundaries = sorted(paragraph_boundaries)
    ordered_sentence_boundaries = sorted(sentence_boundaries)
    packed: list[tuple[str, int | None, tuple[str, ...]]] = []
    cursor = 0
    total = len(token_records)
    while cursor < total:
        target_end = min(cursor + target_tokens, total)
        end = target_end
        if target_end < total:
            minimum_preferred = cursor + max(
                target_tokens // 2,
                overlap_tokens + 1,
            )
            paragraph_boundary = _last_boundary(
                ordered_paragraph_boundaries,
                target_end,
                minimum_preferred,
            )
            # A complete sentence is a stronger boundary than target fullness.
            # Allow a short chunk when needed instead of cutting the following
            # sentence in half. A hard token cut remains the safe fallback when
            # one sentence alone is longer than the configured chunk size.
            sentence_boundary = _last_boundary(
                ordered_sentence_boundaries,
                target_end,
                cursor + overlap_tokens + 1,
            )
            end = paragraph_boundary or sentence_boundary or target_end
        window = token_records[cursor:end]
        packed.append(
            (
                source_stream[window[0][3] : window[-1][4]],
                window[0][1],
                tuple(dict.fromkeys(record[2] for record in window)),
            )
        )
        if end >= total:
            break
        cursor = end - overlap_tokens
    return packed


def _pack_content_aware_text_units(
    units: list[tuple[str, int | None, str]],
    *,
    target_tokens: int,
    overlap_tokens: int,
) -> list[tuple[str, int | None, tuple[str, ...]]]:
    packed: list[tuple[str, int | None, tuple[str, ...]]] = []
    current: list[tuple[str, int | None, str]] = []
    current_tokens = 0

    def flush_current() -> None:
        nonlocal current_tokens
        if not current:
            return
        text = "\n\n".join(item[0] for item in current)
        packed.append(
            (
                text,
                current[0][1],
                tuple(dict.fromkeys(item[2] for item in current)),
            )
        )
        current.clear()
        current_tokens = 0

    for text, page, block_id in units:
        token_count = _estimate_tokens(text)
        if token_count == 0:
            continue
        if token_count > target_tokens:
            flush_current()
            packed.extend(
                _pack_structural_units(
                    [(text, page, block_id)],
                    target_tokens=target_tokens,
                    overlap_tokens=overlap_tokens,
                )
            )
            continue
        if current and current_tokens + token_count > target_tokens:
            flush_current()
        current.append((text, page, block_id))
        current_tokens += token_count
    flush_current()
    return packed


def _table_rows(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _table_header(block: DocumentBlock, rows: list[str]) -> str | None:
    metadata_header = block.metadata.get("header")
    if isinstance(metadata_header, list) and metadata_header:
        values = [str(value).strip() for value in metadata_header if str(value).strip()]
        if values:
            return " | ".join(values)
    return rows[0] if rows else None


def _table_header_lines(
    block: DocumentBlock,
    rows: list[str],
    header: str | None,
) -> tuple[str, ...]:
    if len(rows) >= 2 and _is_markdown_separator_row(rows[1]):
        return (rows[0], rows[1])
    if rows and header and _table_cells(rows[0]) == _table_cells(header):
        return (rows[0],)
    metadata_header = block.metadata.get("header")
    if isinstance(metadata_header, list):
        values = [str(value).strip() for value in metadata_header if str(value).strip()]
        if values:
            return (f"| {' | '.join(values)} |",)
    return (header,) if header else ()


def _table_data_rows(rows: list[str], header: str | None) -> list[str]:
    """Return all data rows whether the parser embeds or detaches the header."""

    if not rows or not header:
        return rows
    offset = 1 if _table_cells(rows[0]) == _table_cells(header) else 0
    if len(rows) > offset and _is_markdown_separator_row(rows[offset]):
        offset += 1
    return rows[offset:]


def _table_cells(value: str) -> tuple[str, ...]:
    return tuple(
        part.strip().casefold() for part in value.strip().strip("|").split("|") if part.strip()
    )


def _is_markdown_separator_row(value: str) -> bool:
    cells = [part.strip() for part in value.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _table_row_groups(
    rows: list[str],
    *,
    header: str | None,
    target_tokens: int,
) -> list[list[str]]:
    data_rows = _table_data_rows(rows, header)
    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for row in data_rows:
        row_tokens = _estimate_tokens(row)
        if current and current_tokens + row_tokens > target_tokens:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(row)
        current_tokens += row_tokens
    if current:
        groups.append(current)
    return groups


def _last_boundary(
    boundaries: list[int],
    target_end: int,
    minimum: int,
) -> int | None:
    index = bisect_right(boundaries, target_end) - 1
    if index < 0 or boundaries[index] < minimum:
        return None
    return boundaries[index]


def _section_paths(
    sections: Iterable[DocumentSection],
    prefix: tuple[str, ...] = (),
) -> dict[str, tuple[str, ...]]:
    paths: dict[str, tuple[str, ...]] = {}
    for section in sections:
        title = " ".join((section.title or "").split()).strip()
        path = (*prefix, title) if title else prefix
        paths[section.id] = path
        paths.update(_section_paths(section.children, path))
    return paths


def _flatten_sections(
    sections: Iterable[DocumentSection],
) -> list[DocumentSection]:
    values: list[DocumentSection] = []
    for section in sections:
        values.append(section)
        values.extend(_flatten_sections(section.children))
    return values


__all__ = [
    "ContentAwareChunkStrategy",
    "ParentChildStructureChunkStrategy",
    "StrategyConfig",
    "StructureAwareRecursiveChunkStrategy",
]
