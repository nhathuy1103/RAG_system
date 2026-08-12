"""Bounded deterministic conversation resolution for shared query semantics."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from app.retrieval.application.query_context import QueryContext, QueryIntent, parse_query_context

CONVERSATION_QUERY_POLICY_VERSION = "p6-conversation-query-v1"

_FOLLOW_UP = re.compile(
    r"\b(what about|how about|and for|then|that one|those|con|the|thi sao|sao nua|"
    r"nhu vay|truong hop do)\b",
    re.IGNORECASE,
)


def resolve_conversation_query(
    question: str,
    history_queries: Sequence[str],
    *,
    owner_id: str,
    notebook_id: str | None,
    history_limit: int = 6,
) -> QueryContext:
    """Resolve missing follow-up dimensions from recent compatible user turns.

    History is used as structured context only. It is never concatenated into
    an OR query, which prevents stale entities and years from dominating sparse
    retrieval.
    """

    if history_limit <= 0:
        raise ValueError("history_limit must be positive")
    current = parse_query_context(question, owner_id=owner_id, notebook_id=notebook_id)
    bounded = tuple(value.strip() for value in history_queries if value.strip())[-history_limit:]
    if not bounded:
        return current

    recent = tuple(
        parse_query_context(value, owner_id=owner_id, notebook_id=notebook_id)
        for value in reversed(bounded)
    )
    short_follow_up = len(current.normalized_query.split()) <= 8 and bool(
        _FOLLOW_UP.search(current.normalized_query)
    )
    is_follow_up = short_follow_up or not current.topic_terms
    if not is_follow_up:
        return current

    inherited: list[str] = []
    topics = current.topic_terms
    entities = current.entity_terms
    predicates = current.predicate_terms
    qualifiers = current.qualifier_terms

    if not topics:
        source = next((item for item in recent if item.topic_terms), None)
        if source is not None:
            topics = source.topic_terms
            entities = source.entity_terms
            inherited.append("topic")
    if not predicates:
        source = next((item for item in recent if item.predicate_terms), None)
        if source is not None:
            predicates = source.predicate_terms
            inherited.append("predicate")
    if not qualifiers:
        source = next((item for item in recent if item.qualifier_terms), None)
        if source is not None and not current.topic_terms:
            qualifiers = source.qualifier_terms
            inherited.append("qualifier")

    explicit_temporal = bool(
        current.reference_years
        or current.quarter
        or current.reference_date
        or current.current_requested
    )
    years = current.reference_years
    quarter = current.quarter
    reference_date = current.reference_date
    period_range = current.period_range
    current_requested = current.current_requested
    historical_requested = current.historical_requested
    intent = current.intent
    comparison = current.comparison_requested
    if not explicit_temporal and not current.topic_terms:
        source = next(
            (
                item
                for item in recent
                if item.reference_years
                or item.quarter
                or item.reference_date
                or item.current_requested
            ),
            None,
        )
        if source is not None:
            years = source.reference_years
            quarter = source.quarter
            reference_date = source.reference_date
            period_range = source.period_range
            current_requested = source.current_requested
            historical_requested = source.historical_requested
            comparison = source.comparison_requested
            intent = source.intent
            inherited.append("temporal")

    # An explicit single year always overrides a previous current/comparison
    # constraint and becomes a historical fact request.
    if current.reference_years and len(current.reference_years) == 1:
        years = current.reference_years
        period_range = None
        current_requested = False
        historical_requested = True
        comparison = False
        intent = QueryIntent.HISTORICAL_FACT
    elif current.current_requested:
        years = ()
        quarter = None
        reference_date = None
        period_range = None
        historical_requested = False
        comparison = False
        intent = QueryIntent.CURRENT_FACT

    resolved = _compose_resolved_query(
        current,
        topics=topics,
        predicates=predicates,
        qualifiers=qualifiers,
        years=years,
        current_requested=current_requested,
        inherited=bool(inherited),
    )
    return replace(
        current,
        normalized_query=current.normalized_query,
        resolved_query=resolved,
        intent=intent,
        reference_years=years,
        quarter=quarter,
        reference_date=reference_date,
        period_range=period_range,
        entity_terms=entities,
        topic_terms=topics,
        predicate_terms=predicates,
        qualifier_terms=qualifiers,
        comparison_requested=comparison,
        current_requested=current_requested,
        historical_requested=historical_requested,
        inherited_dimensions=tuple(dict.fromkeys(inherited)),
        policy_version=CONVERSATION_QUERY_POLICY_VERSION,
    )


def _compose_resolved_query(
    current: QueryContext,
    *,
    topics: tuple[str, ...],
    predicates: tuple[str, ...],
    qualifiers: tuple[str, ...],
    years: tuple[int, ...],
    current_requested: bool,
    inherited: bool,
) -> str:
    if not inherited:
        return current.raw_query
    parts = [*topics, *predicates, *qualifiers]
    if years:
        parts.extend(str(year) for year in years)
    elif current_requested:
        parts.append("current latest")
    # Keep meaningful current-turn terms (for example a newly supplied
    # protocol) but never append previous raw questions.
    parts.extend(current.topic_terms)
    return " ".join(dict.fromkeys(part for part in parts if part)).strip() or current.raw_query


__all__ = ["CONVERSATION_QUERY_POLICY_VERSION", "resolve_conversation_query"]
