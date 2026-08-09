from __future__ import annotations

import io
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from pypdf import PdfReader

from app.pipeline.documents.extraction.documents.analysis import (
    DocumentAnalysisReport,
    DocumentAnalyzer,
    ExtractionStrategy,
    unlock_pdf_with_empty_password,
)
from app.pipeline.documents.extraction.parsing.native_pdf import extract_native_pdf_structure
from app.pipeline.documents.extraction.parsing.parsers import (
    ParsedDocument,
    ParsedPage,
    ParsedSection,
    ParsedTable,
    ParserRegistry,
)
from app.pipeline.documents.extraction.profiling import (
    AdaptiveRouter,
    ExtractionRoute,
    PageClassification,
    PageProfile,
    PageProfiler,
    Phase2Config,
    RouteSource,
    RoutingDecision,
    RoutingMode,
)
from app.pipeline.shared.errors import AppError
from app.pipeline.shared.markdown import (
    MARKDOWN_REPRESENTATION_VERSION,
    render_parsed_document_markdown,
)
from app.pipeline.shared.text_utils import detect_language, normalize_text

if TYPE_CHECKING:
    from app.pipeline.documents.extraction.documents.analysis import PdfPageAnalysis
    from app.pipeline.documents.extraction.ocr.engine import (
        OcrDocumentResult,
        OcrExtractionEngine,
        OcrPageResult,
    )


# A very short text layer is commonly only a page number or running header. OCR
# may replace it only when it has materially more text and quality-gate confidence.
HYBRID_PARTIAL_NATIVE_MAX_CHARACTERS = 40
HYBRID_OCR_REPLACEMENT_MIN_CHARACTERS = 80
HYBRID_OCR_REPLACEMENT_LENGTH_RATIO = 3.0
HYBRID_OCR_SOURCE_MIN_CONFIDENCE = 0.8


@dataclass(frozen=True)
class AdaptiveExtractionResult:
    analysis: DocumentAnalysisReport
    parsed_document: ParsedDocument
    pipeline_selected: str
    ocr_used: bool
    ocr_result: OcrDocumentResult | None = None
    page_profiles: tuple[PageProfile, ...] = ()
    page_classifications: tuple[PageClassification, ...] = ()
    routing_decisions: tuple[RoutingDecision, ...] = ()


class AdaptiveExtractionEngine:
    def __init__(
        self,
        analyzer: DocumentAnalyzer | None = None,
        parser_registry: ParserRegistry | None = None,
        ocr_engine: OcrExtractionEngine | None = None,
        phase2_config: Phase2Config | None = None,
    ) -> None:
        self.analyzer = analyzer or DocumentAnalyzer()
        self.parser_registry = parser_registry or ParserRegistry()
        self.ocr_engine = ocr_engine
        self.phase2_config = phase2_config or Phase2Config()
        self.phase2_config.validate()

    def extract(
        self,
        filename: str,
        content: bytes,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> AdaptiveExtractionResult:
        analysis = self.analyzer.analyze(filename, content)
        phase2_context = _build_phase2_context(
            filename=filename,
            content=content,
            document_id=analysis.filename,
            config=self.phase2_config,
        )
        active_analysis = _analysis_for_active_routing(analysis, phase2_context)
        effective_strategy = active_analysis.extraction_strategy
        if effective_strategy == ExtractionStrategy.OCR.value:
            from app.pipeline.documents.extraction.ocr.engine import ocr_result_to_parsed_document

            ocr_result = _extract_pdf_compat(
                self._get_ocr_engine(),
                filename,
                content,
                active_analysis,
                cancel_check=cancel_check,
            )
            if not ocr_result.text.strip():
                reason = (
                    ", ".join(
                        ocr_result.blocking_reasons or [error.code for error in ocr_result.errors]
                    )
                    or "unknown_ocr_failure"
                )
                raise AppError(
                    "ocr_extraction_failed", f"OCR extraction failed: {reason}.", status_code=422
                )
            parsed = ocr_result_to_parsed_document(ocr_result)
            parsed.document_metadata["document_analysis"] = active_analysis.to_dict()
            parsed.document_metadata["pipeline_selected"] = effective_strategy
            parsed.document_metadata["ocr_result"] = {
                "extraction_status": ocr_result.extraction_status,
                "validation_status": ocr_result.validation_status,
                "dqa_status": ocr_result.dqa_status,
                "chunking_ready": ocr_result.chunking_ready,
            }
            _attach_phase2_metadata(parsed, phase2_context, selected_pipeline=effective_strategy)
            parsed.logical_document = None
            parsed.logical_document = parsed.to_logical_document()
            return AdaptiveExtractionResult(
                analysis=active_analysis,
                parsed_document=parsed,
                pipeline_selected=effective_strategy,
                ocr_used=True,
                ocr_result=ocr_result,
                page_profiles=phase2_context.profiles if phase2_context else (),
                page_classifications=phase2_context.classifications if phase2_context else (),
                routing_decisions=phase2_context.decisions if phase2_context else (),
            )
        if effective_strategy == ExtractionStrategy.HYBRID.value:
            ocr_result = _extract_pdf_compat(
                self._get_ocr_engine(),
                filename,
                content,
                active_analysis,
                cancel_check=cancel_check,
            )
            parsed = _merge_hybrid_pdf_pages(
                filename=filename,
                content=content,
                analysis=active_analysis,
                ocr_result=ocr_result,
            )
            parsed.document_metadata["document_analysis"] = active_analysis.to_dict()
            parsed.document_metadata["pipeline_selected"] = effective_strategy
            parsed.document_metadata["ocr_result"] = {
                "extraction_status": ocr_result.extraction_status,
                "validation_status": ocr_result.validation_status,
                "dqa_status": ocr_result.dqa_status,
                "chunking_ready": ocr_result.chunking_ready,
            }
            _attach_phase2_metadata(parsed, phase2_context, selected_pipeline=effective_strategy)
            parsed.logical_document = None
            parsed.logical_document = parsed.to_logical_document()
            return AdaptiveExtractionResult(
                analysis=active_analysis,
                parsed_document=parsed,
                pipeline_selected=effective_strategy,
                ocr_used=True,
                ocr_result=ocr_result,
                page_profiles=phase2_context.profiles if phase2_context else (),
                page_classifications=phase2_context.classifications if phase2_context else (),
                routing_decisions=phase2_context.decisions if phase2_context else (),
            )
        if effective_strategy == "empty":
            parsed = _empty_pdf_document(filename, active_analysis)
            _attach_phase2_metadata(parsed, phase2_context, selected_pipeline=effective_strategy)
            parsed.logical_document = None
            parsed.logical_document = parsed.to_logical_document()
            return AdaptiveExtractionResult(
                analysis=active_analysis,
                parsed_document=parsed,
                pipeline_selected=effective_strategy,
                ocr_used=False,
                ocr_result=None,
                page_profiles=phase2_context.profiles if phase2_context else (),
                page_classifications=phase2_context.classifications if phase2_context else (),
                routing_decisions=phase2_context.decisions if phase2_context else (),
            )
        if effective_strategy == ExtractionStrategy.REJECT.value:
            raise AppError(
                "adaptive_route_rejected",
                "Adaptive routing produced a terminal unsupported route.",
                status_code=422,
            )
        parser = self.parser_registry.get_parser(filename)
        parsed = parser.parse(content)
        parsed.document_metadata["document_analysis"] = active_analysis.to_dict()
        parsed.document_metadata["pipeline_selected"] = effective_strategy
        _attach_phase2_metadata(parsed, phase2_context, selected_pipeline=effective_strategy)
        parsed.logical_document = None
        parsed.logical_document = parsed.to_logical_document()
        return AdaptiveExtractionResult(
            analysis=active_analysis,
            parsed_document=parsed,
            pipeline_selected=effective_strategy,
            ocr_used=parsed.ocr_used,
            ocr_result=None,
            page_profiles=phase2_context.profiles if phase2_context else (),
            page_classifications=phase2_context.classifications if phase2_context else (),
            routing_decisions=phase2_context.decisions if phase2_context else (),
        )

    def _get_ocr_engine(self) -> OcrExtractionEngine:
        if self.ocr_engine is None:
            from app.pipeline.documents.extraction.ocr.engine import OcrExtractionEngine

            self.ocr_engine = OcrExtractionEngine()
        return self.ocr_engine


@dataclass(frozen=True)
class _Phase2RouteContext:
    profiles: tuple[PageProfile, ...]
    classifications: tuple[PageClassification, ...]
    decisions: tuple[RoutingDecision, ...]
    mode: RoutingMode
    config_checksum: str


def _build_phase2_context(
    *,
    filename: str,
    content: bytes,
    document_id: str,
    config: Phase2Config,
) -> _Phase2RouteContext | None:
    if not config.profiling.enabled or config.routing.mode == RoutingMode.STATIC:
        return None
    profiler = PageProfiler(config.profiling)
    router = AdaptiveRouter(config.routing)
    profiles = tuple(
        profiler.profile_document(
            filename,
            content,
            document_id=document_id,
        )
    )
    route_source = (
        RouteSource.SHADOW if config.routing.mode == RoutingMode.SHADOW else RouteSource.ADAPTIVE
    )
    decisions = tuple(router.decide_many(list(profiles), route_source=route_source))
    classifications = tuple(
        PageClassification.from_mapping(decision.evidence["classification"])
        for decision in decisions
    )
    return _Phase2RouteContext(
        profiles=profiles,
        classifications=classifications,
        decisions=decisions,
        mode=config.routing.mode,
        config_checksum=config.checksum(),
    )


def _analysis_for_active_routing(
    analysis: DocumentAnalysisReport,
    context: _Phase2RouteContext | None,
) -> DocumentAnalysisReport:
    if context is None or context.mode != RoutingMode.ADAPTIVE:
        return analysis
    routes = {decision.route for decision in context.decisions}
    if routes and routes <= {ExtractionRoute.EMPTY}:
        return replace(
            analysis,
            extraction_strategy="empty",
            required_processing=("terminal_empty_route",),
            potential_problems=tuple(
                dict.fromkeys([*analysis.potential_problems, "empty_page_route"])
            ),
        )
    if routes and routes <= {ExtractionRoute.UNSUPPORTED}:
        return replace(
            analysis,
            extraction_strategy=ExtractionStrategy.REJECT.value,
            required_processing=("reject_or_manual_review",),
            potential_problems=tuple(
                dict.fromkeys([*analysis.potential_problems, "unsupported_route"])
            ),
        )
    if not _ocr_needed(context.decisions):
        return replace(
            analysis,
            extraction_strategy=ExtractionStrategy.NATIVE.value,
            estimated_ocr_required=False,
            required_processing=("native_pdf_parser",),
        )
    if _native_needed(context.decisions):
        return replace(
            analysis,
            extraction_strategy=ExtractionStrategy.HYBRID.value,
            estimated_ocr_required=True,
            required_processing=("native_pdf_parser", "ocr_backend", "merge_native_and_ocr"),
        )
    return replace(
        analysis,
        extraction_strategy=ExtractionStrategy.OCR.value,
        estimated_ocr_required=True,
        required_processing=("ocr_backend",),
    )


def _ocr_needed(decisions: tuple[RoutingDecision, ...]) -> bool:
    return any(
        decision.route
        in {
            ExtractionRoute.OCR_ONLY,
            ExtractionRoute.NATIVE_OCR_HYBRID,
            ExtractionRoute.ORIENTATION_RECOVERY_OCR,
        }
        for decision in decisions
    )


def _native_needed(decisions: tuple[RoutingDecision, ...]) -> bool:
    return any(
        decision.route
        in {
            ExtractionRoute.NATIVE_ONLY,
            ExtractionRoute.NATIVE_OCR_HYBRID,
            ExtractionRoute.STATIC_FALLBACK,
        }
        for decision in decisions
    )


def _attach_phase2_metadata(
    parsed: ParsedDocument,
    context: _Phase2RouteContext | None,
    *,
    selected_pipeline: str,
) -> None:
    if context is None:
        return
    parsed.document_metadata["phase2_page_profiling"] = {
        "mode": context.mode.value,
        "selected_pipeline": selected_pipeline,
        "config_checksum": context.config_checksum,
        "profile_coverage": 1.0 if context.profiles else 0.0,
        "decision_coverage": 1.0 if context.decisions else 0.0,
        "profile_schema_version": (
            context.profiles[0].schema_version if context.profiles else None
        ),
        "profiler_version": (context.profiles[0].profiler_version if context.profiles else None),
        "routing_policy_version": (
            context.decisions[0].policy_version if context.decisions else None
        ),
        "profiles": [profile.to_dict() for profile in context.profiles],
        "classifications": [classification.to_dict() for classification in context.classifications],
        "routing_decisions": [decision.to_dict() for decision in context.decisions],
        "downstream_hints": [decision.downstream_hints.to_dict() for decision in context.decisions],
    }


def _empty_pdf_document(
    filename: str,
    analysis: DocumentAnalysisReport,
) -> ParsedDocument:
    return ParsedDocument(
        text="",
        pages=[
            ParsedPage(
                page_number=page.page_number,
                text="",
                metadata={"terminal_route": "EMPTY"},
            )
            for page in analysis.page_analysis
        ],
        sections=[],
        tables=[],
        images_metadata=[],
        document_metadata={
            "title": filename,
            "page_count": analysis.page_count,
            "word_count": 0,
            "table_count": 0,
            "image_count": analysis.image_count,
            "parser_name": "adaptive_empty_pdf",
            "parser_version": "1.0",
            "detected_language": "unknown",
            "ocr_used": False,
            "content_format": "markdown",
            "document_analysis": analysis.to_dict(),
        },
        warnings=[],
        parser_name="adaptive_empty_pdf",
        parser_version="1.0",
        confidence=1.0,
        ocr_used=False,
        detected_language="unknown",
        content_markdown="",
    )


def _merge_hybrid_pdf_pages(
    *,
    filename: str,
    content: bytes,
    analysis: DocumentAnalysisReport,
    ocr_result: OcrDocumentResult,
) -> ParsedDocument:
    native_page_texts = _native_pdf_page_text(content)
    native_extraction = extract_native_pdf_structure(
        content,
        fallback_page_texts=native_page_texts,
    )
    native_pages_by_number: dict[int, ParsedPage] = (
        {page.page_number: page for page in native_extraction.pages}
        if native_extraction is not None
        else {}
    )
    native_pages = (
        {page.page_number: page.text for page in native_extraction.pages}
        if native_extraction is not None
        else native_page_texts
    )
    native_sections_by_page: dict[int, list[ParsedSection]] = {}
    native_tables_by_page: dict[int, list[ParsedTable]] = {}
    native_image_locations_by_page: dict[int, list[str]] = {}
    if native_extraction is not None:
        for section in native_extraction.sections:
            if section.page_number is not None:
                native_sections_by_page.setdefault(section.page_number, []).append(section)
        for table in native_extraction.tables:
            page_number = _page_number_from_table_location(table.location)
            if page_number is not None:
                native_tables_by_page.setdefault(page_number, []).append(table)
        for image in native_extraction.images_metadata:
            page_number = _page_number_from_table_location(image.location)
            if page_number is not None:
                native_image_locations_by_page.setdefault(page_number, []).append(image.location)
    ocr_pages = {page.page_number: page for page in ocr_result.pages}
    analyzed_pages = sorted(analysis.page_analysis, key=lambda page: page.page_number)
    required_ocr_page_numbers = {
        page.page_number for page in analyzed_pages if not page.has_text_layer or page.ocr_required
    }
    invalid_scan_pages = sorted(
        page_number
        for page_number in required_ocr_page_numbers
        if not _is_valid_ocr_page(ocr_pages.get(page_number))
    )
    if invalid_scan_pages:
        _raise_hybrid_scan_page_failure(ocr_result, invalid_scan_pages)

    merged_pages: list[ParsedPage] = []
    sections: list[ParsedSection] = []
    native_page_numbers: list[int] = []
    selected_native_image_locations: set[str] = set()
    selected_ocr_pages: list[OcrPageResult] = []
    selected_tables: list[ParsedTable] = []
    parsed_ocr_pages_by_number: dict[int, ParsedPage] = {}
    parsed_ocr_tables_by_page: dict[int, list[ParsedTable]] = {}
    if ocr_result.pages:
        from app.pipeline.documents.extraction.ocr.engine import ocr_result_to_parsed_document

        parsed_ocr_document = ocr_result_to_parsed_document(ocr_result)
        parsed_ocr_pages_by_number = {page.page_number: page for page in parsed_ocr_document.pages}
        for table in parsed_ocr_document.tables:
            page_number = _page_number_from_table_location(table.location)
            if page_number is not None:
                parsed_ocr_tables_by_page.setdefault(page_number, []).append(table)
    for page in analyzed_pages:
        native_text = normalize_text(native_pages.get(page.page_number, ""))
        ocr_page = ocr_pages.get(page.page_number)
        source = _select_hybrid_page_source(page, native_text, ocr_page)
        if source == "native":
            parsed_page = native_pages_by_number.get(page.page_number) or ParsedPage(
                page_number=page.page_number,
                text=native_text,
            )
            display_source = "Native"
            native_page_numbers.append(page.page_number)
            selected_tables.extend(native_tables_by_page.get(page.page_number, []))
            selected_native_image_locations.update(
                native_image_locations_by_page.get(page.page_number, [])
            )
        elif source == "ocr":
            assert ocr_page is not None
            parsed_page = parsed_ocr_pages_by_number.get(page.page_number) or ParsedPage(
                page_number=page.page_number,
                text=normalize_text(ocr_page.text),
            )
            display_source = "OCR"
            selected_ocr_pages.append(ocr_page)
            selected_tables.extend(parsed_ocr_tables_by_page.get(page.page_number, []))
        else:
            continue
        page_text = parsed_page.text
        merged_pages.append(parsed_page)
        if display_source == "Native" and native_sections_by_page.get(page.page_number):
            sections.extend(native_sections_by_page[page.page_number])
        else:
            sections.append(
                ParsedSection(
                    text=page_text,
                    page_number=page.page_number,
                    title=f"Hybrid Page {page.page_number} {display_source}",
                    block_ids=[element.element_id for element in parsed_page.elements],
                )
            )

    if not merged_pages:
        reason = (
            ", ".join(
                ocr_result.blocking_reasons or tuple(error.code for error in ocr_result.errors)
            )
            or "no_native_or_ocr_text"
        )
        raise AppError(
            "hybrid_extraction_failed",
            f"Hybrid PDF extraction failed: {reason}.",
            status_code=422,
        )

    missing_confidence_pages = [
        page.page_number for page in selected_ocr_pages if page.confidence is None
    ]
    if missing_confidence_pages:
        raise AppError(
            "hybrid_ocr_confidence_missing",
            "Hybrid PDF OCR confidence is missing for selected scanned pages: "
            + ", ".join(str(page_number) for page_number in missing_confidence_pages)
            + ".",
            status_code=422,
        )

    text = normalize_text("\n\n".join(page.text for page in merged_pages))
    warnings = ["HYBRID_PDF_PAGE_LEVEL_MERGE_USED"]
    if native_extraction is not None:
        warnings.extend(native_extraction.warnings)
    warnings.extend(warning.code for warning in ocr_result.warnings)
    for page in selected_ocr_pages:
        warnings.extend(warning.code for warning in page.warnings)
    language = detect_language(text)
    selected_ocr_confidence = (
        min(page.confidence for page in selected_ocr_pages if page.confidence is not None)
        if selected_ocr_pages
        else None
    )
    confidence = (
        min(analysis.confidence, selected_ocr_confidence)
        if selected_ocr_confidence is not None
        else analysis.confidence
    )
    ocr_page_numbers = [page.page_number for page in selected_ocr_pages]
    native_metadata = (
        dict(native_extraction.metadata.get("native_pdf_extraction", {}))
        if native_extraction is not None
        else {
            "provider": "pypdf",
            "mode": "text_only_fallback",
            "model_fallback_status": "not_configured",
        }
    )
    native_metadata.update(
        {
            "hybrid_selected_native_page_count": len(native_page_numbers),
            "hybrid_selected_native_table_count": sum(
                len(native_tables_by_page.get(page_number, []))
                for page_number in native_page_numbers
            ),
            "hybrid_selected_native_element_count": sum(
                len(native_pages_by_number.get(page_number, ParsedPage(page_number, "")).elements)
                for page_number in native_page_numbers
            ),
        }
    )
    document = ParsedDocument(
        text=text,
        pages=merged_pages,
        sections=sections,
        tables=selected_tables,
        images_metadata=[
            image
            for image in (native_extraction.images_metadata if native_extraction is not None else [])
            if image.location in selected_native_image_locations
        ],
        document_metadata={
            "title": filename,
            "page_count": len(merged_pages),
            "word_count": len(text.split()),
            "table_count": len(selected_tables),
            "image_count": len(selected_native_image_locations),
            "parser_name": "hybrid_pdf",
            "parser_version": "1.1",
            "detected_language": language,
            "ocr_used": True,
            "content_format": "markdown",
            "content_representation_version": MARKDOWN_REPRESENTATION_VERSION,
            "native_pdf_extraction": native_metadata,
            "hybrid_native_page_count": len(native_page_numbers),
            "hybrid_ocr_page_count": len(ocr_page_numbers),
            "hybrid_native_page_numbers": native_page_numbers,
            "hybrid_ocr_page_numbers": ocr_page_numbers,
            "hybrid_min_selected_ocr_confidence": selected_ocr_confidence,
            "extraction_provenance": [
                {
                    "page_number": page.page_number,
                    "source": "ocr" if page.page_number in ocr_page_numbers else "native",
                    "status": "PASS",
                    "confidence": (
                        ocr_pages[page.page_number].confidence
                        if page.page_number in ocr_page_numbers and page.page_number in ocr_pages
                        else analysis.confidence
                    ),
                    "indexable": True,
                }
                for page in merged_pages
            ],
        },
        warnings=list(dict.fromkeys(warnings)),
        parser_name="hybrid_pdf",
        parser_version="1.1",
        confidence=confidence,
        ocr_used=True,
        detected_language=language,
    )
    document.content_markdown = render_parsed_document_markdown(document)
    document.logical_document = document.to_logical_document()
    return document


def _is_valid_ocr_page(page: OcrPageResult | None) -> bool:
    return bool(
        page is not None
        and normalize_text(page.text)
        and page.status in {"PASS", "WARN"}
        and not page.errors
    )


def _select_hybrid_page_source(
    page_analysis: PdfPageAnalysis,
    native_text: str,
    ocr_page: OcrPageResult | None,
) -> Literal["native", "ocr"] | None:
    normalized_native = normalize_text(native_text)
    if not page_analysis.has_text_layer or page_analysis.ocr_required:
        return "ocr" if _is_valid_ocr_page(ocr_page) else None
    if not normalized_native:
        return "ocr" if _is_valid_ocr_page(ocr_page) else None
    if _should_replace_partial_native(normalized_native, ocr_page):
        return "ocr"
    return "native"


def _should_replace_partial_native(
    native_text: str,
    ocr_page: OcrPageResult | None,
) -> bool:
    if not _is_valid_ocr_page(ocr_page):
        return False
    assert ocr_page is not None
    if ocr_page.confidence is None or ocr_page.confidence < HYBRID_OCR_SOURCE_MIN_CONFIDENCE:
        return False
    ocr_text = normalize_text(ocr_page.text)
    return (
        len(native_text) <= HYBRID_PARTIAL_NATIVE_MAX_CHARACTERS
        and len(ocr_text) >= HYBRID_OCR_REPLACEMENT_MIN_CHARACTERS
        and len(ocr_text) >= len(native_text) * HYBRID_OCR_REPLACEMENT_LENGTH_RATIO
    )


def _raise_hybrid_scan_page_failure(
    ocr_result: OcrDocumentResult,
    missing_scan_pages: list[int],
) -> None:
    relevant_errors = [
        error
        for error in ocr_result.errors
        if error.page_number is None or error.page_number in missing_scan_pages
    ]
    for page in ocr_result.pages:
        if page.page_number in missing_scan_pages:
            relevant_errors.extend(page.errors)
    page_list = ", ".join(str(page_number) for page_number in missing_scan_pages)
    if relevant_errors and all(error.recoverable for error in relevant_errors):
        raise AppError(
            "retryable_hybrid_ocr_provider_failure",
            f"Hybrid PDF OCR temporarily failed for scanned pages: {page_list}.",
            status_code=503,
        )
    raise AppError(
        "hybrid_ocr_page_failed",
        f"Hybrid PDF OCR produced no text for scanned pages: {page_list}.",
        status_code=422,
    )


def _native_pdf_page_text(content: bytes) -> dict[int, str]:
    reader = PdfReader(io.BytesIO(content))
    if not unlock_pdf_with_empty_password(reader):
        raise AppError(
            "password_protected_file",
            "PDF dang duoc bao ve bang mat khau.",
            status_code=422,
        )
    return {
        page_number: normalize_text(page.extract_text() or "")
        for page_number, page in enumerate(reader.pages, start=1)
    }


def _page_number_from_table_location(location: str) -> int | None:
    match = re.search(r"(?:^|:)page:(\d+)(?:$|:)", location)
    if not match:
        return None
    page_number = int(match.group(1))
    return page_number if page_number > 0 else None


def _extract_pdf_compat(
    engine: OcrExtractionEngine,
    filename: str,
    content: bytes,
    analysis: DocumentAnalysisReport,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> OcrDocumentResult:
    try:
        return engine.extract_pdf(
            filename,
            content,
            analysis,
            cancel_check=cancel_check,
        )
    except TypeError as exc:
        if "cancel_check" not in str(exc):
            raise
        return engine.extract_pdf(filename, content, analysis)
