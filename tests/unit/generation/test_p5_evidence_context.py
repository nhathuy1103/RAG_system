from __future__ import annotations

from typing import Any

from app.generation.application.evidence_context import (
    EvidenceContextPolicy,
    build_generation_context,
)
from app.generation.domain.evidence import EvidenceBundleType, GenerationContext, NoAnswerReason
from app.retrieval.application.query_context import QueryContext, parse_query_context
from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate


def _candidate(
    name: str,
    *,
    document: str | None = None,
    text: str | None = None,
    score: float = 1.0,
    **metadata: object,
) -> RetrievalCandidate:
    raw_rank = metadata.pop("rank", 1)
    rank = raw_rank if isinstance(raw_rank, int) else 1
    return RetrievalCandidate(
        chunk=EvidenceChunk(
            id=f"chunk-{name}",
            document_id=document or f"doc-{name}",
            text=text or f"Evidence {name}",
            metadata=EvidenceMetadata.from_mapping(metadata),
        ),
        score=score,
        rank=rank,
    )


def _query(value: str) -> QueryContext:
    return parse_query_context(value, owner_id="owner", notebook_id="notebook")


def _build(
    query: str,
    candidates: tuple[RetrievalCandidate, ...],
    **policy: Any,
) -> GenerationContext:
    return build_generation_context(
        _query(query),
        candidates,
        authorized_document_ids=frozenset(item.chunk.document_id for item in candidates),
        policy=EvidenceContextPolicy(**policy),
    )


def test_exact_duplicates_become_one_fact_with_visible_occurrences() -> None:
    candidates = (
        _candidate("a", p4_exact_duplicate_group_id="exact-1", score=0.9),
        _candidate("b", p4_exact_duplicate_group_id="exact-1", score=0.8),
        _candidate("c", score=0.7),
    )

    context = _build("What is the price?", candidates)

    assert len(context.evidence) == 2
    duplicate = next(item for item in context.evidence if item.duplicate_group)
    assert duplicate.independent_source_count == 1
    assert "chunk-b" in context.diagnostics.suppressed_ids
    assert context.diagnostics.independent_evidence_count == 2


def test_current_historical_and_unknown_current_are_not_guessed() -> None:
    candidates = (
        _candidate(
            "2024",
            p4_relation_type="VERSION_UPDATE",
            version_family_id="family-1",
            year=2024,
            is_current=False,
        ),
        _candidate(
            "2026",
            p4_relation_type="VERSION_UPDATE",
            version_family_id="family-1",
            year=2026,
            is_current=True,
        ),
    )

    current = _build("What is the current price?", candidates)
    historical = _build("What was the price in 2024?", candidates)
    unknown = _build(
        "What is the latest price?",
        tuple(
            _candidate(
                str(year),
                p4_relation_type="VERSION_UPDATE",
                version_family_id="family-x",
                year=year,
            )
            for year in (2024, 2026)
        ),
    )

    assert {item.document_id for item in current.evidence} == {"doc-2026"}
    assert {item.document_id for item in historical.evidence} == {"doc-2024"}
    assert unknown.no_answer_reason is NoAnswerReason.CURRENT_VERSION_UNKNOWN
    assert len(unknown.evidence) == 2


def test_conflict_and_temporal_endpoints_are_atomic_under_small_budget() -> None:
    conflict = (
        _candidate("450", text="VF8 range 450 km", conflict_group_id="conflict-1"),
        _candidate("480", text="VF8 range 480 km", conflict_group_id="conflict-1"),
    )
    context = _build(
        "Are there conflicting figures for VF8?",
        (*conflict, _candidate("noise", text="x" * 100)),
        max_evidence_items=1,
        max_characters=10,
    )

    assert {item.chunk_id for item in context.evidence} == {"chunk-450", "chunk-480"}
    assert context.diagnostics.budget_overrun_for_mandatory_evidence is True
    conflict_bundle = next(
        item for item in context.bundles if item.bundle_type is EvidenceBundleType.CONFLICT_SET
    )
    assert len(conflict_bundle.evidence_ids) == 2
    assert context.diagnostics.conflict_pair_completeness == 1.0


def test_conditional_qualifier_selects_requested_protocol_without_false_conflict() -> None:
    candidates = (
        _candidate(
            "wltp",
            p4_relation_type="CONDITIONAL_VARIANT",
            conditional_variant_group_id="condition-1",
            test_protocol="WLTP",
        ),
        _candidate(
            "epa",
            p4_relation_type="CONDITIONAL_VARIANT",
            conditional_variant_group_id="condition-1",
            test_protocol="EPA",
        ),
    )

    explicit = _build("What is the WLTP range?", candidates)
    ambiguous = _build("What is the range?", candidates)

    assert {item.document_id for item in explicit.evidence} == {"doc-wltp"}
    assert len(ambiguous.evidence) == 2
    assert any(
        bundle.bundle_type is EvidenceBundleType.CONDITIONAL_SET for bundle in ambiguous.bundles
    )


def test_uncertain_evidence_is_retained_but_forces_controlled_uncertainty() -> None:
    context = _build(
        "What is the price?",
        (_candidate("u", p4_relation_type="UNCERTAIN"),),
    )

    assert len(context.evidence) == 1
    assert context.no_answer_reason is NoAnswerReason.LOW_CONFIDENCE_EVIDENCE


def test_unauthorized_candidate_cannot_enter_evidence_or_diagnostics_groups() -> None:
    visible = _candidate("visible", conflict_group_id="secret-conflict")
    hidden = _candidate("hidden", conflict_group_id="secret-conflict")
    context = build_generation_context(
        _query("Are sources conflicting?"),
        (visible, hidden),
        authorized_document_ids=frozenset({visible.chunk.document_id}),
    )

    assert {item.document_id for item in context.evidence} == {visible.chunk.document_id}
    assert context.diagnostics.conflict_pair_count == 0
    assert context.diagnostics.unauthorized_ids == (hidden.chunk.id,)
