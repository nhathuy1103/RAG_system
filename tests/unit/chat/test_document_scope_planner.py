from datetime import UTC, datetime
from uuid import UUID

from app.chat.application.document_scope_planner import (
    DeterministicDocumentScopePlanner,
    normalize_document_identity,
)
from app.documents.domain.models import Document

OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 6, tzinfo=UTC)


def _document(document_id: str, filename: str) -> Document:
    return Document(
        id=UUID(document_id),
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        original_filename=filename,
        storage_bucket="documents",
        storage_object_path=f"documents/{document_id}/{filename}",
        mime_type="application/octet-stream",
        size_bytes=10,
        content_hash=None,
        status="ready",
        error_message=None,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def test_normalizes_accents_camel_case_and_filename_separators() -> None:
    assert normalize_document_identity("Vinhomes_HảiVân.pdf") == "vinhomes hai van pdf"


def test_routes_unique_authoritative_filename_match() -> None:
    hai_van = _document("30000000-0000-0000-0000-000000000003", "Vinhomes_HaiVan.pdf")
    tay_mo = _document("40000000-0000-0000-0000-000000000004", "Vinhomes_TayMo.pdf")

    plan = DeterministicDocumentScopePlanner().plan(
        "Trong tài liệu Vinhomes Hải Vân, quyết định 5805/QĐ-UBND nói gì?",
        (hai_van, tay_mo),
        (hai_van.id, tay_mo.id),
    )

    assert plan.applied is True
    assert plan.after_document_ids == (hai_van.id,)
    assert plan.matched_titles == ("Vinhomes_HaiVan.pdf",)
    assert plan.source_fields == ("documents.id", "documents.original_filename")


def test_uses_year_in_real_filename_to_disambiguate_price_documents() -> None:
    price_2023 = _document(
        "30000000-0000-0000-0000-000000000003",
        "Vinhomes_Gia_Nha_2023.docx",
    )
    price_2025 = _document(
        "40000000-0000-0000-0000-000000000004",
        "Vinhomes_Gia_Nha_2025.docx",
    )

    plan = DeterministicDocumentScopePlanner().plan(
        "Giá nhà Vinhomes năm 2023 được ghi nhận như thế nào?",
        (price_2023, price_2025),
        (price_2023.id, price_2025.id),
    )

    assert plan.applied is True
    assert plan.after_document_ids == (price_2023.id,)
    assert "2023" in plan.matched_tokens


def test_fails_open_when_query_has_no_unique_filename_evidence() -> None:
    original = _document(
        "30000000-0000-0000-0000-000000000003",
        "demo_kb_chinh_sach_doi_tra_cskh.docx",
    )
    copy = _document(
        "40000000-0000-0000-0000-000000000004",
        "demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
    )
    before = (original.id, copy.id)

    plan = DeterministicDocumentScopePlanner().plan(
        "Chính sách đổi trả áp dụng trong bao lâu?",
        (original, copy),
        before,
    )

    assert plan.applied is False
    assert plan.reason == "no_unique_filename_match"
    assert plan.after_document_ids == tuple(sorted(before, key=str))


def test_never_expands_the_authorized_scope() -> None:
    hai_van = _document("30000000-0000-0000-0000-000000000003", "Vinhomes_HaiVan.pdf")
    tay_mo = _document("40000000-0000-0000-0000-000000000004", "Vinhomes_TayMo.pdf")

    plan = DeterministicDocumentScopePlanner().plan(
        "Đọc Vinhomes Tây Mỗ giúp tôi",
        (hai_van, tay_mo),
        (hai_van.id,),
    )

    assert plan.applied is False
    assert plan.after_document_ids == (hai_van.id,)
