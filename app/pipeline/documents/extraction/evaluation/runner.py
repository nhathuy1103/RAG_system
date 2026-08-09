from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.approved_bundle_integrity import (
    HASH_CONTRACT_VERSION,
    approved_bundle_checksum,
)
from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    frozen_release_block_reason,
)
from app.pipeline.documents.extraction.evaluation.models import ExtractionGroundTruth
from app.pipeline.documents.extraction.evaluation.scorer import score_extraction
from app.pipeline.documents.extraction.parsing.adaptive import AdaptiveExtractionEngine
from app.pipeline.documents.extraction.parsing.parsers import ParserRegistry
from app.pipeline.documents.extraction.profiling.config import (
    Phase2Config,
    ProfilingConfig,
    RoutingConfig,
    RoutingMode,
)
from app.pipeline.documents.extraction.profiling.persistence import ProfileArtifactStore

RELEASE_VALIDATION_STATUS = "HUMAN_VALIDATED"
EXPLORATORY_VALIDATION_STATUSES = {"HUMAN_REVIEWED", "HUMAN_VALIDATED"}
BENCHMARK_STATUSES = {"PASS", "FAIL", "INVALID", "INCOMPLETE"}


def run_manifest(
    manifest_path: Path,
    *,
    release: bool = False,
    skip_draft: bool = True,
    min_human_validated: int = 1,
    page_routing_mode: str | RoutingMode = RoutingMode.STATIC,
    phase2_output_dir: Path | None = None,
) -> dict[str, object]:
    manifest = _load_manifest(manifest_path)
    cases = [ExtractionGroundTruth.from_mapping(item) for item in manifest.get("cases", [])]
    frozen_block = frozen_release_block_reason(manifest_path) if release else None
    if frozen_block:
        return _frozen_release_report(
            cases=cases,
            release=release,
            min_human_validated=min_human_validated,
            reason=frozen_block,
        )
    routing_mode = _routing_mode(page_routing_mode)
    phase2_config = _phase2_config_for_mode(routing_mode)
    parser_registry = ParserRegistry()
    engine = AdaptiveExtractionEngine(
        parser_registry=parser_registry,
        phase2_config=phase2_config,
    )
    scores: list[dict[str, object]] = []
    invalid_cases: list[dict[str, object]] = []
    skipped_cases: list[dict[str, object]] = []
    eligible_cases = 0
    phase2_profiles = []
    phase2_classifications = []
    phase2_decisions = []

    for case in cases:
        eligibility = _case_eligibility(case, release=release, skip_draft=skip_draft)
        if eligibility is not None:
            skipped_cases.append({"case_id": case.case_id, "reason": eligibility})
            continue
        eligible_cases += 1
        document_path = _resolve_document_path(case.document_path, manifest_path, manifest)
        validation_failures = _validate_case_for_execution(
            case,
            document_path=document_path,
            release=release,
        )
        if validation_failures:
            invalid_cases.append(
                {
                    "case_id": case.case_id,
                    "document_path": str(document_path),
                    "failures": tuple(validation_failures),
                }
            )
            continue
        content = document_path.read_bytes()
        try:
            result = engine.extract(document_path.name, content)
            phase2_profiles.extend(result.page_profiles)
            phase2_classifications.extend(result.page_classifications)
            phase2_decisions.extend(result.routing_decisions)
            parsed = result.parsed_document
            parsed.document_metadata.setdefault("domain", case.domain)
            scores.append(score_extraction(parsed, case).to_dict())
        except Exception as exc:
            scores.append(
                {
                    "case_id": case.case_id,
                    "passed": False,
                    "text_recall": 0.0,
                    "table_recall": 0.0,
                    "issue_recall": 0.0,
                    "silent_p0": False,
                    "quality_status": "ERROR",
                    "failures": (f"parser_exception:{exc.__class__.__name__}:{exc}",),
                    "details": {},
                }
            )
    report = _report(
        scores=scores,
        discovered_cases=len(cases),
        eligible_cases=eligible_cases,
        skipped_cases=skipped_cases,
        invalid_cases=invalid_cases,
        release=release,
        min_human_validated=min_human_validated,
        human_validated_count=sum(
            1 for case in cases if case.validation_status == RELEASE_VALIDATION_STATUS
        ),
    )
    report["page_routing_mode"] = routing_mode.value
    report["phase2_routing"] = _phase2_routing_summary(
        profiles=phase2_profiles,
        decisions=phase2_decisions,
        enabled=routing_mode != RoutingMode.STATIC,
    )
    _attach_approved_bundle_integrity(report, manifest_path)
    if phase2_output_dir is not None and routing_mode != RoutingMode.STATIC:
        store = ProfileArtifactStore(phase2_output_dir)
        store.persist_profiles(phase2_profiles)
        store.persist_classifications(phase2_classifications)
        store.persist_decisions(phase2_decisions)
        store.persist_attempts([])
    return report


def dry_run_manifest(
    manifest_path: Path,
    *,
    release: bool = False,
    skip_draft: bool = True,
    min_human_validated: int = 1,
) -> dict[str, object]:
    manifest = _load_manifest(manifest_path)
    cases = [ExtractionGroundTruth.from_mapping(item) for item in manifest.get("cases", [])]
    frozen_block = frozen_release_block_reason(manifest_path) if release else None
    if frozen_block:
        return _frozen_release_report(
            cases=cases,
            release=release,
            min_human_validated=min_human_validated,
            reason=frozen_block,
        )
    scores: list[dict[str, object]] = []
    invalid_cases: list[dict[str, object]] = []
    skipped_cases: list[dict[str, object]] = []
    eligible_cases = 0
    for case in cases:
        eligibility = _case_eligibility(case, release=release, skip_draft=skip_draft)
        if eligibility is not None:
            skipped_cases.append({"case_id": case.case_id, "reason": eligibility})
            continue
        eligible_cases += 1
        document_path = _resolve_document_path(case.document_path, manifest_path, manifest)
        failures = _validate_case_for_execution(
            case,
            document_path=document_path,
            release=release,
        )
        if failures:
            invalid_cases.append(
                {
                    "case_id": case.case_id,
                    "document_path": str(document_path),
                    "failures": tuple(failures),
                }
            )
        else:
            scores.append(
                {
                    "case_id": case.case_id,
                    "passed": True,
                    "validation_status": case.validation_status,
                    "document_path": str(document_path),
                    "failures": (),
                }
            )
    report = _report(
        scores=scores,
        discovered_cases=len(cases),
        eligible_cases=eligible_cases,
        skipped_cases=skipped_cases,
        invalid_cases=invalid_cases,
        release=release,
        min_human_validated=min_human_validated,
        human_validated_count=sum(
            1 for case in cases if case.validation_status == RELEASE_VALIDATION_STATUS
        ),
    )
    _attach_approved_bundle_integrity(report, manifest_path)
    return report


def _attach_approved_bundle_integrity(
    report: dict[str, object],
    manifest_path: Path,
) -> None:
    approved_dir = manifest_path.resolve().parent / "approved_bundle"
    if not approved_dir.exists():
        return
    checksum = approved_bundle_checksum(approved_dir)
    report["approved_bundle_checksum"] = checksum
    report["canonical_approved_bundle_checksum"] = checksum
    report["approved_bundle_hash_contract_version"] = HASH_CONTRACT_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="Run extraction benchmark cases.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--include-draft", action="store_true")
    parser.add_argument("--skip-draft", action="store_true")
    parser.add_argument("--min-human-validated", type=int, default=1)
    parser.add_argument(
        "--page-routing-mode",
        choices=[item.value for item in RoutingMode],
        default=RoutingMode.STATIC.value,
    )
    parser.add_argument("--phase2-output-dir", type=Path)
    args = parser.parse_args()

    skip_draft = not args.include_draft or args.skip_draft or args.release
    payload = (
        dry_run_manifest(
            args.manifest,
            release=args.release,
            skip_draft=skip_draft,
            min_human_validated=args.min_human_validated,
        )
        if args.dry_run
        else run_manifest(
            args.manifest,
            release=args.release,
            skip_draft=skip_draft,
            min_human_validated=args.min_human_validated,
            page_routing_mode=args.page_routing_mode,
            phase2_output_dir=args.phase2_output_dir,
        )
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0 if payload["benchmark_status"] == "PASS" else 1


def _report(
    *,
    scores: list[dict[str, object]],
    discovered_cases: int,
    eligible_cases: int,
    skipped_cases: list[dict[str, object]],
    invalid_cases: list[dict[str, object]],
    release: bool,
    min_human_validated: int,
    human_validated_count: int,
) -> dict[str, object]:
    executed_cases = len(scores)
    passed_cases = sum(1 for score in scores if score.get("passed") is True)
    failed_cases = executed_cases - passed_cases
    silent_p0_count = sum(1 for score in scores if score.get("silent_p0"))
    if invalid_cases or executed_cases == 0:
        status = "INVALID"
    elif release and human_validated_count < min_human_validated:
        status = "INCOMPLETE"
    elif failed_cases or silent_p0_count:
        status = "FAIL"
    else:
        status = "PASS"
    assert status in BENCHMARK_STATUSES
    return {
        "benchmark_status": status,
        "release": release,
        "discovered_cases": discovered_cases,
        "eligible_cases": eligible_cases,
        "executed_cases": executed_cases,
        "skipped_cases": len(skipped_cases),
        "invalid_cases": len(invalid_cases),
        "passed_cases": passed_cases,
        "failed_cases": failed_cases,
        "human_validated_cases": human_validated_count,
        "min_human_validated": min_human_validated,
        "passed": status == "PASS",
        "silent_p0_count": silent_p0_count,
        "scores": scores,
        "skipped": skipped_cases,
        "invalid": invalid_cases,
    }


def _frozen_release_report(
    *,
    cases: list[ExtractionGroundTruth],
    release: bool,
    min_human_validated: int,
    reason: str,
) -> dict[str, object]:
    return _report(
        scores=[],
        discovered_cases=len(cases),
        eligible_cases=0,
        skipped_cases=[],
        invalid_cases=[
            {
                "case_id": "__benchmark__",
                "document_path": "",
                "failures": (reason,),
            }
        ],
        release=release,
        min_human_validated=min_human_validated,
        human_validated_count=sum(
            1 for case in cases if case.validation_status == RELEASE_VALIDATION_STATUS
        ),
    )


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _case_eligibility(
    case: ExtractionGroundTruth,
    *,
    release: bool,
    skip_draft: bool,
) -> str | None:
    status = case.validation_status
    if release and status != RELEASE_VALIDATION_STATUS:
        return f"not_release_validated:{status}"
    if skip_draft and status == "DRAFT":
        return "draft_skipped"
    if not release and skip_draft and status not in EXPLORATORY_VALIDATION_STATUSES:
        return f"not_human_reviewed:{status}"
    return None


def _validate_case_for_execution(
    case: ExtractionGroundTruth,
    *,
    document_path: Path,
    release: bool,
) -> list[str]:
    failures: list[str] = []
    if not document_path.exists():
        failures.append("missing_document")
        return failures
    content = document_path.read_bytes()
    if case.sha256 and _sha256(content) != case.sha256:
        failures.append("sha256_mismatch")
    if release and case.validation_status != RELEASE_VALIDATION_STATUS:
        failures.append("not_human_validated")
    if release and not (case.expected_text or case.expected_tables or case.expected_issues):
        failures.append("empty_expected_outputs")
    if _requires_structured_tables(case) and not case.expected_tables:
        failures.append("missing_expected_tables")
    for table in case.expected_tables:
        if _requires_structured_tables(case) and not table.columns:
            failures.append(f"table_missing_columns:{table.table_id}")
        if _requires_structured_tables(case) and not table.rows:
            failures.append(f"table_missing_critical_rows:{table.table_id}")
    return failures


def _requires_structured_tables(case: ExtractionGroundTruth) -> bool:
    capability = str(case.metadata.get("capability") or "").lower()
    return case.domain in {"structured_document", "financial_report"} and (
        "table" in capability or bool(case.expected_tables)
    )


def _resolve_document_path(
    value: str,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> Path:
    raw = os.path.expandvars(value)
    path = Path(raw)
    if path.is_absolute():
        return path
    dataset_root = os.getenv("EXTRACTION_BENCHMARK_DATASET_ROOT")
    if dataset_root:
        candidate = Path(dataset_root) / raw
        if candidate.exists():
            return candidate
    manifest_root = manifest.get("dataset_root")
    if manifest_root:
        return (manifest_path.parent / str(manifest_root) / raw).resolve()
    return (manifest_path.parent / raw).resolve()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _routing_mode(value: str | RoutingMode) -> RoutingMode:
    if isinstance(value, RoutingMode):
        return value
    return RoutingMode(str(value).upper())


def _phase2_config_for_mode(mode: RoutingMode) -> Phase2Config:
    return Phase2Config(
        profiling=ProfilingConfig(enabled=mode != RoutingMode.STATIC),
        routing=RoutingConfig(mode=mode),
    )


def _phase2_routing_summary(
    *,
    profiles: list[object],
    decisions: list[object],
    enabled: bool,
) -> dict[str, object]:
    if not enabled:
        return {
            "enabled": False,
            "profile_coverage": None,
            "decision_coverage": None,
            "decision_count": 0,
        }
    profile_count = len(profiles)
    decision_count = len(decisions)
    route_counts: dict[str, int] = {}
    ocr_invocation_count = 0
    native_bypass_count = 0
    for decision in decisions:
        route = decision.route.value
        route_counts[route] = route_counts.get(route, 0) + 1
        if route in {"OCR_ONLY", "NATIVE_OCR_HYBRID", "ORIENTATION_RECOVERY_OCR"}:
            ocr_invocation_count += 1
        if route == "NATIVE_ONLY":
            native_bypass_count += 1
    denominator = max(1, profile_count)
    return {
        "enabled": True,
        "profile_coverage": 1.0 if profile_count else 0.0,
        "decision_coverage": 1.0 if decision_count == profile_count and profile_count else 0.0,
        "profile_count": profile_count,
        "decision_count": decision_count,
        "route_counts": route_counts,
        "native_bypass_rate": round(native_bypass_count / denominator, 4),
        "ocr_invocation_rate": round(ocr_invocation_count / denominator, 4),
    }


if __name__ == "__main__":
    raise SystemExit(main())
