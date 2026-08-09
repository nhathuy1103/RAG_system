from __future__ import annotations

import hashlib
import io
import re
import time
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.pipeline.documents.extraction.documents.analysis import (
    DocumentAnalyzer,
    unlock_pdf_with_empty_password,
)
from app.pipeline.documents.extraction.profiling.config import ProfilingConfig
from app.pipeline.documents.extraction.profiling.models import (
    PageProfile,
    ProfileStatus,
    SignalFailure,
)
from app.pipeline.shared.text_utils import normalize_text

_MOJIBAKE_MARKERS = ("Ã", "Â", "Ä", "Æ", "áº", "á»", "â€", "â€“", "ï¿½")
_TABLE_MARKERS = (
    "ma so",
    "mã số",
    "chi tieu",
    "chi tiêu",
    "thuyet minh",
    "thuyết minh",
    "31/03/2026",
    "30/6/2025",
    "vnd",
    "tai san",
    "nguon von",
)
_COMPLEX_MARKERS = ("muc luc", "mục lục", "trang", "table of contents")


class PageProfiler:
    def __init__(self, config: ProfilingConfig | None = None) -> None:
        self.config = config or ProfilingConfig()
        self.config.validate()
        self.analyzer = DocumentAnalyzer()

    def profile_document(
        self,
        filename: str,
        content: bytes,
        *,
        document_id: str | None = None,
    ) -> list[PageProfile]:
        document_id = document_id or Path(filename).stem or _sha256(content)[:12]
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension != "pdf":
            return [self._profile_non_pdf(filename, content, document_id=document_id)]
        return self._profile_pdf(filename, content, document_id=document_id)

    def _profile_pdf(
        self,
        filename: str,
        content: bytes,
        *,
        document_id: str,
    ) -> list[PageProfile]:
        started = time.perf_counter()
        content_checksum = _sha256(content)
        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception as exc:
            return [
                self._fail_closed_profile(
                    document_id=document_id,
                    page_number=1,
                    input_checksum=content_checksum,
                    reason_code="pdf_reader_failed",
                    message=f"{exc.__class__.__name__}: {exc}",
                    latency_ms=_elapsed_ms(started),
                )
            ]
        if not unlock_pdf_with_empty_password(reader):
            return [
                self._fail_closed_profile(
                    document_id=document_id,
                    page_number=1,
                    input_checksum=content_checksum,
                    reason_code="pdf_encrypted",
                    message="PDF is encrypted.",
                    latency_ms=_elapsed_ms(started),
                )
            ]

        analysis = self.analyzer.analyze(filename, content)
        page_analysis = {page.page_number: page for page in analysis.page_analysis}
        profiles: list[PageProfile] = []
        for page_number, page in enumerate(reader.pages, start=1):
            page_started = time.perf_counter()
            failures: list[SignalFailure] = []
            try:
                text = normalize_text(page.extract_text() or "")
            except Exception as exc:
                text = ""
                failures.append(
                    SignalFailure(
                        signal_name="native_text",
                        reason_code="native_text_extraction_failed",
                        required=False,
                        message=f"{exc.__class__.__name__}: {exc}",
                    )
                )
            fact = page_analysis.get(page_number)
            width, height = _page_size(page)
            rotation = _page_rotation(page)
            image_count = fact.image_count if fact is not None else _count_page_images(page)
            font_count = fact.font_count if fact is not None else _count_page_fonts(page)
            profile = self._build_profile(
                document_id=document_id,
                page_number=page_number,
                content_checksum=content_checksum,
                text=text,
                width=width,
                height=height,
                rotation=rotation,
                image_count=image_count,
                font_count=font_count,
                missing_signals=tuple(failures),
                latency_ms=_elapsed_ms(page_started),
            )
            profiles.append(profile)
        if not profiles:
            return [
                self._fail_closed_profile(
                    document_id=document_id,
                    page_number=1,
                    input_checksum=content_checksum,
                    reason_code="pdf_has_no_pages",
                    message="PDF contains no pages.",
                    latency_ms=_elapsed_ms(started),
                )
            ]
        return profiles

    def _profile_non_pdf(
        self,
        filename: str,
        content: bytes,
        *,
        document_id: str,
    ) -> PageProfile:
        started = time.perf_counter()
        text = ""
        failures: list[SignalFailure] = []
        try:
            text = normalize_text(content.decode("utf-8"))
        except UnicodeDecodeError as exc:
            failures.append(
                SignalFailure(
                    signal_name="native_text",
                    reason_code="native_text_utf8_decode_failed",
                    required=False,
                    message=f"{exc.__class__.__name__}: {exc}",
                )
            )
            text = normalize_text(content.decode("latin-1", errors="replace"))
        return self._build_profile(
            document_id=document_id or Path(filename).stem,
            page_number=1,
            content_checksum=_sha256(content),
            text=text,
            width=None,
            height=None,
            rotation=0,
            image_count=0,
            font_count=0,
            missing_signals=tuple(failures),
            latency_ms=_elapsed_ms(started),
        )

    def _build_profile(
        self,
        *,
        document_id: str,
        page_number: int,
        content_checksum: str,
        text: str,
        width: float | None,
        height: float | None,
        rotation: int,
        image_count: int,
        font_count: int,
        missing_signals: tuple[SignalFailure, ...],
        latency_ms: float,
    ) -> PageProfile:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        characters = len(text.strip())
        words = len(text.split())
        digit_count = sum(1 for char in text if char.isdigit())
        mojibake_count = sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)
        replacement_characters = text.count("\ufffd") + text.count("?")
        page_area = max(1.0, float(width or 1000) * float(height or 1000))
        text_density = min(1.0, round((characters / page_area) * 45_000, 4))
        digit_ratio = round(digit_count / max(1, characters), 4)
        mojibake_ratio = round(mojibake_count / max(1, characters), 4)
        repeated_garbage_ratio = _repeated_garbage_ratio(text)
        native_quality_score = _native_quality_score(
            characters=characters,
            words=words,
            mojibake_ratio=mojibake_ratio,
            replacement_characters=replacement_characters,
            repeated_garbage_ratio=repeated_garbage_ratio,
        )
        table_probability = _table_probability(text, digit_ratio=digit_ratio, line_count=len(lines))
        complex_probability = _complex_layout_probability(
            text,
            line_count=len(lines),
            table_probability=table_probability,
        )
        visual_probability = _visual_probability(
            image_count=image_count,
            native_quality_score=native_quality_score,
            characters=characters,
        )
        scan_probability = _scan_probability(
            image_count=image_count,
            characters=characters,
            native_quality_score=native_quality_score,
            visual_probability=visual_probability,
        )
        orientation_confidence = 0.96 if rotation in {90, 180, 270} else 1.0
        reason_codes = _reason_codes(
            characters=characters,
            image_count=image_count,
            rotation=rotation,
            native_quality_score=native_quality_score,
            scan_probability=scan_probability,
            table_probability=table_probability,
            complex_probability=complex_probability,
            visual_probability=visual_probability,
            missing_signals=missing_signals,
        )
        input_checksum = _sha256_text(
            f"{content_checksum}|{page_number}|{self.config.signal_version}"
        )
        return PageProfile(
            document_id=document_id,
            page_number=page_number,
            schema_version=self.config.schema_version,
            profiler_version=self.config.profiler_version,
            signal_version=self.config.signal_version,
            status=(
                ProfileStatus.FAIL_CLOSED
                if any(item.required for item in missing_signals)
                else ProfileStatus.WARN
                if missing_signals
                else ProfileStatus.PASS
            ),
            input_checksum=input_checksum,
            native_text_characters=characters,
            native_word_count=words,
            text_density=text_density,
            digit_ratio=digit_ratio,
            mojibake_ratio=mojibake_ratio,
            replacement_characters=replacement_characters,
            repeated_garbage_ratio=repeated_garbage_ratio,
            image_count=image_count,
            image_coverage=1.0 if image_count else 0.0,
            font_count=font_count,
            width=width,
            height=height,
            rotation_degrees=rotation,
            native_quality_score=native_quality_score,
            scan_probability=scan_probability,
            table_probability=table_probability,
            complex_layout_probability=complex_probability,
            visual_probability=visual_probability,
            orientation_confidence=orientation_confidence,
            line_count=len(lines),
            average_line_length=round(sum(len(line) for line in lines) / max(1, len(lines)), 4),
            max_line_length=max((len(line) for line in lines), default=0),
            missing_signals=missing_signals,
            evidence={
                "text_sample_checksum": _sha256_text(text[:512]),
                "has_text_layer": bool(text.strip()),
                "line_count": len(lines),
                "image_signal_enabled": self.config.image_signal_enabled,
                "cheap_signals_only": True,
                "ocr_invoked": False,
            },
            reason_codes=reason_codes,
            latency_ms=latency_ms,
        )

    def _fail_closed_profile(
        self,
        *,
        document_id: str,
        page_number: int,
        input_checksum: str,
        reason_code: str,
        message: str,
        latency_ms: float,
    ) -> PageProfile:
        failure = SignalFailure(
            signal_name="pdf_page_enumeration",
            reason_code=reason_code,
            required=True,
            message=message,
        )
        return PageProfile(
            document_id=document_id,
            page_number=page_number,
            status=ProfileStatus.FAIL_CLOSED,
            input_checksum=input_checksum,
            native_quality_score=0.0,
            scan_probability=0.0,
            table_probability=0.0,
            complex_layout_probability=0.0,
            visual_probability=0.0,
            missing_signals=(failure,),
            evidence={"cheap_signals_only": True, "ocr_invoked": False},
            reason_codes=(reason_code, "required_signal_failed"),
            latency_ms=latency_ms,
        )


def _native_quality_score(
    *,
    characters: int,
    words: int,
    mojibake_ratio: float,
    replacement_characters: int,
    repeated_garbage_ratio: float,
) -> float:
    length_score = min(1.0, characters / 240.0)
    word_score = min(1.0, words / 40.0)
    quality = (length_score * 0.55) + (word_score * 0.35) + 0.10
    quality -= min(0.35, mojibake_ratio * 8.0)
    quality -= min(0.25, replacement_characters / max(1, characters) * 4.0)
    quality -= min(0.25, repeated_garbage_ratio * 2.0)
    if characters == 0:
        quality = 0.0
    return round(max(0.0, min(1.0, quality)), 4)


def _scan_probability(
    *,
    image_count: int,
    characters: int,
    native_quality_score: float,
    visual_probability: float,
) -> float:
    if characters == 0 and image_count > 0:
        return 0.94
    if characters == 0:
        return 0.72
    if image_count > 0 and characters < 80:
        return 0.78
    if visual_probability >= 0.7:
        return 0.7
    return round(max(0.0, min(1.0, 1.0 - native_quality_score - 0.15)), 4)


def _table_probability(text: str, *, digit_ratio: float, line_count: int) -> float:
    folded = _fold(text)
    marker_hits = sum(1 for marker in _TABLE_MARKERS if marker in folded)
    pipe_or_grid = 1 if "|" in text or re.search(r"\b\d{2,}\s+\d{2,}\b", text) else 0
    score = (
        (marker_hits * 0.16)
        + (digit_ratio * 1.2)
        + min(0.2, line_count / 120.0)
        + (pipe_or_grid * 0.16)
    )
    return round(max(0.0, min(1.0, score)), 4)


def _complex_layout_probability(
    text: str,
    *,
    line_count: int,
    table_probability: float,
) -> float:
    folded = _fold(text)
    marker_hits = sum(1 for marker in _COMPLEX_MARKERS if marker in folded)
    short_lines = sum(1 for line in text.splitlines() if 0 < len(line.strip()) <= 18)
    score = (marker_hits * 0.18) + min(0.25, short_lines / 80.0) + min(0.25, line_count / 140.0)
    if table_probability >= 0.7:
        score += 0.12
    return round(max(0.0, min(1.0, score)), 4)


def _visual_probability(*, image_count: int, native_quality_score: float, characters: int) -> float:
    if image_count <= 0:
        return 0.0
    score = 0.35 + min(0.35, image_count * 0.12)
    if characters < 60:
        score += 0.25
    score += max(0.0, 0.2 - native_quality_score * 0.2)
    return round(max(0.0, min(1.0, score)), 4)


def _reason_codes(
    *,
    characters: int,
    image_count: int,
    rotation: int,
    native_quality_score: float,
    scan_probability: float,
    table_probability: float,
    complex_probability: float,
    visual_probability: float,
    missing_signals: tuple[SignalFailure, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if characters == 0:
        reasons.append("no_native_text")
    elif native_quality_score >= 0.72:
        reasons.append("native_text_quality_good")
    elif native_quality_score < 0.45:
        reasons.append("native_text_quality_weak")
    if image_count > 0:
        reasons.append("image_objects_present")
    if scan_probability >= 0.68:
        reasons.append("scan_probability_high")
    if table_probability >= 0.62:
        reasons.append("table_probability_high")
    if complex_probability >= 0.62:
        reasons.append("complex_layout_probability_high")
    if visual_probability >= 0.7:
        reasons.append("visual_probability_high")
    if rotation in {90, 180, 270}:
        reasons.append("metadata_rotation_present")
    reasons.extend(item.reason_code for item in missing_signals)
    return tuple(dict.fromkeys(reasons))


def _page_size(page: Any) -> tuple[float | None, float | None]:
    try:
        box = page.mediabox
        return float(box.width), float(box.height)
    except Exception:
        return None, None


def _page_rotation(page: Any) -> int:
    try:
        value = int(page.get("/Rotate") or 0)
    except Exception:
        return 0
    return value % 360


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


def _count_page_fonts(page: Any) -> int:
    try:
        resources = page.get("/Resources") or {}
        fonts = resources.get("/Font") or {}
        if hasattr(fonts, "get_object"):
            fonts = fonts.get_object()
        return len(fonts)
    except Exception:
        return 0


def _repeated_garbage_ratio(text: str) -> float:
    if not text:
        return 0.0
    suspicious = re.findall(r"(.)\1{3,}", text)
    return round(sum(len(item) for item in suspicious) / max(1, len(text)), 4)


def _fold(value: str) -> str:
    return " ".join(value.lower().split())


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["PageProfiler"]
