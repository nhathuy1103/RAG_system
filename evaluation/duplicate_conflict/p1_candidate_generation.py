"""P1 high-recall candidate evaluation on the frozen P0 gold splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.knowledge_quality.application.analysis import (
    build_chunk_fingerprint,
    loose_normalize_text,
    strict_normalize_text,
)
from app.knowledge_quality.application.candidate_generation import (
    BINARY_LAYOUT_VERSION,
    candidate_fts_terms,
    fuse_chunk_candidates,
    simhash_fixed_band_keys,
    simhash_fixed_band_multiprobe_keys,
    simhash_multi_layout_keys,
)
from app.knowledge_quality.application.chunk_preembedding import (
    build_chunk_dedup_probes,
    simhash_hamming_distance,
    simhash_lsh_bands,
)
from app.knowledge_quality.domain.models import (
    CandidateChannel,
    CandidateChannelEvidence,
    ChunkDedupCandidate,
    ChunkDedupProbe,
)
from app.pipeline.indexing.application.chunker import ChunkData
from app.pipeline.shared.text_utils import compute_checksum_text, normalize_text
from evaluation.duplicate_conflict.constants import (
    CANDIDATE_DISTRACTOR_COUNT,
    DEV_DATASET_PATH,
    REPOSITORY_ROOT,
    STRESS_CASES_PATH,
    TEST_DATASET_PATH,
)
from evaluation.duplicate_conflict.models import GoldPair, GoldRelation
from evaluation.duplicate_conflict.runner import _distractors
from evaluation.duplicate_conflict.validation import load_pairs, validate_pairs

CONFIG_PATH = REPOSITORY_ROOT / "configs" / "evaluation" / "p1_candidate_generation.json"
REPORT_DIR = REPOSITORY_ROOT / "reports" / "evaluation"
NOISE_RANK = {"none": 0, "light": 1, "medium": 2, "severe": 3}


@dataclass(frozen=True, slots=True)
class PairCandidateResult:
    pair_id: str
    rank: int | None
    candidate_count: int
    channel_ranks: dict[str, int | None]
    ablation_ranks: dict[str, int | None]
    latency_ms: float


class _FixtureCache:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        self.fingerprints: dict[str, Any] = {}
        self.tokens: dict[str, tuple[str, ...]] = {}
        self.vectors: dict[str, tuple[float, ...]] = {}

    def fingerprint(self, text: str) -> Any:
        return self.fingerprints.setdefault(text, build_chunk_fingerprint(text))

    def lexical_tokens(self, text: str) -> tuple[str, ...]:
        cached = self.tokens.get(text)
        if cached is not None:
            return cached
        value = tuple(
            token
            for token in candidate_fts_terms(text, limit=10_000)
        )
        self.tokens[text] = value
        return value

    def dense(self, text: str) -> tuple[float, ...]:
        cached = self.vectors.get(text)
        if cached is not None:
            return cached
        normalized = loose_normalize_text(text)
        words = normalized.split()
        features = [
            f"c:{normalized[index:index + 3]}"
            for index in range(max(0, len(normalized) - 2))
        ]
        features.extend(f"w:{word}" for word in words)
        features.extend(
            f"b:{words[index]}_{words[index + 1]}"
            for index in range(max(0, len(words) - 1))
        )
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        result = tuple(value / norm for value in vector)
        self.vectors[text] = result
        return result


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _probe(pair: GoldPair, cache: _FixtureCache) -> ChunkDedupProbe:
    fingerprint = cache.fingerprint(pair.text_a)
    return ChunkDedupProbe(
        chunk_index=0,
        chunk_id=f"source:{pair.pair_id}",
        canonical_text=pair.text_a,
        embedding_text_checksum=compute_checksum_text(normalize_text(pair.text_a)),
        fingerprint=fingerprint,
        include_fuzzy_candidates=True,
        binary_keys=simhash_multi_layout_keys(fingerprint.loose_signature),
        fts_terms=candidate_fts_terms(pair.text_a),
    )


def _candidate(
    pair: GoldPair,
    cache: _FixtureCache,
    evidence: CandidateChannelEvidence,
    *,
    lsh_matches: int = 0,
) -> ChunkDedupCandidate:
    fingerprint = cache.fingerprint(pair.text_b)
    return ChunkDedupCandidate(
        source_chunk_index=0,
        target_chunk_id=f"target:{pair.pair_id}",
        target_document_id=uuid5(NAMESPACE_URL, f"p1:{pair.pair_id}"),
        target_chunk_index=0,
        canonical_text=pair.text_b,
        normalized_content_hash=fingerprint.strict_hash,
        normalization_version=fingerprint.normalization_version,
        loose_content_signature=fingerprint.loose_signature,
        embedding_text_checksum=compute_checksum_text(normalize_text(pair.text_b)),
        embedding=(0.0,),
        embedding_model="deterministic-ann-fixture-v1",
        lsh_band_matches=lsh_matches,
        channel_evidence=(evidence,),
    )


def _rank_of(target_id: str, candidates: tuple[ChunkDedupCandidate, ...]) -> int | None:
    return next(
        (
            index
            for index, candidate in enumerate(candidates, 1)
            if candidate.target_chunk_id == target_id
        ),
        None,
    )


def _channel_candidates(
    pair: GoldPair,
    all_pairs: tuple[GoldPair, ...],
    cache: _FixtureCache,
    config: dict[str, Any],
) -> tuple[
    ChunkDedupProbe,
    dict[CandidateChannel, tuple[ChunkDedupCandidate, ...]],
    dict[str, int | None],
]:
    probe = _probe(pair, cache)
    corpus = (pair, *_distractors(pair, all_pairs))
    # Materialize up to 50 once so DEV-only limit sweeps reuse identical rankings.
    channel_k = 50
    query_fp = probe.fingerprint

    exact_rows = sorted(
        (
            candidate
            for candidate in corpus
            if cache.fingerprint(candidate.text_b).strict_hash == query_fp.strict_hash
        ),
        key=lambda candidate: candidate.pair_id,
    )[:channel_k]
    exact = tuple(
        _candidate(
            candidate,
            cache,
            CandidateChannelEvidence(CandidateChannel.EXACT, rank, 1.0),
        )
        for rank, candidate in enumerate(exact_rows, 1)
    )

    query_keys = set(simhash_multi_layout_keys(query_fp.loose_signature))
    binary_ranked: list[tuple[int, int, str, GoldPair]] = []
    for candidate in corpus:
        candidate_fp = cache.fingerprint(candidate.text_b)
        overlap = len(query_keys & set(simhash_multi_layout_keys(candidate_fp.loose_signature)))
        if not overlap:
            continue
        distance = simhash_hamming_distance(
            query_fp.loose_signature,
            candidate_fp.loose_signature,
        )
        binary_ranked.append((-overlap, distance, candidate.pair_id, candidate))
    binary_ranked.sort(key=lambda item: item[:3])
    binary = tuple(
        _candidate(
            candidate,
            cache,
            CandidateChannelEvidence(
                CandidateChannel.BINARY,
                rank,
                overlap / 64.0,
                overlap,
            ),
            lsh_matches=overlap,
        )
        for rank, (negative_overlap, _, _, candidate) in enumerate(
            binary_ranked[:channel_k],
            1,
        )
        for overlap in (-negative_overlap,)
    )

    query_terms = set(probe.fts_terms)
    fts_ranked: list[tuple[float, str, GoldPair]] = []
    for candidate in corpus:
        counts = Counter(cache.lexical_tokens(candidate.text_b))
        score = sum(
            1.0 + math.log1p(counts[token]) for token in query_terms if counts[token]
        )
        if score:
            fts_ranked.append((-score, candidate.pair_id, candidate))
    fts_ranked.sort(key=lambda item: item[:2])
    fts = tuple(
        _candidate(
            candidate,
            cache,
            CandidateChannelEvidence(CandidateChannel.FTS, rank, -negative_score),
        )
        for rank, (negative_score, _, candidate) in enumerate(fts_ranked[:channel_k], 1)
    )

    query_vector = cache.dense(pair.text_a)
    ann_ranked = sorted(
        (
            (-_cosine(query_vector, cache.dense(candidate.text_b)), candidate.pair_id, candidate)
            for candidate in corpus
        ),
        key=lambda item: item[:2],
    )[:channel_k]
    ann = tuple(
        _candidate(
            candidate,
            cache,
            CandidateChannelEvidence(CandidateChannel.ANN, rank, -negative_score),
        )
        for rank, (negative_score, _, candidate) in enumerate(ann_ranked, 1)
    )

    channels = {
        CandidateChannel.EXACT: exact,
        CandidateChannel.BINARY: binary,
        CandidateChannel.FTS: fts,
        CandidateChannel.ANN: ann,
    }

    fixed_query = simhash_fixed_band_keys(query_fp.loose_signature)
    multiprobe_query = set(
        simhash_fixed_band_multiprobe_keys(query_fp.loose_signature, bit_radius=2)
    )
    strategy_ranks: dict[str, int | None] = {}
    for strategy, query_binary_keys, key_builder in (
        (
            "fixed_8x8",
            set(fixed_query),
            simhash_fixed_band_keys,
        ),
        (
            "fixed_8x8_multiprobe_r2",
            multiprobe_query,
            simhash_fixed_band_keys,
        ),
        (
            BINARY_LAYOUT_VERSION,
            query_keys,
            simhash_multi_layout_keys,
        ),
    ):
        rows = []
        for candidate in corpus:
            overlap = len(
                query_binary_keys
                & set(key_builder(cache.fingerprint(candidate.text_b).loose_signature))
            )
            if overlap:
                rows.append((-overlap, candidate.pair_id))
        rows.sort()
        order = [candidate_id for _, candidate_id in rows[:50]]
        strategy_ranks[strategy] = (
            order.index(pair.pair_id) + 1 if pair.pair_id in order else None
        )
    return probe, channels, strategy_ranks


def _fuse(
    probe: ChunkDedupProbe,
    channels: dict[CandidateChannel, tuple[ChunkDedupCandidate, ...]],
    selected: tuple[CandidateChannel, ...],
    config: dict[str, Any],
) -> tuple[ChunkDedupCandidate, ...]:
    return fuse_chunk_candidates(
        (probe,),
        (
            candidate
            for channel in selected
            for candidate in channels[channel][: int(config["channel_candidate_k"])]
        ),
        final_limit=int(config["final_candidate_k"]),
        channel_reservation=int(config["channel_reservation"]),
        rrf_k=int(config["rrf_k"]),
    )


def _recall(ranks: list[int | None]) -> dict[str, float]:
    return {
        f"recall@{cutoff}": round(
            sum(rank is not None and rank <= cutoff for rank in ranks) / max(1, len(ranks)),
            6,
        )
        for cutoff in (1, 5, 10, 20, 50)
    }


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "mean": round(statistics.fmean(ordered), 6),
        "p50": round(ordered[(len(ordered) - 1) // 2], 6),
        "p95": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 6),
        "max": round(ordered[-1], 6),
    }


def _breakdown(
    pairs: tuple[GoldPair, ...],
    results: dict[str, PairCandidateResult],
    field: str,
) -> dict[str, dict[str, float | int]]:
    groups: dict[str, list[int | None]] = defaultdict(list)
    for pair in pairs:
        if not pair.candidate_retrieval_required:
            continue
        if field == "ocr_noise":
            key = max(
                (pair.ocr_noise_level_a.value, pair.ocr_noise_level_b.value),
                key=NOISE_RANK.__getitem__,
            )
        elif field == "source_form":
            key = f"{pair.source_form_a.value}_to_{pair.source_form_b.value}"
        elif field == "label":
            key = pair.expected_relation.value
        else:
            value = getattr(pair, field)
            key = value.value if hasattr(value, "value") else str(value)
        groups[key].append(results[pair.pair_id].rank)
    return {
        key: {"population": len(ranks), **_recall(ranks)}
        for key, ranks in sorted(groups.items())
    }


def _stress(config: dict[str, Any]) -> dict[str, object]:
    payload = json.loads(STRESS_CASES_PATH.read_text(encoding="utf-8"))
    long_case = payload["long_document"]
    chunks = []
    for index in range(int(long_case["chunk_count"])):
        text = (
            f"Khối tổng hợp số {index + 1} có nội dung vận hành độc lập và đủ dài để "
            "tham gia kiểm thử ứng viên tài liệu dài."
        )
        chunks.append(
            ChunkData(
                chunk_id=f"stress-{index}", chunk_index=index, text=text,
                embedding_text=text, search_text=text, page_number=index // 4 + 1,
                section_title=None, checksum=compute_checksum_text(text),
                document_id="stress", document_version=1, section_id=None,
                parent_chunk_id=None, offset_start=index * 200,
                offset_end=index * 200 + len(text), strategy="stress",
                strategy_version="1", config_checksum="stress",
                content_checksum=compute_checksum_text(text),
                source_block_ids=(f"block-{index}",), table_identity=None, metadata={},
            )
        )
    probes = build_chunk_dedup_probes(
        tuple(chunks),
        max_fuzzy_probes=None,
        high_recall_candidates=True,
    )
    eligible = {probe.chunk_index + 1 for probe in probes if probe.include_fuzzy_candidates}
    meaningful = set(long_case["meaningful_positions_1_based"])

    simhash_case = payload["simhash_lsh"]
    left = build_chunk_fingerprint(simhash_case["text_a"])
    right = build_chunk_fingerprint(simhash_case["text_b"])
    fixed_overlap = sum(
        a == b
        for a, b in zip(
            simhash_lsh_bands(left.loose_signature),
            simhash_lsh_bands(right.loose_signature),
            strict=True,
        )
    )
    multi_overlap = len(
        set(simhash_multi_layout_keys(left.loose_signature))
        & set(simhash_multi_layout_keys(right.loose_signature))
    )
    return {
        "long_document": {
            "chunk_count": len(chunks),
            "eligible_probe_count": len(eligible),
            "eligible_probe_coverage": round(len(eligible) / len(chunks), 6),
            "meaningful_position_recall": round(len(eligible & meaningful) / len(meaningful), 6),
        },
        "simhash_counterexample": {
            "hamming_distance": simhash_hamming_distance(
                left.loose_signature,
                right.loose_signature,
            ),
            "fixed_aligned_band_overlap": fixed_overlap,
            "selected_multilayout_overlap": multi_overlap,
            "recovered_by_selected_binary": multi_overlap > 0,
        },
        "configured_final_candidate_k": config["final_candidate_k"],
    }


def _scale_benchmark() -> dict[str, object]:
    size = 10_000
    started = time.perf_counter()
    binary_index: dict[str, list[int]] = defaultdict(list)
    fts_index: dict[str, list[int]] = defaultdict(list)
    signatures = [
        hashlib.sha256(f"scale:{index}".encode()).hexdigest()[:16]
        for index in range(size)
    ]
    for index, signature in enumerate(signatures):
        for key in simhash_multi_layout_keys(signature):
            binary_index[key].append(index)
        for term in (f"entity{index % 997}", f"period{index % 24}", "vin"):
            fts_index[term].append(index)
    build_ms = (time.perf_counter() - started) * 1000
    query_latencies = []
    candidate_counts = []
    for index in range(100):
        started = time.perf_counter()
        candidates: set[int] = set()
        for key in simhash_multi_layout_keys(signatures[index * 97 % size]):
            candidates.update(binary_index.get(key, ()))
        candidates.update(fts_index[f"entity{index % 997}"])
        query_latencies.append((time.perf_counter() - started) * 1000)
        candidate_counts.append(len(candidates))
    return {
        "fixture": "in-memory inverted binary+lexical indexes",
        "corpus_chunks": size,
        "build_ms": round(build_ms, 3),
        "query_latency_ms": _distribution(query_latencies),
        "raw_union_candidate_count": _distribution([float(value) for value in candidate_counts]),
        "production_database_benchmark": "not_run_no_production_like_postgres_fixture",
        "100k_benchmark": "not_run_workstation_memory_guard",
    }


def build_report(
    pairs: tuple[GoldPair, ...],
    *,
    split: str,
    include_scale: bool = True,
) -> dict[str, object]:
    validation = validate_pairs(pairs, require_full=False)
    if not validation.valid:
        raise ValueError("Dataset validation failed: " + "; ".join(validation.errors))
    if any(pair.split != split for pair in pairs):
        raise ValueError(f"P1 {split} evaluation received another split")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cache = _FixtureCache(int(config["deterministic_ann_fixture"]["dimensions"]))
    required_pairs = tuple(pair for pair in pairs if pair.candidate_retrieval_required)
    results: dict[str, PairCandidateResult] = {}
    binary_strategy_ranks: dict[str, list[int | None]] = defaultdict(list)
    channel_hits: dict[str, list[int | None]] = defaultdict(list)
    ablation_hits: dict[str, list[int | None]] = defaultdict(list)
    channel_unique: Counter[str] = Counter()
    sweep_ranks: dict[str, list[int | None]] = defaultdict(list)
    sweep_counts: dict[str, list[float]] = defaultdict(list)
    sweep_latencies: dict[str, list[float]] = defaultdict(list)
    full_channels = tuple(CandidateChannel)
    ablations = {
        "exact_only": (CandidateChannel.EXACT,),
        "exact_binary": (CandidateChannel.EXACT, CandidateChannel.BINARY),
        "exact_fts": (CandidateChannel.EXACT, CandidateChannel.FTS),
        "exact_ann": (CandidateChannel.EXACT, CandidateChannel.ANN),
        "all_minus_exact": tuple(c for c in full_channels if c is not CandidateChannel.EXACT),
        "all_minus_binary": tuple(c for c in full_channels if c is not CandidateChannel.BINARY),
        "all_minus_fts": tuple(c for c in full_channels if c is not CandidateChannel.FTS),
        "all_minus_ann": tuple(c for c in full_channels if c is not CandidateChannel.ANN),
        "all_channels": full_channels,
    }
    sweep_configs = {
        "channel_k_15": {**config, "channel_candidate_k": 15},
        "channel_k_30": {**config, "channel_candidate_k": 30},
        "channel_k_50": {**config, "channel_candidate_k": 50},
        "final_k_20": {**config, "final_candidate_k": 20},
        "final_k_50": {**config, "final_candidate_k": 50},
    }

    for pair in required_pairs:
        started = time.perf_counter()
        probe, channels, strategy_ranks = _channel_candidates(pair, pairs, cache, config)
        target_id = f"target:{pair.pair_id}"
        channel_ranks = {
            channel.value: _rank_of(
                target_id,
                candidates[: int(config["channel_candidate_k"])],
            )
            for channel, candidates in channels.items()
        }
        ablation_ranks = {
            name: _rank_of(target_id, _fuse(probe, channels, selected, config))
            for name, selected in ablations.items()
        }
        fused = _fuse(probe, channels, full_channels, config)
        for name, sweep_config in sweep_configs.items():
            sweep_started = time.perf_counter()
            sweep_fused = _fuse(probe, channels, full_channels, sweep_config)
            sweep_latencies[name].append((time.perf_counter() - sweep_started) * 1000)
            sweep_ranks[name].append(_rank_of(target_id, sweep_fused))
            sweep_counts[name].append(float(len(sweep_fused)))
        elapsed_ms = (time.perf_counter() - started) * 1000
        result = PairCandidateResult(
            pair_id=pair.pair_id,
            rank=_rank_of(target_id, fused),
            candidate_count=len(fused),
            channel_ranks=channel_ranks,
            ablation_ranks=ablation_ranks,
            latency_ms=round(elapsed_ms, 6),
        )
        results[pair.pair_id] = result
        for strategy, rank in strategy_ranks.items():
            binary_strategy_ranks[strategy].append(rank)
        for channel, rank in channel_ranks.items():
            channel_hits[channel].append(rank)
        for name, rank in ablation_ranks.items():
            ablation_hits[name].append(rank)
        present = [channel for channel, rank in channel_ranks.items() if rank is not None]
        if len(present) == 1:
            channel_unique[present[0]] += 1

    safety_pairs = pairs
    false_reuse = 0
    reuse_eligible = 0
    for pair in safety_pairs:
        strict = strict_normalize_text(pair.text_a) == strict_normalize_text(pair.text_b)
        checksum = compute_checksum_text(normalize_text(pair.text_a)) == compute_checksum_text(
            normalize_text(pair.text_b)
        )
        eligible = strict and checksum
        reuse_eligible += int(eligible)
        false_reuse += int(eligible and not pair.expected_auto_reuse)

    full_ranks = [results[pair.pair_id].rank for pair in required_pairs]
    report: dict[str, object] = {
        "version": config["version"],
        "split": split,
        "frozen_gold_unchanged": True,
        "config": config,
        "dataset": {
            **validation.to_payload(),
            "retrieval_population": len(required_pairs),
            "distinct_pairs_excluded_from_relevant_population": sum(
                pair.expected_relation is GoldRelation.DISTINCT
                and not pair.candidate_retrieval_required
                for pair in pairs
            ),
            "controlled_corpus_size_per_query": CANDIDATE_DISTRACTOR_COUNT + 1,
        },
        "candidate_generation": {
            **_recall(full_ranks),
            "candidate_count": _distribution(
                [float(results[pair.pair_id].candidate_count) for pair in required_pairs]
            ),
            "latency_ms": _distribution(
                [results[pair.pair_id].latency_ms for pair in required_pairs]
            ),
        },
        "binary_strategies": {
            name: _recall(ranks) for name, ranks in sorted(binary_strategy_ranks.items())
        },
        "channels": {
            name: {**_recall(ranks), "unique_recovery_count": channel_unique[name]}
            for name, ranks in sorted(channel_hits.items())
        },
        "ablations": {
            name: _recall(ranks) for name, ranks in sorted(ablation_hits.items())
        },
        "parameter_sweeps": {
            name: {
                **_recall(sweep_ranks[name]),
                "candidate_count": _distribution(sweep_counts[name]),
                "fusion_latency_ms": _distribution(sweep_latencies[name]),
            }
            for name in sorted(sweep_configs)
        },
        "breakdowns": {
            field: _breakdown(required_pairs, results, field)
            for field in ("domain", "label", "difficulty", "source_form", "ocr_noise")
        },
        "stress": _stress(config),
        "safety": {
            "false_auto_reuse_count": false_reuse,
            "reuse_eligible_count": reuse_eligible,
            "reuse_rule": (
                "strict normalized text + embedding input checksum; production also "
                "requires model match and vector"
            ),
        },
        "scale": _scale_benchmark() if include_scale else {"status": "skipped"},
        "pair_results": [asdict(results[pair.pair_id]) for pair in required_pairs],
    }
    return report


def _pct(value: float | int | str) -> str:
    return f"{float(value) * 100:.1f}%"


def markdown(report: dict[str, Any]) -> str:
    candidate = report["candidate_generation"]
    safety = report["safety"]
    stress = report["stress"]
    lines = [
        f"# P1 candidate generation — {report['split'].upper()}",
        "",
        "> Frozen P0 gold labels and split; deterministic offline ANN fixture; no network calls.",
        "",
        "## Primary result",
        "",
        f"- Recall@1/5/10/20/50: **{_pct(candidate['recall@1'])} / "
        f"{_pct(candidate['recall@5'])} / {_pct(candidate['recall@10'])} / "
        f"{_pct(candidate['recall@20'])} / {_pct(candidate['recall@50'])}**.",
        f"- Retrieval population: **{report['dataset']['retrieval_population']}**; "
        f"final candidate cap: **{report['config']['final_candidate_k']}**.",
        f"- Latency mean/p50/p95/max (controlled 61-item corpus): "
        f"**{candidate['latency_ms']['mean']} / {candidate['latency_ms']['p50']} / "
        f"{candidate['latency_ms']['p95']} / {candidate['latency_ms']['max']} ms**.",
        "",
        "## Binary strategies",
        "",
        "| Strategy | R@5 | R@20 | R@50 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, values in report["binary_strategies"].items():
        lines.append(
            f"| {name} | {_pct(values['recall@5'])} | {_pct(values['recall@20'])} | "
            f"{_pct(values['recall@50'])} |"
        )
    lines.extend(
        [
            "",
            "## Channel ablation",
            "",
            "| Configuration | R@5 | R@20 | R@50 |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for name, values in report["ablations"].items():
        lines.append(
            f"| {name} | {_pct(values['recall@5'])} | {_pct(values['recall@20'])} | "
            f"{_pct(values['recall@50'])} |"
        )
    lines.extend(
        [
            "",
            "## Stress and safety",
            "",
            f"- Long-document eligible/meaningful coverage: "
            f"**{_pct(stress['long_document']['eligible_probe_coverage'])} / "
            f"{_pct(stress['long_document']['meaningful_position_recall'])}**.",
            f"- Hamming-{stress['simhash_counterexample']['hamming_distance']} counterexample: "
            f"fixed overlap **{stress['simhash_counterexample']['fixed_aligned_band_overlap']}**, "
            "multi-layout overlap "
            f"**{stress['simhash_counterexample']['selected_multilayout_overlap']}**.",
            f"- False automatic reuse: **{safety['false_auto_reuse_count']}**.",
            "",
            "## Interpretation limits",
            "",
            "- FTS is a deterministic local ranking approximation over the same bounded OR terms; "
            "the migration uses the real PostgreSQL `search_vector`/GIN/`ts_rank_cd` path.",
            "- ANN uses a locked 1024-dimensional hashed fixture so CI requires no model "
            "or network; "
            "production uses the configured vector index and existing document embeddings.",
            "- The 10k scale result is an in-memory inverted-index diagnostic, not a production "
            "PostgreSQL/Qdrant latency claim. No 100k run was made under the workstation "
            "memory guard.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, object], *, overwrite_frozen_test: bool = False) -> Path:
    split = str(report["split"])
    path = REPORT_DIR / f"p1_candidate_generation_{split}.json"
    markdown_path = REPORT_DIR / f"p1_candidate_generation_{split}.md"
    if split == "test" and path.exists() and not overwrite_frozen_test:
        raise FileExistsError("Frozen P1 TEST report already exists; refusing a second test look")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(markdown(report), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--frozen-test", action="store_true")
    parser.add_argument("--no-scale", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--overwrite-frozen-test", action="store_true")
    args = parser.parse_args(argv)
    if args.split == "test" and not args.frozen_test:
        parser.error("TEST is frozen; pass --frozen-test only after DEV configuration is final")
    path = DEV_DATASET_PATH if args.split == "dev" else TEST_DATASET_PATH
    pairs = load_pairs(path)
    report = build_report(pairs, split=args.split, include_scale=not args.no_scale)
    output = None
    if not args.no_write:
        output = write_report(report, overwrite_frozen_test=args.overwrite_frozen_test)
    summary = {
        "split": args.split,
        "population": report["dataset"]["retrieval_population"],  # type: ignore[index]
        "recall@50": report["candidate_generation"]["recall@50"],  # type: ignore[index]
        "false_auto_reuse": report["safety"]["false_auto_reuse_count"],  # type: ignore[index]
        "report": str(output) if output else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_report", "main", "markdown", "write_report"]
