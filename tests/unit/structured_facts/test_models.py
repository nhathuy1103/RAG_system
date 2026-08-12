"""Serialization, identity, provenance, and derivation model tests."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.structured_facts.domain.models import (
    BusinessScope,
    ClaimDerivation,
    ClaimProvenance,
    ClaimQualifiers,
    ClaimRelation,
    ClaimRelationType,
    CommercialScope,
    LocationScope,
    NormalizedValue,
    QualifierCompatibility,
    ScopeRelation,
    SourceAuthority,
    StructuredClaim,
    TemporalContext,
    TemporalRelation,
)


def _claim(*, vat_included: bool | None = True) -> StructuredClaim:
    optional = {"vat_included": vat_included} if vat_included is not None else {}
    return StructuredClaim(
        id="claim-1",
        owner_id=None,
        notebook_id=None,
        document_id="doc-1",
        subject_key="ocean-park/s1/a101",
        predicate="sale_price",
        value=NormalizedValue(
            value=Decimal("4500000000.00"),
            unit="VND",
            currency="VND",
            basis="total_unit",
            raw_value="4,5 tá»·",
        ),
        scope=BusinessScope(
            location=LocationScope(project="Ocean Park", building="S1", unit="A101"),
            commercial=CommercialScope(price_type="list_price", price_basis="total_unit"),
            document_type="price_list",
        ),
        qualifiers=ClaimQualifiers.from_mappings(
            stable={"price_type": "list_price", "price_basis": "total_unit"},
            optional=optional,
        ),
        temporal=TemporalContext(
            publication_time=datetime(2026, 2, 25, tzinfo=UTC),
            effective_from=date(2026, 3, 1),
        ),
        provenance=ClaimProvenance(
            document_id="doc-1",
            table_id="table-1",
            row_index=14,
            data_row_ordinal=13,
            column_name="GiÃ¡ niÃªm yáº¿t",
            cell_id="R15C7",
            page_number=2,
            source_span=(100, 113),
        ),
        extraction_confidence=0.97,
        extractor_version="structured-price-v1",
        derivation=ClaimDerivation(
            formula="price_per_m2 * carpet_area",
            input_claim_ids=("price-m2-1", "area-1"),
            absolute_tolerance=Decimal("10000000"),
            relative_tolerance=Decimal("0.002"),
        ),
    )


def test_structured_claim_payload_is_json_serializable_and_auditable() -> None:
    claim = _claim()

    payload = claim.to_payload()

    json.dumps(payload)
    value_payload = payload["value"]
    temporal_payload = payload["temporal"]
    provenance_payload = payload["provenance"]
    assert isinstance(value_payload, dict)
    assert isinstance(temporal_payload, dict)
    assert isinstance(provenance_payload, dict)
    assert value_payload["value"] == "4500000000"
    assert temporal_payload["effective_from"] == "2026-03-01"
    assert provenance_payload["source_span"] == {"start": 100, "end": 113}
    assert provenance_payload["data_row_ordinal"] == 13
    assert payload["derivation"] == {
        "formula": "price_per_m2 * carpet_area",
        "input_claim_ids": ["price-m2-1", "area-1"],
        "absolute_tolerance": "10000000",
        "relative_tolerance": "0.002",
    }
    candidate_identity_hash = payload["candidate_identity_hash"]
    claim_identity_hash = payload["claim_identity_hash"]
    assert isinstance(candidate_identity_hash, str)
    assert isinstance(claim_identity_hash, str)
    assert len(candidate_identity_hash) == 64
    assert len(claim_identity_hash) == 64


def test_structured_claim_payload_round_trip_preserves_identity() -> None:
    claim = _claim()
    payload = claim.to_payload()

    restored = StructuredClaim.from_payload(payload)

    assert restored.to_payload() == payload
    assert restored.candidate_identity_hash == claim.candidate_identity_hash
    assert restored.claim_identity_hash == claim.claim_identity_hash


@pytest.mark.parametrize(
    "mutation",
    (
        {"document_id": ""},
        {"subject_key": None},
        {"value": {"value": "not-a-number", "value_type": "decimal"}},
        {"extraction_confidence": "high"},
        {"provenance": {"document_id": "another-document"}},
    ),
)
def test_structured_claim_from_payload_rejects_malformed_evidence(
    mutation: dict[str, object],
) -> None:
    payload = _claim().to_payload()
    payload.update(mutation)

    with pytest.raises(ValueError):
        StructuredClaim.from_payload(payload)


def test_optional_qualifier_changes_claim_identity_but_not_candidate_key() -> None:
    vat_included = _claim(vat_included=True)
    vat_excluded = _claim(vat_included=False)

    assert vat_included.candidate_identity_hash == vat_excluded.candidate_identity_hash
    assert vat_included.claim_identity_hash != vat_excluded.claim_identity_hash


def test_value_or_provenance_changes_claim_identity() -> None:
    claim = _claim()
    changed = StructuredClaim(
        document_id=claim.document_id,
        subject_key=claim.subject_key,
        predicate=claim.predicate,
        value=NormalizedValue(value=Decimal("4600000000"), currency="VND"),
        provenance=claim.provenance,
        extractor_version=claim.extractor_version,
        scope=claim.scope,
        qualifiers=claim.qualifiers,
        temporal=claim.temporal,
    )

    assert claim.candidate_identity_hash == changed.candidate_identity_hash
    assert claim.claim_identity_hash != changed.claim_identity_hash


def test_source_authority_is_post_comparability_metadata() -> None:
    claim = _claim()
    official = replace(
        claim,
        authority=SourceAuthority.from_mapping(
            source_type="developer_price_list",
            publisher="Vinhomes",
            approval_status="approved",
            officiality="official",
            authority_level=90,
            metadata={"signed": True},
        ),
    )
    third_party = replace(
        claim,
        authority=SourceAuthority(
            source_type="broker_listing",
            officiality="unofficial",
            authority_level=20,
        ),
    )

    assert official.candidate_identity_hash == third_party.candidate_identity_hash
    assert official.claim_identity_hash == third_party.claim_identity_hash
    assert official.to_payload()["authority"] == {
        "source_type": "developer_price_list",
        "publisher": "Vinhomes",
        "approval_status": "approved",
        "officiality": "official",
        "authority_level": 90,
        "metadata": {"signed": True},
    }


def test_authority_level_is_bounded() -> None:
    with pytest.raises(ValueError, match="authority_level"):
        SourceAuthority(authority_level=101)


def test_claim_and_provenance_document_must_match() -> None:
    with pytest.raises(ValueError, match="document_id must match"):
        StructuredClaim(
            document_id="doc-1",
            subject_key="unit-a101",
            predicate="sale_price",
            value=NormalizedValue(value=1),
            provenance=ClaimProvenance(document_id="doc-2"),
            extractor_version="v1",
        )


@pytest.mark.parametrize("confidence", (-0.01, 1.01, float("nan")))
def test_extraction_confidence_is_bounded(confidence: float) -> None:
    with pytest.raises(ValueError, match="extraction_confidence"):
        StructuredClaim(
            document_id="doc-1",
            subject_key="unit-a101",
            predicate="sale_price",
            value=NormalizedValue(value=1),
            provenance=ClaimProvenance(document_id="doc-1"),
            extractor_version="v1",
            extraction_confidence=confidence,
        )


def test_invalid_provenance_and_tolerances_are_rejected() -> None:
    with pytest.raises(ValueError, match="row_index"):
        ClaimProvenance(document_id="doc-1", row_index=-1)
    with pytest.raises(ValueError, match="relative_tolerance"):
        ClaimDerivation(formula="a * b", relative_tolerance=Decimal("-0.1"))


def test_claim_relation_has_json_safe_explanation() -> None:
    relation = ClaimRelation(
        relation_type=ClaimRelationType.CONFLICT_CANDIDATE,
        source_claim_id="claim-old",
        target_claim_id="claim-new",
        subject_key="ocean-park/s1/a101",
        predicate="sale_price",
        confidence=0.93,
        reason_codes=("same_subject", "overlapping_effective_interval", "value_mismatch"),
        scope_relation=ScopeRelation.SAME,
        qualifier_compatibility=QualifierCompatibility.EQUAL,
        temporal_relation=TemporalRelation.OVERLAPS,
    )

    assert relation.to_payload()["relation_type"] == "conflict_candidate"
    json.dumps(relation.to_payload())
