"""Attach current production metadata to the approved frozen corpus identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_HEADING_PREFIX = re.compile(r"(?m)^#{1,6}\s+")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _key(row: dict[str, Any]) -> tuple[str, int]:
    return str(row["document_title"]).casefold(), int(row["chunk_index"])


def _normalized_text(value: object) -> str:
    return _HEADING_PREFIX.sub("", str(value or "")).strip()


def align_corpora(
    frozen_rows: list[dict[str, Any]],
    production_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    production_by_key = {_key(row): row for row in production_rows}
    if len(production_by_key) != len(production_rows):
        raise ValueError("Production corpus has duplicate document/chunk_index keys")

    aligned: list[dict[str, Any]] = []
    exact_text_matches = 0
    normalized_text_matches = 0
    for frozen in frozen_rows:
        key = _key(frozen)
        production = production_by_key.get(key)
        if production is None:
            raise ValueError(f"Missing production chunk for {key}")
        if str(frozen["document_id"]) != str(production["document_id"]):
            raise ValueError(f"Document identity mismatch for {key}")
        if frozen.get("text") == production.get("text"):
            exact_text_matches += 1
        elif _normalized_text(frozen.get("text")) == _normalized_text(production.get("text")):
            normalized_text_matches += 1
        else:
            raise ValueError(f"Content mismatch after heading normalization for {key}")

        row = dict(frozen)
        row["current_metadata"] = dict(production.get("current_metadata") or {})
        row["metadata_alignment"] = {
            "source": "current_production_pipeline",
            "key": "document_title+chunk_index",
            "content_check": (
                "exact" if frozen.get("text") == production.get("text") else "heading_normalized"
            ),
        }
        aligned.append(row)

    if len(aligned) != len(production_rows):
        raise ValueError(
            f"Corpus size mismatch: frozen={len(aligned)} production={len(production_rows)}"
        )
    return aligned, {
        "chunk_count": len(aligned),
        "exact_text_match_count": exact_text_matches,
        "heading_normalized_text_match_count": normalized_text_matches,
        "content_mismatch_count": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-corpus", type=Path, required=True)
    parser.add_argument("--production-corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    aligned, stats = align_corpora(
        _load_jsonl(args.frozen_corpus),
        _load_jsonl(args.production_corpus),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(args.output, aligned)
    manifest = {
        "schema_version": "1.0",
        "status": "aligned",
        "purpose": "isolate production metadata while preserving approved chunk identity/text",
        "frozen_corpus": str(args.frozen_corpus.resolve()),
        "frozen_corpus_sha256": _sha256(args.frozen_corpus),
        "production_corpus": str(args.production_corpus.resolve()),
        "production_corpus_sha256": _sha256(args.production_corpus),
        "output": str(args.output.resolve()),
        **stats,
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Aligned {stats['chunk_count']} chunks; exact={stats['exact_text_match_count']}; "
        f"heading-normalized={stats['heading_normalized_text_match_count']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
