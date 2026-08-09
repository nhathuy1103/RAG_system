from evaluation.metadata_baseline.audit_metadata import (
    audit_consistency,
    audit_duplicate_ids,
    audit_metadata_conflicts,
    audit_referential_integrity,
)

from ._helpers import field, record


def test_consistency_finds_surface_acronym_and_document_drift() -> None:
    department = field(
        "department",
        level="chunk",
        consistency_scope="document",
    )
    records = (
        record("chunk", "chunk-1", document_id="doc-1", department="HR"),
        record("chunk", "chunk-2", document_id="doc-1", department="Human Resources"),
        record("chunk", "chunk-3", document_id="doc-2", department=" human resources "),
        record("chunk", "chunk-4", document_id="doc-3", department="Human Resource"),
    )

    issues = audit_consistency(records, (department,))
    issue_types = {issue["issue_type"] for issue in issues}

    assert "case_whitespace_or_unicode_variant" in issue_types
    assert "possible_acronym_variant" in issue_types
    assert "possible_singular_plural_variant" in issue_types
    assert "inconsistent_within_document" in issue_types


def test_conflict_rules_use_composite_schema_roles() -> None:
    version_group = field(
        "version_group_id",
        level="document",
        conflict_roles=("group:version_identity",),
    )
    version = field(
        "version_number",
        level="document",
        expected_type="integer",
        conflict_roles=("group:version_identity",),
    )
    effective = field(
        "effective_from",
        level="document",
        expected_type="date",
        conflict_roles=("compare:version_identity",),
    )
    records = (
        record(
            "document",
            "doc-1",
            version_group_id="family-1",
            version_number=1,
            effective_from="2026-01-01",
        ),
        record(
            "document",
            "doc-2",
            version_group_id="family-1",
            version_number=1,
            effective_from="2026-02-01",
        ),
    )

    issues = audit_metadata_conflicts(records, (version_group, version, effective))

    assert len(issues) == 1
    assert issues[0]["field_name"] == "effective_from"


def test_uniqueness_and_referential_integrity_detect_bad_links() -> None:
    documents = (record("document", "doc-1"),)
    chunks = (
        record("chunk", "chunk-1", document_id="missing", content="one"),
        record("chunk", "chunk-1", document_id="missing", content="two"),
    )

    duplicate_issues = audit_duplicate_ids((*documents, *chunks), ())
    reference_issues = audit_referential_integrity((*documents, *chunks), ())

    assert duplicate_issues[0]["issue_type"] == "duplicate_id_different_payload"
    assert {issue["issue_type"] for issue in reference_issues} == {"missing_parent_document"}


def test_current_batch_target_may_reference_source_chunk_id() -> None:
    target_field = field(
        "pre_embedding_quality.target_chunk_id",
        level="chunk",
        reference_target="chunk_id_or_source_chunk_id",
    )
    records = (
        record("document", "doc-1"),
        record(
            "chunk",
            "chunk-1",
            document_id="doc-1",
            metadata={"source_chunk_id": "doc-1:v1:strategy:0:hash"},
        ),
        record(
            "chunk",
            "chunk-2",
            document_id="doc-1",
            metadata={
                "source_chunk_id": "doc-1:v1:strategy:1:hash",
                "pre_embedding_quality": {
                    "target_chunk_id": "doc-1:v1:strategy:0:hash",
                    "match_source": "current_batch",
                },
            },
        ),
    )

    assert audit_referential_integrity(records, (target_field,)) == []
