from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from app.pipeline.documents.adapters.parsers import ParserRegistry, TxtParser
from app.pipeline.documents.application.extraction_pipeline import (
    AdvancedExtractionPipeline,
    AdvancedExtractionPipelineConfig,
)
from app.pipeline.documents.domain.parsed import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
    ParsedTable,
)
from app.pipeline.documents.domain.source import DocumentSource
from app.pipeline.documents.extraction.canonical.adapters import legacy_to_v2
from app.pipeline.documents.extraction.canonical.ir import CanonicalElement
from app.pipeline.documents.extraction.canonical.validation import validate_canonical_document
from app.pipeline.documents.extraction.layout.detector import build_layout_for_document
from app.pipeline.documents.ports.parser import DocumentParser
from app.pipeline.indexing.adapters.embedding_providers import LocalEmbeddingProvider
from app.pipeline.indexing.application.chunker import Chunker
from app.pipeline.indexing.application.pipeline import IngestionEmbeddingPipeline
from app.pipeline.shared.errors import AppError


def test_advanced_extraction_builds_quality_canonical_and_phase_artifacts() -> None:
    pipeline = AdvancedExtractionPipeline(AdvancedExtractionPipelineConfig(ocr_enabled=False))
    source = DocumentSource(
        document_id="doc-advanced",
        owner_id="owner-1",
        tenant_id="tenant-1",
        title="brief.txt",
        mime_type="text/plain",
        content=b"Revenue increased in 2026.\n\nCosts stayed controlled.",
        metadata={"extraction_attempt_id": "attempt-1"},
    )

    result = pipeline.run(
        source,
        parser_catalog=ParserRegistry(parsers=[TxtParser()]),
    )

    assert result.index_allowed is True
    assert result.quality_report.passed is True
    assert result.canonical_ir is not None
    assert result.canonical_ir.document_id == "doc-advanced"
    assert result.canonical_ir_validation.valid is True
    assert result.canonical_ir_artifact.checksum
    assert result.phase3_layout is not None
    assert result.phase4_tables is not None
    assert result.phase5_verification is not None
    assert result.phase6_multimodal is not None
    assert result.parsed_document.document_metadata["canonical_ir_v2"]["valid"] is True
    assert "phase3_layout" in result.parsed_document.document_metadata
    assert "phase4_tables" in result.parsed_document.document_metadata


def test_ocr_table_is_not_duplicated_across_canonical_elements_and_tables() -> None:
    table_id = "page-1-ocr-table-1"
    parsed = ParsedDocument(
        text="Item | 2025\nRevenue | 100",
        pages=[
            ParsedPage(
                page_number=1,
                text="Item | 2025\nRevenue | 100",
                elements=[
                    ParsedElement(
                        element_id="page-1-block-1",
                        block_type="paragraph",
                        text="Financial report",
                        page_number=1,
                    ),
                    ParsedElement(
                        element_id=table_id,
                        block_type="table",
                        text="Item | 2025\nRevenue | 100",
                        page_number=1,
                    ),
                ],
                width=1200,
                height=1600,
            )
        ],
        tables=[
            ParsedTable(
                table_id=table_id,
                location="page:1:ocr_table:1",
                rows=[["Item", "2025"], ["Revenue", "100"]],
                columns=2,
                header=["Item", "2025"],
            )
        ],
        parser_name="paddleocr",
        parser_version="3.0",
        ocr_used=True,
    )

    canonical = legacy_to_v2(
        parsed,
        document_id="ocr-table-document",
        extraction_attempt_id="attempt-1",
    )

    page = canonical.pages[0]
    assert [element.element_id for element in page.elements] == ["page-1-block-1"]
    assert [table.table_id for table in page.tables] == [table_id]
    assert page.reading_order == ("page-1-block-1", table_id)
    assert validate_canonical_document(canonical).valid is True

    layout = build_layout_for_document(canonical)
    graph = layout.layout_pages[0].reading_order_graph
    assert graph is not None
    node_ids = graph.node_ids
    assert node_ids.count(table_id) == 1
    assert len(node_ids) == len(set(node_ids))


def test_layout_prefers_canonical_table_when_legacy_ir_contains_same_table_element() -> None:
    table_id = "page-1-ocr-table-1"
    parsed = ParsedDocument(
        text="Item | 2025\nRevenue | 100",
        pages=[
            ParsedPage(
                page_number=1,
                text="Item | 2025\nRevenue | 100",
                elements=[],
                width=1200,
                height=1600,
            )
        ],
        tables=[
            ParsedTable(
                table_id=table_id,
                location="page:1:ocr_table:1",
                rows=[["Item", "2025"], ["Revenue", "100"]],
                columns=2,
            )
        ],
        parser_name="paddleocr",
        parser_version="3.0",
        ocr_used=True,
    )
    canonical = legacy_to_v2(
        parsed,
        document_id="legacy-duplicate-table-document",
        extraction_attempt_id="attempt-1",
    )
    duplicate_table_element = CanonicalElement(
        element_id=table_id,
        element_type="table",
        page_index=0,
        text="Item | 2025\nRevenue | 100",
        provenance={"source": "legacy_ocr_table_element"},
        source_block_ids=(table_id,),
    )
    page = replace(
        canonical.pages[0],
        elements=(duplicate_table_element,),
        reading_order=(table_id,),
    )
    legacy_duplicate = replace(canonical, pages=(page,))

    validation = validate_canonical_document(legacy_duplicate)
    assert validation.valid is False
    assert "duplicate_canonical_object_id" in validation.issue_codes

    layout = build_layout_for_document(legacy_duplicate)
    graph = layout.layout_pages[0].reading_order_graph
    assert graph is not None
    node_ids = graph.node_ids
    assert node_ids == (table_id,)


def test_embedding_pipeline_fails_closed_when_quality_blocks_indexing() -> None:
    class EmptyParser:
        parser_name = "empty"
        parser_version = "1.0"
        supported_extensions = ("txt",)

        def supports(self, extension: str) -> bool:
            return extension == "txt"

        def validate(self, content: bytes) -> None:
            assert content

        def parse(self, content: bytes) -> ParsedDocument:
            return ParsedDocument(
                text="",
                pages=[ParsedPage(page_number=1, text="")],
                sections=[ParsedSection(text="", page_number=1, title="Empty")],
                parser_name=self.parser_name,
                parser_version=self.parser_version,
            )

    parser: DocumentParser = EmptyParser()
    pipeline = IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(parsers=[parser]),
        chunker=Chunker.structure_recursive(chunk_size=8, overlap=2),
        embedding_provider=LocalEmbeddingProvider(),
        extraction_pipeline=AdvancedExtractionPipeline(),
    )
    source = DocumentSource(
        document_id="doc-bad",
        owner_id="owner-1",
        tenant_id="tenant-1",
        title="bad.txt",
        mime_type="text/plain",
        content=b"not empty bytes",
    )

    with pytest.raises(AppError) as exc_info:
        pipeline.run(source)

    assert exc_info.value.detail.code == "embedding_blocked_by_extraction_quality"


def test_extraction_subsystem_modules_are_importable() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "documents" / "extraction"
    modules = []
    for path in root.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(root).with_suffix("")
        modules.append("app.pipeline.documents.extraction." + ".".join(relative.parts))

    failures = []
    for module in sorted(modules):
        try:
            importlib.import_module(module)
        except Exception as exc:  # pragma: no cover - diagnostic branch
            failures.append(f"{module}: {type(exc).__name__}: {exc}")

    assert failures == []
