from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from app.pipeline.documents.extraction.parsing.parsers import ParsedDocument
from app.pipeline.documents.extraction.validation.structured import validate_structured_document
from app.pipeline.shared.errors import AppError
from app.pipeline.shared.text_utils import normalize_text


@dataclass(frozen=True)
class DocumentQualityThresholds:
    min_text_characters: int = 1
    min_structure_completeness: float = 0.4
    min_metadata_completeness: float = 0.5
    min_ocr_confidence: float = 0.8


@dataclass(frozen=True)
class DocumentQualityIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class DocumentQualityMetrics:
    text_characters: int
    word_count: int
    page_count: int
    section_count: int
    table_count: int
    image_count: int
    extraction_coverage: float
    structure_completeness: float
    metadata_completeness: float
    table_preservation: float
    image_caption_preservation: float | None
    ocr_accuracy: float | None
    confidence_score: float


@dataclass(frozen=True)
class DocumentQualityReport:
    status: str
    parser_name: str
    detected_language: str
    metrics: DocumentQualityMetrics
    issues: tuple[DocumentQualityIssue, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    recommended_actions: tuple[str, ...] = field(default_factory=tuple)
    structured_ready: bool = False
    business_verified: bool = False

    @property
    def passed(self) -> bool:
        return self.status in {"PASS", "WARN"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DocumentQualityEvaluator:
    def __init__(self, thresholds: DocumentQualityThresholds | None = None) -> None:
        self.thresholds = thresholds or DocumentQualityThresholds()

    def evaluate(self, parsed: ParsedDocument) -> DocumentQualityReport:
        metrics = self._calculate_metrics(parsed)
        issues = list(self._collect_issues(parsed, metrics))
        recommended_actions = self._recommend_actions(parsed, issues)
        status = (
            "FAIL"
            if any(issue.severity == "error" for issue in issues)
            else ("WARN" if issues or parsed.warnings else "PASS")
        )
        return DocumentQualityReport(
            status=status,
            parser_name=parsed.parser_name,
            detected_language=parsed.detected_language,
            metrics=metrics,
            issues=tuple(issues),
            warnings=tuple(parsed.warnings),
            recommended_actions=tuple(recommended_actions),
            structured_ready=status == "PASS" and self._has_structured_evidence(parsed, metrics),
            business_verified=status == "PASS" and not self._has_business_p0(issues),
        )

    def enforce(self, parsed: ParsedDocument, *, mode: str = "rag") -> DocumentQualityReport:
        report = self.evaluate(parsed)
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"rag", "structured"}:
            raise ValueError(f"Unsupported quality gate mode: {mode}")
        accepted = report.passed if normalized_mode == "rag" else report.structured_ready
        if not accepted:
            issue_codes = (
                ", ".join(issue.code for issue in report.issues) or "unknown_quality_issue"
            )
            raise AppError(
                "document_quality_failed",
                f"Document extraction quality is not sufficient for chunking: {issue_codes}.",
                status_code=422,
            )
        return report

    def _calculate_metrics(self, parsed: ParsedDocument) -> DocumentQualityMetrics:
        text = parsed.text.strip()
        page_count = len(parsed.pages)
        section_count = len(parsed.sections)
        table_count = len(parsed.tables)
        image_count = len(parsed.images_metadata)
        structure_signals = [
            bool(text),
            page_count > 0,
            section_count > 0,
            parsed.detected_language != "unknown",
            bool(parsed.logical_document),
        ]
        metadata_keys = (
            "page_count",
            "word_count",
            "table_count",
            "image_count",
            "parser_name",
            "parser_version",
            "detected_language",
            "ocr_used",
        )
        metadata_present = sum(1 for key in metadata_keys if key in parsed.document_metadata)
        expected_text_sources = [section.text for section in parsed.sections if section.text] or [
            page.text for page in parsed.pages if page.text
        ]
        expected_text_size = max(
            sum(len(item.strip()) for item in expected_text_sources), len(text), 1
        )
        expected_table_count = max(table_count, _expected_table_count(parsed))
        preserved_table_count = sum(
            1 for table in parsed.tables if table.rows and table.columns > 0
        )
        table_preservation = (
            1.0 if expected_table_count == 0 else preserved_table_count / expected_table_count
        )
        image_caption_preservation = None
        if image_count:
            image_caption_preservation = (
                sum(1 for image in parsed.images_metadata if image.name) / image_count
            )
        ocr_accuracy = parsed.confidence if parsed.ocr_used else None
        confidence_values = [
            1.0 if text else 0.0,
            min(1.0, len(text) / expected_text_size),
            sum(1 for value in structure_signals if value) / len(structure_signals),
            metadata_present / len(metadata_keys),
            table_preservation,
        ]
        if ocr_accuracy is not None:
            confidence_values.append(ocr_accuracy)
        return DocumentQualityMetrics(
            text_characters=len(text),
            word_count=len(text.split()),
            page_count=page_count,
            section_count=section_count,
            table_count=table_count,
            image_count=image_count,
            extraction_coverage=round(min(1.0, len(text) / expected_text_size), 4),
            structure_completeness=round(
                sum(1 for value in structure_signals if value) / len(structure_signals), 4
            ),
            metadata_completeness=round(metadata_present / len(metadata_keys), 4),
            table_preservation=round(table_preservation, 4),
            image_caption_preservation=round(image_caption_preservation, 4)
            if image_caption_preservation is not None
            else None,
            ocr_accuracy=round(ocr_accuracy, 4) if ocr_accuracy is not None else None,
            confidence_score=round(sum(confidence_values) / len(confidence_values), 4),
        )

    def _collect_issues(
        self, parsed: ParsedDocument, metrics: DocumentQualityMetrics
    ) -> tuple[DocumentQualityIssue, ...]:
        issues: list[DocumentQualityIssue] = []
        if metrics.text_characters < self.thresholds.min_text_characters:
            issues.append(
                DocumentQualityIssue(
                    "empty_extraction", "error", "Parser returned no extractable text."
                )
            )
        if parsed.ocr_used and (
            metrics.ocr_accuracy is None
            or metrics.ocr_accuracy < self.thresholds.min_ocr_confidence
        ):
            issues.append(
                DocumentQualityIssue(
                    "low_ocr_confidence", "error", "OCR confidence is below acceptance criteria."
                )
            )
        if parsed.ocr_used:
            issues.extend(_ocr_completion_issues(parsed))
            issues.extend(_ocr_evidence_issues(parsed))
        if metrics.structure_completeness < self.thresholds.min_structure_completeness:
            issues.append(
                DocumentQualityIssue(
                    "low_structure_completeness",
                    "warning",
                    "Document structure evidence is incomplete.",
                )
            )
        if metrics.metadata_completeness < self.thresholds.min_metadata_completeness:
            issues.append(
                DocumentQualityIssue(
                    "low_metadata_completeness", "warning", "Document metadata is incomplete."
                )
            )
        if metrics.table_preservation < 1.0:
            issues.append(
                DocumentQualityIssue(
                    "table_structure_loss",
                    "warning",
                    "At least one table has missing row or column structure.",
                )
            )
        if metrics.image_count and metrics.image_caption_preservation == 0:
            issues.append(
                DocumentQualityIssue(
                    "image_caption_missing",
                    "warning",
                    "Images were detected without caption/name evidence.",
                )
            )
        for warning in parsed.warnings:
            if warning == "ocr_required_not_production_ready":
                issues.append(
                    DocumentQualityIssue(
                        "ocr_required",
                        "error",
                        "OCR is required but no production OCR provider is available.",
                    )
                )
            elif warning == "active_content_reference":
                issues.append(
                    DocumentQualityIssue(
                        "active_content_reference",
                        "warning",
                        "HTML active content was detected and sanitized.",
                    )
                )
        for issue_code in _business_p0_issue_codes(parsed):
            issues.append(
                DocumentQualityIssue(
                    issue_code,
                    "error",
                    "Business-critical extraction evidence is unsafe for structured use.",
                )
            )
        if _looks_like_structured_document(parsed):
            for validation_issue in validate_structured_document(parsed):
                issues.append(
                    DocumentQualityIssue(
                        validation_issue.code,
                        validation_issue.severity,
                        validation_issue.message,
                    )
                )
        return tuple(issues)

    def _recommend_actions(
        self, parsed: ParsedDocument, issues: list[DocumentQualityIssue]
    ) -> list[str]:
        actions: list[str] = []
        issue_codes = {issue.code for issue in issues}
        if "empty_extraction" in issue_codes:
            actions.append(
                "Reject document before chunking and inspect parser support or OCR need."
            )
        if "low_ocr_confidence" in issue_codes or "ocr_required" in issue_codes:
            actions.append("Route to production OCR provider before retrying extraction.")
        if "ocr_extraction_failed" in issue_codes or "partial_ocr_page_failures" in issue_codes:
            actions.append(
                "Route partial OCR output to retry or review; do not index failed pages silently."
            )
        if "partial_ocr_page_coverage" in issue_codes:
            actions.append(
                "Retry OCR with explicit page completion tracking before accepting the artifact."
            )
        if "low_structure_completeness" in issue_codes:
            actions.append(
                "Review parser structure extraction for pages, sections, headings, tables, and images."
            )
        if "low_metadata_completeness" in issue_codes:
            actions.append("Add parser metadata fields or document-level extraction metadata.")
        if "table_structure_loss" in issue_codes:
            actions.append(
                "Review native PDF table candidates and preserve rows/cells before structured indexing."
            )
        if parsed.parser_name == "pdf" and parsed.ocr_used is False and parsed.text.strip() == "":
            actions.append("Treat as scanned PDF candidate.")
        if "structured_unbalanced_negative_parenthesis" in issue_codes:
            actions.append(
                "Route structured table to fallback OCR/review; do not coerce the sign silently."
            )
        return actions

    def _has_structured_evidence(
        self,
        parsed: ParsedDocument,
        metrics: DocumentQualityMetrics,
    ) -> bool:
        if metrics.text_characters < self.thresholds.min_text_characters:
            return False
        if parsed.ocr_used and (
            metrics.ocr_accuracy is None
            or metrics.ocr_accuracy < self.thresholds.min_ocr_confidence
        ):
            return False
        if metrics.table_count:
            return metrics.table_preservation == 1.0
        return metrics.structure_completeness >= self.thresholds.min_structure_completeness

    def _has_business_p0(self, issues: list[DocumentQualityIssue]) -> bool:
        return any(
            issue.severity == "error" and issue.code in BUSINESS_P0_ISSUES for issue in issues
        )


BUSINESS_P0_ISSUES = {
    "structured_unbalanced_negative_parenthesis",
    "structured_missing_required_columns",
}


_UNBALANCED_FINANCIAL_VALUE = re.compile(r"(?<!\S)\(?\d{1,3}(?:\.\d{3}){2,}\)?(?!\S)")


def _business_p0_issue_codes(parsed: ParsedDocument) -> tuple[str, ...]:
    if not _looks_like_structured_document(parsed):
        return ()
    issue_codes: list[str] = []
    for table in parsed.tables:
        warnings = set(getattr(table, "warnings", []) or [])
        warnings.update(
            str(item) for item in dict(getattr(table, "metadata", {}) or {}).get("warnings", [])
        )
        if (
            "structured_unbalanced_negative_parenthesis" in warnings
            or "financial_unbalanced_negative_parenthesis" in warnings
        ):
            issue_codes.append("structured_unbalanced_negative_parenthesis")
    if _text_has_unbalanced_structured_parentheses(parsed.text):
        issue_codes.append("structured_unbalanced_negative_parenthesis")
    return tuple(dict.fromkeys(issue_codes))


def _ocr_completion_issues(parsed: ParsedDocument) -> tuple[DocumentQualityIssue, ...]:
    metadata = parsed.document_metadata
    issues: list[DocumentQualityIssue] = []
    extraction_status = str(
        metadata.get("extraction_status")
        or _nested_ocr_result_value(metadata, "extraction_status")
        or ""
    ).upper()
    validation_status = str(
        metadata.get("ocr_validation_status")
        or _nested_ocr_result_value(metadata, "validation_status")
        or ""
    ).upper()
    if extraction_status in {"FAIL", "PARTIAL"}:
        issues.append(
            DocumentQualityIssue(
                "ocr_extraction_failed",
                "error",
                "OCR extraction did not complete successfully.",
            )
        )
    if validation_status == "FAIL":
        issues.append(
            DocumentQualityIssue(
                "ocr_validation_failed",
                "error",
                "OCR validation detected blocking completion failures.",
            )
        )

    expected_pages = _positive_int(metadata.get("ocr_page_count"))
    successful_pages = _positive_int(metadata.get("ocr_successful_page_count"))
    failed_pages = _positive_int(metadata.get("ocr_failed_page_count")) or 0
    provenance = metadata.get("extraction_provenance")
    failed_provenance = []
    if isinstance(provenance, list):
        failed_provenance = [
            item
            for item in provenance
            if isinstance(item, dict)
            and (str(item.get("status") or "").upper() == "FAIL" or bool(item.get("error_codes")))
        ]
    if failed_pages or failed_provenance:
        issues.append(
            DocumentQualityIssue(
                "partial_ocr_page_failures",
                "error",
                "OCR output contains failed page records.",
            )
        )
    if (
        expected_pages is not None
        and successful_pages is not None
        and successful_pages < expected_pages
    ):
        issues.append(
            DocumentQualityIssue(
                "partial_ocr_page_coverage",
                "error",
                "OCR successful page coverage is below the source page count.",
            )
        )
    return tuple({issue.code: issue for issue in issues}.values())


_MOJIBAKE_EVIDENCE = re.compile(r"(?:Ã.|Â.|Ä.|Æ.|áº|á»|�)")
_ROTATED_TEXT_EVIDENCE = re.compile(
    r"\b(?:6u|Qnydnyd|Bunp|suo!noS|ue!a|ue!G|Gugo)\b|[A-Za-zÀ-ỹ]+![A-Za-zÀ-ỹ]+",
    re.IGNORECASE,
)
_MONEY_EVIDENCE = re.compile(r"\(?\d{1,3}(?:\.\d{3}){2,}\)?")
_PERCENTAGE_EVIDENCE = re.compile(r"\b\d{2,3}[,.]\d{2}\b")
_FINANCIAL_CODE_EVIDENCE = re.compile(r"^[A-Z]?\d{2,3}[a-z]?$", re.IGNORECASE)


def _ocr_evidence_issues(parsed: ParsedDocument) -> tuple[DocumentQualityIssue, ...]:
    """Report OCR/layout failure modes only when their extraction evidence survives."""

    detected: dict[str, DocumentQualityIssue] = {}

    def add(code: str, message: str) -> None:
        detected.setdefault(code, DocumentQualityIssue(code, "warning", message))

    rotated_pages: set[int] = set()
    for page in parsed.pages:
        metadata = _mapping(page.metadata)
        postprocessing = _mapping(metadata.get("postprocessing"))
        reports = [
            _mapping(postprocessing.get("normalization_report")),
            _mapping(
                _mapping(postprocessing.get("noise_filter")).get("text_reconstruction_report")
            ),
        ]
        if any(_normalization_has_encoding_repairs(report) for report in reports):
            add(
                "vietnamese_ocr_mojibake",
                "Vietnamese OCR text required encoding or diacritic repair.",
            )
        raw_text = "\n".join(
            str(element.metadata.get("ocr_raw_text") or "")
            for element in page.elements
            if isinstance(element.metadata, dict)
        )
        if raw_text and _MOJIBAKE_EVIDENCE.search(raw_text):
            add(
                "vietnamese_ocr_mojibake",
                "Raw Vietnamese OCR evidence contains mojibake-like sequences.",
            )

        noise_filter = _mapping(postprocessing.get("noise_filter"))
        dropped_blocks = noise_filter.get("dropped_blocks")
        dropped_count = _nonnegative_int(noise_filter.get("dropped_block_count"))
        if dropped_count and _has_visual_noise_evidence(dropped_blocks):
            add(
                "logo_stamp_noise",
                "OCR removed visual margin, logo, stamp, or isolated-symbol noise.",
            )
        if any(_positive_counter(report, "broken_lines_merged") for report in reports):
            add(
                "paragraph_line_reconstruction",
                "OCR paragraph lines required evidence-preserving reconstruction.",
            )

        rotation = _nonnegative_int(metadata.get("rotation_applied", getattr(page, "rotation", 0)))
        if rotation:
            rotated_pages.add(page.page_number)
            paragraph_texts = [
                element.text
                for element in page.elements
                if element.block_type == "paragraph" and element.text.strip()
            ]
            short_fragments = sum(
                1
                for text in paragraph_texts
                if len(_fold_evidence(text).replace(" ", "")) <= 3
                and any(char.isalpha() for char in text)
            )
            page_evidence = "\n".join(paragraph_texts)
            if _ROTATED_TEXT_EVIDENCE.search(page_evidence) or short_fragments >= 6:
                add(
                    "rotated_text_artifact",
                    "Residual OCR fragments remain after orientation handling.",
                )

    if _has_signature_role_loss(parsed):
        add(
            "signature_role_mapping_loss",
            "Signature roles are present in OCR text but absent from structured elements.",
        )

    for table in parsed.tables:
        header = [_fold_evidence(cell) for cell in table.header]
        data_rows = _table_data_rows(table)
        page_number = _table_page_number(table.location)
        if _is_toc_table(header) and _is_visual_ocr_table(table):
            add(
                "toc_two_column_order",
                "A two-column table of contents required geometry-based reading-order repair.",
            )
        if _is_financial_table(header):
            _collect_financial_evidence_issues(
                header=header,
                rows=data_rows,
                metadata=_mapping(getattr(table, "metadata", {})),
                add=add,
            )
        if page_number in rotated_pages and _is_subsidiary_table(header):
            repair_provenance = _mapping(
                _mapping(getattr(table, "metadata", {})).get("repair_provenance")
            )
            residual_mapping_loss = _rotated_table_mapping_loss(table, data_rows)
            reconstructed_from_rotated_source = bool(
                repair_provenance.get("orientation_recovery_applied")
                and repair_provenance.get("rotated_table_mapping_reconstructed")
            )
            if residual_mapping_loss or reconstructed_from_rotated_source:
                add(
                    "rotated_table_row_mapping_loss",
                    (
                        "A rotated table contains row-to-column mapping loss."
                        if residual_mapping_loss
                        else "A rotated table required evidence-preserving row mapping reconstruction."
                    ),
                )
                add(
                    "orientation_not_corrected",
                    (
                        "Orientation handling left structured row-mapping defects."
                        if residual_mapping_loss
                        else "Source orientation required bounded correction before structured mapping."
                    ),
                )

    return tuple(detected.values())


def _collect_financial_evidence_issues(
    *,
    header: list[str],
    rows: list[list[str]],
    metadata: dict[str, Any],
    add: Any,
) -> None:
    column_count = len(header)
    period_count = max(0, column_count - 3)
    repair_provenance = _mapping(metadata.get("repair_provenance"))
    if repair_provenance.get("missing_required_columns") is True:
        add(
            "structured_missing_required_columns",
            "Required financial columns were reconstructed from fragmented OCR evidence.",
        )
    if column_count == 7 and (
        any(cell.startswith(("ky_", "quy_", "chin_thang_")) for cell in header[3:])
        or len(set(header[3:])) != 4
        or repair_provenance.get("four_period_columns_reconstructed") is True
    ):
        add(
            "financial_four_period_columns_misassigned",
            "A four-period financial table required period-column reconstruction.",
        )
    if repair_provenance.get("unbalanced_negative_parenthesis") is True:
        add(
            "structured_unbalanced_negative_parenthesis",
            "A financial negative value required parenthesis repair from OCR evidence.",
        )
    if repair_provenance.get("amount_glued_to_label") is True:
        add(
            "structured_amount_glued_to_label",
            "A financial amount required separation from its OCR label.",
        )

    ragged = any(len(row) != column_count for row in rows)
    continuation = False
    missing_period = False
    misplaced = ragged
    glued_amount = False
    for raw_row in rows:
        row = [str(cell).strip() for cell in raw_row]
        padded = [*row, *([""] * max(0, column_count - len(row)))]
        code = padded[0] if padded else ""
        label = padded[1] if len(padded) > 1 else ""
        note = padded[2] if len(padded) > 2 else ""
        periods = padded[3:column_count] if period_count else []
        amount_presence = [bool(_MONEY_EVIDENCE.search(value)) for value in periods]
        if (not code and (label or any(amount_presence))) or (
            code and not _FINANCIAL_CODE_EVIDENCE.fullmatch(code)
        ):
            misplaced = True
        if (code or label) and period_count and not any(amount_presence):
            continuation = True
        if any(amount_presence) and any(not value for value in periods):
            missing_period = True
        if any(char.isalpha() for char in label + note) and _MONEY_EVIDENCE.search(
            label + " " + note
        ):
            glued_amount = True

    if ragged or continuation:
        add(
            "financial_multiline_row_split",
            "Financial rows contain continuation fragments or ragged multiline splits.",
        )
    if missing_period:
        add(
            "financial_missing_period_null_cell",
            "A financial row has an unrepresented blank period cell.",
        )
    if misplaced:
        add(
            "financial_column_misalignment",
            "Financial row evidence is not aligned with the declared columns.",
        )
    if glued_amount:
        add(
            "structured_amount_glued_to_label",
            "A financial amount is attached to a non-value label cell.",
        )


def _normalization_has_encoding_repairs(report: dict[str, Any]) -> bool:
    return bool(
        report.get("mojibake_repaired")
        or _positive_counter(report, "mojibake_sequences_detected")
        or _positive_counter(report, "vietnamese_ocr_terms_repaired")
    )


def _positive_counter(mapping: dict[str, Any], key: str) -> bool:
    return (_nonnegative_int(mapping.get(key)) or 0) > 0


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _expected_table_count(parsed: ParsedDocument) -> int:
    metadata = _mapping(parsed.document_metadata)
    native = _mapping(metadata.get("native_pdf_extraction"))
    candidates = [
        len(parsed.tables),
        _positive_int(native.get("table_candidate_count")) or 0,
        _positive_int(native.get("expected_table_count")) or 0,
        _positive_int(native.get("detected_table_count")) or 0,
    ]
    return max(candidates)


def _has_visual_noise_evidence(value: object) -> bool:
    if not isinstance(value, list):
        return True
    visual_reasons = {
        "vertical_or_margin_noise",
        "tiny_isolated_noise",
        "symbol_heavy_short_text",
        "no_meaningful_words",
        "low_confidence_short_text",
    }
    return any(
        isinstance(item, dict) and bool(set(item.get("reasons") or []) & visual_reasons)
        for item in value
    )


def _fold_evidence(value: object) -> str:
    text = unicodedata.normalize("NFKD", normalize_text(str(value)).casefold())
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).split())


def _table_data_rows(table: Any) -> list[list[str]]:
    rows = [[str(cell) for cell in row] for row in table.rows]
    if rows and [_fold_evidence(cell) for cell in rows[0]] == [
        _fold_evidence(cell) for cell in table.header
    ]:
        return rows[1:]
    return rows


def _is_visual_ocr_table(table: Any) -> bool:
    return str(dict(getattr(table, "metadata", {}) or {}).get("layout") or "") == (
        "ocr_visual_table"
    )


def _is_toc_table(header: list[str]) -> bool:
    return len(header) >= 2 and header[0] == "muc luc" and header[1] == "trang"


def _is_financial_table(header: list[str]) -> bool:
    return len(header) >= 5 and (
        header[0] == "ma so"
        or "thuyet minh" in header
        or any(value in {"tai san", "nguon von", "chi tieu"} for value in header)
    )


def _is_subsidiary_table(header: list[str]) -> bool:
    joined = " ".join(header)
    return len(header) >= 6 and "stt" in header and "ty le" in joined


def _table_page_number(location: object) -> int | None:
    match = re.search(r"\bpage[:-](\d+)\b", str(location or ""), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _has_signature_role_loss(parsed: ParsedDocument) -> bool:
    folded = _fold_evidence(parsed.text)
    role_hits = sum(
        marker in folded for marker in ("nguoi lap", "ke toan truong", "tong giam doc", "giam doc")
    )
    has_structured_roles = any(
        element.block_type.lower() in {"signature", "person", "role"}
        for page in parsed.pages
        for element in page.elements
    )
    return role_hits >= 2 and not has_structured_roles


def _rotated_table_mapping_loss(table: Any, rows: list[list[str]]) -> bool:
    column_count = len(table.header)
    if any(len(row) != column_count for row in rows):
        return True
    for row in rows:
        padded = [*row, *([""] * max(0, column_count - len(row)))]
        if len(padded) < 6:
            return True
        office = _fold_evidence(padded[4])
        activity = _fold_evidence(padded[5])
        office_has_address = bool(
            re.search(r"\d", office)
            or any(token in office for token in ("duong", "phuong", "street", "road"))
        )
        activity_has_address = bool(
            re.search(r"\d{1,4}[/ -]", activity)
            and any(
                token in activity for token in ("duong", "phuong", "street", "road", "thanh pho")
            )
        )
        if not padded[0].strip() or not padded[1].strip() or not office or not activity:
            return True
        if activity_has_address and not office_has_address:
            return True
    return False


def _nested_ocr_result_value(metadata: dict[str, object], key: str) -> object:
    value = metadata.get("ocr_result")
    if isinstance(value, dict):
        return value.get(key)
    return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _text_has_unbalanced_structured_parentheses(text: str) -> bool:
    for match in _UNBALANCED_FINANCIAL_VALUE.finditer(text):
        token = match.group(0)
        if token.count("(") != token.count(")"):
            return True
    return False


def _looks_like_structured_document(parsed: ParsedDocument) -> bool:
    metadata = parsed.document_metadata
    domain = str(metadata.get("domain") or metadata.get("document_type") or "").lower()
    if domain in {"structured_document", "financial_report"}:
        return True
    text = normalize_for_structured_detection(parsed.text)
    return any(
        marker in text
        for marker in (
            "bao cao tai chinh",
            "báo cáo tài chính",
            "bang can doi ke toan",
            "bảng cân đối kế toán",
            "bao cao ket qua hoat dong",
            "báo cáo kết quả hoạt động",
        )
    )


def normalize_for_structured_detection(text: str) -> str:
    return " ".join(text.lower().split())
