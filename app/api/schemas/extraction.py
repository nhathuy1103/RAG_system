"""Schemas for the authenticated, non-persisting extraction inspector."""

from typing import Any

from pydantic import BaseModel


class ExtractionInspectionResponse(BaseModel):
    """A JSON-friendly projection of one Advanced Extraction run."""

    source: dict[str, Any]
    summary: dict[str, Any]
    content: dict[str, str]
    chunking: dict[str, Any]
    chunks: list[dict[str, Any]]
    parsed_document: dict[str, Any]
    quality_report: dict[str, Any]
    quality_decision: dict[str, Any]
    canonical_ir: dict[str, Any] | None
    canonical_ir_validation: dict[str, Any] | None
    canonical_ir_artifact: dict[str, Any] | None
    phases: dict[str, Any]
    adaptive_routing: dict[str, Any]


__all__ = ["ExtractionInspectionResponse"]
