from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.documents.quality import DocumentQualityReport
from app.pipeline.documents.extraction.parsing.parsers import ParsedDocument


class ExtractionQualityMode(StrEnum):
    RAG = "rag"
    STRUCTURED = "structured"


class QualityAction(StrEnum):
    ACCEPT = "ACCEPT"
    ACCEPT_DEGRADED = "ACCEPT_DEGRADED"
    RETRY_CURRENT_PROVIDER = "RETRY_CURRENT_PROVIDER"
    FALLBACK_PROVIDER = "FALLBACK_PROVIDER"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAIL = "FAIL"


class QualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    P0 = "p0"


@dataclass(frozen=True)
class QualityPolicy:
    mode: ExtractionQualityMode
    min_text_score: float
    min_ocr_confidence: float
    allow_degraded: bool
    blocking_issue_codes: tuple[str, ...]
    review_issue_codes: tuple[str, ...]
    fallback_issue_codes: tuple[str, ...]
    max_provider_attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        return payload


@dataclass(frozen=True)
class QualityDecision:
    action: QualityAction
    severity: QualitySeverity
    issue_codes: tuple[str, ...]
    blocking_issues: tuple[str, ...]
    warnings: tuple[str, ...]
    quality_scores: dict[str, float | int | None]
    selected_policy: dict[str, Any]
    provider_attempts: int
    reason: str
    review_required: bool
    index_allowed: bool
    route: str
    fallback_required: bool = False
    degraded_features: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["severity"] = self.severity.value
        return payload


@dataclass(frozen=True)
class ExtractionRouteDecision:
    route: str
    fallback_required: bool
    review_required: bool
    reasons: tuple[str, ...]


STRUCTURED_EXTENSIONS = {"pdf", "xlsx", "csv", "docx", "pptx"}
STRUCTURED_CRITICAL_DOMAINS = {
    "structured_document",
    "financial_report",
    "invoice",
    "contract",
}
P0_ISSUE_CODES = {
    "structured_unbalanced_negative_parenthesis",
    "structured_missing_required_columns",
    "financial_unbalanced_negative_parenthesis",
    "financial_missing_required_columns",
}
CORRUPTION_ISSUE_CODES = {
    "empty_extraction",
    "ocr_required",
}
FALLBACK_ISSUE_CODES = {
    "low_ocr_confidence",
    "ocr_required",
    "page_failures",
    "average_confidence_below_failure_threshold",
    "min_page_confidence_below_failure_threshold",
}


def quality_policy_for_mode(
    mode: str | ExtractionQualityMode,
    *,
    max_provider_attempts: int = 1,
) -> QualityPolicy:
    normalized = _normalize_mode(mode)
    if normalized == ExtractionQualityMode.STRUCTURED:
        return QualityPolicy(
            mode=normalized,
            min_text_score=1.0,
            min_ocr_confidence=0.85,
            allow_degraded=False,
            blocking_issue_codes=tuple(sorted(P0_ISSUE_CODES | CORRUPTION_ISSUE_CODES)),
            review_issue_codes=tuple(sorted(P0_ISSUE_CODES | {"table_structure_loss"})),
            fallback_issue_codes=tuple(sorted(FALLBACK_ISSUE_CODES)),
            max_provider_attempts=max_provider_attempts,
        )
    return QualityPolicy(
        mode=normalized,
        min_text_score=0.4,
        min_ocr_confidence=0.6,
        allow_degraded=True,
        blocking_issue_codes=tuple(sorted(P0_ISSUE_CODES | CORRUPTION_ISSUE_CODES)),
        review_issue_codes=tuple(sorted(P0_ISSUE_CODES)),
        fallback_issue_codes=tuple(sorted(FALLBACK_ISSUE_CODES)),
        max_provider_attempts=max_provider_attempts,
    )


def route_extraction_result(
    *,
    filename: str,
    parsed: ParsedDocument,
    quality: DocumentQualityReport,
    mode: str | ExtractionQualityMode = ExtractionQualityMode.RAG,
    provider_attempts: int = 1,
    max_provider_attempts: int = 1,
    human_validated: bool = False,
) -> QualityDecision:
    policy = quality_policy_for_mode(
        mode,
        max_provider_attempts=max_provider_attempts,
    )
    extension = Path(filename).suffix.lower().lstrip(".")
    route = _route_for_document(extension=extension, parsed=parsed)
    issue_codes = tuple(dict.fromkeys(issue.code for issue in quality.issues))
    warnings = tuple(dict.fromkeys([*quality.warnings, *parsed.warnings]))
    blocking = tuple(code for code in issue_codes if code in policy.blocking_issue_codes)
    tuple(code for code in issue_codes if code in policy.fallback_issue_codes)
    degraded_features = tuple(code for code in issue_codes if code not in blocking)
    scores = {
        "confidence_score": quality.metrics.confidence_score,
        "text_characters": quality.metrics.text_characters,
        "structure_completeness": quality.metrics.structure_completeness,
        "metadata_completeness": quality.metrics.metadata_completeness,
        "table_preservation": quality.metrics.table_preservation,
        "ocr_accuracy": quality.metrics.ocr_accuracy,
    }

    if human_validated:
        return QualityDecision(
            action=QualityAction.ACCEPT,
            severity=QualitySeverity.INFO,
            issue_codes=issue_codes,
            blocking_issues=(),
            warnings=warnings,
            quality_scores=scores,
            selected_policy=policy.to_dict(),
            provider_attempts=provider_attempts,
            reason="human_validated_override",
            review_required=False,
            index_allowed=True,
            route=route,
            fallback_required=False,
            degraded_features=degraded_features,
        )

    if blocking:
        severity = QualitySeverity.P0 if set(blocking) & P0_ISSUE_CODES else QualitySeverity.ERROR
        action = QualityAction.REVIEW_REQUIRED
        reason = "blocking_quality_issue"
        fallback_required = bool(set(blocking) & set(policy.fallback_issue_codes))
        if fallback_required and provider_attempts < policy.max_provider_attempts:
            action = QualityAction.FALLBACK_PROVIDER
            reason = "fallback_available_for_blocking_issue"
        return QualityDecision(
            action=action,
            severity=severity,
            issue_codes=issue_codes,
            blocking_issues=blocking,
            warnings=warnings,
            quality_scores=scores,
            selected_policy=policy.to_dict(),
            provider_attempts=provider_attempts,
            reason=reason,
            review_required=action == QualityAction.REVIEW_REQUIRED,
            index_allowed=False,
            route=route,
            fallback_required=fallback_required,
            degraded_features=degraded_features,
        )

    if quality.status == "FAIL":
        action = (
            QualityAction.FALLBACK_PROVIDER
            if provider_attempts < policy.max_provider_attempts
            else QualityAction.REVIEW_REQUIRED
        )
        return QualityDecision(
            action=action,
            severity=QualitySeverity.ERROR,
            issue_codes=issue_codes,
            blocking_issues=issue_codes,
            warnings=warnings,
            quality_scores=scores,
            selected_policy=policy.to_dict(),
            provider_attempts=provider_attempts,
            reason="quality_failed",
            review_required=action == QualityAction.REVIEW_REQUIRED,
            index_allowed=False,
            route=route,
            fallback_required=action == QualityAction.FALLBACK_PROVIDER,
            degraded_features=degraded_features,
        )

    if policy.mode == ExtractionQualityMode.STRUCTURED and not quality.structured_ready:
        return QualityDecision(
            action=QualityAction.REVIEW_REQUIRED,
            severity=QualitySeverity.ERROR,
            issue_codes=issue_codes,
            blocking_issues=("structured_not_ready",),
            warnings=warnings,
            quality_scores=scores,
            selected_policy=policy.to_dict(),
            provider_attempts=provider_attempts,
            reason="structured_mode_not_ready",
            review_required=True,
            index_allowed=False,
            route=route,
            fallback_required=False,
            degraded_features=degraded_features,
        )

    if quality.status == "WARN" or degraded_features:
        if policy.allow_degraded:
            return QualityDecision(
                action=QualityAction.ACCEPT_DEGRADED,
                severity=QualitySeverity.WARNING,
                issue_codes=issue_codes,
                blocking_issues=(),
                warnings=warnings,
                quality_scores=scores,
                selected_policy=policy.to_dict(),
                provider_attempts=provider_attempts,
                reason="accepted_with_warnings",
                review_required=False,
                index_allowed=True,
                route=route,
                fallback_required=False,
                degraded_features=degraded_features,
            )
        return QualityDecision(
            action=QualityAction.REVIEW_REQUIRED,
            severity=QualitySeverity.WARNING,
            issue_codes=issue_codes,
            blocking_issues=degraded_features,
            warnings=warnings,
            quality_scores=scores,
            selected_policy=policy.to_dict(),
            provider_attempts=provider_attempts,
            reason="degraded_not_allowed",
            review_required=True,
            index_allowed=False,
            route=route,
            fallback_required=False,
            degraded_features=degraded_features,
        )

    return QualityDecision(
        action=QualityAction.ACCEPT,
        severity=QualitySeverity.INFO,
        issue_codes=issue_codes,
        blocking_issues=(),
        warnings=warnings,
        quality_scores=scores,
        selected_policy=policy.to_dict(),
        provider_attempts=provider_attempts,
        reason="quality_passed",
        review_required=False,
        index_allowed=True,
        route=route,
        fallback_required=False,
        degraded_features=(),
    )


def legacy_route_decision(decision: QualityDecision) -> ExtractionRouteDecision:
    return ExtractionRouteDecision(
        route=decision.route,
        fallback_required=decision.fallback_required,
        review_required=decision.review_required,
        reasons=tuple(dict.fromkeys([decision.reason, *decision.blocking_issues])),
    )


def _normalize_mode(mode: str | ExtractionQualityMode) -> ExtractionQualityMode:
    if isinstance(mode, ExtractionQualityMode):
        return mode
    normalized = str(mode).strip().lower()
    if normalized == ExtractionQualityMode.STRUCTURED.value:
        return ExtractionQualityMode.STRUCTURED
    if normalized == ExtractionQualityMode.RAG.value:
        return ExtractionQualityMode.RAG
    raise ValueError(f"Unsupported extraction quality mode: {mode}")


def _route_for_document(*, extension: str, parsed: ParsedDocument) -> str:
    domain = str(
        parsed.document_metadata.get("domain")
        or parsed.document_metadata.get("document_type")
        or ""
    )
    if domain in STRUCTURED_CRITICAL_DOMAINS or _looks_structured(parsed):
        return "structured_review"
    if extension in STRUCTURED_EXTENSIONS and parsed.tables:
        return "structured_review"
    return "rag_ingestion"


def _looks_structured(parsed: ParsedDocument) -> bool:
    text = parsed.text.lower()
    return any(
        marker in text
        for marker in (
            "bao cao tai chinh",
            "báo cáo tài chính",
            "bang can doi ke toan",
            "bảng cân đối kế toán",
            "thuyet minh",
            "thuyết minh",
        )
    )
