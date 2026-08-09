from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    canonical_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
    sha256_json,
    write_json,
)

HASH_ALGORITHM = "SHA-256"
HASH_CONTRACT_VERSION = "approved_bundle_hash_v2"
LEGACY_HASH_CONTRACT_VERSION = "legacy_workspace_bundle_unversioned_v1"
INTEGRITY_MANIFEST_VERSION = "approved_bundle_integrity_manifest_v1"

CANONICAL_INPUTS = (
    "adjudication_policy.json",
    "correction_lineage.jsonl",
    "encoding_inventory.json",
    "manifest.json",
)
JSON_INPUTS = {
    "adjudication_policy.json",
    "encoding_inventory.json",
    "manifest.json",
}
DERIVED_INVENTORY_FIELDS_EXCLUDED_FROM_CANONICAL_HASH = {
    "generated_at",
    "source_manifest",
}

FILE_CLASSIFICATION = {
    "manifest.json": ("scored_ground_truth_and_governance", True),
    "encoding_inventory.json": ("derived_encoding_evidence", False),
    "adjudication_policy.json": ("governance_policy", False),
    "correction_lineage.jsonl": ("correction_lineage_governance", False),
    "bundle_metadata.json": ("governance_envelope", False),
}

PHASE2_JSON_ARTIFACTS = (
    "benchmarks/extraction_v2/pre_phase2_baseline_freeze.json",
    "benchmarks/page_routing_v1/results_static.json",
    "benchmarks/page_routing_v1/results_shadow.json",
    "benchmarks/page_routing_v1/results_adaptive_run_1.json",
    "benchmarks/page_routing_v1/results_adaptive_run_2.json",
    "benchmarks/page_routing_v1/results_adaptive_run_3.json",
    "benchmarks/page_routing_v1/results_static_vs_adaptive.json",
    "output/phase2_static_extraction_benchmark.json",
    "output/phase2_shadow_extraction_benchmark.json",
    "output/phase2_adaptive_extraction_run_1.json",
    "output/phase2_adaptive_extraction_run_2.json",
    "output/phase2_adaptive_extraction_run_3.json",
    "output/phase2_acceptance.json",
    "benchmarks/page_routing_v1/phase2_freeze_metadata.json",
)

PHASE2_MARKDOWN_ARTIFACTS = (
    "docs/audit/PHASE_2_CLOSURE_REPORT.md",
    "docs/audit/PHASE_3_HANDOFF.md",
)


def approved_bundle_checksum(bundle_dir: Path) -> str:
    """Return the canonical v2 checksum for an approved bundle directory."""
    return sha256_bytes(canonical_json_bytes(canonical_bundle_payload(bundle_dir)))


def canonical_bundle_payload(bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    files: list[dict[str, Any]] = []
    for relative_path in CANONICAL_INPUTS:
        path = bundle_dir / relative_path
        _require_regular_file(path, relative_path)
        files.append(
            {
                "relative_path": relative_path,
                "content_type": (
                    "application/x-ndjson"
                    if relative_path.endswith(".jsonl")
                    else "application/json"
                ),
                "content": _canonical_file_content(path, relative_path),
            }
        )
    return {
        "hash_contract_version": HASH_CONTRACT_VERSION,
        "files": files,
    }


def legacy_bundle_checksum_v1(bundle_dir: Path) -> str:
    """Reproduce the formerly unversioned workspace_bundle_checksum contract."""
    bundle_dir = bundle_dir.resolve()
    payload = {
        "manifest": read_json(bundle_dir / "manifest.json"),
        "inventory": read_json(bundle_dir / "encoding_inventory.json"),
        "policy": read_json(bundle_dir / "adjudication_policy.json"),
        "lineage": (bundle_dir / "correction_lineage.jsonl").read_text(encoding="utf-8")
        if (bundle_dir / "correction_lineage.jsonl").exists()
        else "",
    }
    return sha256_json(payload)


def build_integrity_manifest(benchmark_dir: Path) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    bundle_dir = benchmark_dir / "approved_bundle"
    metadata_path = bundle_dir / "bundle_metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {}
    files = []
    for path in sorted(
        (item for item in bundle_dir.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(bundle_dir).as_posix(),
    ):
        relative_path = path.relative_to(bundle_dir).as_posix()
        if path.is_symlink():
            raise ValueError(f"approved bundle symlink is forbidden: {relative_path}")
        category, scored = FILE_CLASSIFICATION.get(
            relative_path,
            ("unclassified_bundle_file", False),
        )
        files.append(
            {
                "relative_path": relative_path,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
                "semantic_category": category,
                "scored": scored,
                "scored_status": "SCORED_CONTENT_PRESENT" if scored else "NON_SCORED",
                "included_in_canonical_checksum": relative_path in CANONICAL_INPUTS,
            }
        )
    payload = {
        "manifest_version": INTEGRITY_MANIFEST_VERSION,
        "hash_contract_version": HASH_CONTRACT_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "bundle_root": "benchmarks/extraction_v2/approved_bundle",
        "canonical_approved_bundle_checksum": approved_bundle_checksum(bundle_dir),
        "previous_approved_bundle_checksum": metadata.get("previous_approved_bundle_checksum"),
        "pre_reconciliation_bundle_checksum": metadata.get("pre_reconciliation_bundle_checksum"),
        "reconciliation_reason": metadata.get("reconciliation_reason"),
        "path_ordering": "relative_path_posix_ordinal",
        "files": files,
    }
    payload["manifest_payload_sha256"] = sha256_json(payload)
    return payload


def write_integrity_manifest(benchmark_dir: Path) -> dict[str, Any]:
    payload = build_integrity_manifest(benchmark_dir)
    write_json(
        benchmark_dir.resolve() / "approved_bundle_integrity_manifest.json",
        payload,
    )
    return payload


def verify_approved_bundle_integrity(
    benchmark_dir: Path,
    *,
    compare_workspace: bool = True,
    require_integrity_manifest: bool = True,
) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    bundle_dir = benchmark_dir / "approved_bundle"
    metadata_path = bundle_dir / "bundle_metadata.json"
    errors: list[str] = []
    canonical_checksum: str | None = None
    legacy_checksum: str | None = None

    try:
        canonical_checksum = approved_bundle_checksum(bundle_dir)
        legacy_checksum = legacy_bundle_checksum_v1(bundle_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"bundle_read_failed:{exc}")

    metadata = read_json(metadata_path) if metadata_path.exists() else {}
    if not metadata:
        errors.append("missing_bundle_metadata")
    else:
        if metadata.get("hash_contract_version") != HASH_CONTRACT_VERSION:
            errors.append(
                "hash_contract_version_mismatch:"
                f"{metadata.get('hash_contract_version')}:{HASH_CONTRACT_VERSION}"
            )
        for field in ("bundle_checksum", "canonical_approved_bundle_checksum"):
            if metadata.get(field) != canonical_checksum:
                errors.append(f"{field}_mismatch:{metadata.get(field)}:{canonical_checksum}")
        manifest_path = bundle_dir / "manifest.json"
        if manifest_path.exists() and metadata.get("manifest_sha256") != sha256_file(manifest_path):
            errors.append("manifest_sha256_mismatch")
        if (
            metadata.get("legacy_bundle_checksum_v1")
            and metadata.get("legacy_bundle_checksum_v1") != legacy_checksum
        ):
            errors.append("legacy_bundle_checksum_v1_mismatch")

    if compare_workspace and canonical_checksum is not None:
        try:
            workspace_checksum = approved_bundle_checksum(benchmark_dir)
            if workspace_checksum != canonical_checksum:
                errors.append(
                    f"workspace_approved_bundle_mismatch:{workspace_checksum}:{canonical_checksum}"
                )
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"workspace_read_failed:{exc}")

    integrity_manifest_path = benchmark_dir / "approved_bundle_integrity_manifest.json"
    if require_integrity_manifest:
        if not integrity_manifest_path.exists():
            errors.append("missing_approved_bundle_integrity_manifest")
        else:
            expected = build_integrity_manifest(benchmark_dir)
            actual = read_json(integrity_manifest_path)
            if actual != expected:
                errors.append("approved_bundle_integrity_manifest_drift")

    return {
        "status": "PASS" if not errors else "FAIL",
        "passed": not errors,
        "hash_contract_version": HASH_CONTRACT_VERSION,
        "canonical_approved_bundle_checksum": canonical_checksum,
        "legacy_bundle_checksum_v1": legacy_checksum,
        "errors": errors,
    }


def verify_phase2_checksum_chain(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    bundle_result = verify_approved_bundle_integrity(repo_root / "benchmarks" / "extraction_v2")
    canonical_checksum = bundle_result.get("canonical_approved_bundle_checksum")
    errors = list(bundle_result["errors"])
    checked_artifacts: list[dict[str, Any]] = []

    for relative_path in PHASE2_JSON_ARTIFACTS:
        path = repo_root / relative_path
        artifact_errors: list[str] = []
        if not path.exists():
            artifact_errors.append("missing_artifact")
        else:
            payload = read_json(path)
            if payload.get("approved_bundle_checksum") != canonical_checksum:
                artifact_errors.append("approved_bundle_checksum_mismatch")
            if payload.get("canonical_approved_bundle_checksum") != canonical_checksum:
                artifact_errors.append("canonical_approved_bundle_checksum_mismatch")
            if payload.get("approved_bundle_hash_contract_version") != HASH_CONTRACT_VERSION:
                artifact_errors.append("hash_contract_version_mismatch")
        checked_artifacts.append(
            {
                "path": relative_path,
                "status": "PASS" if not artifact_errors else "FAIL",
                "errors": artifact_errors,
            }
        )
        errors.extend(f"{relative_path}:{error}" for error in artifact_errors)

    for relative_path in PHASE2_MARKDOWN_ARTIFACTS:
        path = repo_root / relative_path
        artifact_errors = []
        if not path.exists():
            artifact_errors.append("missing_artifact")
        else:
            text = path.read_text(encoding="utf-8")
            if not canonical_checksum or canonical_checksum not in text:
                artifact_errors.append("canonical_checksum_missing")
            if HASH_CONTRACT_VERSION not in text:
                artifact_errors.append("hash_contract_version_missing")
        checked_artifacts.append(
            {
                "path": relative_path,
                "status": "PASS" if not artifact_errors else "FAIL",
                "errors": artifact_errors,
            }
        )
        errors.extend(f"{relative_path}:{error}" for error in artifact_errors)

    return {
        "status": "PASS" if not errors else "FAIL",
        "passed": not errors,
        "hash_contract_version": HASH_CONTRACT_VERSION,
        "canonical_approved_bundle_checksum": canonical_checksum,
        "bundle_integrity": bundle_result,
        "checked_artifacts": checked_artifacts,
        "errors": errors,
    }


def _canonical_file_content(path: Path, relative_path: str) -> Any:
    if relative_path in JSON_INPUTS:
        content = _read_strict_json(path)
        if relative_path == "encoding_inventory.json":
            content = dict(content)
            for field in DERIVED_INVENTORY_FIELDS_EXCLUDED_FROM_CANONICAL_HASH:
                content.pop(field, None)
        return content
    if relative_path == "correction_lineage.jsonl":
        records = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                records.append(_strict_json_loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid correction_lineage.jsonl line {line_number}: {exc}"
                ) from exc
        return records
    raise ValueError(f"unsupported canonical input: {relative_path}")


def _read_strict_json(path: Path) -> Any:
    return _strict_json_loads(path.read_text(encoding="utf-8"))


def _strict_json_loads(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


def _require_regular_file(path: Path, relative_path: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"missing canonical bundle input: {relative_path}")
    if path.is_symlink():
        raise ValueError(f"approved bundle symlink is forbidden: {relative_path}")
    if not path.is_file():
        raise ValueError(f"canonical bundle input is not a file: {relative_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or verify the approved bundle integrity contract."
    )
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        default=Path("benchmarks/extraction_v2"),
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--freeze-guard", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.write_manifest:
        write_integrity_manifest(args.benchmark_dir)
    result = (
        verify_phase2_checksum_chain(args.repo_root)
        if args.freeze_guard
        else verify_approved_bundle_integrity(args.benchmark_dir)
    )
    if args.output:
        write_json(args.output, result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
