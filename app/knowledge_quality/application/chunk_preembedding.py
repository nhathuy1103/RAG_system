"""Explainable chunk duplicate/conflict gate that runs before embedding."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.knowledge_quality.application.analysis import (
    analyze_text_relation,
    build_chunk_fingerprint,
    is_auto_identity_eligible,
    strict_normalize_text,
)
from app.knowledge_quality.application.candidate_generation import (
    candidate_channels,
    candidate_fts_terms,
    simhash_multi_layout_keys,
)
from app.knowledge_quality.domain.models import (
    CHUNK_PREEMBEDDING_DETECTOR_VERSION,
    CandidateChannel,
    ChunkDedupCandidate,
    ChunkDedupProbe,
    ClaimScope,
    DocumentFingerprint,
    QualityRelationCandidate,
    RelationType,
    ScopeComparison,
    TextRelationAnalysis,
)
from app.pipeline.indexing.application.chunker import ChunkData
from app.pipeline.shared.text_utils import compute_checksum_text, normalize_text

DEFAULT_MAX_SIMHASH_DISTANCE = 24
LOGGER = logging.getLogger(__name__)
_LSH_BAND_COUNT = 8
_LSH_BAND_WIDTH = 2
_MAX_BATCH_FUZZY_CANDIDATES = 16
_RELATION_PRIORITY = {
    RelationType.CONFLICT_CANDIDATE: 5,
    RelationType.VERSION_CANDIDATE: 4,
    RelationType.TEMPORAL_SERIES: 3,
    RelationType.NEAR_DUPLICATE: 2,
    RelationType.TEMPLATE_VARIANT: 1,
}


class ChunkIdentityConflictError(RuntimeError):
    """Raised when one authoritative strict identity maps to different text."""


@dataclass(frozen=True, slots=True)
class ChunkDedupPlan:
    """Vectors, dependencies and evidence consumed by the embedding pipeline."""

    precomputed_vectors: dict[int, tuple[float, ...]] = field(default_factory=dict)
    reuse_from_chunk_index: dict[int, int] = field(default_factory=dict)
    metadata_by_chunk_index: dict[int, dict[str, object]] = field(default_factory=dict)
    relations: tuple[QualityRelationCandidate, ...] = ()
    database_candidate_count: int = 0
    exact_match_count: int = 0
    near_duplicate_count: int = 0
    version_candidate_count: int = 0
    conflict_candidate_count: int = 0
    temporal_series_count: int = 0
    template_variant_count: int = 0

    def to_stats(self) -> dict[str, int]:
        return {
            "database_candidate_count": self.database_candidate_count,
            "exact_match_count": self.exact_match_count,
            "near_duplicate_count": self.near_duplicate_count,
            "version_candidate_count": self.version_candidate_count,
            "conflict_candidate_count": self.conflict_candidate_count,
            "temporal_series_count": self.temporal_series_count,
            "template_variant_count": self.template_variant_count,
            "database_vector_reuse_count": len(self.precomputed_vectors),
            "batch_vector_reuse_count": len(self.reuse_from_chunk_index),
        }


@dataclass(frozen=True, slots=True)
class _DatabaseMatch:
    probe: ChunkDedupProbe
    candidate: ChunkDedupCandidate
    analysis: TextRelationAnalysis
    simhash_distance: int


@dataclass(frozen=True, slots=True)
class _BatchMatch:
    source: ChunkDedupProbe
    target: ChunkDedupProbe
    analysis: TextRelationAnalysis
    simhash_distance: int
    lsh_band_matches: int


def build_chunk_dedup_probes(
    chunks: Sequence[ChunkData],
    *,
    max_fuzzy_probes: int | None,
    scope: ClaimScope | None = None,
    high_recall_candidates: bool = False,
) -> tuple[ChunkDedupProbe, ...]:
    """Fingerprint every chunk; P1 makes every eligible chunk candidate-capable."""
    if max_fuzzy_probes is not None and max_fuzzy_probes <= 0:
        raise ValueError("max_fuzzy_probes must be > 0")

    prepared: list[tuple[ChunkData, str, str, DocumentFingerprint]] = []
    fuzzy_eligible_indexes: list[int] = []
    for chunk in chunks:
        canonical_text = str(chunk.metadata.get("canonical_content") or chunk.text).strip()
        embedding_text = normalize_text(chunk.embedding_text or chunk.text)
        fingerprint = build_chunk_fingerprint(canonical_text)
        prepared.append((chunk, canonical_text, embedding_text, fingerprint))
        if is_auto_identity_eligible(fingerprint):
            fuzzy_eligible_indexes.append(chunk.chunk_index)

    fuzzy_indexes = (
        set(fuzzy_eligible_indexes)
        if max_fuzzy_probes is None
        else _sample_indexes(tuple(fuzzy_eligible_indexes), max_fuzzy_probes)
    )
    probes: list[ChunkDedupProbe] = []
    for chunk, canonical_text, embedding_text, fingerprint in prepared:
        probes.append(
            ChunkDedupProbe(
                chunk_index=chunk.chunk_index,
                chunk_id=chunk.chunk_id,
                canonical_text=canonical_text,
                embedding_text_checksum=compute_checksum_text(embedding_text),
                fingerprint=fingerprint,
                include_fuzzy_candidates=chunk.chunk_index in fuzzy_indexes,
                scope=scope,
                binary_keys=(
                    simhash_multi_layout_keys(fingerprint.loose_signature)
                    if high_recall_candidates and chunk.chunk_index in fuzzy_indexes
                    else ()
                ),
                fts_terms=(
                    candidate_fts_terms(canonical_text)
                    if high_recall_candidates and chunk.chunk_index in fuzzy_indexes
                    else ()
                ),
            )
        )
    return tuple(probes)


def plan_chunk_deduplication(
    probes: Sequence[ChunkDedupProbe],
    candidates: Sequence[ChunkDedupCandidate],
    *,
    embedding_model: str,
    enable_exact_reuse: bool,
    max_simhash_distance: int = DEFAULT_MAX_SIMHASH_DISTANCE,
) -> ChunkDedupPlan:
    """Combine strict identity, SimHash-LSH and explainable relation checks."""
    if max_simhash_distance < 0 or max_simhash_distance > 64:
        raise ValueError("max_simhash_distance must be between 0 and 64")

    by_index = {probe.chunk_index: probe for probe in probes}
    if len(by_index) != len(probes):
        raise ValueError("Chunk dedup probes must have unique chunk indexes")

    database_matches: dict[int, list[_DatabaseMatch]] = defaultdict(list)
    fuzzy_relation_matches: list[_DatabaseMatch] = []
    for candidate in candidates:
        probe = by_index.get(candidate.source_chunk_index)
        if probe is None:
            raise ValueError("Chunk candidate references an unknown source chunk")
        match = _analyze_database_candidate(
            probe,
            candidate,
            max_simhash_distance=max_simhash_distance,
        )
        if match is None:
            continue
        database_matches[probe.chunk_index].append(match)
        if match.analysis.relation_type in _RELATION_PRIORITY:
            fuzzy_relation_matches.append(match)

    precomputed_vectors: dict[int, tuple[float, ...]] = {}
    reuse_from_chunk_index: dict[int, int] = {}
    annotations: dict[int, dict[str, object]] = {}
    exact_match_count = 0
    relation_counts: dict[RelationType, int] = defaultdict(int)

    for probe in probes:
        matches = database_matches.get(probe.chunk_index, [])
        exact_matches = [
            match for match in matches if match.analysis.relation_type == RelationType.EXACT_CONTENT
        ]
        if exact_matches:
            exact_match_count += 1
            selected = min(
                exact_matches,
                key=lambda match: (
                    not _can_reuse_embedding(match, embedding_model),
                    str(match.candidate.target_document_id),
                    match.candidate.target_chunk_index,
                    match.candidate.target_chunk_id,
                ),
            )
            reusable = _can_reuse_embedding(selected, embedding_model)
            reuse = enable_exact_reuse and reusable
            if reuse:
                precomputed_vectors[probe.chunk_index] = selected.candidate.embedding
                action = "reuse_exact_embedding"
            elif not enable_exact_reuse:
                action = "exact_match_observed"
            elif selected.candidate.embedding_model != embedding_model:
                action = "exact_match_embedding_model_changed"
            elif selected.candidate.embedding_text_checksum != probe.embedding_text_checksum:
                action = "exact_match_embedding_context_changed"
            else:
                action = "exact_match_embedding_unavailable"
            annotations[probe.chunk_index] = _database_annotation(
                selected,
                action=action,
                embedding_reused=reuse,
            )
            continue

        fuzzy_matches = [
            match for match in matches if match.analysis.relation_type in _RELATION_PRIORITY
        ]
        if fuzzy_matches:
            selected = max(
                fuzzy_matches,
                key=lambda match: (
                    _RELATION_PRIORITY[match.analysis.relation_type],
                    match.analysis.confidence,
                ),
            )
            relation_counts[selected.analysis.relation_type] += 1
            annotations[probe.chunk_index] = _database_annotation(
                selected,
                action=selected.analysis.relation_type.value,
                embedding_reused=False,
            )

    batch_exact_match_count = _apply_batch_exact_reuse(
        probes,
        enable_exact_reuse=enable_exact_reuse,
        precomputed_vectors=precomputed_vectors,
        reuse_from_chunk_index=reuse_from_chunk_index,
        annotations=annotations,
    )
    batch_matches = _find_batch_fuzzy_matches(
        probes,
        max_simhash_distance=max_simhash_distance,
    )
    for batch_match in batch_matches:
        if batch_match.source.chunk_index in annotations:
            continue
        relation_counts[batch_match.analysis.relation_type] += 1
        annotations[batch_match.source.chunk_index] = _batch_annotation(batch_match)

    return ChunkDedupPlan(
        precomputed_vectors=precomputed_vectors,
        reuse_from_chunk_index=reuse_from_chunk_index,
        metadata_by_chunk_index=annotations,
        relations=_build_document_relations(probes, fuzzy_relation_matches),
        database_candidate_count=len(candidates),
        exact_match_count=exact_match_count + batch_exact_match_count,
        near_duplicate_count=relation_counts[RelationType.NEAR_DUPLICATE],
        version_candidate_count=relation_counts[RelationType.VERSION_CANDIDATE],
        conflict_candidate_count=relation_counts[RelationType.CONFLICT_CANDIDATE],
        temporal_series_count=relation_counts[RelationType.TEMPORAL_SERIES],
        template_variant_count=relation_counts[RelationType.TEMPLATE_VARIANT],
    )


def simhash_hamming_distance(left: str, right: str) -> int:
    """Return bit distance between two persisted 64-bit hexadecimal SimHashes."""
    if len(left) != 16 or len(right) != 16:
        raise ValueError("SimHash signatures must contain 16 hexadecimal characters")
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError as exc:
        raise ValueError("SimHash signatures must be hexadecimal") from exc


def simhash_lsh_bands(signature: str) -> tuple[str, ...]:
    """Split a 64-bit SimHash into eight indexable 8-bit LSH bands."""
    if len(signature) != _LSH_BAND_COUNT * _LSH_BAND_WIDTH:
        raise ValueError("SimHash signature must contain 16 hexadecimal characters")
    try:
        int(signature, 16)
    except ValueError as exc:
        raise ValueError("SimHash signature must be hexadecimal") from exc
    return tuple(
        signature[start : start + _LSH_BAND_WIDTH]
        for start in range(0, len(signature), _LSH_BAND_WIDTH)
    )


def _analyze_database_candidate(
    probe: ChunkDedupProbe,
    candidate: ChunkDedupCandidate,
    *,
    max_simhash_distance: int,
) -> _DatabaseMatch | None:
    if candidate.normalization_version != probe.fingerprint.normalization_version:
        return None

    strict_identity_match = candidate.normalized_content_hash == probe.fingerprint.strict_hash
    left_strict = strict_normalize_text(probe.canonical_text)
    right_strict = strict_normalize_text(candidate.canonical_text)
    if strict_identity_match and left_strict != right_strict:
        raise ChunkIdentityConflictError("A strict chunk hash maps to different normalized content")

    distance = simhash_hamming_distance(
        probe.fingerprint.loose_signature,
        candidate.loose_content_signature,
    )
    if not strict_identity_match:
        if not probe.include_fuzzy_candidates:
            return None
        channels = candidate_channels(candidate)
        non_binary_recovery = bool(channels & {CandidateChannel.FTS, CandidateChannel.ANN})
        if distance > max_simhash_distance and not non_binary_recovery:
            return None

    analysis = analyze_text_relation(
        probe.canonical_text,
        candidate.canonical_text,
        semantic_similarity=max(
            (
                evidence.score
                for evidence in candidate.channel_evidence
                if evidence.channel is CandidateChannel.ANN
            ),
            default=None,
        ),
        left_scope=probe.scope,
        right_scope=candidate.scope,
    )
    if strict_identity_match and analysis.relation_type != RelationType.EXACT_CONTENT:
        raise ChunkIdentityConflictError(
            "A strict chunk hash failed authoritative text verification"
        )
    if analysis.relation_type == RelationType.EXACT_CONTENT and not strict_identity_match:
        raise ChunkIdentityConflictError(
            "Equal normalized chunk text has inconsistent strict fingerprints"
        )
    if analysis.relation_type == RelationType.DISTINCT:
        return None
    return _DatabaseMatch(
        probe=probe,
        candidate=candidate,
        analysis=analysis,
        simhash_distance=distance,
    )


def _can_reuse_embedding(match: _DatabaseMatch, embedding_model: str) -> bool:
    return (
        match.candidate.embedding_model == embedding_model
        and bool(match.candidate.embedding)
        and match.candidate.embedding_text_checksum == match.probe.embedding_text_checksum
    )


def _apply_batch_exact_reuse(
    probes: Sequence[ChunkDedupProbe],
    *,
    enable_exact_reuse: bool,
    precomputed_vectors: dict[int, tuple[float, ...]],
    reuse_from_chunk_index: dict[int, int],
    annotations: dict[int, dict[str, object]],
) -> int:
    exact_match_count = 0
    groups: dict[tuple[str, str], list[ChunkDedupProbe]] = defaultdict(list)
    for probe in probes:
        groups[
            (
                probe.fingerprint.normalization_version,
                probe.fingerprint.strict_hash,
            )
        ].append(probe)

    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda item: item.chunk_index)
        representative = ordered[0]
        representative_text = strict_normalize_text(representative.canonical_text)
        for duplicate in ordered[1:]:
            exact_match_count += 1
            if strict_normalize_text(duplicate.canonical_text) != representative_text:
                raise ChunkIdentityConflictError(
                    "A batch strict chunk hash maps to different normalized content"
                )
            same_embedding_context = (
                duplicate.embedding_text_checksum == representative.embedding_text_checksum
            )
            reuse = (
                enable_exact_reuse
                and same_embedding_context
                and duplicate.chunk_index not in precomputed_vectors
            )
            if reuse:
                reuse_from_chunk_index[duplicate.chunk_index] = representative.chunk_index
                action = "reuse_batch_exact_embedding"
            elif not enable_exact_reuse:
                action = "batch_exact_match_observed"
            else:
                action = "batch_exact_embedding_context_changed"
            annotations.setdefault(
                duplicate.chunk_index,
                {
                    "detector_version": CHUNK_PREEMBEDDING_DETECTOR_VERSION,
                    "action": action,
                    "relation_type": RelationType.EXACT_CONTENT.value,
                    "confidence": 1.0,
                    "embedding_reused": reuse,
                    "match_source": "current_batch",
                    "target_chunk_id": representative.chunk_id,
                    "target_chunk_index": representative.chunk_index,
                    "reason_codes": ["strict_content_match"],
                },
            )
    return exact_match_count


def _find_batch_fuzzy_matches(
    probes: Sequence[ChunkDedupProbe],
    *,
    max_simhash_distance: int,
) -> tuple[_BatchMatch, ...]:
    buckets: dict[tuple[int, str], set[int]] = defaultdict(set)
    by_index = {probe.chunk_index: probe for probe in probes}
    for probe in probes:
        for band_index, band in enumerate(simhash_lsh_bands(probe.fingerprint.loose_signature)):
            buckets[(band_index, band)].add(probe.chunk_index)

    matches: list[_BatchMatch] = []
    seen_pairs: set[tuple[str, str]] = set()
    for source in probes:
        if not source.include_fuzzy_candidates:
            continue
        source_bands = simhash_lsh_bands(source.fingerprint.loose_signature)
        candidate_indexes: set[int] = set()
        for band_index, band in enumerate(source_bands):
            candidate_indexes.update(buckets[(band_index, band)])
        candidate_indexes.discard(source.chunk_index)
        for target_index in sorted(candidate_indexes)[:_MAX_BATCH_FUZZY_CANDIDATES]:
            target = by_index[target_index]
            first_chunk_id, second_chunk_id = sorted((source.chunk_id, target.chunk_id))
            pair_key = (first_chunk_id, second_chunk_id)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            if (
                target.fingerprint.strict_hash == source.fingerprint.strict_hash
                and target.fingerprint.normalization_version
                == source.fingerprint.normalization_version
            ):
                continue
            distance = simhash_hamming_distance(
                source.fingerprint.loose_signature,
                target.fingerprint.loose_signature,
            )
            if distance > max_simhash_distance:
                continue
            analysis = analyze_text_relation(
                source.canonical_text,
                target.canonical_text,
                left_scope=source.scope,
                right_scope=target.scope,
            )
            if analysis.relation_type not in _RELATION_PRIORITY:
                continue
            band_matches = sum(
                left == right
                for left, right in zip(
                    source_bands,
                    simhash_lsh_bands(target.fingerprint.loose_signature),
                    strict=True,
                )
            )
            matches.append(
                _BatchMatch(
                    source=source,
                    target=target,
                    analysis=analysis,
                    simhash_distance=distance,
                    lsh_band_matches=band_matches,
                )
            )
    matches.sort(
        key=lambda match: (
            match.source.chunk_index,
            -_RELATION_PRIORITY[match.analysis.relation_type],
            -match.analysis.confidence,
            match.target.chunk_index,
        )
    )
    return tuple(matches)


def _build_document_relations(
    probes: Sequence[ChunkDedupProbe],
    matches: Sequence[_DatabaseMatch],
) -> tuple[QualityRelationCandidate, ...]:
    fuzzy_probe_count = sum(probe.include_fuzzy_candidates for probe in probes)
    by_document: dict[UUID, list[_DatabaseMatch]] = defaultdict(list)
    for match in matches:
        by_document[match.candidate.target_document_id].append(match)

    results: list[QualityRelationCandidate] = []
    for target_document_id, document_matches in by_document.items():
        temporal_pair_count = sum(
            match.analysis.scope_comparison is ScopeComparison.TEMPORAL_DIVERGENCE
            for match in document_matches
        )
        temporal_majority = temporal_pair_count * 2 > len(document_matches)
        conflicts = [
            match
            for match in document_matches
            if match.analysis.relation_type == RelationType.CONFLICT_CANDIDATE
            and match.analysis.confidence >= 0.62
            and match.analysis.validated_conflict_count > 0
            and match.analysis.scope_comparison is ScopeComparison.SAME_SCOPE
        ]
        if conflicts and not temporal_majority:
            selected_group = _deduplicate_conflict_matches(conflicts)
            relation_type = RelationType.CONFLICT_CANDIDATE
        else:
            grouped: dict[RelationType, list[_DatabaseMatch]] = defaultdict(list)
            for match in document_matches:
                grouped[match.analysis.relation_type].append(match)
            selected_group = []
            relation_type = RelationType.DISTINCT
            for candidate_type in (
                RelationType.VERSION_CANDIDATE,
                RelationType.TEMPORAL_SERIES,
                RelationType.NEAR_DUPLICATE,
                RelationType.TEMPLATE_VARIANT,
            ):
                group = grouped.get(candidate_type, [])
                coverage = (
                    len({match.probe.chunk_index for match in group}) / fuzzy_probe_count
                    if fuzzy_probe_count
                    else 0.0
                )
                if group and coverage >= 0.35:
                    selected_group = group
                    relation_type = candidate_type
                    break
        if not selected_group or relation_type == RelationType.DISTINCT:
            continue

        matched_indexes = {match.probe.chunk_index for match in selected_group}
        coverage = len(matched_indexes) / fuzzy_probe_count if fuzzy_probe_count else 0.0
        selected = max(
            selected_group,
            key=lambda match: match.analysis.confidence,
        )
        mean_confidence = sum(match.analysis.confidence for match in selected_group) / len(
            selected_group
        )
        confidence = min(
            0.99,
            0.80 * mean_confidence + 0.20 * max(coverage, 0.20),
        )
        signals = selected.analysis.to_signals()
        signals.update(
            {
                "pre_embedding_detection": True,
                "document_probe_coverage": round(coverage, 6),
                "matched_probe_count": len(matched_indexes),
                "probe_count": fuzzy_probe_count,
                "matched_chunk_pair_count": len(selected_group),
                "temporal_divergence_pair_count": temporal_pair_count,
                "temporal_divergence_ratio": round(
                    temporal_pair_count / len(document_matches),
                    6,
                ),
                "temporal_majority_guard_applied": temporal_majority,
                "validated_conflict_count": sum(
                    match.analysis.validated_conflict_count for match in selected_group
                ),
                "relation_pair_counts": {
                    detected_type.value: sum(
                        match.analysis.relation_type == detected_type for match in document_matches
                    )
                    for detected_type in _RELATION_PRIORITY
                },
                "simhash_hamming_distance": selected.simhash_distance,
                "lsh_band_matches": selected.candidate.lsh_band_matches,
                "selected_chunk_pair": {
                    "source_chunk_id": selected.probe.chunk_id,
                    "source_chunk_index": selected.probe.chunk_index,
                    "target_chunk_id": selected.candidate.target_chunk_id,
                    "target_chunk_index": selected.candidate.target_chunk_index,
                },
            }
        )
        results.append(
            QualityRelationCandidate(
                target_document_id=target_document_id,
                relation_type=relation_type,
                confidence=confidence,
                signals=signals,
                reason=";".join(selected.analysis.reason_codes) or None,
                detector_version=CHUNK_PREEMBEDDING_DETECTOR_VERSION,
            )
        )
        LOGGER.debug(
            "Pre-embedding relation candidate validated",
            extra={
                "target_document_id": str(target_document_id),
                "relation_type": relation_type.value,
                "matched_chunk_pair_count": len(selected_group),
                "scope_comparison": selected.analysis.scope_comparison.value,
                "validated_conflict_count": selected.analysis.validated_conflict_count,
                "reason_codes": selected.analysis.reason_codes,
                "confidence_components": selected.analysis.confidence_components,
            },
        )

    results.sort(key=lambda item: item.confidence, reverse=True)
    return tuple(results)


def _deduplicate_conflict_matches(
    matches: Sequence[_DatabaseMatch],
) -> list[_DatabaseMatch]:
    selected: dict[tuple[str, ...], _DatabaseMatch] = {}
    for match in matches:
        claim_conflict = max(
            match.analysis.claim_conflicts,
            key=lambda item: item.alignment_score,
        )
        claim_key = claim_conflict.left_claim.claim_key
        evidence_key = (
            claim_key.canonical_evidence_key()
            if claim_key is not None
            else (claim_conflict.left_claim.alignment_key,)
        )
        previous = selected.get(evidence_key)
        if previous is None or match.analysis.confidence > previous.analysis.confidence:
            selected[evidence_key] = match
    return list(selected.values())


def _database_annotation(
    match: _DatabaseMatch,
    *,
    action: str,
    embedding_reused: bool,
) -> dict[str, object]:
    analysis = match.analysis
    return {
        "detector_version": CHUNK_PREEMBEDDING_DETECTOR_VERSION,
        "action": action,
        "relation_type": analysis.relation_type.value,
        "confidence": round(analysis.confidence, 6),
        "embedding_reused": embedding_reused,
        "match_source": "database",
        "target_document_id": str(match.candidate.target_document_id),
        "target_chunk_id": match.candidate.target_chunk_id,
        "target_chunk_index": match.candidate.target_chunk_index,
        "simhash_hamming_distance": match.simhash_distance,
        "lsh_band_matches": match.candidate.lsh_band_matches,
        "candidate_channels": sorted(
            channel.value for channel in candidate_channels(match.candidate)
        ),
        "candidate_fused_score": round(match.candidate.fused_score, 8),
        "lexical_similarity": round(analysis.lexical_similarity, 6),
        "containment": round(analysis.containment, 6),
        "reason_codes": list(analysis.reason_codes),
    }


def _batch_annotation(match: _BatchMatch) -> dict[str, object]:
    analysis = match.analysis
    return {
        "detector_version": CHUNK_PREEMBEDDING_DETECTOR_VERSION,
        "action": analysis.relation_type.value,
        "relation_type": analysis.relation_type.value,
        "confidence": round(analysis.confidence, 6),
        "embedding_reused": False,
        "match_source": "current_batch",
        "target_chunk_id": match.target.chunk_id,
        "target_chunk_index": match.target.chunk_index,
        "simhash_hamming_distance": match.simhash_distance,
        "lsh_band_matches": match.lsh_band_matches,
        "lexical_similarity": round(analysis.lexical_similarity, 6),
        "containment": round(analysis.containment, 6),
        "reason_codes": list(analysis.reason_codes),
    }


def _sample_indexes(indexes: tuple[int, ...], maximum: int) -> set[int]:
    if len(indexes) <= maximum:
        return set(indexes)
    if maximum == 1:
        return {indexes[len(indexes) // 2]}
    positions = {
        round(position * (len(indexes) - 1) / (maximum - 1)) for position in range(maximum)
    }
    return {indexes[position] for position in positions}


__all__ = [
    "DEFAULT_MAX_SIMHASH_DISTANCE",
    "ChunkDedupPlan",
    "ChunkIdentityConflictError",
    "build_chunk_dedup_probes",
    "plan_chunk_deduplication",
    "simhash_hamming_distance",
    "simhash_lsh_bands",
]
