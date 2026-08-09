from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.pipeline.documents.extraction.canonical.ir import CanonicalDocument
from app.pipeline.documents.extraction.multimodal.config import Phase6Config
from app.pipeline.documents.extraction.multimodal.models import (
    VisualCandidate,
    stable_id,
)


def collect_visual_candidates(
    document: CanonicalDocument,
    *,
    config: Phase6Config,
    manifest_cases: Iterable[dict[str, Any]] | None = None,
) -> tuple[VisualCandidate, ...]:
    raw_candidates: list[dict[str, Any]] = []
    if manifest_cases is not None:
        raw_candidates.extend(_manifest_candidates(manifest_cases))
    raw_candidates.extend(_metadata_candidates(document))
    raw_candidates.extend(_layout_hint_candidates(document))
    deduped: dict[str, VisualCandidate] = {}
    for raw in raw_candidates:
        if len(deduped) >= config.multimodal.assets.max_candidates_per_document:
            break
        candidate = _candidate_from_raw(document, raw)
        area = (float(candidate.bbox["x_max"]) - float(candidate.bbox["x_min"])) * (
            float(candidate.bbox["y_max"]) - float(candidate.bbox["y_min"])
        )
        if area < config.multimodal.assets.minimum_candidate_area:
            continue
        deduped.setdefault(candidate.candidate_id, candidate)
    return tuple(deduped.values())


def _manifest_candidates(manifest_cases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in manifest_cases:
        if not item.get("requires_visual_processing", True):
            continue
        candidates.append(
            {
                "candidate_id": item.get("candidate_id") or item["case_id"],
                "document_id": item.get("document_id") or "phase6-controlled",
                "page_number": item.get("page_number", 1),
                "candidate_type": item.get("candidate_type") or item.get("visual_type") or "figure",
                "bbox": item.get("bbox") or _default_bbox(item.get("page_number", 1)),
                "source_refs": item.get("source_refs") or [item["case_id"]],
                "reason_codes": item.get("reason_codes") or ["phase6_manifest_case"],
                "image_path": item.get("image_path"),
                "text_hint": item.get("text_hint") or item.get("caption_text"),
                "required": item.get("required", True),
                "metadata": {
                    **dict(item.get("metadata") or {}),
                    "case_id": item["case_id"],
                    "expected_type": item.get("expected_type"),
                    "backend_payload": dict(item.get("backend_payload") or {}),
                    "created_at": item.get("created_at"),
                },
            }
        )
    return candidates


def _metadata_candidates(document: CanonicalDocument) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    doc_candidates = document.document_metadata.get("phase6_visual_candidates", [])
    if isinstance(doc_candidates, list):
        values.extend(dict(item) for item in doc_candidates if isinstance(item, dict))
    for page in document.pages:
        page_candidates = page.page_metadata.get("visual_candidates", [])
        if isinstance(page_candidates, list):
            for item in page_candidates:
                if not isinstance(item, dict):
                    continue
                payload = dict(item)
                payload.setdefault("page_number", page.page_number)
                payload.setdefault("document_id", document.document_id)
                values.append(payload)
    return values


def _layout_hint_candidates(document: CanonicalDocument) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for page in document.pages:
        for element in page.elements:
            block_type = str(element.element_type or "").lower()
            attributes = dict(element.attributes or {})
            is_visual = block_type in {"figure", "image", "chart", "diagram"} or bool(
                attributes.get("phase3_layout", {}).get("block_type") == "figure_region"
                if isinstance(attributes.get("phase3_layout"), dict)
                else False
            )
            if not is_visual or element.geometry is None:
                continue
            bbox = element.geometry.bbox.to_dict()
            bbox.setdefault("coordinate_space_id", element.geometry.coordinate_space_id)
            values.append(
                {
                    "candidate_id": stable_id(
                        "visual-candidate",
                        document.document_id,
                        page.page_number,
                        element.element_id,
                    ),
                    "document_id": document.document_id,
                    "page_number": page.page_number,
                    "candidate_type": "figure" if block_type in {"figure", "image"} else block_type,
                    "bbox": bbox,
                    "source_refs": [element.element_id],
                    "reason_codes": ["phase3_layout_visual_region"],
                    "text_hint": element.text,
                    "metadata": {"element_id": element.element_id},
                }
            )
    return values


def _candidate_from_raw(document: CanonicalDocument, raw: dict[str, Any]) -> VisualCandidate:
    page_number = int(raw.get("page_number") or 1)
    candidate_id = str(
        raw.get("candidate_id")
        or stable_id(
            "visual-candidate",
            raw.get("document_id") or document.document_id,
            page_number,
            raw.get("candidate_type") or "unknown",
            raw.get("bbox") or {},
        )
    )
    bbox = dict(raw.get("bbox") or _default_bbox(page_number))
    bbox.setdefault("coordinate_space_id", f"page-{page_number}-image")
    return VisualCandidate(
        candidate_id=candidate_id,
        document_id=str(raw.get("document_id") or document.document_id),
        page_number=page_number,
        candidate_type=str(raw.get("candidate_type") or "unknown"),
        bbox=bbox,
        source_refs=tuple(str(item) for item in raw.get("source_refs") or ()),
        reason_codes=tuple(str(item) for item in raw.get("reason_codes") or ()),
        image_path=str(raw["image_path"]) if raw.get("image_path") is not None else None,
        text_hint=str(raw["text_hint"]) if raw.get("text_hint") is not None else None,
        required=bool(raw.get("required", True)),
        metadata=dict(raw.get("metadata") or {}),
        created_at=str(
            raw.get("created_at")
            or raw.get("metadata", {}).get("created_at")
            or "2026-07-26T00:00:00Z"
        ),
    )


def _default_bbox(page_number: int) -> dict[str, Any]:
    return {
        "x_min": 0,
        "y_min": 0,
        "x_max": 100,
        "y_max": 100,
        "coordinate_space_id": f"page-{page_number}-image",
    }


__all__ = ["collect_visual_candidates"]
