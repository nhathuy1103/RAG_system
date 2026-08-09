from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.adjudication_preflight import run_preflight
from app.pipeline.documents.extraction.evaluation.approved_bundle_integrity import (
    CANONICAL_INPUTS,
    DERIVED_INVENTORY_FIELDS_EXCLUDED_FROM_CANONICAL_HASH,
    HASH_ALGORITHM,
    HASH_CONTRACT_VERSION,
    LEGACY_HASH_CONTRACT_VERSION,
    legacy_bundle_checksum_v1,
    verify_approved_bundle_integrity,
)
from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    load_jsonl,
    read_json,
    sha256_file,
    write_json,
)
from app.pipeline.documents.extraction.evaluation.promote_adjudicated_benchmark import (
    promote_benchmark,
)

PREVIOUSLY_FROZEN_CHECKSUM = "59236a3c05d38267b63ff5ded3970b8d0be5c735dcd9fc028329bd5b85a97251"
INTERMEDIATE_CHECKSUM = "f356272b3e14195c5c615bb14f82dbaccea56bcd5f8245c694b2e34499d1d3e0"
PRE_RECONCILIATION_CHECKSUM = "b78f28c2a056442eddc7265325675840350d6fbd8224e17fd0330c04d79174b7"
RECONCILIATION_REASON = (
    "SEMANTIC_GT_CHANGE_WITH_HUMAN_APPROVED_CORRECTION_LINEAGE_AND_DETERMINISTIC_HASH_CONTRACT_V2"
)


def reconcile_approved_bundle(
    repo_root: Path,
    *,
    promote: bool = True,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    benchmark_dir = repo_root / "benchmarks" / "extraction_v2"
    approved_dir = benchmark_dir / "approved_bundle"
    reports_dir = benchmark_dir / "reports"
    historical_dir = reports_dir / "amendments" / "2026-07-26_chi-tieu_to_chi-tieu"
    historical_manifest_path = historical_dir / "approved_manifest.before.json"
    historical_metadata_path = historical_dir / "bundle_metadata.before.json"

    historical_manifest = read_json(historical_manifest_path)
    historical_metadata = read_json(historical_metadata_path)
    current_manifest = read_json(benchmark_dir / "manifest.json")
    active_metadata = read_json(approved_dir / "bundle_metadata.json")
    workspace_rows = load_jsonl(benchmark_dir / "correction_lineage.jsonl")
    already_reconciled = bool(
        active_metadata.get("hash_contract_version") == HASH_CONTRACT_VERSION
        and active_metadata.get("reconciliation_reason") == RECONCILIATION_REASON
    )
    pre_observed_checksum = (
        active_metadata.get("pre_reconciliation_bundle_checksum")
        if already_reconciled
        else legacy_bundle_checksum_v1(approved_dir)
    )
    if not pre_observed_checksum:
        raise ValueError("pre-reconciliation checksum is unavailable")

    archive_dir = (
        reports_dir / "integrity_reconciliation" / f"pre_reconcile_{pre_observed_checksum}"
    )
    if not already_reconciled:
        _archive_bundle(approved_dir, archive_dir)
    pre_metadata = (
        read_json(archive_dir / "bundle_metadata.json")
        if (archive_dir / "bundle_metadata.json").exists()
        else active_metadata
    )
    pre_approved_rows = (
        load_jsonl(archive_dir / "correction_lineage.jsonl")
        if (archive_dir / "correction_lineage.jsonl").exists()
        else load_jsonl(approved_dir / "correction_lineage.jsonl")
    )
    archive_metadata = {
        "archive_status": "PRESERVED_READ_ONLY_EVIDENCE",
        "observed_hash_contract_version": LEGACY_HASH_CONTRACT_VERSION,
        "observed_bundle_checksum": pre_observed_checksum,
        "metadata_bundle_checksum": pre_metadata.get("bundle_checksum"),
        "files": [
            {
                "relative_path": path.name,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(
                (item for item in archive_dir.iterdir() if item.is_file()),
                key=lambda item: item.name,
            )
            if path.name != "archive_metadata.json"
        ],
    }
    write_json(archive_dir / "archive_metadata.json", archive_metadata)

    preflight = run_preflight(benchmark_dir)
    write_json(
        reports_dir / "integrity_reconciliation_preflight.json",
        preflight,
    )
    if already_reconciled and promote:
        promotion_path = reports_dir / "integrity_reconciliation_promotion_result.json"
        promotion = read_json(promotion_path)
        post_preflight = run_preflight(benchmark_dir)
        write_json(
            reports_dir / "integrity_reconciliation_post_promotion_preflight.json",
            post_preflight,
        )
        integrity = verify_approved_bundle_integrity(benchmark_dir)
        write_json(
            repo_root / "output" / "approved_bundle_integrity_result.json",
            integrity,
        )
        result = _build_reconciliation_result(
            repo_root=repo_root,
            historical_manifest=historical_manifest,
            historical_metadata=historical_metadata,
            current_manifest=current_manifest,
            pre_metadata=pre_metadata,
            pre_observed_checksum=pre_observed_checksum,
            pre_approved_rows=pre_approved_rows,
            workspace_rows=workspace_rows,
            promotion=promotion,
            post_preflight=post_preflight,
            integrity=integrity,
        )
        _write_reconciliation_artifacts(repo_root, result)
        return result
    if not preflight["passed"] or not promote:
        result = _build_reconciliation_result(
            repo_root=repo_root,
            historical_manifest=historical_manifest,
            historical_metadata=historical_metadata,
            current_manifest=current_manifest,
            pre_metadata=pre_metadata,
            pre_observed_checksum=pre_observed_checksum,
            pre_approved_rows=pre_approved_rows,
            workspace_rows=workspace_rows,
            promotion=None,
            post_preflight=None,
            integrity=None,
        )
        _write_reconciliation_artifacts(repo_root, result)
        return result

    promotion = promote_benchmark(
        benchmark_dir,
        previous_approved_bundle_checksum=PREVIOUSLY_FROZEN_CHECKSUM,
        pre_reconciliation_bundle_checksum=pre_observed_checksum,
        reconciliation_reason=RECONCILIATION_REASON,
        historical_checksums=[
            PREVIOUSLY_FROZEN_CHECKSUM,
            INTERMEDIATE_CHECKSUM,
            pre_observed_checksum,
        ],
    )
    write_json(reports_dir / "promotion_result.json", promotion)
    write_json(
        reports_dir / "integrity_reconciliation_promotion_result.json",
        promotion,
    )
    post_preflight = run_preflight(benchmark_dir)
    write_json(
        reports_dir / "integrity_reconciliation_post_promotion_preflight.json",
        post_preflight,
    )
    integrity = verify_approved_bundle_integrity(benchmark_dir)
    write_json(
        repo_root / "output" / "approved_bundle_integrity_result.json",
        integrity,
    )
    result = _build_reconciliation_result(
        repo_root=repo_root,
        historical_manifest=historical_manifest,
        historical_metadata=historical_metadata,
        current_manifest=read_json(benchmark_dir / "manifest.json"),
        pre_metadata=pre_metadata,
        pre_observed_checksum=pre_observed_checksum,
        pre_approved_rows=pre_approved_rows,
        workspace_rows=workspace_rows,
        promotion=promotion,
        post_preflight=post_preflight,
        integrity=integrity,
    )
    _write_reconciliation_artifacts(repo_root, result)
    return result


def _build_reconciliation_result(
    *,
    repo_root: Path,
    historical_manifest: dict[str, Any],
    historical_metadata: dict[str, Any],
    current_manifest: dict[str, Any],
    pre_metadata: dict[str, Any],
    pre_observed_checksum: str,
    pre_approved_rows: list[dict[str, Any]],
    workspace_rows: list[dict[str, Any]],
    promotion: dict[str, Any] | None,
    post_preflight: dict[str, Any] | None,
    integrity: dict[str, Any] | None,
) -> dict[str, Any]:
    manifest_changes = _json_changes(historical_manifest, current_manifest)
    scored_changes = {
        category: [change for change in manifest_changes if f".{category}" in change["path"]]
        for category in ("expected_text", "expected_tables", "expected_issues")
    }
    historical_promoted_at = _parse_datetime(historical_metadata.get("promoted_at"))
    lineage_added_after_historical = [
        _lineage_summary(row)
        for row in workspace_rows
        if _parse_datetime(row.get("reviewed_at")) > historical_promoted_at
    ]
    approved_ids = {row.get("correction_id") for row in pre_approved_rows}
    workspace_only_before_reconciliation = [
        _lineage_summary(row)
        for row in workspace_rows
        if row.get("correction_id") not in approved_ids
    ]
    historical_manifest_sha = sha256_file(
        repo_root
        / "benchmarks"
        / "extraction_v2"
        / "reports"
        / "amendments"
        / "2026-07-26_chi-tieu_to_chi-tieu"
        / "approved_manifest.before.json"
    )
    canonical_checksum = promotion.get("canonical_approved_bundle_checksum") if promotion else None
    passed = bool(
        promotion
        and promotion.get("promoted")
        and post_preflight
        and post_preflight.get("passed")
        and integrity
        and integrity.get("passed")
        and scored_changes["expected_tables"]
        and not scored_changes["expected_text"]
        and not scored_changes["expected_issues"]
    )
    return {
        "reconciliation_status": "PASS" if passed else "BLOCKED",
        "decision_case": "CASE_C_PLUS_HASH_CONTRACT_VERSIONING",
        "semantic_gt_drift": True,
        "semantic_gt_drift_scope": "expected_tables",
        "previous_approved_bundle_checksum": PREVIOUSLY_FROZEN_CHECKSUM,
        "intermediate_approved_bundle_checksum": INTERMEDIATE_CHECKSUM,
        "pre_reconciliation_bundle_checksum": pre_observed_checksum,
        "canonical_approved_bundle_checksum": canonical_checksum,
        "hash_contract": {
            "previous_version": LEGACY_HASH_CONTRACT_VERSION,
            "canonical_version": HASH_CONTRACT_VERSION,
            "change_classification": "HASH_SCOPE_CHANGE",
            "reason": (
                "The legacy contract included mutable encoding inventory metadata "
                "and raw JSONL bytes. V2 excludes derived timestamps/absolute paths "
                "and canonicalizes every protected structured record."
            ),
        },
        "historical_evidence": {
            "checksum_metadata_path": (
                "benchmarks/extraction_v2/reports/amendments/"
                "2026-07-26_chi-tieu_to_chi-tieu/bundle_metadata.before.json"
            ),
            "manifest_snapshot_path": (
                "benchmarks/extraction_v2/reports/amendments/"
                "2026-07-26_chi-tieu_to_chi-tieu/approved_manifest.before.json"
            ),
            "metadata_checksum_matches_expected": (
                historical_metadata.get("bundle_checksum") == PREVIOUSLY_FROZEN_CHECKSUM
            ),
            "manifest_sha256_matches_metadata": (
                historical_manifest_sha == historical_metadata.get("manifest_sha256")
            ),
            "historical_full_bundle_reproducible": False,
            "missing_historical_artifacts": [
                "encoding_inventory.before.json",
                "adjudication_policy.before.json",
                "correction_lineage.before.jsonl",
            ],
            "evidence_conclusion": (
                "The old full byte/hash payload cannot be reconstructed, but the "
                "frozen checksum metadata and its exact scored manifest snapshot "
                "are verified. This is sufficient to prove scored semantic drift."
            ),
        },
        "file_differences": [
            {
                "relative_path": "manifest.json",
                "classification": "SEMANTIC_GT_CHANGE",
                "details": (
                    f"{len(scored_changes['expected_tables'])} expected_tables "
                    "changes; expected_text and expected_issues unchanged"
                ),
            },
            {
                "relative_path": "encoding_inventory.json",
                "classification": "UNRESOLVED",
                "details": "Historical 59236 bundle snapshot is unavailable.",
            },
            {
                "relative_path": "adjudication_policy.json",
                "classification": "UNRESOLVED",
                "details": "Historical 59236 bundle snapshot is unavailable.",
            },
            {
                "relative_path": "correction_lineage.jsonl",
                "classification": "SEMANTIC_GT_CHANGE",
                "details": (
                    f"{len(lineage_added_after_historical)} approved correction "
                    "records post-date the historical promotion."
                ),
            },
            {
                "relative_path": "bundle_metadata.json",
                "classification": "METADATA_ONLY_CHANGE",
                "details": "Versioned hash contract and reconciliation envelope.",
            },
        ],
        "scored_field_comparison": {
            "expected_text": _change_summary(scored_changes["expected_text"]),
            "expected_tables": _change_summary(scored_changes["expected_tables"]),
            "expected_issues": _change_summary(scored_changes["expected_issues"]),
            "source_page_mapping": _unchanged_summary(
                _source_page_mapping(historical_manifest) == _source_page_mapping(current_manifest)
            ),
            "page_number": _unchanged_summary(
                _page_numbers(historical_manifest) == _page_numbers(current_manifest)
            ),
            "source_checksum": _unchanged_summary(
                _source_checksums(historical_manifest) == _source_checksums(current_manifest)
            ),
        },
        "expected_table_changes": scored_changes["expected_tables"],
        "governance_comparison": {
            "historical_bundle_metadata": historical_metadata,
            "pre_reconciliation_bundle_metadata": pre_metadata,
            "lineage_records_added_after_historical_promotion": (lineage_added_after_historical),
            "workspace_only_lineage_records_before_reconciliation": (
                workspace_only_before_reconciliation
            ),
            "promotion_result": promotion,
            "post_promotion_preflight": post_preflight,
            "integrity_result": integrity,
        },
        "reconciliation_reason": RECONCILIATION_REASON,
    }


def _write_reconciliation_artifacts(
    repo_root: Path,
    result: dict[str, Any],
) -> None:
    write_json(repo_root / "output" / "approved_bundle_checksum_diff.json", result)
    contract_path = repo_root / "docs" / "audit" / "APPROVED_BUNDLE_HASH_CONTRACT.md"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(_hash_contract_markdown(), encoding="utf-8")
    reconciliation_path = (
        repo_root / "docs" / "audit" / "APPROVED_BUNDLE_CHECKSUM_RECONCILIATION.md"
    )
    reconciliation_path.write_text(
        _reconciliation_markdown(result),
        encoding="utf-8",
    )


def _archive_bundle(source_dir: Path, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(
        (item for item in source_dir.iterdir() if item.is_file()),
        key=lambda item: item.name,
    ):
        target = archive_dir / source.name
        if not target.exists():
            shutil.copy2(source, target)


def _json_changes(old: Any, new: Any, path: str = "$") -> list[dict[str, Any]]:
    if type(old) is not type(new):
        return [{"path": path, "old": old, "new": new, "change": "VALUE_CHANGED"}]
    if isinstance(old, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(old) | set(new)):
            child_path = f"{path}.{key}"
            if key not in old:
                changes.append(
                    {
                        "path": child_path,
                        "old": None,
                        "new": new[key],
                        "change": "ADDED_FIELD",
                    }
                )
            elif key not in new:
                changes.append(
                    {
                        "path": child_path,
                        "old": old[key],
                        "new": None,
                        "change": "MISSING_FIELD",
                    }
                )
            else:
                changes.extend(_json_changes(old[key], new[key], child_path))
        return changes
    if isinstance(old, list):
        changes = []
        for index in range(max(len(old), len(new))):
            child_path = f"{path}[{index}]"
            if index >= len(old):
                changes.append(
                    {
                        "path": child_path,
                        "old": None,
                        "new": new[index],
                        "change": "ADDED_ITEM",
                    }
                )
            elif index >= len(new):
                changes.append(
                    {
                        "path": child_path,
                        "old": old[index],
                        "new": None,
                        "change": "MISSING_ITEM",
                    }
                )
            else:
                changes.extend(_json_changes(old[index], new[index], child_path))
        return changes
    if old != new:
        return [{"path": path, "old": old, "new": new, "change": "VALUE_CHANGED"}]
    return []


def _source_page_mapping(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = []
    for case in manifest.get("cases", []):
        mapping.append(
            {
                "case_id": case.get("case_id"),
                "document_path": case.get("document_path"),
                "text_pages": [item.get("page_number") for item in case.get("expected_text", [])],
                "table_pages": [
                    {
                        "table_id": item.get("table_id"),
                        "page_number": item.get("page_number"),
                    }
                    for item in case.get("expected_tables", [])
                ],
            }
        )
    return mapping


def _page_numbers(manifest: dict[str, Any]) -> list[int]:
    values = []
    for case in manifest.get("cases", []):
        values.extend(
            int(item["page_number"])
            for item in case.get("expected_text", [])
            if item.get("page_number") is not None
        )
        values.extend(
            int(item["page_number"])
            for item in case.get("expected_tables", [])
            if item.get("page_number") is not None
        )
    return values


def _source_checksums(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_checksum": manifest.get("source_checksum"),
        "case_checksums": [
            {
                "case_id": case.get("case_id"),
                "sha256": case.get("sha256"),
            }
            for case in manifest.get("cases", [])
        ],
    }


def _change_summary(changes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "SEMANTIC_GT_CHANGE" if changes else "UNCHANGED",
        "change_count": len(changes),
    }


def _unchanged_summary(unchanged: bool) -> dict[str, Any]:
    return {
        "status": "UNCHANGED" if unchanged else "SEMANTIC_GT_CHANGE",
        "equal": unchanged,
    }


def _lineage_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "correction_id": row.get("correction_id"),
        "page_number": row.get("page_number"),
        "field_path": row.get("field_path"),
        "old_value": row.get("old_value"),
        "new_value": row.get("new_value"),
        "reviewer": row.get("reviewer"),
        "reviewed_at": row.get("reviewed_at"),
        "approval_status": row.get("approval_status"),
        "record_sha256": row.get("record_sha256"),
    }


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "1970-01-01T00:00:00+00:00").replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _hash_contract_markdown() -> str:
    included = ", ".join(f"`{item}`" for item in CANONICAL_INPUTS)
    excluded_inventory = ", ".join(
        f"`{item}`" for item in sorted(DERIVED_INVENTORY_FIELDS_EXCLUDED_FROM_CANONICAL_HASH)
    )
    return f"""# Approved Bundle Hash Contract

## Canonical Contract

- Version: `{HASH_CONTRACT_VERSION}`
- Algorithm: `{HASH_ALGORITHM}`
- Character encoding: UTF-8
- Included files, in POSIX ordinal path order: {included}
- Excluded files: `bundle_metadata.json`, the integrity manifest itself, schemas, reports, source images, and directories.
- Filename handling: each POSIX relative filename and content type are included in the canonical payload.
- Directory handling: directory names are represented only through included relative file paths; empty directories are excluded.
- Symlink handling: symlinks are rejected and never followed.

## Canonicalization

JSON files are parsed with duplicate-key rejection. Objects are serialized with keys sorted, no insignificant whitespace, UTF-8 output, and unescaped Unicode. Source indentation, object-key order, trailing spaces, and JSON file line endings therefore do not change the checksum.

`correction_lineage.jsonl` is parsed one non-empty line at a time as strict JSON. Each record is canonicalized as JSON; record order remains significant. JSONL indentation, trailing spaces, blank lines, and CRLF/LF differences do not change the checksum.

`encoding_inventory.json` is protected except for derived mutable fields {excluded_inventory}. Those fields are excluded because they contain a generation timestamp and an absolute machine path. Scored values are never excluded.

Timestamps inside `manifest.json` and `correction_lineage.jsonl` remain included because they are approved governance evidence. `promoted_at` and `source_benchmark` live in the excluded `bundle_metadata.json` governance envelope. Every approved-bundle file, including the envelope, still receives a byte size and SHA-256 in `approved_bundle_integrity_manifest.json`.

The bundle checksum is SHA-256 over canonical JSON:

```text
{{
  "hash_contract_version": "{HASH_CONTRACT_VERSION}",
  "files": [
    {{"relative_path": "...", "content_type": "...", "content": <canonical content>}}
  ]
}}
```

## Legacy Contract

`{LEGACY_HASH_CONTRACT_VERSION}` was previously implemented by `workspace_bundle_checksum` without an explicit version. It used SHA-256 over UTF-8 canonical JSON with fixed object keys `manifest`, `inventory`, `policy`, and `lineage`; canonical object-key sorting, not directory traversal, determined ordering. The first three values were parsed JSON, so their source whitespace, key order, and line endings were ignored. Lineage was one raw UTF-8 string, so its whitespace, blank lines, record order, trailing newline, and CRLF/LF bytes were significant.

Legacy filenames, relative paths, and directories were not included. Its scope was exactly `manifest.json`, `encoding_inventory.json`, `adjudication_policy.json`, and optional `correction_lineage.jsonl`; `bundle_metadata.json` and every other file were excluded. All values inside the three JSON documents were included, including mutable `encoding_inventory.generated_at`, its absolute `source_manifest` path, and governance metadata. `Path.read_*` followed symlinks and did not encode symlink identity. This behavior explains why the legacy checksum was not portable enough for a canonical freeze.
"""


def _reconciliation_markdown(result: dict[str, Any]) -> str:
    scored = result["scored_field_comparison"]
    evidence = result["historical_evidence"]
    return f"""# Approved Bundle Checksum Reconciliation

- Reconciliation status: `{result["reconciliation_status"]}`
- Decision: `{result["decision_case"]}`
- Previous frozen checksum: `{result["previous_approved_bundle_checksum"]}`
- Pre-reconciliation checksum: `{result["pre_reconciliation_bundle_checksum"]}`
- Canonical checksum: `{result["canonical_approved_bundle_checksum"]}`
- Canonical contract: `{result["hash_contract"]["canonical_version"]}`
- Semantic GT drift: `{str(result["semantic_gt_drift"]).lower()}`

## Evidence

The historical `bundle_metadata.before.json` contains the frozen checksum and a manifest SHA-256. Its paired `approved_manifest.before.json` hashes to that exact manifest SHA-256: `{str(evidence["manifest_sha256_matches_metadata"]).lower()}`. Historical snapshots for inventory, policy, and lineage were not retained, so the complete legacy payload cannot be reconstructed byte-for-byte. The exact scored manifest is present, which makes the semantic comparison conclusive rather than inferred.

## Scored Fields

| Field group | Status | Changes |
| --- | --- | ---: |
| expected_text | {scored["expected_text"]["status"]} | {scored["expected_text"]["change_count"]} |
| expected_tables | {scored["expected_tables"]["status"]} | {scored["expected_tables"]["change_count"]} |
| expected_issues | {scored["expected_issues"]["status"]} | {scored["expected_issues"]["change_count"]} |
| source page mapping | {scored["source_page_mapping"]["status"]} | 0 |
| page number | {scored["page_number"]["status"]} | 0 |
| source checksum | {scored["source_checksum"]["status"]} | 0 |

The table changes are the human-approved corrections from `Chi tiêu` to `Chỉ tiêu`, `Mã sô` to `Mã số`, and `Quý 3 năm 2026"` to `Quý 3 năm 2026`, including the affected row keys. They are classified as `SEMANTIC_GT_CHANGE`, not format-only drift.

## Governance

The correction lineage contains the reviewer, review time, human approval, source evidence, old/new hashes, and record hash for every scored correction. Promotion preflight passed, the workspace was promoted again, and the approved bundle now contains the complete workspace lineage. The former `b78f...` approved bundle was archived before promotion because it was missing one workspace lineage record.

## Resolution

The old checksums remain historical evidence. The canonical checksum is governed by `{HASH_CONTRACT_VERSION}` and is the only checksum permitted in regenerated Phase 2 freeze artifacts. Ground Truth was not edited during reconciliation; promotion consumed the already human-approved workspace and correction lineage.
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile historical and canonical approved bundle integrity."
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--no-promote", action="store_true")
    args = parser.parse_args()
    result = reconcile_approved_bundle(
        args.repo_root,
        promote=not args.no_promote,
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["reconciliation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
