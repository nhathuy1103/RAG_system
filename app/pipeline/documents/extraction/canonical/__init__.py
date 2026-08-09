from __future__ import annotations

from app.pipeline.documents.extraction.canonical.adapters import (
    DEFAULT_CANONICAL_IR_ADAPTERS,
    CanonicalIRAdapter,
    DocxCanonicalIRAdapter,
    NativePdfCanonicalIRAdapter,
    OcrCanonicalIRAdapter,
    PptxCanonicalIRAdapter,
    SpreadsheetCanonicalIRAdapter,
    TextLikeCanonicalIRAdapter,
    legacy_to_v2,
    v2_to_legacy_projection,
)
from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateSpace,
    CoordinateTransform,
    Point,
    Polygon,
)
from app.pipeline.documents.extraction.canonical.ir import (
    CANONICAL_IR_SCHEMA_NAME,
    CANONICAL_IR_SCHEMA_VERSION,
    CanonicalDocument,
    CanonicalElement,
    CanonicalPage,
    CanonicalTable,
    CanonicalTableCell,
)
from app.pipeline.documents.extraction.canonical.serialization import (
    canonical_document_from_json,
    canonical_document_to_json,
)
from app.pipeline.documents.extraction.canonical.validation import (
    CanonicalIRValidationIssue,
    CanonicalIRValidationResult,
    validate_canonical_document,
)

__all__ = [
    "CANONICAL_IR_SCHEMA_NAME",
    "CANONICAL_IR_SCHEMA_VERSION",
    "AxisAlignedBoundingBox",
    "CanonicalDocument",
    "CanonicalElement",
    "CanonicalIRAdapter",
    "CanonicalIRValidationIssue",
    "CanonicalIRValidationResult",
    "CanonicalPage",
    "CanonicalTable",
    "CanonicalTableCell",
    "CoordinateSpace",
    "CoordinateTransform",
    "DEFAULT_CANONICAL_IR_ADAPTERS",
    "DocxCanonicalIRAdapter",
    "NativePdfCanonicalIRAdapter",
    "OcrCanonicalIRAdapter",
    "Point",
    "Polygon",
    "PptxCanonicalIRAdapter",
    "SpreadsheetCanonicalIRAdapter",
    "TextLikeCanonicalIRAdapter",
    "canonical_document_from_json",
    "canonical_document_to_json",
    "legacy_to_v2",
    "v2_to_legacy_projection",
    "validate_canonical_document",
]
