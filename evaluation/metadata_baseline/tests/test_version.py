from evaluation.metadata_baseline.audit_metadata import audit_version_consistency

from ._helpers import record


def test_version_audit_finds_current_gap_date_and_parent_mismatch() -> None:
    documents = (
        record(
            "document",
            "doc-1",
            version_group_id="family-1",
            version_number=1,
            effective_from="2026-01-01",
            is_current=True,
            quality_status="clean",
        ),
        record(
            "document",
            "doc-2",
            version_group_id="family-1",
            version_number=3,
            effective_from="2025-12-01",
            is_current=True,
            quality_status="superseded",
        ),
    )
    chunks = (
        record(
            "chunk",
            "chunk-1",
            document_id="doc-1",
            metadata={"document_version": 2},
        ),
    )

    issues = audit_version_consistency((*documents, *chunks))
    issue_types = {issue["issue_type"] for issue in issues}

    assert "multiple_current_versions" in issue_types
    assert "version_sequence_gap" in issue_types
    assert "newer_version_has_older_effective_date" in issue_types
    assert "chunk_parent_version_mismatch" in issue_types
    assert "noncanonical_document_marked_current" in issue_types
