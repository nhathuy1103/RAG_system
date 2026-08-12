from __future__ import annotations

from app.retrieval.application.conversation_query import resolve_conversation_query
from app.retrieval.application.query_context import QueryIntent


def _resolve(question: str, history: list[str], *, limit: int = 6):
    return resolve_conversation_query(
        question,
        history,
        owner_id="actor",
        notebook_id=None,
        history_limit=limit,
    )


def test_direct_query_does_not_invent_history() -> None:
    result = _resolve("Giá Grand Park năm 2025?", [])

    assert result.raw_query == "Giá Grand Park năm 2025?"
    assert result.retrieval_query == result.raw_query
    assert result.reference_years == (2025,)
    assert result.inherited_dimensions == ()


def test_year_follow_up_inherits_topic_and_predicate_but_overrides_period() -> None:
    result = _resolve(
        "2025 thì sao?",
        ["So sánh giá căn hộ Vinhomes qua các năm"],
    )

    assert result.intent is QueryIntent.HISTORICAL_FACT
    assert result.reference_years == (2025,)
    assert "Vinhomes" in result.retrieval_query
    assert "price" in result.retrieval_query
    assert result.comparison_requested is False
    assert result.inherited_dimensions == ("topic", "predicate")


def test_current_follow_up_replaces_historical_year() -> None:
    result = _resolve("Hiện tại thì sao?", ["Giá Grand Park năm 2025?"])

    assert result.intent is QueryIntent.CURRENT_FACT
    assert result.current_requested is True
    assert result.reference_years == ()
    assert "Grand" in result.retrieval_query


def test_entity_override_never_carries_old_entity() -> None:
    result = _resolve("VinFast thì sao?", ["Giá Vinhomes năm 2025?"])

    assert "VinFast" in result.retrieval_query
    assert "Vinhomes" not in result.retrieval_query
    assert result.predicate_terms == ("price",)


def test_predicate_is_inherited_for_short_follow_up() -> None:
    result = _resolve("Grand Park thì sao?", ["Giá Vinhomes năm 2025?"])

    assert result.topic_terms == ("Grand", "Park")
    assert result.predicate_terms == ("price",)


def test_qualifier_override_keeps_subject_and_predicate() -> None:
    result = _resolve("EPA thì sao?", ["VF8 Eco WLTP đi được bao xa?"])

    assert result.topic_terms == ("VF8", "Eco")
    assert result.predicate_terms == ("driving_range",)
    assert result.qualifier_terms == ("epa",)
    assert "wltp" not in result.retrieval_query.casefold()


def test_history_is_bounded_to_recent_compatible_turns() -> None:
    result = _resolve(
        "2026 thì sao?",
        [
            "Doanh thu công ty Alpha năm 2020?",
            "Phí dịch vụ dự án Beta năm 2024?",
            "Giá Grand Park năm 2025?",
        ],
        limit=1,
    )

    assert "Grand" in result.retrieval_query
    assert "Alpha" not in result.retrieval_query
    assert "Beta" not in result.retrieval_query


def test_ambiguous_first_turn_remains_unresolved_instead_of_fabricated() -> None:
    result = _resolve("2025 thì sao?", [])

    assert result.retrieval_query == "2025 thì sao?"
    assert result.topic_terms == ()
    assert result.inherited_dimensions == ()


def test_new_topic_resets_unrelated_predicate_without_follow_up_marker() -> None:
    result = _resolve("Chính sách nghỉ phép?", ["Giá Vinhomes năm 2025?"])

    assert result.retrieval_query == "Chính sách nghỉ phép?"
    assert result.predicate_terms == ()
    assert result.inherited_dimensions == ()


def test_multi_turn_comparison_then_year_followups_never_accumulate_or_queries() -> None:
    first = "So sánh giá căn hộ Vinhomes qua các năm"
    second = "2025 thì sao?"
    result = _resolve("2026 thì sao?", [first, second])

    assert result.reference_years == (2026,)
    assert "2025" not in result.retrieval_query
    assert " OR " not in result.retrieval_query
