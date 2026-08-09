from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.pipeline.documents.application.validation import guess_extension
from app.pipeline.documents.domain.parsed import ParsedDocument
from app.pipeline.documents.domain.source import DocumentSource
from app.pipeline.documents.ports.parser import ParserCatalog
from app.pipeline.shared.errors import AppError
from app.pipeline.shared.markdown import (
    MARKDOWN_REPRESENTATION_VERSION,
    render_parsed_document_markdown,
)
from app.pipeline.shared.text_utils import normalize_text


@dataclass(frozen=True)
class AdvancedExtractionPipelineConfig:
    ocr_enabled: bool = False
    quality_mode: str = "rag"
    provider_attempts: int = 1
    max_provider_attempts: int = 1
    human_validated: bool = False
    run_canonical_ir: bool = True
    run_layout: bool = True
    run_tables: bool = True
    run_verification: bool = True
    run_multimodal: bool = True
    phase2_config: Any | None = None
    phase3_config: Any | None = None
    phase4_config: Any | None = None
    phase5_config: Any | None = None
    phase6_config: Any | None = None
    ocr_runtime_config: Any | None = None


@dataclass(frozen=True)
class AdvancedExtractionResult:
    parsed_document: ParsedDocument
    quality_report: Any
    quality_decision: Any
    canonical_ir: Any | None
    canonical_ir_validation: Any | None
    canonical_ir_artifact: Any | None
    phase3_layout: Any | None
    phase4_tables: Any | None
    phase5_verification: Any | None
    phase6_multimodal: Any | None
    page_profiles: tuple[Any, ...] = ()
    page_classifications: tuple[Any, ...] = ()
    routing_decisions: tuple[Any, ...] = ()

    @property
    def index_allowed(self) -> bool:
        return bool(getattr(self.quality_decision, "index_allowed", False))


class AdvancedExtractionPipeline:
    """Document extraction use case for native, OCR, layout, table, and visual phases."""

    def __init__(
        self,
        config: AdvancedExtractionPipelineConfig | None = None,
    ) -> None:
        self.config = config or AdvancedExtractionPipelineConfig()

    def run(
        self,
        source: DocumentSource,
        *,
        parser_catalog: ParserCatalog,
        cancel_check: object | None = None,
    ) -> AdvancedExtractionResult:
        parsed, phase2 = self._parse(
            source,
            parser_catalog=parser_catalog,
            cancel_check=cancel_check,
        )
        parsed = sanitize_parsed_document(parsed)
        parsed.document_metadata.update(
            {
                **source.metadata,
                "document_id": source.document_id,
                "document_version": source.version,
                "title": source.title,
                "source_title": source.title,
                "tenant_id": source.tenant_id,
                "owner_id": source.owner_id,
            }
        )
        parsed.logical_document = None
        parsed.logical_document = parsed.to_logical_document()

        quality_report, quality_decision = self._quality_gate(
            source,
            parsed,
        )
        parsed.document_metadata["document_quality"] = quality_report.to_dict()
        parsed.document_metadata["quality_decision"] = quality_decision.to_dict()
        parsed.logical_document = None
        parsed.logical_document = parsed.to_logical_document()

        canonical_ir = None
        canonical_validation = None
        canonical_artifact = None
        phase3_layout = None
        phase4_tables = None
        phase5_verification = None
        phase6_multimodal = None

        if self.config.run_canonical_ir:
            canonical_ir, canonical_validation, canonical_artifact = self._canonicalize(
                source, parsed
            )
            parsed.document_metadata["canonical_ir_v2"] = {
                "schema_name": canonical_ir.schema_name,
                "schema_version": canonical_ir.schema_version,
                "checksum": canonical_artifact.checksum,
                "valid": canonical_validation.valid,
                "issue_codes": list(canonical_validation.issue_codes),
                "artifact_reference": canonical_artifact.reference,
            }

        if canonical_ir is not None and self.config.run_layout:
            phase3_layout = self._build_layout(canonical_ir, phase2)
            parsed.document_metadata["phase3_layout"] = phase3_layout.metadata(
                artifact_reference=None
            )

        if canonical_ir is not None and self.config.run_tables:
            phase4_tables = self._build_tables(
                canonical_ir,
                phase3_layout=phase3_layout,
            )
            parsed.document_metadata["phase4_tables"] = phase4_tables.metadata(
                artifact_reference=None
            )

        if canonical_ir is not None and self.config.run_verification:
            phase5_verification = self._build_verification(
                canonical_ir,
                phase4_tables=phase4_tables,
            )
            parsed.document_metadata["phase5_verification"] = phase5_verification.metadata(
                artifact_reference=None
            )

        if canonical_ir is not None and self.config.run_multimodal:
            phase6_multimodal = self._build_multimodal(
                canonical_ir,
                phase5_verification=phase5_verification,
            )
            parsed.document_metadata["phase6_multimodal"] = phase6_multimodal.metadata(
                artifact_reference=None
            )

        parsed.logical_document = None
        parsed.logical_document = parsed.to_logical_document()
        return AdvancedExtractionResult(
            parsed_document=parsed,
            quality_report=quality_report,
            quality_decision=quality_decision,
            canonical_ir=canonical_ir,
            canonical_ir_validation=canonical_validation,
            canonical_ir_artifact=canonical_artifact,
            phase3_layout=phase3_layout,
            phase4_tables=phase4_tables,
            phase5_verification=phase5_verification,
            phase6_multimodal=phase6_multimodal,
            page_profiles=phase2.get("page_profiles", ()),
            page_classifications=phase2.get("page_classifications", ()),
            routing_decisions=phase2.get("routing_decisions", ()),
        )

    def _parse(
        self,
        source: DocumentSource,
        *,
        parser_catalog: ParserCatalog,
        cancel_check: object | None,
    ) -> tuple[ParsedDocument, dict[str, tuple[Any, ...]]]:
        extension = guess_extension(source.title)
        if self.config.ocr_enabled and extension == "pdf":
            from app.pipeline.documents.extraction.ocr.engine import (
                OcrExtractionEngine,
                OcrRuntimeConfig,
            )
            from app.pipeline.documents.extraction.parsing.adaptive import (
                AdaptiveExtractionEngine,
            )

            ocr_config = self.config.ocr_runtime_config or OcrRuntimeConfig()
            engine = AdaptiveExtractionEngine(
                parser_registry=parser_catalog,
                ocr_engine=OcrExtractionEngine(config=ocr_config),
                phase2_config=self.config.phase2_config,
            )
            result = engine.extract(
                source.title,
                source.content,
                cancel_check=cancel_check,
            )
            return result.parsed_document, {
                "page_profiles": result.page_profiles,
                "page_classifications": result.page_classifications,
                "routing_decisions": result.routing_decisions,
            }
        parser = parser_catalog.get_parser(source.title)
        parser.validate(source.content)
        return parser.parse(source.content), {
            "page_profiles": (),
            "page_classifications": (),
            "routing_decisions": (),
        }

    def _quality_gate(
        self,
        source: DocumentSource,
        parsed: ParsedDocument,
    ) -> tuple[Any, Any]:
        from app.pipeline.documents.extraction.documents.quality import (
            DocumentQualityEvaluator,
        )
        from app.pipeline.documents.extraction.routing import route_extraction_result

        quality_report = DocumentQualityEvaluator().evaluate(parsed)
        quality_decision = route_extraction_result(
            filename=source.title,
            parsed=parsed,
            quality=quality_report,
            mode=self.config.quality_mode,
            provider_attempts=self.config.provider_attempts,
            max_provider_attempts=self.config.max_provider_attempts,
            human_validated=self.config.human_validated,
        )
        return quality_report, quality_decision

    def _canonicalize(
        self,
        source: DocumentSource,
        parsed: ParsedDocument,
    ) -> tuple[Any, Any, Any]:
        from app.pipeline.documents.extraction.canonical.adapters import legacy_to_v2
        from app.pipeline.documents.extraction.canonical.artifacts import (
            build_canonical_ir_artifact,
        )
        from app.pipeline.documents.extraction.canonical.validation import (
            validate_canonical_document,
        )

        attempt_id = str(source.metadata.get("extraction_attempt_id") or uuid4())
        canonical_ir = legacy_to_v2(
            parsed,
            document_id=source.document_id,
            source={
                "title": source.title,
                "checksum": source.checksum,
                "mime_type": source.mime_type,
                "tenant_id": source.tenant_id,
                "owner_id": source.owner_id,
                "document_version": source.version,
            },
            extraction_attempt_id=attempt_id,
        )
        validation = validate_canonical_document(canonical_ir)
        artifact = build_canonical_ir_artifact(
            canonical_ir,
            attempt_id=attempt_id,
        )
        return canonical_ir, validation, artifact

    def _build_layout(
        self,
        canonical_ir: Any,
        phase2: dict[str, tuple[Any, ...]],
    ) -> Any:
        from app.pipeline.documents.extraction.layout.detector import (
            build_layout_for_document,
        )

        return build_layout_for_document(
            canonical_ir,
            config=self.config.phase3_config,
            profiles=phase2.get("page_profiles", ()),
            routing_decisions=phase2.get("routing_decisions", ()),
        )

    def _build_tables(
        self,
        canonical_ir: Any,
        *,
        phase3_layout: Any | None,
    ) -> Any:
        from app.pipeline.documents.extraction.tables.engine import (
            build_tables_for_document,
        )

        return build_tables_for_document(
            canonical_ir,
            layout_result=phase3_layout,
            config=self.config.phase4_config,
        )

    def _build_verification(
        self,
        canonical_ir: Any,
        *,
        phase4_tables: Any | None,
    ) -> Any:
        from app.pipeline.documents.extraction.verification.engine import (
            build_verification_for_document,
        )

        return build_verification_for_document(
            canonical_ir,
            table_result=phase4_tables,
            config=self.config.phase5_config,
        )

    def _build_multimodal(
        self,
        canonical_ir: Any,
        *,
        phase5_verification: Any | None,
    ) -> Any:
        from app.pipeline.documents.extraction.multimodal.engine import (
            build_multimodal_for_document,
        )

        return build_multimodal_for_document(
            canonical_ir,
            phase5_verification=phase5_verification,
            config=self.config.phase6_config,
        )


def sanitize_parsed_document(parsed: ParsedDocument) -> ParsedDocument:
    sanitized_sections = [
        type(section)(
            text=normalize_text(section.text),
            page_number=section.page_number,
            title=normalize_text(section.title or "") or section.title,
            level=getattr(section, "level", 1),
            block_ids=list(getattr(section, "block_ids", []) or []),
        )
        for section in parsed.sections
    ]
    sanitized_pages = [
        type(page)(
            page_number=page.page_number,
            text=normalize_text(page.text),
            elements=[
                type(element)(
                    element_id=element.element_id,
                    block_type=element.block_type,
                    text=normalize_text(element.text),
                    page_number=element.page_number,
                    metadata=dict(element.metadata),
                    bbox=getattr(element, "bbox", None),
                    confidence=getattr(element, "confidence", None),
                    rotation=getattr(element, "rotation", 0),
                    provenance=dict(getattr(element, "provenance", {}) or {}),
                )
                for element in getattr(page, "elements", [])
            ],
            metadata=dict(getattr(page, "metadata", {}) or {}),
            width=getattr(page, "width", None),
            height=getattr(page, "height", None),
            rotation=getattr(page, "rotation", 0),
        )
        for page in parsed.pages
    ]
    sanitized_tables = [
        type(table)(
            table_id=table.table_id,
            location=table.location,
            rows=[[normalize_text(cell) for cell in row] for row in table.rows],
            columns=table.columns,
            header=[normalize_text(cell) for cell in table.header],
            warnings=list(table.warnings),
            cells=[dict(cell) for cell in list(getattr(table, "cells", []) or [])],
            bbox=getattr(table, "bbox", None),
            confidence=getattr(table, "confidence", None),
            metadata=dict(getattr(table, "metadata", {}) or {}),
        )
        for table in parsed.tables
    ]
    document_metadata = dict(parsed.document_metadata)
    document_metadata["content_format"] = "markdown"
    document_metadata["content_representation_version"] = MARKDOWN_REPRESENTATION_VERSION
    sanitized = ParsedDocument(
        text=normalize_text(parsed.text),
        pages=sanitized_pages,
        sections=sanitized_sections,
        tables=sanitized_tables,
        images_metadata=list(parsed.images_metadata),
        document_metadata=document_metadata,
        warnings=list(parsed.warnings),
        parser_name=parsed.parser_name,
        parser_version=parsed.parser_version,
        confidence=parsed.confidence,
        ocr_used=parsed.ocr_used,
        detected_language=parsed.detected_language,
        content_markdown=None,
    )
    sanitized.content_markdown = render_parsed_document_markdown(sanitized)
    sanitized.logical_document = sanitized.to_logical_document()
    return sanitized


def ensure_index_allowed(extraction: AdvancedExtractionResult) -> None:
    if extraction.index_allowed:
        return
    detail = extraction.quality_decision.to_dict()
    reason = str(detail.get("reason") or "quality_gate_blocked")
    issue_codes = ", ".join(detail.get("issue_codes") or ())
    suffix = f": {issue_codes}" if issue_codes else ""
    raise AppError(
        "embedding_blocked_by_extraction_quality",
        f"Embedding blocked by extraction quality gate ({reason}){suffix}.",
        status_code=422,
    )


__all__ = [
    "AdvancedExtractionPipeline",
    "AdvancedExtractionPipelineConfig",
    "AdvancedExtractionResult",
    "ensure_index_allowed",
    "sanitize_parsed_document",
]
