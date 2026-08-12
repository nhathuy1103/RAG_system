import json
from datetime import date
from uuid import UUID

import httpx2 as httpx
import pytest

from app.knowledge_quality.domain.models import QualityRelationCandidate, RelationType
from app.structured_facts.adapters.postgrest_repository import (
    PostgrestStructuredFactRepository,
)
from app.structured_facts.ports.repositories import StructuredFactSearch


@pytest.mark.anyio
async def test_replaces_structured_facts_through_guarded_rpc() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/replace_structured_facts_for_document")
        body = request.read()
        assert b'"p_extractor_version":"structured-table-v1"' in body
        assert b'"p_claims":[{"id":"claim-1"}]' in body
        return httpx.Response(
            200,
            json={"table_count": 1, "claim_count": 1, "relation_count": 0},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        result = await PostgrestStructuredFactRepository(client).replace_for_document(
            job_id=UUID("10000000-0000-0000-0000-000000000001"),
            document_id=UUID("20000000-0000-0000-0000-000000000002"),
            extractor_version="structured-table-v1",
            table_snapshots=({"table_id": "table-1"},),
            claims=({"id": "claim-1"},),
        )

    assert result.table_count == 1
    assert result.claim_count == 1


@pytest.mark.anyio
async def test_replaces_p4_document_relations_through_atomic_rpc() -> None:
    target_id = UUID("30000000-0000-0000-0000-000000000003")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/replace_p4_document_relations")
        body = json.loads(request.read())
        assert body["p_source_document_id"] == "20000000-0000-0000-0000-000000000002"
        assert body["p_detector_version"] == "p4-relation-aggregation-v1"
        assert body["p_relations"][0]["target_document_id"] == str(target_id)
        assert body["p_relations"][0]["signals"]["p4_review_status"] == "pending"
        return httpx.Response(200, json=1)

    relation = QualityRelationCandidate(
        target_document_id=target_id,
        relation_type=RelationType.CONFLICT,
        confidence=0.91,
        signals={"p4_review_status": "pending"},
        reason="overlapping_value_conflict",
        detector_version="p4-relation-aggregation-v1",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        count = await PostgrestStructuredFactRepository(client).replace_p4_relations(
            source_document_id=UUID("20000000-0000-0000-0000-000000000002"),
            detector_version="p4-relation-aggregation-v1",
            relations=(relation,),
        )

    assert count == 1


@pytest.mark.anyio
async def test_searches_user_scoped_structured_claims() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/search_structured_claims")
        body = json.loads(request.read())
        assert body["p_qualifiers"] == {
            "stable": {"price_type": "discounted_price"},
            "optional": {"vat_included": True},
        }
        assert body["p_valid_from"] == "2025-03-01T00:00:00+00:00"
        assert body["p_valid_to"] == "2025-03-31T23:59:59.999999+00:00"
        return httpx.Response(
            200,
            json=[
                {
                    "claim_id": "claim-1",
                    "document_id": "20000000-0000-0000-0000-000000000002",
                    "source_chunk_id": "30000000-0000-0000-0000-000000000003",
                    "document_version": 2,
                    "subject_key": "project=ocean-park|building=s1|unit=a101",
                    "predicate": "sale_price",
                    "normalized_value": {"value": "4500000000", "currency": "VND"},
                    "qualifiers": {"stable": {"price_type": "list_price"}},
                    "temporal": {"effective_from": "2025-03-01T00:00:00+00:00"},
                    "provenance": {"table_id": "table-1", "row_index": 4},
                    "authority_metadata": {
                        "source_type": "official_price_list",
                        "publisher": "Developer A",
                        "authority_level": 90,
                        "approval_status": "approved",
                        "metadata": {"channel": "signed_portal"},
                    },
                    "confidence": 0.98,
                    "relation_warnings": [
                        {
                            "relation_id": "70000000-0000-0000-0000-000000000007",
                            "relation_type": "conflict_candidate",
                            "review_status": "pending",
                            "confidence": 0.91,
                        },
                        "malformed-warning-is-ignored",
                    ],
                }
            ],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        evidence = await PostgrestStructuredFactRepository(client).search(
            StructuredFactSearch(
                notebook_id=UUID("40000000-0000-0000-0000-000000000004"),
                document_ids=(UUID("20000000-0000-0000-0000-000000000002"),),
                predicate="sale_price",
                subject_query="a101",
                valid_from=date(2025, 3, 1),
                valid_to=date(2025, 3, 31),
                qualifiers={
                    "stable": {"price_type": "discounted_price"},
                    "optional": {"vat_included": True},
                },
            )
        )

    assert evidence[0].source_chunk_id == UUID("30000000-0000-0000-0000-000000000003")
    assert evidence[0].document_version == 2
    assert evidence[0].authority == {
        "source_type": "official_price_list",
        "publisher": "Developer A",
        "authority_level": 90,
        "approval_status": "approved",
        "metadata": {"channel": "signed_portal"},
    }
    assert evidence[0].relation_warnings == (
        {
            "relation_id": "70000000-0000-0000-0000-000000000007",
            "relation_type": "conflict_candidate",
            "review_status": "pending",
            "confidence": 0.91,
        },
    )


@pytest.mark.anyio
async def test_loads_claim_candidates_with_schema_context() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rpc/load_structured_claim_candidates")
        body = json.loads(request.read())
        assert body == {
            "p_notebook_id": "40000000-0000-0000-0000-000000000004",
            "p_document_id": "20000000-0000-0000-0000-000000000002",
            "p_candidate_hashes": ["candidate-a", "candidate-b"],
            "p_limit": 17,
            "p_schema_fingerprints": ["schema-a", "schema-b"],
        }
        return httpx.Response(
            200,
            json=[
                {
                    "claim_id": "10000000-0000-0000-0000-000000000001",
                    "snapshot_id": "50000000-0000-0000-0000-000000000005",
                    "document_id": "60000000-0000-0000-0000-000000000006",
                    "document_version": 3,
                    "snapshot_key": "table:sale-price:2025-03",
                    "schema_fingerprint": "schema-a",
                    "template_fingerprint": "template-v2",
                    "normalized_schema": {"columns": ["unit", "sale_price", "effective_month"]},
                    "candidate_identity_hash": "candidate-a",
                    "claim": {
                        "id": "domain-claim-1",
                        "claim_identity_hash": "claim-identity-1",
                        "predicate": "sale_price",
                    },
                }
            ],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        candidates = await PostgrestStructuredFactRepository(client).load_claim_candidates(
            notebook_id=UUID("40000000-0000-0000-0000-000000000004"),
            document_id=UUID("20000000-0000-0000-0000-000000000002"),
            candidate_identity_hashes=(
                "candidate-b",
                "candidate-a",
                "candidate-a",
            ),
            schema_fingerprints=("schema-b", "schema-a", "schema-b"),
            limit=17,
        )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.claim_id == UUID("10000000-0000-0000-0000-000000000001")
    assert candidate.snapshot_id == UUID("50000000-0000-0000-0000-000000000005")
    assert candidate.document_id == UUID("60000000-0000-0000-0000-000000000006")
    assert candidate.document_version == 3
    assert candidate.schema_fingerprint == "schema-a"
    assert candidate.template_fingerprint == "template-v2"
    assert candidate.normalized_schema == {"columns": ["unit", "sale_price", "effective_month"]}
    assert candidate.candidate_identity_hash == "candidate-a"
    assert candidate.claim["claim_identity_hash"] == "claim-identity-1"
