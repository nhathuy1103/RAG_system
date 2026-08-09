"""Typed retrieval metadata normalization tests."""

from app.retrieval.domain.metadata import EvidenceMetadata


def test_normalizes_known_types_and_flattens_retrieval_fields() -> None:
    metadata = EvidenceMetadata.from_mapping(
        {
            "page_number": "4",
            "document_version": 3,
            "chunk_index": "7",
            "retrieval_metadata": {
                "title": "Travel policy",
                "section_path": ["Expenses", "Lodging"],
                "content_kind": "table",
                "contextual_summary": "This chunk defines the lodging allowance.",
                "contextual_search_terms": ["Bangkok lodging", "travel allowance"],
            },
            "pre_embedding_quality": {"embedding_reused": False},
        }
    )

    assert metadata.page_number == 4
    assert metadata.document_version == 3
    assert metadata.chunk_index == 7
    assert metadata.text("title") == "Travel policy"
    assert metadata.strings("section_path") == ("Expenses", "Lodging")
    assert metadata.text("contextual_summary") == "This chunk defines the lodging allowance."
    assert metadata.strings("contextual_search_terms") == (
        "Bangkok lodging",
        "travel allowance",
    )
    assert metadata["pre_embedding_quality"] == {"embedding_reused": False}


def test_invalid_numeric_metadata_is_not_exposed_as_a_typed_value() -> None:
    metadata = EvidenceMetadata.from_mapping({"page_number": "page-four", "document_version": ""})

    assert metadata.page_number is None
    assert metadata.document_version == 1
    assert "page_number" not in metadata
