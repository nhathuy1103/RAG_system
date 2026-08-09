from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.pipeline.documents.extraction.multimodal.config import Phase6Config
from app.pipeline.documents.extraction.multimodal.models import (
    MultimodalIssue,
    VisualAsset,
    VisualCandidate,
    VisualRegion,
    stable_id,
    validate_bbox,
)


def build_assets_for_candidates(
    candidates: tuple[VisualCandidate, ...],
    *,
    config: Phase6Config,
) -> tuple[tuple[VisualAsset, ...], tuple[VisualRegion, ...], tuple[MultimodalIssue, ...]]:
    assets: list[VisualAsset] = []
    regions: list[VisualRegion] = []
    issues: list[MultimodalIssue] = []
    seen_checksums: dict[str, str] = {}
    for candidate in candidates:
        try:
            validate_bbox(candidate.bbox)
        except Exception as exc:
            issues.append(
                _issue(
                    candidate,
                    "invalid_visual_geometry",
                    "critical",
                    f"candidate geometry rejected: {exc}",
                )
            )
            continue
        if not candidate.image_path:
            issues.append(
                _issue(
                    candidate,
                    "visual_asset_missing",
                    "high",
                    "candidate has no source image path",
                )
            )
            continue
        image_path = Path(candidate.image_path)
        try:
            byte_size = os.path.getsize(image_path)
        except OSError:
            issues.append(_issue(candidate, "visual_asset_missing", "high", "source image missing"))
            continue
        if byte_size > config.multimodal.assets.max_image_bytes:
            issues.append(
                _issue(
                    candidate,
                    "visual_asset_too_large",
                    "high",
                    "source image exceeded byte limit",
                )
            )
            continue
        try:
            with Image.open(image_path) as opened:
                width, height = opened.size
                opened.verify()
        except (OSError, UnidentifiedImageError) as exc:
            issues.append(
                _issue(
                    candidate,
                    "visual_asset_corrupt",
                    "high",
                    f"source image decode failed: {type(exc).__name__}",
                )
            )
            continue
        if width * height > config.multimodal.assets.max_image_pixels:
            issues.append(
                _issue(
                    candidate,
                    "visual_asset_too_many_pixels",
                    "high",
                    "source image exceeded pixel limit",
                )
            )
            continue
        checksum = _sha256_file(image_path)
        region = VisualRegion(
            region_id=stable_id("visual-region", candidate.candidate_id),
            candidate_id=candidate.candidate_id,
            document_id=candidate.document_id,
            page_number=candidate.page_number,
            region_type=_region_type_for_candidate(candidate.candidate_type),
            bbox=dict(candidate.bbox),
            coordinate_space_id=str(
                candidate.bbox.get("coordinate_space_id") or f"page-{candidate.page_number}-image"
            ),
            transform_chain=tuple(
                candidate.metadata.get("transform_chain") or ("source_image_to_page_bbox",)
            ),
            confidence=float(candidate.metadata.get("candidate_confidence") or 1.0),
            source_refs=tuple(candidate.source_refs),
            provenance={
                "source_image_path": str(image_path),
                "candidate_checksum": candidate.checksum(),
                "raw_asset_reference_preserved": True,
            },
            created_at=str(candidate.metadata.get("created_at") or candidate.created_at),
        )
        duplicate_of = seen_checksums.get(checksum)
        if duplicate_of is None:
            seen_checksums[checksum] = stable_id("visual-asset", candidate.candidate_id, checksum)
        asset_id = stable_id("visual-asset", candidate.candidate_id, checksum)
        assets.append(
            VisualAsset(
                asset_id=asset_id,
                candidate_id=candidate.candidate_id,
                region_id=region.region_id,
                document_id=candidate.document_id,
                page_number=candidate.page_number,
                asset_kind=_region_type_for_candidate(candidate.candidate_type),
                source_path=str(image_path),
                storage_reference=f"visual-asset:{asset_id}:{checksum[:16]}",
                image_checksum=checksum,
                width=width,
                height=height,
                bbox=dict(candidate.bbox),
                coordinate_space_id=region.coordinate_space_id,
                transform_chain=region.transform_chain,
                duplicate_of=duplicate_of,
                terminal_status="duplicate" if duplicate_of else "available",
                created_at=str(candidate.metadata.get("created_at") or candidate.created_at),
            )
        )
        regions.append(region)
    return tuple(assets), tuple(regions), tuple(issues)


def _region_type_for_candidate(candidate_type: str) -> str:
    if candidate_type in {
        "figure",
        "chart",
        "diagram",
        "visual_text",
        "signature",
        "stamp",
        "logo",
        "visual_table",
    }:
        return candidate_type
    if candidate_type == "embedded_image":
        return "figure"
    return "unknown"


def _issue(
    candidate: VisualCandidate,
    issue_type: str,
    severity: str,
    message: str,
) -> MultimodalIssue:
    return MultimodalIssue(
        issue_id=stable_id("visual-issue", candidate.candidate_id, issue_type),
        candidate_id=candidate.candidate_id,
        issue_type=issue_type,
        severity=severity,
        terminal=True,
        message=message,
        review_required=severity in {"high", "critical"},
        source_refs=tuple(candidate.source_refs),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["build_assets_for_candidates"]
