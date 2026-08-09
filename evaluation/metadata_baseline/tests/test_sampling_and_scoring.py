from pathlib import Path

from evaluation.metadata_baseline.common import load_schema
from evaluation.metadata_baseline.create_gold_sample import (
    create_annotation_rows,
    record_strata,
    select_records,
)
from evaluation.metadata_baseline.score_metadata_accuracy import score_annotations

from ._helpers import record

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "metadata_schema.csv"


def test_stratified_selection_is_seeded_and_unique() -> None:
    schema = load_schema(SCHEMA_PATH)
    records = tuple(
        record(
            "document" if index % 2 == 0 else "chunk",
            f"record-{index}",
            document_id=f"doc-{index}" if index % 2 else None,
            status="ready",
        )
        for index in range(10)
    )
    flags = {"record-3": {"metadata_conflict"}, "record-7": {"invalid_enum"}}

    first = select_records(records, schema, sample_size=6, seed=42, flagged=flags)
    second = select_records(records, schema, sample_size=6, seed=42, flagged=flags)

    assert [item.record_id for item in first] == [item.record_id for item in second]
    assert len({item.record_id for item in first}) == 6
    assert {"record-3", "record-7"}.issubset({item.record_id for item in first})


def test_annotation_fields_oversample_version_status_and_dates() -> None:
    schema = load_schema(SCHEMA_PATH)
    document = record("document", "doc-1", status="ready")

    rows = create_annotation_rows((document,), (document,), schema, fields_per_record=8)

    assert {row["field_name"] for row in rows} == {
        "status",
        "quality_status",
        "version_group_id",
        "version_number",
        "is_current",
        "effective_from",
        "effective_to",
        "canonical_document_id",
    }


def test_chunk_annotation_inherits_authoritative_parent_context() -> None:
    schema = load_schema(SCHEMA_PATH)
    document = record(
        "document",
        "doc-1",
        status="ready",
        quality_status="clean",
        original_filename="policy.pdf",
        storage_object_path="owner/notebook/policy.pdf",
        mime_type="application/pdf",
        version_number=2,
    )
    chunk = record("chunk", "chunk-1", document_id="doc-1")

    strata = record_strata(chunk, schema=schema, parent=document)
    rows = create_annotation_rows((chunk,), (document, chunk), schema, fields_per_record=1)

    assert "status:ready" in strata
    assert "quality_status:clean" in strata
    assert "source:owner/notebook/policy.pdf" in strata
    assert rows[0]["source"] == "owner/notebook/policy.pdf"
    assert rows[0]["status"] == "ready"
    assert rows[0]["quality_status"] == "clean"
    assert "mime_type=application/pdf" in str(rows[0]["parent_context"])


def test_accuracy_scores_single_multilabel_and_double_annotation() -> None:
    schema = load_schema(SCHEMA_PATH)
    rows = [
        {
            "field_name": "document_type",
            "current_value": "policy",
            "gold_value": "policy",
            "is_correct": "1",
            "document_type": "policy",
            "source": "source-a",
            "version_group_id": "family-a",
            "error_type": "",
            "annotator_a_value": "policy",
            "annotator_b_value": "policy",
            "annotator_a_is_correct": "1",
            "annotator_b_is_correct": "1",
        },
        {
            "field_name": "document_type",
            "current_value": "report",
            "gold_value": "policy",
            "is_correct": "0",
            "document_type": "policy",
            "source": "source-a",
            "version_group_id": "family-a",
            "error_type": "incorrect",
            "annotator_a_value": "report",
            "annotator_b_value": "policy",
            "annotator_a_is_correct": "0",
            "annotator_b_is_correct": "1",
        },
        {
            "field_name": "contextual_search_terms",
            "current_value": '["hotel","hanoi"]',
            "gold_value": '["hotel","policy"]',
            "is_correct": "0",
            "document_type": "policy",
            "source": "source-a",
            "version_group_id": "family-a",
            "error_type": "incorrect",
            "annotator_a_value": '["hotel","hanoi"]',
            "annotator_b_value": '["hanoi","hotel"]',
            "annotator_a_is_correct": "0",
            "annotator_b_is_correct": "0",
        },
    ]

    accuracy, confusion, agreement, report = score_annotations(rows, schema)

    document_type = next(
        row
        for row in accuracy
        if row["group_type"] == "field" and row["field_name"] == "document_type"
    )
    terms = next(
        row
        for row in accuracy
        if row["group_type"] == "field" and row["field_name"] == "contextual_search_terms"
    )
    terms_agreement = next(
        row for row in agreement if row["field_name"] == "contextual_search_terms"
    )

    assert document_type["accuracy"] == 0.5
    assert terms["jaccard_similarity"] == 0.333333
    assert "document_type" in confusion
    assert terms_agreement["multilabel_jaccard_agreement"] == 1.0
    assert "hard filter" in report
