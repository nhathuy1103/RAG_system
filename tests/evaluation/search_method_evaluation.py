"""Đánh giá phương pháp search — harness đo Recall@k / MRR cho BM25-only,
Dense-only, và Hybrid.

Gọi thẳng ``RetrievalPort.search()`` của từng mode — KHÔNG đi qua
``AgenticRetrievalUseCase`` (không rerank, không score_threshold), vì hai
bước đó thuộc chính sách của vòng lặp agentic, không phải bản chất của thuật
toán search đang so sánh. Xem research/eval_search.html.

Đây là harness dùng chung, không phụ thuộc corpus/bộ câu hỏi cụ thể nào —
``toy_search_dataset.py`` chỉ là dữ liệu giả để kiểm tra harness chạy đúng;
khi có dữ liệu thật, chỉ cần thay ``GroundTruthExample`` list khác vào.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.retrieval.domain.models import RetrievalCandidate, RetrievalFilters
from app.retrieval.ports.retrieval_port import RetrievalPort


@dataclass(frozen=True)
class GroundTruthExample:
    """Một câu hỏi có đáp án đúng biết trước — "đề thi có đáp án"."""

    question: str
    expected_chunk_id: str
    category: str = "general"


@dataclass(frozen=True)
class ModeEvaluation:
    """Kết quả đánh giá của MỘT mode (BM25-only / Dense-only / Hybrid)."""

    mode_name: str
    recall_at_k: dict[int, float]
    mrr: float
    example_count: int


def hit_at_k(results: Sequence[RetrievalCandidate], expected_chunk_id: str, k: int) -> bool:
    """Đoạn đúng có nằm trong top-k kết quả không."""
    return any(candidate.chunk.id == expected_chunk_id for candidate in results[:k])


def reciprocal_rank(results: Sequence[RetrievalCandidate], expected_chunk_id: str) -> float:
    """1/hạng nếu tìm thấy đoạn đúng, 0.0 nếu không tìm thấy."""
    for position, candidate in enumerate(results, start=1):
        if candidate.chunk.id == expected_chunk_id:
            return 1.0 / position
    return 0.0


def evaluate_mode(
    *,
    mode_name: str,
    port: RetrievalPort,
    examples: Sequence[GroundTruthExample],
    filters: RetrievalFilters,
    k_values: Sequence[int],
) -> ModeEvaluation:
    """Chạy toàn bộ ``examples`` qua ``port``, tính Recall@k (mỗi k trong
    ``k_values``) và MRR tổng hợp."""
    if not examples:
        raise ValueError("examples must not be empty")
    if not k_values:
        raise ValueError("k_values must not be empty")

    max_k = max(k_values)
    reciprocal_ranks: list[float] = []
    hits: dict[int, list[bool]] = {k: [] for k in k_values}

    for example in examples:
        results = port.search(example.question, filters, top_k=max_k)
        reciprocal_ranks.append(reciprocal_rank(results, example.expected_chunk_id))
        for k in k_values:
            hits[k].append(hit_at_k(results, example.expected_chunk_id, k))

    recall_at_k = {k: sum(values) / len(values) for k, values in hits.items()}
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    return ModeEvaluation(
        mode_name=mode_name,
        recall_at_k=recall_at_k,
        mrr=mrr,
        example_count=len(examples),
    )


def format_comparison_table(evaluations: Sequence[ModeEvaluation]) -> str:
    """In bảng so sánh dễ đọc trên terminal — không phải để parse."""
    if not evaluations:
        return "(no evaluations)"

    k_values = sorted(evaluations[0].recall_at_k)
    header = "Mode".ljust(14) + "".join(f"Recall@{k}".rjust(12) for k in k_values) + "MRR".rjust(10)
    lines = [header, "-" * len(header)]
    for evaluation in evaluations:
        row = evaluation.mode_name.ljust(14)
        row += "".join(f"{evaluation.recall_at_k[k]:.2f}".rjust(12) for k in k_values)
        row += f"{evaluation.mrr:.3f}".rjust(10)
        lines.append(row)
    return "\n".join(lines)


__all__ = [
    "GroundTruthExample",
    "ModeEvaluation",
    "evaluate_mode",
    "format_comparison_table",
    "hit_at_k",
    "reciprocal_rank",
]
