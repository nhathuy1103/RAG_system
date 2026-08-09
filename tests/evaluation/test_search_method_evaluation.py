"""Đánh giá phương pháp search — kiểm tra harness đúng, rồi chạy thử so sánh
BM25-only / Dense-only / Hybrid trên bộ dữ liệu GIẢ (toy_search_dataset.py).

Kết quả in ra ở đây KHÔNG phải kết luận thật của dự án — corpus chỉ có 12
chunk hư cấu. Khi có tài liệu/câu hỏi thật, thay ``toy_search_dataset`` bằng
dataset thật, giữ nguyên cấu trúc test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter
from app.retrieval.adapters.dense_search import HashingDenseRetrievalAdapter
from app.retrieval.adapters.hybrid_search import HybridRetrievalAdapter
from app.retrieval.domain.models import RetrievalCandidate, RetrievalFilters
from tests.evaluation.search_method_evaluation import (
    GroundTruthExample,
    evaluate_mode,
    format_comparison_table,
    hit_at_k,
    reciprocal_rank,
)
from tests.evaluation.toy_search_dataset import CORPUS, FILTERS, GROUND_TRUTH


def _candidate(chunk_id: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=SimpleNamespace(id=chunk_id),  # type: ignore[arg-type]
        score=1.0,
        rank=1,
    )


class TestHitAtKAndReciprocalRank:
    """Kiểm tra 2 hàm tính điểm cốt lõi bằng ví dụ tự tính tay được."""

    def test_hit_at_k_true_when_within_k(self) -> None:
        results = (_candidate("a"), _candidate("b"), _candidate("c"))

        assert hit_at_k(results, "b", k=2) is True
        assert hit_at_k(results, "c", k=2) is False

    def test_reciprocal_rank_matches_position(self) -> None:
        results = (_candidate("a"), _candidate("b"), _candidate("c"))

        assert reciprocal_rank(results, "a") == 1.0
        assert reciprocal_rank(results, "b") == 0.5
        assert reciprocal_rank(results, "missing") == 0.0


class FakePort:
    """Trả về kết quả đã lập trình sẵn — dùng để kiểm tra evaluate_mode tính
    đúng công thức trên dữ liệu biết trước đáp số, không phụ thuộc BM25/Dense
    thật."""

    def __init__(self, results_by_question: dict[str, tuple[RetrievalCandidate, ...]]) -> None:
        self._results = results_by_question

    def search(
        self, query: str, filters: RetrievalFilters, *, top_k: int
    ) -> tuple[RetrievalCandidate, ...]:
        return self._results[query][:top_k]


def test_evaluate_mode_computes_recall_and_mrr_correctly() -> None:
    examples = (
        GroundTruthExample(question="q1", expected_chunk_id="a"),  # rank 1 -> hit@1, RR=1.0
        GroundTruthExample(question="q2", expected_chunk_id="b"),  # rank 2 -> miss@1, hit@3, RR=0.5
        GroundTruthExample(question="q3", expected_chunk_id="z"),  # not found -> RR=0.0
    )
    port = FakePort(
        {
            "q1": (_candidate("a"), _candidate("x")),
            "q2": (_candidate("x"), _candidate("b"), _candidate("y")),
            "q3": (_candidate("x"), _candidate("y")),
        }
    )

    result = evaluate_mode(
        mode_name="fake",
        port=port,
        examples=examples,
        filters=FILTERS,
        k_values=(1, 3),
    )

    assert result.recall_at_k[1] == 1 / 3  # chỉ q1 hit trong top-1
    assert result.recall_at_k[3] == 2 / 3  # q1 và q2 hit trong top-3, q3 thì không
    assert result.mrr == (1.0 + 0.5 + 0.0) / 3
    assert result.example_count == 3


def test_evaluate_mode_rejects_empty_inputs() -> None:
    port = FakePort({})
    with pytest.raises(ValueError):
        evaluate_mode(mode_name="fake", port=port, examples=(), filters=FILTERS, k_values=(1,))
    with pytest.raises(ValueError):
        evaluate_mode(
            mode_name="fake",
            port=port,
            examples=(GroundTruthExample(question="q", expected_chunk_id="a"),),
            filters=FILTERS,
            k_values=(),
        )


def _build_hybrid() -> HybridRetrievalAdapter:
    bm25 = InMemoryBM25RetrievalAdapter()
    dense = HashingDenseRetrievalAdapter()
    hybrid = HybridRetrievalAdapter(sparse=bm25, dense=dense)
    for chunk in CORPUS:
        hybrid.index(chunk)
    return hybrid


def test_compare_bm25_dense_hybrid_on_toy_dataset(capsys: pytest.CaptureFixture[str]) -> None:
    """Không assert 'mode nào thắng' — corpus giả quá nhỏ để kết luận gì có ý
    nghĩa khoa học. Chỉ kiểm tra harness chạy hết cả 3 mode không lỗi, giá
    trị nằm trong khoảng hợp lệ, và in bảng so sánh ra terminal để xem bằng
    mắt (chạy với ``pytest -s`` để thấy output)."""
    k_values = (1, 3, 5)
    hybrid = _build_hybrid()

    evaluations = [
        evaluate_mode(
            mode_name="bm25-only",
            port=hybrid.sparse,
            examples=GROUND_TRUTH,
            filters=FILTERS,
            k_values=k_values,
        ),
        evaluate_mode(
            mode_name="dense-only",
            port=hybrid.dense,
            examples=GROUND_TRUTH,
            filters=FILTERS,
            k_values=k_values,
        ),
        evaluate_mode(
            mode_name="hybrid",
            port=hybrid,
            examples=GROUND_TRUTH,
            filters=FILTERS,
            k_values=k_values,
        ),
    ]

    for evaluation in evaluations:
        assert 0.0 <= evaluation.mrr <= 1.0
        for k in k_values:
            assert 0.0 <= evaluation.recall_at_k[k] <= 1.0
        # Recall không được giảm khi k tăng (tập hợp lớn hơn không thể chứa ít hit hơn).
        assert evaluation.recall_at_k[1] <= evaluation.recall_at_k[3] <= evaluation.recall_at_k[5]

    with capsys.disabled():
        print("\n" + format_comparison_table(evaluations))


def test_exact_keyword_questions_are_found_at_rank_one_by_bm25() -> None:
    """Assertion có ý nghĩa duy nhất ta CÓ THỂ khẳng định chắc với corpus giả
    này: câu hỏi khớp từ khoá chính xác thì BM25 phải xếp đáp án đúng hạng 1,
    dù có chunk gây nhiễu cùng chủ đề (đây là thế mạnh cốt lõi của BM25)."""
    bm25 = InMemoryBM25RetrievalAdapter()
    for chunk in CORPUS:
        bm25.index(chunk)

    exact_keyword_examples = [
        example for example in GROUND_TRUTH if example.category == "exact_keyword"
    ]
    assert exact_keyword_examples, "toy dataset phải có ít nhất 1 câu exact_keyword"

    for example in exact_keyword_examples:
        results = bm25.search(example.question, FILTERS, top_k=1)
        assert results, f"BM25 không tìm thấy gì cho: {example.question!r}"
        assert results[0].chunk.id == example.expected_chunk_id
