from datetime import date

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


def test_normalizer_promotes_inferred_candidates_but_explicit_values_win() -> None:
    metadata = normalize_chunk_retrieval_metadata(
        chunk_metadata={"document_type": "quy_dinh"},
        document_metadata={
            "inferred_metadata": {
                "document_type": "bao_cao",
                "project_code": "p16",
                "year": "2026",
                "data_period": "Q1/2026",
            }
        },
        source_metadata={},
        title="Tài liệu dự án",
        section_title=None,
    )

    assert metadata["document_type"] == "quy_dinh"
    assert metadata["project_code"] == "P16"
    assert metadata["year"] == 2026
    assert metadata["data_period"] == "Q1-2026"
    assert set(metadata["inferred_metadata_fields"]) == {
        "data_period",
        "document_type",
        "project_code",
        "year",
    }


def test_normalizer_derives_temporal_status_against_an_explicit_date() -> None:
    current = normalize_chunk_retrieval_metadata(
        chunk_metadata={},
        document_metadata={
            "inferred_metadata": {
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
            }
        },
        source_metadata={},
        title="Quy định",
        section_title=None,
        reference_date=date(2026, 8, 11),
    )
    expired = normalize_chunk_retrieval_metadata(
        chunk_metadata={},
        document_metadata={"effective_to": "2025-12-31"},
        source_metadata={},
        title="Quy định cũ",
        section_title=None,
        reference_date=date(2026, 8, 11),
    )

    assert current["effective_status"] == "current"
    assert current["effective_status_as_of"] == "2026-08-11"
    assert expired["effective_status"] == "expired"
