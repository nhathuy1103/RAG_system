from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.approved_bundle_integrity import (
    HASH_CONTRACT_VERSION,
    approved_bundle_checksum,
    legacy_bundle_checksum_v1,
)
from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    load_jsonl,
    make_record_id,
    read_json,
    sha256_file,
    write_json,
)
from app.pipeline.documents.extraction.evaluation.encoding_audit import audit_benchmark

PASS_STATUS = "PASS"
FAIL_STATUS = "FAIL"
APPROVED_STATUS = "HUMAN_APPROVED"
VALIDATED_STATUS = "HUMAN_VALIDATED"
BLOCKED_DECISIONS = {"PENDING_HUMAN_ADJUDICATION", "UNRESOLVED", None, ""}
AI_REVIEWER_MARKERS = ("ai", "codex", "assistant", "chatgpt", "model", "bot")


def run_preflight(benchmark_dir: Path, *, expected_pages: int = 13) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    errors: list[dict[str, Any]] = []
    manifest = _read_required_json(benchmark_dir / "manifest.json", errors, "manifest")
    case = (manifest.get("cases") or [{}])[0] if manifest else {}
    case_id = str(case.get("case_id") or "unknown")

    _check_page_packets(
        benchmark_dir=benchmark_dir,
        case_id=case_id,
        source_sha256=case.get("sha256") or manifest.get("source_checksum") if manifest else None,
        expected_pages=expected_pages,
        errors=errors,
    )
    inventory = audit_benchmark(benchmark_dir) if manifest else {"findings": [], "summary": {}}
    _check_encoding_inventory(inventory, errors)
    _check_correction_lineage(benchmark_dir, errors)
    _check_manifest_schema(manifest, errors)
    _check_bundle_checksum(benchmark_dir, errors)

    return {
        "status": PASS_STATUS if not errors else FAIL_STATUS,
        "passed": not errors,
        "benchmark_dir": str(benchmark_dir.as_posix()),
        "blocking_error_count": len(errors),
        "blocking_errors": errors,
    }


def _check_page_packets(
    *,
    benchmark_dir: Path,
    case_id: str,
    source_sha256: str | None,
    expected_pages: int,
    errors: list[dict[str, Any]],
) -> None:
    workspace = benchmark_dir / "human_validation_workspace" / case_id
    for page_number in range(1, expected_pages + 1):
        page_dir = workspace / f"page_{page_number:02d}"
        validation_path = page_dir / "validation_packet.json"
        adjudication_path = page_dir / "adjudication_packet.json"
        if not validation_path.exists():
            _error(errors, page_number, "validation_packet", "missing_page_validation_packet")
            continue
        if not adjudication_path.exists():
            _error(errors, page_number, "adjudication_packet", "missing_page_adjudication_packet")
            continue
        validation = read_json(validation_path)
        adjudication = read_json(adjudication_path)
        if source_sha256 and validation.get("source_sha256") != source_sha256:
            _error(errors, page_number, "source_sha256", "source_sha256_mismatch")
        _check_packet_reviewer(validation, errors, page_number, "validation_packet")
        _check_packet_reviewer(adjudication, errors, page_number, "adjudication_packet")
        if validation.get("validation_status") != VALIDATED_STATUS:
            _error(errors, page_number, "validation_status", "page_not_human_validated")
        if adjudication.get("approval_status") != APPROVED_STATUS:
            _error(errors, page_number, "approval_status", "page_not_human_approved")
        image = page_dir / str(adjudication.get("source_image") or "")
        crop_manifest_path = page_dir / "source_crop_manifest.json"
        if not image.exists():
            _error(errors, page_number, "source_image", "missing_source_image")
        elif crop_manifest_path.exists():
            crop_manifest = read_json(crop_manifest_path)
            expected_image_sha = crop_manifest.get("source_image_sha256")
            if expected_image_sha and sha256_file(image) != expected_image_sha:
                _error(errors, page_number, "source_image", "source_image_checksum_mismatch")
        else:
            _error(errors, page_number, "source_crop_manifest", "missing_source_crop_manifest")
        for index, decision in enumerate(adjudication.get("field_decisions", [])):
            field_path = str(decision.get("field_path") or f"field_decisions[{index}]")
            if decision.get("decision") in BLOCKED_DECISIONS:
                _error(errors, page_number, field_path, "field_decision_pending_or_unresolved")
            if decision.get("approval_status") != APPROVED_STATUS:
                _error(errors, page_number, field_path, "field_decision_not_human_approved")
            _check_packet_reviewer(decision, errors, page_number, field_path)
            if decision.get("second_review_required") and not decision.get("second_reviewer"):
                _error(errors, page_number, field_path, "missing_required_second_reviewer")
            if decision.get("parser_output_used_as_truth"):
                _error(errors, page_number, field_path, "parser_output_used_as_truth")


def _check_packet_reviewer(
    payload: dict[str, Any],
    errors: list[dict[str, Any]],
    page_number: int | None,
    field_path: str,
) -> None:
    reviewer = payload.get("reviewer")
    if not reviewer:
        _error(errors, page_number, field_path, "missing_reviewer")
    elif _looks_like_ai_reviewer(str(reviewer)):
        _error(errors, page_number, field_path, "ai_reviewer_forbidden")
    reviewed_at = payload.get("reviewed_at")
    if not reviewed_at:
        _error(errors, page_number, field_path, "missing_reviewed_at")
    elif not _valid_iso_datetime(str(reviewed_at)):
        _error(errors, page_number, field_path, "invalid_reviewed_at")


def _check_encoding_inventory(inventory: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    for finding in inventory.get("findings", []):
        if finding.get("severity") != "BLOCKING":
            continue
        _error(
            errors,
            finding.get("page_number"),
            finding.get("field_path"),
            f"blocking_encoding_finding:{finding.get('encoding_class')}",
        )


def _check_correction_lineage(benchmark_dir: Path, errors: list[dict[str, Any]]) -> None:
    lineage_path = benchmark_dir / "correction_lineage.jsonl"
    if not lineage_path.exists():
        _error(errors, None, "correction_lineage", "missing_correction_lineage")
        return
    rows = load_jsonl(lineage_path)
    seen_ids: set[str] = set()
    for row in rows:
        correction_id = str(row.get("correction_id") or "")
        if not correction_id:
            _error(
                errors,
                row.get("page_number"),
                row.get("field_path"),
                "lineage_missing_correction_id",
            )
        if correction_id in seen_ids:
            _error(errors, row.get("page_number"), row.get("field_path"), "duplicate_lineage_id")
        seen_ids.add(correction_id)
        if row.get("parser_output_used_as_truth"):
            _error(
                errors,
                row.get("page_number"),
                row.get("field_path"),
                "lineage_uses_parser_output_as_truth",
            )
        if row.get("approval_status") != APPROVED_STATUS:
            _error(
                errors, row.get("page_number"), row.get("field_path"), "lineage_not_human_approved"
            )
        reviewer = row.get("reviewer")
        if not reviewer or _looks_like_ai_reviewer(str(reviewer)):
            _error(
                errors, row.get("page_number"), row.get("field_path"), "invalid_lineage_reviewer"
            )
        if not _valid_iso_datetime(str(row.get("reviewed_at") or "")):
            _error(
                errors, row.get("page_number"), row.get("field_path"), "invalid_lineage_reviewed_at"
            )
        expected_sha = row.get("record_sha256")
        if expected_sha:
            unsigned = dict(row)
            unsigned.pop("record_sha256", None)
            actual = make_record_id(
                "lineage", json.dumps(unsigned, ensure_ascii=False, sort_keys=True), length=64
            )
            if actual.removeprefix("lineage_") != expected_sha:
                _error(
                    errors,
                    row.get("page_number"),
                    row.get("field_path"),
                    "lineage_record_sha256_mismatch",
                )


def _check_manifest_schema(manifest: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    required = [
        "benchmark_schema_version",
        "parent_benchmark",
        "parent_manifest_checksum",
        "source_checksum",
        "adjudication_policy_version",
        "scoring_normalization_policy_version",
        "minimum_human_approved_cases",
        "release_eligibility_rules",
    ]
    for key in required:
        if key not in manifest:
            _error(errors, None, f"manifest.{key}", "manifest_missing_required_v2_key")


def _check_bundle_checksum(benchmark_dir: Path, errors: list[dict[str, Any]]) -> None:
    approved_dir = benchmark_dir / "approved_bundle"
    metadata_path = approved_dir / "bundle_metadata.json"
    if not metadata_path.exists():
        return
    metadata = read_json(metadata_path)
    if not metadata.get("bundle_checksum"):
        _error(errors, None, "approved_bundle.bundle_checksum", "approved_bundle_checksum_missing")
        return
    try:
        if metadata.get("hash_contract_version") == HASH_CONTRACT_VERSION:
            actual = approved_bundle_checksum(approved_dir)
            expected = metadata.get("canonical_approved_bundle_checksum")
            if metadata.get("bundle_checksum") != expected:
                _error(
                    errors,
                    None,
                    "approved_bundle.bundle_checksum",
                    "approved_bundle_canonical_checksum_fields_disagree",
                )
        else:
            actual = legacy_bundle_checksum_v1(approved_dir)
            expected = metadata.get("bundle_checksum")
        if actual != expected:
            _error(
                errors,
                None,
                "approved_bundle.bundle_checksum",
                f"approved_bundle_checksum_mismatch:{expected}:{actual}",
            )
        manifest_path = approved_dir / "manifest.json"
        if manifest_path.exists() and metadata.get("manifest_sha256") != sha256_file(manifest_path):
            _error(
                errors,
                None,
                "approved_bundle.manifest_sha256",
                "approved_bundle_manifest_sha256_mismatch",
            )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        _error(
            errors,
            None,
            "approved_bundle",
            f"approved_bundle_integrity_read_failed:{exc}",
        )


def _read_required_json(
    path: Path, errors: list[dict[str, Any]], field_path: str
) -> dict[str, Any]:
    if not path.exists():
        _error(errors, None, field_path, "missing_required_json")
        return {}
    try:
        return read_json(path)
    except json.JSONDecodeError as exc:
        _error(errors, None, field_path, f"invalid_json:{exc}")
        return {}


def _error(
    errors: list[dict[str, Any]],
    page_number: int | None,
    field_path: object,
    reason: str,
) -> None:
    errors.append(
        {
            "page_number": page_number,
            "field_path": str(field_path),
            "reason": reason,
        }
    )


def _looks_like_ai_reviewer(value: str) -> bool:
    folded = value.strip().lower()
    return any(marker in folded for marker in AI_REVIEWER_MARKERS)


def _valid_iso_datetime(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate extraction_v2 human adjudication readiness."
    )
    parser.add_argument("benchmark_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_preflight(args.benchmark_dir)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        write_json(args.output, result)
    else:
        print(text)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
