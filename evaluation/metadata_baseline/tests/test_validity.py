from evaluation.metadata_baseline.audit_metadata import audit_field_quality
from evaluation.metadata_baseline.common import validate_value

from ._helpers import field, record


def test_validity_reports_type_enum_and_regex_failures() -> None:
    language = field(
        "language",
        level="chunk",
        allowed_values=("vi", "en"),
        regex=r"^[a-z]{2}$",
    )
    records = (
        record("chunk", "chunk-1", document_id="doc-1", language="vi"),
        record("chunk", "chunk-2", document_id="doc-1", language="vi_VN"),
        record("chunk", "chunk-3", document_id="doc-1", language=12),
    )

    summary, _, validity, _ = audit_field_quality(records, (language,))

    assert summary[0]["validity"] == 0.333333
    issues = [row for row in validity if row["row_type"] == "issue"]
    assert "not_in_allowed_values" in issues[0]["error"]
    assert "regex_mismatch" in issues[0]["error"]
    assert issues[1]["error"] == "expected_string"


def test_validate_value_handles_uuid_date_and_uri() -> None:
    uuid_field = field("id", expected_type="uuid")
    date_field = field("effective_from", expected_type="date")
    uri_field = field("source_uri", expected_type="uri")

    assert validate_value(uuid_field, "11111111-1111-4111-8111-111111111111") == ()
    assert validate_value(uuid_field, "not-a-uuid") == ("expected_uuid",)
    assert validate_value(date_field, "2026-02-29") == ("expected_date",)
    assert validate_value(uri_field, "https://example.test/policy") == ()
    assert validate_value(uri_field, "relative/path") == ("expected_uri",)
