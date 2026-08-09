"""Original-file preview blocks for duplicate/conflict review."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from pypdf import PdfReader

from app.knowledge_quality.application.analysis import strict_normalize_text
from app.knowledge_quality.domain.models import (
    RelationEvidenceBlock,
    RelationEvidenceChunkPair,
    RelationEvidenceDocument,
)

ReviewSide = Literal["source", "target"]

MAX_REVIEW_BLOCKS = 800
MAX_BLOCK_CHARACTERS = 2_000
MIN_MATCH_KEY_CHARACTERS = 8

_TOKEN_PATTERN = re.compile(r"[^\W_]+|\d+(?:[./-]\d+)*", re.UNICODE)
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)


@dataclass(frozen=True, slots=True)
class _DiffRow:
    kind: str
    source: str
    target: str


@dataclass(frozen=True, slots=True)
class _HighlightCandidate:
    key: str
    evidence_type: str
    confidence: float
    reason: str | None
    pair_index: int
    priority: int


def build_original_review_blocks(
    document: RelationEvidenceDocument,
    content: bytes,
    pairs: Sequence[RelationEvidenceChunkPair],
    *,
    side: ReviewSide,
) -> tuple[RelationEvidenceBlock, ...]:
    """Render source bytes into review blocks and annotate confident matches."""
    blocks = render_original_review_blocks(document, content)
    if not blocks:
        return ()
    return annotate_original_review_blocks(blocks, pairs, side=side)


def render_original_review_blocks(
    document: RelationEvidenceDocument,
    content: bytes,
) -> tuple[RelationEvidenceBlock, ...]:
    """Best-effort text/table preview generated from original object bytes."""
    extension = _extension(document.original_filename)
    mime_type = (document.mime_type or "").lower()
    if extension == "docx" or "wordprocessingml.document" in mime_type:
        return _docx_blocks(document, content)
    if extension == "pdf" or mime_type == "application/pdf":
        return _pdf_blocks(document, content)
    if extension == "csv" or "csv" in mime_type:
        return _csv_blocks(document, content)
    if extension in {"html", "htm"} or "html" in mime_type:
        return _html_blocks(document, content)
    if extension in {"txt", "md", "markdown"} or mime_type.startswith("text/"):
        return _text_blocks(document, content)
    return ()


def annotate_original_review_blocks(
    blocks: Sequence[RelationEvidenceBlock],
    pairs: Sequence[RelationEvidenceChunkPair],
    *,
    side: ReviewSide,
) -> tuple[RelationEvidenceBlock, ...]:
    """Map chunk-level evidence back to original-file preview blocks."""
    candidates = _highlight_candidates(pairs, side=side)
    if not candidates:
        return tuple(blocks)

    annotated: list[RelationEvidenceBlock] = []
    for block in blocks:
        block_key = _match_key(" ".join(block.cells) if block.cells else block.text)
        candidate = _best_candidate(block_key, candidates)
        if candidate is None:
            annotated.append(block)
            continue
        annotated.append(
            replace(
                block,
                highlight_type=candidate.evidence_type,
                matched_pair_index=candidate.pair_index,
                confidence=candidate.confidence,
                reason=candidate.reason,
            )
        )
    return tuple(annotated)


def _docx_blocks(
    document: RelationEvidenceDocument,
    content: bytes,
) -> tuple[RelationEvidenceBlock, ...]:
    if not zipfile.is_zipfile(io.BytesIO(content)):
        return ()
    doc = DocxDocument(io.BytesIO(content))
    blocks: list[RelationEvidenceBlock] = []
    for item in doc.iter_inner_content():
        if len(blocks) >= MAX_REVIEW_BLOCKS:
            break
        if isinstance(item, DocxParagraph):
            text = _clean_text(item.text)
            if not text:
                continue
            style_name = str(getattr(item.style, "name", "") or "")
            block_type = (
                "heading"
                if re.fullmatch(r"Heading\s+[1-6]", style_name, re.IGNORECASE)
                else "paragraph"
            )
            blocks.append(
                _block(
                    document.id,
                    len(blocks),
                    block_type=block_type,
                    text=text,
                    page_number=1,
                )
            )
            continue
        if isinstance(item, DocxTable):
            for row in item.rows:
                if len(blocks) >= MAX_REVIEW_BLOCKS:
                    break
                cells = tuple(_clean_text(cell.text) for cell in row.cells)
                if not any(cells):
                    continue
                blocks.append(
                    _block(
                        document.id,
                        len(blocks),
                        block_type="table_row",
                        text=" ".join(cell for cell in cells if cell),
                        page_number=1,
                        cells=cells,
                    )
                )
    return tuple(blocks)


def _pdf_blocks(
    document: RelationEvidenceDocument,
    content: bytes,
) -> tuple[RelationEvidenceBlock, ...]:
    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return ()

    blocks: list[RelationEvidenceBlock] = []
    for page_number, page in enumerate(reader.pages, start=1):
        if len(blocks) >= MAX_REVIEW_BLOCKS:
            break
        for line in (page.extract_text() or "").splitlines():
            text = _clean_text(line)
            if not text:
                continue
            blocks.append(
                _block(
                    document.id,
                    len(blocks),
                    block_type="line",
                    text=text,
                    page_number=page_number,
                )
            )
            if len(blocks) >= MAX_REVIEW_BLOCKS:
                break
    return tuple(blocks)


def _csv_blocks(
    document: RelationEvidenceDocument,
    content: bytes,
) -> tuple[RelationEvidenceBlock, ...]:
    decoded = _decode_text(content)
    reader = csv.reader(io.StringIO(decoded, newline=""))
    blocks: list[RelationEvidenceBlock] = []
    for row in reader:
        if len(blocks) >= MAX_REVIEW_BLOCKS:
            break
        cells = tuple(_clean_text(cell) for cell in row)
        if not any(cells):
            continue
        blocks.append(
            _block(
                document.id,
                len(blocks),
                block_type="table_row",
                text=" ".join(cell for cell in cells if cell),
                page_number=1,
                cells=cells,
            )
        )
    return tuple(blocks)


def _html_blocks(
    document: RelationEvidenceDocument,
    content: bytes,
) -> tuple[RelationEvidenceBlock, ...]:
    soup = BeautifulSoup(_decode_text(content), "html.parser")
    for active in soup.find_all(["script", "style"]):
        active.decompose()

    blocks: list[RelationEvidenceBlock] = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr"]):
        if len(blocks) >= MAX_REVIEW_BLOCKS:
            break
        if node.name == "tr":
            cells = tuple(
                _clean_text(cell.get_text(" ", strip=True))
                for cell in node.find_all(["th", "td"], recursive=False)
            )
            if not any(cells):
                continue
            blocks.append(
                _block(
                    document.id,
                    len(blocks),
                    block_type="table_row",
                    text=" ".join(cell for cell in cells if cell),
                    page_number=1,
                    cells=cells,
                )
            )
            continue
        text = _clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        blocks.append(
            _block(
                document.id,
                len(blocks),
                block_type="heading" if node.name.startswith("h") else "paragraph",
                text=text,
                page_number=1,
            )
        )
    return tuple(blocks)


def _text_blocks(
    document: RelationEvidenceDocument,
    content: bytes,
) -> tuple[RelationEvidenceBlock, ...]:
    decoded = _decode_text(content)
    paragraphs = [_clean_text(part) for part in re.split(r"\n\s*\n", decoded)]
    paragraphs = [part for part in paragraphs if part]
    if len(paragraphs) <= 1:
        paragraphs = [_clean_text(line) for line in decoded.splitlines()]
        paragraphs = [line for line in paragraphs if line]
    return tuple(
        _block(
            document.id,
            index,
            block_type="paragraph",
            text=text,
            page_number=1,
        )
        for index, text in enumerate(paragraphs[:MAX_REVIEW_BLOCKS])
    )


def _highlight_candidates(
    pairs: Sequence[RelationEvidenceChunkPair],
    *,
    side: ReviewSide,
) -> tuple[_HighlightCandidate, ...]:
    candidates: list[_HighlightCandidate] = []
    for pair_index, pair in enumerate(pairs):
        chunk = pair.source_chunk if side == "source" else pair.target_chunk
        if chunk is None:
            continue
        for line in _highlight_lines(pair, side=side):
            key = _match_key(line)
            if not _usable_match_key(key):
                continue
            candidates.append(
                _HighlightCandidate(
                    key=key,
                    evidence_type=pair.evidence_type,
                    confidence=pair.confidence,
                    reason=pair.reason,
                    pair_index=pair_index,
                    priority=_highlight_priority(pair.evidence_type),
                )
            )
    return tuple(candidates)


def _highlight_lines(
    pair: RelationEvidenceChunkPair,
    *,
    side: ReviewSide,
) -> tuple[str, ...]:
    source_lines = _split_review_lines(
        pair.source_chunk.content if pair.source_chunk is not None else ""
    )
    target_lines = _split_review_lines(
        pair.target_chunk.content if pair.target_chunk is not None else ""
    )
    side_lines = source_lines if side == "source" else target_lines

    if pair.evidence_type in {"exact_content", "source_only", "target_only"}:
        return tuple(side_lines)

    changed: list[str] = []
    for row in _line_diff(source_lines, target_lines):
        text = row.source if side == "source" else row.target
        if row.kind != "same" and text:
            changed.append(text)
    if changed:
        return tuple(changed)
    return tuple(side_lines) if len(side_lines) == 1 else ()


def _line_diff(
    source_lines: Sequence[str],
    target_lines: Sequence[str],
) -> tuple[_DiffRow, ...]:
    dp = [[0 for _ in range(len(target_lines) + 1)] for _ in range(len(source_lines) + 1)]
    for i in range(len(source_lines) - 1, -1, -1):
        for j in range(len(target_lines) - 1, -1, -1):
            dp[i][j] = (
                dp[i + 1][j + 1] + 1
                if source_lines[i] == target_lines[j]
                else max(dp[i + 1][j], dp[i][j + 1])
            )

    rows: list[_DiffRow] = []
    i = 0
    j = 0
    while i < len(source_lines) or j < len(target_lines):
        if i < len(source_lines) and j < len(target_lines) and source_lines[i] == target_lines[j]:
            rows.append(_DiffRow("same", source_lines[i], target_lines[j]))
            i += 1
            j += 1
        elif j >= len(target_lines) or (i < len(source_lines) and dp[i + 1][j] >= dp[i][j + 1]):
            rows.append(_DiffRow("source_added", source_lines[i], ""))
            i += 1
        else:
            rows.append(_DiffRow("target_removed", "", target_lines[j]))
            j += 1
    return tuple(rows)


def _best_candidate(
    block_key: str,
    candidates: Sequence[_HighlightCandidate],
) -> _HighlightCandidate | None:
    if not _usable_match_key(block_key):
        return None
    matches = [candidate for candidate in candidates if _keys_match(block_key, candidate.key)]
    if not matches:
        return None
    return max(
        matches,
        key=lambda candidate: (
            candidate.priority,
            candidate.confidence,
            len(candidate.key),
        ),
    )


def _keys_match(block_key: str, candidate_key: str) -> bool:
    if block_key == candidate_key:
        return True
    if min(len(block_key), len(candidate_key)) < 12:
        return False
    return candidate_key in block_key or block_key in candidate_key


def _split_review_lines(text: str) -> tuple[str, ...]:
    return tuple(
        line for line in (_clean_text(part) for part in str(text or "").splitlines()) if line
    )


def _match_key(text: str) -> str:
    normalized = (
        unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).replace("\u00a0", " ").casefold()
    )
    normalized = normalized.replace("|", " ")
    return " ".join(_TOKEN_PATTERN.findall(normalized))


def _usable_match_key(key: str) -> bool:
    if len(key) < MIN_MATCH_KEY_CHARACTERS:
        return False
    return len(key.split()) >= 2


def _highlight_priority(evidence_type: str) -> int:
    if "conflict" in evidence_type:
        return 50
    if evidence_type == "source_only":
        return 45
    if evidence_type == "target_only":
        return 40
    if evidence_type in {"near_duplicate", "version_candidate", "version"}:
        return 30
    if evidence_type == "exact_content":
        return 10
    return 1


def _block(
    document_id: UUID,
    block_index: int,
    *,
    block_type: str,
    text: str,
    page_number: int | None,
    cells: Sequence[str] = (),
) -> RelationEvidenceBlock:
    return RelationEvidenceBlock(
        id=f"{document_id}:original:{block_index}",
        document_id=document_id,
        block_index=block_index,
        block_type=block_type,
        text=_truncate_text(text),
        page_number=page_number,
        cells=tuple(_truncate_text(cell) for cell in cells),
    )


def _clean_text(text: str) -> str:
    return strict_normalize_text(str(text or ""))


def _truncate_text(text: str) -> str:
    if len(text) <= MAX_BLOCK_CHARACTERS:
        return text
    return text[:MAX_BLOCK_CHARACTERS].rstrip() + "..."


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", maxsplit=1)[1].lower()


__all__ = [
    "annotate_original_review_blocks",
    "build_original_review_blocks",
    "render_original_review_blocks",
]
