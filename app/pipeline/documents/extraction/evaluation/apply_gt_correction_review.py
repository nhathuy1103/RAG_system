from __future__ import annotations

import argparse
import json
import re
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.adjudication_editor import (
    apply_value_to_manifest,
    reviewer_is_ai,
)
from app.pipeline.documents.extraction.evaluation.approved_bundle_integrity import (
    verify_approved_bundle_integrity,
)
from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    load_jsonl,
    make_record_id,
    read_json,
    sha256_file,
    sha256_json,
    sha256_text,
    write_json,
    write_jsonl,
)
from app.pipeline.documents.extraction.evaluation.encoding_audit import write_inventory

APPROVED_STATUS = "HUMAN_APPROVED"
PENDING_STATUS = "PENDING_HUMAN_APPROVAL"
REPLACE_OPERATION = "REPLACE"
REMOVE_OPERATION = "REMOVE"
ISSUE_PATH_RE = re.compile(r"^cases\[(\d+)]\.expected_issues\[(\d+)]$")
TEXT_PATH_RE = re.compile(r"^cases\[(\d+)]\.expected_text\[(\d+)]\.text$")
CELL_PATH_RE = re.compile(r"^cases\[(\d+)]\.expected_tables\[(\d+)]\.rows\[(\d+)]\.(.*)$")


def apply_human_approved_review(
    benchmark_dir: Path,
    review_path: Path,
    *,
    reviewer: str,
    reviewed_at: str,
    approval_evidence: str,
    expected_approved_bundle_checksum: str,
    amendment_dir: Path,
) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    review_path = review_path.resolve()
    amendment_dir = amendment_dir.resolve()
    _validate_approval(reviewer, reviewed_at, approval_evidence)

    review = read_json(review_path)
    if review.get("status") != PENDING_STATUS:
        raise ValueError(f"Correction review must be {PENDING_STATUS}.")
    if review.get("approved_bundle_modified"):
        raise ValueError("Correction review says the approved bundle was already modified.")
    _validate_candidate_benchmark(review, benchmark_dir.parent.parent)

    integrity = verify_approved_bundle_integrity(benchmark_dir)
    if not integrity["passed"]:
        raise ValueError(f"Approved bundle integrity failed: {integrity['errors']}")
    actual_checksum = str(integrity["canonical_approved_bundle_checksum"])
    if actual_checksum != expected_approved_bundle_checksum:
        raise ValueError(
            "Approved bundle checksum changed before amendment: "
            f"{expected_approved_bundle_checksum} != {actual_checksum}"
        )

    manifest_path = benchmark_dir / "manifest.json"
    lineage_path = benchmark_dir / "correction_lineage.jsonl"
    manifest = read_json(manifest_path)
    planned = _plan_corrections(manifest, review.get("corrections") or [])
    _validate_source_evidence(planned, benchmark_dir.parent.parent)
    amended_manifest = deepcopy(manifest)
    _apply_planned_corrections(amended_manifest, planned)
    lineage_rows = load_jsonl(lineage_path)
    new_lineage = [
        _lineage_record(
            review=review,
            correction=item,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            approval_evidence=approval_evidence,
        )
        for item in planned
    ]
    existing_ids = {row.get("correction_id") for row in lineage_rows}
    duplicate_ids = [
        row["correction_id"] for row in new_lineage if row["correction_id"] in existing_ids
    ]
    if duplicate_ids:
        raise ValueError(f"Correction lineage already contains: {duplicate_ids}")

    _archive_pre_amendment_state(
        benchmark_dir=benchmark_dir,
        review_path=review_path,
        amendment_dir=amendment_dir,
        approved_bundle_checksum=actual_checksum,
    )
    write_json(manifest_path, amended_manifest)
    write_jsonl(lineage_path, [*lineage_rows, *new_lineage])
    write_inventory(benchmark_dir, benchmark_dir / "encoding_inventory.json")

    result = {
        "status": "APPLIED_TO_WORKSPACE",
        "applied": True,
        "case_id": review.get("case_id"),
        "reviewer": reviewer.strip(),
        "reviewed_at": reviewed_at,
        "approval_evidence": approval_evidence.strip(),
        "correction_count": len(planned),
        "operations": {
            REPLACE_OPERATION: sum(item["operation"] == REPLACE_OPERATION for item in planned),
            REMOVE_OPERATION: sum(item["operation"] == REMOVE_OPERATION for item in planned),
        },
        "previous_approved_bundle_checksum": actual_checksum,
        "workspace_manifest_sha256": sha256_file(manifest_path),
        "lineage_records_added": [item["correction_id"] for item in new_lineage],
        "amendment_archive": amendment_dir.as_posix(),
        "approved_bundle_modified": False,
    }
    approved_review = dict(review)
    approved_review.update(
        {
            "status": APPROVED_STATUS,
            "reviewer": reviewer.strip(),
            "reviewed_at": reviewed_at,
            "approval_evidence": approval_evidence.strip(),
            "workspace_application": result,
        }
    )
    write_json(review_path, approved_review)
    write_json(amendment_dir / "gt_correction_review.approved.json", approved_review)
    write_json(amendment_dir / "workspace_application_result.json", result)
    return result


def _plan_corrections(
    manifest: dict[str, Any],
    corrections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not corrections:
        raise ValueError("Correction review contains no corrections.")
    planned: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for correction in corrections:
        field_path = str(correction.get("field_path") or "")
        if not field_path or field_path in seen_paths:
            raise ValueError(f"Invalid or duplicate correction path: {field_path}")
        seen_paths.add(field_path)
        operation = str(correction.get("candidate_operation") or REPLACE_OPERATION).strip().upper()
        if operation not in {REPLACE_OPERATION, REMOVE_OPERATION}:
            raise ValueError(f"Unsupported correction operation: {operation}")
        old_value = _value_at_path(manifest, field_path)
        expected_old_value = correction.get("old_value")
        if old_value != expected_old_value:
            raise ValueError(
                f"Old value mismatch at {field_path}: {expected_old_value!r} != {old_value!r}"
            )
        if operation == REMOVE_OPERATION:
            if not ISSUE_PATH_RE.match(field_path):
                raise ValueError(f"REMOVE is only supported for expected issues: {field_path}")
            new_value = None
        else:
            if "candidate_value" not in correction:
                raise ValueError(f"Missing candidate_value at {field_path}")
            new_value = correction["candidate_value"]
        planned.append(
            {
                **correction,
                "field_path": field_path,
                "operation": operation,
                "old_value": old_value,
                "new_value": new_value,
            }
        )
    return planned


def _apply_planned_corrections(
    manifest: dict[str, Any],
    planned: list[dict[str, Any]],
) -> None:
    for correction in planned:
        if correction["operation"] != REPLACE_OPERATION:
            continue
        apply_value_to_manifest(
            manifest,
            correction["field_path"],
            str(correction["new_value"]),
        )
    removals = sorted(
        (correction for correction in planned if correction["operation"] == REMOVE_OPERATION),
        key=lambda item: _issue_path_indexes(item["field_path"]),
        reverse=True,
    )
    for correction in removals:
        case_index, issue_index = _issue_path_indexes(correction["field_path"])
        del manifest["cases"][case_index]["expected_issues"][issue_index]


def _value_at_path(manifest: dict[str, Any], field_path: str) -> Any:
    if match := ISSUE_PATH_RE.match(field_path):
        case_index, issue_index = int(match.group(1)), int(match.group(2))
        return manifest["cases"][case_index]["expected_issues"][issue_index]
    if match := TEXT_PATH_RE.match(field_path):
        case_index, text_index = int(match.group(1)), int(match.group(2))
        return manifest["cases"][case_index]["expected_text"][text_index]["text"]
    if match := CELL_PATH_RE.match(field_path):
        case_index, table_index, row_index = map(int, match.groups()[:3])
        key = match.group(4)
        return manifest["cases"][case_index]["expected_tables"][table_index]["rows"][row_index][key]
    raise ValueError(f"Unsupported correction path: {field_path}")


def _issue_path_indexes(field_path: str) -> tuple[int, int]:
    match = ISSUE_PATH_RE.match(field_path)
    if not match:
        raise ValueError(f"Not an expected issue path: {field_path}")
    return int(match.group(1)), int(match.group(2))


def _lineage_record(
    *,
    review: dict[str, Any],
    correction: dict[str, Any],
    reviewer: str,
    reviewed_at: str,
    approval_evidence: str,
) -> dict[str, Any]:
    old_value = correction["old_value"]
    new_value = correction["new_value"]
    record = {
        "correction_id": make_record_id(
            "corr",
            review.get("case_id"),
            correction.get("page_number"),
            correction["field_path"],
            correction["operation"],
            sha256_json(old_value),
            sha256_json(new_value),
            reviewer,
            reviewed_at,
        ),
        "case_id": review.get("case_id"),
        "page_number": correction.get("page_number"),
        "field_path": correction["field_path"],
        "old_benchmark": "extraction_v2_approved_bundle",
        "correction_operation": correction["operation"],
        "old_value": old_value,
        "new_value": new_value,
        "defect_type": "SOURCE_EVIDENCE_GT_CORRECTION",
        "reason": correction.get("reason"),
        "source_evidence": correction.get("source_evidence"),
        "parser_output_used_as_truth": False,
        "reviewer": reviewer.strip(),
        "reviewed_at": reviewed_at,
        "second_reviewer": None,
        "approval_status": APPROVED_STATUS,
        "approval_evidence": approval_evidence.strip(),
        "old_value_sha256": _value_sha256(old_value),
        "new_value_sha256": _value_sha256(new_value),
    }
    unsigned = json.dumps(record, ensure_ascii=False, sort_keys=True)
    record["record_sha256"] = make_record_id(
        "lineage",
        unsigned,
        length=64,
    ).removeprefix("lineage_")
    return record


def _value_sha256(value: Any) -> str:
    return sha256_text(value) if isinstance(value, str) else sha256_json(value)


def _validate_candidate_benchmark(
    review: dict[str, Any],
    repo_root: Path,
) -> None:
    summary = review.get("candidate_benchmark") or {}
    if summary.get("benchmark_status") != "PASS":
        raise ValueError("Candidate benchmark is not PASS.")
    if summary.get("silent_p0"):
        raise ValueError("Candidate benchmark contains a silent P0.")
    for metric in ("text_recall", "table_recall", "issue_recall"):
        if float(summary.get(metric) or 0.0) < 0.7:
            raise ValueError(f"Candidate benchmark {metric} is below 0.7.")
    report_path = repo_root / str(summary.get("report") or "")
    if not report_path.is_file():
        raise ValueError(f"Candidate benchmark report is missing: {report_path}")
    report = read_json(report_path)
    score = (report.get("scores") or [{}])[0]
    for key in ("text_recall", "table_recall", "issue_recall", "silent_p0"):
        if score.get(key) != summary.get(key):
            raise ValueError(f"Candidate benchmark summary mismatch: {key}")
    if report.get("benchmark_status") != summary.get("benchmark_status"):
        raise ValueError("Candidate benchmark status mismatch.")


def _validate_source_evidence(
    planned: list[dict[str, Any]],
    repo_root: Path,
) -> None:
    missing = [
        str(correction.get("source_evidence") or "")
        for correction in planned
        if not (repo_root / str(correction.get("source_evidence") or "")).is_file()
    ]
    if missing:
        raise ValueError(f"Correction source evidence is missing: {missing}")


def _validate_approval(
    reviewer: str,
    reviewed_at: str,
    approval_evidence: str,
) -> None:
    if not reviewer.strip() or reviewer_is_ai(reviewer):
        raise ValueError("Reviewer must identify a human.")
    try:
        datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be ISO-8601.") from exc
    if not approval_evidence.strip():
        raise ValueError("Approval evidence is required.")


def _archive_pre_amendment_state(
    *,
    benchmark_dir: Path,
    review_path: Path,
    amendment_dir: Path,
    approved_bundle_checksum: str,
) -> None:
    if amendment_dir.exists():
        raise FileExistsError(f"Amendment archive already exists: {amendment_dir}")
    amendment_dir.mkdir(parents=True)
    shutil.copy2(benchmark_dir / "manifest.json", amendment_dir / "manifest.before.json")
    shutil.copy2(
        benchmark_dir / "correction_lineage.jsonl",
        amendment_dir / "correction_lineage.before.jsonl",
    )
    shutil.copy2(review_path, amendment_dir / "gt_correction_review.before.json")
    approved_archive = amendment_dir / "approved_bundle.before"
    shutil.copytree(benchmark_dir / "approved_bundle", approved_archive)
    archive_files = [
        {
            "relative_path": path.relative_to(amendment_dir).as_posix(),
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(
            (item for item in amendment_dir.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(amendment_dir).as_posix(),
        )
    ]
    write_json(
        amendment_dir / "archive_metadata.json",
        {
            "archive_status": "PRESERVED_PRE_AMENDMENT_EVIDENCE",
            "approved_bundle_checksum": approved_bundle_checksum,
            "files": archive_files,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply an explicitly human-approved Ground Truth correction review."
    )
    parser.add_argument("benchmark_dir", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--approval-evidence", required=True)
    parser.add_argument("--expected-approved-bundle-checksum", required=True)
    parser.add_argument("--amendment-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = apply_human_approved_review(
        args.benchmark_dir,
        args.review,
        reviewer=args.reviewer,
        reviewed_at=args.reviewed_at,
        approval_evidence=args.approval_evidence,
        expected_approved_bundle_checksum=args.expected_approved_bundle_checksum,
        amendment_dir=args.amendment_dir,
    )
    if args.output:
        write_json(args.output, result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
