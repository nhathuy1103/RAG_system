from __future__ import annotations

from app.retrieval.adapters.local_adaptive import HeuristicAdaptiveClassifier


def test_greeting_does_not_need_retrieval() -> None:
    classifier = HeuristicAdaptiveClassifier()

    decision = classifier.classify("Chào bạn")

    assert decision.needs_retrieval is False
    assert decision.fixed_answer is not None


def test_system_help_question_does_not_need_retrieval() -> None:
    classifier = HeuristicAdaptiveClassifier()

    decision = classifier.classify("Hướng dẫn tôi cách dùng hệ thống này")

    assert decision.needs_retrieval is False
    assert decision.fixed_answer is not None


def test_document_question_needs_retrieval() -> None:
    classifier = HeuristicAdaptiveClassifier()

    decision = classifier.classify("Doanh thu quý 3 của công ty là bao nhiêu?")

    assert decision.needs_retrieval is True
    assert decision.fixed_answer is None


def test_vietnamese_chi_tiet_does_not_match_english_hi_greeting() -> None:
    classifier = HeuristicAdaptiveClassifier()

    decision = classifier.classify("Tôi biết chi tiết các dự án được không")

    assert decision.needs_retrieval is True
    assert decision.fixed_answer is None
