from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.adjudication_preflight import (
    APPROVED_STATUS,
    VALIDATED_STATUS,
    run_preflight,
)
from app.pipeline.documents.extraction.evaluation.adjudication_workspace import (
    ADJUDICATION_POLICY_VERSION,
    workspace_bundle_checksum,
)
from app.pipeline.documents.extraction.evaluation.approved_bundle_integrity import (
    HASH_CONTRACT_VERSION,
    legacy_bundle_checksum_v1,
    write_integrity_manifest,
)
from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    read_json,
    sha256_file,
    utc_now_iso,
    write_json,
)
from app.pipeline.documents.extraction.evaluation.scoring_normalization import POLICY_VERSION


def promote_benchmark(
    benchmark_dir: Path,
    *,
    previous_approved_bundle_checksum: str | None = None,
    pre_reconciliation_bundle_checksum: str | None = None,
    reconciliation_reason: str | None = None,
    historical_checksums: list[str] | None = None,
) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    preflight = run_preflight(benchmark_dir)
    report_path = benchmark_dir / "reports" / "promotion_preflight_result.json"
    write_json(report_path, preflight)
    if not preflight["passed"]:
        return {
            "promotion_status": "BLOCKED_BY_PREFLIGHT",
            "promoted": False,
            "preflight": preflight,
            "approved_bundle": None,
        }

    manifest_path = benchmark_dir / "manifest.json"
    manifest = read_json(manifest_path)
    _mark_manifest_approved(manifest)
    write_json(manifest_path, manifest)

    approved_dir = benchmark_dir / "approved_bundle"
    approved_dir.mkdir(parents=True, exist_ok=True)
    write_json(approved_dir / "manifest.json", manifest)
    _copy_if_exists(
        benchmark_dir / "encoding_inventory.json", approved_dir / "encoding_inventory.json"
    )
    _copy_if_exists(
        benchmark_dir / "adjudication_policy.json", approved_dir / "adjudication_policy.json"
    )
    _copy_if_exists(
        benchmark_dir / "correction_lineage.jsonl", approved_dir / "correction_lineage.jsonl"
    )
    bundle_checksum = workspace_bundle_checksum(benchmark_dir)
    legacy_checksum = legacy_bundle_checksum_v1(benchmark_dir)
    metadata_path = approved_dir / "bundle_metadata.json"
    previous_metadata = read_json(metadata_path) if metadata_path.exists() else {}
    previous_canonical = previous_metadata.get(
        "canonical_approved_bundle_checksum"
    ) or previous_metadata.get("bundle_checksum")
    promoted_at = (
        previous_metadata.get("promoted_at")
        if previous_canonical == bundle_checksum
        else utc_now_iso()
    )
    history = list(previous_metadata.get("historical_approved_bundle_checksums") or [])
    history.extend(historical_checksums or [])
    if previous_canonical and previous_canonical != bundle_checksum:
        history.append(str(previous_canonical))
    history = list(dict.fromkeys(item for item in history if item))
    metadata = {
        "bundle_status": "IMMUTABLE_APPROVED",
        "bundle_checksum": bundle_checksum,
        "canonical_approved_bundle_checksum": bundle_checksum,
        "hash_contract_version": HASH_CONTRACT_VERSION,
        "legacy_bundle_checksum_v1": legacy_checksum,
        "manifest_sha256": sha256_file(manifest_path),
        "policy_version": ADJUDICATION_POLICY_VERSION,
        "scoring_normalization_version": POLICY_VERSION,
        "promoted_at": promoted_at or utc_now_iso(),
        "source_benchmark": str(benchmark_dir.as_posix()),
        "previous_approved_bundle_checksum": (
            previous_approved_bundle_checksum or previous_canonical
        ),
        "pre_reconciliation_bundle_checksum": (
            pre_reconciliation_bundle_checksum or previous_canonical
        ),
        "historical_approved_bundle_checksums": history,
        "reconciliation_reason": reconciliation_reason,
    }
    write_json(metadata_path, metadata)
    integrity_manifest = write_integrity_manifest(benchmark_dir)
    return {
        "promotion_status": "PROMOTED",
        "promoted": True,
        "preflight": preflight,
        "approved_bundle": str(approved_dir.as_posix()),
        "bundle_checksum": bundle_checksum,
        "canonical_approved_bundle_checksum": bundle_checksum,
        "approved_bundle_hash_contract_version": HASH_CONTRACT_VERSION,
        "legacy_bundle_checksum_v1": legacy_checksum,
        "integrity_manifest_sha256": integrity_manifest["manifest_payload_sha256"],
    }


def _mark_manifest_approved(manifest: dict[str, Any]) -> None:
    manifest["document_status"] = VALIDATED_STATUS
    manifest["approval_status"] = APPROVED_STATUS
    manifest["promoted_policy_version"] = ADJUDICATION_POLICY_VERSION
    manifest["promoted_scoring_normalization_version"] = POLICY_VERSION
    for case in manifest.get("cases", []):
        case["validation_status"] = VALIDATED_STATUS
        metadata = dict(case.get("metadata") or {})
        metadata.update(
            {
                "validation_status": VALIDATED_STATUS,
                "approval_status": APPROVED_STATUS,
                "evidence_complete": True,
                "promoted_from_adjudication": True,
                "adjudication_policy_version": ADJUDICATION_POLICY_VERSION,
                "scoring_normalization_policy_version": POLICY_VERSION,
            }
        )
        case["metadata"] = metadata


def _copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote a human-adjudicated extraction_v2 benchmark."
    )
    parser.add_argument("benchmark_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous-approved-bundle-checksum")
    parser.add_argument("--pre-reconciliation-bundle-checksum")
    parser.add_argument("--reconciliation-reason")
    parser.add_argument("--historical-checksum", action="append", default=[])
    args = parser.parse_args()
    result = promote_benchmark(
        args.benchmark_dir,
        previous_approved_bundle_checksum=args.previous_approved_bundle_checksum,
        pre_reconciliation_bundle_checksum=args.pre_reconciliation_bundle_checksum,
        reconciliation_reason=args.reconciliation_reason,
        historical_checksums=args.historical_checksum,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        write_json(args.output, result)
    else:
        print(text)
    return 0 if result["promoted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
