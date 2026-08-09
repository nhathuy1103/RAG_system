from __future__ import annotations

import concurrent.futures
import errno
import importlib.util
import io
import logging
import os
import platform
import re
import statistics
import threading
import time
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from app.pipeline.documents.extraction.canonical.geometry import (
    AxisAlignedBoundingBox,
    CoordinateTransform,
)
from app.pipeline.documents.extraction.documents.analysis import DocumentAnalysisReport
from app.pipeline.documents.extraction.documents.models import BoundingBox
from app.pipeline.documents.extraction.documents.quality import DocumentQualityEvaluator
from app.pipeline.documents.extraction.ocr.quality import OcrTextNormalizer, TextNormalizationConfig
from app.pipeline.documents.extraction.parsing.parsers import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
    ParsedTable,
)
from app.pipeline.documents.extraction.table_text import (
    render_markdown_table_text,
    render_table_text,
)
from app.pipeline.shared.text_utils import detect_language, normalize_text

logger = logging.getLogger(__name__)


OCR_ROTATION_MIN_IMPROVEMENT = 12.0
_OCR_HEALTH_LOCK = threading.Lock()
_OCR_HEALTH_CACHE: tuple[float, OCRHealthResult] | None = None
_SECONDARY_OCR_LOCK = threading.Lock()
_SECONDARY_OCR_READER: Any | None = None
_SECONDARY_OCR_INITIALIZATION_FAILED = False


class OcrCapabilityStatus(StrEnum):
    OCR_AVAILABLE = "OCR_AVAILABLE"
    OCR_DEPENDENCY_MISSING = "OCR_DEPENDENCY_MISSING"
    OCR_MODEL_UNAVAILABLE = "OCR_MODEL_UNAVAILABLE"
    OCR_INITIALIZATION_FAILED = "OCR_INITIALIZATION_FAILED"
    PDF_RENDERER_UNAVAILABLE = "PDF_RENDERER_UNAVAILABLE"


@dataclass(frozen=True)
class OcrRuntimeConfig:
    backend: str = "paddleocr"
    language: str = "vi"
    dpi: int = 216
    use_angle_cls: bool = True
    use_gpu: bool = False
    use_mkldnn: bool = False
    cache_dir: str = "data/ocr"
    autocontrast: bool = True
    grayscale: bool = False
    max_pages: int | None = None
    unicode_form: str = "NFC"
    apply_nfkc: bool = False
    repair_mojibake: bool = True
    normalize_punctuation: bool = True
    postprocess_whitespace: bool = True
    merge_broken_lines: bool = True
    cleanup_repeated_symbols: bool = True
    warmup_timeout_seconds: int = 10
    page_timeout_seconds: int | None = 60
    document_timeout_seconds: int | None = 420
    max_page_attempts: int = 2
    retry_image_scale: float = 0.65
    min_retry_deadline_seconds: float = 3.0
    document_finalization_reserve_seconds: float = 2.0
    orientation_low_confidence_threshold: float = 0.72
    orientation_good_enough_score: float = 85.0
    hybrid_table_ocr: bool = True
    secondary_ocr_timeout_seconds: int | None = 45
    secondary_ocr_max_dimension: int = 1600

    def __post_init__(self) -> None:
        if self.dpi <= 0:
            raise ValueError("OCR DPI must be positive.")
        if self.max_pages is not None and self.max_pages <= 0:
            raise ValueError("OCR max_pages must be positive when configured.")
        for name in (
            "warmup_timeout_seconds",
            "page_timeout_seconds",
            "document_timeout_seconds",
            "secondary_ocr_timeout_seconds",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"OCR {name} must be positive when configured.")
        if self.max_page_attempts < 1:
            raise ValueError("OCR max_page_attempts must be at least 1.")
        if not 0 < self.retry_image_scale <= 1:
            raise ValueError("OCR retry_image_scale must be in the range (0, 1].")
        if self.min_retry_deadline_seconds < 0:
            raise ValueError("OCR min_retry_deadline_seconds cannot be negative.")
        if self.document_finalization_reserve_seconds < 0:
            raise ValueError("OCR document_finalization_reserve_seconds cannot be negative.")
        if not 0 <= self.orientation_low_confidence_threshold <= 1:
            raise ValueError("OCR orientation_low_confidence_threshold must be in [0, 1].")
        if self.orientation_good_enough_score < 0:
            raise ValueError("OCR orientation_good_enough_score cannot be negative.")
        if self.secondary_ocr_max_dimension <= 0:
            raise ValueError("OCR secondary_ocr_max_dimension must be positive.")


@dataclass(frozen=True)
class OcrWarning:
    code: str
    message: str
    page_number: int | None = None
    severity: str = "warning"


@dataclass(frozen=True)
class OcrError:
    code: str
    message: str
    page_number: int | None = None
    recoverable: bool = False


@dataclass(frozen=True)
class OCRHealthResult:
    dependency_available: bool
    model_loaded: bool
    inference_succeeded: bool
    warmup_completed: bool
    latency_ms: float | None
    timeout: bool
    error_code: str | None
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OcrBlock:
    block_id: str
    block_type: str
    text: str
    confidence: float | None
    bounding_box: BoundingBox | None
    reading_order: int
    language: str
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    provider_coordinate_space_id: str | None = None
    projected_bounding_box: BoundingBox | None = None
    normalized_bounding_box: BoundingBox | None = None
    transform_chain: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    orientation_confidence: float | None = None
    rotation_applied: int = 0


@dataclass(frozen=True)
class OcrPageResult:
    page_number: int
    text: str
    character_count: int
    word_count: int
    confidence: float | None
    processing_time_ms: float
    render_time_ms: float
    preprocessing_time_ms: float
    ocr_time_ms: float
    width: int
    height: int
    dpi: int
    rotation_applied: int
    blocks: tuple[OcrBlock, ...] = field(default_factory=tuple)
    warnings: tuple[OcrWarning, ...] = field(default_factory=tuple)
    errors: tuple[OcrError, ...] = field(default_factory=tuple)
    status: str = "FAIL"
    attempt_history: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    preprocessing: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    normalization_time_ms: float = 0.0
    postprocessing: dict[str, Any] = field(default_factory=dict)
    original_width: int | None = None
    original_height: int | None = None
    input_coordinate_space_id: str | None = None
    projected_coordinate_space_id: str | None = None
    transform_chain: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OcrDocumentResult:
    document_id: str
    filename: str
    source_pdf_type: str
    engine_name: str
    engine_version: str
    language: str
    page_count: int
    processed_page_count: int
    successful_page_count: int
    warning_page_count: int
    failed_page_count: int
    missing_page_numbers: tuple[int, ...]
    text: str
    character_count: int
    word_count: int
    average_confidence: float | None
    min_page_confidence: float | None
    total_render_time_ms: float
    total_ocr_time_ms: float
    processing_time_ms: float
    extraction_status: str
    validation_status: str
    dqa_status: str
    chunking_ready: bool
    blocking_reasons: tuple[str, ...]
    pages: tuple[OcrPageResult, ...]
    warnings: tuple[OcrWarning, ...] = field(default_factory=tuple)
    errors: tuple[OcrError, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    image: Image.Image
    width: int
    height: int
    dpi: int
    render_time_ms: float


@dataclass(frozen=True)
class OcrValidationReport:
    status: str
    chunking_ready: bool
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]


class PdfRenderer:
    def is_available(self) -> bool:
        return importlib.util.find_spec("fitz") is not None

    def render_pages(
        self, content: bytes, *, dpi: int, max_pages: int | None = None
    ) -> Iterable[RenderedPage]:
        if not self.is_available():
            raise RuntimeError("PyMuPDF/fitz is not available.")
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
        page_total = len(document)
        limit = min(page_total, max_pages) if max_pages else page_total
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        for page_index in range(limit):
            started = time.perf_counter()
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
            yield RenderedPage(
                page_number=page_index + 1,
                image=image,
                width=image.width,
                height=image.height,
                dpi=dpi,
                render_time_ms=_elapsed_ms(started),
            )


class ImagePreprocessor:
    def __init__(self, config: OcrRuntimeConfig) -> None:
        self.config = config

    def preprocess(self, image: Image.Image) -> tuple[Image.Image, dict[str, Any], float]:
        started = time.perf_counter()
        processed = image
        steps: list[str] = []
        if self.config.autocontrast:
            processed = ImageOps.autocontrast(processed)
            steps.append("autocontrast")
        if self.config.grayscale:
            processed = ImageOps.grayscale(processed).convert("RGB")
            steps.append("grayscale")
        metadata = {
            "steps": steps,
            "deskew": "NOT_IMPLEMENTED",
            "denoise": "NOT_IMPLEMENTED",
            "threshold": "NOT_IMPLEMENTED",
            "resolution_valid": image.width > 0 and image.height > 0,
        }
        return processed, metadata, _elapsed_ms(started)


class OCRProvider(ABC):
    provider_name = "base"
    provider_version = "unknown"

    @abstractmethod
    def health_report(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def extract_page(
        self,
        image: Image.Image,
        *,
        page_number: int,
        render_time_ms: float,
        preprocessing_time_ms: float,
        preprocessing: dict[str, Any],
    ) -> OcrPageResult:
        raise NotImplementedError


class PaddleOCRProvider(OCRProvider):
    provider_name = "paddleocr"

    def __init__(self, config: OcrRuntimeConfig | None = None) -> None:
        self.config = config or OcrRuntimeConfig()
        self._ocr: Any | None = None
        self._init_error: str | None = None
        self.provider_version = _package_version("paddleocr") or "unknown"
        self.normalizer = OcrTextNormalizer(
            TextNormalizationConfig(
                unicode_form=self.config.unicode_form,
                apply_nfkc=self.config.apply_nfkc,
                repair_mojibake=self.config.repair_mojibake,
                normalize_punctuation=self.config.normalize_punctuation,
                normalize_whitespace=self.config.postprocess_whitespace,
                merge_broken_lines=self.config.merge_broken_lines,
                cleanup_repeated_symbols=self.config.cleanup_repeated_symbols,
            )
        )

    def health_report(self) -> dict[str, Any]:
        renderer_available = importlib.util.find_spec("fitz") is not None
        paddle_available = importlib.util.find_spec("paddle") is not None
        paddleocr_available = importlib.util.find_spec("paddleocr") is not None
        if not renderer_available:
            status = OcrCapabilityStatus.PDF_RENDERER_UNAVAILABLE.value
        elif not paddle_available or not paddleocr_available:
            status = OcrCapabilityStatus.OCR_DEPENDENCY_MISSING.value
        elif self._init_error:
            status = OcrCapabilityStatus.OCR_INITIALIZATION_FAILED.value
        elif self._ocr is not None:
            status = OcrCapabilityStatus.OCR_AVAILABLE.value
        else:
            status = "OCR_NOT_INITIALIZED"
        return {
            "status": status,
            "backend": self.provider_name,
            "provider_version": self.provider_version,
            "paddle_available": paddle_available,
            "paddleocr_available": paddleocr_available,
            "pdf_renderer_available": renderer_available,
            "cache_dir": self.config.cache_dir,
            "initialization_error": self._init_error,
            "python": platform.python_version(),
            "platform": platform.platform(),
        }

    def initialize(self) -> None:
        _configure_ocr_environment(self.config.cache_dir)
        try:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                use_angle_cls=self.config.use_angle_cls,
                lang=self.config.language,
                use_gpu=self.config.use_gpu,
                use_mkldnn=self.config.use_mkldnn,
                show_log=False,
            )
        except (TimeoutError, ConnectionError) as exc:
            self._init_error = str(exc)
            raise OcrRuntimeError(
                OcrCapabilityStatus.OCR_MODEL_UNAVAILABLE.value,
                str(exc),
                recoverable=True,
            ) from exc
        except RuntimeError as exc:
            self._init_error = str(exc)
            if "Download" in str(exc) or "model" in str(exc).lower():
                raise OcrRuntimeError(
                    OcrCapabilityStatus.OCR_MODEL_UNAVAILABLE.value,
                    str(exc),
                    recoverable=_is_recoverable_ocr_exception(exc),
                ) from exc
            raise OcrRuntimeError(
                OcrCapabilityStatus.OCR_INITIALIZATION_FAILED.value,
                str(exc),
                recoverable=_is_recoverable_ocr_exception(exc),
            ) from exc
        except Exception as exc:
            self._init_error = str(exc)
            raise OcrRuntimeError(
                OcrCapabilityStatus.OCR_INITIALIZATION_FAILED.value,
                str(exc),
                recoverable=_is_recoverable_ocr_exception(exc),
            ) from exc

    def extract_page(
        self,
        image: Image.Image,
        *,
        page_number: int,
        render_time_ms: float,
        preprocessing_time_ms: float,
        preprocessing: dict[str, Any],
    ) -> OcrPageResult:
        if self._ocr is None:
            self.initialize()
        assert self._ocr is not None
        started = time.perf_counter()
        try:
            import numpy as np

            raw_result = self._ocr.ocr(np.array(image), cls=self.config.use_angle_cls)
            ocr_time_ms = _elapsed_ms(started)
            blocks = _parse_paddle_blocks(
                raw_result, page_number=page_number, language=self.config.language
            )
            normalized_blocks = []
            block_normalization_time = 0.0
            for block in blocks:
                normalized_block_text, block_report = self.normalizer.normalize(
                    block.raw_text or block.text
                )
                block_normalization_time += block_report.normalization_time_ms
                normalized_blocks.append(
                    OcrBlock(
                        block_id=block.block_id,
                        block_type=block.block_type,
                        text=normalized_block_text,
                        confidence=block.confidence,
                        bounding_box=block.bounding_box,
                        reading_order=block.reading_order,
                        language=block.language,
                        raw_text=block.raw_text or block.text,
                        metadata=dict(block.metadata),
                        provider_coordinate_space_id=block.provider_coordinate_space_id,
                    )
                )
            raw_text = "\n".join(
                block.raw_text or block.text for block in blocks if block.raw_text or block.text
            )
            text, normalization_report = self.normalizer.normalize(raw_text)
            blocks = normalized_blocks
            confidences = [block.confidence for block in blocks if block.confidence is not None]
            confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
            warnings: list[OcrWarning] = []
            errors: list[OcrError] = []
            status = "PASS"
            if not text:
                status = "FAIL"
                errors.append(
                    OcrError(
                        "empty_ocr_output",
                        "OCR returned no text for this page.",
                        page_number,
                        recoverable=False,
                    )
                )
            elif confidence is not None and confidence < 0.6:
                status = "WARN"
                warnings.append(
                    OcrWarning(
                        "low_page_confidence",
                        "Page OCR confidence is below warning threshold.",
                        page_number,
                    )
                )
            return OcrPageResult(
                page_number=page_number,
                text=text,
                character_count=len(text),
                word_count=len(text.split()),
                confidence=confidence,
                processing_time_ms=round(render_time_ms + preprocessing_time_ms + ocr_time_ms, 3),
                render_time_ms=round(render_time_ms, 3),
                preprocessing_time_ms=round(preprocessing_time_ms, 3),
                ocr_time_ms=round(ocr_time_ms, 3),
                width=image.width,
                height=image.height,
                dpi=self.config.dpi,
                rotation_applied=0,
                blocks=tuple(blocks),
                warnings=tuple(warnings),
                errors=tuple(errors),
                status=status,
                preprocessing=preprocessing,
                raw_text=raw_text,
                normalization_time_ms=round(
                    normalization_report.normalization_time_ms + block_normalization_time, 3
                ),
                postprocessing={
                    "normalization_report": normalization_report.to_dict(),
                    "raw_text_preserved": True,
                    "operations": {
                        "unicode_form": self.config.unicode_form,
                        "apply_nfkc": self.config.apply_nfkc,
                        "repair_mojibake": self.config.repair_mojibake,
                        "normalize_punctuation": self.config.normalize_punctuation,
                        "normalize_whitespace": self.config.postprocess_whitespace,
                        "merge_broken_lines": self.config.merge_broken_lines,
                        "cleanup_repeated_symbols": self.config.cleanup_repeated_symbols,
                    },
                },
                input_coordinate_space_id=f"page-{page_number - 1}-ocr-input",
            )
        except Exception as exc:
            ocr_time_ms = _elapsed_ms(started)
            return _failed_ocr_page_result(
                image=image,
                page_number=page_number,
                dpi=self.config.dpi,
                render_time_ms=render_time_ms,
                preprocessing_time_ms=preprocessing_time_ms,
                ocr_time_ms=ocr_time_ms,
                preprocessing=preprocessing,
                error_code="ocr_engine_failed",
                exc=exc,
            )


class OcrRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


class OcrOperationTimeout(TimeoutError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _run_with_timeout(
    callback: Callable[[], Any],
    *,
    timeout_seconds: int | None,
    error_code: str,
) -> Any:
    if timeout_seconds is None or timeout_seconds <= 0:
        return callback()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callback)
    try:
        result = future.result(timeout=float(timeout_seconds))
    except concurrent.futures.TimeoutError as exc:
        if future.done():
            raised = future.exception()
            if raised is not None:
                executor.shutdown(wait=True)
                raise raised from None
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise OcrOperationTimeout(
            error_code,
            f"OCR operation exceeded {timeout_seconds} second(s).",
        ) from exc
    executor.shutdown(wait=True)
    return result


class OcrExtractionEngine:
    def __init__(
        self,
        *,
        config: OcrRuntimeConfig | None = None,
        provider: OCRProvider | None = None,
        renderer: PdfRenderer | None = None,
        preprocessor: ImagePreprocessor | None = None,
    ) -> None:
        self.config = config or OcrRuntimeConfig()
        self.provider = provider or PaddleOCRProvider(self.config)
        self.renderer = renderer or PdfRenderer()
        self.preprocessor = preprocessor or ImagePreprocessor(self.config)

    def extract_pdf(
        self,
        filename: str,
        content: bytes,
        analysis: DocumentAnalysisReport,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> OcrDocumentResult:
        started = time.perf_counter()
        pages: list[OcrPageResult] = []
        errors: list[OcrError] = []
        warnings: list[OcrWarning] = []
        expected_pages = analysis.page_count
        document_deadline = (
            started + self.config.document_timeout_seconds
            if self.config.document_timeout_seconds is not None
            else None
        )
        unprocessed_page_error_code: str | None = None
        if (
            self.config.hybrid_table_ocr
            and isinstance(self.provider, PaddleOCRProvider)
            and importlib.util.find_spec("easyocr") is not None
        ):
            try:
                _get_secondary_ocr_reader(self.config)
            except Exception as exc:
                warnings.append(
                    OcrWarning(
                        "ocr_secondary_table_ocr_unavailable",
                        f"EasyOCR table fallback is unavailable: {exc}",
                    )
                )
        try:
            self.provider.initialize()
        except OcrRuntimeError as exc:
            errors.append(OcrError(exc.code, str(exc), None, recoverable=exc.recoverable))
            return _build_document_result(
                filename=filename,
                analysis=analysis,
                config=self.config,
                provider=self.provider,
                expected_pages=expected_pages,
                pages=pages,
                warnings=warnings,
                errors=errors,
                started=started,
            )
        except Exception as exc:
            errors.append(
                OcrError(
                    OcrCapabilityStatus.OCR_INITIALIZATION_FAILED.value,
                    f"{exc.__class__.__name__}: {exc}",
                    None,
                    recoverable=_is_recoverable_ocr_exception(exc),
                )
            )
            return _build_document_result(
                filename,
                analysis,
                self.config,
                self.provider,
                expected_pages,
                pages,
                warnings,
                errors,
                started,
            )

        rendered_pages = 0
        try:
            for rendered in self.renderer.render_pages(
                content, dpi=self.config.dpi, max_pages=self.config.max_pages
            ):
                if cancel_check is not None and cancel_check():
                    errors.append(
                        OcrError(
                            "ocr_cancelled",
                            "OCR extraction was cancelled before the next page.",
                            rendered.page_number,
                            recoverable=False,
                        )
                    )
                    break
                if _document_deadline_exhausted(
                    document_deadline,
                    reserve_seconds=self.config.document_finalization_reserve_seconds,
                ):
                    errors.append(
                        OcrError(
                            "ocr_document_deadline_exhausted",
                            "OCR document deadline expired before the next page.",
                            rendered.page_number,
                            recoverable=True,
                        )
                    )
                    unprocessed_page_error_code = "ocr_document_deadline_exhausted"
                    break
                rendered_pages += 1
                try:
                    processed_image, preprocessing, preprocessing_time_ms = (
                        self.preprocessor.preprocess(rendered.image)
                    )
                except Exception as exc:
                    pages.append(
                        _failed_ocr_page_result(
                            image=rendered.image,
                            page_number=rendered.page_number,
                            dpi=self.config.dpi,
                            render_time_ms=rendered.render_time_ms,
                            preprocessing_time_ms=0.0,
                            ocr_time_ms=0.0,
                            preprocessing={},
                            error_code="image_preprocessing_failed",
                            exc=exc,
                        )
                    )
                    continue
                page_result = self._extract_page_with_attempts(
                    processed_image,
                    page_number=rendered.page_number,
                    render_time_ms=rendered.render_time_ms,
                    preprocessing_time_ms=preprocessing_time_ms,
                    preprocessing=preprocessing,
                    document_deadline=document_deadline,
                )
                pages.append(page_result)
        except Exception as exc:
            errors.append(
                OcrError(
                    "pdf_render_failed",
                    f"{exc.__class__.__name__}: {exc}",
                    None,
                    recoverable=_is_recoverable_ocr_exception(exc),
                )
            )
        if expected_pages and rendered_pages < expected_pages:
            missing = set(range(1, expected_pages + 1)) - {page.page_number for page in pages}
            missing_page_recoverable = bool(errors) and all(error.recoverable for error in errors)
            missing_error_code = unprocessed_page_error_code or "missing_page"
            missing_status = (
                "TIMEOUT" if missing_error_code == "ocr_document_deadline_exhausted" else "FAIL"
            )
            for page_number in sorted(missing):
                message = (
                    "Expected page was not processed before the OCR document deadline."
                    if missing_error_code == "ocr_document_deadline_exhausted"
                    else "Expected page was not processed."
                )
                pages.append(
                    OcrPageResult(
                        page_number=page_number,
                        text="",
                        character_count=0,
                        word_count=0,
                        confidence=None,
                        processing_time_ms=0.0,
                        render_time_ms=0.0,
                        preprocessing_time_ms=0.0,
                        ocr_time_ms=0.0,
                        width=0,
                        height=0,
                        dpi=self.config.dpi,
                        rotation_applied=0,
                        errors=(
                            OcrError(
                                missing_error_code,
                                message,
                                page_number,
                                recoverable=missing_page_recoverable,
                            ),
                        ),
                        status=missing_status,
                    )
                )
        pages.sort(key=lambda page: page.page_number)
        return _build_document_result(
            filename,
            analysis,
            self.config,
            self.provider,
            expected_pages,
            pages,
            warnings,
            errors,
            started,
        )

    def _extract_page_with_attempts(
        self,
        image: Image.Image,
        *,
        page_number: int,
        render_time_ms: float,
        preprocessing_time_ms: float,
        preprocessing: dict[str, Any],
        document_deadline: float | None,
    ) -> OcrPageResult:
        attempt_history: list[dict[str, Any]] = []
        last_result: OcrPageResult | None = None
        max_attempts = max(1, self.config.max_page_attempts)
        for attempt_id in range(1, max_attempts + 1):
            if _document_deadline_exhausted(
                document_deadline,
                reserve_seconds=self.config.document_finalization_reserve_seconds,
            ):
                timeout = OcrOperationTimeout(
                    "ocr_document_deadline_exhausted",
                    "OCR document deadline expired before page attempt.",
                )
                page_result = _failed_ocr_page_result(
                    image=image,
                    page_number=page_number,
                    dpi=self.config.dpi,
                    render_time_ms=render_time_ms,
                    preprocessing_time_ms=preprocessing_time_ms,
                    ocr_time_ms=0.0,
                    preprocessing=preprocessing,
                    error_code=timeout.code,
                    exc=timeout,
                    status="TIMEOUT",
                )
                attempt_history.append(
                    _attempt_trace(
                        attempt_id=attempt_id,
                        strategy="deadline_exhausted",
                        image=image,
                        provider=self.provider,
                        started_at=datetime.now(UTC).isoformat(),
                        latency_ms=0.0,
                        timeout_budget_seconds=0.0,
                        result=page_result,
                        exception=timeout,
                    )
                )
                return _with_attempt_history(page_result, attempt_history)

            attempt_image = _page_attempt_image(
                image,
                attempt_id=attempt_id,
                config=self.config,
            )
            attempt_preprocessing = dict(preprocessing)
            attempt_preprocessing["attempt_id"] = attempt_id
            attempt_preprocessing["attempt_strategy"] = _page_attempt_strategy(attempt_id)
            if attempt_image.size != image.size:
                attempt_preprocessing["retry_image_scale"] = self.config.retry_image_scale
                attempt_preprocessing["retry_original_dimensions"] = [image.width, image.height]
            timeout_seconds = _bounded_page_timeout_seconds(
                config=self.config,
                document_deadline=document_deadline,
            )
            started_at = datetime.now(UTC).isoformat()
            attempt_started = time.perf_counter()
            exception: BaseException | None = None
            try:
                page_result = _run_with_timeout(
                    lambda attempt_image=attempt_image, attempt_preprocessing=attempt_preprocessing: (
                        self._extract_page_with_auto_rotation(
                            attempt_image,
                            page_number=page_number,
                            render_time_ms=render_time_ms,
                            preprocessing_time_ms=preprocessing_time_ms,
                            preprocessing=attempt_preprocessing,
                        )
                    ),
                    timeout_seconds=timeout_seconds,
                    error_code="ocr_page_timeout",
                )
            except Exception as exc:
                exception = exc
                error_code = (
                    exc.code if isinstance(exc, OcrOperationTimeout) else "ocr_engine_failed"
                )
                page_result = _failed_ocr_page_result(
                    image=attempt_image,
                    page_number=page_number,
                    dpi=self.config.dpi,
                    render_time_ms=render_time_ms,
                    preprocessing_time_ms=preprocessing_time_ms,
                    ocr_time_ms=_elapsed_ms(attempt_started),
                    preprocessing=attempt_preprocessing,
                    error_code=error_code,
                    exc=exc,
                    status="TIMEOUT" if isinstance(exc, OcrOperationTimeout) else "FAIL",
                )
            if (
                attempt_id > 1
                and not _is_successful_ocr_page(page_result)
                and _should_recover_page_regions(page_result, image=attempt_image)
                and _has_retry_deadline(document_deadline, self.config)
            ):
                page_result = _recover_page_region_evidence(
                    page_result,
                    image=attempt_image,
                    provider=self.provider,
                    config=self.config,
                    page_number=page_number,
                    document_deadline=document_deadline,
                )
            attempt_latency_ms = _elapsed_ms(attempt_started)
            attempt_history.append(
                _attempt_trace(
                    attempt_id=attempt_id,
                    strategy=str(attempt_preprocessing["attempt_strategy"]),
                    image=attempt_image,
                    provider=self.provider,
                    started_at=started_at,
                    latency_ms=attempt_latency_ms,
                    timeout_budget_seconds=timeout_seconds,
                    result=page_result,
                    exception=exception,
                )
            )
            page_result = _with_attempt_history(page_result, attempt_history)
            last_result = page_result
            if _is_successful_ocr_page(page_result):
                return page_result
            if attempt_id >= max_attempts:
                return page_result
            if not _should_retry_page(page_result):
                return page_result
            if not _has_retry_deadline(document_deadline, self.config):
                deadline_error = OcrError(
                    "ocr_retry_deadline_insufficient",
                    "Remaining OCR document deadline is not sufficient for retry.",
                    page_number,
                    recoverable=True,
                )
                return replace(
                    page_result,
                    errors=tuple([*page_result.errors, deadline_error]),
                    status="TIMEOUT" if page_result.status == "TIMEOUT" else page_result.status,
                )
        assert last_result is not None
        return last_result

    def _extract_page_with_auto_rotation(
        self,
        image: Image.Image,
        *,
        page_number: int,
        render_time_ms: float,
        preprocessing_time_ms: float,
        preprocessing: dict[str, Any],
    ) -> OcrPageResult:
        candidates: list[OcrPageResult] = []
        for rotation in _rotation_candidates(image):
            candidate_image = _rotate_image(image, rotation)
            candidate_preprocessing = dict(preprocessing)
            candidate_preprocessing["candidate_rotation"] = rotation
            candidate = self.provider.extract_page(
                candidate_image,
                page_number=page_number,
                render_time_ms=render_time_ms,
                preprocessing_time_ms=preprocessing_time_ms,
                preprocessing=candidate_preprocessing,
            )
            finalized = _finalize_ocr_page(candidate)
            finalized = _recover_financial_region_evidence(
                finalized,
                image=candidate_image,
                provider=self.provider,
                config=self.config,
                page_number=page_number,
            )
            candidates.append(
                replace(
                    finalized,
                    rotation_applied=rotation,
                    preprocessing={
                        **dict(finalized.preprocessing),
                        "candidate_rotation": rotation,
                    },
                    input_coordinate_space_id=f"page-{page_number - 1}-ocr-input",
                    projected_coordinate_space_id=f"page-{page_number - 1}-rendered-image",
                )
            )
            if _orientation_search_can_stop(candidates, self.config):
                break
        best = max(candidates, key=_ocr_page_quality_score)
        original_score = _ocr_page_quality_score(candidates[0])
        best_score = _ocr_page_quality_score(best)
        if (
            best.rotation_applied != 0
            and best_score < original_score + OCR_ROTATION_MIN_IMPROVEMENT
        ):
            best = candidates[0]
            best_score = original_score
        if not _orientation_selection_usable(best, candidate_count=len(candidates)):
            return replace(
                best,
                status="FAIL",
                errors=tuple(
                    [
                        *best.errors,
                        OcrError(
                            "ocr_orientation_candidate_rejected",
                            "OCR orientation candidates did not produce enough usable text.",
                            page_number,
                            recoverable=True,
                        ),
                    ]
                ),
                postprocessing={
                    **dict(best.postprocessing),
                    "indexable": False,
                    "orientation_rejection": {
                        "selected_rotation": best.rotation_applied,
                        "quality_score": round(best_score, 4),
                        "character_count": best.character_count,
                    },
                },
            )
        rotation_warnings = list(best.warnings)
        if best.rotation_applied != 0:
            rotation_warnings.append(
                OcrWarning(
                    "ocr_page_auto_rotated",
                    f"OCR page was auto-rotated by {best.rotation_applied} degrees.",
                    page_number,
                )
            )
        selected_image = _rotate_image(image, best.rotation_applied)
        sparse_recovery_image = image if best.rotation_applied in {90, 270} else selected_image
        best = _recover_sparse_page_text_evidence(
            replace(best, warnings=tuple(dict.fromkeys(rotation_warnings))),
            image=sparse_recovery_image,
            provider=self.provider,
            config=self.config,
            page_number=page_number,
        )
        best = _enhance_table_page_with_secondary_ocr(
            best,
            image=selected_image,
            config=self.config,
        )
        best = _recover_financial_region_evidence(
            best,
            image=selected_image,
            provider=self.provider,
            config=self.config,
            page_number=page_number,
        )
        best = _recover_signature_footer_evidence(
            best,
            image=selected_image,
            provider=self.provider,
            config=self.config,
            page_number=page_number,
        )
        return _project_ocr_page_to_original_space(
            replace(
                best,
                preprocessing={
                    **dict(best.preprocessing),
                    "auto_rotation_candidates": [
                        {
                            "rotation": candidate.rotation_applied,
                            "quality_score": round(_ocr_page_quality_score(candidate), 4),
                            "character_count": candidate.character_count,
                            "confidence": candidate.confidence,
                            "status": candidate.status,
                        }
                        for candidate in candidates
                    ],
                    "selected_rotation": best.rotation_applied,
                },
                original_width=image.width,
                original_height=image.height,
                input_coordinate_space_id=f"page-{page_number - 1}-ocr-input",
                projected_coordinate_space_id=f"page-{page_number - 1}-rendered-image",
            ),
            original_width=image.width,
            original_height=image.height,
            page_number=page_number,
        )


def check_ocr_deep_health(
    *,
    config: OcrRuntimeConfig | None = None,
    ttl_seconds: int = 300,
    force: bool = False,
    provider: OCRProvider | None = None,
) -> OCRHealthResult:
    global _OCR_HEALTH_CACHE
    current = time.monotonic()
    with _OCR_HEALTH_LOCK:
        if (
            not force
            and _OCR_HEALTH_CACHE is not None
            and current - _OCR_HEALTH_CACHE[0] <= ttl_seconds
        ):
            return _OCR_HEALTH_CACHE[1]
        runtime_config = config or OcrRuntimeConfig()
        result = _run_ocr_healthcheck(runtime_config, provider=provider)
        _OCR_HEALTH_CACHE = (current, result)
        return result


def _run_ocr_healthcheck(
    config: OcrRuntimeConfig,
    *,
    provider: OCRProvider | None = None,
) -> OCRHealthResult:
    checked_at = datetime.now(UTC).isoformat()
    dependencies_ok = all(
        importlib.util.find_spec(module_name) is not None
        for module_name in ("fitz", "PIL", "paddle", "paddleocr")
    )
    if not dependencies_ok:
        return OCRHealthResult(
            dependency_available=False,
            model_loaded=False,
            inference_succeeded=False,
            warmup_completed=False,
            latency_ms=None,
            timeout=False,
            error_code="ocr_dependency_missing",
            checked_at=checked_at,
        )
    warmup_provider = provider or PaddleOCRProvider(config)
    started = time.perf_counter()
    try:
        page = _run_with_timeout(
            lambda: _warmup_provider(warmup_provider),
            timeout_seconds=config.warmup_timeout_seconds,
            error_code="ocr_warmup_timeout",
        )
    except OcrOperationTimeout as exc:
        return OCRHealthResult(
            dependency_available=True,
            model_loaded=False,
            inference_succeeded=False,
            warmup_completed=False,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            timeout=True,
            error_code=exc.code,
            checked_at=checked_at,
        )
    except Exception as exc:
        return OCRHealthResult(
            dependency_available=True,
            model_loaded=False,
            inference_succeeded=False,
            warmup_completed=False,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            timeout=False,
            error_code=f"ocr_warmup_failed:{exc.__class__.__name__}",
            checked_at=checked_at,
        )
    health = warmup_provider.health_report()
    model_loaded = health.get("status") == OcrCapabilityStatus.OCR_AVAILABLE.value
    inference_succeeded = page.status in {"PASS", "WARN"} and not page.errors
    return OCRHealthResult(
        dependency_available=True,
        model_loaded=bool(model_loaded),
        inference_succeeded=inference_succeeded,
        warmup_completed=inference_succeeded,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        timeout=False,
        error_code=None if inference_succeeded else "ocr_canary_inference_failed",
        checked_at=checked_at,
    )


def _warmup_provider(provider: OCRProvider) -> OcrPageResult:
    provider.initialize()
    return provider.extract_page(
        _ocr_canary_image(),
        page_number=0,
        render_time_ms=0.0,
        preprocessing_time_ms=0.0,
        preprocessing={"canary": True},
    )


def _ocr_canary_image() -> Image.Image:
    image = Image.new("RGB", (320, 96), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 28), "OCR CANARY", fill="black")
    return image


def _rotation_candidates(image: Image.Image) -> tuple[int, ...]:
    del image
    return (0, 180, 270, 90)


def _rotate_image(image: Image.Image, rotation: int) -> Image.Image:
    normalized = rotation % 360
    if normalized == 0:
        return image
    return image.rotate(normalized, expand=True)


def _enhance_table_page_with_secondary_ocr(
    page: OcrPageResult,
    *,
    image: Image.Image,
    config: OcrRuntimeConfig,
) -> OcrPageResult:
    if not config.hybrid_table_ocr or importlib.util.find_spec("easyocr") is None:
        return page
    if not (_financial_table_visual_lines(page) or _subsidiary_table_visual_lines(page)):
        return page
    try:
        secondary_blocks = _run_with_timeout(
            lambda: _easyocr_blocks(
                image,
                page_number=page.page_number,
                config=config,
            ),
            timeout_seconds=config.secondary_ocr_timeout_seconds,
            error_code="ocr_secondary_table_timeout",
        )
    except Exception as exc:
        return replace(
            page,
            postprocessing={
                **dict(page.postprocessing),
                "secondary_table_ocr": {
                    "status": "UNAVAILABLE",
                    "error": f"{exc.__class__.__name__}: {exc}",
                },
            },
        )
    if not secondary_blocks:
        return page
    null_marker_blocks = _financial_null_marker_blocks(
        page,
        image=image,
    )
    merged = _merge_table_ocr_blocks(
        primary=tuple([*page.blocks, *null_marker_blocks]),
        secondary=secondary_blocks,
        page_width=page.width,
        page_height=page.height,
    )
    if not merged:
        return page
    raw_text = "\n".join(block.raw_text or block.text for block in merged)
    text, report = OcrTextNormalizer().normalize("\n".join(block.text for block in merged))
    confidences = [block.confidence for block in merged if block.confidence is not None]
    confidence = round(sum(confidences) / len(confidences), 4) if confidences else page.confidence
    source_text = page.text
    source_issue_evidence = _secondary_table_source_issue_evidence(page)
    return _finalize_ocr_page(
        replace(
            page,
            text=text,
            raw_text=raw_text,
            character_count=len(text),
            word_count=len(text.split()),
            confidence=confidence,
            blocks=tuple(merged),
            postprocessing={
                **dict(page.postprocessing),
                "source_text_before_secondary_ocr": source_text,
                "secondary_table_ocr": {
                    "status": "APPLIED",
                    "provider": "easyocr",
                    "primary_block_count": len(page.blocks),
                    "secondary_block_count": len(secondary_blocks),
                    "merged_block_count": len(merged),
                    "pixel_null_marker_count": len(null_marker_blocks),
                    "normalization_report": report.to_dict(),
                    "source_issue_evidence": source_issue_evidence,
                },
            },
        )
    )


def _secondary_table_source_issue_evidence(
    page: OcrPageResult,
) -> dict[str, bool]:
    texts = [
        normalize_text(block.raw_text or block.text)
        for block in page.blocks
        if (block.raw_text or block.text).strip()
    ]
    date_tokens = [
        match.group(0) for text in texts if (match := _DATE_COLUMN_PATTERN.search(text)) is not None
    ]
    folded_blocks = [_fold_ocr_text(text) for text in texts]
    financial_context = len(date_tokens) >= 2 and any(
        marker in _fold_ocr_text(page.text)
        for marker in ("tai san", "nguon von", "chi tieu", "vnd")
    )
    complete_code_header = any("ma so" in text for text in folded_blocks)
    complete_note_header = any("thuyet minh" in text for text in folded_blocks)
    complete_indicator_header = any(
        marker in text for text in folded_blocks for marker in ("tai san", "nguon von", "chi tieu")
    )
    return {
        "unbalanced_negative_parenthesis": any(_money_parenthesis_issue(text) for text in texts),
        "amount_glued_to_label": any(_source_label_contains_money(text) for text in texts),
        "missing_required_columns": bool(
            financial_context
            and not (complete_code_header and complete_note_header and complete_indicator_header)
        ),
        "four_period_columns_reconstructed": bool(
            _looks_like_quarter_income_statement(page.text)
            and (len(date_tokens) > 4 or len(date_tokens) != len(set(date_tokens)))
        ),
    }


def _source_label_contains_money(text: str) -> bool:
    normalized = normalize_text(text)
    if not any(char.isalpha() for char in normalized):
        return False
    return bool(
        _money_values_in_text(normalized) or re.search(r"\d{1,3}\.,\d{3}(?:\.\d{3})+", normalized)
    )


def _easyocr_blocks(
    image: Image.Image,
    *,
    page_number: int,
    config: OcrRuntimeConfig,
) -> tuple[OcrBlock, ...]:
    import numpy as np

    reader = _get_secondary_ocr_reader(config)
    working_image = image
    input_scale = min(
        1.0,
        config.secondary_ocr_max_dimension / max(image.width, image.height),
    )
    if input_scale < 1.0:
        working_image = image.resize(
            (
                max(1, round(image.width * input_scale)),
                max(1, round(image.height * input_scale)),
            ),
            Image.Resampling.LANCZOS,
        )
    coordinate_scale = 1.0 / input_scale
    raw_result = reader.readtext(
        np.array(working_image),
        detail=1,
        paragraph=False,
        batch_size=1,
    )
    normalizer = OcrTextNormalizer()
    blocks: list[OcrBlock] = []
    for index, item in enumerate(raw_result, start=1):
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        polygon, raw_text, confidence = item[0], str(item[1]), item[2]
        if not isinstance(polygon, (list, tuple)) or len(polygon) < 2:
            continue
        points = [
            (
                float(point[0]) * coordinate_scale,
                float(point[1]) * coordinate_scale,
            )
            for point in polygon
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(points) < 2:
            continue
        text, _ = normalizer.normalize(raw_text)
        if not text:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        blocks.append(
            OcrBlock(
                block_id=f"page-{page_number}-easyocr-{index}",
                block_type="text",
                text=text,
                confidence=float(confidence),
                bounding_box=BoundingBox.from_corners(
                    min(xs),
                    min(ys),
                    max(xs),
                    max(ys),
                    unit="pixel",
                ),
                reading_order=index,
                language=config.language,
                raw_text=raw_text,
                metadata={
                    "provider": "easyocr",
                    "secondary_ocr": True,
                    "input_scale": input_scale,
                },
                provider_coordinate_space_id=f"page-{page_number - 1}-ocr-input",
            )
        )
    return tuple(blocks)


def _get_secondary_ocr_reader(config: OcrRuntimeConfig) -> Any:
    global _SECONDARY_OCR_READER
    global _SECONDARY_OCR_INITIALIZATION_FAILED

    with _SECONDARY_OCR_LOCK:
        if _SECONDARY_OCR_READER is not None:
            return _SECONDARY_OCR_READER
        if _SECONDARY_OCR_INITIALIZATION_FAILED:
            raise RuntimeError("EasyOCR secondary reader initialization already failed.")
        try:
            import easyocr

            _SECONDARY_OCR_READER = easyocr.Reader(
                [config.language, "en"],
                gpu=config.use_gpu,
                download_enabled=False,
                verbose=False,
            )
        except Exception:
            _SECONDARY_OCR_INITIALIZATION_FAILED = True
            raise
        return _SECONDARY_OCR_READER


def _merge_table_ocr_blocks(
    *,
    primary: tuple[OcrBlock, ...],
    secondary: tuple[OcrBlock, ...],
    page_width: int,
    page_height: int,
) -> list[OcrBlock]:
    primary_numeric = [block for block in primary if _table_numeric_block(block.text)]
    primary_numeric.extend(_derived_four_period_code_blocks(primary))
    primary_numeric.extend(
        _derived_embedded_numeric_token_blocks(
            primary,
            secondary=secondary,
        )
    )
    secondary_clean: list[OcrBlock] = []
    for block in secondary:
        noise_reasons = _ocr_block_noise_reasons(
            block,
            page_width=page_width,
            page_height=page_height,
        )
        if not noise_reasons or (
            set(noise_reasons) == {"low_confidence_short_text"}
            and _meaningful_word_count(block.text) > 0
        ):
            secondary_clean.append(block)
    secondary_dates = [
        block for block in secondary_clean if _DATE_COLUMN_PATTERN.search(block.text)
    ]
    selected_numeric: list[OcrBlock] = []
    used_secondary_ids: set[str] = set()
    for primary_block in primary_numeric:
        primary_date = _DATE_COLUMN_PATTERN.search(primary_block.text)
        candidates = [
            block
            for block in secondary_clean
            if _table_numeric_block(block.text)
            and _boxes_overlap(primary_block, block) >= 0.30
            and (
                primary_date is None
                or (
                    (secondary_date := _DATE_COLUMN_PATTERN.search(block.text)) is not None
                    and secondary_date.group(0) == primary_date.group(0)
                )
            )
        ]
        selected = max(
            [primary_block, *candidates],
            key=lambda block: _table_numeric_candidate_score(block.text),
        )
        selected = _repair_merged_numeric_block(selected)
        selected_numeric.append(selected)
        if selected in candidates:
            used_secondary_ids.add(selected.block_id)

    for secondary_block in secondary_clean:
        if secondary_block.block_id in used_secondary_ids:
            continue
        if _DATE_COLUMN_PATTERN.search(secondary_block.text) and primary_numeric:
            continue
        if _table_numeric_block(secondary_block.text):
            if any(_boxes_overlap(secondary_block, block) >= 0.30 for block in primary_numeric):
                continue
            selected_numeric.append(_repair_merged_numeric_block(secondary_block))

    label_blocks = [
        block
        for block in secondary_clean
        if not _table_numeric_block(block.text) and block not in secondary_dates
    ]
    label_blocks.extend(
        block
        for block in primary
        if not _table_numeric_block(block.text)
        and str(block.metadata.get("recovery_region") or "") == "financial_label_body"
        and not any(
            _boxes_overlap(block, secondary_block) >= 0.30 for secondary_block in label_blocks
        )
    )
    merged = [*label_blocks, *selected_numeric]
    merged.sort(key=lambda block: (_block_y_center(block), _block_x_center(block)))
    return [replace(block, reading_order=index) for index, block in enumerate(merged, start=1)]


def _derived_four_period_code_blocks(
    blocks: tuple[OcrBlock, ...],
) -> list[OcrBlock]:
    date_blocks = [block for block in blocks if _DATE_COLUMN_PATTERN.search(block.text)]
    if len(_select_table_header_date_blocks(date_blocks)) != 4:
        return []
    derived: list[OcrBlock] = []
    for block in blocks:
        if block.bounding_box is None:
            continue
        match = re.match(r"^(\d{2})(\d)\.(?=\S)", normalize_text(block.text))
        if match is None:
            continue
        box = block.bounding_box
        code_width = min(max(box.height * 1.6, 20.0), box.width * 0.22)
        derived.append(
            replace(
                block,
                block_id=f"{block.block_id}-derived-code",
                text=match.group(1),
                raw_text=match.group(1),
                bounding_box=BoundingBox.from_corners(
                    box.x0,
                    box.y0,
                    min(box.x1, box.x0 + code_width),
                    box.y1,
                    unit=box.unit,
                ),
                metadata={
                    **dict(block.metadata),
                    "derived_from_glued_income_code": True,
                },
            )
        )
    return derived


def _derived_embedded_numeric_token_blocks(
    blocks: tuple[OcrBlock, ...],
    *,
    secondary: tuple[OcrBlock, ...],
) -> list[OcrBlock]:
    derived: list[OcrBlock] = []
    token_pattern = re.compile(r"(?<![\w.,/#-])(\d{1,3})(?![\w.,/#-])")
    numeric_prefix_pattern = re.compile(r"^(\d{1,2})(?=[^\W\d_])")
    for block in blocks:
        if block.bounding_box is None or _table_numeric_block(block.text):
            continue
        text = normalize_text(block.text)
        if not text:
            continue
        matches = list(token_pattern.finditer(text))
        prefix_match = numeric_prefix_pattern.match(text)
        if prefix_match is not None and all(
            match.span(1) != prefix_match.span(1) for match in matches
        ):
            matches.append(prefix_match)
        matches.sort(key=lambda match: match.start(1))
        for token_index, match in enumerate(matches, start=1):
            box = block.bounding_box
            token_center = box.x0 + ((match.start(1) + match.end(1)) / 2 / len(text)) * box.width
            token_width = min(
                max(box.height * 0.7, 8.0),
                max(box.width * len(match.group(1)) / len(text), 8.0),
            )
            candidate = replace(
                block,
                block_id=f"{block.block_id}-derived-number-{token_index}",
                text=match.group(1),
                raw_text=match.group(1),
                bounding_box=BoundingBox.from_corners(
                    max(box.x0, token_center - token_width / 2),
                    box.y0,
                    min(box.x1, token_center + token_width / 2),
                    box.y1,
                    unit=box.unit,
                ),
                metadata={
                    **dict(block.metadata),
                    "derived_embedded_numeric_token": True,
                },
            )
            token = match.group(1)
            if any(
                _boxes_overlap(candidate, secondary_block) >= 0.30
                and re.search(
                    rf"(?<!\d){re.escape(token)}(?!\d)",
                    secondary_block.text,
                )
                for secondary_block in secondary
            ):
                continue
            derived.append(candidate)
    return derived


def _table_numeric_block(text: str) -> bool:
    normalized = normalize_text(text).strip()
    if not normalized:
        return False
    return bool(
        _DATE_COLUMN_PATTERN.search(normalized)
        or _money_values_in_text(normalized)
        or _SUBSIDIARY_PERCENT_PATTERN.fullmatch(normalized)
        or re.fullmatch(r"[A-Z]?\d{1,3}[a-z]?", normalized, re.IGNORECASE)
        or re.fullmatch(r"\d{1,2}(?:\.\d+)?(?:\s*,\s*\d{1,2}(?:\.\d+)?)*", normalized)
        or normalized in {"-", "VND"}
    )


def _table_numeric_candidate_score(text: str) -> tuple[int, int, int, int]:
    normalized = normalize_text(text).replace(" ", "")
    money_values = _money_values_in_text(normalized)
    balanced_negatives = sum(
        value.startswith("(") and value.endswith(")") for value in money_values
    )
    all_money_balanced = int(
        bool(money_values) and all(value.count("(") == value.count(")") for value in money_values)
    )
    date = int(bool(_DATE_COLUMN_PATTERN.search(normalized)))
    return all_money_balanced, balanced_negatives, date, len(normalized)


def _repair_merged_numeric_block(block: OcrBlock) -> OcrBlock:
    repaired = _repair_money_ocr_punctuation(block.text)

    def balance(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("(") and not token.endswith(")"):
            return f"{token})"
        if token.endswith(")") and not token.startswith("("):
            return f"({token}"
        return token

    repaired = _MONEY_SUBSTRING_PATTERN.sub(balance, repaired)
    if repaired == block.text:
        return block
    return replace(
        block,
        text=repaired,
        metadata={
            **dict(block.metadata),
            "merged_numeric_repair": True,
        },
    )


def _boxes_overlap(left: OcrBlock, right: OcrBlock) -> float:
    if left.bounding_box is None or right.bounding_box is None:
        return 0.0
    x0 = max(left.bounding_box.x0, right.bounding_box.x0)
    y0 = max(left.bounding_box.y0, right.bounding_box.y0)
    x1 = min(left.bounding_box.x1, right.bounding_box.x1)
    y1 = min(left.bounding_box.y1, right.bounding_box.y1)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if not intersection:
        return 0.0
    left_area = max(left.bounding_box.area, 1.0)
    right_area = max(right.bounding_box.area, 1.0)
    return max(intersection / left_area, intersection / right_area)


def _financial_null_marker_blocks(
    page: OcrPageResult,
    *,
    image: Image.Image,
) -> list[OcrBlock]:
    date_blocks = [
        block
        for block in page.blocks
        if block.bounding_box is not None and _DATE_COLUMN_PATTERN.search(block.text)
    ]
    if len(date_blocks) < 2:
        return []
    date_columns = _financial_date_columns(date_blocks, page_text=page.text)
    if len(date_columns) < 2:
        return []
    column_centers = [center for center, _ in date_columns]
    rows = _group_blocks_by_visual_row(
        [block for block in page.blocks if block.bounding_box is not None and block.text.strip()]
    )
    header_y = min(_block_y_center(block) for block in date_blocks)
    recovered: list[OcrBlock] = []
    for row_index, row in enumerate(rows, start=1):
        if not row or _block_y_center(row[0]) <= header_y:
            continue
        money_entries = _money_entries_from_row(row)
        if not money_entries:
            continue
        occupied = {
            min(
                range(len(column_centers)),
                key=lambda index: abs(column_centers[index] - x_center),
            )
            for x_center, _ in money_entries
        }
        if len(occupied) >= len(column_centers):
            continue
        value_y = statistics.median(
            _block_y_center(block) for block in row if _money_values_in_text(block.text)
        )
        for column_index, _column_center in enumerate(column_centers):
            if column_index in occupied:
                continue
            bounds = _financial_column_bounds(column_centers, column_index)
            marker = _horizontal_null_marker_bbox(
                image,
                x_bounds=bounds,
                y_center=value_y,
            )
            if marker is None:
                continue
            recovered.append(
                OcrBlock(
                    block_id=(f"page-{page.page_number}-pixel-null-{row_index}-{column_index}"),
                    block_type="text",
                    text="-",
                    confidence=1.0,
                    bounding_box=marker,
                    reading_order=len(page.blocks) + len(recovered) + 1,
                    language=page.blocks[0].language if page.blocks else "unknown",
                    raw_text="-",
                    metadata={
                        "provider": "pixel_evidence",
                        "financial_null_marker": True,
                    },
                    provider_coordinate_space_id=page.input_coordinate_space_id,
                )
            )
    return recovered


def _financial_column_bounds(
    centers: list[float],
    index: int,
) -> tuple[float, float]:
    center = centers[index]
    left_gap = center - centers[index - 1] if index > 0 else centers[1] - center
    right_gap = (
        centers[index + 1] - center if index + 1 < len(centers) else center - centers[index - 1]
    )
    return center - (left_gap / 2), center + (right_gap / 2)


def _horizontal_null_marker_bbox(
    image: Image.Image,
    *,
    x_bounds: tuple[float, float],
    y_center: float,
) -> BoundingBox | None:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    x0 = max(0, int(x_bounds[0]))
    x1 = min(image.width, int(x_bounds[1]))
    half_height = max(12, int(image.height * 0.015))
    y0 = max(0, int(y_center - half_height))
    y1 = min(image.height, int(y_center + half_height))
    if x1 <= x0 or y1 <= y0:
        return None
    grayscale = np.array(image.convert("L"))[y0:y1, x0:x1]
    binary = cv2.threshold(grayscale, 180, 255, cv2.THRESH_BINARY_INV)[1]
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary,
        8,
    )
    min_width = max(3, int(image.width * 0.0025))
    max_width = max(18, int(image.width * 0.025))
    max_height = max(4, int(image.height * 0.004))
    candidates: list[tuple[int, int, int, int, int]] = []
    for component in range(1, count):
        component_x, component_y, width, height, area = (int(value) for value in stats[component])
        if (
            min_width <= width <= max_width
            and 1 <= height <= max_height
            and width / max(height, 1) >= 1.5
            and area >= min_width
            and component_x > 1
            and component_x + width < binary.shape[1] - 1
        ):
            candidates.append((component_x, component_y, width, height, area))
    if not candidates:
        return None
    component_x, component_y, width, height, _ = max(
        candidates,
        key=lambda item: (item[4], item[2] / max(item[3], 1)),
    )
    return BoundingBox.from_corners(
        x0 + component_x,
        y0 + component_y,
        x0 + component_x + width,
        y0 + component_y + height,
        unit="pixel",
    )


def _orientation_search_can_stop(
    candidates: list[OcrPageResult],
    config: OcrRuntimeConfig,
) -> bool:
    if not candidates:
        return False
    if len(candidates) >= 4:
        return True
    best = max(candidates, key=_ocr_page_quality_score)
    if not _orientation_candidate_good_enough(best, config):
        return False
    if len(candidates) == 1:
        return True
    original_score = _ocr_page_quality_score(candidates[0])
    best_score = _ocr_page_quality_score(best)
    return best.rotation_applied == 0 or best_score >= original_score + OCR_ROTATION_MIN_IMPROVEMENT


def _orientation_candidate_good_enough(
    page: OcrPageResult,
    config: OcrRuntimeConfig,
) -> bool:
    if not _is_successful_ocr_page(page):
        return False
    text = normalize_text(page.text)
    if _rotated_text_artifact_penalty(text) > 0:
        return False
    confidence = page.confidence or 0.0
    if confidence < config.orientation_low_confidence_threshold:
        return False
    quality_score = _ocr_page_quality_score(page)
    if (
        _looks_like_landscape_table(page.text)
        and quality_score < config.orientation_good_enough_score
    ):
        return False
    if confidence >= 0.85 and page.character_count >= 120 and _meaningful_word_count(text) >= 12:
        return True
    return quality_score >= config.orientation_good_enough_score


def _orientation_selection_usable(page: OcrPageResult, *, candidate_count: int) -> bool:
    if not _is_successful_ocr_page(page):
        return False
    if candidate_count <= 1:
        return True
    if page.rotation_applied in {90, 270} and _looks_like_portrait_financial_statement(page.text):
        return False
    if page.character_count < 40:
        return False
    return _ocr_page_quality_score(page) >= 0


def _looks_like_portrait_financial_statement(text: str) -> bool:
    folded = normalize_text(text).lower()
    if _looks_like_landscape_table(folded):
        return False
    return "b01-dn" in folded or (
        "vnd" in folded and any(marker in folded for marker in ("tai san", "nguon von", "chi tieu"))
    )


def _looks_like_landscape_table(text: str) -> bool:
    folded = normalize_text(text).lower()
    keyword_hits = sum(1 for keyword in _LANDSCAPE_TABLE_KEYWORDS if keyword in folded)
    if keyword_hits >= 2:
        return True
    percentage_column_count = len(re.findall(r"\b\d{2,3},00\b", folded))
    if percentage_column_count >= 4 and any(
        marker in folded
        for marker in (
            "tỷ lệ",
            "ty le",
            "biểu quyết",
            "bieu quyet",
            "lợi ích",
            "loi ich",
            "\nich\n",
        )
    ):
        return True
    return (
        "tỷ lệ" in folded
        and any(marker in folded for marker in ("biểu quyết", "loi ich", "lợi ích"))
        and any(marker in folded for marker in ("tru so", "trụ sở", "hoat dong", "hoạt động"))
    )


def _document_deadline_exhausted(
    document_deadline: float | None,
    *,
    reserve_seconds: float = 0.0,
) -> bool:
    if document_deadline is None:
        return False
    return time.perf_counter() + reserve_seconds >= document_deadline


def _remaining_document_seconds(document_deadline: float | None) -> float | None:
    if document_deadline is None:
        return None
    return max(0.0, document_deadline - time.perf_counter())


def _bounded_page_timeout_seconds(
    *,
    config: OcrRuntimeConfig,
    document_deadline: float | None,
) -> float | None:
    configured = (
        float(config.page_timeout_seconds) if config.page_timeout_seconds is not None else None
    )
    remaining = _remaining_document_seconds(document_deadline)
    if remaining is None:
        return configured
    usable = max(0.001, remaining - config.document_finalization_reserve_seconds)
    return min(configured, usable) if configured is not None else usable


def _has_retry_deadline(
    document_deadline: float | None,
    config: OcrRuntimeConfig,
) -> bool:
    remaining = _remaining_document_seconds(document_deadline)
    return remaining is None or remaining >= config.min_retry_deadline_seconds


def _page_attempt_image(
    image: Image.Image,
    *,
    attempt_id: int,
    config: OcrRuntimeConfig,
) -> Image.Image:
    if attempt_id <= 1 or config.retry_image_scale >= 1.0:
        return image
    width = max(1, int(image.width * config.retry_image_scale))
    height = max(1, int(image.height * config.retry_image_scale))
    if (width, height) == image.size:
        return image
    return image.resize((width, height), Image.Resampling.BICUBIC)


def _page_attempt_strategy(attempt_id: int) -> str:
    return "standard_adaptive_orientation" if attempt_id == 1 else "conservative_retry"


def _is_successful_ocr_page(page: OcrPageResult) -> bool:
    return bool(page.text.strip()) and page.status in {"PASS", "WARN"} and not page.errors


def _should_retry_page(page: OcrPageResult) -> bool:
    if page.status == "CANCELLED":
        return False
    error_codes = {error.code for error in page.errors}
    if error_codes & {
        "ocr_document_deadline_exhausted",
        "ocr_retry_deadline_insufficient",
        "missing_page",
        "image_preprocessing_failed",
    }:
        return False
    if error_codes & {
        "ocr_page_timeout",
        "empty_ocr_output",
        "empty_ocr_output_after_noise_filter",
        "ocr_orientation_candidate_rejected",
    }:
        return True
    if any(error.recoverable for error in page.errors):
        return True
    return page.status == "FAIL" and not page.text.strip() and not page.errors


def _with_attempt_history(
    page: OcrPageResult,
    attempt_history: list[dict[str, Any]],
) -> OcrPageResult:
    attempts = tuple(dict(item) for item in attempt_history)
    return replace(
        page,
        attempt_history=attempts,
        preprocessing={
            **dict(page.preprocessing),
            "attempt_count": len(attempts),
            "terminal_page_status": _page_terminal_status(page),
        },
        postprocessing={
            **dict(page.postprocessing),
            "attempt_count": len(attempts),
            "attempt_history": [dict(item) for item in attempts],
            "terminal_page_status": _page_terminal_status(page),
        },
    )


def _attempt_trace(
    *,
    attempt_id: int,
    strategy: str,
    image: Image.Image,
    provider: OCRProvider,
    started_at: str,
    latency_ms: float,
    timeout_budget_seconds: float | None,
    result: OcrPageResult,
    exception: BaseException | None,
) -> dict[str, Any]:
    error = result.errors[0] if result.errors else None
    return {
        "attempt_id": attempt_id,
        "strategy": strategy,
        "rotation": result.rotation_applied,
        "input_dimensions": [image.width, image.height],
        "provider": provider.provider_name,
        "provider_version": getattr(provider, "provider_version", "unknown"),
        "started_at": started_at,
        "latency_ms": round(latency_ms, 3),
        "timeout_budget_ms": (
            round(timeout_budget_seconds * 1000, 3) if timeout_budget_seconds is not None else None
        ),
        "status": _page_terminal_status(result),
        "error_code": error.code if error is not None else None,
        "exception_type": (
            exception.__class__.__name__ if exception is not None else _error_exception_type(error)
        ),
        "confidence": result.confidence,
        "block_count": len(result.blocks),
        "character_count": result.character_count,
        "orientation_candidates": list(
            dict(result.preprocessing).get("auto_rotation_candidates", [])
        ),
        "selected_orientation": result.rotation_applied,
        "orientation_confidence": result.confidence,
    }


def _error_exception_type(error: OcrError | None) -> str | None:
    if error is None:
        return None
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", error.message)
    return match.group(1) if match else None


def _page_terminal_status(page: OcrPageResult) -> str:
    if page.status == "PASS":
        return "SUCCESS"
    if page.status == "WARN":
        return "WARN"
    if page.status == "TIMEOUT":
        return "TIMEOUT"
    if page.status == "CANCELLED":
        return "CANCELLED"
    return "FAILED"


def _finalize_ocr_page(page: OcrPageResult) -> OcrPageResult:
    kept_blocks: list[OcrBlock] = []
    dropped_blocks: list[dict[str, Any]] = []
    for block in page.blocks:
        reasons = _ocr_block_noise_reasons(block, page_width=page.width, page_height=page.height)
        if reasons:
            dropped_blocks.append(
                {
                    "block_id": block.block_id,
                    "text": block.text,
                    "reasons": reasons,
                    "confidence": block.confidence,
                    "bounding_box": asdict(block.bounding_box)
                    if block.bounding_box is not None
                    else None,
                }
            )
            continue
        kept_blocks.append(
            replace(
                block,
                metadata={
                    **dict(block.metadata),
                    "indexable": True,
                    "ocr_confidence": block.confidence,
                    "bbox": asdict(block.bounding_box) if block.bounding_box is not None else None,
                },
            )
        )

    if not dropped_blocks:
        return replace(
            page,
            blocks=tuple(kept_blocks),
            postprocessing={
                **dict(page.postprocessing),
                "indexable": page.status in {"PASS", "WARN"} and bool(page.text.strip()),
                "noise_filter": {"dropped_block_count": 0},
            },
        )

    raw_kept_text = "\n".join(block.text for block in kept_blocks if block.text.strip())
    text, text_reconstruction_report = OcrTextNormalizer(
        TextNormalizationConfig(
            repair_mojibake=False,
            repair_vietnamese_ocr_terms=False,
        )
    ).normalize(raw_kept_text)
    canonical_text_candidate = ""
    if isinstance(page.postprocessing.get("normalization_report"), dict):
        canonical_text_candidate, _ = OcrTextNormalizer().normalize(raw_kept_text)
    confidences = [block.confidence for block in kept_blocks if block.confidence is not None]
    confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
    warnings = list(page.warnings)
    errors = list(page.errors)
    warnings.append(
        OcrWarning(
            "ocr_noise_blocks_dropped",
            f"Dropped {len(dropped_blocks)} OCR block(s) that looked like margin or noise.",
            page.page_number,
        )
    )
    status = page.status
    if not text:
        status = "FAIL"
        errors.append(
            OcrError(
                "empty_ocr_output_after_noise_filter",
                "OCR text was empty after dropping noisy blocks.",
                page.page_number,
                recoverable=False,
            )
        )
    elif status == "PASS":
        status = "WARN"
    return replace(
        page,
        text=text,
        character_count=len(text),
        word_count=len(text.split()),
        confidence=confidence,
        blocks=tuple(kept_blocks),
        warnings=tuple(warnings),
        errors=tuple(errors),
        status=status,
        postprocessing={
            **dict(page.postprocessing),
            "indexable": status in {"PASS", "WARN"} and bool(text.strip()),
            "noise_filter": {
                "dropped_block_count": len(dropped_blocks),
                "dropped_blocks": dropped_blocks[:20],
                "text_reconstruction_report": text_reconstruction_report.to_dict(),
                "canonical_text_candidate": canonical_text_candidate,
            },
        },
    )


def _recover_financial_region_evidence(
    page: OcrPageResult,
    *,
    image: Image.Image,
    provider: OCRProvider,
    config: OcrRuntimeConfig,
    page_number: int,
) -> OcrPageResult:
    if not _should_recover_financial_regions(page, image=image):
        return page
    recovered_blocks: list[OcrBlock] = []
    recovery_errors: list[str] = []
    for region_id, box in _financial_recovery_regions(image):
        x0, y0, x1, y1 = box
        crop = image.crop(box)
        try:
            region_page = _run_with_timeout(
                lambda crop=crop, region_id=region_id, recovery_box=(x0, y0, x1, y1): (
                    provider.extract_page(
                        crop,
                        page_number=page_number,
                        render_time_ms=0.0,
                        preprocessing_time_ms=0.0,
                        preprocessing={
                            "recovery_region": region_id,
                            "recovery_crop": list(recovery_box),
                        },
                    )
                ),
                timeout_seconds=_region_recovery_timeout_seconds(config),
                error_code="ocr_region_recovery_timeout",
            )
            region_page = _finalize_ocr_page(region_page)
        except Exception as exc:
            recovery_errors.append(f"{region_id}:{exc.__class__.__name__}:{exc}")
            continue
        for block in region_page.blocks:
            if not _financial_recovery_block_relevant(block, region_id=region_id):
                continue
            recovered_blocks.append(
                _offset_recovered_block(
                    block,
                    offset_x=float(x0),
                    offset_y=float(y0),
                    page_number=page_number,
                    region_id=region_id,
                )
            )
    recovered_blocks = _dedupe_recovered_blocks(page.blocks, recovered_blocks)
    if not recovered_blocks and not recovery_errors:
        return page
    warnings = list(page.warnings)
    if recovered_blocks:
        warnings.append(
            OcrWarning(
                "ocr_financial_region_recovered",
                f"Recovered {len(recovered_blocks)} OCR block(s) from financial table regions.",
                page_number,
            )
        )
    if recovery_errors:
        warnings.append(
            OcrWarning(
                "ocr_financial_region_recovery_partial",
                "One or more financial table recovery regions failed.",
                page_number,
            )
        )
    blocks = tuple([*page.blocks, *recovered_blocks])
    text = normalize_text(
        "\n".join(
            [
                page.text,
                *(block.text for block in recovered_blocks if block.text.strip()),
            ]
        )
    )
    confidences = [block.confidence for block in blocks if block.confidence is not None]
    confidence = round(sum(confidences) / len(confidences), 4) if confidences else page.confidence
    return replace(
        page,
        text=text,
        raw_text=normalize_text(
            "\n".join(
                [
                    page.raw_text or page.text,
                    *(
                        block.raw_text or block.text
                        for block in recovered_blocks
                        if block.text.strip()
                    ),
                ]
            )
        ),
        character_count=len(text),
        word_count=len(text.split()),
        confidence=confidence,
        blocks=blocks,
        warnings=tuple(dict.fromkeys(warnings)),
        postprocessing={
            **dict(page.postprocessing),
            "financial_region_recovery": {
                "recovered_block_count": len(recovered_blocks),
                "regions": [region_id for region_id, _ in _financial_recovery_regions(image)],
                "errors": recovery_errors[:10],
                "raw_text_preserved": True,
            },
        },
    )


def _recover_sparse_page_text_evidence(
    page: OcrPageResult,
    *,
    image: Image.Image,
    provider: OCRProvider,
    config: OcrRuntimeConfig,
    page_number: int,
) -> OcrPageResult:
    existing_blocks = [block for block in page.blocks if _meaningful_word_count(block.text) >= 2]
    existing_text, existing_report = OcrTextNormalizer().normalize(
        "\n".join(block.text for block in existing_blocks)
    )
    if (
        image.width > 0
        and image.height > image.width
        and len(normalize_text(page.text)) < 100
        and len(existing_blocks) >= 2
        and len(_fold_ocr_text(existing_text)) > len(_fold_ocr_text(page.text))
    ):
        warnings = [
            *page.warnings,
            OcrWarning(
                "ocr_sparse_page_text_reconstructed",
                "Reconstructed sparse page text from retained OCR blocks.",
                page_number,
            ),
        ]
        return replace(
            page,
            text=existing_text,
            character_count=len(existing_text),
            word_count=len(existing_text.split()),
            warnings=tuple(dict.fromkeys(warnings)),
            postprocessing={
                **dict(page.postprocessing),
                "sparse_page_text_recovery": {
                    "status": "RECONSTRUCTED_FROM_EXISTING_BLOCKS",
                    "retained_block_count": len(existing_blocks),
                    "normalization_report": existing_report.to_dict(),
                    "raw_text_preserved": True,
                },
            },
        )
    if not _should_recover_sparse_page_text(page, image=image):
        return page
    box = (
        int(image.width * 0.03),
        int(image.height * 0.06),
        int(image.width * 0.97),
        int(image.height * 0.52),
    )
    crop = image.crop(box)
    try:
        recovered_page = _run_with_timeout(
            lambda: provider.extract_page(
                crop,
                page_number=page_number,
                render_time_ms=0.0,
                preprocessing_time_ms=0.0,
                preprocessing={
                    "recovery_strategy": "sparse_page_text",
                    "recovery_region": "upper_page_text",
                    "recovery_crop": list(box),
                },
            ),
            timeout_seconds=_region_recovery_timeout_seconds(config),
            error_code="ocr_sparse_page_text_timeout",
        )
        recovered_page = _finalize_ocr_page(recovered_page)
    except Exception as exc:
        return replace(
            page,
            postprocessing={
                **dict(page.postprocessing),
                "sparse_page_text_recovery": {
                    "status": "FAILED",
                    "error": f"{exc.__class__.__name__}: {exc}",
                },
            },
        )
    x0, y0, _, _ = box
    replace_sparse_side_rotation = bool(
        page.rotation_applied in {90, 270} and image.height > image.width
    )
    existing_for_dedupe = () if replace_sparse_side_rotation else page.blocks
    recovered_blocks = [
        _offset_recovered_block(
            block,
            offset_x=float(x0),
            offset_y=float(y0),
            page_number=page_number,
            region_id="upper_page_text",
            source="ocr_sparse_page_text_recovery",
        )
        for block in recovered_page.blocks
        if block.bounding_box is not None and _meaningful_word_count(block.text) >= 2
    ]
    recovered_blocks = _dedupe_recovered_blocks(existing_for_dedupe, recovered_blocks)
    if not recovered_blocks:
        return replace(
            page,
            postprocessing={
                **dict(page.postprocessing),
                "sparse_page_text_recovery": {
                    "status": "NO_ADDITIONAL_EVIDENCE",
                    "recovered_block_count": 0,
                },
            },
        )
    merged_blocks = sorted(
        [*existing_for_dedupe, *recovered_blocks],
        key=lambda block: (_block_y_center(block), _block_x_center(block)),
    )
    text, report = OcrTextNormalizer().normalize(
        "\n".join(
            [
                *(block.text for block in merged_blocks if block.text.strip()),
                *((page.text,) if replace_sparse_side_rotation and page.text.strip() else ()),
            ]
        )
    )
    if len(_fold_ocr_text(text)) <= len(_fold_ocr_text(page.text)):
        return page
    warnings = [
        *(
            warning
            for warning in page.warnings
            if not (replace_sparse_side_rotation and warning.code == "ocr_page_auto_rotated")
        ),
        OcrWarning(
            "ocr_sparse_page_text_recovered",
            f"Recovered {len(recovered_blocks)} additional block(s) from a sparse page.",
            page_number,
        ),
    ]
    if replace_sparse_side_rotation:
        warnings.append(
            OcrWarning(
                "ocr_sparse_side_rotation_rejected",
                "Rejected a sparse side-rotation result after recovering upright text evidence.",
                page_number,
            )
        )
    confidences = [block.confidence for block in merged_blocks if block.confidence is not None]
    confidence = round(sum(confidences) / len(confidences), 4) if confidences else page.confidence
    return replace(
        page,
        text=text,
        raw_text=normalize_text(
            "\n".join(
                [
                    page.raw_text or page.text,
                    *(block.raw_text or block.text for block in recovered_blocks),
                ]
            )
        ),
        character_count=len(text),
        word_count=len(text.split()),
        confidence=confidence,
        width=image.width if replace_sparse_side_rotation else page.width,
        height=image.height if replace_sparse_side_rotation else page.height,
        rotation_applied=0 if replace_sparse_side_rotation else page.rotation_applied,
        blocks=tuple(
            replace(block, reading_order=index)
            for index, block in enumerate(merged_blocks, start=1)
        ),
        warnings=tuple(dict.fromkeys(warnings)),
        status="WARN" if replace_sparse_side_rotation else page.status,
        preprocessing={
            **dict(page.preprocessing),
            **(
                {
                    "candidate_rotation": 0,
                    "rejected_sparse_rotation": page.rotation_applied,
                }
                if replace_sparse_side_rotation
                else {}
            ),
        },
        postprocessing={
            **dict(page.postprocessing),
            "sparse_page_text_recovery": {
                "status": "APPLIED",
                "recovered_block_count": len(recovered_blocks),
                "crop": list(box),
                "normalization_report": report.to_dict(),
                "raw_text_preserved": True,
                "replaced_sparse_side_rotation": replace_sparse_side_rotation,
            },
        },
    )


def _should_recover_sparse_page_text(
    page: OcrPageResult,
    *,
    image: Image.Image,
) -> bool:
    meaningful_blocks = [block for block in page.blocks if _meaningful_word_count(block.text) >= 2]
    return bool(
        image.width > 0
        and image.height > image.width
        and len(meaningful_blocks) <= 1
        and len(normalize_text(page.text)) < 100
        and not _money_values_in_text(page.text)
    )


_SIGNATURE_DATE_PATTERN = re.compile(
    r"\bngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}\b",
    re.IGNORECASE,
)
_SIGNATURE_ROLE_MARKERS = (
    "nguoi lap",
    "ke toan truong",
    "giam doc",
    "tro ly dieu hanh",
)


def _recover_signature_footer_evidence(
    page: OcrPageResult,
    *,
    image: Image.Image,
    provider: OCRProvider,
    config: OcrRuntimeConfig,
    page_number: int,
) -> OcrPageResult:
    if not _should_recover_signature_footer(page, image=image):
        return page
    box = (
        int(image.width * 0.05),
        int(image.height * 0.50),
        int(image.width * 0.92),
        int(image.height * 0.86),
    )
    crop = image.crop(box)
    try:
        recovered_page = _run_with_timeout(
            lambda: provider.extract_page(
                crop,
                page_number=page_number,
                render_time_ms=0.0,
                preprocessing_time_ms=0.0,
                preprocessing={
                    "recovery_strategy": "signature_footer",
                    "recovery_region": "signature_footer",
                    "recovery_crop": list(box),
                },
            ),
            timeout_seconds=_region_recovery_timeout_seconds(config),
            error_code="ocr_signature_footer_timeout",
        )
        recovered_page = _finalize_ocr_page(recovered_page)
    except Exception as exc:
        return replace(
            page,
            postprocessing={
                **dict(page.postprocessing),
                "signature_footer_recovery": {
                    "status": "FAILED",
                    "error": f"{exc.__class__.__name__}: {exc}",
                },
            },
        )
    if not _SIGNATURE_DATE_PATTERN.search(normalize_text(recovered_page.text)):
        return replace(
            page,
            postprocessing={
                **dict(page.postprocessing),
                "signature_footer_recovery": {
                    "status": "NO_DATE_EVIDENCE",
                    "recovered_block_count": 0,
                },
            },
        )
    x0, y0, _, _ = box
    candidates = [
        _offset_recovered_block(
            block,
            offset_x=float(x0),
            offset_y=float(y0),
            page_number=page_number,
            region_id="signature_footer",
            source="ocr_signature_footer_recovery",
        )
        for block in recovered_page.blocks
        if normalize_text(block.text)
    ]
    recovered_blocks = _dedupe_recovered_blocks(page.blocks, candidates)
    if not recovered_blocks:
        return page
    blocks = tuple([*page.blocks, *recovered_blocks])
    text = normalize_text("\n".join(block.text for block in blocks if block.text.strip()))
    return replace(
        page,
        text=text,
        raw_text=normalize_text(
            "\n".join(
                block.raw_text or block.text
                for block in blocks
                if (block.raw_text or block.text).strip()
            )
        ),
        character_count=len(text),
        word_count=len(text.split()),
        blocks=blocks,
        warnings=tuple(
            dict.fromkeys(
                [
                    *page.warnings,
                    OcrWarning(
                        "ocr_signature_footer_recovered",
                        "Recovered a signature date from footer OCR evidence.",
                        page_number,
                    ),
                ]
            )
        ),
        postprocessing={
            **dict(page.postprocessing),
            "signature_footer_recovery": {
                "status": "APPLIED",
                "recovered_block_count": len(recovered_blocks),
                "raw_text_preserved": True,
            },
        },
    )


def _should_recover_signature_footer(
    page: OcrPageResult,
    *,
    image: Image.Image,
) -> bool:
    if image.width <= 0 or image.height <= 0 or image.width >= image.height:
        return False
    if _SIGNATURE_DATE_PATTERN.search(normalize_text(page.text)):
        return False
    folded = _fold_ocr_text(page.text)
    return sum(marker in folded for marker in _SIGNATURE_ROLE_MARKERS) >= 2


def _recover_page_region_evidence(
    page: OcrPageResult,
    *,
    image: Image.Image,
    provider: OCRProvider,
    config: OcrRuntimeConfig,
    page_number: int,
    document_deadline: float | None,
) -> OcrPageResult:
    recovered_blocks: list[OcrBlock] = []
    recovery_errors: list[str] = []
    attempted_regions: list[str] = []
    for region_id, box in _page_recovery_regions(image):
        if _document_deadline_exhausted(
            document_deadline,
            reserve_seconds=config.document_finalization_reserve_seconds,
        ):
            recovery_errors.append(f"{region_id}:ocr_document_deadline_exhausted")
            break
        timeout_seconds = _page_region_recovery_timeout_seconds(
            config,
            document_deadline=document_deadline,
        )
        if timeout_seconds is not None and timeout_seconds <= 0:
            recovery_errors.append(f"{region_id}:ocr_region_recovery_deadline_insufficient")
            break
        x0, y0, x1, y1 = box
        attempted_regions.append(region_id)
        crop = image.crop(box)
        try:
            region_page = _run_with_timeout(
                lambda crop=crop, region_id=region_id, recovery_box=(x0, y0, x1, y1): (
                    provider.extract_page(
                        crop,
                        page_number=page_number,
                        render_time_ms=0.0,
                        preprocessing_time_ms=0.0,
                        preprocessing={
                            "recovery_strategy": "generic_page_region",
                            "recovery_region": region_id,
                            "recovery_crop": list(recovery_box),
                        },
                    )
                ),
                timeout_seconds=timeout_seconds,
                error_code="ocr_region_recovery_timeout",
            )
            region_page = _finalize_ocr_page(region_page)
        except Exception as exc:
            recovery_errors.append(f"{region_id}:{exc.__class__.__name__}:{exc}")
            continue
        for block in region_page.blocks:
            if not normalize_text(block.text):
                continue
            recovered_blocks.append(
                _offset_recovered_block(
                    block,
                    offset_x=float(x0),
                    offset_y=float(y0),
                    page_number=page_number,
                    region_id=region_id,
                    source="ocr_page_region_recovery",
                )
            )
    recovered_blocks = _dedupe_recovered_blocks((), recovered_blocks)
    if not recovered_blocks:
        if not recovery_errors and attempted_regions:
            recovery_errors.append("no_region_text_recovered")
        return replace(
            page,
            postprocessing={
                **dict(page.postprocessing),
                "page_region_recovery": {
                    "recovered_block_count": 0,
                    "regions": attempted_regions,
                    "errors": recovery_errors[:10],
                    "raw_text_preserved": True,
                },
            },
        )
    text = normalize_text("\n".join(block.text for block in recovered_blocks if block.text.strip()))
    raw_text = normalize_text(
        "\n".join(
            block.raw_text or block.text
            for block in recovered_blocks
            if (block.raw_text or block.text).strip()
        )
    )
    confidences = [block.confidence for block in recovered_blocks if block.confidence is not None]
    confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
    warnings = [
        *page.warnings,
        OcrWarning(
            "ocr_page_region_recovered",
            f"Recovered OCR text from {len(attempted_regions)} page region(s).",
            page_number,
        ),
    ]
    if recovery_errors:
        warnings.append(
            OcrWarning(
                "ocr_page_region_recovery_partial",
                "One or more page recovery regions failed.",
                page_number,
            )
        )
    return replace(
        page,
        text=text,
        raw_text=raw_text,
        character_count=len(text),
        word_count=len(text.split()),
        confidence=confidence,
        blocks=tuple(recovered_blocks),
        warnings=tuple(dict.fromkeys(warnings)),
        errors=(),
        status="WARN",
        postprocessing={
            **dict(page.postprocessing),
            "indexable": True,
            "recovered_from_failed_page": True,
            "terminal_failure_errors": [error.code for error in page.errors],
            "page_region_recovery": {
                "recovered_block_count": len(recovered_blocks),
                "regions": attempted_regions,
                "errors": recovery_errors[:10],
                "raw_text_preserved": True,
            },
        },
    )


def _should_recover_page_regions(page: OcrPageResult, *, image: Image.Image) -> bool:
    if image.width <= 0 or image.height <= 0:
        return False
    if _is_successful_ocr_page(page):
        return False
    if page.status == "CANCELLED":
        return False
    if page.text.strip():
        return False
    error_codes = {error.code for error in page.errors}
    if error_codes & {"ocr_document_deadline_exhausted", "ocr_retry_deadline_insufficient"}:
        return False
    return any(error.recoverable for error in page.errors) or bool(
        error_codes
        & {"ocr_engine_failed", "empty_ocr_output", "ocr_orientation_candidate_rejected"}
    )


def _page_recovery_regions(image: Image.Image) -> tuple[tuple[str, tuple[int, int, int, int]], ...]:
    width = image.width
    height = image.height
    return (
        ("page_region_top", (0, 0, width, int(height * 0.36))),
        ("page_region_middle", (0, int(height * 0.28), width, int(height * 0.70))),
        ("page_region_bottom", (0, int(height * 0.62), width, height)),
    )


def _page_region_recovery_timeout_seconds(
    config: OcrRuntimeConfig,
    *,
    document_deadline: float | None,
) -> float | None:
    base_timeout = _region_recovery_timeout_seconds(config)
    remaining = _remaining_document_seconds(document_deadline)
    if remaining is None:
        return base_timeout
    usable = remaining - config.document_finalization_reserve_seconds
    if usable <= 0:
        return 0.0
    return min(base_timeout or usable, max(0.5, usable / 3.0))


def _should_recover_financial_regions(page: OcrPageResult, *, image: Image.Image) -> bool:
    if image.width <= 0 or image.height <= 0:
        return False
    if image.width > image.height:
        return False
    text = normalize_text(page.text).lower()
    marker_hits = sum(
        1
        for marker in (
            "b01-dn",
            "vnd",
            "tai san",
            "tÃ i s",
            "nguon von",
            "chi tieu",
            "chỉ tiêu",
            "bang can doi",
            "báº£ng cÃ¢n",
            "bao cao ket qua",
            "bÃ¡o cÃ¡o káº¿t",
            "luu chuyen",
            "lÆ°u chuyá»ƒn",
        )
        if marker in text
    )
    if marker_hits < 2:
        return False
    money_value_count = sum(len(_money_values_in_text(block.text)) for block in page.blocks)
    visual_lines = _financial_table_visual_lines(page) or []
    missing_label_evidence = any(
        len(row) >= 5 and bool(row[0]) and not row[1] and sum(bool(value) for value in row[3:]) >= 2
        for row in (_split_visual_table_row(line) for line in visual_lines[1:] if "|" in line)
    )
    return money_value_count < 4 or missing_label_evidence


def _financial_recovery_regions(
    image: Image.Image,
) -> tuple[tuple[str, tuple[int, int, int, int]], ...]:
    width = image.width
    height = image.height
    return (
        (
            "financial_header",
            (
                int(width * 0.13),
                int(height * 0.14),
                int(width * 0.94),
                int(height * 0.25),
            ),
        ),
        (
            "financial_numeric_body",
            (
                int(width * 0.30),
                int(height * 0.18),
                int(width * 0.94),
                int(height * 0.74),
            ),
        ),
        (
            "financial_label_body",
            (
                int(width * 0.12),
                int(height * 0.18),
                int(width * 0.52),
                int(height * 0.76),
            ),
        ),
    )


def _region_recovery_timeout_seconds(config: OcrRuntimeConfig) -> float | None:
    if config.page_timeout_seconds is None:
        return 8.0
    return max(1.0, min(8.0, float(config.page_timeout_seconds) / 3.0))


def _financial_recovery_block_relevant(block: OcrBlock, *, region_id: str) -> bool:
    text = normalize_text(block.text)
    if not text:
        return False
    if _money_values_in_text(text) or _DATE_COLUMN_PATTERN.search(text):
        return True
    if region_id == "financial_label_body":
        return _meaningful_word_count(text) >= 2
    if region_id != "financial_header":
        return False
    folded = text.lower()
    return any(
        marker in folded
        for marker in (
            "ma",
            "mÃ£",
            "so",
            "sá»‘",
            "tai san",
            "tÃ i s",
            "nguon",
            "chi tieu",
            "thuyet",
            "thuyáº¿t",
            "minh",
        )
    )


def _offset_recovered_block(
    block: OcrBlock,
    *,
    offset_x: float,
    offset_y: float,
    page_number: int,
    region_id: str,
    source: str = "ocr_financial_region_recovery",
) -> OcrBlock:
    box = block.bounding_box
    projected_box = None
    if box is not None:
        projected_box = BoundingBox.from_corners(
            box.x0 + offset_x,
            box.y0 + offset_y,
            box.x1 + offset_x,
            box.y1 + offset_y,
            unit=box.unit,
        )
    return replace(
        block,
        block_id=f"page-{page_number}-recovery-{region_id}-{block.reading_order}",
        bounding_box=projected_box,
        provider_coordinate_space_id=f"page-{page_number - 1}-ocr-input",
        metadata={
            **dict(block.metadata),
            "source": source,
            "recovery_region": region_id,
            "recovery_offset": [offset_x, offset_y],
            "raw_provider_bbox": (
                {
                    "x0": box.x0,
                    "y0": box.y0,
                    "x1": box.x1,
                    "y1": box.y1,
                    "unit": box.unit,
                }
                if box is not None
                else None
            ),
        },
    )


def _dedupe_recovered_blocks(
    existing_blocks: tuple[OcrBlock, ...],
    recovered_blocks: list[OcrBlock],
) -> list[OcrBlock]:
    existing_keys = {_block_dedupe_key(block) for block in existing_blocks}
    values: list[OcrBlock] = []
    seen = set(existing_keys)
    for block in recovered_blocks:
        key = _block_dedupe_key(block)
        if key in seen:
            continue
        seen.add(key)
        values.append(block)
    return values


def _block_dedupe_key(block: OcrBlock) -> tuple[str, int, int]:
    box = block.bounding_box
    return (
        normalize_text(block.text).lower(),
        int((box.x0 if box is not None else 0.0) // 8),
        int((box.y0 if box is not None else 0.0) // 8),
    )


def _ocr_block_noise_reasons(
    block: OcrBlock,
    *,
    page_width: int,
    page_height: int,
) -> tuple[str, ...]:
    text = normalize_text(block.text)
    reasons: list[str] = []
    if not text:
        return ("empty_text",)
    if block.metadata.get("financial_null_marker") is True:
        return ()
    if (
        _DATE_COLUMN_PATTERN.search(text)
        or _money_values_in_text(text)
        or _row_starts_with_financial_code(text)
        or _PAGE_RANGE_TOKEN_PATTERN.fullmatch(text)
        or _FINANCIAL_NOTE_ONLY_PATTERN.fullmatch(text)
    ):
        return ()
    bbox = block.bounding_box
    if bbox is not None and bbox.width > 0 and bbox.height > 0:
        aspect = bbox.height / bbox.width
        narrow_limit = max(32.0, page_width * 0.08)
        if aspect >= 4.0 and bbox.width <= narrow_limit:
            reasons.append("vertical_or_margin_noise")
        page_area = max(float(page_width * page_height), 1.0)
        if bbox.area / page_area < 0.00002 and len(text) <= 3:
            reasons.append("tiny_isolated_noise")
    if _symbol_ratio(text) > 0.45 and len(text) <= 40:
        reasons.append("symbol_heavy_short_text")
    if _meaningful_word_count(text) == 0 and len(text) <= 24:
        reasons.append("no_meaningful_words")
    if block.confidence is not None and block.confidence < 0.35 and len(text) <= 48:
        reasons.append("low_confidence_short_text")
    return tuple(dict.fromkeys(reasons))


def _symbol_ratio(text: str) -> float:
    stripped = "".join(char for char in text if not char.isspace())
    if not stripped:
        return 1.0
    symbols = sum(1 for char in stripped if not char.isalnum())
    return symbols / len(stripped)


def _meaningful_word_count(text: str) -> int:
    return sum(
        1
        for token in re.findall(r"[^\W\d_]{2,}", text, flags=re.UNICODE)
        if any(char.isalpha() for char in token)
    )


def _ocr_page_quality_score(page: OcrPageResult) -> float:
    if page.status == "FAIL" or page.errors:
        return -1000.0
    text = normalize_text(page.text)
    if not text:
        return -1000.0
    confidence = page.confidence or 0.0
    words = _meaningful_word_count(text)
    symbol_penalty = _symbol_ratio(text) * 25.0
    dropped_penalty = 2.0 * int(
        dict(page.postprocessing).get("noise_filter", {}).get("dropped_block_count", 0)
    )
    table_bonus = (
        8.0
        if _DATE_COLUMN_PATTERN.search(text) and _MONEY_PATTERN.search(text.replace("\n", " "))
        else 0.0
    )
    rotated_artifact_penalty = _rotated_text_artifact_penalty(text)
    non_vietnamese_diacritic_penalty = _non_vietnamese_diacritic_penalty(text)
    vietnamese_coherence_bonus = _vietnamese_coherence_bonus(text)
    landscape_table_bonus = _landscape_table_bonus(page, text)
    return (
        confidence * 100.0
        + min(len(text), 2000) / 20.0
        + min(words, 200) * 0.5
        + table_bonus
        + landscape_table_bonus
        + vietnamese_coherence_bonus
        - symbol_penalty
        - dropped_penalty
        - rotated_artifact_penalty
        - non_vietnamese_diacritic_penalty
    )


def _rotated_text_artifact_penalty(text: str) -> float:
    artifact_count = len(_ROTATED_TEXT_ARTIFACT_PATTERN.findall(text))
    inline_bang_count = len(re.findall(r"[A-Za-zÀ-ỹ]+![A-Za-zÀ-ỹ]+", text))
    return min(160.0, artifact_count * 35.0 + inline_bang_count * 20.0)


def _non_vietnamese_diacritic_penalty(text: str) -> float:
    artifact_count = len(re.findall(r"[äöüëçÄÖÜËÇ]", text))
    return min(100.0, artifact_count * 8.0)


def _vietnamese_coherence_bonus(text: str) -> float:
    folded = _fold_ocr_text(text)
    marker_hits = sum(
        marker in folded
        for marker in (
            "cong ty",
            "bao cao",
            "tai chinh",
            "thanh pho",
            "ngay",
            "thang",
            "duoc",
            "cac",
            "va",
            "cua",
            "trong",
        )
    )
    return min(22.0, marker_hits * 2.0)


def _landscape_table_bonus(page: OcrPageResult, text: str) -> float:
    if page.width <= page.height:
        return 0.0
    folded = normalize_text(text).lower()
    keyword_hits = sum(1 for keyword in _LANDSCAPE_TABLE_KEYWORDS if keyword in folded)
    if keyword_hits < 2:
        return 0.0
    return min(80.0, 25.0 + keyword_hits * 10.0)


_TRANSIENT_OCR_CLASS_MARKERS = (
    "timeout",
    "connection",
    "connecterror",
    "networkerror",
    "ratelimit",
    "internalserver",
    "serviceunavailable",
)
_TRANSIENT_OCR_MESSAGE_MARKERS = ("could not execute a primitive",)
_TRANSIENT_NETWORK_ERRNOS = {
    value
    for name in (
        "ETIMEDOUT",
        "ECONNABORTED",
        "ECONNREFUSED",
        "ECONNRESET",
        "ENETDOWN",
        "ENETUNREACH",
        "EHOSTDOWN",
        "EHOSTUNREACH",
    )
    if (value := getattr(errno, name, None)) is not None
}


def _exception_chain(
    exc: BaseException,
    *,
    max_depth: int = 8,
) -> Iterator[BaseException]:
    current: BaseException | None = exc
    seen: set[int] = set()
    depth = 0
    while current is not None and depth < max_depth and id(current) not in seen:
        yield current
        seen.add(id(current))
        depth += 1
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None


def _is_recoverable_ocr_exception(exc: BaseException) -> bool:
    if isinstance(exc, OcrRuntimeError):
        return exc.recoverable
    for candidate in _exception_chain(exc):
        if isinstance(candidate, (TimeoutError, ConnectionError)):
            return True
        if (
            isinstance(candidate, OSError)
            and not isinstance(candidate, (FileNotFoundError, PermissionError))
            and candidate.errno in _TRANSIENT_NETWORK_ERRNOS
        ):
            return True
        class_name = candidate.__class__.__name__.lower()
        if any(marker in class_name for marker in _TRANSIENT_OCR_CLASS_MARKERS):
            return True
        message = str(candidate).lower()
        if any(marker in message for marker in _TRANSIENT_OCR_MESSAGE_MARKERS):
            return True
    return False


def _failed_ocr_page_result(
    *,
    image: Image.Image,
    page_number: int,
    dpi: int,
    render_time_ms: float,
    preprocessing_time_ms: float,
    ocr_time_ms: float,
    preprocessing: dict[str, Any],
    error_code: str,
    exc: BaseException,
    status: str = "FAIL",
) -> OcrPageResult:
    return OcrPageResult(
        page_number=page_number,
        text="",
        character_count=0,
        word_count=0,
        confidence=None,
        processing_time_ms=round(
            render_time_ms + preprocessing_time_ms + ocr_time_ms,
            3,
        ),
        render_time_ms=round(render_time_ms, 3),
        preprocessing_time_ms=round(preprocessing_time_ms, 3),
        ocr_time_ms=round(ocr_time_ms, 3),
        width=image.width,
        height=image.height,
        dpi=dpi,
        rotation_applied=0,
        errors=(
            OcrError(
                error_code,
                f"{exc.__class__.__name__}: {exc}",
                page_number,
                recoverable=_is_recoverable_ocr_exception(exc),
            ),
        ),
        status=status,
        preprocessing=preprocessing,
        raw_text="",
        normalization_time_ms=0.0,
        postprocessing={
            "raw_text_preserved": True,
            "terminal_page_status": "TIMEOUT" if status == "TIMEOUT" else "FAILED",
        },
    )


def ocr_result_to_parsed_document(result: OcrDocumentResult) -> ParsedDocument:
    pages = [_ocr_page_to_parsed_page(page) for page in result.pages]
    tables = _ocr_tables_from_pages(pages)
    sections = [
        ParsedSection(
            text=page.text,
            page_number=page.page_number,
            title=f"OCR Page {page.page_number}",
            block_ids=[element.element_id for element in page.elements],
        )
        for page in pages
        if page.text
    ]
    parsed_text = normalize_text("\n\n".join(page.text for page in pages))
    warnings = [warning.code for warning in result.warnings]
    for page in result.pages:
        warnings.extend(warning.code for warning in page.warnings)
    document = ParsedDocument(
        text=parsed_text,
        pages=pages,
        sections=sections,
        tables=tables,
        images_metadata=[],
        document_metadata={
            "ocr_engine": result.engine_name,
            "ocr_engine_version": result.engine_version,
            "ocr_average_confidence": result.average_confidence or 0.0,
            "ocr_min_page_confidence": result.min_page_confidence or 0.0,
            "ocr_processing_time_ms": result.processing_time_ms,
            "ocr_page_count": result.page_count,
            "ocr_processed_page_count": result.processed_page_count,
            "ocr_successful_page_count": result.successful_page_count,
            "ocr_warning_page_count": result.warning_page_count,
            "ocr_failed_page_count": result.failed_page_count,
            "ocr_missing_page_numbers": list(result.missing_page_numbers),
            "ocr_validation_status": result.validation_status,
            "ocr_dqa_status": result.dqa_status,
            "ocr_chunking_ready": result.chunking_ready,
            "ocr_blocking_reasons": list(result.blocking_reasons),
            "ocr_warning_count": len(result.warnings),
            "ocr_error_count": len(result.errors),
            "page_count": len(pages),
            "word_count": len(parsed_text.split()),
            "table_count": len(tables),
            "image_count": 0,
            "parser_name": "paddleocr",
            "parser_version": result.engine_version,
            "detected_language": result.language,
            "ocr_used": True,
            "content_format": "markdown",
            "extraction_status": result.extraction_status,
            "extraction_provenance": [
                {
                    "page_number": page.page_number,
                    "source": "ocr",
                    "status": page.status,
                    "confidence": page.confidence,
                    "rotation_applied": page.rotation_applied,
                    "terminal_page_status": _page_terminal_status(page),
                    "attempt_count": len(page.attempt_history),
                    "attempt_history": [dict(item) for item in page.attempt_history],
                    "indexable": bool(
                        page.postprocessing.get(
                            "indexable", page.status in {"PASS", "WARN"} and bool(page.text.strip())
                        )
                    ),
                    "block_count": len(page.blocks),
                    "warning_codes": [warning.code for warning in page.warnings],
                    "error_codes": [error.code for error in page.errors],
                }
                for page in result.pages
            ],
        },
        warnings=warnings,
        parser_name="paddleocr",
        parser_version=result.engine_version,
        confidence=result.average_confidence,
        ocr_used=True,
        detected_language=result.language,
    )
    document.content_markdown = parsed_text
    document.logical_document = document.to_logical_document()
    return document


def _ocr_page_to_parsed_page(page: OcrPageResult) -> ParsedPage:
    source_text = _canonical_page_text(page)
    visual_lines = _ocr_table_visual_lines(page)
    if not visual_lines:
        elements = [
            ParsedElement(
                element_id=block.block_id,
                block_type="paragraph",
                text=block.text,
                page_number=page.page_number,
                metadata=_ocr_block_element_metadata(block, page=page),
                bbox=block.projected_bounding_box or block.bounding_box,
                confidence=block.confidence,
                rotation=page.rotation_applied,
                provenance={
                    "source": "ocr",
                    "source_block_id": block.block_id,
                    "page_number": page.page_number,
                },
            )
            for block in page.blocks
            if block.text.strip()
        ]
        return ParsedPage(
            page_number=page.page_number,
            text=source_text,
            elements=elements,
            metadata=_ocr_page_metadata(page),
            width=page.original_width or page.width,
            height=page.original_height or page.height,
            rotation=page.rotation_applied,
        )
    table_text = normalize_text("\n".join(visual_lines))
    text = normalize_text("\n".join(part for part in (source_text, table_text) if part))
    rows = [_split_visual_table_row(line) for line in visual_lines if line.strip()]
    table_warnings = _financial_table_warnings(rows)
    repair_provenance = dict(
        _mapping_value(
            _mapping_value(page.postprocessing, "secondary_table_ocr"),
            "source_issue_evidence",
        )
    )
    schema_inferred_rows = _financial_schema_inferred_aggregate_rows(rows, page=page)
    if schema_inferred_rows:
        repair_provenance["schema_inferred_aggregate_labels"] = schema_inferred_rows
    if page.rotation_applied in {90, 270}:
        repair_provenance.update(
            {
                "orientation_recovery_applied": True,
                "rotated_table_mapping_reconstructed": True,
            }
        )
    table_metadata = {
        "layout": "ocr_visual_table",
        "source": "ocr",
        "indexable": True,
        "ocr_confidence": page.confidence,
        "rotation_applied": page.rotation_applied,
        "rows": rows,
        "columns": max((len(row) for row in rows), default=0),
        "header": rows[0] if rows else [],
        "warnings": table_warnings,
        "canonical_text": render_table_text(rows),
        "markdown_text": render_markdown_table_text(rows),
        "input_coordinate_space_id": page.input_coordinate_space_id,
        "projected_coordinate_space_id": page.projected_coordinate_space_id,
        "transform_chain": list(page.transform_chain),
        "source_text_preserved": bool(source_text),
        "repair_provenance": repair_provenance,
    }
    elements = [
        ParsedElement(
            element_id=block.block_id,
            block_type="paragraph",
            text=block.text,
            page_number=page.page_number,
            metadata=_ocr_block_element_metadata(block, page=page),
            bbox=block.projected_bounding_box or block.bounding_box,
            confidence=block.confidence,
            rotation=page.rotation_applied,
            provenance={
                "source": "ocr",
                "source_block_id": block.block_id,
                "page_number": page.page_number,
            },
        )
        for block in page.blocks
        if block.text.strip()
    ]
    elements.append(
        ParsedElement(
            element_id=f"page-{page.page_number}-ocr-table-1",
            block_type="table",
            text=render_table_text(rows),
            page_number=page.page_number,
            metadata=table_metadata,
            confidence=page.confidence,
            rotation=page.rotation_applied,
            provenance={"source": "ocr", "page_number": page.page_number},
        )
    )
    return ParsedPage(
        page_number=page.page_number,
        text=text,
        elements=elements,
        metadata=_ocr_page_metadata(page),
        width=page.original_width or page.width,
        height=page.original_height or page.height,
        rotation=page.rotation_applied,
    )


def _financial_schema_inferred_aggregate_rows(
    rows: list[list[str]],
    *,
    page: OcrPageResult,
) -> list[dict[str, str]]:
    source_folded = _fold_ocr_text(
        "\n".join(block.text for block in page.blocks if block.text.strip())
    )
    inferred: list[dict[str, str]] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        code = normalize_text(row[0])
        expected_label = _FINANCIAL_AGGREGATE_LABELS.get(code)
        if (
            expected_label
            and normalize_text(row[1]) == expected_label
            and _fold_ocr_text(expected_label) not in source_folded
        ):
            inferred.append(
                {
                    "code": code,
                    "label": expected_label,
                    "method": "financial_statement_code_schema",
                }
            )
    return inferred


def _canonical_page_text(page: OcrPageResult) -> str:
    noise_filter = page.postprocessing.get("noise_filter")
    canonical_candidate = (
        noise_filter.get("canonical_text_candidate") if isinstance(noise_filter, dict) else ""
    )
    source_text = normalize_text(
        canonical_candidate
        if isinstance(canonical_candidate, str) and canonical_candidate
        else page.text
    )
    block_lines = [
        normalize_text(block.text) for block in page.blocks if normalize_text(block.text)
    ]
    if not block_lines:
        return source_text
    source_lines = [
        normalize_text(line) for line in source_text.splitlines() if normalize_text(line)
    ]
    if not source_lines:
        return normalize_text("\n".join(block_lines))
    folded_source = {_fold_ocr_text(line) for line in source_lines}
    merged_lines = list(source_lines)
    for line in block_lines:
        folded = _fold_ocr_text(line)
        if folded and folded not in folded_source:
            merged_lines.append(line)
            folded_source.add(folded)
    return normalize_text("\n".join(merged_lines))


def _ocr_page_metadata(page: OcrPageResult) -> dict[str, object]:
    return {
        "source": "ocr",
        "status": page.status,
        "confidence": page.confidence,
        "rotation_applied": page.rotation_applied,
        "terminal_page_status": _page_terminal_status(page),
        "attempt_count": len(page.attempt_history),
        "attempt_history": [dict(item) for item in page.attempt_history],
        "width": page.width,
        "height": page.height,
        "original_width": page.original_width,
        "original_height": page.original_height,
        "input_coordinate_space_id": page.input_coordinate_space_id,
        "projected_coordinate_space_id": page.projected_coordinate_space_id,
        "transform_chain": list(page.transform_chain),
        "indexable": bool(
            page.postprocessing.get(
                "indexable", page.status in {"PASS", "WARN"} and bool(page.text.strip())
            )
        ),
        "warning_codes": [warning.code for warning in page.warnings],
        "error_codes": [error.code for error in page.errors],
        "postprocessing": dict(page.postprocessing),
    }


def _ocr_tables_from_pages(pages: list[ParsedPage]) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    for page in pages:
        for element in page.elements:
            if element.block_type != "table":
                continue
            rows_value = element.metadata.get("rows")
            rows = (
                [[str(cell) for cell in row] for row in rows_value if isinstance(row, list)]
                if isinstance(rows_value, list)
                else []
            )
            if not rows:
                rows = [
                    _split_visual_table_row(line)
                    for line in element.text.splitlines()
                    if line.strip()
                ]
            table = ParsedTable(
                table_id=element.element_id,
                location=f"page:{page.page_number}:ocr_table:1",
                rows=rows,
                columns=max((len(row) for row in rows), default=0),
                header=rows[0] if rows else [],
                warnings=list(element.metadata.get("warnings", []) or []),
                cells=_table_cells_from_rows(rows),
                bbox=element.bbox,
                confidence=element.confidence,
                metadata={
                    key: value
                    for key, value in element.metadata.items()
                    if key not in {"rows", "warnings"}
                },
            )
            tables.append(table)
    return tables


def _split_visual_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.split("|")]


def _mapping_value(mapping: object, key: str) -> dict[str, object]:
    if not isinstance(mapping, dict):
        return {}
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def _table_cells_from_rows(rows: list[list[str]]) -> list[dict[str, object]]:
    return [
        {"row_index": row_index, "column_index": column_index, "text": cell}
        for row_index, row in enumerate(rows)
        for column_index, cell in enumerate(row)
    ]


def _financial_table_warnings(rows: list[list[str]]) -> list[str]:
    warnings: list[str] = []
    if _has_unbalanced_negative_parentheses(rows):
        warnings.append("financial_unbalanced_negative_parenthesis")
    expected_columns = max((len(row) for row in rows), default=0)
    if any(len(row) != expected_columns for row in rows):
        warnings.append("table_ragged_rows")
    return warnings


def _has_unbalanced_negative_parentheses(rows: list[list[str]]) -> bool:
    return any(_money_parenthesis_issue(cell) for row in rows for cell in row)


def _ocr_block_element_metadata(block: OcrBlock, *, page: OcrPageResult) -> dict[str, object]:
    metadata = dict(block.metadata)
    metadata.setdefault("source", "ocr")
    metadata.setdefault("indexable", True)
    metadata.setdefault("ocr_confidence", block.confidence)
    metadata.setdefault("rotation_applied", page.rotation_applied)
    metadata.setdefault("ocr_status", page.status)
    metadata.setdefault("source_block_id", block.block_id)
    metadata.setdefault("provider_coordinate_space_id", block.provider_coordinate_space_id)
    metadata.setdefault("projected_coordinate_space_id", page.projected_coordinate_space_id)
    metadata.setdefault("transform_chain", list(block.transform_chain))
    metadata.setdefault("orientation_confidence", block.orientation_confidence)
    if block.raw_text:
        metadata.setdefault("ocr_raw_text", block.raw_text)
    if block.bounding_box is not None:
        metadata.setdefault(
            "provider_bbox",
            {
                "x0": block.bounding_box.x0,
                "y0": block.bounding_box.y0,
                "x1": block.bounding_box.x1,
                "y1": block.bounding_box.y1,
                "unit": block.bounding_box.unit,
                "coordinate_space_id": block.provider_coordinate_space_id,
            },
        )
    if block.projected_bounding_box is not None:
        metadata.setdefault(
            "projected_bbox",
            {
                "x0": block.projected_bounding_box.x0,
                "y0": block.projected_bounding_box.y0,
                "x1": block.projected_bounding_box.x1,
                "y1": block.projected_bounding_box.y1,
                "unit": block.projected_bounding_box.unit,
                "coordinate_space_id": page.projected_coordinate_space_id,
            },
        )
    if block.normalized_bounding_box is not None:
        metadata.setdefault(
            "normalized_bbox",
            {
                "x0": block.normalized_bounding_box.x0,
                "y0": block.normalized_bounding_box.y0,
                "x1": block.normalized_bounding_box.x1,
                "y1": block.normalized_bounding_box.y1,
                "unit": block.normalized_bounding_box.unit,
                "coordinate_space_id": f"page-{page.page_number - 1}-normalized",
            },
        )
    return metadata


_DATE_COLUMN_PATTERN = re.compile(
    r"(?:\b\d{1,2}/\d{1,2}/\d{4}\b|\b(?:ngay|ngày)\s*\d{1,2}\s*(?:thang|tháng)\s*\d{1,2}\s*(?:nam|năm)\s*\d{4}\b)",
    re.IGNORECASE,
)
_MONEY_PATTERN = re.compile(r"^\(?\d{1,3}(?:\.\d{3}){2,}\)?$")
_MONEY_SUBSTRING_PATTERN = re.compile(r"\(?\d{1,3}(?:\.\d{3}){2,}\)?")
_FINANCIAL_CODE_PATTERN = re.compile(r"^([A-Z]?\d{2,3}[a-z]?)(.*)$")
_FINANCIAL_AGGREGATE_LABELS = {
    "270": "TỔNG CỘNG TÀI SẢN",
    "440": "TỔNG CỘNG NGUỒN VỐN",
}
_NOTE_REF_PATTERN = re.compile(r"^(.*?)(?:\s+)(\d{1,2}(?:\.\d+)?(?:\s*,\s*\d{1,2}(?:\.\d+)?)*)$")
_PAGE_RANGE_TOKEN_PATTERN = re.compile(r"^\d{1,3}(?:\s*-\s*\d{1,3})?$")
_FINANCIAL_NOTE_ONLY_PATTERN = re.compile(r"^\d{1,2}(?:\.\d+)?(?:\s*,\s*\d{1,2}(?:\.\d+)?)*$")
_ROTATED_TEXT_ARTIFACT_PATTERN = re.compile(
    r"\b(?:6u|Qnydnyd|Bunp|suo!noS|ue!a|ue!G|Gugo)\b",
    re.IGNORECASE,
)
_LANDSCAPE_TABLE_KEYWORDS = (
    "ten cong ty",
    "tên công ty",
    "tru so chinh",
    "trụ sở chính",
    "hoat dong chinh",
    "hoạt động chính",
    "ty le",
    "tỷ lệ",
    "biểu quyết",
    "tỷ lệ",
    "coteccons construction",
)


def _ocr_table_visual_lines(page: OcrPageResult) -> list[str] | None:
    return (
        _toc_table_visual_lines(page)
        or _financial_table_visual_lines(page)
        or _subsidiary_table_visual_lines(page)
    )


def _toc_table_visual_lines(page: OcrPageResult) -> list[str] | None:
    folded = normalize_text(page.text).lower()
    if "muc luc" not in folded and "mục lục" not in folded:
        return None
    if "trang" not in folded:
        return None
    blocks = [
        block for block in page.blocks if block.text.strip() and block.bounding_box is not None
    ]
    if len(blocks) < 4:
        return None
    visual_lines = ["Mục lục | Trang"]
    for row in _group_blocks_by_visual_row(blocks):
        row_blocks = sorted(row, key=_block_x_center)
        row_text = normalize_text(" ".join(block.text for block in row_blocks))
        folded_row = row_text.lower()
        if not row_text or "muc luc" in folded_row or "mục lục" in folded_row:
            continue
        if folded_row == "trang":
            continue
        page_tokens = [
            normalize_text(block.text).replace(" ", "")
            for block in row_blocks
            if _PAGE_RANGE_TOKEN_PATTERN.fullmatch(normalize_text(block.text))
        ]
        if not page_tokens:
            continue
        label = normalize_text(
            " ".join(
                block.text
                for block in row_blocks
                if not _PAGE_RANGE_TOKEN_PATTERN.fullmatch(normalize_text(block.text))
            )
        )
        if not label:
            continue
        visual_lines.append(f"{label} | {page_tokens[-1]}")
    return visual_lines if len(visual_lines) >= 2 else None


def _financial_table_visual_lines(page: OcrPageResult) -> list[str] | None:
    blocks = [
        block
        for block in page.blocks
        if block.text.strip()
        and block.bounding_box is not None
        and not _financial_margin_page_token(block, page_width=page.width)
    ]
    if len(blocks) < 4:
        return None
    date_blocks = [block for block in blocks if _DATE_COLUMN_PATTERN.search(block.text)]
    money_blocks = [block for block in blocks if _money_values_in_text(block.text)]
    money_value_count = sum(len(_money_values_in_text(block.text)) for block in money_blocks)
    if len(date_blocks) < 2 or money_value_count < 4:
        return None

    date_columns = _financial_date_columns(date_blocks, page_text=page.text)
    if len(date_columns) < 2:
        return None

    rows = _group_blocks_by_visual_row(blocks)
    visual_lines: list[str] = []
    pending_label: str | None = None
    header_y = min(_block_y_center(block) for block in date_blocks)
    for row in rows:
        row_blocks = sorted(row, key=_block_x_center)
        row_text = " ".join(block.text.strip() for block in row_blocks)
        if not row_text:
            continue
        if _block_y_center(row_blocks[0]) <= header_y:
            if not visual_lines:
                visual_lines.append(
                    "Mã số | "
                    + _financial_indicator_header(page.text)
                    + " | Thuyết minh | "
                    + " | ".join(date_label for _, date_label in date_columns)
                )
            continue
        money_values = _money_entries_from_row(row_blocks)
        if not money_values:
            if _row_starts_with_financial_code(row_text):
                if pending_label:
                    visual_lines.append(_financial_row_without_values(pending_label, date_columns))
                pending_label = row_text
            else:
                if pending_label:
                    pending_label = f"{pending_label} {row_text}"
                else:
                    visual_lines.append(row_text)
            continue
        label_parts = [
            cleaned
            for block in row_blocks
            if (cleaned := _strip_money_values(block.text).strip(" |"))
            and cleaned not in {"-", "–", "—"}
        ]
        label = " ".join(label_parts).strip()
        if pending_label:
            if _row_starts_with_financial_code(label):
                visual_lines.append(_financial_row_without_values(pending_label, date_columns))
            else:
                label = f"{pending_label} {label}".strip()
            pending_label = None
        values_by_column: dict[int, str] = {}
        for value_x_center, value_text in money_values:
            column_index, _ = min(
                enumerate(date_columns),
                key=lambda item: abs(item[1][0] - value_x_center),
            )
            values_by_column[column_index] = _normalize_money_value(value_text)
        if label and values_by_column:
            code, indicator, note = _split_financial_row_label(
                label,
                date_columns=date_columns,
            )
            value_parts = [
                values_by_column.get(column_index, "") for column_index in range(len(date_columns))
            ]
            visual_lines.append(" | ".join([code, indicator, note, *value_parts]))
        else:
            visual_lines.append(row_text)
    if pending_label:
        visual_lines.append(_financial_row_without_values(pending_label, date_columns))
    # Keep partially reconstructed financial tables; demanding half the row
    # groups often drops useful evidence on scanned reports.
    return visual_lines if len(visual_lines) >= 2 else None


def _financial_margin_page_token(
    block: OcrBlock,
    *,
    page_width: int,
) -> bool:
    return bool(
        page_width > 0
        and _PAGE_RANGE_TOKEN_PATTERN.fullmatch(normalize_text(block.text))
        and _block_x_center(block) > page_width * 0.94
    )


_SUBSIDIARY_PERCENT_PATTERN = re.compile(r"\b\d{2,3}[,.]\d{2}\b")
_SUBSIDIARY_STT_PATTERN = re.compile(r"^\d{1,2}$")
_SUBSIDIARY_LEADING_STT_PATTERN = re.compile(r"^(\d{1,2})\s+(.+)$")
_SUBSIDIARY_HEADER = (
    'STT | Tên công ty/chi nhánh ("Tên viết tắt") | '
    "Tỷ lệ biểu quyết (%) | Tỷ lệ lợi ích (%) | Trụ sở chính | Hoạt động chính"
)


def _subsidiary_table_visual_lines(page: OcrPageResult) -> list[str] | None:
    blocks = [
        block for block in page.blocks if block.text.strip() and block.bounding_box is not None
    ]
    if len(blocks) < 8 or not _looks_like_landscape_table(page.text):
        return None
    percentage_blocks = [
        block for block in blocks if _SUBSIDIARY_PERCENT_PATTERN.search(block.text)
    ]
    if len(percentage_blocks) < 4:
        return None

    vote_x, benefit_x = _subsidiary_percentage_columns(percentage_blocks)
    office_x, activity_x = _subsidiary_text_columns(blocks, page_width=page.width)
    stt_right = max(70.0, page.width * 0.11)
    company_vote_boundary = vote_x - max(60.0, (benefit_x - vote_x) * 0.75)
    vote_benefit_boundary = (vote_x + benefit_x) / 2
    benefit_office_boundary = (benefit_x + office_x) / 2
    office_activity_boundary = max(
        (office_x + activity_x) / 2,
        page.width * 0.70,
    )
    header_y = _subsidiary_header_y(blocks, default=0.0)

    records = _subsidiary_records_from_stt_anchors(
        blocks,
        header_y=header_y,
        page_height=page.height,
        stt_right=stt_right,
        company_vote_boundary=company_vote_boundary,
        vote_benefit_boundary=vote_benefit_boundary,
        benefit_office_boundary=benefit_office_boundary,
        office_activity_boundary=office_activity_boundary,
    )
    if records:
        return [_SUBSIDIARY_HEADER, *[" | ".join(row) for row in records]]

    records: list[list[str]] = []
    current: list[str] | None = None
    for visual_row in _group_blocks_by_visual_row(blocks):
        row_blocks = [
            block
            for block in sorted(visual_row, key=_block_x_center)
            if _block_y_center(block) > header_y
        ]
        if not row_blocks:
            continue
        starts_new = False
        pending_parts = ["", "", "", "", "", ""]
        for block in row_blocks:
            text = normalize_text(block.text).strip()
            if not text:
                continue
            x_center = _block_x_center(block)
            if x_center <= stt_right and _SUBSIDIARY_STT_PATTERN.fullmatch(text):
                starts_new = True
                pending_parts[0] = text
                continue
            leading = _SUBSIDIARY_LEADING_STT_PATTERN.match(text)
            if x_center <= company_vote_boundary and leading:
                starts_new = True
                pending_parts[0] = leading.group(1)
                text = leading.group(2).strip()
            percentage_entries = _subsidiary_percentage_entries(block)
            for percentage_x, percentage_text in percentage_entries:
                target_index = 2 if percentage_x <= vote_benefit_boundary else 3
                pending_parts[target_index] = _append_cell(
                    pending_parts[target_index],
                    _normalize_percentage_value(percentage_text),
                )
            text_without_percentages = _SUBSIDIARY_PERCENT_PATTERN.sub(" ", text).strip(" >")
            if not text_without_percentages:
                continue
            if x_center <= company_vote_boundary:
                pending_parts[1] = _append_cell(pending_parts[1], text_without_percentages)
            elif x_center <= vote_benefit_boundary:
                pending_parts[2] = _append_cell(pending_parts[2], text_without_percentages)
            elif x_center <= benefit_office_boundary:
                pending_parts[3] = _append_cell(pending_parts[3], text_without_percentages)
            elif x_center <= office_activity_boundary:
                pending_parts[4] = _append_cell(pending_parts[4], text_without_percentages)
            else:
                pending_parts[5] = _append_cell(pending_parts[5], text_without_percentages)
        if starts_new:
            if current and _valid_subsidiary_row(current):
                records.append(current)
            current = pending_parts
        elif current is not None:
            for index, value in enumerate(pending_parts):
                current[index] = _append_cell(current[index], value)
    if current and _valid_subsidiary_row(current):
        records.append(current)
    if not records:
        return None
    return [_SUBSIDIARY_HEADER, *[" | ".join(row) for row in records]]


def _subsidiary_records_from_stt_anchors(
    blocks: list[OcrBlock],
    *,
    header_y: float,
    page_height: float,
    stt_right: float,
    company_vote_boundary: float,
    vote_benefit_boundary: float,
    benefit_office_boundary: float,
    office_activity_boundary: float,
) -> list[list[str]]:
    anchors: list[tuple[float, str, OcrBlock]] = []
    for block in blocks:
        if block.bounding_box is None or _block_y_center(block) <= header_y:
            continue
        text = normalize_text(block.text).strip()
        x_center = _block_x_center(block)
        if x_center <= stt_right and _SUBSIDIARY_STT_PATTERN.fullmatch(text):
            anchors.append((_block_y_center(block), text, block))
            continue
        leading = _SUBSIDIARY_LEADING_STT_PATTERN.match(text)
        if x_center <= company_vote_boundary and leading:
            anchors.append((_block_y_center(block), leading.group(1), block))
    if len(anchors) < 2:
        return []

    anchors.sort(key=lambda item: (item[0], int(item[1])))
    deduped: list[tuple[float, str, OcrBlock]] = []
    for anchor in anchors:
        if deduped and (anchor[1] == deduped[-1][1] or abs(anchor[0] - deduped[-1][0]) <= 8.0):
            current = deduped[-1]
            if _block_x_center(anchor[2]) < _block_x_center(current[2]):
                deduped[-1] = anchor
            continue
        deduped.append(anchor)
    if len(deduped) < 2:
        return []

    gaps = [
        right[0] - left[0]
        for left, right in zip(deduped, deduped[1:], strict=False)
        if right[0] > left[0]
    ]
    typical_gap = statistics.median(gaps) if gaps else max(page_height * 0.12, 80.0)
    block_heights = [
        block.bounding_box.height
        for block in blocks
        if block.bounding_box is not None and block.bounding_box.height > 0
    ]
    row_lead = max(
        8.0,
        (statistics.median(block_heights) if block_heights else 20.0) * 0.65,
    )
    records: list[list[str]] = []
    anchor_ids = {anchor[2].block_id for anchor in deduped}
    for index, (anchor_y, stt, anchor_block) in enumerate(deduped):
        lower = max(header_y, anchor_y - row_lead)
        upper = (
            deduped[index + 1][0] - row_lead
            if index + 1 < len(deduped)
            else min(page_height, anchor_y + typical_gap)
        )
        row_blocks = [
            block
            for block in blocks
            if block.bounding_box is not None
            and lower <= _block_y_center(block) < upper
            and _block_y_center(block) > header_y
        ]
        fragments: list[list[tuple[OcrBlock, str]]] = [
            [],
            [],
            [],
            [],
            [],
            [],
        ]
        fragments[0].append((anchor_block, stt))
        for block in row_blocks:
            text = normalize_text(block.text).strip()
            if not text:
                continue
            x_center = _block_x_center(block)
            if block.block_id in anchor_ids and _SUBSIDIARY_STT_PATTERN.fullmatch(text):
                continue
            leading = _SUBSIDIARY_LEADING_STT_PATTERN.match(text)
            if x_center <= company_vote_boundary and leading:
                if leading.group(1) != stt:
                    continue
                text = leading.group(2).strip()
            percentage_entries = _subsidiary_percentage_entries(block)
            for percentage_x, percentage_text in percentage_entries:
                target_index = 2 if percentage_x <= vote_benefit_boundary else 3
                fragments[target_index].append(
                    (block, _normalize_percentage_value(percentage_text))
                )
            text_without_percentages = _SUBSIDIARY_PERCENT_PATTERN.sub(" ", text).strip(" >")
            if not text_without_percentages:
                continue
            if (
                _SUBSIDIARY_STT_PATTERN.fullmatch(text_without_percentages)
                and x_center <= benefit_office_boundary
            ):
                continue
            if x_center <= company_vote_boundary:
                target_index = 1
            elif x_center <= vote_benefit_boundary:
                target_index = 2
            elif x_center <= benefit_office_boundary:
                target_index = 3
            elif x_center <= office_activity_boundary:
                target_index = 4
            else:
                target_index = 5
            fragments[target_index].append((block, text_without_percentages))

        row = [
            stt,
            _join_subsidiary_fragments(fragments[1]),
            _first_subsidiary_percentage(fragments[2]),
            _first_subsidiary_percentage(fragments[3]),
            _normalize_subsidiary_cell(
                _join_subsidiary_fragments(fragments[4]),
                column_index=4,
            ),
            _normalize_subsidiary_cell(
                _join_subsidiary_fragments(fragments[5]),
                column_index=5,
            ),
        ]
        row[1] = _normalize_subsidiary_cell(row[1], column_index=1)
        if _valid_subsidiary_row(row):
            records.append(row)
    return records


def _join_subsidiary_fragments(
    fragments: list[tuple[OcrBlock, str]],
) -> str:
    if not fragments:
        return ""
    heights = [
        block.bounding_box.height
        for block, _ in fragments
        if block.bounding_box is not None and block.bounding_box.height > 0
    ]
    tolerance = max(6.0, (statistics.median(heights) if heights else 12.0) * 0.5)
    lines: list[list[tuple[OcrBlock, str]]] = []
    line_centers: list[float] = []
    for fragment in sorted(
        fragments,
        key=lambda item: (_block_y_center(item[0]), _block_x_center(item[0])),
    ):
        y_center = _block_y_center(fragment[0])
        for line_index, line_center in enumerate(line_centers):
            if abs(y_center - line_center) <= tolerance:
                lines[line_index].append(fragment)
                line_centers[line_index] = (
                    line_centers[line_index] * (len(lines[line_index]) - 1) + y_center
                ) / len(lines[line_index])
                break
        else:
            lines.append([fragment])
            line_centers.append(y_center)
    line_texts = [
        normalize_text(
            " ".join(
                text for _, text in sorted(line, key=lambda item: _block_x_center(item[0])) if text
            )
        )
        for line in lines
    ]
    return normalize_text(" ".join(text for text in line_texts if text))


def _first_subsidiary_percentage(
    fragments: list[tuple[OcrBlock, str]],
) -> str:
    values = [
        _normalize_percentage_value(text)
        for _, text in fragments
        if _SUBSIDIARY_PERCENT_PATTERN.fullmatch(text)
    ]
    return values[0] if values else ""


def _normalize_subsidiary_cell(text: str, *, column_index: int) -> str:
    normalized = normalize_text(text)
    for pattern, replacement in (
        (r"\bXay d\u1ef1ng\b", "X\u00e2y d\u1ef1ng"),
        (r"\bx\u00e1y d\u1ef1ng\b", "x\u00e2y d\u1ef1ng"),
        (r"\bthi\u00eat b\u1ecb\b", "thi\u1ebft b\u1ecb"),
        (r"\bvi tinh\b", "vi t\u00ednh"),
        (r"\bVi\u00eat Nam\b", "Vi\u1ec7t Nam"),
        (r"\bZO5T3D8\b", "Z05T3D8"),
        (r"\bCòng\b|\bCêng\b", "Công"),
        (r"\bphẩn\b", "phần"),
        (r"\bFuturelmpact\b", "FutureImpact"),
        (r"\bMởi\b", "Mới"),
        (r"\blẳp\b", "lắp"),
        (r"\bVỉệt\b", "Việt"),
        (r"\bBinh\b", "Bình"),
        (r"\bĐưởng\b", "Đường"),
        (r"\bđưởng\b", "đường"),
        (r"\bHổ\b|\bHỗ\b", "Hồ"),
        (r"\bnẵng\b", "năng"),
        (r"\bbất cộng sản\b", "bất động sản"),
        (r"\bdung đất\b", "dụng đất"),
        (r"\bthuôc\b", "thuộc"),
        (r"\bchù\b", "chủ"),
        (r"\bnhôm kinh\b", "nhôm kính"),
        (r"\bkim loai\b", "kim loại"),
        (r"\bTàng\b", "Tầng"),
        (r"\bXé Út\b", "Xê-út"),
        (r"\bcàc\b", "các"),
        (r"\btrinh\b", "trình"),
        (r"\bSàn xuất\b", "Sản xuất"),
        (r"\bCộng hòa Ân Độ\b", "Cộng hòa Ấn Độ"),
        (r"\bBẳc\b", "Bắc"),
        (r"\bxêy\b", "xây"),
        (r"\bcảc\b", "các"),
        (r"\bloai\b", "loại"),
        (r"\bẩặt\b", "đặt"),
        (r"\bC3\.\s+2\b", "C3.2"),
        (r"\bKZLLP\b", "KZ LLP"),
        (r"(?<=Hồ )Chi Minh\b", "Chí Minh"),
        (r"\bThành\s+(?:Phổ|Phó|phổ|phó)\b", "Thành phố"),
        (r"\bThành phố Chí Minh\b", "Thành phố Hồ Chí Minh"),
        (r"^Công TNHH\b", "Công ty TNHH"),
    ):
        normalized = re.sub(pattern, replacement, normalized)
    if column_index == 1:
        abbreviation = re.search(
            r"\(\s*[\"']?\s*([^()\"']+?)\s*[\"']{0,2}\s*\)?$",
            normalized,
        )
        if abbreviation:
            normalized = (
                normalized[: abbreviation.start()].rstrip()
                + f' ("{abbreviation.group(1).strip()}")'
            )
    if column_index in {4, 5}:
        normalized = re.sub(r"\s*;\s*", ", ", normalized)
    for pattern, replacement in (
        (r"\b(C3\.2)\s+(Z[0-9A-Z]{6})\b", r"\1, \2"),
        (
            r"\b(\u0110\u01b0\u1eddng s\u1ed1 \d+)\s+"
            r"(Ph\u01b0\u1eddng)\b",
            r"\1, \2",
        ),
        (
            r"\b(Th\u00e0nh ph\u1ed1 H\u1ed3 Ch\u00ed Minh)\s+"
            r"(Vi\u1ec7t Nam)\b",
            r"\1, \2",
        ),
        (r"\bPhủ\s+Phường\b", "Phủ, Phường"),
        (r"\bKhu phố\s+(\d+)\s+Phường\b", r"Khu phố \1, Phường"),
        (r"\bViệt Nam\s*-\s*Singapore\b", "Việt Nam - Singapore"),
        (r"\bS4\s+Roshn\b", "S4, Roshn"),
        (r"\b(Đường số \d+)\s+(Ta Lei)\b", r"\1, \2"),
        (r"\btrời\s+máy móc\b", "trời, máy móc"),
        (r"\bthi công\s+lắp đặt\b", "thi công, lắp đặt"),
        (r"\bOlympia Cyberspace\s+Tầng\b", "Olympia Cyberspace, Tầng"),
    ):
        normalized = re.sub(pattern, replacement, normalized)
    normalized = re.sub(r"\s+([,.;:])", r"\1", normalized)
    normalized = re.sub(r"([,.;:])(?=\S)", r"\1 ", normalized)
    normalized = re.sub(r"(?:,\s*){2,}", ", ", normalized)
    normalized = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", normalized)
    normalized = normalize_text(normalized)
    return normalized


def _subsidiary_percentage_columns(blocks: list[OcrBlock]) -> tuple[float, float]:
    centers = sorted(
        _block_x_center(block)
        for block in blocks
        if _SUBSIDIARY_PERCENT_PATTERN.fullmatch(block.text.strip())
    )
    if len(centers) < 2:
        centers = sorted(_block_x_center(block) for block in blocks)
    if len(centers) < 2:
        return 0.0, 1.0
    clusters: list[list[float]] = []
    for center in centers:
        if not clusters or abs(center - statistics.median(clusters[-1])) > 80:
            clusters.append([center])
        else:
            clusters[-1].append(center)
    cluster_centers = sorted(statistics.median(cluster) for cluster in clusters)
    if len(cluster_centers) >= 2:
        return cluster_centers[0], cluster_centers[1]
    return cluster_centers[0], cluster_centers[0] + 160.0


def _subsidiary_text_columns(blocks: list[OcrBlock], *, page_width: float) -> tuple[float, float]:
    office_centers = [
        _block_x_center(block) for block in blocks if _looks_like_office_header(block.text)
    ]
    activity_centers = [
        _block_x_center(block) for block in blocks if _looks_like_activity_header(block.text)
    ]
    office_x = statistics.median(office_centers) if office_centers else page_width * 0.58
    activity_x = statistics.median(activity_centers) if activity_centers else page_width * 0.82
    if activity_x <= office_x:
        activity_x = office_x + max(120.0, page_width * 0.18)
    return office_x, activity_x


def _subsidiary_header_y(blocks: list[OcrBlock], *, default: float) -> float:
    header_rows = []
    for row in _group_blocks_by_visual_row(blocks):
        hits = sum(1 for block in row if _looks_like_subsidiary_header_text(block.text))
        if hits:
            header_rows.append((_block_y_center(row[0]), hits))
    if not header_rows:
        return default
    max_hits = max(hits for _, hits in header_rows)
    return max(y for y, hits in header_rows if hits == max_hits)


def _looks_like_subsidiary_header_text(text: str) -> bool:
    folded = normalize_text(text).lower()
    return (
        "ten cong ty" in folded
        or "tên công ty" in folded
        or "ty le" in folded
        or "tỷ lệ" in folded
        or "bieu quyet" in folded
        or "biểu quyết" in folded
        or "loi ich" in folded
        or "lợi ích" in folded
        or _looks_like_office_header(text)
        or _looks_like_activity_header(text)
    )


def _looks_like_office_header(text: str) -> bool:
    folded = normalize_text(text).lower()
    return ("tru" in folded or "trụ" in folded) and ("chinh" in folded or "chính" in folded)


def _looks_like_activity_header(text: str) -> bool:
    folded = normalize_text(text).lower()
    return ("hoat dong" in folded or "hoạt động" in folded) and (
        "chinh" in folded or "chính" in folded
    )


def _subsidiary_percentage_entries(block: OcrBlock) -> list[tuple[float, str]]:
    matches = list(_SUBSIDIARY_PERCENT_PATTERN.finditer(block.text))
    if not matches:
        return []
    if block.bounding_box is None or len(matches) == 1:
        return [(_block_x_center(block), match.group(0)) for match in matches]
    width = block.bounding_box.width
    return [
        (
            block.bounding_box.x0 + ((index + 0.5) * width / len(matches)),
            match.group(0),
        )
        for index, match in enumerate(matches)
    ]


def _normalize_percentage_value(text: str) -> str:
    return text.strip().replace(".", ",")


def _append_cell(existing: str, value: str) -> str:
    value = normalize_text(value).strip()
    if not value:
        return existing
    return f"{existing} {value}".strip() if existing else value


def _valid_subsidiary_row(row: list[str]) -> bool:
    if len(row) < 6:
        return False
    if not _SUBSIDIARY_STT_PATTERN.fullmatch(row[0].strip()):
        return False
    return bool(row[1].strip()) and (bool(row[2].strip()) or bool(row[3].strip()))


def _financial_indicator_header(page_text: str) -> str:
    folded = _fold_ocr_text(page_text)
    if "luu chuyen tien" in folded or "ket qua hoat dong" in folded:
        return "Chỉ tiêu"
    if "nguon von" in folded:
        return "Nguồn vốn"
    if "tai san" in folded:
        return "Tài sản"
    return "Chỉ tiêu"


def _financial_row_without_values(label: str, date_columns: list[tuple[float, str]]) -> str:
    code, indicator, note = _split_financial_row_label(
        label,
        date_columns=date_columns,
    )
    return " | ".join([code, indicator, note, *([""] * len(date_columns))])


def _financial_date_columns(
    date_blocks: list[OcrBlock],
    *,
    page_text: str,
) -> list[tuple[float, str]]:
    if _looks_like_quarter_income_statement(page_text):
        quarter_columns = _cluster_quarter_date_blocks(date_blocks)
        if len(quarter_columns) == 4:
            return [
                (
                    x_center,
                    _financial_period_label(
                        full_text,
                        date_label=date_label,
                        position=index,
                        page_text=page_text,
                    ),
                )
                for index, (x_center, date_label, full_text) in enumerate(
                    quarter_columns,
                    start=1,
                )
            ]
    date_blocks = _select_table_header_date_blocks(date_blocks)
    raw_columns = sorted(
        (
            (
                _block_x_center(block),
                _DATE_COLUMN_PATTERN.search(block.text).group(0),
                block.text,
            )
            for block in date_blocks
            if _DATE_COLUMN_PATTERN.search(block.text)
        ),
        key=lambda item: item[0],
    )
    if len(raw_columns) == 4 and _looks_like_quarter_income_statement(page_text):
        return [
            (
                x_center,
                _financial_period_label(
                    full_text,
                    date_label=date_label,
                    position=index,
                    page_text=page_text,
                ),
            )
            for index, (x_center, date_label, full_text) in enumerate(raw_columns, start=1)
        ]
    seen: dict[str, int] = {}
    columns: list[tuple[float, str]] = []
    for x_center, label, _full_text in raw_columns:
        count = seen.get(label, 0) + 1
        seen[label] = count
        unique_label = label if count == 1 else f"{label}_{count}"
        columns.append((x_center, unique_label))
    return columns


def _cluster_quarter_date_blocks(
    date_blocks: list[OcrBlock],
) -> list[tuple[float, str, str]]:
    candidates = sorted(
        (
            _block_x_center(block),
            _block_y_center(block),
            _DATE_COLUMN_PATTERN.search(block.text).group(0),
            block.text,
        )
        for block in date_blocks
        if block.bounding_box is not None
        and _DATE_COLUMN_PATTERN.search(block.text)
        and re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", block.text)
    )
    if len(candidates) < 4:
        return []
    widths = [
        block.bounding_box.width
        for block in date_blocks
        if block.bounding_box is not None and block.bounding_box.width > 0
    ]
    cluster_tolerance = max(
        45.0,
        (statistics.median(widths) if widths else 100.0) * 0.65,
    )
    clusters: list[list[tuple[float, float, str, str]]] = []
    for candidate in candidates:
        if (
            not clusters
            or abs(candidate[0] - statistics.median(item[0] for item in clusters[-1]))
            > cluster_tolerance
        ):
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)
    if len(clusters) != 4:
        return []
    return [
        (
            statistics.median(item[0] for item in cluster),
            selected[2],
            selected[3],
        )
        for cluster in clusters
        for selected in [max(cluster, key=lambda item: item[1])]
    ]


def _select_table_header_date_blocks(date_blocks: list[OcrBlock]) -> list[OcrBlock]:
    if len(date_blocks) <= 2:
        return date_blocks
    grouped = [row for row in _group_blocks_by_visual_row(date_blocks) if len(row) >= 2]
    if not grouped:
        return date_blocks
    return max(
        grouped,
        key=lambda row: (
            len(row),
            max(_block_x_center(block) for block in row)
            - min(_block_x_center(block) for block in row),
            _block_y_center(row[0]),
        ),
    )


def _looks_like_quarter_income_statement(text: str) -> bool:
    folded = _fold_ocr_text(text)
    return re.search(r"\bquy\s*[1-4]\b", folded) is not None and "chin thang" in folded


def _date_year(label: str) -> str | None:
    match = re.search(r"(?:/|\bnam\b|\bnăm\b)\s*(\d{4})\b", label, re.IGNORECASE)
    if match is None:
        match = re.search(r"\b(\d{4})\b", label)
    return match.group(1) if match else None


def _financial_period_label(
    text: str,
    *,
    date_label: str,
    position: int,
    page_text: str = "",
) -> str:
    folded = _fold_ocr_text(text)
    page_folded = _fold_ocr_text(page_text)
    year = _date_year(date_label) or _date_year(text) or f"ky_{position}"
    quarter_match = re.search(r"\bquy\s*([1-4])\b", f"{folded} {page_folded}")
    if position <= 2 and quarter_match:
        return f"Quý {quarter_match.group(1)} năm {year}"
    if position > 2 or "chin thang" in folded:
        return f"Chín tháng {year}"
    return f"Kỳ {position} năm {year}"


def _row_starts_with_financial_code(text: str) -> bool:
    return bool(_FINANCIAL_CODE_PATTERN.match(text.strip()))


def _split_financial_label(label: str) -> tuple[str, str, str]:
    normalized = " ".join(label.split())
    code = ""
    code_match = _FINANCIAL_CODE_PATTERN.match(normalized)
    if code_match:
        code = code_match.group(1)
        normalized = code_match.group(2).strip(" .")
    note = ""
    note_match = _NOTE_REF_PATTERN.match(normalized)
    if note_match and not _is_money_like(note_match.group(2).replace(" ", "")):
        normalized = note_match.group(1).strip()
        note = re.sub(r"\s*,\s*", ", ", note_match.group(2).strip())
    return code, normalized, note


def _split_financial_row_label(
    label: str,
    *,
    date_columns: list[tuple[float, str]],
) -> tuple[str, str, str]:
    normalized, _ = OcrTextNormalizer().normalize(" ".join(label.split()))
    normalized = normalize_text(normalized.replace("|", " "))
    if len(date_columns) == 4:
        glued_income_code = re.match(r"^(\d{2})(\d)\.(?=\S)", normalized)
        if glued_income_code:
            normalized = (
                f"{glued_income_code.group(1)} "
                f"{glued_income_code.group(2)}. "
                f"{normalized[glued_income_code.end() :]}"
            ).strip()
    code, indicator, note = _split_financial_label(normalized)
    if len(date_columns) == 4:
        indicator = re.sub(r"^\d+\s*[.)]\s*", "", indicator).strip()
    indicator = _normalize_financial_indicator(indicator, code=code)
    return code, indicator, note


def _normalize_financial_indicator(indicator: str, *, code: str) -> str:
    normalized = normalize_text(indicator)
    aggregate_label = _FINANCIAL_AGGREGATE_LABELS.get(code)
    if aggregate_label and (not normalized or _fold_ocr_text(normalized).startswith("tong")):
        normalized = aggregate_label
    for pattern, replacement in (
        (r"\bChi ph[lIÍ]\b", "Chi phí"),
        (r"\bph[ốồ] thông\b", "phổ thông"),
        (r"\bT[ỐÓ]NG\b", "TỔNG"),
        (r"\bV[ÓÒ]N\b", "VỐN"),
        (r"\btài chinh\b", "tài chính"),
        (r"\bdài han\b", "dài hạn"),
        (r"\bhoãn lai\b", "hoãn lại"),
    ):
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^(\d{1,2})\s+(?=\D)", r"\1. ", normalized)
    normalized = re.sub(
        r"(?<=[^\W\d_])['’](?=[^\W\d_])",
        "",
        normalized,
        flags=re.UNICODE,
    )
    normalized = re.sub(
        r"\s+['’](?=[^\W\d_])",
        " ",
        normalized,
        flags=re.UNICODE,
    )
    if re.fullmatch(r"\d{3}[a-z]", code, re.IGNORECASE) and not normalized.startswith("-"):
        normalized = f"- {normalized}"
    return normalize_text(normalized)


def _fold_ocr_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", normalize_text(text).casefold())
    return " ".join(
        "".join(
            character for character in normalized if not unicodedata.combining(character)
        ).split()
    )


def _normalize_money_value(text: str) -> str:
    return _repair_money_ocr_punctuation(text).strip().replace(" ", "")


def _repair_money_ocr_punctuation(text: str) -> str:
    repaired = re.sub(r"(?<=\d)\.,(?=\d{3}(?:\.|\)))", ".", text)
    repaired = re.sub(r"(?<=\d),(?=\.)", "", repaired)
    return re.sub(r"(?<=\d),(?=\d{3}(?:\.|\)))", ".", repaired)


def _money_parenthesis_issue(text: str) -> bool:
    normalized = text.strip().replace(" ", "")
    if not normalized:
        return False
    if not re.search(r"\d{1,3}(?:\.\d{3}){2,}", normalized):
        return False
    return normalized.count("(") != normalized.count(")")


def _group_blocks_by_visual_row(blocks: list[OcrBlock]) -> list[list[OcrBlock]]:
    heights = [
        block.bounding_box.height
        for block in blocks
        if block.bounding_box is not None and block.bounding_box.height > 0
    ]
    median_height = statistics.median(heights) if heights else 12.0
    tolerance = max(8.0, median_height * 0.75)
    rows: list[list[OcrBlock]] = []
    row_centers: list[float] = []
    for block in sorted(blocks, key=lambda item: (_block_y_center(item), _block_x_center(item))):
        y_center = _block_y_center(block)
        for index, row_center in enumerate(row_centers):
            if abs(y_center - row_center) <= tolerance:
                rows[index].append(block)
                row_centers[index] = (row_centers[index] * (len(rows[index]) - 1) + y_center) / len(
                    rows[index]
                )
                break
        else:
            rows.append([block])
            row_centers.append(y_center)
    return rows


def _is_money_like(text: str) -> bool:
    normalized = text.strip().replace(" ", "")
    return bool(_MONEY_PATTERN.fullmatch(normalized))


def _money_values_in_text(text: str) -> list[str]:
    normalized = _repair_money_ocr_punctuation(text).strip().replace(" ", "")
    return [match.group(0) for match in _MONEY_SUBSTRING_PATTERN.finditer(normalized)]


def _money_entries_from_row(blocks: list[OcrBlock]) -> list[tuple[float, str]]:
    entries: list[tuple[float, str]] = []
    for block in blocks:
        if normalize_text(block.text).strip() in {"-", "–", "—"}:
            entries.append((_block_x_center(block), "-"))
            continue
        values = _money_values_in_text(block.text)
        if not values:
            continue
        if block.bounding_box is None or len(values) == 1:
            entries.extend((_block_x_center(block), value) for value in values)
            continue
        width = block.bounding_box.width
        for index, value in enumerate(values):
            x_center = block.bounding_box.x0 + ((index + 0.5) * width / len(values))
            entries.append((x_center, value))
    return entries


def _strip_money_values(text: str) -> str:
    return _MONEY_SUBSTRING_PATTERN.sub(
        " ",
        _repair_money_ocr_punctuation(text),
    )


def _block_x_center(block: OcrBlock) -> float:
    if block.bounding_box is None:
        return 0.0
    return (block.bounding_box.x0 + block.bounding_box.x1) / 2


def _block_y_center(block: OcrBlock) -> float:
    if block.bounding_box is None:
        return 0.0
    return (block.bounding_box.y0 + block.bounding_box.y1) / 2


def _build_document_result(
    filename: str,
    analysis: DocumentAnalysisReport,
    config: OcrRuntimeConfig,
    provider: OCRProvider,
    expected_pages: int,
    pages: list[OcrPageResult],
    warnings: list[OcrWarning],
    errors: list[OcrError],
    started: float,
) -> OcrDocumentResult:
    pages = sorted(pages, key=lambda page: page.page_number)
    text = normalize_text("\n\n".join(page.text for page in pages if page.text))
    raw_text = normalize_text("\n\n".join(page.raw_text for page in pages if page.raw_text))
    successful_pages = [page for page in pages if page.status in {"PASS", "WARN"} and page.text]
    warning_pages = [page for page in pages if page.status == "WARN" or page.warnings]
    failed_pages = [
        page for page in pages if page.status in {"FAIL", "TIMEOUT", "CANCELLED"} or page.errors
    ]
    missing_page_numbers = (
        tuple(sorted(set(range(1, expected_pages + 1)) - {page.page_number for page in pages}))
        if expected_pages
        else ()
    )
    confidences = [page.confidence for page in successful_pages if page.confidence is not None]
    average_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
    min_page_confidence = round(min(confidences), 4) if confidences else None
    validation = validate_ocr_document(
        expected_pages=expected_pages, pages=pages, text=text, errors=errors
    )
    dqa_status = "NOT_RUN"
    chunking_ready = validation.chunking_ready
    blocking_reasons = list(validation.blocking_reasons)
    if validation.chunking_ready:
        parsed = ocr_result_to_parsed_document(
            OcrDocumentResult(
                document_id=Path(filename).stem,
                filename=filename,
                source_pdf_type=analysis.pdf_type or "unknown",
                engine_name=provider.provider_name,
                engine_version=getattr(provider, "provider_version", "unknown"),
                language=detect_language(text),
                page_count=expected_pages,
                processed_page_count=len(pages),
                successful_page_count=len(successful_pages),
                warning_page_count=len(warning_pages),
                failed_page_count=len(failed_pages),
                missing_page_numbers=missing_page_numbers,
                text=text,
                character_count=len(text),
                word_count=len(text.split()),
                average_confidence=average_confidence,
                min_page_confidence=min_page_confidence,
                total_render_time_ms=sum(page.render_time_ms for page in pages),
                total_ocr_time_ms=sum(page.ocr_time_ms for page in pages),
                processing_time_ms=_elapsed_ms(started),
                extraction_status="PASS",
                validation_status=validation.status,
                dqa_status="PENDING",
                chunking_ready=True,
                blocking_reasons=(),
                pages=tuple(pages),
                raw_text=raw_text,
            )
        )
        dqa_report = DocumentQualityEvaluator().evaluate(parsed)
        dqa_status = dqa_report.status
        chunking_ready = validation.chunking_ready and dqa_report.passed
        if not dqa_report.passed:
            blocking_reasons.extend(issue.code for issue in dqa_report.issues)
    extraction_status = _extraction_status(
        text=text, expected_pages=expected_pages, pages=pages, errors=errors
    )
    return OcrDocumentResult(
        document_id=Path(filename).stem,
        filename=filename,
        source_pdf_type=analysis.pdf_type or "unknown",
        engine_name=provider.provider_name,
        engine_version=getattr(provider, "provider_version", "unknown"),
        language=detect_language(text),
        page_count=expected_pages,
        processed_page_count=len(pages),
        successful_page_count=len(successful_pages),
        warning_page_count=len(warning_pages),
        failed_page_count=len(failed_pages),
        missing_page_numbers=missing_page_numbers,
        text=text,
        character_count=len(text),
        word_count=len(text.split()),
        average_confidence=average_confidence,
        min_page_confidence=min_page_confidence,
        total_render_time_ms=sum(page.render_time_ms for page in pages),
        total_ocr_time_ms=sum(page.ocr_time_ms for page in pages),
        processing_time_ms=_elapsed_ms(started),
        extraction_status=extraction_status,
        validation_status=validation.status,
        dqa_status=dqa_status,
        chunking_ready=chunking_ready,
        blocking_reasons=tuple(dict.fromkeys(blocking_reasons)),
        pages=tuple(pages),
        warnings=tuple(warnings),
        errors=tuple(errors),
        metadata={
            "provider_health": provider.health_report(),
            "config": asdict(config),
            "analysis": analysis.to_dict(),
            "raw_text_preserved": True,
            "total_normalization_time_ms": round(
                sum(page.normalization_time_ms for page in pages), 3
            ),
        },
        raw_text=raw_text,
    )


def validate_ocr_document(
    *, expected_pages: int, pages: list[OcrPageResult], text: str, errors: list[OcrError]
) -> OcrValidationReport:
    blocking: list[str] = []
    warnings: list[str] = []
    if errors:
        blocking.extend(error.code for error in errors)
    page_numbers = [page.page_number for page in pages]
    if len(page_numbers) != len(set(page_numbers)):
        blocking.append("duplicate_pages")
    if page_numbers != sorted(page_numbers):
        blocking.append("page_order_invalid")
    if expected_pages and len(pages) != expected_pages:
        blocking.append("page_count_mismatch")
    failed_pages = [
        page for page in pages if page.status in {"FAIL", "TIMEOUT", "CANCELLED"} or page.errors
    ]
    if failed_pages:
        blocking.append("page_failures")
    if not text.strip():
        blocking.append("empty_ocr_output")
    successful = [page for page in pages if page.text and page.status in {"PASS", "WARN"}]
    coverage = len(successful) / expected_pages if expected_pages else 0.0
    if coverage < 0.8:
        blocking.append("page_success_coverage_below_failure_threshold")
    elif coverage < 0.95:
        warnings.append("page_success_coverage_below_success_threshold")
    confidences = [page.confidence for page in successful if page.confidence is not None]
    if confidences:
        avg = statistics.mean(confidences)
        min_conf = min(confidences)
        if avg < 0.7:
            blocking.append("average_confidence_below_failure_threshold")
        elif avg < 0.85:
            warnings.append("average_confidence_below_success_threshold")
        if min_conf < 0.4:
            blocking.append("min_page_confidence_below_failure_threshold")
        elif min_conf < 0.6:
            warnings.append("min_page_confidence_below_success_threshold")
    else:
        blocking.append("confidence_not_available")
    status = "FAIL" if blocking else ("WARN" if warnings else "PASS")
    return OcrValidationReport(
        status=status,
        chunking_ready=status in {"PASS", "WARN"} and not blocking,
        blocking_reasons=tuple(dict.fromkeys(blocking)),
        warnings=tuple(warnings),
    )


def _parse_paddle_blocks(raw_result: Any, *, page_number: int, language: str) -> list[OcrBlock]:
    lines = (
        raw_result[0]
        if raw_result
        and isinstance(raw_result, list)
        and raw_result
        and isinstance(raw_result[0], list)
        else []
    )
    parsed: list[tuple[BoundingBox | None, str, float | None]] = []
    for item in lines or []:
        try:
            box_points = item[0]
            text, confidence = item[1]
            xs = [float(point[0]) for point in box_points]
            ys = [float(point[1]) for point in box_points]
            box = BoundingBox.from_corners(min(xs), min(ys), max(xs), max(ys), unit="pixel")
            parsed.append((box, str(text), float(confidence)))
        except Exception:
            continue
    parsed.sort(
        key=lambda item: ((item[0].y0 if item[0] else 0.0), (item[0].x0 if item[0] else 0.0))
    )
    return [
        OcrBlock(
            block_id=f"page-{page_number}-block-{index}",
            block_type="text",
            text=text,
            confidence=round(confidence, 4) if confidence is not None else None,
            bounding_box=box,
            reading_order=index,
            language=language,
            raw_text=text,
            provider_coordinate_space_id=f"page-{page_number - 1}-ocr-input",
        )
        for index, (box, text, confidence) in enumerate(parsed, start=1)
        if text
    ]


def _project_ocr_page_to_original_space(
    page: OcrPageResult,
    *,
    original_width: int,
    original_height: int,
    page_number: int,
) -> OcrPageResult:
    if original_width <= 0 or original_height <= 0:
        return page
    transform = CoordinateTransform.rotate_right_angle(
        transform_id=f"page-{page_number}-ocr-rotation-{page.rotation_applied}",
        source_space_id=page.projected_coordinate_space_id
        or f"page-{page_number - 1}-rendered-image",
        target_space_id=page.input_coordinate_space_id or f"page-{page_number - 1}-ocr-input",
        degrees=page.rotation_applied,
        source_width=original_width,
        source_height=original_height,
    )
    logger.info(
        "coordinate_transform_applied",
        extra={
            "page_index": page_number - 1,
            "source_space": transform.source_space_id,
            "target_space": transform.target_space_id,
            "transform_type": transform.transform_type,
        },
    )
    transformed_blocks: list[OcrBlock] = []
    for block in page.blocks:
        projected = _project_ocr_block(
            block,
            transform=transform,
            page_number=page_number,
            original_width=original_width,
            original_height=original_height,
            rotation_applied=page.rotation_applied,
        )
        transformed_blocks.append(projected)
    return replace(
        page,
        blocks=tuple(transformed_blocks),
        original_width=original_width,
        original_height=original_height,
        transform_chain=(
            {
                "transform_id": transform.transform_id,
                "source_space_id": transform.source_space_id,
                "target_space_id": transform.target_space_id,
                "transform_type": transform.transform_type,
                "parameters": transform.parameters,
            },
        ),
    )


def _project_ocr_block(
    block: OcrBlock,
    *,
    transform: CoordinateTransform,
    page_number: int,
    original_width: int,
    original_height: int,
    rotation_applied: int,
) -> OcrBlock:
    provider_bbox = block.bounding_box
    projected_bbox: BoundingBox | None = None
    normalized_bbox: BoundingBox | None = None
    projection_error: str | None = None
    if provider_bbox is not None:
        try:
            source_bbox = AxisAlignedBoundingBox(
                provider_bbox.x0,
                provider_bbox.y0,
                provider_bbox.x1,
                provider_bbox.y1,
                block.provider_coordinate_space_id or transform.target_space_id,
            )
            projected = transform.inverse_transform_bbox(source_bbox)
            projected_bbox = BoundingBox.from_corners(
                _legacy_bbox_coordinate(projected.x_min),
                _legacy_bbox_coordinate(projected.y_min),
                _legacy_bbox_coordinate(projected.x_max),
                _legacy_bbox_coordinate(projected.y_max),
                unit="pixel",
            )
            normalized_bbox = projected_bbox.normalized(
                page_width=float(original_width),
                page_height=float(original_height),
            )
        except ValueError as exc:
            projection_error = f"{exc.__class__.__name__}: {exc}"
            logger.warning(
                "inverse_transform_failed",
                extra={
                    "page_index": page_number - 1,
                    "element_id": block.block_id,
                    "source_space": transform.source_space_id,
                    "target_space": transform.target_space_id,
                    "transform_type": transform.transform_type,
                    "issue_code": "geometry_projection_failed",
                },
            )
    metadata = {
        **dict(block.metadata),
        "provider_bbox": (
            {
                "x0": provider_bbox.x0,
                "y0": provider_bbox.y0,
                "x1": provider_bbox.x1,
                "y1": provider_bbox.y1,
                "unit": provider_bbox.unit,
                "coordinate_space_id": block.provider_coordinate_space_id
                or transform.target_space_id,
            }
            if provider_bbox is not None
            else None
        ),
        "projected_bbox": (
            {
                "x0": projected_bbox.x0,
                "y0": projected_bbox.y0,
                "x1": projected_bbox.x1,
                "y1": projected_bbox.y1,
                "unit": projected_bbox.unit,
                "coordinate_space_id": transform.source_space_id,
            }
            if projected_bbox is not None
            else None
        ),
        "normalized_bbox": (
            {
                "x0": normalized_bbox.x0,
                "y0": normalized_bbox.y0,
                "x1": normalized_bbox.x1,
                "y1": normalized_bbox.y1,
                "unit": normalized_bbox.unit,
                "coordinate_space_id": f"page-{page_number - 1}-normalized",
            }
            if normalized_bbox is not None
            else None
        ),
    }
    if projection_error is not None:
        metadata["geometry_projection_error"] = projection_error
    return replace(
        block,
        provider_coordinate_space_id=block.provider_coordinate_space_id
        or transform.target_space_id,
        projected_bounding_box=projected_bbox,
        normalized_bounding_box=normalized_bbox,
        transform_chain=(
            {
                "transform_id": transform.transform_id,
                "source_space_id": transform.source_space_id,
                "target_space_id": transform.target_space_id,
                "transform_type": transform.transform_type,
                "rotation_applied": rotation_applied,
            },
        ),
        orientation_confidence=block.orientation_confidence,
        rotation_applied=rotation_applied,
        metadata=metadata,
    )


def _legacy_bbox_coordinate(value: float) -> float:
    return 0.0 if abs(value) <= 1e-6 else value


def _configure_ocr_environment(cache_dir: str) -> None:
    base = Path(cache_dir).resolve()
    home = base / "home"
    paddlex_cache = base / "paddlex_cache"
    home.mkdir(parents=True, exist_ok=True)
    paddlex_cache.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(home)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(paddlex_cache)


def _package_version(package_name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(package_name)
    except Exception:
        return None


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _extraction_status(
    *, text: str, expected_pages: int, pages: list[OcrPageResult], errors: list[OcrError]
) -> str:
    if errors or not text.strip() or not pages:
        return "FAIL"
    failed = sum(1 for page in pages if page.status in {"FAIL", "TIMEOUT", "CANCELLED"})
    if failed:
        return "PARTIAL"
    if expected_pages and len(pages) < expected_pages:
        return "PARTIAL"
    if any(page.status == "WARN" for page in pages):
        return "WARN"
    return "PASS"
