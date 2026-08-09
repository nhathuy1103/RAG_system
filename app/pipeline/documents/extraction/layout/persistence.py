from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import write_jsonl
from app.pipeline.documents.extraction.layout.detector import LayoutDocumentResult
from app.pipeline.documents.extraction.layout.models import (
    LayoutIssue,
    LayoutPage,
    LayoutRegion,
    ReadingOrderGraph,
)


@dataclass(frozen=True)
class Phase3LayoutArtifact:
    reference: str
    checksum: str
    created_at: str
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "checksum": self.checksum,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class LayoutArtifactStore:
    output_dir: Path = Path("output")

    @property
    def layout_pages_path(self) -> Path:
        return self.output_dir / "layout_pages.jsonl"

    @property
    def regions_path(self) -> Path:
        return self.output_dir / "layout_regions.jsonl"

    @property
    def blocks_path(self) -> Path:
        return self.output_dir / "layout_blocks.jsonl"

    @property
    def graphs_path(self) -> Path:
        return self.output_dir / "reading_order_graphs.jsonl"

    @property
    def issues_path(self) -> Path:
        return self.output_dir / "layout_issues.jsonl"

    def persist_result(self, result: LayoutDocumentResult) -> None:
        pages = list(result.layout_pages)
        write_jsonl_atomic(self.layout_pages_path, [page.to_dict() for page in pages])
        write_jsonl_atomic(
            self.regions_path,
            [region.to_dict() for page in pages for region in page.regions],
        )
        write_jsonl_atomic(
            self.blocks_path,
            [block.to_dict() for page in pages for block in page.blocks],
        )
        write_jsonl_atomic(
            self.graphs_path,
            [
                page.reading_order_graph.to_dict()
                for page in pages
                if page.reading_order_graph is not None
            ],
        )
        write_jsonl_atomic(
            self.issues_path,
            [issue.to_dict() for page in pages for issue in page.issues],
        )


def build_layout_artifact(result: LayoutDocumentResult, *, attempt_id: str) -> Phase3LayoutArtifact:
    payload = {
        "artifact_type": "phase3_layout_reading_order",
        "attempt_id": attempt_id,
        "mode": result.mode.value,
        "config_checksum": result.config_checksum,
        "layout_pages": [page.to_dict() for page in result.layout_pages],
        "comparison": result.comparison,
        "performance": result.performance,
    }
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return Phase3LayoutArtifact(
        reference=f"phase3-layout:{attempt_id}:{checksum[:16]}",
        checksum=checksum,
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        payload_json=payload_json,
    )


def persist_layout_artifact(
    storage: Any,
    *,
    tenant_id: str,
    owner_id: str,
    document_id: str,
    version: int,
    attempt_id: str,
    result: LayoutDocumentResult,
) -> Phase3LayoutArtifact:
    built = build_layout_artifact(result, attempt_id=attempt_id)
    if hasattr(storage, "save_bytes"):
        stored = storage.save_bytes(
            tenant_id=tenant_id,
            owner_id=owner_id,
            document_id=document_id,
            version=version,
            filename=f"phase3-layout-{attempt_id}.json",
            content=built.payload_json.encode("utf-8"),
        )
        return Phase3LayoutArtifact(
            reference=getattr(stored, "storage_path", built.reference),
            checksum=built.checksum,
            created_at=built.created_at,
            payload_json=built.payload_json,
        )
    return built


def read_layout_pages(path: Path) -> list[LayoutPage]:
    return [LayoutPage.from_mapping(item) for item in _read_jsonl(path)]


def read_layout_regions(path: Path) -> list[LayoutRegion]:
    return [LayoutRegion.from_mapping(item) for item in _read_jsonl(path)]


def read_reading_order_graphs(path: Path) -> list[ReadingOrderGraph]:
    return [ReadingOrderGraph.from_mapping(item) for item in _read_jsonl(path)]


def read_layout_issues(path: Path) -> list[LayoutIssue]:
    return [LayoutIssue.from_mapping(item) for item in _read_jsonl(path)]


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    write_jsonl(tmp_path, rows)
    os.replace(tmp_path, path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


__all__ = [
    "LayoutArtifactStore",
    "Phase3LayoutArtifact",
    "build_layout_artifact",
    "persist_layout_artifact",
    "read_layout_issues",
    "read_layout_pages",
    "read_layout_regions",
    "read_reading_order_graphs",
]
