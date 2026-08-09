from __future__ import annotations

from uuid import UUID

import pytest

from app.knowledge_quality.application.analysis import build_chunk_fingerprint
from app.knowledge_quality.application.chunk_preembedding import (
    ChunkIdentityConflictError,
    plan_chunk_deduplication,
    simhash_hamming_distance,
    simhash_lsh_bands,
)
from app.knowledge_quality.domain.models import (
    ChunkDedupCandidate,
    ChunkDedupProbe,
    ClaimScope,
    RelationType,
)
from app.pipeline.shared.text_utils import compute_checksum_text, normalize_text

TARGET_DOCUMENT_ID = UUID("50000000-0000-0000-0000-000000000005")


def _probe(
    text: str,
    *,
    chunk_index: int = 0,
    embedding_text: str | None = None,
    include_fuzzy: bool = True,
    scope: ClaimScope | None = None,
) -> ChunkDedupProbe:
    return ChunkDedupProbe(
        chunk_index=chunk_index,
        chunk_id=f"source-{chunk_index}",
        canonical_text=text,
        embedding_text_checksum=compute_checksum_text(normalize_text(embedding_text or text)),
        fingerprint=build_chunk_fingerprint(text),
        include_fuzzy_candidates=include_fuzzy,
        scope=scope,
    )


def _candidate(
    probe: ChunkDedupProbe,
    *,
    text: str | None = None,
    normalized_hash: str | None = None,
    embedding_text_checksum: str | None = None,
    embedding_model: str = "embedding-v1",
    embedding: tuple[float, ...] = (0.1, 0.2, 0.3),
    scope: ClaimScope | None = None,
) -> ChunkDedupCandidate:
    candidate_text = text or probe.canonical_text
    fingerprint = build_chunk_fingerprint(candidate_text)
    probe_bands = simhash_lsh_bands(probe.fingerprint.loose_signature)
    candidate_bands = simhash_lsh_bands(fingerprint.loose_signature)
    return ChunkDedupCandidate(
        source_chunk_index=probe.chunk_index,
        target_chunk_id="60000000-0000-0000-0000-000000000006",
        target_document_id=TARGET_DOCUMENT_ID,
        target_chunk_index=3,
        canonical_text=candidate_text,
        normalized_content_hash=normalized_hash or fingerprint.strict_hash,
        normalization_version=fingerprint.normalization_version,
        loose_content_signature=fingerprint.loose_signature,
        embedding_text_checksum=(
            embedding_text_checksum
            if embedding_text_checksum is not None
            else probe.embedding_text_checksum
        ),
        embedding=embedding,
        embedding_model=embedding_model,
        lsh_band_matches=sum(
            left == right for left, right in zip(probe_bands, candidate_bands, strict=True)
        ),
        scope=scope or probe.scope,
    )


def test_exact_chunk_reuses_compatible_persisted_embedding() -> None:
    probe = _probe("The approved expense policy applies to every employee.")
    candidate = _candidate(probe)

    plan = plan_chunk_deduplication(
        (probe,),
        (candidate,),
        embedding_model="embedding-v1",
        enable_exact_reuse=True,
    )

    assert plan.precomputed_vectors == {0: candidate.embedding}
    assert plan.relations == ()
    assert plan.metadata_by_chunk_index[0]["action"] == "reuse_exact_embedding"
    assert plan.metadata_by_chunk_index[0]["embedding_reused"] is True


def test_exact_content_with_different_embedding_context_is_not_reused() -> None:
    probe = _probe(
        "The approved expense policy applies to every employee.",
        embedding_text="Finance > The approved expense policy applies to every employee.",
    )
    candidate = _candidate(
        probe,
        embedding_text_checksum=compute_checksum_text(
            "HR > The approved expense policy applies to every employee."
        ),
    )

    plan = plan_chunk_deduplication(
        (probe,),
        (candidate,),
        embedding_model="embedding-v1",
        enable_exact_reuse=True,
    )

    assert plan.precomputed_vectors == {}
    assert plan.metadata_by_chunk_index[0]["action"] == "exact_match_embedding_context_changed"


def test_shadow_observes_exact_match_without_reusing_vector() -> None:
    probe = _probe("The approved expense policy applies to every employee.")
    candidate = _candidate(probe)

    plan = plan_chunk_deduplication(
        (probe,),
        (candidate,),
        embedding_model="embedding-v1",
        enable_exact_reuse=False,
    )

    assert plan.precomputed_vectors == {}
    assert plan.reuse_from_chunk_index == {}
    assert plan.metadata_by_chunk_index[0]["action"] == "exact_match_observed"
    assert plan.metadata_by_chunk_index[0]["embedding_reused"] is False


def test_same_strict_hash_with_different_text_blocks_the_plan() -> None:
    probe = _probe("The approved reimbursement limit is five million VND.")
    candidate = _candidate(
        probe,
        text="The approved reimbursement limit is seven million VND.",
        normalized_hash=probe.fingerprint.strict_hash,
    )

    with pytest.raises(ChunkIdentityConflictError, match="different normalized"):
        plan_chunk_deduplication(
            (probe,),
            (candidate,),
            embedding_model="embedding-v1",
            enable_exact_reuse=True,
        )


def test_near_duplicate_is_flagged_but_not_reused() -> None:
    probe = _probe(
        "All employees must submit the monthly expense report before the Friday deadline."
    )
    candidate = _candidate(
        probe,
        text=("All employees must submit the monthly expense reports before the Friday deadline."),
    )
    assert candidate.lsh_band_matches > 0

    plan = plan_chunk_deduplication(
        (probe,),
        (candidate,),
        embedding_model="embedding-v1",
        enable_exact_reuse=True,
    )

    assert plan.precomputed_vectors == {}
    assert plan.metadata_by_chunk_index[0]["relation_type"] == "near_duplicate"
    assert plan.relations[0].relation_type == RelationType.NEAR_DUPLICATE
    assert plan.relations[0].target_document_id == TARGET_DOCUMENT_ID


def test_number_change_is_a_conflict_candidate_and_keeps_both_vectors() -> None:
    probe = _probe(
        "The reimbursement limit is 5 million VND for each approved request.",
        scope=ClaimScope(project_id="project-a"),
    )
    candidate = _candidate(
        probe,
        text=("The reimbursement limit is 7 million VND for each approved request."),
    )
    assert candidate.lsh_band_matches > 0

    plan = plan_chunk_deduplication(
        (probe,),
        (candidate,),
        embedding_model="embedding-v1",
        enable_exact_reuse=True,
    )

    assert plan.precomputed_vectors == {}
    assert plan.metadata_by_chunk_index[0]["relation_type"] == "conflict_candidate"
    assert plan.relations[0].relation_type == RelationType.CONFLICT_CANDIDATE
    reason_codes = plan.relations[0].signals["reason_codes"]
    assert isinstance(reason_codes, list)
    assert "semantic_quantity_mismatch" in reason_codes


def test_different_scope_value_change_aggregates_as_template_variant() -> None:
    probe = _probe(
        "The reimbursement limit is 5 million VND for each approved request.",
        scope=ClaimScope(project_id="project-a"),
    )
    candidate = _candidate(
        probe,
        text="The reimbursement limit is 7 million VND for each approved request.",
        scope=ClaimScope(project_id="project-b"),
    )

    plan = plan_chunk_deduplication(
        (probe,),
        (candidate,),
        embedding_model="embedding-v1",
        enable_exact_reuse=True,
    )

    assert plan.conflict_candidate_count == 0
    assert plan.template_variant_count == 1
    assert plan.relations[0].relation_type == RelationType.TEMPLATE_VARIANT
    assert plan.relations[0].signals["validated_conflict_count"] == 0


def test_same_batch_exact_chunks_share_the_representative_vector() -> None:
    first = _probe(
        "Company registration number 0123456789.",
        chunk_index=0,
        include_fuzzy=False,
    )
    second = _probe(
        "Company registration number 0123456789.",
        chunk_index=1,
        include_fuzzy=False,
    )

    plan = plan_chunk_deduplication(
        (first, second),
        (),
        embedding_model="embedding-v1",
        enable_exact_reuse=True,
    )

    assert plan.reuse_from_chunk_index == {1: 0}
    assert plan.metadata_by_chunk_index[1]["action"] == "reuse_batch_exact_embedding"


def test_simhash_helpers_validate_and_measure_64_bit_signatures() -> None:
    assert simhash_lsh_bands("0123456789abcdef") == (
        "01",
        "23",
        "45",
        "67",
        "89",
        "ab",
        "cd",
        "ef",
    )
    assert (
        simhash_hamming_distance(
            "0000000000000000",
            "000000000000000f",
        )
        == 4
    )
    with pytest.raises(ValueError, match="16 hexadecimal"):
        simhash_hamming_distance("abc", "def")
