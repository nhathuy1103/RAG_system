#!/usr/bin/env python3
"""Generate a deliberately simple surface-similarity baseline (no gold metadata)."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip().casefold()


def numbers(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+(?:[.,]\d+)?", text))


def predict(pair: dict[str, Any]) -> str:
    # This baseline intentionally ignores parent context to expose template leakage risk.
    left = normalize(pair["side_a"]["text"])
    right = normalize(pair["side_b"]["text"])
    if left == right:
        return "EXACT_DUPLICATE"
    similarity = SequenceMatcher(None, left, right).ratio()
    if similarity >= 0.92:
        if numbers(left) != numbers(right):
            return "CONFLICT"
        return "NEAR_DUPLICATE"
    if similarity >= 0.72:
        return "NEAR_DUPLICATE"
    return "DISTINCT"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=root / "data" / "benchmark_test.jsonl")
    parser.add_argument("--output", type=Path, default=root / "reports" / "naive_test_predictions.jsonl")
    args = parser.parse_args()
    pairs = load_jsonl(args.gold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for pair in pairs:
            handle.write(
                json.dumps(
                    {"pair_id": pair["pair_id"], "predicted_relation": predict(pair)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
