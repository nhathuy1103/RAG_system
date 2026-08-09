from __future__ import annotations

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.adapters.dense_search import HashingDenseRetrievalAdapter
from app.retrieval.adapters.hybrid_search import HybridRetrievalAdapter
from app.retrieval.adapters.local_reformulation import FallbackQueryReformulator
from app.retrieval.adapters.local_reranker import IdentityReranker
from app.retrieval.adapters.local_sufficiency import KeywordOverlapSufficiencyChecker
from app.retrieval.application.agentic_retrieval import AgenticRetrievalUseCase
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate, RetrievalFilters


def _seeded_adapter() -> HybridRetrievalAdapter:
    adapter = HybridRetrievalAdapter(
        sparse=InMemoryBM25RetrievalAdapter(), dense=HashingDenseRetrievalAdapter()
    )
    adapter.index(
        EvidenceChunk(
            id="c1",
            document_id="doc-1",
            text="Doanh thu quý 3 của phòng kinh doanh đạt 5 tỷ đồng.",
            metadata={"owner_id": "user-1"},
        )
    )
    adapter.index(
        EvidenceChunk(
            id="c2",
            document_id="doc-1",
            text="Trưởng phòng kinh doanh là Nguyễn Văn A.",
            metadata={"owner_id": "user-1"},
        )
    )
    adapter.index(
        EvidenceChunk(
            id="other-user",
            document_id="doc-2",
            text="Doanh thu quý 3 của phòng kinh doanh đạt 5 tỷ đồng.",
            metadata={"owner_id": "someone-else"},
        )
    )
    return adapter


class TestKeywordOverlapSufficiencyChecker:
    def test_sufficient_once_overlap_ratio_is_met(self) -> None:
        checker = KeywordOverlapSufficiencyChecker(min_overlap_ratio=0.5)
        evidence = (
            RetrievalCandidate(
                chunk=EvidenceChunk(id="c1", document_id="d", text="doanh thu quý 3 tăng mạnh"),
                score=1.0,
                rank=1,
            ),
        )

        check = checker.check("doanh thu quý 3 là bao nhiêu?", evidence)

        assert check.sufficient is True

    def test_insufficient_reports_missing_keywords(self) -> None:
        checker = KeywordOverlapSufficiencyChecker(min_overlap_ratio=0.9)
        evidence = (
            RetrievalCandidate(
                chunk=EvidenceChunk(id="c1", document_id="d", text="doanh thu quý 3"),
                score=1.0,
                rank=1,
            ),
        )

        check = checker.check("phòng nào doanh thu cao nhất và ai đứng đầu?", evidence)

        assert check.sufficient is False
        assert check.missing is not None


def test_identity_reranker_preserves_order_and_respects_top_k() -> None:
    candidates = (
        RetrievalCandidate(chunk=EvidenceChunk(id="a", document_id="d", text=""), score=2, rank=1),
        RetrievalCandidate(chunk=EvidenceChunk(id="b", document_id="d", text=""), score=1, rank=2),
    )

    result = IdentityReranker().rerank("q", candidates, top_k=1)

    assert [c.chunk.id for c in result] == ["a"]


def test_fallback_reformulator_prefers_missing_over_original_question() -> None:
    reformulator = FallbackQueryReformulator()

    assert reformulator.reformulate(original_question="A và B?", evidence=(), missing="B?") == "B?"
    assert (
        reformulator.reformulate(original_question="A và B?", evidence=(), missing=None)
        == "A và B?"
    )


def test_full_wiring_answers_a_two_part_question_across_rounds() -> None:
    """End-to-end sanity check: placeholder adapters wired through the real use case."""
    use_case = AgenticRetrievalUseCase(
        retrieval_port=_seeded_adapter(),
        sufficiency_checker=KeywordOverlapSufficiencyChecker(min_overlap_ratio=0.6),
        reformulator=FallbackQueryReformulator(),
        reranker=IdentityReranker(),
        max_rounds=3,
    )

    result = use_case.run(
        original_question=(
            "doanh thu quý 3 của phòng kinh doanh là bao nhiêu và trưởng phòng là ai?"
        ),
        filters=RetrievalFilters(owner_id="user-1"),
        top_k=5,
    )

    assert {c.chunk.id for c in result.evidence} <= {"c1", "c2"}
    assert result.rounds_used >= 1
