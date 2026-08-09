from __future__ import annotations

from app.retrieval.adapters.local_contextualizer import HeuristicContextualizer


def test_no_reference_marker_is_never_ambiguous() -> None:
    contextualizer = HeuristicContextualizer()

    result = contextualizer.contextualize("doanh thu quý 3 là bao nhiêu?", ())

    assert result.is_ambiguous is False
    assert result.resolved_question == "doanh thu quý 3 là bao nhiêu?"


def test_reference_marker_with_concrete_keywords_is_not_ambiguous() -> None:
    contextualizer = HeuristicContextualizer()

    result = contextualizer.contextualize("doanh thu quý 3 của phòng đó là bao nhiêu?", ())

    assert result.is_ambiguous is False


def test_reference_marker_without_history_is_ambiguous() -> None:
    contextualizer = HeuristicContextualizer()

    result = contextualizer.contextualize("còn đó thì sao?", ())

    assert result.is_ambiguous is True
    assert result.clarifying_question is not None


def test_reference_marker_with_history_attempts_a_merge() -> None:
    contextualizer = HeuristicContextualizer()

    result = contextualizer.contextualize(
        "còn cái đó thì sao?",
        ("Doanh thu quý 3 là 5 tỷ đồng.",),
    )

    assert result.is_ambiguous is False
    assert "Doanh thu quý 3" in result.resolved_question
