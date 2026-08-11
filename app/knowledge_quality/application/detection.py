"""Backend-neutral ANN candidate generation for document relationships."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.knowledge_quality.application.analysis import analyze_text_relation
from app.knowledge_quality.application.scope import extract_claim_scope, merge_claim_scopes
from app.knowledge_quality.domain.models import (
    DETECTOR_VERSION,
    ClaimScope,
    QualityRelationCandidate,
    RelationType,
    ScopeComparison,
    TextRelationAnalysis,
)
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.pipeline.indexing.ports.vector_index import VectorIndex, VectorSearchHit

_RELATION_PRIORITY = {
    RelationType.CONFLICT_CANDIDATE: 6,
    RelationType.VERSION_CANDIDATE: 5,
    RelationType.TEMPORAL_SERIES: 4,
    RelationType.NEAR_DUPLICATE: 3,
    RelationType.TEMPLATE_VARIANT: 2,
    RelationType.EXACT_CONTENT: 1,
    RelationType.DISTINCT: 0,
}


@dataclass(frozen=True, slots=True)
class _PairEvidence:
    probe_index: int
    source_chunk_id: str
    target_chunk_id: str
    source_page_number: int | None
    target_page_number: int | None
    source_chunk_index: int | None
    target_chunk_index: int | None
    analysis: TextRelationAnalysis


@dataclass(slots=True)
class _Aggregate:
    target_document_id: UUID
    evidence: list[_PairEvidence] = field(default_factory=list)

    def add(
        self,
        probe_index: int,
        source: EmbeddedChunk,
        target: VectorSearchHit,
        analysis: TextRelationAnalysis,
    ) -> None:
        self.evidence.append(
            _PairEvidence(
                probe_index=probe_index,
                source_chunk_id=source.id,
                target_chunk_id=target.chunk_id,
                source_page_number=source.page_number,
                target_page_number=target.page_number,
                source_chunk_index=source.chunk_index,
                target_chunk_index=target.chunk_index,
                analysis=analysis,
            )
        )


def detect_document_relation_candidates(
    *,
    vector_index: VectorIndex,
    chunks: tuple[EmbeddedChunk, ...],
    max_probe_chunks: int = 8,
    candidates_per_probe: int = 5,
) -> tuple[QualityRelationCandidate, ...]:
    """Probe existing vectors and return conservative document-level candidates."""
    if not chunks or max_probe_chunks <= 0 or candidates_per_probe <= 0:
        return ()

    probes = _sample_chunks(chunks, max_probe_chunks)
    source_document_id = chunks[0].document_id
    source_scope = _chunk_scope(chunks[0])
    owner_id = chunks[0].owner_id
    aggregates: dict[UUID, _Aggregate] = {}

    for probe_index, chunk in enumerate(probes):
        hits = vector_index.query(
            chunk.embedding,
            owner_id=owner_id,
            document_ids=None,
            limit=candidates_per_probe,
            tenant_id=chunk.tenant_id,
        )
        for hit in hits:
            if hit.document_id == source_document_id:
                continue
            try:
                target_document_id = UUID(hit.document_id)
            except ValueError:
                continue
            analysis = analyze_text_relation(
                chunk.text,
                hit.text,
                semantic_similarity=hit.score,
                left_scope=source_scope,
                right_scope=_hit_scope(hit),
            )
            if analysis.relation_type == RelationType.DISTINCT:
                continue
            aggregate = aggregates.setdefault(
                target_document_id,
                _Aggregate(target_document_id=target_document_id),
            )
            aggregate.add(probe_index, chunk, hit, analysis)

    results: list[QualityRelationCandidate] = []
    probe_count = len(probes)
    for aggregate in aggregates.values():
        relation_groups: dict[RelationType, list[_PairEvidence]] = {}
        for pair in aggregate.evidence:
            relation_groups.setdefault(pair.analysis.relation_type, []).append(pair)
        temporal_pair_count = sum(
            pair.analysis.scope_comparison is ScopeComparison.TEMPORAL_DIVERGENCE
            for pair in aggregate.evidence
        )
        temporal_majority = temporal_pair_count * 2 > len(aggregate.evidence)

        selected_group: list[_PairEvidence] | None = None
        relation_type: RelationType | None = None
        coverage = 0.0
        ordered_groups = sorted(
            relation_groups.items(),
            key=lambda item: _RELATION_PRIORITY[item[0]],
            reverse=True,
        )
        for detected_type, pairs in ordered_groups:
            if detected_type == RelationType.CONFLICT_CANDIDATE:
                if temporal_majority:
                    continue
                pairs = [
                    pair
                    for pair in pairs
                    if pair.analysis.validated_conflict_count > 0
                    and pair.analysis.scope_comparison is ScopeComparison.SAME_SCOPE
                ]
                pairs = _deduplicate_conflict_pairs(pairs)
                if not pairs:
                    continue
            matched_probe_indexes = {pair.probe_index for pair in pairs}
            candidate_coverage = len(matched_probe_indexes) / probe_count
            candidate_type = detected_type
            if detected_type == RelationType.EXACT_CONTENT:
                candidate_type = (
                    RelationType.VERSION_CANDIDATE
                    if candidate_coverage >= 0.65
                    else RelationType.NEAR_DUPLICATE
                )
            minimum_coverage = 0.0 if candidate_type == RelationType.CONFLICT_CANDIDATE else 0.35
            if candidate_coverage >= minimum_coverage:
                selected_group = pairs
                relation_type = candidate_type
                coverage = candidate_coverage
                break

        if selected_group is None or relation_type is None:
            continue

        selected_pair = max(
            selected_group,
            key=lambda pair: pair.analysis.confidence,
        )
        selected = selected_pair.analysis
        matched_probe_indexes = {pair.probe_index for pair in selected_group}
        mean_confidence = sum(pair.analysis.confidence for pair in selected_group) / len(
            selected_group
        )
        confidence = min(0.99, 0.75 * mean_confidence + 0.25 * coverage)
        signals = selected.to_signals()
        signals.update(
            {
                "document_probe_coverage": round(coverage, 6),
                "matched_probe_count": len(matched_probe_indexes),
                "probe_count": probe_count,
                "matched_chunk_pair_count": len(selected_group),
                "temporal_divergence_pair_count": temporal_pair_count,
                "temporal_divergence_ratio": round(
                    temporal_pair_count / len(aggregate.evidence),
                    6,
                ),
                "temporal_majority_guard_applied": temporal_majority,
                "validated_conflict_count": sum(
                    pair.analysis.validated_conflict_count for pair in selected_group
                ),
                "relation_pair_counts": {
                    detected_type.value: len(pairs)
                    for detected_type, pairs in relation_groups.items()
                },
                "selected_chunk_pair": {
                    "probe_index": selected_pair.probe_index,
                    "source_chunk_id": selected_pair.source_chunk_id,
                    "target_chunk_id": selected_pair.target_chunk_id,
                    "source_page_number": selected_pair.source_page_number,
                    "target_page_number": selected_pair.target_page_number,
                    "source_chunk_index": selected_pair.source_chunk_index,
                    "target_chunk_index": selected_pair.target_chunk_index,
                },
            }
        )
        results.append(
            QualityRelationCandidate(
                target_document_id=aggregate.target_document_id,
                relation_type=relation_type,
                confidence=confidence,
                signals=signals,
                reason=";".join(selected.reason_codes) or None,
                detector_version=DETECTOR_VERSION,
            )
        )

    results.sort(key=lambda item: item.confidence, reverse=True)
    return tuple(results)


def _chunk_scope(chunk: EmbeddedChunk) -> ClaimScope:
    persisted = ClaimScope.from_metadata(chunk.metadata.get("claim_scope"))
    fallback = extract_claim_scope(
        chunk.text,
        document_id=chunk.document_id,
        version_id=str(chunk.document_version),
    )
    return merge_claim_scopes(persisted, fallback) or fallback


def _hit_scope(hit: VectorSearchHit) -> ClaimScope:
    persisted = ClaimScope.from_metadata(hit.metadata.get("claim_scope"))
    fallback = extract_claim_scope(
        hit.text,
        document_id=hit.document_id,
        version_id=str(hit.document_version),
    )
    return merge_claim_scopes(persisted, fallback) or fallback


def _deduplicate_conflict_pairs(pairs: list[_PairEvidence]) -> list[_PairEvidence]:
    selected: dict[tuple[str, ...], _PairEvidence] = {}
    for pair in pairs:
        conflict = max(pair.analysis.claim_conflicts, key=lambda item: item.alignment_score)
        claim_key = conflict.left_claim.claim_key
        evidence_key = (
            claim_key.canonical_evidence_key()
            if claim_key is not None
            else (conflict.left_claim.alignment_key,)
        )
        previous = selected.get(evidence_key)
        if previous is None or pair.analysis.confidence > previous.analysis.confidence:
            selected[evidence_key] = pair
    return list(selected.values())


def _sample_chunks(
    chunks: tuple[EmbeddedChunk, ...],
    maximum: int,
) -> tuple[EmbeddedChunk, ...]:
    if len(chunks) <= maximum:
        return chunks
    if maximum == 1:
        return (chunks[len(chunks) // 2],)
    indexes = {round(position * (len(chunks) - 1) / (maximum - 1)) for position in range(maximum)}
    return tuple(chunks[index] for index in sorted(indexes))


__all__ = ["detect_document_relation_candidates"]
