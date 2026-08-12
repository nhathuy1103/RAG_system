from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from app.retrieval.application.relation_policy import (
    apply_relation_aware_policy,
    document_diversity_at_k,
    duplicate_redundancy_at_k,
    unique_evidence_at_k,
)
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate, RetrievalFilters

FILTERS = RetrievalFilters(owner_id="owner", notebook_id="notebook")


def _candidate(
    chunk_id: str,
    *,
    document_id: str | None = None,
    score: float = 1.0,
    metadata: Mapping[str, object] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=EvidenceChunk(
            id=chunk_id,
            document_id=document_id or f"doc-{chunk_id}",
            text=f"evidence {chunk_id}",
            metadata=EvidenceMetadata.from_mapping(
                {
                    "owner_id": "owner",
                    "notebook_id": "notebook",
                    **dict(metadata or {}),
                }
            ),
        ),
        score=score,
        rank=1,
    )


def test_exact_duplicate_collapse_retains_only_visible_provenance() -> None:
    candidates = (
        _candidate("a", metadata={"exact_duplicate_group_id": "exact"}, score=0.8),
        _candidate("b", metadata={"exact_duplicate_group_id": "exact"}, score=0.9),
        _candidate("c"),
        _candidate(
            "hidden",
            metadata={"owner_id": "another", "exact_duplicate_group_id": "exact"},
        ),
    )

    result = apply_relation_aware_policy(candidates, query="q", filters=FILTERS)

    assert [item.chunk.id for item in result.evidence] == ["b", "c"]
    assert result.diagnostics.suppressed_duplicate_ids == ("a",)
    assert "hidden" not in result.diagnostics.legacy_chunk_ids
    raw_provenance = cast(str, result.evidence[0].chunk.metadata["p4_provenance_chunk_ids"])
    assert json.loads(raw_provenance) == [
        "a",
        "b",
    ]


def test_document_duplicate_collapse_keeps_all_chunks_from_the_representative() -> None:
    candidates = (
        _candidate(
            "a-1",
            document_id="doc-a",
            score=1.0,
            metadata={"p4_exact_duplicate_group_id": "exact"},
        ),
        _candidate(
            "a-2",
            document_id="doc-a",
            score=0.95,
            metadata={"p4_exact_duplicate_group_id": "exact"},
        ),
        _candidate(
            "b-1",
            document_id="doc-b",
            score=0.9,
            metadata={"p4_exact_duplicate_group_id": "exact"},
        ),
        _candidate(
            "b-2",
            document_id="doc-b",
            score=0.85,
            metadata={"p4_exact_duplicate_group_id": "exact"},
        ),
    )

    result = apply_relation_aware_policy(candidates, query="q", filters=FILTERS)

    assert [item.chunk.id for item in result.evidence] == ["a-1", "a-2"]
    assert result.diagnostics.suppressed_duplicate_ids == ("b-1", "b-2")
    for item in result.evidence:
        raw = cast(str, item.chunk.metadata["p4_provenance_chunk_ids"])
        assert json.loads(raw) == ["a-1", "a-2", "b-1", "b-2"]


def test_shadow_computes_policy_without_changing_visible_results() -> None:
    candidates = (
        _candidate("a", metadata={"near_duplicate_group_id": "near"}),
        _candidate("b", metadata={"near_duplicate_group_id": "near"}, score=0.9),
    )

    result = apply_relation_aware_policy(
        candidates,
        query="q",
        filters=FILTERS,
        mode="shadow",
    )

    assert result.evidence == candidates
    assert len(result.proposed_evidence) == 1
    assert result.diagnostics.suppressed_duplicate_ids == ("b",)


def test_conflict_sides_are_preserved_while_duplicate_alias_is_collapsed() -> None:
    candidates = (
        _candidate(
            "a",
            metadata={
                "exact_duplicate_group_id": "same-450",
                "conflict_group_id": "range-conflict",
            },
        ),
        _candidate(
            "b",
            metadata={
                "exact_duplicate_group_id": "same-450",
                "conflict_group_id": "range-conflict",
            },
            score=0.8,
        ),
        _candidate("c", metadata={"conflict_group_id": "range-conflict"}),
    )

    result = apply_relation_aware_policy(candidates, query="q", filters=FILTERS)

    assert [item.chunk.id for item in result.evidence] == ["a", "c"]
    assert result.diagnostics.preserved_conflict_ids == ("a", "c")


def test_current_historical_and_comparison_version_queries() -> None:
    candidates = tuple(
        _candidate(
            f"v{year}",
            metadata={
                "version_family_id": "family",
                "reference_year": year,
                "version_number": year - 2023,
                "is_current": year == 2026,
            },
        )
        for year in (2024, 2025, 2026)
    )

    current = apply_relation_aware_policy(candidates, query="current price", filters=FILTERS)
    historical = apply_relation_aware_policy(candidates, query="price in 2024", filters=FILTERS)
    comparison = apply_relation_aware_policy(
        candidates,
        query="compare 2024 to 2026",
        filters=FILTERS,
    )

    assert [item.chunk.id for item in current.evidence] == ["v2026"]
    assert [item.chunk.id for item in historical.evidence] == ["v2024"]
    assert [item.chunk.id for item in comparison.evidence] == ["v2024", "v2026"]


def test_version_selection_keeps_all_retrieved_chunks_of_the_selected_document() -> None:
    candidates = (
        _candidate(
            "old-1",
            document_id="old",
            metadata={"version_family_id": "family", "version_number": 1},
        ),
        _candidate(
            "new-1",
            document_id="new",
            metadata={
                "version_family_id": "family",
                "version_number": 2,
                "is_current": True,
            },
        ),
        _candidate(
            "new-2",
            document_id="new",
            score=0.8,
            metadata={
                "version_family_id": "family",
                "version_number": 2,
                "is_current": True,
            },
        ),
    )

    result = apply_relation_aware_policy(candidates, query="current facts", filters=FILTERS)

    assert [item.chunk.id for item in result.evidence] == ["new-1", "new-2"]


def test_current_query_does_not_guess_when_validity_is_unknown_or_ambiguous() -> None:
    unknown = tuple(
        _candidate(
            f"unknown-{version}",
            metadata={"version_family_id": "unknown-family", "version_number": version},
        )
        for version in (1, 2)
    )
    ambiguous = tuple(
        _candidate(
            f"current-{version}",
            metadata={
                "version_family_id": "ambiguous-family",
                "version_number": version,
                "is_current": True,
            },
        )
        for version in (1, 2)
    )

    unknown_result = apply_relation_aware_policy(
        unknown,
        query="current price",
        filters=FILTERS,
    )
    ambiguous_result = apply_relation_aware_policy(
        ambiguous,
        query="latest price",
        filters=FILTERS,
    )

    assert unknown_result.evidence == unknown
    assert ambiguous_result.evidence == ambiguous


def test_conditional_query_filters_only_when_condition_is_explicit() -> None:
    candidates = (
        _candidate(
            "wltp",
            metadata={"p4_relation_type": "CONDITIONAL_VARIANT", "test_protocol": "WLTP"},
        ),
        _candidate(
            "epa",
            metadata={"p4_relation_type": "CONDITIONAL_VARIANT", "test_protocol": "EPA"},
        ),
    )

    unspecified = apply_relation_aware_policy(candidates, query="range", filters=FILTERS)
    specified = apply_relation_aware_policy(candidates, query="WLTP range", filters=FILTERS)

    assert unspecified.evidence == candidates
    assert [item.chunk.id for item in specified.evidence] == ["wltp"]


def test_uncertain_evidence_is_never_suppressed_by_near_or_version_groups() -> None:
    candidates = (
        _candidate(
            "near-certain",
            metadata={"near_duplicate_group_id": "near", "version_family_id": "family"},
        ),
        _candidate(
            "uncertain",
            metadata={
                "near_duplicate_group_id": "near",
                "version_family_id": "family",
                "p4_relation_type": "UNCERTAIN",
            },
        ),
    )

    result = apply_relation_aware_policy(candidates, query="current facts", filters=FILTERS)

    assert {item.chunk.id for item in result.evidence} == {"near-certain", "uncertain"}


def test_relation_metrics_measure_redundancy_unique_evidence_and_diversity() -> None:
    candidates = (
        _candidate("a", document_id="one", metadata={"near_duplicate_group_id": "near"}),
        _candidate("b", document_id="two", metadata={"near_duplicate_group_id": "near"}),
        _candidate("c", document_id="three"),
    )

    assert duplicate_redundancy_at_k(candidates, 3) == 1 / 3
    assert unique_evidence_at_k(candidates, 3) == 2
    assert document_diversity_at_k(candidates, 3) == 3


def test_unauthorized_conflict_and_version_metadata_does_not_leak() -> None:
    allowed = _candidate("allowed", metadata={"conflict_group_id": "secret"})
    forbidden = _candidate(
        "forbidden",
        metadata={
            "owner_id": "other",
            "conflict_group_id": "secret",
            "version_family_id": "secret-version",
        },
    )

    result = apply_relation_aware_policy((allowed, forbidden), query="q", filters=FILTERS)

    assert result.evidence == (allowed,)
    assert result.diagnostics.legacy_chunk_ids == ("allowed",)
    assert result.diagnostics.preserved_conflict_ids == ()


def test_unauthorized_exact_counterpart_is_not_added_to_visible_provenance() -> None:
    allowed = _candidate("allowed", metadata={"exact_duplicate_group_id": "secret"})
    forbidden = _candidate(
        "forbidden",
        metadata={"owner_id": "other", "exact_duplicate_group_id": "secret"},
    )

    result = apply_relation_aware_policy((allowed, forbidden), query="q", filters=FILTERS)
    raw = cast(str, result.evidence[0].chunk.metadata["p4_provenance_chunk_ids"])

    assert json.loads(raw) == ["allowed"]
    assert "forbidden" not in result.diagnostics.suppressed_duplicate_ids
