"""High-recall, bounded chunk-candidate generation primitives.

This module only generates and fuses candidates. Authoritative identity and
relation classification remain in ``chunk_preembedding``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import replace
from itertools import combinations

from app.knowledge_quality.application.analysis import loose_normalize_text
from app.knowledge_quality.domain.models import (
    CandidateChannel,
    CandidateChannelEvidence,
    ChunkDedupCandidate,
    ChunkDedupProbe,
)

BINARY_LAYOUT_MULTIPLIERS = (1, 3, 5, 7, 11, 13, 17, 21)
BINARY_LAYOUT_VERSION = "simhash-multilayout-8x8-v1"
DEFAULT_CHANNEL_RESERVATION = 4
DEFAULT_FINAL_CANDIDATE_LIMIT = 50
DEFAULT_RRF_K = 60
DEFAULT_FTS_TERM_LIMIT = 16

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "có",
        "là",
        "tại",
        "năm",
        "và",
        "của",
        "cho",
        "với",
        "được",
        "theo",
        "trong",
        "mỗi",
        "một",
        "mức",
        "khoảng",
        "tham",
        "chiếu",
        "giá",
        "trị",
    }
)


def simhash_multi_layout_keys(signature: str) -> tuple[str, ...]:
    """Return 64 GIN-indexable keys from eight deterministic bit layouts."""
    if len(signature) != 16:
        raise ValueError("SimHash signature must contain 16 hexadecimal characters")
    try:
        raw = f"{int(signature, 16):064b}"
    except ValueError as exc:
        raise ValueError("SimHash signature must be hexadecimal") from exc

    keys: list[str] = []
    for multiplier in BINARY_LAYOUT_MULTIPLIERS:
        permutation = "".join(raw[(index * multiplier) % 64] for index in range(64))
        for band in range(8):
            value = int(permutation[band * 8 : band * 8 + 8], 2)
            keys.append(f"m{multiplier}:b{band}:{value:02x}")
    return tuple(keys)


def simhash_fixed_band_keys(signature: str) -> tuple[str, ...]:
    """Return the eight stored keys used by a fixed-band multi-probe strategy."""
    if len(signature) != 16:
        raise ValueError("SimHash signature must contain 16 hexadecimal characters")
    try:
        int(signature, 16)
    except ValueError as exc:
        raise ValueError("SimHash signature must be hexadecimal") from exc
    return tuple(
        f"fixed:b{band}:{signature[band * 2 : band * 2 + 2]}" for band in range(8)
    )


def simhash_fixed_band_multiprobe_keys(
    signature: str,
    *,
    bit_radius: int = 2,
) -> tuple[str, ...]:
    """Expand each query byte to bounded Hamming neighbors for strategy comparison."""
    if bit_radius not in {0, 1, 2}:
        raise ValueError("Fixed-band multi-probe radius must be 0, 1, or 2")
    stored = simhash_fixed_band_keys(signature)
    result: list[str] = []
    for band, key in enumerate(stored):
        value = int(key[-2:], 16)
        for distance in range(bit_radius + 1):
            for positions in combinations(range(8), distance):
                neighbor = value
                for position in positions:
                    neighbor ^= 1 << position
                result.append(f"fixed:b{band}:{neighbor:02x}")
    return tuple(result)


def candidate_fts_terms(text: str, *, limit: int = DEFAULT_FTS_TERM_LIMIT) -> tuple[str, ...]:
    """Select bounded, deterministic OR terms for the existing ``simple`` FTS index."""
    if limit <= 0:
        raise ValueError("FTS term limit must be > 0")
    counts = Counter(
        token
        for token in _TOKEN_PATTERN.findall(loose_normalize_text(text))
        if len(token) >= 2 and token not in _STOPWORDS
    )
    return tuple(
        sorted(counts, key=lambda token: (counts[token], -len(token), token))[:limit]
    )


def candidate_channels(candidate: ChunkDedupCandidate) -> frozenset[CandidateChannel]:
    return frozenset(evidence.channel for evidence in candidate.channel_evidence)


def fuse_chunk_candidates(
    probes: Sequence[ChunkDedupProbe],
    candidates: Iterable[ChunkDedupCandidate],
    *,
    final_limit: int = DEFAULT_FINAL_CANDIDATE_LIMIT,
    channel_reservation: int = DEFAULT_CHANNEL_RESERVATION,
    rrf_k: int = DEFAULT_RRF_K,
) -> tuple[ChunkDedupCandidate, ...]:
    """Stable per-probe union, evidence merge, reservation, and reciprocal-rank fusion."""
    if final_limit <= 0 or final_limit > 50:
        raise ValueError("Final candidate limit must be between 1 and 50")
    if channel_reservation < 0:
        raise ValueError("Channel reservation must be >= 0")
    if rrf_k <= 0:
        raise ValueError("RRF rank constant must be > 0")

    probe_by_index = {probe.chunk_index: probe for probe in probes}
    if len(probe_by_index) != len(probes):
        raise ValueError("Chunk candidate probes must have unique chunk indexes")

    merged: dict[tuple[int, str], ChunkDedupCandidate] = {}
    evidence_by_identity: dict[
        tuple[int, str], dict[CandidateChannel, CandidateChannelEvidence]
    ] = defaultdict(dict)
    for candidate in candidates:
        identity = (candidate.source_chunk_index, candidate.target_chunk_id)
        if candidate.source_chunk_index not in probe_by_index:
            raise ValueError("Chunk candidate references an unknown source chunk")
        previous = merged.get(identity)
        if previous is not None and (
            previous.target_document_id != candidate.target_document_id
            or previous.target_chunk_index != candidate.target_chunk_index
        ):
            raise ValueError("Stable target chunk identity maps to conflicting metadata")
        if previous is None:
            merged[identity] = candidate
        else:
            merged[identity] = replace(
                previous,
                lsh_band_matches=max(
                    previous.lsh_band_matches,
                    candidate.lsh_band_matches,
                ),
            )
        for evidence in candidate.channel_evidence:
            selected_evidence = evidence_by_identity[identity].get(evidence.channel)
            if selected_evidence is None or (evidence.rank, -evidence.score) < (
                selected_evidence.rank,
                -selected_evidence.score,
            ):
                evidence_by_identity[identity][evidence.channel] = evidence

    by_probe: dict[int, list[ChunkDedupCandidate]] = defaultdict(list)
    for identity, candidate in merged.items():
        merged_evidence = tuple(
            sorted(
                evidence_by_identity[identity].values(),
                key=lambda item: (item.channel.value, item.rank),
            )
        )
        score = sum(1.0 / (rrf_k + item.rank) for item in merged_evidence)
        by_probe[candidate.source_chunk_index].append(
            replace(candidate, channel_evidence=merged_evidence, fused_score=score)
        )

    fused_selected: list[ChunkDedupCandidate] = []
    channel_order = (
        CandidateChannel.EXACT,
        CandidateChannel.BINARY,
        CandidateChannel.FTS,
        CandidateChannel.ANN,
    )
    for probe in probes:
        pool = by_probe.get(probe.chunk_index, [])
        ranked = sorted(
            pool,
            key=lambda item: (
                -item.fused_score,
                str(item.target_document_id),
                item.target_chunk_index,
                item.target_chunk_id,
            ),
        )
        reserved_ids: set[str] = set()
        probe_selected: list[ChunkDedupCandidate] = []
        for channel in channel_order:
            channel_ranked = sorted(
                (
                    candidate
                    for candidate in pool
                    if channel in candidate_channels(candidate)
                ),
                key=lambda candidate: (
                    next(
                        evidence.rank
                        for evidence in candidate.channel_evidence
                        if evidence.channel is channel
                    ),
                    -candidate.fused_score,
                    candidate.target_chunk_id,
                ),
            )
            for candidate in channel_ranked[:channel_reservation]:
                if candidate.target_chunk_id in reserved_ids:
                    continue
                reserved_ids.add(candidate.target_chunk_id)
                probe_selected.append(candidate)
        for candidate in ranked:
            if len(probe_selected) >= final_limit:
                break
            if candidate.target_chunk_id in reserved_ids:
                continue
            reserved_ids.add(candidate.target_chunk_id)
            probe_selected.append(candidate)
        fused_selected.extend(probe_selected[:final_limit])
    return tuple(fused_selected)


__all__ = [
    "BINARY_LAYOUT_MULTIPLIERS",
    "BINARY_LAYOUT_VERSION",
    "DEFAULT_CHANNEL_RESERVATION",
    "DEFAULT_FINAL_CANDIDATE_LIMIT",
    "DEFAULT_FTS_TERM_LIMIT",
    "DEFAULT_RRF_K",
    "candidate_channels",
    "candidate_fts_terms",
    "fuse_chunk_candidates",
    "simhash_multi_layout_keys",
    "simhash_fixed_band_keys",
    "simhash_fixed_band_multiprobe_keys",
]
