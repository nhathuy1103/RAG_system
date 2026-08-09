"""Score retrieval outputs against the metadata-focused test set.

Expected input JSONL, one row per query result:

    {
      "test_id": "cs_004_return_deadline",
      "mode": "v5_context_terms",
      "latency_ms": 123.4,
      "results": [
        {
          "rank": 1,
          "chunk_id": "...",
          "document_title": "demo_kb_chinh_sach_doi_tra_cskh - Copy.docx",
          "page_number": null,
          "section_title": "Chính sách áp dụng",
          "excerpt": "..."
        }
      ]
    }

Chat citations from this repo already contain document_title/page_number/excerpt,
so they can be used directly as items in the "results" array.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

TITLE_PATHS = (
    ("document_title",),
    ("title",),
    ("filename",),
    ("source_file",),
    ("document", "title"),
    ("document", "original_filename"),
    ("metadata", "title"),
    ("metadata", "document_title"),
    ("metadata", "retrieval_metadata", "title"),
    ("chunk", "metadata", "title"),
    ("chunk", "metadata", "document_title"),
    ("chunk", "metadata", "retrieval_metadata", "title"),
)

PAGE_PATHS = (
    ("page",),
    ("page_number",),
    ("metadata", "page"),
    ("metadata", "page_number"),
    ("chunk", "metadata", "page"),
    ("chunk", "metadata", "page_number"),
)

CHUNK_ID_PATHS = (
    ("chunk_id",),
    ("id",),
    ("chunk", "id"),
)

TEXT_KEYS = {
    "text",
    "content",
    "excerpt",
    "search_text",
    "embedding_text",
    "section_title",
    "page_or_section",
    "document_title",
    "title",
}

MOJIBAKE_MARKERS = ("Ã", "Ä", "áº", "á»", "Æ", "�")


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.casefold().split())


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def contains_term(haystack: str, term: str) -> bool:
    normalized_haystack = normalize(haystack)
    normalized_term = normalize(term)
    if normalized_term in normalized_haystack:
        return True
    return strip_accents(normalized_term) in strip_accents(normalized_haystack)


def get_path(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def candidate_title(candidate: dict[str, Any]) -> str:
    for path in TITLE_PATHS:
        value = get_path(candidate, path)
        if value:
            return str(value)
    return ""


def candidate_page(candidate: dict[str, Any]) -> int | None:
    for path in PAGE_PATHS:
        value = get_path(candidate, path)
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def candidate_chunk_id(candidate: dict[str, Any]) -> str:
    for path in CHUNK_ID_PATHS:
        value = get_path(candidate, path)
        if value:
            return str(value)
    return ""


def collect_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(collect_text(item))
        return parts
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if key in TEXT_KEYS:
                parts.append(str(key))
            if isinstance(item, (str, int, float, bool, dict, list)):
                parts.extend(collect_text(item))
        return parts
    return [str(value)]


def candidate_text(candidate: dict[str, Any]) -> str:
    return "\n".join(collect_text(candidate))


def has_mojibake(text: str) -> bool:
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        if path.name == "retrieval_results.jsonl":
            raise SystemExit(
                f"Missing results file: {path}\n"
                "You have generated the test questions, but not the retrieval outputs yet.\n"
                "For a smoke test, run:\n"
                "  python evaluation\\retrieval_metadata_testset\\score_retrieval_results.py "
                "--results evaluation\\retrieval_metadata_testset\\retrieval_results.example.jsonl "
                "--output-dir evaluation\\retrieval_metadata_testset\\results\\example\n"
                "To create real results, run the questions through your retrieval/chat API "
                "and save "
                "them as retrieval_results.jsonl."
            )
        raise SystemExit(f"Missing JSONL file: {path}")
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
    return rows


def is_doc_match(candidate: dict[str, Any], expected_title: str) -> bool:
    title = candidate_title(candidate)
    if title and normalize(title) == normalize(expected_title):
        return True
    return contains_term(candidate_text(candidate), expected_title)


def is_page_match(candidate: dict[str, Any], expected: dict[str, Any]) -> bool | None:
    expected_page = expected.get("page")
    if expected_page in (None, ""):
        return None
    page = candidate_page(candidate)
    if page is None:
        return False
    tolerance = int(expected.get("page_tolerance") or 0)
    return abs(page - int(expected_page)) <= tolerance


def is_hit(candidate: dict[str, Any], expected: dict[str, Any]) -> bool:
    relevant_chunk_ids = {
        str(value) for value in expected.get("relevant_chunk_ids", []) if str(value).strip()
    }
    if relevant_chunk_ids:
        return candidate_chunk_id(candidate) in relevant_chunk_ids
    if not is_doc_match(candidate, expected["document_title"]):
        return False
    text = candidate_text(candidate)
    return all(contains_term(text, term) for term in expected.get("must_include_terms", []))


def relevant_groups(expected: dict[str, Any]) -> list[set[str]]:
    groups = [
        {str(value) for value in group if str(value).strip()}
        for group in expected.get("relevant_chunk_groups", [])
        if isinstance(group, list)
    ]
    groups = [group for group in groups if group]
    if groups:
        return groups
    ids = {str(value) for value in expected.get("relevant_chunk_ids", []) if str(value).strip()}
    return [ids] if ids else []


def evidence_group_coverage(
    results: list[dict[str, Any]], expected: dict[str, Any], k: int
) -> float:
    groups = relevant_groups(expected)
    if not groups:
        return 0.0
    returned = {candidate_chunk_id(candidate) for candidate in results[:k]}
    return sum(bool(group & returned) for group in groups) / len(groups)


def all_evidence_groups_hit(
    results: list[dict[str, Any]], expected: dict[str, Any], k: int
) -> bool:
    groups = relevant_groups(expected)
    return bool(groups) and evidence_group_coverage(results, expected, k) == 1.0


def permission_leak(results: list[dict[str, Any]], expected: dict[str, Any], k: int) -> bool:
    protected = {
        str(value) for value in expected.get("protected_chunk_ids", []) if str(value).strip()
    }
    return bool(protected & {candidate_chunk_id(candidate) for candidate in results[:k]})


def protected_hit_count(
    results: list[dict[str, Any]], expected: dict[str, Any], k: int
) -> int:
    protected = {
        str(value) for value in expected.get("protected_chunk_ids", []) if str(value).strip()
    }
    return sum(candidate_chunk_id(candidate) in protected for candidate in results[:k])


def sensitive_term_leak(
    results: list[dict[str, Any]], expected: dict[str, Any], k: int
) -> bool:
    terms = [
        str(value)
        for value in expected.get("must_not_include_terms", [])
        if str(value).strip()
    ]
    if not terms:
        return False
    text = "\n".join(candidate_text(candidate) for candidate in results[:k])
    return any(contains_term(text, term) for term in terms)


def required_document_coverage(
    results: list[dict[str, Any]], expected: dict[str, Any], k: int
) -> float:
    required = {
        normalize(value)
        for value in expected.get("must_cite_document_titles", [])
        if str(value).strip()
    }
    if not required:
        return 1.0
    returned = {normalize(candidate_title(candidate)) for candidate in results[:k]}
    return len(required & returned) / len(required)


def forbidden_document_citation(
    results: list[dict[str, Any]], expected: dict[str, Any], k: int
) -> bool:
    forbidden = {
        normalize(value)
        for value in expected.get("must_not_cite_document_titles", [])
        if str(value).strip()
    }
    returned = {normalize(candidate_title(candidate)) for candidate in results[:k]}
    return bool(forbidden & returned)


def table_structured_hit(
    results: list[dict[str, Any]], expected: dict[str, Any], k: int
) -> bool:
    expected_cell = str(expected.get("expected_cell_value") or "").strip()
    expected_table_id = str(expected.get("table_id") or "").strip()
    relevant_ids = {
        str(value) for value in expected.get("relevant_chunk_ids", []) if str(value).strip()
    }
    if not expected_cell or not expected_table_id:
        return False
    for candidate in results[:k]:
        if relevant_ids and candidate_chunk_id(candidate) not in relevant_ids:
            continue
        if str(candidate.get("table_id") or "") != expected_table_id:
            continue
        if contains_term(candidate_text(candidate), expected_cell):
            return True
    return False


def reciprocal_rank(results: list[dict[str, Any]], expected: dict[str, Any], max_k: int) -> float:
    for index, candidate in enumerate(results[:max_k], start=1):
        if is_hit(candidate, expected):
            return 1.0 / index
    return 0.0


def first_hit_rank(
    results: list[dict[str, Any]], expected: dict[str, Any], max_k: int
) -> int | None:
    for index, candidate in enumerate(results[:max_k], start=1):
        if is_hit(candidate, expected):
            return index
    return None


def term_hit_rate(results: list[dict[str, Any]], expected: dict[str, Any], k: int) -> float:
    terms = expected.get("must_include_terms", []) + expected.get("should_include_terms", [])
    if not terms:
        return 1.0
    text = "\n".join(candidate_text(candidate) for candidate in results[:k])
    return sum(contains_term(text, term) for term in terms) / len(terms)


def top1_forbidden(results: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
    if not results:
        return False
    forbidden = expected.get("forbidden_document_titles", [])
    top_text = candidate_text(results[0])
    top_title = candidate_title(results[0])
    forbidden_id = candidate_chunk_id(results[0]) in {
        str(value) for value in expected.get("forbidden_chunk_ids", []) if str(value).strip()
    }
    return forbidden_id or any(
        normalize(top_title) == normalize(title) or contains_term(top_text, title)
        for title in forbidden
    )


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    index = round((len(sorted_values) - 1) * pct)
    return sorted_values[index]


def score(
    testset: list[dict[str, Any]], result_rows: list[dict[str, Any]], k_values: list[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tests_by_id = {row["id"]: row for row in testset}
    max_k = max(k_values)
    details: list[dict[str, Any]] = []

    for row in result_rows:
        test_id = row.get("test_id") or row.get("id") or row.get("query_id")
        if test_id not in tests_by_id:
            print(f"warning: skipping unknown test_id={test_id!r}", file=sys.stderr)
            continue
        test = tests_by_id[test_id]
        expected = {
            **test["expected"],
            "relevant_chunk_ids": test.get("relevant_chunk_ids", []),
            "relevant_chunk_groups": test.get("relevant_chunk_groups", []),
            "protected_chunk_ids": test.get("protected_chunk_ids", []),
            "forbidden_chunk_ids": test.get("forbidden_chunk_ids", []),
        }
        target_type = str(test.get("target_type") or expected.get("target_type") or "single")
        permission_allowed = target_type == "permission_allowed"
        permission_denied = target_type in {"permission", "permission_denied"}
        answerable = bool(
            test.get(
                "answerable",
                target_type not in {"null", "permission", "permission_denied"},
            )
        )
        results = row.get("results") or row.get("citations") or []
        if not isinstance(results, list):
            print(f"warning: test_id={test_id!r} has non-list results", file=sys.stderr)
            results = []
        first_rank = first_hit_rank(results, expected, max_k)
        first_hit = results[first_rank - 1] if first_rank else None
        page_hit = is_page_match(first_hit, expected) if first_hit else None
        top1_text = candidate_text(results[0]) if results else ""
        slices = test.get("benchmark_slices") or [
            test.get("primary_slice") or test.get("query_type") or test["category"]
        ]
        required_fields = test.get("required_metadata_fields") or test.get("metadata_focus") or []
        preflight_pass = bool(row.get("filter_preflight_pass", True))
        document_coverage = required_document_coverage(results, expected, max_k)
        denied_sensitive_leak = sensitive_term_leak(results, expected, max_k)
        denied_forbidden_citation = forbidden_document_citation(results, expected, max_k)
        detail = {
            "mode": row.get("mode") or "default",
            "test_id": test_id,
            "query_id": test_id,
            "category": test["category"],
            "query_type": test.get("query_type") or test["category"],
            "difficulty": test["difficulty"],
            "scenario_id": test.get("scenario_id", ""),
            "evidence_fact_ids": " | ".join(
                str(value) for value in test.get("evidence_fact_ids", [])
            ),
            "permission_pair_id": test.get("permission_pair_id", ""),
            "query_style": test.get("query_style", ""),
            "split": test.get("split", ""),
            "primary_slice": test.get("primary_slice", test.get("category", "")),
            "benchmark_slices": " | ".join(str(value) for value in slices),
            "required_metadata_fields": " | ".join(str(value) for value in required_fields),
            "target_type": target_type,
            "answerable": int(answerable),
            "is_table_structured": int(bool(expected.get("expected_cell_value"))),
            "expected_response_class": expected.get("response_class", ""),
            "query": test["query"],
            "expected_document_title": expected.get("document_title", ""),
            "top1_document_title": candidate_title(results[0]) if results else "",
            "result_count": len(results),
            "empty_result": int(not results),
            "filter_preflight_pass": int(preflight_pass),
            "filter_preflight_status": row.get("filter_preflight_status", "passed"),
            "skipped_metadata_filter_fields": " | ".join(
                str(value) for value in row.get("skipped_metadata_filter_fields", [])
            ),
            "first_hit_rank": first_rank or "",
            "mrr_at_max_k": reciprocal_rank(results, expected, max_k),
            "evidence_group_count": len(relevant_groups(expected)),
            "evidence_group_coverage_at_max_k": evidence_group_coverage(results, expected, max_k),
            "all_evidence_groups_at_max_k": int(all_evidence_groups_hit(results, expected, max_k)),
            "null_rejection_at_max_k": int(
                target_type == "null" and preflight_pass and not results[:max_k]
            ),
            "permission_leak_at_max_k": int(
                permission_denied and permission_leak(results, expected, max_k)
            ),
            "permission_safe_at_max_k": int(
                permission_denied
                and not permission_leak(results, expected, max_k)
                and not denied_sensitive_leak
                and not denied_forbidden_citation
            ),
            "protected_hit_count_at_max_k": protected_hit_count(results, expected, max_k),
            "sensitive_term_leak_at_max_k": int(permission_denied and denied_sensitive_leak),
            "forbidden_document_citation_at_max_k": int(
                permission_denied and denied_forbidden_citation
            ),
            "permission_allowed_hit_at_max_k": int(
                permission_allowed and first_rank is not None and first_rank <= max_k
            ),
            "required_document_coverage_at_max_k": document_coverage,
            "all_required_documents_at_max_k": int(document_coverage == 1.0),
            "table_structured_hit_at_max_k": int(
                table_structured_hit(results, expected, max_k)
            ),
            "page_hit": "" if page_hit is None else int(bool(page_hit)),
            "term_hit_rate_at_max_k": term_hit_rate(results, expected, max_k),
            "top1_forbidden": int(top1_forbidden(results, expected)),
            "top1_mojibake": int(has_mojibake(top1_text)),
            "latency_ms": row.get("latency_ms", ""),
        }
        for k in k_values:
            detail[f"hit_at_{k}"] = int(first_rank is not None and first_rank <= k)
            detail[f"term_hit_rate_at_{k}"] = term_hit_rate(results, expected, k)
            group_coverage = evidence_group_coverage(results, expected, k)
            all_groups = all_evidence_groups_hit(results, expected, k)
            document_coverage = required_document_coverage(results, expected, k)
            all_documents = document_coverage == 1.0
            null_rejection = target_type == "null" and preflight_pass and not results[:k]
            leak = permission_denied and permission_leak(results, expected, k)
            sensitive_leak = permission_denied and sensitive_term_leak(results, expected, k)
            forbidden_citation = permission_denied and forbidden_document_citation(
                results, expected, k
            )
            denied_safe = not leak and not sensitive_leak and not forbidden_citation
            allowed_hit = permission_allowed and first_rank is not None and first_rank <= k
            structured_hit = table_structured_hit(results, expected, k)
            if target_type == "multi_hop":
                success = all_groups and all_documents
            elif target_type == "null":
                success = null_rejection
            elif permission_denied:
                success = denied_safe
            elif permission_allowed:
                success = allowed_hit and all_documents
            elif expected.get("expected_cell_value"):
                success = structured_hit
            else:
                success = first_rank is not None and first_rank <= k and all_documents
            detail[f"evidence_group_coverage_at_{k}"] = group_coverage
            detail[f"all_evidence_groups_at_{k}"] = int(all_groups)
            detail[f"null_rejection_at_{k}"] = int(null_rejection)
            detail[f"permission_leak_at_{k}"] = int(leak)
            detail[f"protected_hit_count_at_{k}"] = protected_hit_count(results, expected, k)
            detail[f"sensitive_term_leak_at_{k}"] = int(sensitive_leak)
            detail[f"forbidden_document_citation_at_{k}"] = int(forbidden_citation)
            detail[f"permission_safe_at_{k}"] = int(permission_denied and denied_safe)
            detail[f"permission_allowed_hit_at_{k}"] = int(allowed_hit)
            detail[f"required_document_coverage_at_{k}"] = document_coverage
            detail[f"all_required_documents_at_{k}"] = int(all_documents)
            detail[f"table_structured_hit_at_{k}"] = int(structured_hit)
            detail[f"success_at_{k}"] = int(success)
        details.append(detail)

    summaries: list[dict[str, Any]] = []
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for detail in details:
        by_mode[detail["mode"]].append(detail)

    for mode, rows in sorted(by_mode.items()):
        answerable_rows = [row for row in rows if int(row["answerable"]) == 1]
        multi_hop_rows = [row for row in rows if row["target_type"] == "multi_hop"]
        null_rows = [row for row in rows if row["target_type"] == "null"]
        permission_denied_rows = [
            row for row in rows if row["target_type"] in {"permission", "permission_denied"}
        ]
        permission_allowed_rows = [
            row for row in rows if row["target_type"] == "permission_allowed"
        ]
        permission_rows = [*permission_allowed_rows, *permission_denied_rows]
        table_rows = [row for row in rows if int(row["is_table_structured"]) == 1]
        latencies = [
            float(row["latency_ms"]) for row in rows if row["latency_ms"] not in ("", None)
        ]
        summary = {
            "mode": mode,
            "evaluated_count": len(rows),
            "answerable_count": len(answerable_rows),
            "multi_hop_count": len(multi_hop_rows),
            "null_count": len(null_rows),
            "permission_count": len(permission_rows),
            "permission_allowed_count": len(permission_allowed_rows),
            "permission_denied_count": len(permission_denied_rows),
            "table_structured_count": len(table_rows),
            "missing_count": len(testset) - len(rows),
            "filter_preflight_pass_rate": statistics.mean(
                int(row["filter_preflight_pass"]) for row in rows
            )
            if rows
            else 0.0,
            "mrr_at_max_k": statistics.mean(float(row["mrr_at_max_k"]) for row in answerable_rows)
            if answerable_rows
            else 0.0,
            "term_hit_rate_at_max_k": statistics.mean(
                float(row["term_hit_rate_at_max_k"]) for row in answerable_rows
            )
            if answerable_rows
            else 0.0,
            "forbidden_top1_rate": statistics.mean(
                int(row["top1_forbidden"]) for row in answerable_rows
            )
            if answerable_rows
            else 0.0,
            "empty_result_rate": statistics.mean(
                int(row["empty_result"]) for row in answerable_rows
            )
            if answerable_rows
            else 0.0,
            "top1_mojibake_rate": statistics.mean(int(row["top1_mojibake"]) for row in rows)
            if rows
            else 0.0,
            "latency_p50_ms": percentile(latencies, 0.50),
            "latency_p95_ms": percentile(latencies, 0.95),
        }
        for k in k_values:
            summary[f"recall_at_{k}"] = (
                statistics.mean(int(row[f"hit_at_{k}"]) for row in answerable_rows)
                if answerable_rows
                else 0.0
            )
            summary[f"term_hit_rate_at_{k}"] = (
                statistics.mean(float(row[f"term_hit_rate_at_{k}"]) for row in answerable_rows)
                if answerable_rows
                else 0.0
            )
            summary[f"success_at_{k}"] = statistics.mean(
                int(row[f"success_at_{k}"]) for row in rows
            )
            summary[f"multi_hop_group_coverage_at_{k}"] = (
                statistics.mean(
                    float(row[f"evidence_group_coverage_at_{k}"]) for row in multi_hop_rows
                )
                if multi_hop_rows
                else 0.0
            )
            summary[f"multi_hop_all_groups_at_{k}"] = (
                statistics.mean(int(row[f"all_evidence_groups_at_{k}"]) for row in multi_hop_rows)
                if multi_hop_rows
                else 0.0
            )
            summary[f"null_rejection_at_{k}"] = (
                statistics.mean(int(row[f"null_rejection_at_{k}"]) for row in null_rows)
                if null_rows
                else 0.0
            )
            summary[f"permission_safe_at_{k}"] = (
                statistics.mean(
                    int(row[f"permission_safe_at_{k}"]) for row in permission_denied_rows
                )
                if permission_denied_rows
                else 0.0
            )
            summary[f"permission_leak_at_{k}"] = (
                statistics.mean(
                    int(row[f"permission_leak_at_{k}"]) for row in permission_denied_rows
                )
                if permission_denied_rows
                else 0.0
            )
            summary[f"permission_allowed_recall_at_{k}"] = (
                statistics.mean(
                    int(row[f"permission_allowed_hit_at_{k}"])
                    for row in permission_allowed_rows
                )
                if permission_allowed_rows
                else 0.0
            )
            summary[f"protected_hit_count_at_{k}"] = sum(
                int(row[f"protected_hit_count_at_{k}"]) for row in permission_denied_rows
            )
            summary[f"sensitive_term_leak_at_{k}"] = (
                statistics.mean(
                    int(row[f"sensitive_term_leak_at_{k}"])
                    for row in permission_denied_rows
                )
                if permission_denied_rows
                else 0.0
            )
            summary[f"all_required_documents_at_{k}"] = statistics.mean(
                int(row[f"all_required_documents_at_{k}"]) for row in rows
            )
            summary[f"table_structured_success_at_{k}"] = (
                statistics.mean(
                    int(row[f"table_structured_hit_at_{k}"]) for row in table_rows
                )
                if table_rows
                else 0.0
            )
        summaries.append(summary)

    return details, summaries


def write_outputs(
    details: list[dict[str, Any]], summaries: list[dict[str, Any]], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    details_path = output_dir / "retrieval_eval_details.csv"
    summary_path = output_dir / "retrieval_eval_summary.json"

    if details:
        with details_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(details[0].keys()))
            writer.writeheader()
            writer.writerows(details)
    summary_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {details_path}")
    print(f"Wrote {summary_path}")


def print_table(summaries: list[dict[str, Any]], k_values: list[int]) -> None:
    if not summaries:
        print("No scored rows.")
        return
    last_k = max(k_values)
    headers = [
        "mode",
        "count",
        f"recall@{last_k}",
        f"mrr@{last_k}",
        f"terms@{last_k}",
        "bad_doc@1",
        "empty",
        "mojibake@1",
        "p95_ms",
    ]
    print("\t".join(headers))
    for row in summaries:
        values = [
            row["mode"],
            str(row["evaluated_count"]),
            f"{row[f'recall_at_{last_k}']:.3f}",
            f"{row['mrr_at_max_k']:.3f}",
            f"{row[f'term_hit_rate_at_{last_k}']:.3f}",
            f"{row['forbidden_top1_rate']:.3f}",
            f"{row['empty_result_rate']:.3f}",
            f"{row['top1_mojibake_rate']:.3f}",
            "" if row["latency_p95_ms"] is None else f"{row['latency_p95_ms']:.1f}",
        ]
        print("\t".join(values))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--testset", type=Path, default=Path(__file__).resolve().parent / "testset.jsonl"
    )
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parent / "results"
    )
    parser.add_argument("--k", default="1,3,5,10", help="Comma-separated k values, e.g. 1,3,5,10")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    k_values = sorted({int(value.strip()) for value in args.k.split(",") if value.strip()})
    if not k_values:
        raise SystemExit("--k must contain at least one integer")
    testset = load_jsonl(args.testset)
    result_rows = load_jsonl(args.results)
    details, summaries = score(testset, result_rows, k_values)
    print_table(summaries, k_values)
    write_outputs(details, summaries, args.output_dir)


if __name__ == "__main__":
    main()
