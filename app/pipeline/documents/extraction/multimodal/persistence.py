from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    write_json,
    write_jsonl,
)
from app.pipeline.documents.extraction.multimodal.backends import VisualBackendRegistry
from app.pipeline.documents.extraction.multimodal.engine import MultimodalExtractionResult


@dataclass(frozen=True)
class Phase6MultimodalArtifact:
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
class MultimodalArtifactStore:
    output_dir: Path = Path("output")

    @property
    def visual_backend_registry_path(self) -> Path:
        return self.output_dir / "visual_backend_registry.json"

    def persist_result(
        self,
        result: MultimodalExtractionResult,
        *,
        registry: VisualBackendRegistry,
    ) -> None:
        write_json(self.visual_backend_registry_path, registry.to_dict())
        write_jsonl_atomic(
            self.output_dir / "visual_candidates.jsonl",
            [item.to_dict() for item in result.candidates],
        )
        write_jsonl_atomic(
            self.output_dir / "visual_assets.jsonl",
            [item.to_dict() for item in result.assets],
        )
        write_jsonl_atomic(
            self.output_dir / "visual_regions.jsonl",
            [item.to_dict() for item in result.regions],
        )
        write_jsonl_atomic(
            self.output_dir / "visual_backend_requests.jsonl",
            [item.to_dict() for item in result.requests],
        )
        write_jsonl_atomic(
            self.output_dir / "visual_backend_attempts.jsonl",
            [item.to_dict() for item in result.attempts],
        )
        write_jsonl_atomic(
            self.output_dir / "visual_backend_results.jsonl",
            [item.to_dict() for item in result.backend_results],
        )
        write_jsonl_atomic(
            self.output_dir / "figures.jsonl",
            [item.to_dict() for item in result.figures],
        )
        write_jsonl_atomic(
            self.output_dir / "figure_caption_links.jsonl",
            [item.to_dict() for item in result.caption_links],
        )
        write_jsonl_atomic(
            self.output_dir / "visual_text_blocks.jsonl",
            [item.to_dict() for item in result.visual_text_blocks],
        )
        write_jsonl_atomic(
            self.output_dir / "charts.jsonl",
            [item.to_dict() for item in result.charts],
        )
        write_jsonl_atomic(
            self.output_dir / "chart_axes.jsonl",
            [item.to_dict() for item in result.chart_axes],
        )
        write_jsonl_atomic(
            self.output_dir / "chart_legends.jsonl",
            [item.to_dict() for item in result.chart_legends],
        )
        write_jsonl_atomic(
            self.output_dir / "chart_series.jsonl",
            [item.to_dict() for item in result.chart_series],
        )
        write_jsonl_atomic(
            self.output_dir / "chart_data_points.jsonl",
            [item.to_dict() for item in result.chart_data_points],
        )
        write_jsonl_atomic(
            self.output_dir / "diagrams.jsonl",
            [item.to_dict() for item in result.diagrams],
        )
        write_jsonl_atomic(
            self.output_dir / "diagram_nodes.jsonl",
            [item.to_dict() for item in result.diagram_nodes],
        )
        write_jsonl_atomic(
            self.output_dir / "diagram_edges.jsonl",
            [item.to_dict() for item in result.diagram_edges],
        )
        write_jsonl_atomic(
            self.output_dir / "signatures.jsonl",
            [item.to_dict() for item in result.signatures],
        )
        write_jsonl_atomic(
            self.output_dir / "stamps.jsonl",
            [item.to_dict() for item in result.stamps],
        )
        write_jsonl_atomic(
            self.output_dir / "logos.jsonl",
            [item.to_dict() for item in result.logos],
        )
        write_jsonl_atomic(
            self.output_dir / "multimodal_evidence.jsonl",
            [item.to_dict() for item in result.evidence],
        )
        write_jsonl_atomic(
            self.output_dir / "multimodal_issues.jsonl",
            [item.to_dict() for item in result.issues],
        )
        write_jsonl_atomic(
            self.output_dir / "multimodal_review_packages.jsonl",
            result.review_packages,
        )
        write_jsonl_atomic(
            self.output_dir / "multimodal_results.jsonl",
            [
                {
                    "candidate_id": candidate.candidate_id,
                    "mode": result.mode,
                    "terminal": (
                        candidate.candidate_id
                        in {item.candidate_id for item in result.backend_results}
                        or candidate.candidate_id
                        in {issue.candidate_id for issue in result.issues if issue.terminal}
                    ),
                    "evidence_ids": [
                        item.evidence_id
                        for item in result.evidence
                        if item.candidate_id == candidate.candidate_id
                    ],
                    "issue_ids": [
                        item.issue_id
                        for item in result.issues
                        if item.candidate_id == candidate.candidate_id
                    ],
                }
                for candidate in result.candidates
            ],
        )


def build_multimodal_artifact(
    result: MultimodalExtractionResult,
    *,
    attempt_id: str,
) -> Phase6MultimodalArtifact:
    payload = result.to_artifact_dict()
    payload["attempt_id"] = attempt_id
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return Phase6MultimodalArtifact(
        reference=f"phase6-multimodal:{attempt_id}:{checksum[:16]}",
        checksum=checksum,
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        payload_json=payload_json,
    )


def persist_multimodal_artifact(
    storage: Any,
    *,
    tenant_id: str,
    owner_id: str,
    document_id: str,
    version: int,
    attempt_id: str,
    result: MultimodalExtractionResult,
) -> Phase6MultimodalArtifact:
    built = build_multimodal_artifact(result, attempt_id=attempt_id)
    if hasattr(storage, "save_bytes"):
        stored = storage.save_bytes(
            tenant_id=tenant_id,
            owner_id=owner_id,
            document_id=document_id,
            version=version,
            filename=f"phase6-multimodal-{attempt_id}.json",
            content=built.payload_json.encode("utf-8"),
        )
        return Phase6MultimodalArtifact(
            reference=getattr(stored, "storage_path", built.reference),
            checksum=built.checksum,
            created_at=built.created_at,
            payload_json=built.payload_json,
        )
    return built


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    write_jsonl(tmp_path, rows)
    os.replace(tmp_path, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


__all__ = [
    "MultimodalArtifactStore",
    "Phase6MultimodalArtifact",
    "build_multimodal_artifact",
    "persist_multimodal_artifact",
    "read_jsonl",
    "write_jsonl_atomic",
]
