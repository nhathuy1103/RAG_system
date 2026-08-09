from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FROZEN_STATUS = "FROZEN_KNOWN_GT_ENCODING_DEFECT"
FROZEN_RELEASE_BLOCK_REASON = "frozen_benchmark_not_release_eligible"
FREEZE_METADATA_NAME = "freeze_metadata.json"
V1_KNOWN_DEFECTS = [
    "MULTILAYER_MOJIBAKE",
    "LOSSY_QUESTION_MARK_ENCODING",
    "MIXED_ENCODING_IN_SAME_TABLE",
    "SEMANTIC_VALIDATION_NOT_PROVEN",
]
DEFAULT_PREVIOUS_RESULT = {
    "text_recall": 0.1622,
    "table_recall": 0.0,
    "issue_recall": 0.1333,
    "benchmark_status": "FAIL",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_json(payload: Any) -> str:
    return sha256_bytes(canonical_json_bytes(payload))


def iter_benchmark_bundle_files(root: Path) -> list[Path]:
    excluded_dirs = {"__pycache__", ".pytest_cache", "generated_corpus"}
    excluded_names = {FREEZE_METADATA_NAME}
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in excluded_dirs for part in relative.parts):
            continue
        if path.name in excluded_names:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def tree_checksum(root: Path, files: Iterable[Path] | None = None) -> str:
    digest = hashlib.sha256()
    selected = list(files) if files is not None else iter_benchmark_bundle_files(root)
    for path in sorted(selected, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def file_checksum_map(root: Path, files: Iterable[Path] | None = None) -> dict[str, str]:
    selected = list(files) if files is not None else iter_benchmark_bundle_files(root)
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(selected, key=lambda item: item.relative_to(root).as_posix())
    }


def freeze_benchmark_v1(
    benchmark_dir: Path,
    *,
    scorer_version: str = "extraction_scorer_v1",
    previous_result: dict[str, Any] | None = None,
    apply_readonly: bool = False,
    frozen_at: str | None = None,
) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    manifest_path = benchmark_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing manifest: {manifest_path}")
    manifest = read_json(manifest_path)
    files = iter_benchmark_bundle_files(benchmark_dir)
    checksums = file_checksum_map(benchmark_dir, files)
    cases = manifest.get("cases", [])
    source_sha256 = cases[0].get("sha256") if cases else None
    metadata = {
        "benchmark_id": manifest.get("version") or benchmark_dir.name,
        "status": FROZEN_STATUS,
        "release_eligible": False,
        "source_sha256": source_sha256,
        "manifest_sha256": sha256_file(manifest_path),
        "ground_truth_bundle_sha256": tree_checksum(benchmark_dir, files),
        "scorer_version": scorer_version,
        "frozen_at": frozen_at or utc_now_iso(),
        "known_defects": list(V1_KNOWN_DEFECTS),
        "previous_benchmark_result": previous_result or DEFAULT_PREVIOUS_RESULT,
        "file_checksums": checksums,
        "protected_paths": sorted(checksums),
        "write_guard": {
            "mode": "checksum_and_optional_readonly",
            "readonly_applied": apply_readonly,
            "drift_check_command": (
                "python -m app.pipeline.documents.extraction.evaluation.benchmark_freeze "
                f"{benchmark_dir.as_posix()} --check"
            ),
        },
    }
    write_json(benchmark_dir / FREEZE_METADATA_NAME, metadata)
    if apply_readonly:
        for path in files:
            _set_readonly(path)
    return metadata


def check_frozen_benchmark(benchmark_dir: Path) -> dict[str, Any]:
    benchmark_dir = benchmark_dir.resolve()
    metadata_path = benchmark_dir / FREEZE_METADATA_NAME
    if not metadata_path.exists():
        return {
            "status": "NO_FREEZE_METADATA",
            "passed": False,
            "failures": ["missing_freeze_metadata"],
        }
    metadata = read_json(metadata_path)
    failures: list[str] = []
    expected = dict(metadata.get("file_checksums") or {})
    for relative, expected_sha in expected.items():
        path = benchmark_dir / relative
        if not path.exists():
            failures.append(f"missing_protected_file:{relative}")
            continue
        actual = sha256_file(path)
        if actual != expected_sha:
            failures.append(f"checksum_drift:{relative}:{expected_sha}:{actual}")
    current_files = set(file_checksum_map(benchmark_dir).keys())
    missing_from_metadata = sorted(current_files - set(expected))
    if missing_from_metadata:
        failures.extend(f"untracked_ground_truth_file:{path}" for path in missing_from_metadata)
    return {
        "status": "PASS" if not failures else "FAIL",
        "passed": not failures,
        "benchmark_id": metadata.get("benchmark_id"),
        "release_eligible": bool(metadata.get("release_eligible")),
        "ground_truth_bundle_sha256": metadata.get("ground_truth_bundle_sha256"),
        "failures": failures,
    }


def frozen_release_block_reason(manifest_path: Path) -> str | None:
    metadata_path = manifest_path.parent / FREEZE_METADATA_NAME
    if not metadata_path.exists():
        return None
    metadata = read_json(metadata_path)
    if metadata.get("status") == FROZEN_STATUS and not metadata.get("release_eligible", False):
        return FROZEN_RELEASE_BLOCK_REASON
    return None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def make_record_id(prefix: str, *parts: object, length: int = 16) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256_text(raw)[:length]}"


def _set_readonly(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode & ~stat.S_IWRITE)
