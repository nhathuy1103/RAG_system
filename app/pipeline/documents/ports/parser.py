from __future__ import annotations

from typing import Protocol

from app.pipeline.documents.domain.parsed import ParsedDocument


class DocumentParser(Protocol):
    parser_name: str
    parser_version: str
    supported_extensions: tuple[str, ...]

    def supports(self, extension: str) -> bool: ...

    def validate(self, content: bytes) -> None: ...

    def parse(self, content: bytes) -> ParsedDocument: ...


class ParserCatalog(Protocol):
    def get_parser(self, filename: str) -> DocumentParser: ...

    def supports(self, filename: str) -> bool: ...

    @property
    def supported_extensions(self) -> tuple[str, ...]: ...


__all__ = ["DocumentParser", "ParserCatalog"]
