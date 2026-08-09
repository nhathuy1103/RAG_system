from __future__ import annotations

import argparse
import json
import shutil
import stat
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    FREEZE_METADATA_NAME,
    make_record_id,
    read_json,
    sha256_file,
    utc_now_iso,
    write_json,
    write_jsonl,
)
from app.pipeline.documents.extraction.evaluation.encoding_audit import (
    audit_benchmark,
    repair_candidates_for_value,
)
from app.pipeline.documents.extraction.evaluation.scoring_normalization import POLICY_VERSION

ADJUDICATION_POLICY_VERSION = "adjudication_policy_v1"
V2_SCHEMA_VERSION = "extraction_benchmark_v2.0"
PENDING_STATUS = "PENDING_ENCODING_ADJUDICATION"
PENDING_DECISION = "PENDING_HUMAN_ADJUDICATION"
PENDING_APPROVAL = "PENDING"


def create_extraction_v2_workspace(parent_dir: Path, target_dir: Path) -> dict[str, Any]:
    parent_dir = parent_dir.resolve()
    target_dir = target_dir.resolve()
    parent_manifest_path = parent_dir / "manifest.json"
    parent_manifest = read_json(parent_manifest_path)
    parent_freeze = _load_parent_freeze(parent_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "schemas").mkdir(exist_ok=True)
    (target_dir / "human_validation_workspace").mkdir(exist_ok=True)
    (target_dir / "reports").mkdir(exist_ok=True)

    v2_manifest = _build_v2_manifest(parent_manifest, parent_manifest_path, parent_freeze)
    write_json(target_dir / "manifest.json", v2_manifest)
    write_json(
        target_dir / "freeze_source_reference.json",
        _freeze_source_reference(parent_dir, parent_freeze),
    )
    write_json(target_dir / "adjudication_policy.json", adjudication_policy())
    _write_schemas(target_dir / "schemas")

    inventory = audit_benchmark(target_dir)
    write_json(target_dir / "encoding_inventory.json", inventory)
    page_findings = _group_findings_by_page(inventory.get("findings", []))
    queue = _adjudication_queue(inventory.get("findings", []))
    write_jsonl(target_dir / "adjudication_queue.jsonl", queue)
    write_jsonl(target_dir / "correction_lineage.jsonl", [])

    pages = _review_pages(parent_dir, parent_manifest)
    for page_number in pages:
        _write_page_workspace(
            parent_dir=parent_dir,
            target_dir=target_dir,
            manifest=v2_manifest,
            page_number=page_number,
            findings=page_findings.get(page_number, []),
        )

    summary = {
        "workspace_status": "CREATED",
        "benchmark_id": "extraction_v2",
        "parent_benchmark": parent_manifest.get("version"),
        "page_packets": len(pages),
        "adjudication_queue_items": len(queue),
        "blocking_findings": inventory["summary"]["blocking_count"],
        "created_at": utc_now_iso(),
        "data_verdict": "AWAITING_HUMAN_ADJUDICATION",
    }
    write_json(target_dir / "reports" / "workspace_summary.json", summary)
    return summary


def adjudication_policy() -> dict[str, Any]:
    return {
        "policy_version": ADJUDICATION_POLICY_VERSION,
        "reviewer_rules": {
            "ai_reviewers_forbidden": True,
            "parser_output_is_untrusted": True,
            "human_entered_values_required_for_lossy_question_marks": True,
            "do_not_strip_vietnamese_accents": True,
            "do_not_use_fuzzy_matching_for_approval": True,
        },
        "text": [
            "Mojibake repairs require human confirmation from the page image.",
            "Lossy question-mark values require manual transcription from the page image.",
            "Parser output is not source evidence.",
        ],
        "table_exact_fields": [
            "column_headers",
            "row_labels",
            "row_column_mapping",
            "code_columns",
            "notes_columns",
            "period_headers",
            "numbers",
            "parentheses",
            "negative_signs",
            "hyphens",
            "blank_cells",
            "merged_cells",
            "multiline_cells",
        ],
        "p0_second_review_required_when": [
            "negative_number",
            "multiple_periods",
            "rotated_table",
            "subsidiary_ownership_percentage",
            "row_or_cell_ambiguity",
            "structural_correction",
        ],
        "issues": {
            "source_truth_must_be_distinct_from_extraction_defect": True,
            "ground_truth_mojibake_cannot_justify_expected_mojibake_issue": True,
        },
    }


def _build_v2_manifest(
    parent_manifest: dict[str, Any],
    parent_manifest_path: Path,
    parent_freeze: dict[str, Any],
) -> dict[str, Any]:
    cases = []
    for case in parent_manifest.get("cases", []):
        copied = json.loads(json.dumps(case, ensure_ascii=False))
        copied["validation_status"] = PENDING_STATUS
        metadata = dict(copied.get("metadata") or {})
        metadata.update(
            {
                "validation_status": PENDING_STATUS,
                "evidence_complete": False,
                "reviewer": None,
                "reviewed_at": None,
                "approval_status": PENDING_APPROVAL,
                "parent_validation_status": case.get("validation_status"),
                "parent_human_validation_not_inherited": True,
                "source_page_image_reference_root": (
                    f"human_validation_workspace/{case.get('case_id')}/page_##/page_##_source.png"
                ),
            }
        )
        copied["metadata"] = metadata
        cases.append(copied)
    source_checksum = cases[0].get("sha256") if cases else None
    return {
        "version": "extraction_v2",
        "benchmark_schema_version": V2_SCHEMA_VERSION,
        "parent_benchmark": parent_manifest.get("version"),
        "parent_manifest_checksum": sha256_file(parent_manifest_path),
        "parent_ground_truth_bundle_checksum": parent_freeze.get("ground_truth_bundle_sha256"),
        "source_checksum": source_checksum,
        "adjudication_policy_version": ADJUDICATION_POLICY_VERSION,
        "scoring_normalization_policy_version": POLICY_VERSION,
        "minimum_human_approved_cases": 1,
        "release_eligibility_rules": {
            "case_validation_status": "HUMAN_VALIDATED",
            "document_approval_status": "HUMAN_APPROVED",
            "all_page_packets_human_approved": True,
            "preflight_required": True,
            "blocking_encoding_findings_allowed": 0,
        },
        "dataset_root": parent_manifest.get("dataset_root"),
        "cases": cases,
    }


def _load_parent_freeze(parent_dir: Path) -> dict[str, Any]:
    path = parent_dir / FREEZE_METADATA_NAME
    return read_json(path) if path.exists() else {}


def _freeze_source_reference(parent_dir: Path, parent_freeze: dict[str, Any]) -> dict[str, Any]:
    return {
        "parent_benchmark": "extraction_v1",
        "parent_path": str(parent_dir.as_posix()),
        "freeze_metadata": str((parent_dir / FREEZE_METADATA_NAME).as_posix()),
        "freeze_metadata_sha256": (
            sha256_file(parent_dir / FREEZE_METADATA_NAME)
            if (parent_dir / FREEZE_METADATA_NAME).exists()
            else None
        ),
        "parent_manifest_sha256": parent_freeze.get("manifest_sha256"),
        "parent_ground_truth_bundle_sha256": parent_freeze.get("ground_truth_bundle_sha256"),
        "known_defects": parent_freeze.get("known_defects", []),
    }


def _review_pages(parent_dir: Path, manifest: dict[str, Any]) -> list[int]:
    workspace = parent_dir / "human_validation_workspace"
    pages: set[int] = set()
    for page_dir in workspace.glob("*/page_*"):
        try:
            pages.add(int(page_dir.name.split("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    for case in manifest.get("cases", []):
        for item in case.get("expected_text", []):
            if item.get("page_number"):
                pages.add(int(item["page_number"]))
        for table in case.get("expected_tables", []):
            if table.get("page_number"):
                pages.add(int(table["page_number"]))
    return sorted(pages)


def _group_findings_by_page(findings: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        page = finding.get("page_number")
        if page is not None:
            grouped[int(page)].append(finding)
    return grouped


def _adjudication_queue(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for finding in findings:
        if not finding.get("requires_human_review"):
            continue
        rows.append(
            {
                "queue_id": make_record_id("queue", finding["finding_id"]),
                "finding_id": finding["finding_id"],
                "case_id": finding.get("case_id"),
                "page_number": finding.get("page_number"),
                "field_path": finding.get("field_path"),
                "encoding_class": finding.get("encoding_class"),
                "severity": finding.get("severity"),
                "decision": PENDING_DECISION,
                "approval_status": PENDING_APPROVAL,
                "reviewer": None,
                "reviewed_at": None,
            }
        )
    return rows


def _write_page_workspace(
    *,
    parent_dir: Path,
    target_dir: Path,
    manifest: dict[str, Any],
    page_number: int,
    findings: list[dict[str, Any]],
) -> None:
    case = manifest["cases"][0]
    case_id = case["case_id"]
    parent_page = parent_dir / "human_validation_workspace" / case_id / f"page_{page_number:02d}"
    target_page = target_dir / "human_validation_workspace" / case_id / f"page_{page_number:02d}"
    target_page.mkdir(parents=True, exist_ok=True)
    image_name = f"page_{page_number:02d}_source.png"
    _copy_if_exists(parent_page / image_name, target_page / image_name)
    _copy_if_exists(
        parent_page / "current_parser_output_untrusted.md",
        target_page / "parser_output_untrusted.md",
    )
    v1_packet = _read_optional_json(parent_page / "validation_packet.json")
    snapshot = _page_snapshot(case, v1_packet, page_number)
    write_json(target_page / "v1_expected_snapshot.json", snapshot)
    candidates = _repair_candidates_for_findings(findings)
    write_json(target_page / "repair_candidates.json", candidates)
    crop_manifest = _source_crop_manifest(target_page, image_name, page_number, v1_packet)
    write_json(target_page / "source_crop_manifest.json", crop_manifest)
    validation_packet = _validation_packet(
        case=case,
        page_number=page_number,
        findings=findings,
        image_name=image_name,
        v1_packet=v1_packet,
    )
    write_json(target_page / "validation_packet.json", validation_packet)
    adjudication_packet = _adjudication_packet(
        case=case,
        page_number=page_number,
        findings=findings,
        candidates=candidates,
        image_name=image_name,
        v1_packet=v1_packet,
    )
    write_json(target_page / "adjudication_packet.json", adjudication_packet)
    (target_page / "review_checklist.md").write_text(
        _review_checklist(page_number, findings),
        encoding="utf-8",
    )


def _copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        if target.exists():
            target.chmod(target.stat().st_mode | stat.S_IWRITE)
        shutil.copyfile(source, target)
        target.chmod(target.stat().st_mode | stat.S_IWRITE)


def _read_optional_json(path: Path) -> dict[str, Any]:
    return read_json(path) if path.exists() else {}


def _page_snapshot(
    case: dict[str, Any], v1_packet: dict[str, Any], page_number: int
) -> dict[str, Any]:
    return {
        "case_id": case.get("case_id"),
        "page_number": page_number,
        "v1_validation_status": v1_packet.get("validation_status"),
        "v1_reviewer": v1_packet.get("reviewer"),
        "v1_reviewed_at": v1_packet.get("reviewed_at"),
        "v1_expected_text": [
            item for item in case.get("expected_text", []) if item.get("page_number") == page_number
        ],
        "v1_expected_tables": [
            item
            for item in case.get("expected_tables", [])
            if item.get("page_number") == page_number
        ],
        "v1_page_packet_expected_text": v1_packet.get("expected_text", []),
        "v1_page_packet_expected_tables": v1_packet.get("expected_tables", []),
        "v1_page_packet_expected_issues": v1_packet.get("expected_issues", []),
        "approval_state_inherited": False,
        "reason": "v2 resets approval because v1 has known ground-truth encoding defects",
    }


def _source_crop_manifest(
    target_page: Path,
    image_name: str,
    page_number: int,
    v1_packet: dict[str, Any],
) -> dict[str, Any]:
    image_path = target_page / image_name
    return {
        "page_number": page_number,
        "source_document_sha256": v1_packet.get("source_sha256"),
        "source_image": image_name,
        "source_image_sha256": sha256_file(image_path) if image_path.exists() else None,
        "crops": [
            {
                "crop_id": "page_full",
                "source_image": image_name,
                "bbox": None,
                "purpose": "full-page human adjudication evidence",
            }
        ],
    }


def _repair_candidates_for_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    rows = {}
    for finding in findings:
        candidates = repair_candidates_for_value(str(finding.get("raw_value") or ""))
        rows[finding["finding_id"]] = {
            "field_path": finding.get("field_path"),
            "encoding_class": finding.get("encoding_class"),
            "candidates": candidates,
        }
    return rows


def _validation_packet(
    *,
    case: dict[str, Any],
    page_number: int,
    findings: list[dict[str, Any]],
    image_name: str,
    v1_packet: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_id": case.get("case_id"),
        "page_number": page_number,
        "source_image": image_name,
        "source_sha256": case.get("sha256"),
        "source_checksum_matches_v1_packet": (
            not v1_packet or v1_packet.get("source_sha256") == case.get("sha256")
        ),
        "validation_status": PENDING_STATUS,
        "evidence_complete": False,
        "reviewer": None,
        "reviewed_at": None,
        "approval_status": PENDING_APPROVAL,
        "field_level_findings": findings,
        "required_human_checks": [
            "all_blocking_encoding_findings_resolved",
            "lossy_question_mark_values_transcribed_from_source_image",
            "table_headers_row_labels_and_cells_checked_exactly",
            "negative_signs_parentheses_hyphens_blank_cells_checked_exactly",
            "expected_issue_codes_checked_against_extraction_defects",
            "parser_output_not_used_as_source_truth",
        ],
    }


def _adjudication_packet(
    *,
    case: dict[str, Any],
    page_number: int,
    findings: list[dict[str, Any]],
    candidates: dict[str, Any],
    image_name: str,
    v1_packet: dict[str, Any],
) -> dict[str, Any]:
    field_decisions = []
    for finding in findings:
        if not finding.get("requires_human_review"):
            continue
        field_decisions.append(
            {
                "finding_id": finding["finding_id"],
                "case_id": finding.get("case_id"),
                "page_number": page_number,
                "field_path": finding.get("field_path"),
                "encoding_class": finding.get("encoding_class"),
                "old_v1_value": finding.get("raw_value"),
                "repair_candidate": candidates.get(finding["finding_id"], {}).get("candidates", []),
                "parser_output_used_as_truth": False,
                "human_entered_value": None,
                "reviewer": None,
                "reviewed_at": None,
                "decision": PENDING_DECISION,
                "reason": None,
                "second_reviewer": None,
                "second_review_required": _requires_second_review(finding),
                "approval_status": PENDING_APPROVAL,
            }
        )
    return {
        "case_id": case.get("case_id"),
        "page_number": page_number,
        "source_image": image_name,
        "source_checksum": case.get("sha256"),
        "source_page_evidence": f"page_{page_number:02d}/{image_name}",
        "field_level_findings": findings,
        "v1_expected_snapshot": "v1_expected_snapshot.json",
        "repair_candidates": "repair_candidates.json",
        "parser_output_untrusted": {
            "path": "parser_output_untrusted.md",
            "trust": "UNTRUSTED",
        },
        "field_decisions": field_decisions,
        "human_entered_value": None,
        "reviewer": None,
        "reviewed_at": None,
        "decision": PENDING_DECISION,
        "reason": None,
        "second_reviewer": None,
        "approval_status": PENDING_APPROVAL,
        "v1_reviewer_not_inherited": v1_packet.get("reviewer"),
        "packet_sha256": None,
    }


def _requires_second_review(finding: dict[str, Any]) -> bool:
    field_path = str(finding.get("field_path") or "")
    severity = str(finding.get("severity") or "")
    encoding_class = str(finding.get("encoding_class") or "")
    return "expected_tables" in field_path and (
        severity == "BLOCKING" or encoding_class in {"NEGATIVE_SIGN_RISK", "PERIOD_HEADER_RISK"}
    )


def _review_checklist(page_number: int, findings: list[dict[str, Any]]) -> str:
    blocking = sum(1 for item in findings if item.get("severity") == "BLOCKING")
    review = sum(1 for item in findings if item.get("severity") == "REVIEW")
    return (
        f"# Page {page_number:02d} Encoding Adjudication Checklist\n\n"
        f"- Blocking findings: {blocking}\n"
        f"- Review findings: {review}\n"
        "- Confirm source image matches the source PDF page.\n"
        "- Resolve every field decision from the source image, not parser output.\n"
        "- Manually transcribe every lossy question-mark value.\n"
        "- Verify table headers, row labels, periods, numbers, signs, hyphens, and blank cells exactly.\n"
        "- Add a second reviewer for P0 table corrections where the policy requires it.\n"
        "- Append correction lineage for every corrected value before promotion.\n"
    )


def _write_schemas(schema_dir: Path) -> None:
    write_json(
        schema_dir / "adjudication_packet.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Extraction v2 adjudication packet",
            "type": "object",
            "required": ["case_id", "page_number", "field_decisions", "approval_status"],
            "properties": {
                "case_id": {"type": "string"},
                "page_number": {"type": "integer", "minimum": 1},
                "field_decisions": {"type": "array"},
                "approval_status": {"type": "string"},
            },
        },
    )
    write_json(
        schema_dir / "correction_lineage.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Extraction v2 correction lineage record",
            "type": "object",
            "required": [
                "correction_id",
                "case_id",
                "page_number",
                "field_path",
                "old_value",
                "new_value",
                "reviewer",
                "reviewed_at",
                "approval_status",
                "record_sha256",
            ],
        },
    )
    write_json(
        schema_dir / "encoding_inventory.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Extraction v2 encoding inventory",
            "type": "object",
            "required": ["benchmark_id", "summary", "findings"],
        },
    )
    write_json(
        schema_dir / "manifest.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Extraction v2 manifest",
            "type": "object",
            "required": [
                "version",
                "benchmark_schema_version",
                "parent_benchmark",
                "adjudication_policy_version",
                "scoring_normalization_policy_version",
                "cases",
            ],
        },
    )
    write_json(
        schema_dir / "scoring_normalization_v1.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Safe scoring normalization v1",
            "type": "object",
            "required": ["policy_version", "allowed_operations", "forbidden_operations"],
        },
    )
    write_json(
        schema_dir / "bundle_manifest.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Promoted extraction v2 approved bundle manifest",
            "type": "object",
            "required": [
                "bundle_checksum",
                "canonical_approved_bundle_checksum",
                "hash_contract_version",
                "manifest_sha256",
                "policy_version",
            ],
        },
    )


def workspace_bundle_checksum(benchmark_dir: Path) -> str:
    from app.pipeline.documents.extraction.evaluation.approved_bundle_integrity import (
        approved_bundle_checksum,
    )

    return approved_bundle_checksum(benchmark_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create extraction_v2 adjudication workspace.")
    parser.add_argument("--parent", type=Path, default=Path("benchmarks/extraction_v1"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/extraction_v2"))
    args = parser.parse_args()
    summary = create_extraction_v2_workspace(args.parent, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
