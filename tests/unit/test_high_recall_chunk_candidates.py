from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from app.knowledge_quality.application.analysis import build_chunk_fingerprint
from app.knowledge_quality.application.candidate_generation import (
    candidate_fts_terms,
    fuse_chunk_candidates,
    simhash_fixed_band_keys,
    simhash_fixed_band_multiprobe_keys,
    simhash_multi_layout_keys,
)
from app.knowledge_quality.application.chunk_preembedding import (
    build_chunk_dedup_probes,
    plan_chunk_deduplication,
    simhash_hamming_distance,
)
from app.knowledge_quality.application.detection import (
    detect_fused_document_relation_candidates,
)
from app.knowledge_quality.domain.models import (
    CandidateChannel,
    CandidateChannelEvidence,
    ChunkDedupCandidate,
    ChunkDedupProbe,
)
from app.pipeline.indexing.application.chunker import ChunkData
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.pipeline.indexing.ports.vector_index import VectorSearchHit
from app.pipeline.shared.text_utils import compute_checksum_text, normalize_text

TARGET_DOCUMENT_ID = UUID("10000000-0000-0000-0000-000000000001")


def _chunk(index: int, text: str) -> ChunkData:
    return ChunkData(
        chunk_id=f"chunk-{index}", chunk_index=index, text=text,
        embedding_text=text, search_text=text, page_number=index + 1,
        section_title=None, checksum=compute_checksum_text(text),
        document_id="source", document_version=1, section_id=None,
        parent_chunk_id=None, offset_start=index * 200,
        offset_end=index * 200 + len(text), strategy="test", strategy_version="1",
        config_checksum="test", content_checksum=compute_checksum_text(text),
        source_block_ids=(f"block-{index}",), table_identity=None, metadata={},
    )


def _probe(text: str) -> ChunkDedupProbe:
    fingerprint = build_chunk_fingerprint(text)
    return ChunkDedupProbe(
        chunk_index=0,
        chunk_id="source-0",
        canonical_text=text,
        embedding_text_checksum=compute_checksum_text(normalize_text(text)),
        fingerprint=fingerprint,
        include_fuzzy_candidates=True,
        binary_keys=simhash_multi_layout_keys(fingerprint.loose_signature),
        fts_terms=candidate_fts_terms(text),
    )


def _candidate(
    probe: ChunkDedupProbe,
    channel: CandidateChannel,
    *,
    rank: int = 1,
    checksum: str | None = None,
    model: str = "model-v1",
) -> ChunkDedupCandidate:
    return ChunkDedupCandidate(
        source_chunk_index=probe.chunk_index,
        target_chunk_id="target-0",
        target_document_id=TARGET_DOCUMENT_ID,
        target_chunk_index=0,
        canonical_text=probe.canonical_text,
        normalized_content_hash=probe.fingerprint.strict_hash,
        normalization_version=probe.fingerprint.normalization_version,
        loose_content_signature=probe.fingerprint.loose_signature,
        embedding_text_checksum=checksum,
        embedding=(0.1, 0.2),
        embedding_model=model,
        channel_evidence=(CandidateChannelEvidence(channel, rank, 1.0),),
    )


def test_binary_strategies_are_bounded_and_selected_layout_recovers_counterexample() -> None:
    payload = json.loads(
        Path("datasets/duplicate_conflict/stress_cases.json").read_text(encoding="utf-8")
    )["simhash_lsh"]
    left = build_chunk_fingerprint(payload["text_a"]).loose_signature
    right = build_chunk_fingerprint(payload["text_b"]).loose_signature

    assert simhash_hamming_distance(left, right) == 21
    assert not (set(simhash_fixed_band_keys(left)) & set(simhash_fixed_band_keys(right)))
    assert set(simhash_multi_layout_keys(left)) & set(simhash_multi_layout_keys(right))
    assert len(simhash_multi_layout_keys(left)) == 64
    assert len(simhash_fixed_band_multiprobe_keys(left, bit_radius=2)) == 296


def test_high_recall_probe_generation_covers_every_eligible_long_document_chunk() -> None:
    chunks = tuple(
        _chunk(
            index,
            f"Nội dung vận hành dài số {index} cho dự án Alpha, kỳ 2026 và giá trị 120 triệu đồng.",
        )
        for index in range(100)
    )
    probes = build_chunk_dedup_probes(
        chunks,
        max_fuzzy_probes=None,
        high_recall_candidates=True,
    )

    assert len(probes) == 100
    assert all(probe.include_fuzzy_candidates for probe in probes)
    assert all(len(probe.binary_keys) == 64 for probe in probes)
    assert all(probe.fts_terms for probe in probes)


def test_fts_terms_are_bounded_deterministic_and_present_in_payload() -> None:
    text = "Vinhomes Alpha có phí quản lý 12.000 đồng mỗi mét vuông trong năm 2026."
    probe = _probe(text)

    assert probe.fts_terms == candidate_fts_terms(text)
    assert 0 < len(probe.fts_terms) <= 16
    assert probe.to_payload()["fts_terms"] == list(probe.fts_terms)


def test_union_deduplicates_stable_target_and_retains_channel_evidence() -> None:
    probe = _probe("Giá căn hộ Alpha năm 2026 là 4 tỷ đồng và áp dụng cho tòa S1.01.")
    exact = _candidate(probe, CandidateChannel.EXACT)
    fts = _candidate(probe, CandidateChannel.FTS, rank=3)

    fused = fuse_chunk_candidates((probe,), (fts, exact), final_limit=50)

    assert len(fused) == 1
    assert {item.channel for item in fused[0].channel_evidence} == {
        CandidateChannel.EXACT,
        CandidateChannel.FTS,
    }
    assert fused[0].fused_score > 0


def test_exact_reuse_still_requires_checksum_model_vector_and_strict_verification() -> None:
    probe = _probe("Chính sách bảo hành pin Alpha áp dụng 10 năm hoặc 200.000 km.")
    wrong_checksum = _candidate(
        probe,
        CandidateChannel.EXACT,
        checksum="different",
    )
    blocked = plan_chunk_deduplication(
        (probe,),
        (wrong_checksum,),
        embedding_model="model-v1",
        enable_exact_reuse=True,
    )
    reusable = _candidate(
        probe,
        CandidateChannel.EXACT,
        checksum=probe.embedding_text_checksum,
    )
    allowed = plan_chunk_deduplication(
        (probe,),
        (reusable,),
        embedding_model="model-v1",
        enable_exact_reuse=True,
    )

    assert blocked.precomputed_vectors == {}
    assert allowed.precomputed_vectors == {0: (0.1, 0.2)}


class _AnnIndex:
    def __init__(self) -> None:
        self.query_count = 0

    def query(self, embedding: tuple[float, ...], **_: object) -> list[VectorSearchHit]:
        self.query_count += 1
        return [
            VectorSearchHit(
                chunk_id=f"ann-target-{self.query_count}",
                document_id=str(TARGET_DOCUMENT_ID),
                score=0.94,
                text="Giá căn hộ Alpha năm 2026 là 4 tỷ đồng và áp dụng cho tòa S1.01.",
                page_number=1,
                section_title=None,
                document_version=1,
                chunk_index=self.query_count - 1,
            )
        ]


def test_ann_path_queries_every_eligible_chunk_and_joins_the_same_fusion_core() -> None:
    texts = (
        "Giá căn hộ Alpha năm 2026 là 4 tỷ đồng và áp dụng cho tòa S1.01.",
        "Phí quản lý Alpha năm 2026 là 12.000 đồng trên mét vuông mỗi tháng.",
        "Chính sách bàn giao Alpha năm 2026 áp dụng trong quý ba.",
    )
    probes = tuple(_probe(text) for text in texts)
    probes = tuple(
        ChunkDedupProbe(
            chunk_index=index,
            chunk_id=f"source-{index}",
            canonical_text=probe.canonical_text,
            embedding_text_checksum=probe.embedding_text_checksum,
            fingerprint=probe.fingerprint,
            include_fuzzy_candidates=True,
            binary_keys=probe.binary_keys,
            fts_terms=probe.fts_terms,
        )
        for index, probe in enumerate(probes)
    )
    chunks = tuple(
        EmbeddedChunk(
            id=f"source-{index}", document_id="20000000-0000-0000-0000-000000000001",
            document_version=1, owner_id="owner", tenant_id="tenant", chunk_index=index,
            page_number=1, section_title=None, checksum=compute_checksum_text(text),
            text=text, canonical_text=text, token_count=len(text.split()),
            embedding=(1.0, float(index)), embedding_model="model-v1",
        )
        for index, text in enumerate(texts)
    )
    index = _AnnIndex()

    result = detect_fused_document_relation_candidates(
        vector_index=index,  # type: ignore[arg-type]
        chunks=chunks,
        probes=probes,
        preembedding_candidates=(),
        candidates_per_channel=5,
        final_candidate_limit=50,
    )

    assert index.query_count == len(chunks)
    assert result.probe_count == len(chunks)
    assert result.ann_candidate_count == len(chunks)
    assert all(
        candidate.channel_evidence[0].channel is CandidateChannel.ANN
        for candidate in result.candidates
    )
