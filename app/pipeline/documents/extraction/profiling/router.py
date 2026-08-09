from __future__ import annotations

import time

from app.pipeline.documents.extraction.profiling.classifier import classify_page
from app.pipeline.documents.extraction.profiling.config import RoutingConfig, RoutingMode
from app.pipeline.documents.extraction.profiling.models import (
    DownstreamCapabilityHints,
    ExtractionRoute,
    PageClass,
    PageClassification,
    PageProfile,
    ProfileStatus,
    RouteSource,
    RoutingDecision,
)


class AdaptiveRouter:
    def __init__(self, config: RoutingConfig | None = None) -> None:
        self.config = config or RoutingConfig()
        self.config.validate()

    def classify(self, profile: PageProfile) -> PageClassification:
        return classify_page(profile, config=self.config)

    def decide(
        self,
        profile: PageProfile,
        *,
        route_source: RouteSource | None = None,
    ) -> RoutingDecision:
        started = time.perf_counter()
        classification = self.classify(profile)
        source = route_source or _route_source_for_mode(self.config.mode)
        route, terminal, review_required, reasons = self._route_for(
            profile,
            classification,
        )
        hints = self._hints_for(profile, classification, review_required=review_required)
        fallback_route = (
            ExtractionRoute.STATIC_FALLBACK
            if self.config.static_fallback_enabled
            and route
            not in {
                ExtractionRoute.NATIVE_ONLY,
                ExtractionRoute.EMPTY,
                ExtractionRoute.UNSUPPORTED,
            }
            else None
        )
        explanation = _explanation(profile, classification, route, reasons, hints)
        return RoutingDecision(
            document_id=profile.document_id,
            page_number=profile.page_number,
            route=route,
            route_source=source,
            policy_version=self.config.policy_version,
            input_checksum=profile.input_checksum,
            profile_checksum=profile.checksum(),
            classification_checksum=classification.checksum(),
            confidence=classification.confidence,
            maximum_attempts=self.config.maximum_attempts,
            maximum_orientation_candidates=self.config.maximum_orientation_candidates,
            maximum_page_deadline_ms=self.config.maximum_page_deadline_ms,
            static_fallback_enabled=self.config.static_fallback_enabled,
            fallback_route=fallback_route,
            review_required=review_required,
            terminal=terminal,
            reason_codes=tuple(dict.fromkeys([*classification.reason_codes, *reasons])),
            evidence={
                "profile": classification.evidence,
                "classification": classification.to_dict(),
                "policy_thresholds": {
                    "native_quality_threshold": self.config.native_quality_threshold,
                    "scan_probability_threshold": self.config.scan_probability_threshold,
                    "hybrid_threshold": self.config.hybrid_threshold,
                    "table_probability_threshold": self.config.table_probability_threshold,
                    "complex_layout_threshold": self.config.complex_layout_threshold,
                    "manual_review_threshold": self.config.manual_review_threshold,
                },
            },
            downstream_hints=hints,
            explanation=explanation,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def decide_many(
        self,
        profiles: list[PageProfile],
        *,
        route_source: RouteSource | None = None,
    ) -> list[RoutingDecision]:
        return [
            self.decide(profile, route_source=route_source)
            for profile in sorted(profiles, key=lambda item: item.page_number)
        ]

    def _route_for(
        self,
        profile: PageProfile,
        classification: PageClassification,
    ) -> tuple[ExtractionRoute, bool, bool, tuple[str, ...]]:
        reasons: list[str] = []
        primary = classification.primary_class
        secondaries = set(classification.secondary_classes)

        if profile.status == ProfileStatus.FAIL_CLOSED:
            return (
                ExtractionRoute.UNSUPPORTED,
                True,
                False,
                ("profile_required_signal_failed", "fail_closed_unsupported"),
            )
        if primary == PageClass.EMPTY:
            return ExtractionRoute.EMPTY, True, False, ("terminal_empty_page",)
        if primary == PageClass.UNSUPPORTED:
            return ExtractionRoute.UNSUPPORTED, True, False, ("terminal_unsupported_page",)
        if classification.confidence < self.config.manual_review_threshold:
            return (
                ExtractionRoute.MANUAL_REVIEW,
                True,
                True,
                ("manual_review_confidence_threshold",),
            )
        if (
            PageClass.ROTATED in secondaries
            and profile.orientation_confidence >= self.config.orientation_confidence_threshold
        ):
            reasons.append("bounded_orientation_recovery")
            return (
                ExtractionRoute.ORIENTATION_RECOVERY_OCR,
                False,
                False,
                tuple(reasons),
            )
        if primary == PageClass.SCANNED:
            return ExtractionRoute.OCR_ONLY, False, False, ("scanned_page_requires_ocr",)
        if primary == PageClass.HYBRID:
            return (
                ExtractionRoute.NATIVE_OCR_HYBRID,
                False,
                False,
                ("hybrid_page_preserve_native_and_ocr",),
            )
        if primary == PageClass.NATIVE:
            if PageClass.TABLE_LIKELY in secondaries or PageClass.COMPLEX_LAYOUT in secondaries:
                return (
                    ExtractionRoute.NATIVE_ONLY,
                    False,
                    False,
                    ("native_page_with_downstream_hint",),
                )
            return ExtractionRoute.NATIVE_ONLY, False, False, ("native_page_bypass_ocr",)
        if primary == PageClass.LOW_INFORMATION:
            if profile.image_count > 0:
                return (
                    ExtractionRoute.NATIVE_OCR_HYBRID,
                    False,
                    False,
                    ("low_information_with_image_fallback_ocr",),
                )
            return (
                ExtractionRoute.STATIC_FALLBACK,
                False,
                False,
                ("low_information_static_fallback",),
            )
        if self.config.static_fallback_enabled:
            return ExtractionRoute.STATIC_FALLBACK, False, False, ("uncertain_static_fallback",)
        return ExtractionRoute.MANUAL_REVIEW, True, True, ("uncertain_manual_review",)

    def _hints_for(
        self,
        profile: PageProfile,
        classification: PageClassification,
        *,
        review_required: bool,
    ) -> DownstreamCapabilityHints:
        secondaries = set(classification.secondary_classes)
        reason_codes: list[str] = []
        table_candidate = PageClass.TABLE_LIKELY in secondaries
        complex_candidate = PageClass.COMPLEX_LAYOUT in secondaries
        visual_candidate = PageClass.VISUAL_DOMINANT in secondaries
        rotated_candidate = PageClass.ROTATED in secondaries
        if table_candidate:
            reason_codes.append("phase4_table_candidate")
        if complex_candidate:
            reason_codes.append("phase3_complex_layout_candidate")
        if visual_candidate:
            reason_codes.append("phase6_visual_candidate")
        if rotated_candidate:
            reason_codes.append("phase3_rotated_layout_candidate")
        if classification.primary_class == PageClass.HYBRID:
            reason_codes.append("native_ocr_disagreement_possible")
        if review_required:
            reason_codes.append("manual_review_required")
        return DownstreamCapabilityHints(
            table_candidate=table_candidate,
            complex_layout_candidate=complex_candidate,
            visual_extraction_candidate=visual_candidate,
            reading_order_candidate=complex_candidate or table_candidate,
            rotated_layout_candidate=rotated_candidate,
            native_ocr_disagreement_review=classification.primary_class == PageClass.HYBRID,
            manual_review=review_required,
            reason_codes=tuple(reason_codes),
        )


def _route_source_for_mode(mode: RoutingMode) -> RouteSource:
    if mode == RoutingMode.SHADOW:
        return RouteSource.SHADOW
    if mode == RoutingMode.ADAPTIVE:
        return RouteSource.ADAPTIVE
    return RouteSource.STATIC


def _explanation(
    profile: PageProfile,
    classification: PageClassification,
    route: ExtractionRoute,
    reasons: tuple[str, ...],
    hints: DownstreamCapabilityHints,
) -> str:
    hint_codes = ", ".join(hints.reason_codes) or "none"
    reason_text = ", ".join(reasons or classification.reason_codes) or "no_reason"
    return (
        f"Page {profile.page_number} routed to {route.value} because "
        f"primary_class={classification.primary_class.value}, "
        f"native_quality_score={profile.native_quality_score:.4f}, "
        f"scan_probability={profile.scan_probability:.4f}, "
        f"table_probability={profile.table_probability:.4f}, "
        f"complex_layout_probability={profile.complex_layout_probability:.4f}, "
        f"visual_probability={profile.visual_probability:.4f}, "
        f"max_attempts evidence is bounded, reasons={reason_text}, "
        f"downstream_hints={hint_codes}."
    )


__all__ = ["AdaptiveRouter"]
