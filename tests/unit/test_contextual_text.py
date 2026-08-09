"""Deterministic contextual projection tests."""

from app.shared.contextual_text import ChunkContext, build_embedding_text, build_search_text


def test_embedding_context_contains_semantics_but_not_locator_fields() -> None:
    context = ChunkContext(
        title="Travel policy",
        document_type="policy",
        section_title="Lodging",
        section_path=("Expenses", "Lodging"),
        content_kind="table",
        table_header="Grade | City | Maximum",
        contextual_summary="This row defines the Bangkok lodging allowance.",
        contextual_search_terms=("Bangkok lodging",),
    )

    text = build_embedding_text("A | Bangkok | 120 USD", context)

    assert text.startswith("Document: Travel policy\nDocument type: policy\n")
    assert "Section: Expenses > Lodging" in text
    assert "Content type: table" in text
    assert "Table header: Grade | City | Maximum" in text
    assert "Context: This row defines the Bangkok lodging allowance." in text
    assert "Page:" not in text
    assert text.endswith("A | Bangkok | 120 USD")


def test_search_projection_adds_aliases_without_changing_canonical_content() -> None:
    context = ChunkContext(
        title="Travel policy",
        section_title="Lodging",
        keyword_aliases=("HR-TRAVEL-04", "business trip allowance"),
        contextual_summary="This rule applies to lodging expenses.",
        contextual_search_terms=("lodging expenses",),
    )
    content = "The maximum is 120 USD."

    search_text = build_search_text(content, context)

    assert "Travel policy" in search_text
    assert "HR-TRAVEL-04" in search_text
    assert "business trip allowance" in search_text
    assert "This rule applies to lodging expenses." in search_text
    assert "lodging expenses" in search_text
    assert search_text.endswith(content)
    assert content == "The maximum is 120 USD."


def test_projection_uses_semantic_title_and_omits_parser_only_section_labels() -> None:
    context = ChunkContext(
        title="demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
        document_type="policy",
        section_title="Page 14",
        section_path=("DOCX", "Page 14"),
        contextual_summary="Điều kiện đổi trả áp dụng cho yêu cầu của khách hàng.",
    )

    embedding_text = build_embedding_text("Khách hàng gửi yêu cầu đổi trả.", context)
    search_text = build_search_text("Khách hàng gửi yêu cầu đổi trả.", context)

    assert embedding_text.startswith("Document: demo kb chinh sach doi tra cskh\n")
    assert ".docx" not in embedding_text
    assert "Section:" not in embedding_text
    assert "Page 14" not in search_text
    assert "DOCX" not in search_text
