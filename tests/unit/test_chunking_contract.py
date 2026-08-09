from __future__ import annotations

from app.pipeline.documents.domain.parsed import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
)
from app.pipeline.indexing.application.chunker import Chunker


def test_content_aware_chunker_keeps_embedding_context() -> None:
    parsed = ParsedDocument(
        text="Revenue\n2025 | 10\n2026 | 12",
        pages=[
            ParsedPage(
                page_number=1,
                text="Revenue\n2025 | 10\n2026 | 12",
                elements=[
                    ParsedElement(
                        element_id="table-1",
                        block_type="table",
                        text="2025 | 10\n2026 | 12",
                        page_number=1,
                        metadata={"header": ["year", "revenue"]},
                    )
                ],
            )
        ],
        sections=[
            ParsedSection(
                text="Revenue\n2025 | 10\n2026 | 12",
                page_number=1,
                title="Financials",
                block_ids=["table-1"],
            )
        ],
        parser_name="fixture",
        parser_version="1.0",
        detected_language="en",
    )

    chunks = Chunker.content_aware(chunk_size=32, overlap=4).chunk(
        "doc-1",
        1,
        parsed,
    )

    assert len(chunks) == 1
    assert chunks[0].metadata["table_atomic"] is True
    assert chunks[0].metadata["table_data_row_start_ordinal"] == 0
    assert chunks[0].metadata["table_data_row_end_ordinal"] == 1
    assert chunks[0].metadata["retrieval_metadata"]["content_kind"] == "table"
    assert "Document: FIXTURE" in chunks[0].embedding_text
    assert "Section: Financials" in chunks[0].embedding_text
    assert "Table header: year | revenue" in chunks[0].embedding_text
    assert "Page:" not in chunks[0].embedding_text
