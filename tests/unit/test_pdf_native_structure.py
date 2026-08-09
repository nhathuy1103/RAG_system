from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.pipeline.documents.adapters.parsers import PdfParser
from app.pipeline.documents.domain.analysis import (
    DocumentAnalysisReport,
    ExtractionStrategy,
    PdfPageAnalysis,
)
from app.pipeline.documents.domain.parsed import ParsedDocument, ParsedPage, ParsedSection
from app.pipeline.documents.extraction.canonical.adapters import legacy_to_v2
from app.pipeline.documents.extraction.documents.quality import DocumentQualityEvaluator
from app.pipeline.documents.extraction.layout.detector import build_layout_for_document
from app.pipeline.documents.extraction.ocr.engine import OcrDocumentResult
from app.pipeline.documents.extraction.parsing.adaptive import _merge_hybrid_pdf_pages
from app.pipeline.documents.extraction.tables.engine import build_tables_for_document


def _simple_native_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    commands = [
        "BT /F1 18 Tf 72 730 Td (Annual Revenue Report) Tj ET",
        "BT /F1 10 Tf 72 710 Td (Company Confidential) Tj ET",
        "BT /F1 12 Tf 72 680 Td (Year) Tj ET",
        "BT /F1 12 Tf 180 680 Td (Revenue) Tj ET",
        "BT /F1 12 Tf 72 660 Td (2025) Tj ET",
        "BT /F1 12 Tf 180 660 Td (100) Tj ET",
        "BT /F1 12 Tf 72 640 Td (2026) Tj ET",
        "BT /F1 12 Tf 180 640 Td (140) Tj ET",
        "BT /F1 12 Tf 72 610 Td (Revenue increased strongly.) Tj ET",
    ]
    content_stream = DecodedStreamObject()
    content_stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content_stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_parser_extracts_native_headings_tables_and_geometry() -> None:
    pytest.importorskip("fitz")

    parsed = PdfParser().parse(_simple_native_pdf())

    native = parsed.document_metadata["native_pdf_extraction"]
    assert native["provider"] == "pymupdf"
    assert native["heading_count"] >= 1
    assert native["table_count"] == 1
    assert "Annual Revenue Report" in parsed.text
    assert parsed.pages[0].width == 612
    assert any(
        element.block_type == "heading" and element.text == "Annual Revenue Report"
        for element in parsed.pages[0].elements
    )
    assert parsed.sections[0].title == "Annual Revenue Report"

    table = parsed.tables[0]
    assert table.rows == [["Year", "Revenue"], ["2025", "100"], ["2026", "140"]]
    assert table.header == ["Year", "Revenue"]
    assert table.bbox is not None
    assert len(table.cells) == 6
    assert table.cells[0]["bbox"]["unit"] == "pt"

    canonical = legacy_to_v2(parsed, document_id="native-pdf")
    assert len(canonical.pages[0].tables) == 1
    assert canonical.pages[0].tables[0].bbox is not None

    layout = build_layout_for_document(canonical)
    assert any(block.block_type == "table_region" for block in layout.layout_pages[0].blocks)

    table_result = build_tables_for_document(canonical, layout_result=layout)
    assert table_result.structured_tables
    assert table_result.structured_tables[0].to_matrix()[0] == ["Year", "Revenue"]


def test_hybrid_merge_preserves_native_pdf_structure_for_native_pages() -> None:
    pytest.importorskip("fitz")

    content = _simple_native_pdf()
    analysis = DocumentAnalysisReport(
        filename="native-table.pdf",
        file_type="pdf",
        page_count=1,
        image_count=0,
        text_layer=True,
        font_available=True,
        pdf_type="hybrid_pdf",
        extraction_strategy=ExtractionStrategy.HYBRID.value,
        confidence=0.95,
        required_processing=("native_pdf_parser", "ocr_backend", "merge_native_and_ocr"),
        page_analysis=(
            PdfPageAnalysis(
                page_number=1,
                text_characters=100,
                has_text_layer=True,
                font_count=1,
                ocr_required=False,
            ),
        ),
    )
    ocr_result = OcrDocumentResult(
        document_id="native-table",
        filename="native-table.pdf",
        source_pdf_type="hybrid_pdf",
        engine_name="test-ocr",
        engine_version="0",
        language="en",
        page_count=1,
        processed_page_count=0,
        successful_page_count=0,
        warning_page_count=0,
        failed_page_count=0,
        missing_page_numbers=(),
        text="",
        character_count=0,
        word_count=0,
        average_confidence=None,
        min_page_confidence=None,
        total_render_time_ms=0,
        total_ocr_time_ms=0,
        processing_time_ms=0,
        extraction_status="PASS",
        validation_status="PASS",
        dqa_status="PASS",
        chunking_ready=True,
        blocking_reasons=(),
        pages=(),
    )

    parsed = _merge_hybrid_pdf_pages(
        filename="native-table.pdf",
        content=content,
        analysis=analysis,
        ocr_result=ocr_result,
    )

    native = parsed.document_metadata["native_pdf_extraction"]
    assert native["provider"] == "pymupdf"
    assert native["hybrid_selected_native_table_count"] == 1
    assert parsed.document_metadata["hybrid_native_page_numbers"] == [1]
    assert parsed.tables[0].rows == [["Year", "Revenue"], ["2025", "100"], ["2026", "140"]]
    assert any(
        element.block_type == "heading" and element.text == "Annual Revenue Report"
        for element in parsed.pages[0].elements
    )
    assert parsed.sections[0].title == "Annual Revenue Report"
    assert parsed.content_markdown is not None
    assert parsed.content_markdown.startswith("# Annual Revenue Report")
    assert "## Page 1" not in parsed.content_markdown


def test_pdf_quality_does_not_pass_table_candidates_vacuously() -> None:
    parsed = ParsedDocument(
        text="Visible PDF text",
        pages=[ParsedPage(page_number=1, text="Visible PDF text")],
        sections=[ParsedSection(text="Visible PDF text", page_number=1, title="Page 1")],
        tables=[],
        parser_name="pdf",
        parser_version="2.0",
        detected_language="en",
        document_metadata={
            "page_count": 1,
            "word_count": 3,
            "table_count": 0,
            "image_count": 0,
            "parser_name": "pdf",
            "parser_version": "2.0",
            "detected_language": "en",
            "ocr_used": False,
            "native_pdf_extraction": {
                "provider": "pymupdf",
                "table_candidate_count": 1,
                "table_count": 0,
            },
        },
    )
    parsed.logical_document = parsed.to_logical_document()

    report = DocumentQualityEvaluator().evaluate(parsed)

    assert report.metrics.table_preservation == 0.0
    assert report.status == "WARN"
    assert "table_structure_loss" in {issue.code for issue in report.issues}
