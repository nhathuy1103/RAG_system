from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from app.knowledge_quality.application.persisted_relation_aggregation import (
    aggregate_persisted_claim_relations,
)
from app.structured_facts.domain.models import (
    ClaimProvenance,
    NormalizedValue,
    StructuredClaim,
)
from app.structured_facts.ports.repositories import StructuredClaimCandidate


def _claim(document_id: UUID, claim_id: str, predicate: str, value: str) -> StructuredClaim:
    return StructuredClaim(
        id=claim_id,
        document_id=str(document_id),
        subject_key="business-entity",
        predicate=predicate,
        value=NormalizedValue(value=Decimal(value), unit="unit"),
        provenance=ClaimProvenance(document_id=str(document_id)),
        extractor_version="p3-test-v1",
    )


def _candidate(
    document_id: UUID,
    snapshot_id: UUID,
    claim: StructuredClaim,
) -> StructuredClaimCandidate:
    return StructuredClaimCandidate(
        claim_id=uuid4(),
        snapshot_id=snapshot_id,
        document_id=document_id,
        document_version=1,
        snapshot_key="prior-snapshot",
        schema_fingerprint="a" * 64,
        template_fingerprint=None,
        normalized_schema={"source_form": "prose"},
        candidate_identity_hash=claim.candidate_identity_hash,
        claim=claim.to_payload(),
    )


def test_persisted_p3_edges_materialize_one_claim_grounded_p4_relation() -> None:
    owner_id = UUID("10000000-0000-0000-0000-000000000001")
    notebook_id = UUID("20000000-0000-0000-0000-000000000002")
    source_id = UUID("30000000-0000-0000-0000-000000000003")
    target_id = UUID("40000000-0000-0000-0000-000000000004")
    snapshot_id = UUID("50000000-0000-0000-0000-000000000005")
    source_price = _claim(source_id, "s-price", "property_price", "6.2")
    source_area = _claim(source_id, "s-area", "usable_area", "70")
    target_price = _claim(target_id, "t-price", "property_price", "7.1")
    target_area = _claim(target_id, "t-area", "usable_area", "70")
    target_fee = _claim(target_id, "t-fee", "management_fee", "20")
    current_payloads = tuple(
        {**claim.to_payload(), "claim_key": claim.id}
        for claim in (source_price, source_area)
    )
    candidates = tuple(
        _candidate(target_id, snapshot_id, claim)
        for claim in (target_price, target_area, target_fee)
    )
    common = {
        "target_snapshot_id": str(snapshot_id),
        "scope_relation": "same",
        "qualifier_compatibility": "equal",
        "temporal_relation": "same",
        "confidence": 1.0,
    }
    relations = (
        {
            **common,
            "source_claim_key": "s-price",
            "target_claim_key": "t-price",
            "relation_type": "conflict_candidate",
            "evidence": {
                "subject_key": "business-entity",
                "predicate": "property_price",
                "target_document_id": str(target_id),
                "reason_codes": ["normalized_values_conflict"],
            },
        },
        {
            **common,
            "source_claim_key": "s-area",
            "target_claim_key": "t-area",
            "relation_type": "unchanged",
            "evidence": {
                "subject_key": "business-entity",
                "predicate": "usable_area",
                "target_document_id": str(target_id),
                "reason_codes": ["normalized_values_equal"],
            },
        },
        {
            **common,
            "source_claim_key": None,
            "target_claim_key": "t-fee",
            "relation_type": "target_only",
            "evidence": {
                "subject_key": "business-entity",
                "predicate": "management_fee",
                "target_document_id": str(target_id),
                "reason_codes": ["target_only_claim"],
            },
        },
    )

    output = aggregate_persisted_claim_relations(
        owner_id=owner_id,
        notebook_id=notebook_id,
        source_document_id=source_id,
        current_claims=current_payloads,
        candidates=candidates,
        relation_payloads=relations,
    )

    assert len(output) == 1
    relation = output[0]
    assert relation.target_document_id == target_id
    assert relation.relation_type.value == "conflict"
    assert relation.signals["p4_primary_relation"] == "CONFLICT"
    assert relation.signals["p4_facets"]["has_conflict"] is True  # type: ignore[index]
    assert relation.signals["p4_facets"]["has_version_changes"] is True  # type: ignore[index]
    assert relation.signals["p4_claim_summary"]["added_count"] == 1  # type: ignore[index]
    assert len(relation.signals["p4_conflict_claims"]) == 1  # type: ignore[arg-type]
    assert relation.signals["p4_review_status"] == "pending"
