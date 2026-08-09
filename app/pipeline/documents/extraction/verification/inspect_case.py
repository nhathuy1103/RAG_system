from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import write_json
from app.pipeline.documents.extraction.verification.persistence import read_jsonl


def inspect_verification_cases(
    *,
    output_dir: Path = Path("output/phase5_visual_overlays"),
    cases_path: Path = Path("output/verification_cases.jsonl"),
    decisions_path: Path = Path("output/arbitration_decisions.jsonl"),
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = read_jsonl(cases_path)
    decisions = {item["case_id"]: item for item in read_jsonl(decisions_path)}
    overlays: list[str] = []
    for index, case in enumerate(cases[:50], start=1):
        bbox = dict(case.get("bbox") or {})
        width = max(float(bbox.get("x_max", 360)) - float(bbox.get("x_min", 0)), 120.0)
        height = max(float(bbox.get("y_max", 80)) - float(bbox.get("y_min", 0)), 60.0)
        decision = decisions.get(case["case_id"], {})
        color = "#198754" if decision.get("status") == "accepted" else "#b54708"
        svg = _svg(
            width=width,
            height=height,
            color=color,
            label=f"{case['case_id']} {decision.get('status', 'missing')}",
        )
        path = output_dir / f"{index:02d}_{case['case_id']}.svg"
        path.write_text(svg, encoding="utf-8")
        overlays.append(str(path))
    report = {
        "status": "PASS" if cases and len(decisions) == len(cases) else "FAIL",
        "case_count": len(cases),
        "decision_count": len(decisions),
        "overlays": overlays,
    }
    write_json(output_dir / "inspection_report.json", report)
    return report


def _svg(*, width: float, height: float, color: str, label: str) -> str:
    safe_label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">\n'
        '<rect x="1" y="1" width="98%" height="96%" fill="none" '
        f'stroke="{color}" stroke-width="2"/>\n'
        f'<text x="8" y="22" font-family="Arial" font-size="12" fill="{color}">'
        f"{safe_label}</text>\n"
        "</svg>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Phase 5 verification cases.")
    parser.add_argument("--output-dir", type=Path, default=Path("output/phase5_visual_overlays"))
    parser.add_argument("--cases", type=Path, default=Path("output/verification_cases.jsonl"))
    parser.add_argument(
        "--decisions", type=Path, default=Path("output/arbitration_decisions.jsonl")
    )
    args = parser.parse_args()
    report = inspect_verification_cases(
        output_dir=args.output_dir,
        cases_path=args.cases,
        decisions_path=args.decisions,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
