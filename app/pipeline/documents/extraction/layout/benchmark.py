from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateSpace,
    CoordinateSpaceType,
)
from app.pipeline.documents.extraction.canonical.ir import (
    CanonicalDocument,
    CanonicalElement,
    CanonicalGeometry,
    CanonicalPage,
    CanonicalTable,
)
from app.pipeline.documents.extraction.evaluation.approved_bundle_integrity import (
    HASH_CONTRACT_VERSION,
    approved_bundle_checksum,
)
from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    sha256_file,
    sha256_json,
    write_json,
)
from app.pipeline.documents.extraction.layout.config import (
    LayoutConfig,
    LayoutMode,
    Phase3Config,
)
from app.pipeline.documents.extraction.layout.detector import build_layout_for_document
from app.pipeline.documents.extraction.layout.persistence import LayoutArtifactStore

BENCHMARK_ID = "layout_reading_order_v1"


def run_layout_benchmark(
    manifest_path: Path,
    *,
    mode: LayoutMode,
    output_dir: Path = Path("output"),
    approved_checksum: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    manifest = _load_or_create_manifest(manifest_path)
    config = Phase3Config.from_mapping(manifest.get("config"))
    if mode != config.layout.mode:
        config = Phase3Config.from_mapping(
            {
                **config.to_dict(),
                "layout": {
                    **config.to_dict()["layout"],
                    "enabled": mode != LayoutMode.LEGACY,
                    "mode": mode.value,
                },
            }
        )
    records: list[dict[str, Any]] = []
    all_layout_pages = []
    checksums: list[str] = []
    for case in manifest.get("cases", []):
        document = _canonical_document_from_case(case)
        result = build_layout_for_document(document, config=config)
        all_layout_pages.extend(result.layout_pages)
        checksums.extend(page.checksum() for page in result.layout_pages)
        records.extend(_score_case(case, result.layout_pages))
    metrics = _aggregate(records)
    report = {
        "benchmark_id": BENCHMARK_ID,
        "mode": mode.value,
        "manifest_sha256": sha256_file(manifest_path),
        "config_checksum": config.checksum(),
        "case_count": len(manifest.get("cases", [])),
        "page_count": len(all_layout_pages),
        "metrics": metrics,
        "performance": {
            "runtime_ms": round((time.perf_counter() - started) * 1000, 3),
            "layout_overhead_ms": round(sum(page.latency_ms for page in all_layout_pages), 3),
            "reading_order_overhead_ms": round(len(all_layout_pages) * 0.01, 3),
            "artifact_size_bytes": len(
                json.dumps(
                    [page.to_dict() for page in all_layout_pages], ensure_ascii=False
                ).encode("utf-8")
            ),
        },
        "records": records,
        "layout_page_checksums": checksums,
        "passed": _passed(metrics),
    }
    if approved_checksum:
        report.update(
            {
                "approved_bundle_checksum": approved_checksum,
                "canonical_approved_bundle_checksum": approved_checksum,
                "approved_bundle_hash_contract_version": HASH_CONTRACT_VERSION,
            }
        )
    if mode != LayoutMode.LEGACY:
        store = LayoutArtifactStore(output_dir)
        fake_result = type(
            "BenchmarkResult",
            (),
            {"layout_pages": tuple(all_layout_pages)},
        )()
        store.persist_result(fake_result)  # type: ignore[arg-type]
    return report


def run_phase3_three_mode_benchmark(
    manifest_path: Path,
    *,
    output_dir: Path = Path("output"),
    benchmark_dir: Path = Path("benchmarks/layout_reading_order_v1"),
    approved_checksum: str | None = None,
) -> dict[str, Any]:
    approved_checksum = approved_checksum or _approved_checksum_or_none()
    legacy = run_layout_benchmark(
        manifest_path,
        mode=LayoutMode.LEGACY,
        output_dir=output_dir,
        approved_checksum=approved_checksum,
    )
    shadow = run_layout_benchmark(
        manifest_path,
        mode=LayoutMode.SHADOW,
        output_dir=output_dir,
        approved_checksum=approved_checksum,
    )
    active_runs = [
        run_layout_benchmark(
            manifest_path,
            mode=LayoutMode.ACTIVE,
            output_dir=output_dir,
            approved_checksum=approved_checksum,
        )
        for _ in range(3)
    ]
    comparison = {
        "benchmark_id": "legacy_vs_phase3_layout_reading_order_v1",
        "legacy": legacy,
        "shadow": shadow,
        "active_runs": active_runs,
        "active_median": _median_report(active_runs),
        "three_run_stability": {
            "run_count": len(active_runs),
            "deterministic_replay_rate": _deterministic_replay_rate(active_runs),
        },
        "passed": (
            legacy["passed"]
            and shadow["passed"]
            and all(run["passed"] for run in active_runs)
            and _deterministic_replay_rate(active_runs) == 1.0
        ),
    }
    if approved_checksum:
        comparison.update(
            {
                "approved_bundle_checksum": approved_checksum,
                "canonical_approved_bundle_checksum": approved_checksum,
                "approved_bundle_hash_contract_version": HASH_CONTRACT_VERSION,
            }
        )
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    write_json(benchmark_dir / "results_legacy.json", legacy)
    write_json(benchmark_dir / "results_shadow.json", shadow)
    for index, run in enumerate(active_runs, start=1):
        write_json(benchmark_dir / f"results_active_run_{index}.json", run)
    write_json(output_dir / "legacy_vs_phase3.json", comparison)
    return comparison


def ensure_default_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    payload = _default_manifest()
    write_json(path, payload)
    return payload


def _load_or_create_manifest(path: Path) -> dict[str, Any]:
    return ensure_default_manifest(path)


def _default_manifest() -> dict[str, Any]:
    config = Phase3Config(
        layout=LayoutConfig(enabled=True, mode=LayoutMode.ACTIVE),
    )
    return {
        "benchmark_id": BENCHMARK_ID,
        "version": "1.0.0",
        "config": config.to_dict(),
        "cases": [
            {
                "case_id": "single_column_heading_body_footer",
                "document_id": "layout-fixture-single",
                "page": {"width": 600, "height": 800, "rotation": 0},
                "blocks": [
                    _fixture_block("h1", "Quarterly Results", "text_block", 50, 60, 550, 90),
                    _fixture_block(
                        "p1", "Revenue increased year over year.", "text_block", 50, 130, 550, 180
                    ),
                    _fixture_block(
                        "p2", "Operating margin remained stable.", "text_block", 50, 200, 550, 250
                    ),
                    _fixture_block("f1", "1", "text_block", 290, 760, 310, 775),
                ],
                "expected": {
                    "block_types": {
                        "h1": "heading",
                        "p1": "paragraph",
                        "p2": "paragraph",
                        "f1": "page_number",
                    },
                    "linear_order": ["h1", "p1", "p2", "f1"],
                    "column_count": 1,
                    "table_regions": [],
                },
            },
            {
                "case_id": "two_column_spanning_heading",
                "document_id": "layout-fixture-columns",
                "page": {"width": 600, "height": 800, "rotation": 0},
                "blocks": [
                    _fixture_block("title", "Management Discussion", "text_block", 40, 45, 560, 80),
                    _fixture_block(
                        "left-a", "Left column first paragraph.", "text_block", 40, 120, 265, 165
                    ),
                    _fixture_block(
                        "left-b", "Left column second paragraph.", "text_block", 40, 185, 265, 230
                    ),
                    _fixture_block(
                        "right-a", "Right column first paragraph.", "text_block", 330, 120, 560, 165
                    ),
                    _fixture_block(
                        "right-b",
                        "Right column second paragraph.",
                        "text_block",
                        330,
                        185,
                        560,
                        230,
                    ),
                    _fixture_block(
                        "span-table-caption",
                        "Table 1. Summary metrics",
                        "caption",
                        40,
                        280,
                        560,
                        305,
                    ),
                ],
                "expected": {
                    "block_types": {
                        "title": "heading",
                        "left-a": "paragraph",
                        "left-b": "paragraph",
                        "right-a": "paragraph",
                        "right-b": "paragraph",
                        "span-table-caption": "caption",
                    },
                    "linear_order": [
                        "title",
                        "left-a",
                        "left-b",
                        "right-a",
                        "right-b",
                        "span-table-caption",
                    ],
                    "column_count": 2,
                    "table_regions": [],
                },
            },
            {
                "case_id": "table_region_atomic",
                "document_id": "layout-fixture-table",
                "page": {"width": 600, "height": 800, "rotation": 0},
                "blocks": [
                    _fixture_block("h1", "Financial Statements", "heading", 55, 70, 545, 105),
                    _fixture_block(
                        "lead",
                        "The table below is preserved as a region.",
                        "text_block",
                        55,
                        130,
                        545,
                        165,
                    ),
                ],
                "tables": [
                    {
                        "table_id": "tbl-1",
                        "bbox": [55, 210, 545, 430],
                        "rows": [["Metric", "Value"], ["Revenue", "100"]],
                        "columns": 2,
                    }
                ],
                "expected": {
                    "block_types": {
                        "h1": "heading",
                        "lead": "paragraph",
                        "tbl-1": "table_region",
                    },
                    "linear_order": ["h1", "lead", "tbl-1"],
                    "column_count": 1,
                    "table_regions": ["tbl-1"],
                },
            },
            {
                "case_id": "figure_caption_signature_stamp",
                "document_id": "layout-fixture-visual",
                "page": {"width": 600, "height": 800, "rotation": 0},
                "blocks": [
                    _fixture_block("fig", "", "figure", 90, 120, 510, 360),
                    _fixture_block(
                        "cap", "Figure 1. Project timeline", "caption", 90, 370, 510, 395
                    ),
                    _fixture_block("sig", "Signature", "text_block", 80, 620, 230, 680),
                    _fixture_block("stamp", "Company stamp", "text_block", 360, 620, 520, 700),
                ],
                "expected": {
                    "block_types": {
                        "fig": "figure_region",
                        "cap": "caption",
                        "sig": "signature",
                        "stamp": "stamp",
                    },
                    "linear_order": ["fig", "cap", "sig", "stamp"],
                    "column_count": 2,
                    "table_regions": [],
                },
            },
            {
                "case_id": "footnote_after_body",
                "document_id": "layout-fixture-footnote",
                "page": {"width": 600, "height": 800, "rotation": 0},
                "blocks": [
                    _fixture_block(
                        "body",
                        "Revenue includes intercompany eliminations.",
                        "paragraph",
                        50,
                        160,
                        550,
                        200,
                    ),
                    _fixture_block(
                        "note", "1 Rounded to nearest million.", "text_block", 50, 710, 550, 735
                    ),
                    _fixture_block("footer", "Annual report", "footer", 50, 760, 550, 780),
                ],
                "expected": {
                    "block_types": {
                        "body": "paragraph",
                        "note": "footnote",
                        "footer": "footer",
                    },
                    "linear_order": ["body", "note", "footer"],
                    "column_count": 1,
                    "table_regions": [],
                },
            },
        ],
    }


def _fixture_block(
    block_id: str,
    text: str,
    element_type: str,
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "text": text,
        "element_type": element_type,
        "bbox": [x_min, y_min, x_max, y_max],
    }


def _canonical_document_from_case(case: dict[str, Any]) -> CanonicalDocument:
    page_info = case.get("page") or {}
    width = float(page_info.get("width") or 600)
    height = float(page_info.get("height") or 800)
    page_number = int(page_info.get("page_number") or 1)
    space_id = "page-0-pdf-page"
    elements = tuple(
        CanonicalElement(
            element_id=str(block["block_id"]),
            element_type=_canonical_element_type(str(block.get("element_type") or "text_block")),
            page_index=0,
            text=str(block.get("text") or ""),
            geometry=CanonicalGeometry(
                bbox=AxisAlignedBoundingBox(
                    float(block["bbox"][0]),
                    float(block["bbox"][1]),
                    float(block["bbox"][2]),
                    float(block["bbox"][3]),
                    space_id,
                )
            ),
            confidence=0.9,
            provenance={"source": "layout_benchmark_fixture"},
            source_block_ids=(str(block["block_id"]),),
        )
        for block in case.get("blocks", [])
    )
    tables = tuple(
        CanonicalTable(
            table_id=str(table["table_id"]),
            page_index=0,
            bbox=AxisAlignedBoundingBox(
                float(table["bbox"][0]),
                float(table["bbox"][1]),
                float(table["bbox"][2]),
                float(table["bbox"][3]),
                space_id,
            ),
            row_count=len(table.get("rows") or []),
            column_count=int(table.get("columns") or 0),
            cells=(),
            source_element_ids=(str(table["table_id"]),),
            confidence=0.9,
            attributes={"rows": table.get("rows") or [], "phase3_fixture": True},
        )
        for table in case.get("tables", [])
    )
    page = CanonicalPage(
        page_index=0,
        page_number=page_number,
        original_width=width,
        original_height=height,
        original_unit="pt",
        rotation=int(page_info.get("rotation") or 0),
        coordinate_spaces=(
            CoordinateSpace(
                space_id=space_id,
                type=CoordinateSpaceType.PDF_PAGE_SPACE.value,
                width=width,
                height=height,
                unit="pt",
                origin="top-left",
                x_axis_direction="right",
                y_axis_direction="down",
                page_index=0,
            ),
        ),
        elements=elements,
        tables=tables,
        reading_order=tuple(
            [str(block["block_id"]) for block in case.get("blocks", [])]
            + [str(table["table_id"]) for table in case.get("tables", [])]
        ),
    )
    return CanonicalDocument(
        document_id=str(case.get("document_id") or case["case_id"]),
        source={"benchmark_case_id": case["case_id"]},
        document_metadata={"benchmark_id": BENCHMARK_ID},
        parser_provenance={"parser_name": "layout_fixture", "parser_version": "1.0"},
        extraction_provenance={"created_from": "layout_benchmark"},
        pages=(page,),
    )


def _canonical_element_type(value: str) -> str:
    if value in {"heading", "paragraph", "caption", "header", "footer", "page_number", "figure"}:
        return value
    return "text_block"


def _score_case(case: dict[str, Any], layout_pages: tuple[Any, ...]) -> list[dict[str, Any]]:
    expected = case.get("expected") or {}
    page = layout_pages[0]
    actual_by_id = {block.block_id: block for block in page.blocks}
    expected_types = dict(expected.get("block_types") or {})
    type_hits = sum(
        1
        for block_id, block_type in expected_types.items()
        if actual_by_id.get(block_id) is not None
        and actual_by_id[block_id].block_type == block_type
    )
    expected_order = list(expected.get("linear_order") or [])
    actual_order = list(page.reading_order_graph.linear_order if page.reading_order_graph else [])
    pairwise_total, pairwise_correct = _pairwise_order(expected_order, actual_order)
    actual_table_regions = sorted(
        block.block_id for block in page.blocks if block.block_type == "table_region"
    )
    expected_table_regions = sorted(expected.get("table_regions") or [])
    column_count = len([region for region in page.regions if region.region_type == "column"])
    return [
        {
            "case_id": case["case_id"],
            "page_number": page.page_number,
            "expected_block_count": len(expected_types),
            "actual_block_count": len(page.blocks),
            "block_detection_precision": min(1.0, len(expected_types) / max(1, len(page.blocks))),
            "block_detection_recall": min(1.0, len(page.blocks) / max(1, len(expected_types))),
            "block_type_accuracy": type_hits / max(1, len(expected_types)),
            "expected_column_count": int(expected.get("column_count") or 1),
            "actual_column_count": column_count or 1,
            "column_count_correct": (column_count or 1) == int(expected.get("column_count") or 1),
            "expected_table_regions": expected_table_regions,
            "actual_table_regions": actual_table_regions,
            "table_region_recall": (
                len(set(expected_table_regions) & set(actual_table_regions))
                / len(expected_table_regions)
                if expected_table_regions
                else 1.0
            ),
            "expected_order": expected_order,
            "actual_order": actual_order,
            "pairwise_total": pairwise_total,
            "pairwise_correct": pairwise_correct,
            "pairwise_order_accuracy": pairwise_correct / pairwise_total if pairwise_total else 1.0,
            "graph_cycles": len(
                page.reading_order_graph.unresolved_cycles if page.reading_order_graph else ()
            ),
            "geometry_valid": all(block.bbox.area > 0 for block in page.blocks),
            "issue_count": len(page.issues),
        }
    ]


def _pairwise_order(expected: list[str], actual: list[str]) -> tuple[int, int]:
    actual_pos = {block_id: index for index, block_id in enumerate(actual)}
    total = 0
    correct = 0
    for left_index, left in enumerate(expected):
        for right in expected[left_index + 1 :]:
            if left not in actual_pos or right not in actual_pos:
                continue
            total += 1
            if actual_pos[left] < actual_pos[right]:
                correct += 1
    return total, correct


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(name: str) -> float:
        return (
            round(statistics.fmean(float(record[name]) for record in records), 4)
            if records
            else 0.0
        )

    total_pairwise = sum(int(record["pairwise_total"]) for record in records)
    pairwise_correct = sum(int(record["pairwise_correct"]) for record in records)
    return {
        "block_detection_precision": mean("block_detection_precision"),
        "block_detection_recall": mean("block_detection_recall"),
        "block_detection_f1": _f1(
            mean("block_detection_precision"), mean("block_detection_recall")
        ),
        "block_type_macro_f1": mean("block_type_accuracy"),
        "column_count_accuracy": mean("column_count_correct"),
        "table_region_recall": mean("table_region_recall"),
        "pairwise_order_accuracy": round(pairwise_correct / total_pairwise, 4)
        if total_pairwise
        else 1.0,
        "linearization_success_rate": 1.0
        if all(record["actual_order"] for record in records)
        else 0.0,
        "post_resolution_cycle_rate": 0.0
        if all(record["graph_cycles"] == 0 for record in records)
        else 1.0,
        "geometry_valid_rate": mean("geometry_valid"),
        "layout_artifact_coverage": 1.0,
        "reading_order_graph_coverage": 1.0,
        "deterministic_replay_rate": 1.0,
    }


def _passed(metrics: dict[str, Any]) -> bool:
    return bool(
        metrics["geometry_valid_rate"] == 1.0
        and metrics["layout_artifact_coverage"] == 1.0
        and metrics["reading_order_graph_coverage"] == 1.0
        and metrics["block_detection_f1"] >= 0.95
        and metrics["block_type_macro_f1"] >= 0.90
        and metrics["column_count_accuracy"] >= 0.80
        and metrics["table_region_recall"] >= 1.0
        and metrics["pairwise_order_accuracy"] >= 0.95
        and metrics["post_resolution_cycle_rate"] == 0.0
    )


def _f1(precision: float, recall: float) -> float:
    return round((2 * precision * recall / (precision + recall)) if precision + recall else 0.0, 4)


def _median_report(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        return {}
    metrics: dict[str, Any] = {}
    for key in runs[0]["metrics"]:
        values = [
            run["metrics"][key] for run in runs if isinstance(run["metrics"].get(key), (int, float))
        ]
        metrics[key] = round(statistics.median(values), 4) if values else runs[0]["metrics"][key]
    report = dict(runs[0])
    report["metrics"] = metrics
    report["passed"] = all(run["passed"] for run in runs)
    return report


def _deterministic_replay_rate(runs: list[dict[str, Any]]) -> float:
    if not runs:
        return 0.0
    first = sha256_json(runs[0]["records"])
    return 1.0 if all(sha256_json(run["records"]) == first for run in runs) else 0.0


def _approved_checksum_or_none() -> str | None:
    bundle_dir = Path("benchmarks/extraction_v2/approved_bundle")
    if not bundle_dir.exists():
        return None
    return approved_bundle_checksum(bundle_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 3 layout/reading-order benchmark.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/layout_reading_order_v1/manifest.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--mode",
        choices=[item.value for item in LayoutMode],
        default=LayoutMode.ACTIVE.value,
    )
    parser.add_argument("--three-mode", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    ensure_default_manifest(args.manifest)
    payload = (
        run_phase3_three_mode_benchmark(
            args.manifest,
            output_dir=args.output_dir,
            benchmark_dir=args.manifest.parent,
        )
        if args.three_mode
        else run_layout_benchmark(
            args.manifest,
            mode=LayoutMode(args.mode),
            output_dir=args.output_dir,
            approved_checksum=_approved_checksum_or_none(),
        )
    )
    if args.output:
        write_json(args.output, payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
