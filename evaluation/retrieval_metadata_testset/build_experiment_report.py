"""Create a concise verdict from A/B/C/D retrieval metric CSV files."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RUN_DIR = SCRIPT_DIR / "runs" / "latest"
REQUIRED_MODES = (
    "no_metadata",
    "current_metadata",
    "shuffled_metadata",
    "gold_metadata",
)
THRESHOLDS = {
    "recall_at_5": 0.85,
    "mrr_at_10": 0.65,
    "term_hit_rate_at_5": 0.90,
    "forbidden_top1_rate_max": 0.10,
    "empty_result_rate_max": 0.05,
    "top1_mojibake_rate_max": 0.0,
    "latency_p95_ms_max": 1000.0,
    "metadata_recall_delta_min": 0.05,
    "placebo_recall_delta_min": 0.05,
    "latency_relative_increase_max": 0.15,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing metric file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(value: object, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _comparison(
    rows: list[dict[str, str]],
    name: str,
    metric: str,
) -> dict[str, str] | None:
    return next(
        (row for row in rows if row.get("comparison") == name and row.get("metric") == metric),
        None,
    )


def _gate(name: str, passed: bool, actual: object, expected: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "actual": actual,
        "expected": expected,
    }


def build_report(
    *,
    summary_rows: list[dict[str, str]],
    comparison_rows: list[dict[str, str]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    by_mode = {row["mode"]: row for row in summary_rows}
    query_count = int(manifest.get("query_count") or 0)
    current = by_mode.get("current_metadata", {})
    baseline = by_mode.get("no_metadata", {})
    b_minus_a = _comparison(comparison_rows, "B_minus_A", "recall_at_5")
    b_minus_c = _comparison(comparison_rows, "B_minus_C", "recall_at_5")
    d_minus_b = _comparison(comparison_rows, "D_minus_B", "recall_at_5")

    baseline_p95 = _number(baseline.get("latency_p95_ms"))
    current_p95 = _number(current.get("latency_p95_ms"))
    latency_delta = (current_p95 - baseline_p95) / baseline_p95 if baseline_p95 > 0 else 0.0
    gates = [
        _gate(
            "all_required_modes_complete",
            all(
                mode in by_mode and int(_number(by_mode[mode].get("count"))) == query_count
                for mode in REQUIRED_MODES
            ),
            {mode: int(_number(by_mode.get(mode, {}).get("count"))) for mode in REQUIRED_MODES},
            f"{query_count} rows per mode",
        ),
        _gate(
            "ground_truth_resolved",
            int(manifest.get("ground_truth_unresolved_count") or 0) == 0,
            int(manifest.get("ground_truth_unresolved_count") or 0),
            "0 unresolved cases",
        ),
        _gate(
            "current_recall_at_5",
            _number(current.get("recall_at_5")) >= THRESHOLDS["recall_at_5"],
            _number(current.get("recall_at_5")),
            f">= {THRESHOLDS['recall_at_5']}",
        ),
        _gate(
            "current_mrr_at_10",
            _number(current.get("mrr_at_10")) >= THRESHOLDS["mrr_at_10"],
            _number(current.get("mrr_at_10")),
            f">= {THRESHOLDS['mrr_at_10']}",
        ),
        _gate(
            "current_term_hit_rate_at_5",
            _number(current.get("term_hit_rate_at_5")) >= THRESHOLDS["term_hit_rate_at_5"],
            _number(current.get("term_hit_rate_at_5")),
            f">= {THRESHOLDS['term_hit_rate_at_5']}",
        ),
        _gate(
            "current_error_rates",
            _number(current.get("forbidden_top1_rate")) <= THRESHOLDS["forbidden_top1_rate_max"]
            and _number(current.get("empty_result_rate")) <= THRESHOLDS["empty_result_rate_max"]
            and _number(current.get("top1_mojibake_rate")) <= THRESHOLDS["top1_mojibake_rate_max"],
            {
                "forbidden_top1_rate": _number(current.get("forbidden_top1_rate")),
                "empty_result_rate": _number(current.get("empty_result_rate")),
                "top1_mojibake_rate": _number(current.get("top1_mojibake_rate")),
            },
            "forbidden<=0.10, empty<=0.05, mojibake=0",
        ),
        _gate(
            "current_latency_p95",
            current_p95 <= THRESHOLDS["latency_p95_ms_max"],
            current_p95,
            f"<= {THRESHOLDS['latency_p95_ms_max']} ms",
        ),
        _gate(
            "metadata_beats_no_metadata",
            b_minus_a is not None
            and _number(b_minus_a.get("absolute_delta")) >= THRESHOLDS["metadata_recall_delta_min"],
            None if b_minus_a is None else _number(b_minus_a.get("absolute_delta")),
            f"Recall@5 delta >= {THRESHOLDS['metadata_recall_delta_min']}",
        ),
        _gate(
            "metadata_beats_shuffled_placebo",
            b_minus_c is not None
            and _number(b_minus_c.get("absolute_delta")) >= THRESHOLDS["placebo_recall_delta_min"],
            None if b_minus_c is None else _number(b_minus_c.get("absolute_delta")),
            f"Recall@5 delta >= {THRESHOLDS['placebo_recall_delta_min']}",
        ),
        _gate(
            "latency_regression",
            latency_delta <= THRESHOLDS["latency_relative_increase_max"],
            round(latency_delta, 6),
            f"relative p95 increase <= {THRESHOLDS['latency_relative_increase_max']}",
        ),
    ]
    production_comparable = bool(manifest.get("production_comparable"))
    failed = [gate for gate in gates if not gate["passed"]]
    if not production_comparable:
        verdict = "proxy_only"
    elif failed:
        verdict = "needs_optimization"
    else:
        verdict = "pass"
    return {
        "schema_version": "1.0",
        "verdict": verdict,
        "production_comparable": production_comparable,
        "embedding_provider": manifest.get("embedding_provider"),
        "embedding_model": manifest.get("embedding_model"),
        "query_count": query_count,
        "gates": gates,
        "failed_gate_count": len(failed),
        "key_deltas": {
            "B_minus_A_recall_at_5": (
                None if b_minus_a is None else _number(b_minus_a.get("absolute_delta"))
            ),
            "B_minus_C_recall_at_5": (
                None if b_minus_c is None else _number(b_minus_c.get("absolute_delta"))
            ),
            "D_minus_B_recall_at_5": (
                None if d_minus_b is None else _number(d_minus_b.get("absolute_delta"))
            ),
            "B_minus_A_latency_p95_relative": round(latency_delta, 6),
        },
        "mode_metrics": by_mode,
        "note": manifest.get("production_comparability_note"),
    }


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    verdict_labels = {
        "proxy_only": "PROXY ONLY - chưa dùng để kết luận production",
        "needs_optimization": "NEEDS OPTIMIZATION",
        "pass": "PASS",
    }
    lines = [
        "# Báo cáo thí nghiệm metadata retrieval",
        "",
        f"Kết luận: **{verdict_labels[report['verdict']]}**",
        "",
        f"Embedding: `{report.get('embedding_provider')}` / `{report.get('embedding_model')}`",
        f"Số câu hỏi: {report.get('query_count')}",
        f"Ghi chú: {report.get('note') or ''}",
        "",
        "## So sánh chính",
        "",
        "| So sánh | Recall@5 delta |",
        "|---|---:|",
        f"| B - A | {_fmt(report['key_deltas']['B_minus_A_recall_at_5'])} |",
        f"| B - C | {_fmt(report['key_deltas']['B_minus_C_recall_at_5'])} |",
        f"| D - B | {_fmt(report['key_deltas']['D_minus_B_recall_at_5'])} |",
        "",
        "## Quality gates",
        "",
        "| Gate | Trạng thái | Giá trị | Yêu cầu |",
        "|---|---|---|---|",
    ]
    for gate in report["gates"]:
        status = "PASS" if gate["passed"] else "FAIL"
        actual = (
            json.dumps(gate["actual"], ensure_ascii=False)
            if isinstance(gate["actual"], dict)
            else _fmt(gate["actual"])
        )
        lines.append(f"| {gate['name']} | {status} | {actual} | {gate['expected']} |")
    lines.extend(
        [
            "",
            "## Cách đọc",
            "",
            "- B - A đo lợi ích của metadata hiện tại so với chunk thô.",
            "- B - C xác nhận lợi ích đến từ ý nghĩa metadata, không chỉ do input dài hơn.",
            "- D - B cho biết dư địa cải thiện nếu metadata được chuẩn hóa tốt hơn.",
            (
                "- Kết quả hashing chỉ dùng kiểm tra pipeline; "
                "hãy chạy OpenAI trước khi ra quyết định."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--metrics-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics_dir = args.metrics_dir or (args.run_dir / "metrics")
    manifest_path = args.run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary_rows = _read_csv(metrics_dir / "retrieval_metric_summary.csv")
    comparison_rows = _read_csv(metrics_dir / "retrieval_metric_comparison.csv")
    report = build_report(
        summary_rows=summary_rows,
        comparison_rows=comparison_rows,
        manifest=manifest,
    )
    json_path = args.run_dir / "experiment_verdict.json"
    markdown_path = args.run_dir / "experiment_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Verdict={report['verdict']} failed_gates={report['failed_gate_count']}")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


if __name__ == "__main__":
    main()
