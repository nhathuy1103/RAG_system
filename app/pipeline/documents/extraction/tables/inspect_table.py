from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.tables.persistence import read_structured_tables


def inspect_table(
    *,
    table_id: str | None = None,
    output_dir: Path = Path("output/phase4_visual_overlays"),
    structured_tables_path: Path = Path("output/structured_tables.jsonl"),
) -> dict[str, Any]:
    tables = read_structured_tables(structured_tables_path)
    selected = [table for table in tables if table_id is None or table.table_id == table_id]
    output_dir.mkdir(parents=True, exist_ok=True)
    overlays: list[str] = []
    for table in selected:
        path = output_dir / f"{_safe_name(table.table_id)}.svg"
        path.write_text(_table_svg(table), encoding="utf-8")
        overlays.append(str(path))
    report = {
        "status": "PASS" if selected else "NO_TABLES",
        "table_count": len(selected),
        "overlay_count": len(overlays),
        "overlays": overlays,
    }
    report_path = output_dir / "inspection_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["json_report"] = str(report_path)
    return report


def _table_svg(table: Any) -> str:
    bbox = table.bbox
    width = max(1.0, bbox.width + 80)
    height = max(1.0, bbox.height + 80)
    offset_x = 40 - bbox.x_min
    offset_y = 40 - bbox.y_min

    def rect(item: Any, color: str, stroke_width: float = 1.0, fill: str = "none") -> str:
        return (
            f'<rect x="{item.x_min + offset_x:.2f}" y="{item.y_min + offset_y:.2f}" '
            f'width="{item.width:.2f}" height="{item.height:.2f}" '
            f'fill="{fill}" stroke="{color}" stroke-width="{stroke_width:.2f}" />'
        )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#ffffff" />',
        rect(bbox, "#111827", 2.0),
        f'<text x="16" y="22" font-family="Arial" font-size="14" fill="#111827">{_escape(table.table_id)} | {_escape(table.table_type)}</text>',
    ]
    for row in table.rows:
        parts.append(rect(row.bbox, "#2563eb", 0.8))
    for column in table.columns:
        parts.append(rect(column.bbox, "#059669", 0.8))
    for cell in table.cells:
        parts.append(rect(cell.bbox, "#dc2626", 0.7, "rgba(220,38,38,0.04)"))
        parts.append(
            f'<text x="{cell.bbox.x_min + offset_x + 3:.2f}" y="{cell.bbox.y_min + offset_y + 13:.2f}" '
            f'font-family="Arial" font-size="10" fill="#374151">{_escape(cell.normalized_text[:24])}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Phase 4 table artifacts.")
    parser.add_argument("--table-id")
    parser.add_argument("--output-dir", type=Path, default=Path("output/phase4_visual_overlays"))
    parser.add_argument(
        "--structured-tables", type=Path, default=Path("output/structured_tables.jsonl")
    )
    args = parser.parse_args()
    report = inspect_table(
        table_id=args.table_id,
        output_dir=args.output_dir,
        structured_tables_path=args.structured_tables,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
