"""Tests for backend-neutral ANN relation candidate aggregation."""

from dataclasses import replace
from uuid import UUID

from app.knowledge_quality.application.detection import (
    detect_document_relation_candidates,
)
from app.knowledge_quality.domain.models import ClaimScope, RelationType
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.pipeline.indexing.ports.vector_index import VectorSearchHit

SOURCE_ID = "30000000-0000-0000-0000-000000000003"
TARGET_ID = "40000000-0000-0000-0000-000000000004"


def _chunk(index: int, text: str) -> EmbeddedChunk:
    return EmbeddedChunk(
        id=f"source:{index}",
        document_id=SOURCE_ID,
        document_version=1,
        owner_id="owner-1",
        tenant_id="notebook-1",
        chunk_index=index,
        page_number=1,
        section_title=None,
        checksum=f"checksum-{index}",
        text=text,
        canonical_text=text,
        token_count=len(text.split()),
        embedding=(1.0, 0.0),
        embedding_model="test",
    )


class _ScriptedVectorIndex:
    def __init__(self, hits: list[list[VectorSearchHit]]) -> None:
        self.hits = list(hits)

    def query(
        self,
        embedding,
        *,
        owner_id,
        document_ids,
        limit,
        tenant_id=None,
    ):
        del embedding, document_ids
        assert owner_id == "owner-1"
        assert tenant_id == "notebook-1"
        assert limit == 3
        return self.hits.pop(0)


def _hit(
    text: str,
    score: float = 0.97,
    *,
    chunk_id: str = "target-chunk",
    page_number: int | None = 1,
    chunk_index: int | None = None,
) -> VectorSearchHit:
    return VectorSearchHit(
        chunk_id=chunk_id,
        document_id=TARGET_ID,
        score=score,
        text=text,
        page_number=page_number,
        section_title=None,
        document_version=1,
        chunk_index=chunk_index,
    )


def test_aggregates_high_coverage_chunk_matches_into_version_candidate() -> None:
    chunks = (
        _chunk(0, "The policy applies to all permanent employees."),
        _chunk(1, "Annual leave is twelve working days."),
        _chunk(2, "Managers approve leave through the HR portal."),
    )
    index = _ScriptedVectorIndex(
        [
            [_hit(chunks[0].text)],
            [_hit(chunks[1].text)],
            [_hit(chunks[2].text)],
        ]
    )

    candidates = detect_document_relation_candidates(
        vector_index=index,
        chunks=chunks,
        max_probe_chunks=3,
        candidates_per_probe=3,
    )

    assert len(candidates) == 1
    assert candidates[0].target_document_id == UUID(TARGET_ID)
    assert candidates[0].relation_type == RelationType.VERSION_CANDIDATE
    assert candidates[0].signals["document_probe_coverage"] == 1.0
    assert candidates[0].signals["selected_chunk_pair"] == {
        "probe_index": 0,
        "source_chunk_id": "source:0",
        "target_chunk_id": "target-chunk",
        "source_page_number": 1,
        "target_page_number": 1,
        "source_chunk_index": 0,
        "target_chunk_index": None,
    }


def test_ignores_self_hits_invalid_document_ids_and_low_coverage() -> None:
    chunks = tuple(
        _chunk(index, f"Distinct policy paragraph number {index}.") for index in range(4)
    )
    valid_hit = _hit(chunks[0].text)
    index = _ScriptedVectorIndex(
        [
            [
                replace(valid_hit, document_id=SOURCE_ID),
                replace(valid_hit, document_id="not-a-uuid"),
                valid_hit,
            ],
            [],
            [],
            [],
        ]
    )

    candidates = detect_document_relation_candidates(
        vector_index=index,
        chunks=chunks,
        max_probe_chunks=4,
        candidates_per_probe=3,
    )

    assert candidates == ()


def test_relation_coverage_and_confidence_use_only_selected_relation_type() -> None:
    chunks = (
        _chunk(0, "Revenue was 120 million USD."),
        _chunk(1, "The policy applies to all permanent employees."),
        _chunk(2, "Annual leave is twelve working days."),
        _chunk(3, "Managers approve leave through the HR portal."),
        _chunk(4, "Security training is completed each year."),
        _chunk(5, "Travel requests require manager approval."),
    )
    index = _ScriptedVectorIndex(
        [
            [
                _hit(
                    "Revenue was 120 billion USD.",
                    chunk_id="target-conflict",
                    page_number=90,
                    chunk_index=90,
                )
            ],
            [
                _hit(
                    chunks[1].text,
                    chunk_id="target-1",
                    page_number=11,
                    chunk_index=1,
                )
            ],
            [
                _hit(
                    chunks[2].text,
                    chunk_id="target-2",
                    page_number=12,
                    chunk_index=2,
                )
            ],
            [
                _hit(
                    chunks[3].text,
                    chunk_id="target-3",
                    page_number=13,
                    chunk_index=3,
                )
            ],
            [
                _hit(
                    chunks[4].text,
                    chunk_id="target-4",
                    page_number=14,
                    chunk_index=4,
                )
            ],
            [
                _hit(
                    chunks[5].text,
                    chunk_id="target-5",
                    page_number=15,
                    chunk_index=5,
                )
            ],
        ]
    )

    candidates = detect_document_relation_candidates(
        vector_index=index,
        chunks=chunks,
        max_probe_chunks=6,
        candidates_per_probe=3,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.relation_type == RelationType.VERSION_CANDIDATE
    assert candidate.signals["document_probe_coverage"] == 0.833333
    assert candidate.signals["matched_probe_count"] == 5
    assert candidate.signals["matched_chunk_pair_count"] == 5
    assert candidate.signals["relation_pair_counts"] == {
        "conflict_candidate": 1,
        "exact_content": 5,
    }
    assert candidate.signals["selected_chunk_pair"] == {
        "probe_index": 1,
        "source_chunk_id": "source:1",
        "target_chunk_id": "target-1",
        "source_page_number": 1,
        "target_page_number": 11,
        "source_chunk_index": 1,
        "target_chunk_index": 1,
    }
    assert candidate.confidence == 0.9583333333333334


def test_ann_aggregation_requires_same_scope_for_document_conflict() -> None:
    scope = ClaimScope(project_id="project-a").to_metadata()
    chunk = replace(
        _chunk(0, "Revenue was 120 million USD."),
        metadata={"claim_scope": scope},
    )
    hit = replace(
        _hit("Revenue was 121 million USD."),
        metadata={"claim_scope": scope},
    )

    candidates = detect_document_relation_candidates(
        vector_index=_ScriptedVectorIndex([[hit]]),
        chunks=(chunk,),
        max_probe_chunks=1,
        candidates_per_probe=3,
    )

    assert candidates[0].relation_type == RelationType.CONFLICT_CANDIDATE
    assert candidates[0].signals["validated_conflict_count"] == 1


def test_ann_different_scopes_are_template_variants() -> None:
    chunk = replace(
        _chunk(0, "Revenue was 120 million USD."),
        metadata={"claim_scope": ClaimScope(project_id="project-a").to_metadata()},
    )
    hit = replace(
        _hit("Revenue was 121 million USD."),
        metadata={"claim_scope": ClaimScope(project_id="project-b").to_metadata()},
    )

    candidates = detect_document_relation_candidates(
        vector_index=_ScriptedVectorIndex([[hit]]),
        chunks=(chunk,),
        max_probe_chunks=1,
        candidates_per_probe=3,
    )

    assert candidates[0].relation_type == RelationType.TEMPLATE_VARIANT
    assert candidates[0].signals["validated_conflict_count"] == 0
