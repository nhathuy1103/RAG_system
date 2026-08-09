"""Deterministic semantic projections shared by ingestion and sparse retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

CONTEXTUAL_TEXT_VERSION = "contextual-text-v4"

_FILE_EXTENSION_PATTERN = re.compile(
    r"(?i)\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|jsonl?)$"
)
_COPY_SUFFIX_PATTERN = re.compile(r"(?i)\s*-\s*copy(?:\s*\(\d+\))?$")
_PAGE_SECTION_PATTERN = re.compile(
    r"(?i)^(?:page|trang)\s*(?:number\s*)?\d+(?:\s*(?:/|of)\s*\d+)?$"
)
_GENERIC_SECTION_VALUES = frozenset({"docx", "pdf", "document", "unknown", "n/a"})


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _string_tuple(value: object | None) -> tuple[str, ...]:
    if isinstance(value, str):
        values: Iterable[object] = value.split(">")
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        values = value
    else:
        return ()
    return tuple(text for item in values if (text := _clean(item)) is not None)


def _semantic_document_title(value: object | None) -> str | None:
    title = _clean(value)
    if title is None:
        return None
    title = title.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    title = _FILE_EXTENSION_PATTERN.sub("", title)
    title = _COPY_SUFFIX_PATTERN.sub("", title)
    return _clean(title.replace("_", " "))


def _semantic_section(value: object | None) -> str | None:
    section = _clean(value)
    if section is None:
        return None
    if section.casefold() in _GENERIC_SECTION_VALUES or _PAGE_SECTION_PATTERN.fullmatch(section):
        return None
    return section


@dataclass(frozen=True, slots=True)
class ChunkContext:
    """Short, human-readable context that remains meaningful after chunking."""

    title: str | None = None
    document_type: str | None = None
    section_title: str | None = None
    section_path: tuple[str, ...] = ()
    content_kind: str | None = None
    table_header: str | None = None
    keyword_aliases: tuple[str, ...] = ()
    contextual_summary: str | None = None
    contextual_search_terms: tuple[str, ...] = ()

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, object]) -> ChunkContext:
        nested = metadata.get("retrieval_metadata")
        retrieval = nested if isinstance(nested, Mapping) else {}

        def value(key: str) -> object | None:
            direct = metadata.get(key)
            return direct if direct not in (None, "") else retrieval.get(key)

        return cls(
            title=_clean(value("title")),
            document_type=_clean(value("document_type")),
            section_title=_clean(value("section_title") or value("heading")),
            section_path=_string_tuple(value("section_path")),
            content_kind=_clean(value("content_kind") or value("block_type")),
            table_header=_clean(value("table_header")),
            keyword_aliases=_string_tuple(value("keyword_aliases")),
            contextual_summary=_clean(value("contextual_summary")),
            contextual_search_terms=_string_tuple(value("contextual_search_terms")),
        )

    @property
    def effective_section(self) -> str | None:
        semantic_path = tuple(
            section for value in self.section_path if (section := _semantic_section(value))
        )
        if semantic_path:
            return " > ".join(semantic_path)
        return _semantic_section(self.section_title)

    def as_retrieval_metadata(self) -> dict[str, object]:
        values: dict[str, object] = {}
        if title := _clean(self.title):
            values["title"] = title
        if (document_type := _clean(self.document_type)) and document_type != "unknown":
            values["document_type"] = document_type
        if section_title := _clean(self.section_title):
            values["section_title"] = section_title
        if self.section_path:
            values["section_path"] = list(self.section_path)
        if content_kind := _clean(self.content_kind):
            values["content_kind"] = content_kind
        if table_header := _clean(self.table_header):
            values["table_header"] = table_header
        if self.keyword_aliases:
            values["keyword_aliases"] = list(self.keyword_aliases)
        if contextual_summary := _clean(self.contextual_summary):
            values["contextual_summary"] = contextual_summary
        if self.contextual_search_terms:
            values["contextual_search_terms"] = list(self.contextual_search_terms)
        return values


def build_embedding_text(content: str, context: ChunkContext) -> str:
    """Prepend only stable semantic context; IDs, ACL, pages, and hashes stay out."""

    lines: list[str] = []
    if title := _semantic_document_title(context.title):
        lines.append(f"Document: {title}")
    if (document_type := _clean(context.document_type)) and document_type != "unknown":
        lines.append(f"Document type: {document_type}")
    if section := context.effective_section:
        lines.append(f"Section: {section}")
    if (content_kind := _clean(context.content_kind)) and content_kind != "paragraph":
        lines.append(f"Content type: {content_kind}")
    if table_header := _clean(context.table_header):
        lines.append(f"Table header: {table_header}")
    if contextual_summary := _clean(context.contextual_summary):
        lines.append(f"Context: {contextual_summary}")

    body = content.strip()
    return "\n".join([*lines, "", body]).strip() if lines else body


def build_search_text(content: str, context: ChunkContext) -> str:
    """Build a lexical projection with exact names, paths, headers, and aliases."""

    values: list[str] = []
    for candidate in (
        _semantic_document_title(context.title),
        context.document_type if context.document_type != "unknown" else None,
        context.effective_section,
        context.content_kind if context.content_kind != "paragraph" else None,
        context.table_header,
        *context.keyword_aliases,
        context.contextual_summary,
        *context.contextual_search_terms,
        content,
    ):
        if text := _clean(candidate):
            values.append(text)

    deduplicated: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(value)
    return "\n".join(deduplicated)


__all__ = [
    "CONTEXTUAL_TEXT_VERSION",
    "ChunkContext",
    "build_embedding_text",
    "build_search_text",
]
