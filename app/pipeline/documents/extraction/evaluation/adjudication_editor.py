from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    load_jsonl,
    make_record_id,
    read_json,
    sha256_json,
    sha256_text,
    write_json,
    write_jsonl,
)
from app.pipeline.documents.extraction.evaluation.encoding_audit import (
    semantic_signature,
    write_inventory,
)

DECISION_OPTIONS = (
    "PENDING_HUMAN_ADJUDICATION",
    "CONFIRMED_V1_VALUE_CORRECT",
    "CONFIRMED_GT_ENCODING_DEFECT",
    "CONFIRMED_GT_STRUCTURAL_DEFECT",
    "CONFIRMED_PARSER_DEFECT",
    "MANUAL_TRANSCRIPTION_REQUIRED",
    "UNRESOLVED",
)
APPROVAL_OPTIONS = ("PENDING", "HUMAN_APPROVED")
APPROVED_STATUS = "HUMAN_APPROVED"
VALIDATED_STATUS = "HUMAN_VALIDATED"
PENDING_DECISIONS = {"", "PENDING_HUMAN_ADJUDICATION", "UNRESOLVED"}
CORRECTION_DECISIONS = {
    "CONFIRMED_GT_ENCODING_DEFECT",
    "CONFIRMED_GT_STRUCTURAL_DEFECT",
    "MANUAL_TRANSCRIPTION_REQUIRED",
}
AI_REVIEWER_MARKERS = ("ai", "codex", "assistant", "chatgpt", "model", "bot")
TEXT_PATH_RE = re.compile(r"^cases\[(\d+)]\.expected_text\[(\d+)]\.text$")
COLUMN_PATH_RE = re.compile(r"^cases\[(\d+)]\.expected_tables\[(\d+)]\.columns\[(\d+)]$")
ROW_KEY_PATH_RE = re.compile(
    r"^cases\[(\d+)]\.expected_tables\[(\d+)]\.rows\[(\d+)]\.<row_key:(.*)>$"
)
CELL_PATH_RE = re.compile(r"^cases\[(\d+)]\.expected_tables\[(\d+)]\.rows\[(\d+)]\.(.*)$")


@dataclass(frozen=True)
class PagePaths:
    root: Path
    case_id: str
    page_number: int
    page_dir: Path
    adjudication_packet: Path
    validation_packet: Path


def load_case_id(benchmark_dir: Path) -> str:
    manifest = read_json(benchmark_dir / "manifest.json")
    cases = manifest.get("cases") or []
    if not cases:
        raise ValueError("Manifest không có case nào.")
    return str(cases[0]["case_id"])


def page_paths(benchmark_dir: Path, page_number: int, *, case_id: str | None = None) -> PagePaths:
    root = benchmark_dir.resolve()
    resolved_case_id = case_id or load_case_id(root)
    page_dir = root / "human_validation_workspace" / resolved_case_id / f"page_{page_number:02d}"
    return PagePaths(
        root=root,
        case_id=resolved_case_id,
        page_number=page_number,
        page_dir=page_dir,
        adjudication_packet=page_dir / "adjudication_packet.json",
        validation_packet=page_dir / "validation_packet.json",
    )


def list_page_statuses(benchmark_dir: Path) -> list[dict[str, Any]]:
    case_id = load_case_id(benchmark_dir)
    statuses: list[dict[str, Any]] = []
    workspace = benchmark_dir / "human_validation_workspace" / case_id
    for page_dir in sorted(workspace.glob("page_*")):
        try:
            page_number = int(page_dir.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        packet_path = page_dir / "adjudication_packet.json"
        validation_path = page_dir / "validation_packet.json"
        if not packet_path.exists():
            statuses.append(
                {
                    "page": page_number,
                    "findings": 0,
                    "decisions": 0,
                    "pending": 0,
                    "approved": 0,
                    "second_review_required": 0,
                    "page_status": "MISSING_PACKET",
                }
            )
            continue
        packet = read_json(packet_path)
        validation = read_json(validation_path) if validation_path.exists() else {}
        decisions = list(packet.get("field_decisions") or [])
        statuses.append(
            {
                "page": page_number,
                "findings": len(packet.get("field_level_findings") or []),
                "decisions": len(decisions),
                "pending": sum(
                    1 for item in decisions if item.get("decision") in PENDING_DECISIONS
                ),
                "approved": sum(
                    1 for item in decisions if item.get("approval_status") == APPROVED_STATUS
                ),
                "second_review_required": sum(
                    1 for item in decisions if item.get("second_review_required")
                ),
                "page_status": packet.get("approval_status") or "PENDING",
                "validation_status": validation.get("validation_status"),
            }
        )
    return statuses


def load_page_context(benchmark_dir: Path, page_number: int) -> dict[str, Any]:
    paths = page_paths(benchmark_dir, page_number)
    packet = read_json(paths.adjudication_packet)
    validation = read_json(paths.validation_packet) if paths.validation_packet.exists() else {}
    return {
        "paths": paths,
        "packet": packet,
        "validation": validation,
        "snapshot": _read_optional_json(paths.page_dir / "v1_expected_snapshot.json"),
        "repair_candidates": _read_optional_json(paths.page_dir / "repair_candidates.json"),
        "parser_output": _read_optional_text(paths.page_dir / "parser_output_untrusted.md"),
    }


def save_field_decision(
    benchmark_dir: Path,
    page_number: int,
    finding_id: str,
    *,
    decision: str,
    human_entered_value: str,
    reviewer: str,
    reviewed_at: str,
    reason: str,
    second_reviewer: str | None = None,
    approval_status: str = "PENDING",
) -> dict[str, Any]:
    if decision not in DECISION_OPTIONS:
        raise ValueError(f"Decision không hợp lệ: {decision}")
    if approval_status not in APPROVAL_OPTIONS:
        raise ValueError(f"Approval status không hợp lệ: {approval_status}")
    if approval_status == APPROVED_STATUS:
        _validate_human_review_fields(reviewer, reviewed_at)

    paths = page_paths(benchmark_dir, page_number)
    packet = read_json(paths.adjudication_packet)
    target = _find_decision(packet, finding_id)
    target.update(
        {
            "decision": decision,
            "human_entered_value": human_entered_value.strip() or None,
            "reviewer": reviewer.strip() or None,
            "reviewed_at": reviewed_at.strip() or None,
            "reason": reason.strip() or None,
            "second_reviewer": second_reviewer.strip() if second_reviewer else None,
            "approval_status": approval_status,
            "parser_output_used_as_truth": False,
        }
    )
    _stamp_packet_hash(packet)
    write_json(paths.adjudication_packet, packet)

    lineage_record = None
    if approval_status == APPROVED_STATUS and _decision_changes_value(target):
        lineage_record = append_lineage_record(
            benchmark_dir,
            packet=packet,
            decision_record=target,
        )
    return {
        "saved": True,
        "lineage_appended": lineage_record is not None,
        "lineage_record": lineage_record,
    }


def approve_page(
    benchmark_dir: Path,
    page_number: int,
    *,
    reviewer: str,
    reviewed_at: str,
    reason: str,
) -> dict[str, Any]:
    _validate_human_review_fields(reviewer, reviewed_at)
    paths = page_paths(benchmark_dir, page_number)
    packet = read_json(paths.adjudication_packet)
    errors = page_approval_errors(packet)
    if errors:
        return {"approved": False, "errors": errors}

    packet.update(
        {
            "reviewer": reviewer.strip(),
            "reviewed_at": reviewed_at.strip(),
            "reason": reason.strip() or "Trang đã được reviewer xác nhận từ ảnh nguồn.",
            "approval_status": APPROVED_STATUS,
            "decision": _page_decision(packet),
        }
    )
    _stamp_packet_hash(packet)
    write_json(paths.adjudication_packet, packet)

    validation = read_json(paths.validation_packet) if paths.validation_packet.exists() else {}
    validation.update(
        {
            "reviewer": reviewer.strip(),
            "reviewed_at": reviewed_at.strip(),
            "validation_status": VALIDATED_STATUS,
            "approval_status": APPROVED_STATUS,
            "evidence_complete": True,
            "human_validation_basis": "Reviewer xác nhận packet từ ảnh nguồn và correction lineage.",
        }
    )
    write_json(paths.validation_packet, validation)
    return {"approved": True, "errors": []}


def page_approval_errors(packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, item in enumerate(packet.get("field_decisions") or []):
        label = item.get("field_path") or f"field_decisions[{index}]"
        if item.get("decision") in PENDING_DECISIONS:
            errors.append(f"{label}: decision còn pending/unresolved")
        if item.get("approval_status") != APPROVED_STATUS:
            errors.append(f"{label}: chưa HUMAN_APPROVED")
        if not item.get("reviewer"):
            errors.append(f"{label}: thiếu reviewer")
        elif reviewer_is_ai(str(item.get("reviewer"))):
            errors.append(f"{label}: reviewer không được là AI/Codex")
        if not _valid_iso_datetime(str(item.get("reviewed_at") or "")):
            errors.append(f"{label}: reviewed_at không hợp lệ")
        if item.get("second_review_required") and not item.get("second_reviewer"):
            errors.append(f"{label}: thiếu second_reviewer")
        if item.get("parser_output_used_as_truth"):
            errors.append(f"{label}: parser output bị dùng làm truth")
    return errors


def append_lineage_record(
    benchmark_dir: Path,
    *,
    packet: dict[str, Any],
    decision_record: dict[str, Any],
) -> dict[str, Any] | None:
    new_value = str(decision_record.get("human_entered_value") or "").strip()
    old_value = str(decision_record.get("old_v1_value") or "")
    if not new_value or new_value == old_value:
        return None
    reviewer = str(decision_record.get("reviewer") or "")
    reviewed_at = str(decision_record.get("reviewed_at") or "")
    _validate_human_review_fields(reviewer, reviewed_at)
    record = {
        "correction_id": make_record_id(
            "corr",
            packet.get("case_id"),
            packet.get("page_number"),
            decision_record.get("field_path"),
            old_value,
            new_value,
            reviewer,
            reviewed_at,
        ),
        "case_id": packet.get("case_id"),
        "page_number": packet.get("page_number"),
        "field_path": decision_record.get("field_path"),
        "old_benchmark": "extraction_v1",
        "old_value": old_value,
        "new_value": new_value,
        "defect_type": decision_record.get("encoding_class"),
        "source_evidence": packet.get("source_page_evidence"),
        "parser_output_used_as_truth": False,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "second_reviewer": decision_record.get("second_reviewer"),
        "approval_status": APPROVED_STATUS,
        "old_value_sha256": sha256_text(old_value),
        "new_value_sha256": sha256_text(new_value),
    }
    record["record_sha256"] = _lineage_record_sha(record)
    lineage_path = benchmark_dir / "correction_lineage.jsonl"
    rows = load_jsonl(lineage_path)
    if any(row.get("correction_id") == record["correction_id"] for row in rows):
        return None
    rows.append(record)
    write_jsonl(lineage_path, rows)
    return record


def apply_approved_corrections_to_manifest(benchmark_dir: Path) -> dict[str, Any]:
    manifest_path = benchmark_dir / "manifest.json"
    manifest = read_json(manifest_path)
    corrections: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    case_id = load_case_id(benchmark_dir)
    workspace = benchmark_dir / "human_validation_workspace" / case_id
    for packet_path in sorted(workspace.glob("page_*/adjudication_packet.json")):
        packet = read_json(packet_path)
        for decision in packet.get("field_decisions") or []:
            if decision.get("approval_status") != APPROVED_STATUS:
                continue
            if decision.get("decision") not in CORRECTION_DECISIONS:
                skipped.append(
                    {
                        "field_path": decision.get("field_path"),
                        "reason": "decision_does_not_change_ground_truth",
                    }
                )
                continue
            new_value = str(decision.get("human_entered_value") or "").strip()
            old_value = str(decision.get("old_v1_value") or "")
            if not new_value or new_value == old_value:
                skipped.append(
                    {
                        "field_path": decision.get("field_path"),
                        "reason": "no_value_change",
                    }
                )
                continue
            field_path = str(decision.get("field_path") or "")
            existing = corrections.get(field_path)
            if existing and existing["new_value"] != new_value:
                errors.append(
                    {
                        "field_path": field_path,
                        "reason": "conflicting_human_values",
                        "values": [existing["new_value"], new_value],
                    }
                )
                continue
            corrections[field_path] = {
                "field_path": field_path,
                "old_value": old_value,
                "new_value": new_value,
            }
    applied: list[dict[str, Any]] = []
    manifest_written = False
    if errors:
        return {
            "applied_count": 0,
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "applied": applied,
            "skipped": skipped,
            "errors": errors,
            "manifest_written": manifest_written,
        }
    key_aliases = _row_key_aliases(corrections.values())
    for correction in sorted(corrections.values(), key=_correction_sort_key):
        try:
            apply_value_to_manifest(
                manifest,
                str(correction["field_path"]),
                str(correction["new_value"]),
                key_aliases=key_aliases,
            )
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            errors.append(
                {
                    "field_path": correction["field_path"],
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            applied.append(correction)
    if applied and not errors:
        write_json(manifest_path, manifest)
        write_inventory(benchmark_dir, benchmark_dir / "encoding_inventory.json")
        manifest_written = True
    return {
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "manifest_written": manifest_written,
    }


def find_correction_conflicts(benchmark_dir: Path) -> list[dict[str, Any]]:
    case_id = load_case_id(benchmark_dir)
    workspace = benchmark_dir / "human_validation_workspace" / case_id
    by_path: dict[str, list[dict[str, Any]]] = {}
    for packet_path in sorted(workspace.glob("page_*/adjudication_packet.json")):
        packet = read_json(packet_path)
        for decision in packet.get("field_decisions") or []:
            if decision.get("approval_status") != APPROVED_STATUS:
                continue
            if decision.get("decision") not in CORRECTION_DECISIONS:
                continue
            new_value = str(decision.get("human_entered_value") or "").strip()
            old_value = str(decision.get("old_v1_value") or "")
            if not new_value or new_value == old_value:
                continue
            field_path = str(decision.get("field_path") or "")
            by_path.setdefault(field_path, []).append(
                {
                    "page": packet.get("page_number"),
                    "finding_id": decision.get("finding_id"),
                    "field_path": field_path,
                    "human_entered_value": new_value,
                    "decision": decision.get("decision"),
                    "reviewer": decision.get("reviewer"),
                    "reviewed_at": decision.get("reviewed_at"),
                }
            )

    conflicts: list[dict[str, Any]] = []
    for field_path, decisions in by_path.items():
        values = []
        for decision in decisions:
            value = decision["human_entered_value"]
            if value not in values:
                values.append(value)
        if len(values) > 1:
            conflicts.append(
                {
                    "field_path": field_path,
                    "values": values,
                    "decisions": decisions,
                }
            )
    return conflicts


def apply_value_to_manifest(
    manifest: dict[str, Any],
    field_path: str,
    new_value: str,
    *,
    key_aliases: dict[tuple[int, int, int, str], str] | None = None,
) -> None:
    if match := TEXT_PATH_RE.match(field_path):
        case_index, text_index = (int(match.group(1)), int(match.group(2)))
        manifest["cases"][case_index]["expected_text"][text_index]["text"] = new_value
        return
    if match := COLUMN_PATH_RE.match(field_path):
        case_index, table_index, column_index = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        manifest["cases"][case_index]["expected_tables"][table_index]["columns"][column_index] = (
            new_value
        )
        return
    if match := ROW_KEY_PATH_RE.match(field_path):
        case_index, table_index, row_index = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        old_key = match.group(4)
        row = manifest["cases"][case_index]["expected_tables"][table_index]["rows"][row_index]
        if old_key not in row:
            if new_value in row:
                return
            equivalent_key = _single_semantic_equivalent_key(row, old_key, new_value)
            if equivalent_key is None:
                raise KeyError(old_key)
            _rename_row_key(row, equivalent_key, new_value)
            return
        if new_value != old_key:
            _rename_row_key(row, old_key, new_value)
        return
    if match := CELL_PATH_RE.match(field_path):
        case_index, table_index, row_index = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        key = match.group(4)
        row = manifest["cases"][case_index]["expected_tables"][table_index]["rows"][row_index]
        actual_key = key
        if actual_key not in row and key_aliases:
            actual_key = key_aliases.get((case_index, table_index, row_index, key), key)
        if actual_key not in row:
            raise KeyError(key)
        row[actual_key] = new_value
        return
    raise ValueError(f"Không hỗ trợ field_path: {field_path}")


def _rename_row_key(row: dict[str, Any], old_key: str, new_key: str) -> None:
    if old_key == new_key:
        return
    old_cell_value = row.pop(old_key)
    if new_key in row:
        if not str(row.get(new_key) or "").strip() and old_cell_value:
            row[new_key] = old_cell_value
        return
    row[new_key] = old_cell_value


def _single_semantic_equivalent_key(
    row: dict[str, Any],
    old_key: str,
    new_key: str,
) -> str | None:
    signatures = {
        signature
        for signature in (semantic_signature(old_key), semantic_signature(new_key))
        if signature
    }
    if not signatures:
        return None
    candidates = [
        key for key in row if key != new_key and semantic_signature(str(key)) in signatures
    ]
    return str(candidates[0]) if len(candidates) == 1 else None


def reviewer_is_ai(value: str) -> bool:
    folded = value.strip().lower()
    return any(marker in folded for marker in AI_REVIEWER_MARKERS)


def _find_decision(packet: dict[str, Any], finding_id: str) -> dict[str, Any]:
    for item in packet.get("field_decisions") or []:
        if item.get("finding_id") == finding_id:
            return item
    raise KeyError(finding_id)


def _decision_changes_value(decision_record: dict[str, Any]) -> bool:
    if decision_record.get("decision") not in CORRECTION_DECISIONS:
        return False
    new_value = str(decision_record.get("human_entered_value") or "").strip()
    old_value = str(decision_record.get("old_v1_value") or "")
    return bool(new_value and new_value != old_value)


def _row_key_aliases(corrections: Iterable[dict[str, Any]]) -> dict[tuple[int, int, int, str], str]:
    aliases: dict[tuple[int, int, int, str], str] = {}
    for correction in corrections:
        field_path = str(correction.get("field_path") or "")
        match = ROW_KEY_PATH_RE.match(field_path)
        if not match:
            continue
        case_index, table_index, row_index = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        aliases[(case_index, table_index, row_index, match.group(4))] = str(
            correction.get("new_value") or ""
        )
    return aliases


def _correction_sort_key(correction: dict[str, Any]) -> tuple[int, str]:
    field_path = str(correction.get("field_path") or "")
    if COLUMN_PATH_RE.match(field_path):
        return (0, field_path)
    if ROW_KEY_PATH_RE.match(field_path):
        return (1, field_path)
    if TEXT_PATH_RE.match(field_path):
        return (2, field_path)
    return (3, field_path)


def _lineage_record_sha(record: dict[str, Any]) -> str:
    unsigned = dict(record)
    unsigned.pop("record_sha256", None)
    return make_record_id(
        "lineage",
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True),
        length=64,
    ).removeprefix("lineage_")


def _stamp_packet_hash(packet: dict[str, Any]) -> None:
    unsigned = dict(packet)
    unsigned["packet_sha256"] = None
    packet["packet_sha256"] = sha256_json(unsigned)


def _validate_human_review_fields(reviewer: str, reviewed_at: str) -> None:
    if not reviewer.strip():
        raise ValueError("Thiếu reviewer.")
    if reviewer_is_ai(reviewer):
        raise ValueError("Reviewer không được là AI/Codex/assistant.")
    if not _valid_iso_datetime(reviewed_at):
        raise ValueError("reviewed_at phải là ISO-8601.")


def _valid_iso_datetime(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _page_decision(packet: dict[str, Any]) -> str:
    if any(_decision_changes_value(item) for item in packet.get("field_decisions") or []):
        return "CONFIRMED_GT_ENCODING_DEFECT"
    return "CONFIRMED_V1_VALUE_CORRECT"


def _read_optional_json(path: Path) -> dict[str, Any]:
    return read_json(path) if path.exists() else {}


def _read_optional_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""
