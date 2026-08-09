"""Regression tests for PDFs encrypted with an empty user password."""

from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.pipeline.documents.adapters.parsers import PdfParser
from app.pipeline.documents.domain.analysis import DocumentAnalyzer
from app.pipeline.documents.extraction.profiling.models import ProfileStatus
from app.pipeline.documents.extraction.profiling.profiler import PageProfiler
from app.pipeline.shared.errors import AppError


def _encrypted_text_pdf(user_password: str) -> bytes:
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
    content_stream = DecodedStreamObject()
    content_stream.set_data(b"BT /F1 12 Tf 72 720 Td (Empty password PDF content) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content_stream)
    writer.encrypt(
        user_password=user_password,
        owner_password="owner-secret",
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_empty_password_pdf_is_analyzed_parsed_and_profiled() -> None:
    content = _encrypted_text_pdf("")

    analysis = DocumentAnalyzer().analyze("empty-password.pdf", content)
    parsed = PdfParser().parse(content)
    profiles = PageProfiler().profile_document("empty-password.pdf", content)

    assert analysis.encrypted is False
    assert analysis.page_count == 1
    assert "Empty password PDF content" in parsed.text
    assert len(profiles) == 1
    assert profiles[0].status is not ProfileStatus.FAIL_CLOSED
    assert "pdf_encrypted" not in profiles[0].reason_codes


def test_nonempty_password_pdf_remains_rejected() -> None:
    content = _encrypted_text_pdf("secret")

    analysis = DocumentAnalyzer().analyze("locked.pdf", content)

    assert analysis.encrypted is True
    with pytest.raises(AppError) as exc_info:
        PdfParser().parse(content)
    assert exc_info.value.detail.code == "password_protected_file"
