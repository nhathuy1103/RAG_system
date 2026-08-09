from evaluation.metadata_baseline.audit_metadata import audit_field_quality

from ._helpers import field, record


def test_coverage_distinguishes_missing_states_and_valid_coverage() -> None:
    schema = (
        field(
            "status",
            level="document",
            required=True,
            allowed_values=("ready", "failed"),
        ),
    )
    records = (
        record("document", "doc-1", status="ready"),
        record("document", "doc-2", status=""),
        record("document", "doc-3", status="unknown"),
        record("document", "doc-4", status=None),
        record("document", "doc-5"),
    )

    summary, coverage, validity, distributions = audit_field_quality(records, schema)

    assert summary == [
        {
            "field_name": "status",
            "category": "derived",
            "level": "document",
            "record_type": "document",
            "required": True,
            "total_records": 5,
            "non_empty_count": 1,
            "valid_count": 1,
            "coverage": 0.2,
            "valid_coverage": 0.2,
            "validity": 1.0,
            "missing_count": 1,
            "null_count": 1,
            "empty_string_count": 1,
            "empty_list_count": 0,
            "empty_object_count": 0,
            "placeholder_count": 1,
            "unique_count": 1,
            "cardinality_ratio": 1.0,
            "entropy": 0.0,
            "importance": "high",
        }
    ]
    assert any(row["dimension"] == "all" and row["valid_coverage"] == 0.2 for row in coverage)
    assert validity[0]["invalid_count"] == 0
    assert distributions["document.status"]["dominant_value_ratio"] == 1.0
