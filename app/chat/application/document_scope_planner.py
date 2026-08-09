"""Conservative pre-retrieval routing from authoritative document identity."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from uuid import UUID

from app.documents.domain.models import Document

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")
_TOKEN = re.compile(r"[a-z0-9]+")
_GENERIC_TOKENS = frozenset(
    {
        "bao",
        "cao",
        "copy",
        "demo",
        "doc",
        "document",
        "file",
        "kb",
        "tai",
        "lieu",
        "txt",
        "vinhomes",
    }
)


def normalize_document_identity(value: str) -> str:
    """Normalize filename/query text without inventing aliases."""

    camel_split = _CAMEL_BOUNDARY.sub(" ", value)
    decomposed = unicodedata.normalize("NFKD", camel_split)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(_TOKEN.findall(ascii_text.casefold()))


def _identity_tokens(filename: str) -> frozenset[str]:
    tokens = normalize_document_identity(PurePath(filename).stem).split()
    return frozenset(
        token
        for token in tokens
        if token not in _GENERIC_TOKENS and (len(token) >= 3 or token.isdigit())
    )


@dataclass(frozen=True)
class DocumentScopePlan:
    """Auditable decision produced before sparse/dense retrieval."""

    applied: bool
    reason: str
    source_fields: tuple[str, ...]
    before_document_ids: tuple[UUID, ...]
    after_document_ids: tuple[UUID, ...]
    matched_titles: tuple[str, ...] = ()
    matched_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeterministicDocumentScopePlanner:
    """Narrow only when a real filename is uniquely identified; otherwise fail open."""

    min_distinctive_tokens: int = 1

    def plan(
        self,
        query: str,
        documents: Sequence[Document],
        allowed_document_ids: tuple[UUID, ...],
    ) -> DocumentScopePlan:
        before = tuple(sorted(set(allowed_document_ids), key=str))
        allowed = set(before)
        query_tokens = frozenset(normalize_document_identity(query).split())
        matches: list[tuple[Document, frozenset[str]]] = []

        for document in documents:
            if document.id not in allowed:
                continue
            tokens = _identity_tokens(document.original_filename)
            if len(tokens) >= self.min_distinctive_tokens and tokens.issubset(query_tokens):
                matches.append((document, tokens))

        if len(matches) != 1:
            return DocumentScopePlan(
                applied=False,
                reason=("no_unique_filename_match" if not matches else "ambiguous_filename_match"),
                source_fields=("documents.id", "documents.original_filename"),
                before_document_ids=before,
                after_document_ids=before,
                matched_titles=tuple(sorted(item[0].original_filename for item in matches)),
                matched_tokens=tuple(
                    sorted({token for _, tokens in matches for token in tokens})
                ),
            )

        document, tokens = matches[0]
        return DocumentScopePlan(
            applied=True,
            reason="unique_authoritative_filename_match",
            source_fields=("documents.id", "documents.original_filename"),
            before_document_ids=before,
            after_document_ids=(document.id,),
            matched_titles=(document.original_filename,),
            matched_tokens=tuple(sorted(tokens)),
        )


__all__ = [
    "DeterministicDocumentScopePlanner",
    "DocumentScopePlan",
    "normalize_document_identity",
]
