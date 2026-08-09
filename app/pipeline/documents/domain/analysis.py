from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.pipeline.shared.text_utils import detect_language, normalize_text


class PdfType(StrEnum):
    TEXT_NATIVE = "text_native_pdf"
    SCANNED = "scanned_pdf"
    HYBRID = "hybrid_pdf"
    ENCRYPTED = "encrypted_pdf"
    CORRUPTED = "corrupted_pdf"
    UNKNOWN = "unknown_pdf"


class ExtractionStrategy(StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    HYBRID = "hybrid"
    REJECT = "reject"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class PdfPageAnalysis:
    page_number: int
    text_characters: int
    has_text_layer: bool
    image_count: int = 0
    font_count: int = 0
    ocr_required: bool = False
    ocr_reason: str | None = None


@dataclass(frozen=True)
class DocumentAnalysisReport:
    filename: str
    file_type: str
    document_language: str = "unknown"
    page_count: int = 0
    image_count: int = 0
    text_layer: bool = False
    font_available: bool = False
    image_coverage: float | None = None
    encrypted: bool = False
    corrupted: bool = False
    pdf_type: str | None = None
    estimated_scan_quality: str = "unknown"
    estimated_ocr_required: bool = False
    extraction_strategy: str = ExtractionStrategy.UNSUPPORTED.value
    confidence: float = 0.0
    potential_problems: tuple[str, ...] = field(default_factory=tuple)
    required_processing: tuple[str, ...] = field(default_factory=tuple)
    page_analysis: tuple[PdfPageAnalysis, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DocumentAnalyzer:
    def analyze(self, filename: str, content: bytes) -> DocumentAnalysisReport:
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension == "pdf":
            return self._analyze_pdf(filename, content)
        return DocumentAnalysisReport(
            filename=filename,
            file_type=extension or "unknown",
            extraction_strategy=ExtractionStrategy.NATIVE.value
            if extension
            else ExtractionStrategy.UNSUPPORTED.value,
            confidence=0.8 if extension else 0.0,
            required_processing=("native_parser",) if extension else ("reject_unsupported_format",),
        )

    def _analyze_pdf(self, filename: str, content: bytes) -> DocumentAnalysisReport:
        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception:
            return DocumentAnalysisReport(
                filename=filename,
                file_type="pdf",
                corrupted=True,
                pdf_type=PdfType.CORRUPTED.value,
                extraction_strategy=ExtractionStrategy.REJECT.value,
                confidence=1.0,
                potential_problems=("corrupted_pdf",),
                required_processing=("reject_corrupted_pdf",),
            )
        if not unlock_pdf_with_empty_password(reader):
            return DocumentAnalysisReport(
                filename=filename,
                file_type="pdf",
                encrypted=True,
                pdf_type=PdfType.ENCRYPTED.value,
                extraction_strategy=ExtractionStrategy.REJECT.value,
                confidence=1.0,
                potential_problems=("encrypted_pdf",),
                required_processing=("reject_password_protected_pdf",),
            )

        page_facts: list[tuple[int, str, int, int]] = []
        extracted_text: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = normalize_text(page.extract_text() or "")
            image_count = _count_page_images(page)
            font_count = _count_page_fonts(page)
            page_facts.append((page_number, text, image_count, font_count))
            if text:
                extracted_text.append(text)

        page_count = len(page_facts)
        recurrence_counts = Counter(
            key for _, text, _, _ in page_facts if (key := _recurrence_key(text))
        )
        page_reports: list[PdfPageAnalysis] = []
        for page_number, text, image_count, font_count in page_facts:
            ocr_required, ocr_reason = _ocr_requirement(
                text=text,
                image_count=image_count,
                page_count=page_count,
                recurrence_counts=recurrence_counts,
            )
            page_reports.append(
                PdfPageAnalysis(
                    page_number=page_number,
                    text_characters=len(text.strip()),
                    has_text_layer=bool(text.strip()),
                    image_count=image_count,
                    font_count=font_count,
                    ocr_required=ocr_required,
                    ocr_reason=ocr_reason,
                )
            )

        pages_with_text = sum(1 for page in page_reports if page.has_text_layer)
        image_count = sum(page.image_count for page in page_reports)
        font_count = sum(page.font_count for page in page_reports)
        text_layer = pages_with_text > 0
        font_available = font_count > 0
        image_coverage = (
            round(sum(1 for page in page_reports if page.image_count > 0) / page_count, 4)
            if page_count
            else None
        )
        pdf_type = _classify_pdf_type(page_reports)
        strategy = _select_strategy(pdf_type)
        problems = _potential_pdf_problems(
            pdf_type,
            page_reports=page_reports,
            image_count=image_count,
            font_available=font_available,
        )
        required_processing = _required_processing(strategy)
        confidence = _classification_confidence(
            page_reports=page_reports,
            image_count=image_count,
        )
        return DocumentAnalysisReport(
            filename=filename,
            file_type="pdf",
            document_language=detect_language("\n".join(extracted_text)),
            page_count=page_count,
            image_count=image_count,
            text_layer=text_layer,
            font_available=font_available,
            image_coverage=image_coverage,
            encrypted=False,
            corrupted=False,
            pdf_type=pdf_type.value,
            estimated_scan_quality="unknown"
            if pdf_type != PdfType.SCANNED
            else ("image_detected" if image_count else "no_text_layer"),
            estimated_ocr_required=(
                any(page.ocr_required for page in page_reports) or pdf_type is PdfType.UNKNOWN
            ),
            extraction_strategy=strategy.value,
            confidence=confidence,
            potential_problems=problems,
            required_processing=required_processing,
            page_analysis=tuple(page_reports),
        )


def unlock_pdf_with_empty_password(reader: PdfReader) -> bool:
    """Unlock PDFs that require no user password, rejecting genuinely locked files."""
    if not reader.is_encrypted:
        return True
    try:
        return bool(reader.decrypt(""))
    except Exception:
        return False


def _classify_pdf_type(page_reports: list[PdfPageAnalysis]) -> PdfType:
    if not page_reports:
        return PdfType.UNKNOWN
    if all(not page.has_text_layer for page in page_reports):
        return PdfType.SCANNED
    if any(page.ocr_required for page in page_reports):
        return PdfType.HYBRID
    return PdfType.TEXT_NATIVE


def _select_strategy(pdf_type: PdfType) -> ExtractionStrategy:
    if pdf_type == PdfType.TEXT_NATIVE:
        return ExtractionStrategy.NATIVE
    if pdf_type == PdfType.SCANNED:
        return ExtractionStrategy.OCR
    if pdf_type == PdfType.HYBRID:
        return ExtractionStrategy.HYBRID
    return ExtractionStrategy.REJECT


def _required_processing(strategy: ExtractionStrategy) -> tuple[str, ...]:
    if strategy == ExtractionStrategy.NATIVE:
        return ("native_pdf_parser",)
    if strategy == ExtractionStrategy.OCR:
        return ("ocr_backend",)
    if strategy == ExtractionStrategy.HYBRID:
        return ("native_pdf_parser", "ocr_backend", "merge_native_and_ocr")
    return ("reject_or_manual_review",)


def _potential_pdf_problems(
    pdf_type: PdfType,
    *,
    page_reports: list[PdfPageAnalysis],
    image_count: int,
    font_available: bool,
) -> tuple[str, ...]:
    problems: list[str] = []
    if pdf_type == PdfType.SCANNED:
        problems.append("no_text_layer")
        problems.append("ocr_required")
    if pdf_type == PdfType.HYBRID:
        problems.append("partial_text_layer")
        problems.append("ocr_required_for_some_pages")
    if any(page.has_text_layer and page.ocr_required for page in page_reports):
        problems.append("sparse_text_layer")
    if any(page.ocr_reason == "image_dominant_sparse_text" for page in page_reports):
        problems.append("image_dominant_sparse_text")
    if pdf_type == PdfType.UNKNOWN:
        problems.append("pdf_type_unknown")
    if image_count == 0 and pdf_type in {PdfType.SCANNED, PdfType.UNKNOWN}:
        problems.append("image_objects_not_detected_by_pypdf")
    if not font_available and pdf_type == PdfType.TEXT_NATIVE:
        problems.append("font_resources_not_detected")
    return tuple(problems)


def _classification_confidence(
    *,
    page_reports: list[PdfPageAnalysis],
    image_count: int,
) -> float:
    if not page_reports:
        return 0.2
    pages_with_text = sum(1 for page in page_reports if page.has_text_layer)
    if pages_with_text == 0 and image_count > 0:
        return 0.9
    if pages_with_text == 0:
        return 0.75
    if any(page.ocr_required for page in page_reports):
        return 0.85
    if pages_with_text == len(page_reports):
        return 0.95
    return 0.85


def _ocr_requirement(
    *,
    text: str,
    image_count: int,
    page_count: int,
    recurrence_counts: Counter[str],
) -> tuple[bool, str | None]:
    normalized = normalize_text(text)
    if not normalized:
        return True, "no_text_layer"
    if len(normalized) > 40:
        return False, None
    if image_count > 0:
        return True, "image_dominant_sparse_text"
    if page_count > 1 and _is_page_number(normalized):
        return True, "page_number_only"
    recurrence_key = _recurrence_key(normalized)
    if recurrence_key and recurrence_counts[recurrence_key] > 1:
        return True, "recurring_sparse_text"
    return False, None


def _is_page_number(text: str) -> bool:
    match = re.fullmatch(
        r"(?:(page|trang)\s*)?[-–—]?\s*(\d{1,4})\s*[-–—]?",
        text.strip(),
        re.IGNORECASE,
    )
    if not match:
        return False
    prefix, digits = match.groups()
    return prefix is not None or int(digits) <= 999


def _recurrence_key(text: str) -> str:
    normalized = re.sub(r"\d+", "#", " ".join(text.lower().split()))
    return normalized if len(normalized) >= 4 else ""


def _count_page_fonts(page: Any) -> int:
    try:
        resources = page.get("/Resources") or {}
        fonts = resources.get("/Font") or {}
        if hasattr(fonts, "get_object"):
            fonts = fonts.get_object()
        return len(fonts)
    except Exception:
        return 0


def _count_page_images(page: Any) -> int:
    try:
        images = getattr(page, "images", None)
        if images is not None:
            return len(images)
    except Exception:
        pass
    try:
        resources = page.get("/Resources") or {}
        xobjects = resources.get("/XObject") or {}
        if hasattr(xobjects, "get_object"):
            xobjects = xobjects.get_object()
        count = 0
        for item in xobjects.values():
            obj = item.get_object() if hasattr(item, "get_object") else item
            if obj.get("/Subtype") == "/Image":
                count += 1
        return count
    except Exception:
        return 0
