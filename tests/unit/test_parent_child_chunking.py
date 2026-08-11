from __future__ import annotations

from app.pipeline.documents.adapters.parsers import MarkdownParser, ParserRegistry
from app.pipeline.documents.domain.parsed import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
)
from app.pipeline.documents.domain.source import DocumentSource
from app.pipeline.indexing.adapters.embedding_providers import LocalEmbeddingProvider
from app.pipeline.indexing.adapters.vector_indexes import PgVectorIndex, QdrantVectorIndex
from app.pipeline.indexing.application.chunker import (
    PARENT_CHILD_STRATEGY,
    Chunker,
    chunk_parsed_document,
)
from app.pipeline.indexing.application.pipeline import IngestionEmbeddingPipeline
from app.pipeline.indexing.domain.chunking_strategies import StrategyConfig


def test_parent_stops_at_section_end_and_children_never_overlap() -> None:
    parsed = MarkdownParser().parse(
        b"""# Knowledge Base

Document introduction.

## Part 1

w01 w02 w03 w04 w05 w06

### Part 1 details

w07 w08 w09 w10 w11 w12

## Part 2

z01 z02 z03 z04
"""
    )

    chunks = Chunker.parent_child_structure(chunk_size=4).chunk("doc-1", 1, parsed)
    part_one = [chunk for chunk in chunks if chunk.metadata["parent_section_title"] == "Part 1"]

    assert len(part_one) >= 3
    assert {chunk.parent_chunk_id for chunk in part_one} == {
        part_one[0].metadata["parent_chunk_id"]
    }
    assert [chunk.metadata["parent_child_index"] for chunk in part_one] == list(
        range(len(part_one))
    )
    assert all(chunk.metadata["overlap_tokens"] == 0 for chunk in chunks)

    holders = [chunk for chunk in part_one if "parent_context" in chunk.metadata]
    assert len(holders) == 1
    parent_content = holders[0].metadata["parent_context"]["content"]
    assert "Part 1" in parent_content
    assert "Part 1 details" in parent_content
    assert "w12" in parent_content
    assert "Part 2" not in parent_content
    assert "z01" not in parent_content

    child_text = " ".join(chunk.text for chunk in part_one)
    for ordinal in range(1, 13):
        assert child_text.split().count(f"w{ordinal:02d}") == 1


def test_oversized_text_cuts_at_complete_sentence_before_token_limit() -> None:
    parsed = MarkdownParser().parse(
        "# Chính sách\n\nMột hai. Ba bốn năm sáu bảy!".encode()
    )

    chunks = Chunker.parent_child_structure(chunk_size=6).chunk(
        "doc-sentence-boundary",
        1,
        parsed,
    )
    paragraph_chunks = [chunk.text for chunk in chunks if not chunk.text.startswith("#")]

    assert paragraph_chunks == ["Một hai.", "Ba bốn năm sáu bảy!"]
    assert all(chunk.metadata["overlap_tokens"] == 0 for chunk in chunks)


def test_oversized_single_sentence_uses_token_fallback_without_losing_words() -> None:
    parsed = MarkdownParser().parse(b"# Policy\n\none two three four five six seven")

    chunks = Chunker.parent_child_structure(chunk_size=4).chunk(
        "doc-long-sentence",
        1,
        parsed,
    )
    paragraph_text = " ".join(
        chunk.text for chunk in chunks if not chunk.text.startswith("#")
    )

    assert paragraph_text.split() == ["one", "two", "three", "four", "five", "six", "seven"]


def test_large_table_children_repeat_header_without_repeating_data_rows() -> None:
    table_text = "| Project | Price |\n| --- | --- |\n| Alpha | 10 |\n| Beta | 20 |\n| Gamma | 30 |"
    parsed = ParsedDocument(
        text=table_text,
        pages=[
            ParsedPage(
                page_number=1,
                text=table_text,
                elements=[
                    ParsedElement(
                        element_id="table-1",
                        block_type="table",
                        text=table_text,
                        page_number=1,
                        metadata={"header": ["Project", "Price"]},
                    )
                ],
            )
        ],
        sections=[
            ParsedSection(
                text=table_text,
                page_number=1,
                title="Prices",
                block_ids=["table-1"],
            )
        ],
        parser_name="fixture",
        parser_version="1.0",
        detected_language="en",
    )
    config = StrategyConfig(
        chunk_size=20,
        overlap=7,
        table_atomic_max_tokens=5,
        table_row_group_target_tokens=5,
    )

    chunks = chunk_parsed_document(
        "doc-table",
        1,
        parsed,
        config,
        strategy=PARENT_CHILD_STRATEGY,
    )

    assert len(chunks) == 3
    assert all(chunk.metadata["overlap_tokens"] == 0 for chunk in chunks)
    assert all(chunk.metadata["table_row_group"] is True for chunk in chunks)
    assert all(chunk.metadata["table_header_repeated"] is True for chunk in chunks)
    assert all(chunk.text.startswith("| Project | Price |\n| --- | --- |") for chunk in chunks)
    for project in ("Alpha", "Beta", "Gamma"):
        assert sum(project in chunk.text for chunk in chunks) == 1

    parent_context = chunks[0].metadata["parent_context"]
    assert parent_context["content"] == table_text
    assert all("parent_context" not in chunk.metadata for chunk in chunks[1:])


def test_parent_child_strategy_is_registered_and_forces_zero_overlap() -> None:
    parsed = MarkdownParser().parse(b"# One\n\na b c d e f")
    chunks = chunk_parsed_document(
        "doc-registered",
        1,
        parsed,
        StrategyConfig(chunk_size=3, overlap=2),
        strategy="parent_child_structure",
    )

    assert chunks
    assert {chunk.strategy for chunk in chunks} == {"parent_child_structure"}
    assert all(chunk.metadata["overlap_tokens"] == 0 for chunk in chunks)


def test_parent_metadata_survives_embedding_for_database_persistence() -> None:
    pipeline = IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(parsers=[MarkdownParser()]),
        chunker=Chunker.parent_child_structure(chunk_size=4),
        embedding_provider=LocalEmbeddingProvider(),
    )
    result = pipeline.run(
        DocumentSource(
            document_id="doc-persist-parent",
            owner_id="owner-1",
            tenant_id="tenant-1",
            title="policy.md",
            mime_type="text/markdown",
            content=b"# Part 1\n\na b c d e f",
        )
    )

    first = result.embedded_chunks[0]
    assert first.metadata["node_type"] == "child"
    assert first.metadata["parent_chunk_id"]
    assert first.metadata["parent_child_index"] == 0
    assert first.metadata["parent_context"]["content"].endswith("a b c d e f")

    qdrant_payload = QdrantVectorIndex._chunk_payload(first)
    assert qdrant_payload["metadata"]["parent_chunk_id"] == first.metadata["parent_chunk_id"]
    assert "parent_context" not in qdrant_payload["metadata"]

    postgres_row = PgVectorIndex._chunk_row(first)
    assert postgres_row["metadata"]["parent_context"] == first.metadata["parent_context"]
