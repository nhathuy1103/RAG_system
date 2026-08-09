from app.pipeline.indexing.domain.retrieval_metadata import (
    normalize_chunk_retrieval_metadata,
)


def test_normalizer_derives_project_identity_from_structured_heading() -> None:
    metadata = normalize_chunk_retrieval_metadata(
        chunk_metadata={
            "retrieval_metadata": {
                "document_type": "AMENITY_CATALOG",
                "content_kind": "TABLE",
            }
        },
        document_metadata={},
        source_metadata={},
        title="Vinhomes_Tien_Ich_2026.docx",
        section_title="P16 \u2022 Vinhomes Smart City",
    )

    assert metadata["project_code"] == "P16"
    assert metadata["project_name"] == "Vinhomes Smart City"
    assert metadata["year"] == 2026
    assert metadata["document_type"] == "amenity_catalog"
    assert metadata["content_kind"] == "table"


def test_normalizer_does_not_invent_project_or_status() -> None:
    metadata = normalize_chunk_retrieval_metadata(
        chunk_metadata={},
        document_metadata={},
        source_metadata={},
        title="general-notes.docx",
        section_title="Overview",
    )

    assert "project_code" not in metadata
    assert "effective_status" not in metadata
