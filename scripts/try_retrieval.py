"""Interactive smoke test for the retrieval flow (see retrieval_SPEC.html).

Wires the same real placeholder adapters as
tests/integration/test_retrieval_request_end_to_end.py, seeds a tiny sample
corpus, then lets you type your own questions and see exactly what the flow
returns — FixedAnswer / ClarificationNeeded / AgenticRetrievalResult.

Run from the repository root:

    PYTHONPATH=src python3 scripts/try_retrieval.py
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

OWNER_ID = "demo-user"

SAMPLE_CHUNKS = [
    EvidenceChunk(
        id="c1",
        document_id="doc-1",
        text="Doanh thu quý 3 của công ty đạt 5 tỷ đồng, tăng 20% so với quý 2.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c2",
        document_id="doc-1",
        text="Trưởng phòng kinh doanh là bà Nguyễn Thị B, phụ trách từ năm 2022.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c3",
        document_id="doc-1",
        text="Chi phí vận hành quý 3 là 2 tỷ đồng, chủ yếu cho nhân sự và marketing.",
        metadata={"owner_id": OWNER_ID},
    ),
]


def build_handler() -> RetrievalRequestHandler:
    search = HybridRetrievalAdapter(
        bm25=InMemoryBM25RetrievalAdapter(), dense=HashingDenseRetrievalAdapter()
    )
    for chunk in SAMPLE_CHUNKS:
        search.index(chunk)
    return RetrievalRequestHandler(
        contextualizer=HeuristicContextualizer(),
        adaptive_classifier=HeuristicAdaptiveClassifier(),
        agentic_retrieval=AgenticRetrievalUseCase(
            retrieval_port=search,
            sufficiency_checker=KeywordOverlapSufficiencyChecker(min_overlap_ratio=0.4),
            reformulator=FallbackQueryReformulator(),
        ),
    )


def print_result(result: object) -> None:
    if isinstance(result, ClarificationNeeded):
        print(f"[HỎI LẠI USER] {result.clarifying_question}")
        print(f"  (lý do: {result.reasoning})")
    elif isinstance(result, FixedAnswer):
        print(f"[TRẢ LỜI CỐ ĐỊNH] {result.answer}")
        print(f"  (lý do: {result.reasoning})")
    elif isinstance(result, AgenticRetrievalResult):
        status = "GIVE UP" if result.gave_up else "OK"
        print(f"[RETRIEVAL {status}] {result.rounds_used} vòng, {len(result.evidence)} evidence:")
        for candidate in result.evidence:
            print(f"  - [{candidate.chunk.id}] {candidate.chunk.text}")
        print("  Trace:")
        for step in result.trace:
            check = step.sufficiency
            print(
                f"    round {step.round_index}: query={step.query_used!r} "
                f"new_evidence={step.new_evidence_count} "
                f"sufficient={check.sufficient} missing={check.missing!r}"
            )
    else:
        print(f"[UNKNOWN RESULT TYPE] {result!r}")


def main() -> None:
    handler = build_handler()
    print("Sample corpus đã nạp 3 chunk (doanh thu, trưởng phòng, chi phí).")
    print("Gõ câu hỏi rồi Enter. Gõ 'exit' để thoát.\n")

    history: list[str] = []
    while True:
        try:
            message = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message or message.lower() in {"exit", "quit"}:
            break

        result = handler.handle(
            message=message,
            history=tuple(history),
            filters=RetrievalFilters(owner_id=OWNER_ID),
            top_k=5,
        )
        print_result(result)
        print()
        history.append(message)


if __name__ == "__main__":
    main()
