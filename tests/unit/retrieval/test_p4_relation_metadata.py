from __future__ import annotations

import json
from collections.abc import Mapping

import httpx2 as httpx

from app.retrieval.adapters.postgrest_relation_metadata import (
    PostgrestRelationMetadataAdapter,
)
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate, RetrievalFilters

SOURCE = "10000000-0000-0000-0000-000000000001"
TARGET = "20000000-0000-0000-0000-000000000002"
HIDDEN = "30000000-0000-0000-0000-000000000003"
OWNER = "40000000-0000-0000-0000-000000000004"
NOTEBOOK = "50000000-0000-0000-0000-000000000005"


def _candidate(chunk_id: str, document_id: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=EvidenceChunk(
            id=chunk_id,
            document_id=document_id,
            text=f"evidence {chunk_id}",
            metadata={"owner_id": OWNER, "notebook_id": NOTEBOOK},
        ),
        score=1.0,
        rank=1,
    )


def test_relation_metadata_enrichment_uses_only_fully_visible_edges() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["owner_id"] == f"eq.{OWNER}"
        assert request.url.params["notebook_id"] == f"eq.{NOTEBOOK}"
        if request.url.path.endswith("/documents"):
            return httpx.Response(
                200,
                json=[
                    {"id": SOURCE, "version_number": 1, "is_current": False, "status": "ready"},
                    {"id": TARGET, "version_number": 2, "is_current": True, "status": "ready"},
                ],
            )
        assert request.url.path.endswith("/document_relations")
        return httpx.Response(
            200,
            json=[
                {
                    "source_document_id": SOURCE,
                    "target_document_id": TARGET,
                    "relation_type": "conflict",
                    "status": "pending",
                    "detector_version": "p4-relation-aggregation-v1",
                    "preferred_document_id": SOURCE,
                    "signals": {
                        "p4_primary_relation": "CONFLICT",
                        "p4_facets": {"has_conflict": True, "has_version_changes": True},
                        "p4_preference": {"document_id": SOURCE},
                        "p4_versions": {"retrieval": "p4-relation-retrieval-v1"},
                    },
                },
                {
                    "source_document_id": SOURCE,
                    "target_document_id": HIDDEN,
                    "relation_type": "exact_content",
                    "status": "auto_confirmed",
                    "detector_version": "p4-relation-aggregation-v1",
                    "preferred_document_id": None,
                    "signals": {"p4_primary_relation": "EXACT_DUPLICATE"},
                },
            ],
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        enriched = PostgrestRelationMetadataAdapter(client).enrich(
            (_candidate("source-chunk", SOURCE), _candidate("target-chunk", TARGET)),
            RetrievalFilters(owner_id=OWNER, notebook_id=NOTEBOOK),
        )

    for candidate in enriched:
        metadata: Mapping[str, object] = candidate.chunk.metadata
        assert metadata["p4_relation_type"] == "CONFLICT"
        assert str(metadata["conflict_group_id"]).startswith("p4-conflict-")
        assert str(metadata["version_family_id"]).startswith("p4-version-")
        assert "p4_exact_duplicate_group_id" not in metadata
        assert HIDDEN not in json.dumps(dict(metadata))
    assert enriched[0].chunk.metadata["p4_preferred_evidence"] is True
    assert "p4_preferred_evidence" not in enriched[1].chunk.metadata
    assert enriched[0].chunk.metadata["version_number"] == 1
    assert enriched[0].chunk.metadata["is_current"] is False
    assert enriched[1].chunk.metadata["version_number"] == 2
    assert enriched[1].chunk.metadata["is_current"] is True


def test_relation_metadata_enrichment_reads_canonical_enterprise_edges() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/knowledge_document_relations")
        assert "owner_id" not in request.url.params
        assert "notebook_id" not in request.url.params
        return httpx.Response(
            200,
            json=[
                {
                    "source_document_id": SOURCE,
                    "target_document_id": TARGET,
                    "relation_type": "conflict",
                    "status": "pending",
                    "detector_version": "knowledge-quality-v4",
                    "preferred_document_id": None,
                    "signals": {
                        "p4_primary_relation": "CONFLICT",
                        "p4_review_status": "pending",
                    },
                }
            ],
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://supabase.test/rest/v1",
    ) as client:
        enriched = PostgrestRelationMetadataAdapter(client).enrich(
            (_candidate("source-chunk", SOURCE), _candidate("target-chunk", TARGET)),
            RetrievalFilters(owner_id=OWNER, notebook_id=None),
        )

    for candidate in enriched:
        assert candidate.chunk.metadata["p4_relation_type"] == "CONFLICT"
        assert str(candidate.chunk.metadata["conflict_group_id"]).startswith(
            "p4-conflict-"
        )
