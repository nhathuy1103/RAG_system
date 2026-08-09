from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    make_record_id,
    read_json,
    sha256_text,
    utc_now_iso,
    write_json,
)
from app.pipeline.documents.extraction.evaluation.scoring_normalization import normalized_text

ENCODING_CLASSES = {
    "VALID_UNICODE",
    "NFC_DIFFERENCE",
    "WHITESPACE_DIFFERENCE",
    "MULTILAYER_MOJIBAKE",
    "SINGLE_LAYER_MOJIBAKE",
    "LOSSY_QUESTION_MARK_ENCODING",
    "UNICODE_REPLACEMENT_CHARACTER",
    "MIXED_ENCODING",
    "DUPLICATE_SEMANTIC_FIELD",
    "NUMERIC_FORMAT_RISK",
    "NEGATIVE_SIGN_RISK",
    "PERIOD_HEADER_RISK",
    "NULL_HYPHEN_RISK",
    "UNRESOLVED",
}
BLOCKING_CLASSES = {
    "MULTILAYER_MOJIBAKE",
    "SINGLE_LAYER_MOJIBAKE",
    "LOSSY_QUESTION_MARK_ENCODING",
    "UNICODE_REPLACEMENT_CHARACTER",
    "MIXED_ENCODING",
    "DUPLICATE_SEMANTIC_FIELD",
    "UNRESOLVED",
}
REVIEW_CLASSES = {
    "NFC_DIFFERENCE",
    "WHITESPACE_DIFFERENCE",
    "NUMERIC_FORMAT_RISK",
    "NEGATIVE_SIGN_RISK",
    "PERIOD_HEADER_RISK",
    "NULL_HYPHEN_RISK",
}
MOJIBAKE_MARKERS = (
    "\u00c3\u0192",
    "\u00c3\u201a",
    "\u00c3\u201e",
    "\u00c3\u2020",
    "\u00c3",
    "\u00c2",
    "\u00c4",
    "\u00c6",
    "\u00e2\u20ac",
    "\u00e2\u201a\u00ac",
    "\u00e1\u00bb",
    "\u00e1\u00ba",
    "\u00ef\u00bf\u00bd",
)
QUESTION_LOSS_RE = re.compile(r"(?iu)(?<=\w)\?(?=\w)|\w+\?+\w*|\w*\?+\w+")
DATE_HEADER_RE = re.compile(r"\b\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\b|\b\d{4}\b")
NUMBER_RE = re.compile(r"(?<!\w)[(\-]?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\)?(?!\w)")
NEGATIVE_RE = re.compile(r"^\s*(?:\(|-|[\u2212\u2012\u2013\u2014])\s*\d")
NULL_HYPHEN_RE = re.compile(r"^\s*[-\u2010-\u2015]\s*$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
FINANCIAL_FIELD_HINTS = (
    "column",
    "row",
    "cell",
    "header",
    "expected_tables",
    "text",
    "notes",
)
VOWELS = set("aeiouy")


def audit_benchmark(benchmark_dir: Path) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    manifest = read_json(benchmark_dir / "manifest.json")
    raw_records = list(iter_expected_values(manifest))
    findings = build_findings(raw_records)
    summary = summarize_findings(findings)
    return {
        "benchmark_id": manifest.get("version") or benchmark_dir.name,
        "generated_at": utc_now_iso(),
        "source_manifest": str((benchmark_dir / "manifest.json").as_posix()),
        "total_values_scanned": len(raw_records),
        "summary": summary,
        "findings": findings,
    }


def iter_expected_values(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for case_index, case in enumerate(manifest.get("cases", [])):
        case_id = str(case.get("case_id") or f"case_{case_index}")
        for index, item in enumerate(case.get("expected_text", [])):
            yield {
                "case_id": case_id,
                "page_number": item.get("page_number"),
                "field_path": f"cases[{case_index}].expected_text[{index}].text",
                "value": str(item.get("text") or ""),
                "field_kind": "expected_text",
                "severity_hint": item.get("severity"),
            }
        for table_index, table in enumerate(case.get("expected_tables", [])):
            page_number = table.get("page_number")
            for column_index, column in enumerate(table.get("columns", [])):
                yield {
                    "case_id": case_id,
                    "page_number": page_number,
                    "field_path": (
                        f"cases[{case_index}].expected_tables[{table_index}]"
                        f".columns[{column_index}]"
                    ),
                    "value": str(column),
                    "field_kind": "table_column",
                    "severity_hint": table.get("severity"),
                }
            for row_index, row in enumerate(table.get("rows", [])):
                for key, value in row.items():
                    yield {
                        "case_id": case_id,
                        "page_number": page_number,
                        "field_path": (
                            f"cases[{case_index}].expected_tables[{table_index}]"
                            f".rows[{row_index}].{key}"
                        ),
                        "value": str(value),
                        "field_kind": "table_cell",
                        "row_key": str(key),
                        "severity_hint": table.get("severity"),
                    }
                    yield {
                        "case_id": case_id,
                        "page_number": page_number,
                        "field_path": (
                            f"cases[{case_index}].expected_tables[{table_index}]"
                            f".rows[{row_index}].<row_key:{key}>"
                        ),
                        "value": str(key),
                        "field_kind": "table_row_key",
                        "severity_hint": table.get("severity"),
                    }
        for issue_index, issue in enumerate(case.get("expected_issues", [])):
            for key, value in issue.items():
                if isinstance(value, str):
                    yield {
                        "case_id": case_id,
                        "page_number": issue.get("page_number"),
                        "field_path": (f"cases[{case_index}].expected_issues[{issue_index}].{key}"),
                        "value": value,
                        "field_kind": "expected_issue_metadata",
                        "severity_hint": issue.get("severity"),
                    }
        metadata = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
        for key in ("notes", "caption", "review_notes"):
            value = metadata.get(key)
            if isinstance(value, str):
                yield {
                    "case_id": case_id,
                    "page_number": None,
                    "field_path": f"cases[{case_index}].metadata.{key}",
                    "value": value,
                    "field_kind": "notes",
                    "severity_hint": None,
                }


def build_findings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for record in records:
        classes = classify_value(
            record["value"],
            field_path=record["field_path"],
            field_kind=record.get("field_kind", ""),
        )
        for encoding_class in classes:
            findings.append(_finding(record, encoding_class))
    findings.extend(_duplicate_semantic_key_findings(records))
    return sorted(
        findings,
        key=lambda item: (
            str(item.get("case_id")),
            int(item.get("page_number") or 0),
            str(item.get("field_path")),
            str(item.get("encoding_class")),
        ),
    )


def classify_value(value: str, *, field_path: str = "", field_kind: str = "") -> list[str]:
    classes: list[str] = []
    if CONTROL_RE.search(value):
        classes.append("UNRESOLVED")
    if "\ufffd" in value or "\u00ef\u00bf\u00bd" in value:
        classes.append("UNICODE_REPLACEMENT_CHARACTER")
    mojibake = looks_like_mojibake(value)
    lossy = looks_like_lossy_question_mark(value, field_path=field_path, field_kind=field_kind)
    if mojibake and lossy:
        classes.append("MIXED_ENCODING")
    if mojibake:
        repair = best_lossless_repair(value)
        classes.append(
            "MULTILAYER_MOJIBAKE" if repair.get("depth", 1) > 1 else "SINGLE_LAYER_MOJIBAKE"
        )
    if lossy:
        classes.append("LOSSY_QUESTION_MARK_ENCODING")
    if unicodedata.normalize("NFC", value) != value:
        classes.append("NFC_DIFFERENCE")
    if normalized_text(value) != value.strip():
        classes.append("WHITESPACE_DIFFERENCE")
    if NUMBER_RE.search(value):
        classes.append("NUMERIC_FORMAT_RISK")
    if NEGATIVE_RE.search(value):
        classes.append("NEGATIVE_SIGN_RISK")
    if (
        "column" in field_kind or "header" in field_path or ".columns[" in field_path
    ) and DATE_HEADER_RE.search(value):
        classes.append("PERIOD_HEADER_RISK")
    if NULL_HYPHEN_RE.match(value):
        classes.append("NULL_HYPHEN_RISK")
    if not classes:
        classes.append("VALID_UNICODE")
    return _dedupe(classes)


def looks_like_mojibake(value: str) -> bool:
    return bool(any(marker in value for marker in MOJIBAKE_MARKERS))


def looks_like_lossy_question_mark(
    value: str,
    *,
    field_path: str = "",
    field_kind: str = "",
) -> bool:
    if "?" not in value:
        return False
    stripped = value.strip()
    lowered_path = f"{field_path} {field_kind}".lower()
    if any(hint in lowered_path for hint in ("table_column", "table_row_key", "expected_tables")):
        return True
    if (
        stripped.endswith("?")
        and stripped.count("?") == 1
        and not QUESTION_LOSS_RE.search(stripped[:-1])
    ):
        return False
    if any(hint in lowered_path for hint in FINANCIAL_FIELD_HINTS) and "?" in stripped:
        return True
    if stripped.count("?") > 1:
        return True
    return bool(QUESTION_LOSS_RE.search(stripped))


def repair_candidates_for_value(value: str) -> list[dict[str, Any]]:
    if looks_like_lossy_question_mark(value):
        return [
            {
                "original_value": value,
                "candidate_value": None,
                "repair_operations": ["MANUAL_TRANSCRIPTION_REQUIRED"],
                "confidence": 0.0,
                "lossless": False,
                "human_approval_required": True,
                "reason": "lossy_question_mark_encoding_requires_source_image_transcription",
            }
        ]
    candidates: list[dict[str, Any]] = []
    nfc = unicodedata.normalize("NFC", value)
    if nfc != value:
        candidates.append(
            {
                "original_value": value,
                "candidate_value": nfc,
                "repair_operations": ["unicode_nfc"],
                "confidence": 1.0,
                "lossless": True,
                "human_approval_required": True,
                "reason": "unicode_nfc_candidate_only",
            }
        )
    if looks_like_mojibake(value):
        repaired = best_lossless_repair(value)
        candidate = repaired.get("candidate_value")
        if candidate and candidate != value:
            candidates.append(
                {
                    "original_value": value,
                    "candidate_value": candidate,
                    "repair_operations": repaired["repair_operations"],
                    "confidence": repaired["confidence"],
                    "lossless": repaired["lossless"],
                    "human_approval_required": True,
                    "reason": "reversible_mojibake_repair_candidate",
                }
            )
    return candidates


def best_lossless_repair(value: str, *, max_depth: int = 3) -> dict[str, Any]:
    best = {
        "original_value": value,
        "candidate_value": value,
        "repair_operations": [],
        "confidence": 0.0,
        "lossless": False,
        "depth": 0,
    }
    seen = {value}
    frontier = [(value, [])]
    for _depth in range(max_depth):
        next_frontier: list[tuple[str, list[str]]] = []
        for current, operations in frontier:
            for encoding in ("cp1252", "latin1"):
                operation = f"{encoding}_encode_utf8_decode"
                try:
                    candidate = current.encode(encoding).decode("utf-8")
                except UnicodeError:
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                new_operations = operations + [operation]
                lossless = _round_trips(value, candidate, new_operations)
                confidence = _repair_confidence(value, candidate, lossless)
                if lossless and confidence > best["confidence"]:
                    best = {
                        "original_value": value,
                        "candidate_value": candidate,
                        "repair_operations": new_operations,
                        "confidence": confidence,
                        "lossless": True,
                        "depth": len(new_operations),
                    }
                if len(new_operations) < max_depth:
                    next_frontier.append((candidate, new_operations))
        frontier = next_frontier
    return best


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_class = Counter(str(item["encoding_class"]) for item in findings)
    blocking = sum(1 for item in findings if item.get("severity") == "BLOCKING")
    by_page: dict[str, Counter[str]] = defaultdict(Counter)
    for item in findings:
        by_page[str(item.get("page_number") or "document")][str(item["encoding_class"])] += 1
    return {
        "by_class": dict(sorted(by_class.items())),
        "blocking_count": blocking,
        "review_count": sum(1 for item in findings if item.get("requires_human_review")),
        "by_page": {page: dict(counter) for page, counter in sorted(by_page.items())},
    }


def write_inventory(benchmark_dir: Path, output: Path) -> dict[str, Any]:
    inventory = audit_benchmark(benchmark_dir)
    write_json(output, inventory)
    return inventory


def _finding(record: dict[str, Any], encoding_class: str) -> dict[str, Any]:
    severity = _severity_for_class(encoding_class)
    raw_value = record["value"]
    return {
        "finding_id": make_record_id(
            "enc",
            record.get("case_id"),
            record.get("page_number"),
            record.get("field_path"),
            encoding_class,
            raw_value,
        ),
        "case_id": record.get("case_id"),
        "page_number": record.get("page_number"),
        "field_path": record.get("field_path"),
        "field_kind": record.get("field_kind"),
        "raw_value": raw_value,
        "raw_value_sha256": sha256_text(raw_value),
        "encoding_class": encoding_class,
        "severity": severity,
        "auto_repair_allowed": False,
        "requires_human_review": severity in {"BLOCKING", "REVIEW"},
        "reason": _reason_for_class(encoding_class),
    }


def _duplicate_semantic_key_findings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int | None, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("field_kind") != "table_row_key":
            continue
        key = (
            str(record.get("case_id")),
            record.get("page_number"),
            _row_scope(str(record.get("field_path"))),
        )
        grouped[key].append(record)
    findings: list[dict[str, Any]] = []
    for records_in_row in grouped.values():
        signatures: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records_in_row:
            signature = semantic_signature(str(record.get("value") or ""))
            if signature:
                signatures[signature].append(record)
        for signature_records in signatures.values():
            raw_values = {str(record.get("value") or "") for record in signature_records}
            if len(raw_values) <= 1:
                continue
            for record in signature_records:
                finding = _finding(record, "DUPLICATE_SEMANTIC_FIELD")
                finding["reason"] = (
                    "row has multiple keys with the same folded semantic signature: "
                    + ", ".join(sorted(raw_values))
                )
                findings.append(finding)
    return findings


def semantic_signature(value: str) -> str:
    repaired = best_lossless_repair(value).get("candidate_value") or value
    normalized = unicodedata.normalize("NFD", str(repaired).lower())
    no_marks = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    alnum = "".join(char for char in no_marks if char.isalnum() or char == "?")
    without_unknowns = alnum.replace("?", "")
    consonants = "".join(char for char in without_unknowns if char not in VOWELS)
    return consonants or without_unknowns


def _row_scope(field_path: str) -> str:
    marker = ".<row_key:"
    if marker in field_path:
        return field_path.split(marker, 1)[0]
    return field_path


def _severity_for_class(encoding_class: str) -> str:
    if encoding_class in BLOCKING_CLASSES:
        return "BLOCKING"
    if encoding_class in REVIEW_CLASSES:
        return "REVIEW"
    return "INFO"


def _reason_for_class(encoding_class: str) -> str:
    return {
        "VALID_UNICODE": "value is valid under the audit heuristics",
        "NFC_DIFFERENCE": "unicode NFC normalization changes the raw value",
        "WHITESPACE_DIFFERENCE": "safe whitespace normalization changes the raw value",
        "MULTILAYER_MOJIBAKE": "value contains multi-layer mojibake markers",
        "SINGLE_LAYER_MOJIBAKE": "value contains mojibake markers",
        "LOSSY_QUESTION_MARK_ENCODING": "question marks appear inside lexical tokens or financial fields",
        "UNICODE_REPLACEMENT_CHARACTER": "value contains a replacement character marker",
        "MIXED_ENCODING": "value combines mojibake and lossy question-mark encoding",
        "DUPLICATE_SEMANTIC_FIELD": "duplicate row key after conservative semantic folding",
        "NUMERIC_FORMAT_RISK": "numeric financial formatting requires exact human review",
        "NEGATIVE_SIGN_RISK": "negative sign or parentheses require exact human review",
        "PERIOD_HEADER_RISK": "period/date header requires exact human review",
        "NULL_HYPHEN_RISK": "hyphen/null value requires explicit source review",
        "UNRESOLVED": "value contains control or unresolved characters",
    }.get(encoding_class, "unclassified encoding finding")


def _repair_confidence(original: str, candidate: str, lossless: bool) -> float:
    confidence = 0.0
    if lossless:
        confidence += 0.35
    if looks_like_mojibake(original) and not looks_like_mojibake(candidate):
        confidence += 0.3
    if _has_vietnamese_plausibility(candidate):
        confidence += 0.2
    if _printable(candidate) and "\ufffd" not in candidate:
        confidence += 0.15
    return round(min(confidence, 1.0), 3)


def _has_vietnamese_plausibility(value: str) -> bool:
    return any("\u1ea0" <= char <= "\u1ef9" or char in "\u0102\u0103\u0110\u0111" for char in value)


def _printable(value: str) -> bool:
    return not CONTROL_RE.search(value) and all(
        char.isprintable() or char in "\r\n\t" for char in value
    )


def _round_trips(original: str, candidate: str, operations: list[str]) -> bool:
    current = candidate
    for operation in reversed(operations):
        encoding = operation.split("_", 1)[0]
        try:
            current = current.encode("utf-8").decode(encoding)
        except UnicodeError:
            return False
    return current == original


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit benchmark ground truth encoding.")
    parser.add_argument("benchmark_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-promotable",
        action="store_true",
        help="exit non-zero when blocking findings remain",
    )
    args = parser.parse_args()

    inventory = write_inventory(
        args.benchmark_dir,
        args.output or args.benchmark_dir / "encoding_inventory.json",
    )
    print(json.dumps(inventory["summary"], ensure_ascii=False, indent=2))
    has_blocking = inventory["summary"]["blocking_count"] > 0
    return 1 if args.require_promotable and has_blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
