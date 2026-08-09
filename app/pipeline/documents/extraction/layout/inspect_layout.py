from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.canonical.serialization import read_canonical_document
from app.pipeline.documents.extraction.layout.config import LayoutConfig, LayoutMode, Phase3Config
from app.pipeline.documents.extraction.layout.detector import build_layout_for_document
from app.pipeline.documents.extraction.layout.models import LayoutPage
from app.pipeline.documents.extraction.layout.persistence import read_layout_pages


def inspect_layout(
    *,
    document_id: str,
    page_number: int,
    output_dir: Path,
    artifact: Path | None = None,
    layout_pages_path: Path = Path("output/layout_pages.jsonl"),
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if artifact is not None:
        document = read_canonical_document(artifact)
        config = Phase3Config(layout=LayoutConfig(enabled=True, mode=LayoutMode.SHADOW))
        result = build_layout_for_document(document, config=config)
        page = next(item for item in result.layout_pages if item.page_number == page_number)
    else:
        page = next(
            item
            for item in read_layout_pages(layout_pages_path)
            if item.document_id == document_id and item.page_number == page_number
        )
    report = _write_visuals(page, output_dir=output_dir)
    (output_dir / "layout_inspection_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _write_visuals(page: LayoutPage, *, output_dir: Path) -> dict[str, Any]:
    source_path = output_dir / "source_image.svg"
    raw_native_path = output_dir / "raw_native_overlay.svg"
    raw_ocr_path = output_dir / "raw_ocr_overlay.svg"
    reconciled_path = output_dir / "reconciled_blocks_overlay.svg"
    region_path = output_dir / "region_overlay.svg"
    type_path = output_dir / "block_type_overlay.svg"
    arrows_path = output_dir / "reading_order_arrows.svg"
    rejected_path = output_dir / "rejected_conflicting_edges.svg"
    _write_svg(source_path, page, mode="source")
    _write_svg(raw_native_path, page, mode="native")
    _write_svg(raw_ocr_path, page, mode="ocr")
    _write_svg(reconciled_path, page, mode="blocks")
    _write_svg(region_path, page, mode="regions")
    _write_svg(type_path, page, mode="types")
    _write_svg(arrows_path, page, mode="arrows")
    _write_svg(rejected_path, page, mode="rejected")
    return {
        "document_id": page.document_id,
        "page_number": page.page_number,
        "schema_version": page.schema_version,
        "layout_page_checksum": page.checksum(),
        "source_image": str(source_path),
        "raw_native_overlay": str(raw_native_path),
        "raw_ocr_overlay": str(raw_ocr_path),
        "reconciled_blocks_overlay": str(reconciled_path),
        "region_overlay": str(region_path),
        "block_type_overlay": str(type_path),
        "reading_order_arrows": str(arrows_path),
        "rejected_conflicting_edges": str(rejected_path),
        "json_report": str(output_dir / "layout_inspection_report.json"),
        "block_count": len(page.blocks),
        "region_count": len(page.regions),
        "issue_count": len(page.issues),
    }


def _write_svg(path: Path, page: LayoutPage, *, mode: str) -> None:
    colors = {
        "paragraph": "#2563eb",
        "heading": "#7c3aed",
        "title": "#7c3aed",
        "caption": "#0891b2",
        "table_region": "#dc2626",
        "figure_region": "#16a34a",
        "header": "#6b7280",
        "footer": "#6b7280",
        "footnote": "#b45309",
        "signature": "#be185d",
        "stamp": "#b91c1c",
    }
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page.page_width}" height="{page.page_height}" viewBox="0 0 {page.page_width} {page.page_height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#ffffff" stroke="#111827" stroke-width="1"/>',
    ]
    if mode in {"native", "ocr", "blocks", "types"}:
        for block in page.blocks:
            if mode == "native" and block.source != "native":
                continue
            if mode == "ocr" and block.source != "ocr":
                continue
            color = colors.get(block.block_type, "#111827")
            lines.append(
                f'<rect x="{block.bbox.x_min}" y="{block.bbox.y_min}" width="{block.bbox.width}" height="{block.bbox.height}" fill="none" stroke="{color}" stroke-width="2"/>'
            )
            label = block.block_type if mode == "types" else block.block_id
            lines.append(
                f'<text x="{block.bbox.x_min + 3}" y="{max(12, block.bbox.y_min - 3)}" font-size="10" fill="{color}">{_escape(label)}</text>'
            )
    if mode == "regions":
        for region in page.regions:
            color = "#0f766e" if region.region_type in {"column", "body"} else "#9333ea"
            lines.append(
                f'<rect x="{region.bbox.x_min}" y="{region.bbox.y_min}" width="{region.bbox.width}" height="{region.bbox.height}" fill="none" stroke="{color}" stroke-width="1.5" stroke-dasharray="5 3"/>'
            )
            lines.append(
                f'<text x="{region.bbox.x_min + 3}" y="{max(12, region.bbox.y_min + 12)}" font-size="10" fill="{color}">{_escape(region.region_type)}</text>'
            )
    if mode == "arrows" and page.reading_order_graph is not None:
        by_id = {block.block_id: block for block in page.blocks}
        for edge in page.reading_order_graph.edges:
            if (
                edge.relation != "before"
                or edge.source_id not in by_id
                or edge.target_id not in by_id
            ):
                continue
            source = by_id[edge.source_id].bbox
            target = by_id[edge.target_id].bbox
            lines.append(
                f'<line x1="{source.x_max}" y1="{(source.y_min + source.y_max) / 2}" x2="{target.x_min}" y2="{(target.y_min + target.y_max) / 2}" stroke="#f97316" stroke-width="2" marker-end="url(#arrow)"/>'
            )
    if mode == "rejected" and page.reading_order_graph is not None:
        for edge in page.reading_order_graph.rejected_edges:
            lines.append(
                f'<text x="16" y="24" font-size="12" fill="#b91c1c">{_escape(edge.edge_id)}</text>'
            )
    lines.insert(
        1,
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="5" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#f97316"/></marker></defs>',
    )
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Phase 3 layout artifacts.")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--layout-pages", type=Path, default=Path("output/layout_pages.jsonl"))
    args = parser.parse_args()
    report = inspect_layout(
        document_id=args.document_id,
        page_number=args.page,
        output_dir=args.output,
        artifact=args.artifact,
        layout_pages_path=args.layout_pages,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
