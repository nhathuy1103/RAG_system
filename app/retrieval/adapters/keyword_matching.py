"""Shared keyword extraction for the placeholder (non-LLM) adapters."""

from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "là",
        "và",
        "của",
        "có",
        "không",
        "cho",
        "trong",
        "một",
        "các",
        "những",
        "này",
        "đó",
        "với",
        "được",
        "gì",
        "sao",
        "hay",
        "hoặc",
        "cái",
        "còn",
        "thì",
        "vậy",
        "nên",
        "the",
        "a",
        "an",
        "is",
        "are",
        "of",
        "to",
        "and",
        "in",
        "on",
    }
)


def tokenize_list(text: str) -> list[str]:
    """Lowercase and tokenize into a LIST — keeps duplicates/order (for BM25)."""
    return [match.lower() for match in _WORD_PATTERN.findall(text) if len(match) > 1]


def tokenize_all(text: str) -> set[str]:
    """Lowercase and tokenize WITHOUT dropping stopwords (needed to detect references)."""
    return set(tokenize_list(text))


def extract_keywords(text: str) -> set[str]:
    """Lowercase, tokenize, and drop stopwords/single-character tokens."""
    return {word for word in tokenize_list(text) if word not in _STOPWORDS}


__all__ = ["extract_keywords", "tokenize_all", "tokenize_list"]
