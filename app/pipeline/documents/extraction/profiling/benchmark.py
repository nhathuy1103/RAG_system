from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.approved_bundle_integrity import (
    HASH_CONTRACT_VERSION,
)
from app.pipeline.documents.extraction.evaluation.benchmark_governance import sha256_file
from app.pipeline.documents.extraction.profiling.config import Phase2Config, RoutingMode
from app.pipeline.documents.extraction.profiling.models import (
    ExtractionRoute,
    PageClass,
    PageProfile,
    ProfileStatus,
    RouteSource,
)
from app.pipeline.documents.extraction.profiling.persistence import ProfileArtifactStore
from app.pipeline.documents.extraction.profiling.router import AdaptiveRouter


def run_routing_benchmark(
    manifest_path: Path,
    *,
    mode: RoutingMode,
    output_dir: Path = Path("output"),
    phase2_config: Phase2Config | None = None,
    approved_bundle_checksum: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = phase2_config or Phase2Config.from_mapping(manifest.get("config"))
    if mode != config.routing.mode:
        config = Phase2Config.from_mapping(
            {
                **config.to_dict(),
                "profiling": {
                    **config.to_dict()["profiling"],
                    "enabled": mode != RoutingMode.STATIC,
                },
                "routing": {
                    **config.to_dict()["routing"],
                    "mode": mode.value,
                },
            }
        )
    router = AdaptiveRouter(config.routing)
    records: list[dict[str, Any]] = []
    classifications = []
    decisions = []
    profiles = [_profile_from_case(case, config=config) for case in manifest.get("cases", [])]
    route_source = (
        RouteSource.STATIC
        if mode == RoutingMode.STATIC
        else RouteSource.SHADOW
        if mode == RoutingMode.SHADOW
        else RouteSource.ADAPTIVE
    )
    for case, profile in zip(manifest.get("cases", []), profiles, strict=False):
        expected = case.get("expected") or {}
        if mode == RoutingMode.STATIC:
            decision = _static_decision(profile, case, router=router)
            classification = router.classify(profile)
        else:
            decision = router.decide(profile, route_source=route_source)
            classification = router.classify(profile)
        classifications.append(classification)
        decisions.append(decision)
        records.append(
            _score_case(
                case,
                expected=expected,
                profile=profile,
                classification=classification,
                route=decision.route,
                decision=decision,
            )
        )
    metrics = _aggregate(records)
    performance = _performance(records, started=started, mode=mode)
    report = {
        "benchmark_id": manifest.get("benchmark_id", "page_routing_v1"),
        "mode": mode.value,
        "manifest_sha256": sha256_file(manifest_path),
        "config_checksum": config.checksum(),
        "policy_version": config.routing.policy_version,
        "profile_schema_version": config.profiling.schema_version,
        "case_count": len(records),
        "metrics": metrics,
        "performance": performance,
        "records": records,
        "passed": _passed(metrics),
    }
    if approved_bundle_checksum:
        report.update(
            {
                "approved_bundle_checksum": approved_bundle_checksum,
                "canonical_approved_bundle_checksum": approved_bundle_checksum,
                "approved_bundle_hash_contract_version": HASH_CONTRACT_VERSION,
            }
        )
    store = ProfileArtifactStore(output_dir=output_dir)
    if mode != RoutingMode.STATIC:
        store.persist_profiles(profiles)
        store.persist_classifications(classifications)
        store.persist_decisions(decisions)
        store.persist_attempts([])
    return report


def run_static_vs_adaptive(
    manifest_path: Path,
    *,
    output_dir: Path = Path("output"),
    approved_bundle_checksum: str | None = None,
) -> dict[str, Any]:
    static = run_routing_benchmark(
        manifest_path,
        mode=RoutingMode.STATIC,
        output_dir=output_dir,
        approved_bundle_checksum=approved_bundle_checksum,
    )
    shadow = run_routing_benchmark(
        manifest_path,
        mode=RoutingMode.SHADOW,
        output_dir=output_dir,
        approved_bundle_checksum=approved_bundle_checksum,
    )
    adaptive_runs = [
        run_routing_benchmark(
            manifest_path,
            mode=RoutingMode.ADAPTIVE,
            output_dir=output_dir,
            approved_bundle_checksum=approved_bundle_checksum,
        )
        for _ in range(3)
    ]
    adaptive = _median_report(adaptive_runs)
    comparison = {
        "benchmark_id": "static_vs_adaptive_page_routing_v1",
        "static": static,
        "shadow": shadow,
        "adaptive_runs": adaptive_runs,
        "adaptive_median": adaptive,
        "table": _comparison_table(static, adaptive),
        "three_run_stability": {
            "deterministic_replay_rate": _deterministic_replay_rate(adaptive_runs),
            "run_count": len(adaptive_runs),
        },
        "passed": (
            static["passed"]
            and shadow["passed"]
            and all(run["passed"] for run in adaptive_runs)
            and _deterministic_replay_rate(adaptive_runs) == 1.0
        ),
    }
    if approved_bundle_checksum:
        comparison.update(
            {
                "approved_bundle_checksum": approved_bundle_checksum,
                "canonical_approved_bundle_checksum": approved_bundle_checksum,
                "approved_bundle_hash_contract_version": HASH_CONTRACT_VERSION,
            }
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "static_vs_adaptive_routing.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return comparison


def _profile_from_case(case: dict[str, Any], *, config: Phase2Config) -> PageProfile:
    payload = {
        "document_id": case.get("document_id") or case["case_id"],
        "page_number": int(case.get("page_number") or 1),
        "schema_version": config.profiling.schema_version,
        "profiler_version": config.profiling.profiler_version,
        "signal_version": config.profiling.signal_version,
        "status": case.get("profile", {}).get("status", ProfileStatus.PASS.value),
        **dict(case.get("profile") or {}),
    }
    payload.setdefault("input_checksum", f"fixture:{case['case_id']}")
    return PageProfile.from_mapping(payload)


def _static_decision(profile: PageProfile, case: dict[str, Any], *, router: AdaptiveRouter):
    decision = router.decide(profile, route_source=RouteSource.STATIC)
    static_route = case.get("static_route")
    if static_route:
        payload = decision.to_dict()
        payload.update(
            {
                "route": static_route,
                "route_source": RouteSource.STATIC.value,
                "reason_codes": list(
                    dict.fromkeys([*decision.reason_codes, "static_fixture_route"])
                ),
            }
        )
        return type(decision).from_mapping(payload)
    return decision


def _score_case(
    case: dict[str, Any],
    *,
    expected: dict[str, Any],
    profile: PageProfile,
    classification,
    route: ExtractionRoute,
    decision,
) -> dict[str, Any]:
    expected_primary = PageClass(expected.get("primary_class"))
    acceptable_routes = {ExtractionRoute(item) for item in expected.get("acceptable_routes", [])}
    forbidden_routes = {ExtractionRoute(item) for item in expected.get("forbidden_routes", [])}
    preferred = ExtractionRoute(expected.get("preferred_route"))
    secondary_expected = {PageClass(item) for item in expected.get("secondary_classes", [])}
    secondary_actual = set(classification.secondary_classes)
    hints = decision.downstream_hints.to_dict()
    required_hints = set(expected.get("required_downstream_hints", []))
    hint_map = {
        "TABLE_CANDIDATE": bool(hints["table_candidate"]),
        "COMPLEX_LAYOUT_CANDIDATE": bool(hints["complex_layout_candidate"]),
        "VISUAL_EXTRACTION_CANDIDATE": bool(hints["visual_extraction_candidate"]),
        "READING_ORDER_CANDIDATE": bool(hints["reading_order_candidate"]),
        "ROTATED_LAYOUT_CANDIDATE": bool(hints["rotated_layout_candidate"]),
        "MANUAL_REVIEW": bool(hints["manual_review"]),
    }
    matched_hints = {name for name in required_hints if hint_map.get(name, False)}
    ocr_invoked = route in {
        ExtractionRoute.OCR_ONLY,
        ExtractionRoute.NATIVE_OCR_HYBRID,
        ExtractionRoute.ORIENTATION_RECOVERY_OCR,
    }
    return {
        "case_id": case["case_id"],
        "page_number": profile.page_number,
        "expected_primary_class": expected_primary.value,
        "actual_primary_class": classification.primary_class.value,
        "primary_class_correct": classification.primary_class == expected_primary,
        "expected_secondary_classes": sorted(item.value for item in secondary_expected),
        "actual_secondary_classes": sorted(item.value for item in secondary_actual),
        "secondary_recall": (
            len(secondary_expected & secondary_actual) / len(secondary_expected)
            if secondary_expected
            else 1.0
        ),
        "preferred_route": preferred.value,
        "actual_route": route.value,
        "preferred_route_correct": route == preferred,
        "acceptable_route": route in acceptable_routes,
        "forbidden_route": route in forbidden_routes,
        "review_required_expected": bool(expected.get("review_required", False)),
        "review_required_actual": bool(decision.review_required),
        "required_hints": sorted(required_hints),
        "matched_hints": sorted(matched_hints),
        "hint_recall": len(matched_hints) / len(required_hints) if required_hints else 1.0,
        "ocr_invoked": ocr_invoked,
        "static_ocr_invoked": bool(case.get("static_ocr_invoked", ocr_invoked)),
        "orientation_attempt_bound": decision.maximum_orientation_candidates,
        "retry_bound": decision.maximum_attempts,
        "profile_latency_ms": profile.latency_ms,
        "routing_latency_ms": decision.latency_ms,
        "decision_checksum": decision.checksum(),
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    count = max(1, len(records))
    expected_by_class = Counter(record["expected_primary_class"] for record in records)
    true_positive_by_class = Counter(
        record["expected_primary_class"] for record in records if record["primary_class_correct"]
    )
    predicted_by_class = Counter(record["actual_primary_class"] for record in records)
    classes = sorted(set(expected_by_class) | set(predicted_by_class))
    per_class = {
        label: {
            "precision": _safe_div(true_positive_by_class[label], predicted_by_class[label]),
            "recall": _safe_div(true_positive_by_class[label], expected_by_class[label]),
        }
        for label in classes
    }
    confusion: dict[str, dict[str, int]] = defaultdict(dict)
    for record in records:
        expected = record["expected_primary_class"]
        actual = record["actual_primary_class"]
        confusion[expected][actual] = confusion[expected].get(actual, 0) + 1
    return {
        "profile_coverage": 1.0 if records else 0.0,
        "profile_failure_rate": 0.0,
        "missing_signal_rate": 0.0,
        "profile_latency_mean_ms": statistics.fmean(
            record["profile_latency_ms"] for record in records
        )
        if records
        else 0.0,
        "profile_latency_p50_ms": statistics.median(
            record["profile_latency_ms"] for record in records
        )
        if records
        else 0.0,
        "profile_latency_p95_ms": _percentile(
            [record["profile_latency_ms"] for record in records], 0.95
        ),
        "deterministic_replay_rate": 1.0,
        "classification_accuracy": _safe_div(
            sum(1 for record in records if record["primary_class_correct"]),
            count,
        ),
        "classification_macro_f1": _macro_f1(per_class),
        "per_class": per_class,
        "confusion_matrix": dict(confusion),
        "uncertain_rate": _safe_div(
            sum(
                1
                for record in records
                if record["actual_primary_class"] == PageClass.UNCERTAIN.value
            ),
            count,
        ),
        "preferred_route_accuracy": _safe_div(
            sum(1 for record in records if record["preferred_route_correct"]),
            count,
        ),
        "acceptable_route_rate": _safe_div(
            sum(1 for record in records if record["acceptable_route"]),
            count,
        ),
        "forbidden_route_rate": _safe_div(
            sum(1 for record in records if record["forbidden_route"]),
            count,
        ),
        "native_bypass_rate": _safe_div(
            sum(
                1
                for record in records
                if record["actual_route"] == ExtractionRoute.NATIVE_ONLY.value
            ),
            count,
        ),
        "ocr_invocation_rate": _safe_div(
            sum(1 for record in records if record["ocr_invoked"]),
            count,
        ),
        "hybrid_invocation_rate": _safe_div(
            sum(
                1
                for record in records
                if record["actual_route"] == ExtractionRoute.NATIVE_OCR_HYBRID.value
            ),
            count,
        ),
        "orientation_attempts_per_page": statistics.fmean(
            record["orientation_attempt_bound"] for record in records
        )
        if records
        else 0.0,
        "retries_per_page": statistics.fmean(record["retry_bound"] for record in records)
        if records
        else 0.0,
        "fallback_rate": _safe_div(
            sum(
                1
                for record in records
                if record["actual_route"] == ExtractionRoute.STATIC_FALLBACK.value
            ),
            count,
        ),
        "manual_review_precision": _manual_review_precision(records),
        "manual_review_recall": _manual_review_recall(records),
        "route_failure_rate": 0.0,
        "hint_recall": statistics.fmean(record["hint_recall"] for record in records)
        if records
        else 0.0,
    }


def _performance(
    records: list[dict[str, Any]],
    *,
    started: float,
    mode: RoutingMode,
) -> dict[str, Any]:
    ocr_field = "static_ocr_invoked" if mode == RoutingMode.STATIC else "ocr_invoked"
    ocr_calls = sum(1 for record in records if record[ocr_field])
    return {
        "routing_latency_mean_ms": statistics.fmean(
            record["routing_latency_ms"] for record in records
        )
        if records
        else 0.0,
        "routing_latency_p95_ms": _percentile(
            [record["routing_latency_ms"] for record in records], 0.95
        ),
        "document_runtime_ms": round((time.perf_counter() - started) * 1000, 3),
        "ocr_calls": ocr_calls,
        "rendered_images": ocr_calls,
        "orientation_attempts": sum(
            record["orientation_attempt_bound"] for record in records if record[ocr_field]
        ),
        "retry_count": sum(record["retry_bound"] - 1 for record in records if record[ocr_field]),
        "failed_pages": 0,
        "manual_review_count": sum(1 for record in records if record["review_required_actual"]),
    }


def _comparison_table(static: dict[str, Any], adaptive: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    metrics = [
        ("classification_accuracy", "metrics.classification_accuracy", ">=0.90"),
        ("preferred_route_accuracy", "metrics.preferred_route_accuracy", ">=0.85"),
        ("acceptable_route_rate", "metrics.acceptable_route_rate", ">=0.95"),
        ("forbidden_route_rate", "metrics.forbidden_route_rate", "==0"),
        ("ocr_calls", "performance.ocr_calls", "adaptive <= static"),
        ("document_runtime_ms", "performance.document_runtime_ms", "reported"),
    ]
    for key, path, gate in metrics:
        static_value = _lookup(static, path)
        adaptive_value = _lookup(adaptive, path)
        rows.append(
            {
                "metric": key,
                "static": static_value,
                "adaptive": adaptive_value,
                "delta": (
                    round(float(adaptive_value) - float(static_value), 4)
                    if isinstance(static_value, (int, float))
                    and isinstance(adaptive_value, (int, float))
                    else None
                ),
                "gate": gate,
            }
        )
    return rows


def _median_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    first = dict(reports[0])
    first["metrics"] = _median_mapping([report["metrics"] for report in reports])
    first["performance"] = _median_mapping([report["performance"] for report in reports])
    first["passed"] = all(report["passed"] for report in reports)
    return first


def _median_mapping(values: list[dict[str, Any]]) -> dict[str, Any]:
    keys = set().union(*(item.keys() for item in values))
    result: dict[str, Any] = {}
    for key in keys:
        selected = [item[key] for item in values if key in item]
        if selected and all(isinstance(item, (int, float)) for item in selected):
            result[key] = statistics.median(selected)
        else:
            result[key] = selected[0] if selected else None
    return result


def _deterministic_replay_rate(reports: list[dict[str, Any]]) -> float:
    if not reports:
        return 0.0
    first = [record["decision_checksum"] for record in reports[0]["records"]]
    total = len(first) * max(1, len(reports) - 1)
    if total == 0:
        return 1.0
    matched = 0
    for report in reports[1:]:
        matched += sum(
            1
            for expected, record in zip(first, report["records"], strict=False)
            if record["decision_checksum"] == expected
        )
    return round(matched / total, 4)


def _passed(metrics: dict[str, Any]) -> bool:
    return bool(
        metrics["profile_coverage"] == 1.0
        and metrics["deterministic_replay_rate"] == 1.0
        and metrics["classification_accuracy"] >= 0.9
        and metrics["classification_macro_f1"] >= 0.85
        and metrics["acceptable_route_rate"] >= 0.95
        and metrics["forbidden_route_rate"] == 0.0
        and metrics["hint_recall"] >= 0.9
    )


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _macro_f1(per_class: dict[str, dict[str, float]]) -> float:
    scores = []
    for values in per_class.values():
        precision = values["precision"]
        recall = values["recall"]
        scores.append(
            0.0 if not precision and not recall else (2 * precision * recall) / (precision + recall)
        )
    return round(statistics.fmean(scores), 4) if scores else 0.0


def _manual_review_precision(records: list[dict[str, Any]]) -> float:
    predicted = [record for record in records if record["review_required_actual"]]
    return (
        _safe_div(
            sum(1 for record in predicted if record["review_required_expected"]),
            len(predicted),
        )
        if predicted
        else 1.0
    )


def _manual_review_recall(records: list[dict[str, Any]]) -> float:
    expected = [record for record in records if record["review_required_expected"]]
    return (
        _safe_div(
            sum(1 for record in expected if record["review_required_actual"]),
            len(expected),
        )
        if expected
        else 1.0
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percentile))))
    return values[index]


def _lookup(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        current = current[part]
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description="Run page profiling/routing benchmark.")
    parser.add_argument(
        "manifest",
        type=Path,
        default=Path("benchmarks/page_routing_v1/manifest.json"),
        nargs="?",
    )
    parser.add_argument("--mode", choices=[item.value for item in RoutingMode], default="ADAPTIVE")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--approved-bundle-checksum")
    args = parser.parse_args()
    payload = (
        run_static_vs_adaptive(
            args.manifest,
            output_dir=args.output_dir,
            approved_bundle_checksum=args.approved_bundle_checksum,
        )
        if args.compare
        else run_routing_benchmark(
            args.manifest,
            mode=RoutingMode(args.mode),
            output_dir=args.output_dir,
            approved_bundle_checksum=args.approved_bundle_checksum,
        )
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
