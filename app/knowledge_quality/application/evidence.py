"""Reviewer-facing evidence assembly for document relations."""

from __future__ import annotations

from dataclasses import replace

from app.knowledge_quality.application.analysis import analyze_text_relation
from app.knowledge_quality.domain.models import (
    DocumentRelation,
    RelationEvidenceChunk,
    RelationEvidenceChunkPair,
    RelationType,
    TextRelationAnalysis,
)

_PAIR_PRIORITY = {
    RelationType.CONFLICT_CANDIDATE.value: 7,
    RelationType.VERSION_CANDIDATE.value: 6,
    RelationType.TEMPORAL_SERIES.value: 5,
    RelationType.NEAR_DUPLICATE.value: 4,
    RelationType.TEMPLATE_VARIANT.value: 3,
    RelationType.EXACT_CONTENT.value: 2,
    RelationType.RELATED.value: 1,
    RelationType.DISTINCT.value: 0,
}


def build_relation_chunk_pairs(
    relation: DocumentRelation,
    source_chunks: tuple[RelationEvidenceChunk, ...],
    target_chunks: tuple[RelationEvidenceChunk, ...],
) -> tuple[RelationEvidenceChunkPair, ...]:
    """Align chunks into exact, changed, conflict, and one-sided evidence."""
    if not source_chunks and not target_chunks:
        return ()

    used_source: set[str] = set()
    used_target: set[str] = set()
    pairs: list[RelationEvidenceChunkPair] = []

    for source, target in _exact_group_pairs(source_chunks, target_chunks):
        if source.id in used_source or target.id in used_target:
            continue
        pairs.append(_exact_pair(source, target))
        used_source.add(source.id)
        used_target.add(target.id)

    selected_pair = _selected_chunk_pair(relation, source_chunks, target_chunks)
    if selected_pair is not None:
        source, target = selected_pair
        if source.id not in used_source and target.id not in used_target:
            pairs.append(_analyzed_pair(source, target, relation=relation))
            used_source.add(source.id)
            used_target.add(target.id)

    candidates: list[tuple[tuple[float, float, float, int, int], RelationEvidenceChunkPair]] = []
    for source in source_chunks:
        if source.id in used_source:
            continue
        for target in target_chunks:
            if target.id in used_target:
                continue
            analysis = analyze_text_relation(source.content, target.content)
            if (
                analysis.relation_type == RelationType.DISTINCT
                and max(analysis.lexical_similarity, analysis.containment) < 0.45
            ):
                continue
            pair = _pair_from_analysis(source, target, analysis)
            candidates.append(
                (
                    _candidate_sort_key(pair, source.chunk_index, target.chunk_index),
                    pair,
                )
            )

    for _, pair in sorted(candidates, key=lambda item: item[0], reverse=True):
        candidate_source = pair.source_chunk
        candidate_target = pair.target_chunk
        if candidate_source is None or candidate_target is None:
            continue
        if candidate_source.id in used_source or candidate_target.id in used_target:
            continue
        pairs.append(pair)
        used_source.add(candidate_source.id)
        used_target.add(candidate_target.id)

    for source in source_chunks:
        if source.id not in used_source:
            pairs.append(
                RelationEvidenceChunkPair(
                    source_chunk=source,
                    target_chunk=None,
                    evidence_type="source_only",
                    confidence=1.0,
                    signals={"added_content": True},
                    reason="content_only_in_source_document",
                )
            )
    for target in target_chunks:
        if target.id not in used_target:
            pairs.append(
                RelationEvidenceChunkPair(
                    source_chunk=None,
                    target_chunk=target,
                    evidence_type="target_only",
                    confidence=1.0,
                    signals={"removed_content": True},
                    reason="content_only_in_target_document",
                )
            )

    return tuple(sorted(pairs, key=_pair_display_key))


def _exact_group_pairs(
    source_chunks: tuple[RelationEvidenceChunk, ...],
    target_chunks: tuple[RelationEvidenceChunk, ...],
) -> tuple[tuple[RelationEvidenceChunk, RelationEvidenceChunk], ...]:
    targets_by_group: dict[str, list[RelationEvidenceChunk]] = {}
    for target in target_chunks:
        group_id = target.exact_duplicate_group_id
        if group_id:
            targets_by_group.setdefault(group_id, []).append(target)

    pairs: list[tuple[RelationEvidenceChunk, RelationEvidenceChunk]] = []
    for source in source_chunks:
        group_id = source.exact_duplicate_group_id
        if not group_id:
            continue
        candidates = targets_by_group.get(group_id)
        if not candidates:
            continue
        target = min(
            candidates,
            key=lambda item: abs(item.chunk_index - source.chunk_index),
        )
        candidates.remove(target)
        pairs.append((source, target))
    return tuple(pairs)


def _selected_chunk_pair(
    relation: DocumentRelation,
    source_chunks: tuple[RelationEvidenceChunk, ...],
    target_chunks: tuple[RelationEvidenceChunk, ...],
) -> tuple[RelationEvidenceChunk, RelationEvidenceChunk] | None:
    selected = relation.signals.get("selected_chunk_pair")
    if not isinstance(selected, dict):
        return None
    source = _find_selected_chunk(
        source_chunks,
        chunk_id=selected.get("source_chunk_id"),
        chunk_index=selected.get("source_chunk_index"),
    )
    target = _find_selected_chunk(
        target_chunks,
        chunk_id=selected.get("target_chunk_id"),
        chunk_index=selected.get("target_chunk_index"),
    )
    if source is None or target is None:
        return None
    return source, target


def _find_selected_chunk(
    chunks: tuple[RelationEvidenceChunk, ...],
    *,
    chunk_id: object,
    chunk_index: object,
) -> RelationEvidenceChunk | None:
    if isinstance(chunk_id, str):
        for chunk in chunks:
            if chunk.id == chunk_id:
                return chunk
    if isinstance(chunk_index, int):
        for chunk in chunks:
            if chunk.chunk_index == chunk_index:
                return chunk
    return None


def _analyzed_pair(
    source: RelationEvidenceChunk,
    target: RelationEvidenceChunk,
    *,
    relation: DocumentRelation,
) -> RelationEvidenceChunkPair:
    semantic = relation.signals.get("semantic_similarity")
    analysis = analyze_text_relation(
        source.content,
        target.content,
        semantic_similarity=semantic if isinstance(semantic, int | float) else None,
    )
    pair = _pair_from_analysis(source, target, analysis)
    if (
        relation.relation_type == RelationType.CONFLICT_CANDIDATE
        and pair.evidence_type == RelationType.DISTINCT.value
    ):
        signals = dict(pair.signals)
        signals["relation_level_conflict"] = True
        return replace(
            pair,
            evidence_type=RelationType.CONFLICT_CANDIDATE.value,
            confidence=max(pair.confidence, relation.confidence),
            signals=signals,
            reason=relation.reason or pair.reason,
        )
    return pair


def _pair_from_analysis(
    source: RelationEvidenceChunk,
    target: RelationEvidenceChunk,
    analysis: TextRelationAnalysis,
) -> RelationEvidenceChunkPair:
    return RelationEvidenceChunkPair(
        source_chunk=source,
        target_chunk=target,
        evidence_type=analysis.relation_type.value,
        confidence=analysis.confidence,
        signals=analysis.to_signals(),
        reason=";".join(analysis.reason_codes) or None,
    )


def _exact_pair(
    source: RelationEvidenceChunk,
    target: RelationEvidenceChunk,
) -> RelationEvidenceChunkPair:
    analysis = analyze_text_relation(source.content, target.content)
    if analysis.relation_type == RelationType.EXACT_CONTENT:
        return _pair_from_analysis(source, target, analysis)
    signals = analysis.to_signals()
    signals["same_exact_duplicate_group_id"] = True
    return RelationEvidenceChunkPair(
        source_chunk=source,
        target_chunk=target,
        evidence_type=RelationType.EXACT_CONTENT.value,
        confidence=1.0,
        signals=signals,
        reason="same_exact_duplicate_group_id",
    )


def _candidate_sort_key(
    pair: RelationEvidenceChunkPair,
    source_index: int,
    target_index: int,
) -> tuple[float, float, float, int, int]:
    semantic = pair.signals.get("semantic_similarity")
    lexical = pair.signals.get("lexical_similarity")
    containment = pair.signals.get("containment")
    score = max(
        float(semantic) if isinstance(semantic, int | float) else 0.0,
        float(lexical) if isinstance(lexical, int | float) else 0.0,
        float(containment) if isinstance(containment, int | float) else 0.0,
    )
    return (
        float(_PAIR_PRIORITY.get(pair.evidence_type, 0)),
        pair.confidence,
        score,
        -abs(source_index - target_index),
        -min(source_index, target_index),
    )


def _pair_display_key(pair: RelationEvidenceChunkPair) -> tuple[int, int, str]:
    source_index = pair.source_chunk.chunk_index if pair.source_chunk is not None else 1_000_000
    target_index = pair.target_chunk.chunk_index if pair.target_chunk is not None else 1_000_000
    return (min(source_index, target_index), source_index, pair.evidence_type)


__all__ = ["build_relation_chunk_pairs"]
