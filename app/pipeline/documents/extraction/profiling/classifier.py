from __future__ import annotations

from app.pipeline.documents.extraction.profiling.config import RoutingConfig
from app.pipeline.documents.extraction.profiling.models import (
    PageClass,
    PageClassification,
    PageProfile,
    ProfileStatus,
)


def classify_page(
    profile: PageProfile,
    *,
    config: RoutingConfig,
) -> PageClassification:
    secondary: list[PageClass] = []
    reasons: list[str] = list(profile.reason_codes)
    evidence = {
        "native_quality_score": profile.native_quality_score,
        "scan_probability": profile.scan_probability,
        "table_probability": profile.table_probability,
        "complex_layout_probability": profile.complex_layout_probability,
        "visual_probability": profile.visual_probability,
        "rotation_degrees": profile.rotation_degrees,
        "native_text_characters": profile.native_text_characters,
        "image_count": profile.image_count,
    }

    if profile.status == ProfileStatus.FAIL_CLOSED:
        return PageClassification(
            page_number=profile.page_number,
            classifier_version=config.classifier_version,
            primary_class=PageClass.UNSUPPORTED,
            secondary_classes=(PageClass.UNCERTAIN,),
            confidence=1.0,
            evidence=evidence,
            reason_codes=tuple(dict.fromkeys([*reasons, "profile_fail_closed"])),
        )

    if profile.native_text_characters == 0 and profile.image_count == 0:
        primary = PageClass.EMPTY
        confidence = 0.95
        reasons.append("empty_page_signals")
    elif (
        profile.scan_probability >= config.scan_probability_threshold
        and profile.native_text_characters == 0
    ):
        primary = PageClass.SCANNED
        confidence = profile.scan_probability
        reasons.append("no_native_text_scan_likely")
    elif (
        profile.scan_probability >= config.hybrid_threshold
        and profile.native_quality_score < config.native_quality_threshold
        and profile.image_count > 0
    ):
        primary = PageClass.HYBRID
        confidence = max(profile.scan_probability, 0.72)
        reasons.append("weak_native_plus_image")
    elif profile.native_quality_score >= config.native_quality_threshold:
        primary = PageClass.NATIVE
        confidence = profile.native_quality_score
        reasons.append("native_quality_above_threshold")
    elif profile.native_text_characters <= 30:
        primary = PageClass.LOW_INFORMATION
        confidence = 0.68
        reasons.append("low_information_text_layer")
    else:
        primary = PageClass.UNCERTAIN
        confidence = max(0.4, profile.native_quality_score)
        reasons.append("profile_uncertain")

    if profile.rotation_degrees in {90, 180, 270}:
        secondary.append(PageClass.ROTATED)
    if profile.table_probability >= config.table_probability_threshold:
        secondary.append(PageClass.TABLE_LIKELY)
    if profile.complex_layout_probability >= config.complex_layout_threshold:
        secondary.append(PageClass.COMPLEX_LAYOUT)
    if profile.visual_probability >= 0.7:
        secondary.append(PageClass.VISUAL_DOMINANT)
    if (
        primary not in {PageClass.EMPTY, PageClass.UNSUPPORTED}
        and confidence < config.manual_review_threshold
    ):
        secondary.append(PageClass.UNCERTAIN)
        reasons.append("classification_confidence_low")

    return PageClassification(
        page_number=profile.page_number,
        classifier_version=config.classifier_version,
        primary_class=primary,
        secondary_classes=tuple(dict.fromkeys(secondary)),
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        evidence=evidence,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


__all__ = ["classify_page"]
