"""Conservative, explainable duplicate and conflict signals."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

from app.knowledge_quality.application.business_scope import load_or_resolve_business_context
from app.knowledge_quality.application.claims import (
    classify_numeric_mentions,
    detect_claim_conflicts,
    normalize_claim_comparison_text,
    normalized_dates,
    normalized_number_literal,
    normalized_quantities,
)
from app.knowledge_quality.application.conflict_admission import decide_conflict_admission
from app.knowledge_quality.application.scope import (
    compare_claim_scopes,
    extract_claim_scope,
    has_explicit_reference_period,
    merge_claim_scopes,
    scope_reason_codes,
)
from app.knowledge_quality.domain.models import (
    CHUNK_NORMALIZATION_VERSION,
    DOCUMENT_NORMALIZATION_VERSION,
    LEGACY_DOCUMENT_NORMALIZATION_VERSION,
    ClaimConflict,
    ClaimScope,
    DocumentFingerprint,
    RelationType,
    ScopeComparison,
    TextRelationAnalysis,
)
from app.knowledge_quality.domain.scope_models import ConflictAdmissionDisposition

_AUTHORITATIVE_IGNORABLE = dict.fromkeys(map(ord, "\u00ad\u200b\u2060\ufeff"), None)
_CANDIDATE_IGNORABLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"), None)
_LEGACY_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_WORD_PATTERN = re.compile(r"[^\W_]+|\d+(?:[.,]\d+)*", re.UNICODE)
_NUMBER_PATTERN = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?:\s*%)?", re.UNICODE)
_NEGATIONS = frozenset(
    {
        "khong",
        "không",
        "chua",
        "chưa",
        "chang",
        "chẳng",
        "cam",
        "cấm",
        "not",
        "no",
        "never",
        "without",
    }
)
MIN_AUTO_IDENTITY_CHARACTERS = 40
MIN_AUTO_IDENTITY_TOKENS = 6


@dataclass(frozen=True, slots=True)
class ConflictEvidence:
    left_index: int
    right_index: int
    analysis: TextRelationAnalysis


def strict_normalize_text(text: str) -> str:
    """Normalize representation while preserving authoritative semantics."""
    normalized = unicodedata.normalize("NFC", text).translate(_AUTHORITATIVE_IGNORABLE)
    normalized = normalized.replace("\u00a0", " ")
    return " ".join(normalized.split())


def loose_normalize_text(text: str) -> str:
    """Candidate-only normalization; never use this value for automatic merge."""
    normalized = (
        unicodedata.normalize("NFKC", text)
        .translate(_CANDIDATE_IGNORABLE)
        .replace("\u00a0", " ")
        .casefold()
    )
    return " ".join(_tokens(normalized))


def _legacy_strict_normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).translate(_LEGACY_ZERO_WIDTH)
    normalized = normalized.replace("\u00a0", " ")
    return " ".join(normalized.split())


def _legacy_loose_normalize_text(text: str) -> str:
    return " ".join(_tokens(_legacy_strict_normalize_text(text).casefold()))


def build_document_fingerprint(
    text: str,
    *,
    identity_payload: str | None = None,
    normalization_version: str = DOCUMENT_NORMALIZATION_VERSION,
    identity_trusted: bool = True,
    projection_source: str = "plain_text",
    table_count: int = 0,
    fallback_used: bool = False,
    unrepresented_visual_count: int = 0,
    template_structure_signature: str | None = None,
    template_structure_version: str | None = None,
) -> DocumentFingerprint:
    """Build a document identity from semantic text and an optional canonical payload."""
    strict_text = strict_normalize_text(text)
    loose_text = loose_normalize_text(strict_text)
    tokens = tuple(loose_text.split())
    hash_input = identity_payload if identity_payload is not None else strict_text
    replacement_character_count = strict_text.count("\ufffd")
    return DocumentFingerprint(
        strict_hash=hashlib.sha256(hash_input.encode("utf-8")).hexdigest(),
        loose_signature=_simhash(tokens),
        normalization_version=normalization_version,
        character_count=len(strict_text),
        token_count=len(tokens),
        numbers=_numbers(strict_text),
        dates=_dates(strict_text),
        has_negation=_has_negation(tokens),
        identity_trusted=identity_trusted and replacement_character_count == 0,
        projection_source=projection_source,
        table_count=table_count,
        fallback_used=fallback_used,
        unrepresented_visual_count=unrepresented_visual_count,
        replacement_character_count=replacement_character_count,
        template_structure_signature=template_structure_signature,
        template_structure_version=template_structure_version,
    )


def build_legacy_document_fingerprint(text: str) -> DocumentFingerprint:
    """Reproduce v1 exactly so reconciliation repairs can verify existing rows."""
    strict_text = _legacy_strict_normalize_text(text)
    loose_text = _legacy_loose_normalize_text(strict_text)
    tokens = tuple(loose_text.split())
    return DocumentFingerprint(
        strict_hash=hashlib.sha256(strict_text.encode("utf-8")).hexdigest(),
        loose_signature=_simhash(tokens),
        normalization_version=LEGACY_DOCUMENT_NORMALIZATION_VERSION,
        character_count=len(strict_text),
        token_count=len(tokens),
        numbers=_numbers(strict_text),
        dates=_dates(strict_text),
        has_negation=_has_negation(tokens),
        replacement_character_count=strict_text.count("\ufffd"),
    )


def build_chunk_fingerprint(text: str) -> DocumentFingerprint:
    """Keep chunk identity versioned independently from document projection."""
    return build_document_fingerprint(
        text,
        normalization_version=CHUNK_NORMALIZATION_VERSION,
        projection_source="chunk_text",
    )


def is_auto_identity_eligible(fingerprint: DocumentFingerprint) -> bool:
    """Reject empty/tiny extraction output as authoritative auto-merge identity."""
    return (
        fingerprint.identity_trusted
        and fingerprint.unrepresented_visual_count == 0
        and fingerprint.replacement_character_count == 0
        and fingerprint.character_count >= MIN_AUTO_IDENTITY_CHARACTERS
        and fingerprint.token_count >= MIN_AUTO_IDENTITY_TOKENS
    )


def analyze_text_relation(
    left: str,
    right: str,
    *,
    semantic_similarity: float | None = None,
    left_scope: ClaimScope | None = None,
    right_scope: ClaimScope | None = None,
    left_entity_scope_metadata: object = None,
    right_entity_scope_metadata: object = None,
    domain_scope_mode: str = "shadow",
) -> TextRelationAnalysis:
    """Classify text only after scope and aligned-claim validation."""
    if domain_scope_mode not in {"off", "shadow", "on"}:
        raise ValueError("domain_scope_mode must be off, shadow, or on")
    left_strict = strict_normalize_text(left)
    right_strict = strict_normalize_text(right)
    if left_strict == right_strict and left_strict:
        return TextRelationAnalysis(
            relation_type=RelationType.EXACT_CONTENT,
            confidence=1.0,
            lexical_similarity=1.0,
            containment=1.0,
            semantic_similarity=semantic_similarity,
            number_agreement=True,
            date_agreement=True,
            negation_mismatch=False,
            reason_codes=("strict_content_match",),
            scope_comparison=compare_claim_scopes(left_scope, right_scope),
        )

    effective_left_scope = merge_claim_scopes(
        left_scope,
        extract_claim_scope(left),
    )
    effective_right_scope = merge_claim_scopes(
        right_scope,
        extract_claim_scope(right),
    )
    legacy_scope_comparison = compare_claim_scopes(effective_left_scope, effective_right_scope)
    scope_comparison = legacy_scope_comparison
    p2_decision = None
    p2_signals: dict[str, object] = {}
    if domain_scope_mode != "off":
        p2_left = load_or_resolve_business_context(
            left,
            persisted_metadata=left_entity_scope_metadata,
        )
        p2_right = load_or_resolve_business_context(
            right,
            persisted_metadata=right_entity_scope_metadata,
        )
        p2_decision = decide_conflict_admission(
            p2_left,
            p2_right,
            legacy_scope=legacy_scope_comparison.value,
        )
        p2_signals = {**p2_decision.to_payload(), "mode": domain_scope_mode}
        if domain_scope_mode == "on" and not p2_decision.allows_conflict_analysis:
            if p2_decision.disposition in {
                ConflictAdmissionDisposition.DISTINCT_ENTITY,
                ConflictAdmissionDisposition.CONDITIONAL_VARIANT,
            }:
                scope_comparison = ScopeComparison.DIFFERENT_SCOPE
            elif p2_decision.disposition is ConflictAdmissionDisposition.TEMPORAL_VARIANT:
                scope_comparison = ScopeComparison.TEMPORAL_DIVERGENCE
            else:
                scope_comparison = ScopeComparison.UNKNOWN_SCOPE
    left_tokens = tuple(_tokens(left_strict.casefold()))
    right_tokens = tuple(_tokens(right_strict.casefold()))
    left_shingles = _shingles(left_tokens, 3)
    right_shingles = _shingles(right_tokens, 3)
    lexical = max(
        _jaccard(left_shingles, right_shingles),
        SequenceMatcher(None, left_tokens, right_tokens, autojunk=False).ratio(),
    )
    containment = max(
        _containment(left_shingles, right_shingles),
        _token_containment(left_tokens, right_tokens),
    )
    left_projection = normalize_claim_comparison_text(left_strict)
    right_projection = normalize_claim_comparison_text(right_strict)
    projection_similarity = _sequence_similarity(left_projection, right_projection)
    exact_line_count, exact_line_ratio = _exact_line_overlap(left, right)
    template_similarity = max(lexical, containment, projection_similarity, exact_line_ratio)
    structural_numbers_ignored = sum(
        mention.role.value == "structural_reference"
        for text in (left_strict, right_strict)
        for mention in classify_numeric_mentions(text)
    )
    left_numbers = normalized_quantities(left_strict)
    right_numbers = normalized_quantities(right_strict)
    left_dates, right_dates = _dates(left_strict), _dates(right_strict)
    claim_conflicts = (
        detect_claim_conflicts(
            left_strict,
            right_strict,
            left_scope=effective_left_scope,
            right_scope=effective_right_scope,
        )
        if p2_decision is None or domain_scope_mode != "on" or p2_decision.allows_conflict_analysis
        else ()
    )
    structured_reasons = {
        reason for conflict in claim_conflicts for reason in conflict.reason_codes
    }
    number_agreement = (
        left_numbers == right_numbers and "semantic_quantity_mismatch" not in structured_reasons
    )
    date_agreement = left_dates == right_dates and "date_value_mismatch" not in structured_reasons
    negation_mismatch = "negation_mismatch" in structured_reasons or (
        not claim_conflicts and _has_negation(left_tokens) != _has_negation(right_tokens)
    )
    unit_agreement = "unit_value_mismatch" not in structured_reasons
    policy_modality_mismatch = "policy_modality_mismatch" in structured_reasons

    semantic = semantic_similarity if semantic_similarity is not None else 0.0
    claim_alignment = max(
        (conflict.alignment_score for conflict in claim_conflicts),
        default=0.0,
    )
    critical_difference = (
        not number_agreement
        or not date_agreement
        or negation_mismatch
        or not unit_agreement
        or policy_modality_mismatch
    )

    temporal_support = max(template_similarity, semantic)
    if scope_comparison is ScopeComparison.TEMPORAL_DIVERGENCE and temporal_support >= 0.35:
        explicit_periods = has_explicit_reference_period(
            effective_left_scope
        ) and has_explicit_reference_period(effective_right_scope)
        relation_type = (
            RelationType.TEMPORAL_SERIES if explicit_periods else RelationType.VERSION_CANDIDATE
        )
        reasons = list(scope_reason_codes(effective_left_scope, effective_right_scope))
        if p2_decision is not None and domain_scope_mode == "on":
            reasons.extend(p2_decision.reason_codes)
        reasons.append(
            "historical_series_not_conflict"
            if relation_type is RelationType.TEMPORAL_SERIES
            else "effective_period_version_difference"
        )
        if structured_reasons or not number_agreement or not date_agreement:
            reasons.append("value_difference_across_temporal_periods")
        if structural_numbers_ignored:
            reasons.append("structural_numbers_ignored")
        confidence = (
            min(0.49, 0.25 + 0.24 * temporal_support)
            if relation_type is RelationType.TEMPORAL_SERIES
            else min(0.89, 0.45 + 0.40 * temporal_support)
        )
        return TextRelationAnalysis(
            relation_type=relation_type,
            confidence=confidence,
            lexical_similarity=lexical,
            containment=containment,
            semantic_similarity=semantic_similarity,
            number_agreement=number_agreement,
            date_agreement=date_agreement,
            negation_mismatch=negation_mismatch,
            reason_codes=tuple(dict.fromkeys(reasons)),
            unit_agreement=unit_agreement,
            policy_modality_mismatch=policy_modality_mismatch,
            claim_conflicts=(),
            scope_comparison=scope_comparison,
            template_similarity=template_similarity,
            validated_conflict_count=0,
            confidence_components={
                "temporal_alignment": 1.0,
                "semantic_alignment": temporal_support,
                "template_similarity": template_similarity,
            },
            exact_line_overlap_count=exact_line_count,
            exact_line_overlap_ratio=exact_line_ratio,
            structural_numbers_ignored=structural_numbers_ignored,
            domain_scope_decision=p2_signals,
        )

    validated_conflicts = _deduplicate_claim_conflicts(claim_conflicts)
    if validated_conflicts and critical_difference:
        scope_alignment = 1.0 if scope_comparison is ScopeComparison.SAME_SCOPE else 0.65
        value_conflict = 1.0
        semantic_support = max(semantic, projection_similarity)
        confidence_components = {
            "scope_alignment": scope_alignment,
            "claim_key_alignment": claim_alignment,
            "value_conflict": value_conflict,
            "semantic_alignment": semantic_support,
            "template_similarity": template_similarity,
        }
        confidence = min(
            0.99,
            0.35 * scope_alignment
            + 0.35 * claim_alignment
            + 0.20 * value_conflict
            + 0.10 * semantic_support,
        )
        reasons = _ordered_conflict_reasons(structured_reasons)
        reasons.append("same_claim_key")
        reasons.append(
            "validated_same_scope_conflict"
            if scope_comparison is ScopeComparison.SAME_SCOPE
            else "scope_unknown_strong_claim_conflict"
        )
        return TextRelationAnalysis(
            relation_type=RelationType.CONFLICT_CANDIDATE,
            confidence=confidence,
            lexical_similarity=lexical,
            containment=containment,
            semantic_similarity=semantic_similarity,
            number_agreement=number_agreement,
            date_agreement=date_agreement,
            negation_mismatch=negation_mismatch,
            reason_codes=tuple(reasons),
            unit_agreement=unit_agreement,
            policy_modality_mismatch=policy_modality_mismatch,
            claim_conflicts=validated_conflicts,
            scope_comparison=scope_comparison,
            template_similarity=template_similarity,
            validated_conflict_count=len(validated_conflicts),
            confidence_components=confidence_components,
            exact_line_overlap_count=exact_line_count,
            exact_line_overlap_ratio=exact_line_ratio,
            structural_numbers_ignored=structural_numbers_ignored,
            domain_scope_decision=p2_signals,
        )

    if scope_comparison is ScopeComparison.DIFFERENT_SCOPE:
        reasons = list(scope_reason_codes(effective_left_scope, effective_right_scope))
        if p2_decision is not None and domain_scope_mode == "on":
            reasons.extend(p2_decision.reason_codes)
        if structural_numbers_ignored:
            reasons.append("structural_numbers_ignored")
        if template_similarity >= 0.45:
            reasons.extend(("shared_legal_template", "template_overlap_without_claim_alignment"))
            relation_type = RelationType.TEMPLATE_VARIANT
            confidence = min(0.97, 0.70 * template_similarity + 0.30 * containment)
        else:
            reasons.append("different_claim_key")
            relation_type = RelationType.DISTINCT
            confidence = max(0.0, 1.0 - template_similarity)
        return TextRelationAnalysis(
            relation_type=relation_type,
            confidence=confidence,
            lexical_similarity=lexical,
            containment=containment,
            semantic_similarity=semantic_similarity,
            number_agreement=number_agreement,
            date_agreement=date_agreement,
            negation_mismatch=negation_mismatch,
            reason_codes=tuple(dict.fromkeys(reasons)),
            unit_agreement=unit_agreement,
            policy_modality_mismatch=policy_modality_mismatch,
            scope_comparison=scope_comparison,
            template_similarity=template_similarity,
            exact_line_overlap_count=exact_line_count,
            exact_line_overlap_ratio=exact_line_ratio,
            structural_numbers_ignored=structural_numbers_ignored,
            domain_scope_decision=p2_signals,
        )

    length_ratio = (
        min(len(left_tokens), len(right_tokens)) / max(len(left_tokens), len(right_tokens))
        if left_tokens and right_tokens
        else 0.0
    )

    if not critical_difference and (
        semantic >= 0.92 or (projection_similarity >= 0.86 and length_ratio >= 0.85)
    ):
        confidence = min(
            0.97,
            0.60 * max(semantic, projection_similarity) + 0.25 * containment + 0.15 * length_ratio,
        )
        reasons = ["high_semantic_lexical_overlap"]
        if structural_numbers_ignored:
            reasons.append("structural_numbers_ignored")
        return TextRelationAnalysis(
            relation_type=RelationType.NEAR_DUPLICATE,
            confidence=confidence,
            lexical_similarity=lexical,
            containment=containment,
            semantic_similarity=semantic_similarity,
            number_agreement=number_agreement,
            date_agreement=date_agreement,
            negation_mismatch=negation_mismatch,
            reason_codes=tuple(reasons),
            unit_agreement=unit_agreement,
            policy_modality_mismatch=policy_modality_mismatch,
            claim_conflicts=claim_conflicts,
            scope_comparison=scope_comparison,
            template_similarity=template_similarity,
            exact_line_overlap_count=exact_line_count,
            exact_line_overlap_ratio=exact_line_ratio,
            structural_numbers_ignored=structural_numbers_ignored,
            domain_scope_decision=p2_signals,
        )

    if not critical_difference and containment >= 0.72 and projection_similarity >= 0.52:
        confidence = min(0.98, 0.45 * containment + 0.30 * lexical + 0.25 * semantic)
        return TextRelationAnalysis(
            relation_type=RelationType.VERSION_CANDIDATE,
            confidence=confidence,
            lexical_similarity=lexical,
            containment=containment,
            semantic_similarity=semantic_similarity,
            number_agreement=number_agreement,
            date_agreement=date_agreement,
            negation_mismatch=negation_mismatch,
            reason_codes=("high_content_containment",),
            unit_agreement=unit_agreement,
            policy_modality_mismatch=policy_modality_mismatch,
            claim_conflicts=claim_conflicts,
            scope_comparison=scope_comparison,
            template_similarity=template_similarity,
            exact_line_overlap_count=exact_line_count,
            exact_line_overlap_ratio=exact_line_ratio,
            structural_numbers_ignored=structural_numbers_ignored,
            domain_scope_decision=p2_signals,
        )

    if not critical_difference and (
        (semantic >= 0.88 and projection_similarity >= 0.40) or projection_similarity >= 0.82
    ):
        confidence = min(0.97, 0.55 * max(semantic, lexical) + 0.45 * containment)
        return TextRelationAnalysis(
            relation_type=RelationType.NEAR_DUPLICATE,
            confidence=confidence,
            lexical_similarity=lexical,
            containment=containment,
            semantic_similarity=semantic_similarity,
            number_agreement=number_agreement,
            date_agreement=date_agreement,
            negation_mismatch=negation_mismatch,
            reason_codes=("high_semantic_lexical_overlap",),
            unit_agreement=unit_agreement,
            policy_modality_mismatch=policy_modality_mismatch,
            claim_conflicts=claim_conflicts,
            scope_comparison=scope_comparison,
            template_similarity=template_similarity,
            exact_line_overlap_count=exact_line_count,
            exact_line_overlap_ratio=exact_line_ratio,
            structural_numbers_ignored=structural_numbers_ignored,
            domain_scope_decision=p2_signals,
        )

    distinct_reasons = ["insufficient_duplicate_evidence"]
    if structural_numbers_ignored:
        distinct_reasons.extend(
            ("structural_numbers_ignored", "structural_reference_difference_only")
        )
    if critical_difference and scope_comparison is ScopeComparison.UNKNOWN_SCOPE:
        distinct_reasons.append("scope_unknown_conflict_suppressed")
    if p2_decision is not None and domain_scope_mode == "on":
        distinct_reasons.extend(p2_decision.reason_codes)
    if scope_comparison is ScopeComparison.TEMPORAL_DIVERGENCE:
        distinct_reasons.extend(scope_reason_codes(effective_left_scope, effective_right_scope))
        distinct_reasons.append("temporal_similarity_below_threshold")
    return TextRelationAnalysis(
        relation_type=RelationType.DISTINCT,
        confidence=max(0.0, 1.0 - max(semantic, lexical, containment)),
        lexical_similarity=lexical,
        containment=containment,
        semantic_similarity=semantic_similarity,
        number_agreement=number_agreement,
        date_agreement=date_agreement,
        negation_mismatch=negation_mismatch,
        reason_codes=tuple(distinct_reasons),
        unit_agreement=unit_agreement,
        policy_modality_mismatch=policy_modality_mismatch,
        claim_conflicts=claim_conflicts,
        scope_comparison=scope_comparison,
        template_similarity=template_similarity,
        exact_line_overlap_count=exact_line_count,
        exact_line_overlap_ratio=exact_line_ratio,
        structural_numbers_ignored=structural_numbers_ignored,
        domain_scope_decision=p2_signals,
    )


def detect_conflicts(texts: tuple[str, ...]) -> tuple[ConflictEvidence, ...]:
    """Find high-confidence critical differences in a small retrieved context."""
    conflicts: list[ConflictEvidence] = []
    for (left_index, left), (right_index, right) in combinations(enumerate(texts), 2):
        analysis = analyze_text_relation(left, right)
        if (
            analysis.relation_type == RelationType.CONFLICT_CANDIDATE
            and analysis.confidence >= 0.62
        ):
            conflicts.append(
                ConflictEvidence(
                    left_index=left_index,
                    right_index=right_index,
                    analysis=analysis,
                )
            )
    return tuple(conflicts)


def _sequence_similarity(left: str, right: str) -> float:
    left_tokens = tuple(_tokens(left.casefold()))
    right_tokens = tuple(_tokens(right.casefold()))
    if not left_tokens or not right_tokens:
        return 1.0 if left_tokens == right_tokens and (left or right) else 0.0
    return max(
        SequenceMatcher(None, left_tokens, right_tokens, autojunk=False).ratio(),
        _token_containment(left_tokens, right_tokens),
    )


def _exact_line_overlap(left: str, right: str) -> tuple[int, float]:
    left_lines = {strict_normalize_text(line) for line in left.splitlines() if line.strip()}
    right_lines = {strict_normalize_text(line) for line in right.splitlines() if line.strip()}
    overlap = left_lines & right_lines
    denominator = min(len(left_lines), len(right_lines))
    return len(overlap), len(overlap) / denominator if denominator else 0.0


def _deduplicate_claim_conflicts(
    conflicts: tuple[ClaimConflict, ...],
) -> tuple[ClaimConflict, ...]:
    selected: dict[tuple[str, ...], ClaimConflict] = {}
    for conflict in conflicts:
        claim_key = conflict.left_claim.claim_key
        evidence_key = (
            claim_key.canonical_evidence_key()
            if claim_key is not None
            else (conflict.left_claim.alignment_key,)
        )
        key = (*evidence_key, *conflict.reason_codes)
        previous = selected.get(key)
        if previous is None or conflict.alignment_score > previous.alignment_score:
            selected[key] = conflict
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (item.left_claim.span_start, item.right_claim.span_start),
        )
    )


def _ordered_conflict_reasons(reasons: set[str]) -> list[str]:
    order = (
        "semantic_quantity_mismatch",
        "unit_value_mismatch",
        "date_value_mismatch",
        "negation_mismatch",
        "policy_modality_mismatch",
    )
    return [
        reason
        for reason in order
        if reason in reasons
        and not (reason == "policy_modality_mismatch" and "negation_mismatch" in reasons)
    ]


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _WORD_PATTERN.finditer(text))


def _numbers(text: str) -> tuple[str, ...]:
    values = {normalized_number_literal(match.group(0)) for match in _NUMBER_PATTERN.finditer(text)}
    return tuple(sorted(values))


def _dates(text: str) -> tuple[str, ...]:
    return normalized_dates(text)


def _has_negation(tokens: tuple[str, ...]) -> bool:
    return bool(_NEGATIONS.intersection(tokens))


def _shingles(tokens: tuple[str, ...], size: int) -> frozenset[tuple[str, ...]]:
    if not tokens:
        return frozenset()
    if len(tokens) <= size:
        return frozenset({tokens})
    return frozenset(tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1))


def _jaccard(left: frozenset[object], right: frozenset[object]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _containment(left: frozenset[object], right: frozenset[object]) -> float:
    denominator = min(len(left), len(right))
    return len(left & right) / denominator if denominator else 0.0


def _token_containment(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> float:
    denominator = min(len(left), len(right))
    if denominator == 0:
        return 0.0
    overlap = sum((Counter(left) & Counter(right)).values())
    return overlap / denominator


def _simhash(tokens: tuple[str, ...]) -> str:
    shingles = _shingles(tokens, 3)
    if not shingles:
        return "0" * 16
    weights = [0] * 64
    for shingle in shingles:
        raw = "\x1f".join(shingle).encode("utf-8")
        value = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
        for bit in range(64):
            weights[bit] += 1 if value & (1 << bit) else -1
    signature = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            signature |= 1 << bit
    return f"{signature:016x}"


__all__ = [
    "ConflictEvidence",
    "analyze_text_relation",
    "build_chunk_fingerprint",
    "build_document_fingerprint",
    "build_legacy_document_fingerprint",
    "detect_conflicts",
    "is_auto_identity_eligible",
    "loose_normalize_text",
    "strict_normalize_text",
]
