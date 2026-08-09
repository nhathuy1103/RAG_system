from evaluation.metadata_baseline.audit_metadata import audit_temporal_consistency

from ._helpers import record


def test_temporal_audit_detects_parse_order_and_range_errors() -> None:
    records = (
        record(
            "document",
            "doc-1",
            created_at="2026-02-02T10:00:00Z",
            updated_at="2026-02-02T09:00:00Z",
            effective_from="2026-12-31",
            effective_to="2026-01-01",
        ),
        record(
            "document",
            "doc-2",
            created_at="not-a-date",
            updated_at="2099-01-01T00:00:00Z",
        ),
    )

    issues = audit_temporal_consistency(records)
    issue_types = {issue["issue_type"] for issue in issues}

    assert "created_after_updated" in issue_types
    assert "effective_after_expiry" in issue_types
    assert "unparseable_date" in issue_types
    assert "date_outside_reasonable_range" in issue_types
