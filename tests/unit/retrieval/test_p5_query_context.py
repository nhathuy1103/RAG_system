from __future__ import annotations

import pytest

from app.retrieval.application.query_context import QueryIntent, parse_query_context


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("What is the price of VF8?", QueryIntent.DEFAULT_FACT),
        ("What is the latest price of VF8?", QueryIntent.CURRENT_FACT),
        ("What was the VF8 price in 2024?", QueryIntent.HISTORICAL_FACT),
        ("How did the price change from 2024 to 2026?", QueryIntent.TEMPORAL_COMPARISON),
        ("What changed between version 2 and version 3?", QueryIntent.VERSION_COMPARISON),
        ("Are there conflicting figures for VF8?", QueryIntent.CONFLICT_CHECK),
        ("Which source says 450 km and which says 480 km?", QueryIntent.SOURCE_COMPARISON),
    ],
)
def test_minimal_relation_intent_taxonomy(query: str, intent: QueryIntent) -> None:
    parsed = parse_query_context(query, owner_id="owner", notebook_id="notebook")

    assert parsed.intent is intent


def test_temporal_qualifier_and_output_constraints_are_deterministic() -> None:
    parsed = parse_query_context(
        "So sánh WLTP Q2/2024 đến 2026 dưới dạng bảng",
        owner_id="owner",
        notebook_id="notebook",
    )

    assert parsed.intent is QueryIntent.TEMPORAL_COMPARISON
    assert parsed.reference_years == (2024, 2026)
    assert parsed.period_range == (2024, 2026)
    assert parsed.quarter == (2024, 2)
    assert parsed.qualifier_terms == ("wltp",)
    assert parsed.requested_output_constraints == ("table",)


def test_invalid_date_is_not_fabricated() -> None:
    parsed = parse_query_context(
        "Giá ngày 31/02/2025 là bao nhiêu?",
        owner_id="owner",
        notebook_id="notebook",
    )

    assert parsed.intent is QueryIntent.HISTORICAL_FACT
    assert parsed.reference_date is None
    assert parsed.reference_years == (2025,)
