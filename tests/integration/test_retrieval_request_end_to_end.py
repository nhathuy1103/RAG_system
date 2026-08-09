"""End-to-end wiring check for the retrieval flow — ALL real (placeholder)
adapters, no fakes/mocks. Unit tests in tests/unit/retrieval prove each piece's
logic in isolation; this proves they still behave sensibly when composed
exactly like a real caller would (see retrieval_SPEC.html and
application/handle_retrieval_request.py).
"""

from __future__ import annotations

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.adapters.dense_search import HashingDenseRetrievalAdapter
from app.retrieval.adapters.hybrid_search import HybridRetrievalAdapter
from app.retrieval.adapters.local_adaptive import HeuristicAdaptiveClassifier
from app.retrieval.adapters.local_contextualizer import HeuristicContextualizer
from app.retrieval.adapters.local_reformulation import FallbackQueryReformulator
from app.retrieval.adapters.local_sufficiency import KeywordOverlapSufficiencyChecker
from app.retrieval.application.agentic_retrieval import AgenticRetrievalUseCase
from app.retrieval.application.handle_retrieval_request import (
    ClarificationNeeded,
    FixedAnswer,
    RetrievalRequestHandler,
)
from app.retrieval.domain.models import (
    AgenticRetrievalResult,
    EvidenceChunk,
    RetrievalFilters,
)


def _build_handler() -> RetrievalRequestHandler:
    """Wires every real placeholder adapter the same way a composition root
    would — this is the thing worth testing, not any single adapter alone."""
    search = HybridRetrievalAdapter(
        sparse=InMemoryBM25RetrievalAdapter(), dense=HashingDenseRetrievalAdapter()
    )
    search.index(
        EvidenceChunk(
            id="c1",
            document_id="doc-1",
            text="Doanh thu quý 3 của công ty đạt 5 tỷ đồng.",
            metadata={"owner_id": "user-1"},
        )
    )
    search.index(
        EvidenceChunk(
            id="c2",
            document_id="doc-1",
            text="Trưởng phòng kinh doanh là bà Nguyễn Thị B.",
            metadata={"owner_id": "user-1"},
        )
    )
    return RetrievalRequestHandler(
        contextualizer=HeuristicContextualizer(),
        adaptive_classifier=HeuristicAdaptiveClassifier(),
        agentic_retrieval=AgenticRetrievalUseCase(
            retrieval_port=search,
            sufficiency_checker=KeywordOverlapSufficiencyChecker(min_overlap_ratio=0.4),
            reformulator=FallbackQueryReformulator(),
        ),
    )


FILTERS = RetrievalFilters(owner_id="user-1")


def test_greeting_short_circuits_to_a_fixed_answer_without_retrieval() -> None:
    handler = _build_handler()

    result = handler.handle(message="Chào bạn", history=(), filters=FILTERS, top_k=5)

    assert isinstance(result, FixedAnswer)


def test_dangling_reference_with_no_history_asks_for_clarification() -> None:
    handler = _build_handler()

    result = handler.handle(message="còn đó thì sao?", history=(), filters=FILTERS, top_k=5)

    assert isinstance(result, ClarificationNeeded)
    assert result.clarifying_question


def test_real_document_question_returns_evidence_scoped_to_owner() -> None:
    handler = _build_handler()

    result = handler.handle(
        message="Doanh thu quý 3 của công ty là bao nhiêu?",
        history=(),
        filters=FILTERS,
        top_k=5,
    )

    assert isinstance(result, AgenticRetrievalResult)
    assert result.evidence
    assert all(c.chunk.metadata.get("owner_id") == "user-1" for c in result.evidence)


def test_question_about_another_users_documents_finds_nothing() -> None:
    handler = _build_handler()

    result = handler.handle(
        message="Doanh thu quý 3 của công ty là bao nhiêu?",
        history=(),
        filters=RetrievalFilters(owner_id="someone-else"),
        top_k=5,
    )

    assert isinstance(result, AgenticRetrievalResult)
    assert result.evidence == ()
    assert result.gave_up is True
