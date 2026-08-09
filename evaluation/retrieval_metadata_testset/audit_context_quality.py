"""Audit raw and effective contextual summaries before retrieval evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
_NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*%?")
_MID_SENTENCE_PATTERN = re.compile(r"[.!?…]+(?=\s+\S)")
_FILE_PATTERN = re.compile(r"(?i)\b\S+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|jsonl?)\b")
_PAGE_PATTERN = re.compile(r"(?i)\b(?:page|trang)\s*(?:number\s*)?\d+\b")
_BOILERPLATE_PATTERN = re.compile(
    r"(?i)^(?:đoạn (?:này )?thuộc (?:tài liệu|phần|mục)|this chunk belongs to)\b"
)
_TERMINAL_PUNCTUATION = (".", "!", "?", "…")
_CONTEXT_FIELDS = frozenset(
    {"contextual_summary", "contextual_search_terms", "context_enrichment"}
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "các",
        "cho",
        "có",
        "của",
        "được",
        "in",
        "is",
        "là",
        "này",
        "of",
        "the",
        "thuộc",
        "to",
        "trong",
        "và",
        "về",
        "với",
    }
)


def _tokens(text: str) -> set[str]:
    return {
        token
        for raw in _TOKEN_PATTERN.findall(text.casefold())
        if len(token := raw.strip("_")) > 1 and token not in _STOPWORDS
    }


def _flatten_metadata(value: object, *, parent: str = "") -> Iterable[str]:
    if parent in _CONTEXT_FIELDS:
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _flatten_metadata(item, parent=str(key))
    elif isinstance(value, Iterable) and not isinstance(value, str | bytes):
        for item in value:
            yield from _flatten_metadata(item, parent=parent)
    elif value not in (None, ""):
        yield str(value)


def score_context(
    context: str,
    *,
    chunk_text: str,
    metadata: Mapping[str, object],
    max_words: int,
) -> dict[str, object]:
    clean = " ".join(context.split()).strip()
    metadata_evidence = " ".join(_flatten_metadata(metadata))
    evidence = f"{chunk_text}\n{metadata_evidence}"
    context_tokens = _tokens(clean)
    chunk_tokens = _tokens(chunk_text)
    metadata_tokens = _tokens(metadata_evidence)
    evidence_tokens = chunk_tokens | metadata_tokens

    unsupported_numbers = sorted(
        set(_NUMBER_PATTERN.findall(clean)) - set(_NUMBER_PATTERN.findall(evidence))
    )
    supported_ratio = (
        len(context_tokens & evidence_tokens) / len(context_tokens) if context_tokens else 0.0
    )
    chunk_overlap = (
        len(context_tokens & chunk_tokens) / len(context_tokens) if context_tokens else 0.0
    )
    discriminative_chunk_tokens = context_tokens & chunk_tokens
    added_supported_tokens = (context_tokens - chunk_tokens) & metadata_tokens

    word_count = len(clean.split())
    has_terminal_punctuation = clean.endswith(_TERMINAL_PUNCTUATION)
    is_one_sentence = not bool(_MID_SENTENCE_PATTERN.search(clean))
    has_filename = bool(_FILE_PATTERN.search(clean))
    has_page_locator = bool(_PAGE_PATTERN.search(clean))
    has_boilerplate = bool(_BOILERPLATE_PATTERN.search(clean))
    complete = bool(
        clean
        and has_terminal_punctuation
        and is_one_sentence
        and word_count <= max_words
        and not has_filename
        and not has_page_locator
        and not has_boilerplate
    )

    groundedness = 0 if unsupported_numbers else 2
    chunk_specific = 2 if len(discriminative_chunk_tokens) >= 3 else int(
        bool(discriminative_chunk_tokens)
    )
    added_value = 2 if len(added_supported_tokens) >= 3 else int(bool(added_supported_tokens))
    non_redundancy = 2 if chunk_overlap <= 0.5 else (1 if chunk_overlap <= 0.75 else 0)
    completeness = 2 if complete else 0
    total = groundedness + chunk_specific + added_value + non_redundancy + completeness

    if groundedness == 0 or completeness == 0:
        decision = "reject"
    elif total >= 9:
        decision = "keep"
    elif total >= 7:
        decision = "keep_and_monitor"
    elif total >= 5:
        decision = "regenerate"
    else:
        decision = "reject"

    return {
        "word_count": word_count,
        "supported_token_ratio": round(supported_ratio, 6),
        "chunk_overlap_ratio": round(chunk_overlap, 6),
        "unsupported_numbers": " | ".join(unsupported_numbers),
        "has_terminal_punctuation": has_terminal_punctuation,
        "is_one_sentence": is_one_sentence,
        "has_filename": has_filename,
        "has_page_locator": has_page_locator,
        "has_boilerplate": has_boilerplate,
        "groundedness_score": groundedness,
        "chunk_specific_score": chunk_specific,
        "added_value_score": added_value,
        "non_redundancy_score": non_redundancy,
        "completeness_score": completeness,
        "total_score": total,
        "decision": decision,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise SystemExit(f"{path}:{line_number}: expected one JSON object")
            rows.append(value)
    return rows


def audit(corpus: list[dict[str, Any]], *, max_words: int) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for chunk in corpus:
        current = chunk.get("current_metadata")
        gold = chunk.get("gold_metadata")
        current_metadata = current if isinstance(current, dict) else {}
        gold_metadata = gold if isinstance(gold, dict) else {}
        raw = str(current_metadata.get("contextual_summary") or "").strip()
        effective = str(gold_metadata.get("contextual_summary") or raw).strip()
        overridden = bool(raw and effective and raw != effective)
        enrichment = current_metadata.get("context_enrichment")
        enrichment_metadata = enrichment if isinstance(enrichment, Mapping) else {}
        enrichment_status = str(enrichment_metadata.get("status") or "")
        needs_context = enrichment_metadata.get("needs_context")
        quality_flags = enrichment_metadata.get("quality_flags")
        for source, context, metadata in (
            ("raw", raw, current_metadata),
            ("effective", effective, gold_metadata),
        ):
            scores = score_context(
                context,
                chunk_text=str(chunk.get("text") or ""),
                metadata=metadata,
                max_words=max_words,
            )
            if source == "raw" and not context and enrichment_status == "not_needed":
                scores["decision"] = "not_needed"
            output.append(
                {
                    "chunk_id": str(chunk.get("chunk_id") or ""),
                    "document_title": str(chunk.get("document_title") or ""),
                    "chunk_index": chunk.get("chunk_index"),
                    "section_title": str(metadata.get("section_title") or ""),
                    "context_source": source,
                    "enrichment_status": enrichment_status if source == "raw" else "gold",
                    "needs_context": needs_context if source == "raw" else "",
                    "quality_flags": (
                        " | ".join(str(flag) for flag in quality_flags)
                        if source == "raw" and isinstance(quality_flags, list)
                        else ""
                    ),
                    "summary_overridden_by_gold": overridden,
                    "contextual_summary": context,
                    **scores,
                }
            )
    return output


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for source in ("raw", "effective"):
        selected = [row for row in rows if row["context_source"] == source]
        words = [int(row["word_count"]) for row in selected]
        decisions = Counter(str(row["decision"]) for row in selected)
        output[source] = {
            "count": len(selected),
            "nonempty_count": sum(bool(row["contextual_summary"]) for row in selected),
            "not_needed_count": sum(row["decision"] == "not_needed" for row in selected),
            "median_words": statistics.median(words) if words else 0,
            "p95_words": sorted(words)[max(0, int(len(words) * 0.95) - 1)] if words else 0,
            "missing_terminal_punctuation": sum(
                bool(row["contextual_summary"])
                and not bool(row["has_terminal_punctuation"])
                for row in selected
            ),
            "filename_count": sum(bool(row["has_filename"]) for row in selected),
            "page_locator_count": sum(bool(row["has_page_locator"]) for row in selected),
            "boilerplate_count": sum(bool(row["has_boilerplate"]) for row in selected),
            "decisions": dict(sorted(decisions.items())),
        }
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--max-words", type=int, default=45)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.max_words <= 0:
        raise SystemExit("--max-words must be greater than zero")
    rows = audit(_load_jsonl(args.corpus), max_words=args.max_words)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary_path = args.summary_output or args.output.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(_summary(rows), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} audit rows to {args.output}")
    print(f"Wrote summary to {summary_path}")


if __name__ == "__main__":
    main()
