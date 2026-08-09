from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import write_json
from app.pipeline.documents.extraction.multimodal.models import (
    MultimodalExtractionResult,
    VisualCandidate,
    VisualRegion,
)


def write_visual_inspection_overlays(
    result: MultimodalExtractionResult,
    *,
    output_dir: Path = Path("output/phase6_visual_overlays"),
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    regions = {region.candidate_id: region for region in result.regions}
    for candidate in result.candidates:
        region = regions.get(candidate.candidate_id)
        path = output_dir / f"{candidate.candidate_id}.svg"
        path.write_text(_svg_for_candidate(candidate, region), encoding="utf-8")
        written.append(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_type": candidate.candidate_type,
                "overlay_path": path.as_posix(),
                "bbox": candidate.bbox,
                "has_region": region is not None,
            }
        )
    report = {
        "status": "PASS",
        "overlay_count": len(written),
        "visual_inspection_artifact_count": len(written),
        "raw_image_bytes_exported": False,
        "overlays": written,
    }
    write_json(output_dir / "inspection_report.json", report)
    return report


def _svg_for_candidate(
    candidate: VisualCandidate,
    region: VisualRegion | None,
) -> str:
    bbox = dict(region.bbox if region is not None else candidate.bbox)
    width = max(int(float(bbox["x_max"]) + 20), 160)
    height = max(int(float(bbox["y_max"]) + 20), 120)
    label = candidate.candidate_type
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        '<rect x="0" y="0" width="100%" height="100%" fill="white"/>\n'
        f'<rect x="{bbox["x_min"]}" y="{bbox["y_min"]}" '
        f'width="{float(bbox["x_max"]) - float(bbox["x_min"])}" '
        f'height="{float(bbox["y_max"]) - float(bbox["y_min"])}" '
        'fill="none" stroke="#0B5CAD" stroke-width="2"/>\n'
        f'<text x="{bbox["x_min"]}" y="{max(float(bbox["y_min"]) - 4, 12)}" '
        'font-family="Arial" font-size="12" fill="#0B5CAD">'
        f"{_escape(label)}"
        "</text>\n"
        "</svg>\n"
    )


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Phase 6 visual overlays.")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/phase6_visual_overlays"))
    args = parser.parse_args()
    json.loads(args.artifact.read_text(encoding="utf-8"))

    raise SystemExit(
        "inspect_visual CLI expects in-memory result use in Phase 6 benchmark; "
        "use benchmark --three-mode to generate overlays."
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["write_visual_inspection_overlays"]
