"""Deterministic prose-to-StructuredClaim extraction and table bridge for P3."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from app.knowledge_quality.application.business_scope import (
    ScopeTextContext,
    resolve_business_context,
)
from app.structured_facts.application.predicate_registry import (
    PREDICATE_REGISTRY_VERSION,
    PredicateMatch,
    canonicalize_predicate,
    find_predicate_matches,
)
from app.structured_facts.application.table_analyzer import TableAnalysis
from app.structured_facts.application.value_normalization import (
    OPERATOR_NORMALIZER_VERSION,
    VALUE_NORMALIZER_VERSION,
    normalize_value_expression,
)
from app.structured_facts.domain.models import (
    BusinessScope,
    ClaimProvenance,
    ClaimQualifiers,
    ConstraintValue,
    EntityEvidenceSource,
    NormalizedValue,
    ProductScope,
    ScalarValue,
    StructuredClaim,
    TemporalContext,
    ValueExpression,
    ValueOperator,
)

CLAIM_EXTRACTOR_VERSION = (
    "p3-prose-claims-v1+"
    f"{PREDICATE_REGISTRY_VERSION}+{VALUE_NORMALIZER_VERSION}+{OPERATOR_NORMALIZER_VERSION}"
)
MAX_CLAIMS_PER_CHUNK = 64

_SENTENCE_BOUNDARY = re.compile(r";|(?<=[!?])\s+|(?<=\.)\s+(?=[A-ZÀ-Ỹ0-9])")
_YEAR_VALUE_LINE = re.compile(r"^\s*((?:19|20)\d{2})\s*:\s*(.+)$")
_MONEY_VALUE = re.compile(
    r"(?:(?:từ|tu|ít nhất|it nhat|tối thiểu|toi thieu|không quá|khong qua|tối đa|toi da|"
    r"khoảng|khoang|xấp xỉ|xap xi|about|around|at least|at most)\s+)?"
    r"[+-]?\d[\d\s.,]*(?:\s*(?:[–—-]|đến|den|to)\s*[+-]?\d[\d\s.,]*)?"
    r"\s*(?:tỷ|ty|triệu|trieu|billion|million|bn|mn|vnd|vnđ|đồng|dong|usd|eur|[$€])"
    r"(?:\s*/\s*(?:căn|can|unit|m\s*(?:2|²)|sqm)(?:\s*/\s*(?:tháng|thang|month))?)?",
    re.IGNORECASE,
)
_UNIT_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "driving_range": re.compile(
        r"[+-]?\d[\d\s.,]*\s*(?:km|m|kilomet(?:er|re)?s?|met(?:er|re)s?)\b", re.I
    ),
    "battery_capacity": re.compile(r"[+-]?\d[\d\s.,]*\s*kwh\b", re.I),
    "charging_power": re.compile(r"[+-]?\d[\d\s.,]*\s*(?:kw|w)\b", re.I),
    "motor_power": re.compile(r"[+-]?\d[\d\s.,]*\s*(?:kw|w)\b", re.I),
    "torque": re.compile(r"[+-]?\d[\d\s.,]*\s*nm\b", re.I),
    "property_area": re.compile(r"[+-]?\d[\d\s.,]*\s*(?:m\s*(?:2|²)|sqm)\b", re.I),
    "charging_time": re.compile(
        r"[+-]?\d[\d\s.,]*\s*(?:phút|phut|minutes?|giây|giay|seconds?)\b", re.I
    ),
    "discount_rate": re.compile(r"[+-]?\d[\d\s.,]*\s*(?:%|percent)\b", re.I),
    "acceleration": re.compile(r"[+-]?\d[\d\s.,]*\s*(?:giây|giay|seconds?)\b", re.I),
    "warranty_duration": re.compile(
        r"[+-]?\d[\d\s.,]*\s*(?:năm|nam|years?|tháng|thang|months?)\b", re.I
    ),
}


@dataclass(frozen=True, slots=True)
class ClaimExtractionResult:
    claims: tuple[StructuredClaim, ...]
    warnings: tuple[str, ...]
    segment_count: int
    capped: bool = False


def extract_structured_claims(
    text: str,
    *,
    document_id: str,
    contexts: tuple[ScopeTextContext | str, ...] = (),
    domain_hint: str | None = None,
    owner_id: str | None = None,
    notebook_id: str | None = None,
    chunk_id: str | None = None,
    page_number: int | None = None,
    ingested_at: datetime | None = None,
    ocr_noise_level: str = "none",
    max_claims: int = MAX_CLAIMS_PER_CHUNK,
) -> ClaimExtractionResult:
    """Extract bounded, source-spanned claims while consuming P2 context."""
    if not document_id.strip():
        raise ValueError("document_id is required")
    if max_claims < 1:
        raise ValueError("max_claims must be positive")
    ocr_confidence = {
        "none": 1.0,
        "light": 0.9,
        "medium": 0.72,
        "severe": 0.45,
    }.get(ocr_noise_level)
    if ocr_confidence is None:
        raise ValueError("ocr_noise_level must be none, light, medium, or severe")
    external_contexts = tuple(_as_scope_context(item, index) for index, item in enumerate(contexts))
    segments = _segment_spans(text)
    inherited: list[ScopeTextContext] = list(external_contexts)
    document_context = resolve_business_context(
        text,
        contexts=external_contexts,
        domain_hint=domain_hint,
    )
    if document_context.primary_entity is not None and not document_context.ambiguous_entity_types:
        inherited.append(
            ScopeTextContext(
                text,
                EntityEvidenceSource.PARENT_CONTEXT,
                "document-claim-context",
            )
        )
    claims: list[StructuredClaim] = []
    warnings: list[str] = []
    capped = False

    for segment_index, (start, end) in enumerate(segments):
        segment = text[start:end].strip()
        if not segment:
            continue
        resolved = resolve_business_context(
            segment,
            contexts=tuple(inherited[-4:]),
            domain_hint=domain_hint,
        )
        primary = resolved.primary_entity
        domain = domain_hint or (primary.domain if primary is not None else None)
        matches = list(find_predicate_matches(segment, domain=domain))
        if not matches:
            inferred = _infer_predicate_from_value(segment, domain)
            if inferred is not None:
                matches.append(PredicateMatch(inferred, "inferred-value-role", 0, 0, 0.92))
        if not matches:
            if primary is not None or _looks_context_heading(segment):
                inherited.append(
                    ScopeTextContext(
                        segment,
                        EntityEvidenceSource.PARENT_CONTEXT,
                        f"segment:{segment_index}",
                    )
                )
            continue
        if primary is None:
            warnings.append(f"unresolved_subject:{segment_index}")
            continue

        for match_index, match in enumerate(matches):
            next_start = (
                matches[match_index + 1].start if match_index + 1 < len(matches) else len(segment)
            )
            local_end = max(match.end, next_start)
            claim_text = segment[match.start : local_end] if match.start else segment[:local_end]
            predicate = canonicalize_predicate(match.predicate, domain=domain)
            if predicate in {"availability", "feature_availability", "payment_term"}:
                claim_text = segment
            value_text = _value_phrase(claim_text, predicate)
            expression = _parse_claim_value(value_text, claim_text, predicate)
            qualifiers = _claim_qualifiers(resolved.qualifiers, predicate, claim_text, expression)
            scope = _scope_with_value_dimensions(resolved.business_scope, predicate, expression)
            scope = _claim_source_scope(scope, predicate, segment, domain)
            confidence = _extraction_confidence(
                entity_confidence=primary.confidence,
                predicate_confidence=match.confidence,
                value_confidence=expression.confidence,
                has_temporal=bool(resolved.temporal.reference_period),
                ocr_confidence=ocr_confidence,
            )
            absolute_start = start + (segment.find(claim_text) if claim_text else 0)
            absolute_end = absolute_start + len(claim_text)
            provenance = ClaimProvenance(
                document_id=document_id,
                page_number=page_number,
                source_span=(absolute_start, absolute_end),
                chunk_id=chunk_id,
                block_id=f"segment:{segment_index}",
            )
            claim_id = str(
                uuid5(
                    NAMESPACE_URL,
                    "\x1f".join(
                        (
                            document_id,
                            str(absolute_start),
                            str(absolute_end),
                            primary.canonical_id,
                            predicate,
                            CLAIM_EXTRACTOR_VERSION,
                        )
                    ),
                )
            )
            temporal = resolved.temporal
            if (
                temporal.reference_period is None
                and document_context.temporal.reference_period is not None
            ):
                temporal = document_context.temporal
            if temporal.reference_period is None:
                temporal = _p3_temporal_context(segment, fallback_text=text)
            if ingested_at is not None and temporal.ingested_at is None:
                temporal = replace(temporal, ingested_at=ingested_at.astimezone(UTC))
            claims.append(
                StructuredClaim(
                    id=claim_id,
                    owner_id=owner_id,
                    notebook_id=notebook_id,
                    document_id=document_id,
                    subject_key=primary.canonical_id,
                    predicate=predicate,
                    value=expression.to_normalized_value(),
                    value_expression=expression,
                    scope=scope,
                    qualifiers=qualifiers,
                    temporal=temporal,
                    provenance=provenance,
                    extraction_confidence=confidence,
                    extractor_version=CLAIM_EXTRACTOR_VERSION,
                    evidence=(
                        f"predicate_alias:{match.alias}",
                        f"value_text:{value_text}",
                        f"entity_registry:{primary.registry_version}",
                        f"ocr_noise_level:{ocr_noise_level}",
                    ),
                )
            )
            if len(claims) >= max_claims:
                warnings.append("claim_cap_reached")
                capped = True
                break
        if capped:
            break
        inherited.append(
            ScopeTextContext(
                segment,
                EntityEvidenceSource.PARENT_CONTEXT,
                f"segment:{segment_index}",
            )
        )
    return ClaimExtractionResult(
        claims=tuple(claims),
        warnings=tuple(dict.fromkeys(warnings)),
        segment_count=len(segments),
        capped=capped,
    )


def canonicalize_table_claims(analysis: TableAnalysis) -> tuple[StructuredClaim, ...]:
    """Adapt legacy table predicates/values into the same P3 claim contract."""
    canonical: list[StructuredClaim] = []
    for claim in analysis.claims:
        domain = _claim_domain(claim)
        predicate = canonicalize_predicate(claim.predicate, domain=domain)
        if predicate == "property_price" and domain == "vinfast":
            predicate = "vehicle_price"
        value = claim.value
        if _legacy_value_needs_parsing(value, predicate):
            expression = normalize_value_expression(
                value.raw_value or str(value.value),
                predicate=predicate,
                unit_hint=value.unit,
                currency_hint=value.currency,
                basis_hint=value.basis,
            ).expression
        else:
            expression = ValueExpression.from_normalized_value(value)
        subject_key, canonical_scope = _canonical_table_subject_scope(claim, domain)
        temporal = claim.temporal
        if temporal.reference_period is None:
            model_year = canonical_scope.vehicle.model_year
            if isinstance(model_year, int | str) and str(model_year).isdigit():
                temporal = _year_temporal(int(str(model_year)))
            elif temporal.effective_from is not None:
                effective_year = temporal.effective_from.year
                if temporal.effective_to is None or temporal.effective_to.year == effective_year:
                    temporal = replace(
                        temporal,
                        reference_period=str(effective_year),
                        claim_periods=(f"year:{effective_year}",),
                    )
        canonical_scope = _table_value_qualifiers(canonical_scope, predicate, value.raw_value)
        canonical.append(
            replace(
                claim,
                subject_key=subject_key,
                predicate=predicate,
                value_expression=expression,
                scope=_scope_with_value_dimensions(canonical_scope, predicate, expression),
                qualifiers=_claim_qualifiers(
                    claim.qualifiers,
                    predicate,
                    value.raw_value or str(value.value),
                    expression,
                ),
                temporal=temporal,
                extractor_version=f"{claim.extractor_version}+p3-bridge-v1",
                evidence=(
                    *claim.evidence,
                    "source_form:table",
                    f"legacy_predicate:{claim.predicate}",
                ),
            )
        )
    return tuple(canonical)


def _segment_spans(text: str) -> tuple[tuple[int, int], ...]:
    # A newline is often OCR/layout whitespace inside a sentence. It becomes a
    # hard boundary only around an explicit ``YYYY: value`` period row.
    newline_boundaries: set[tuple[int, int]] = set()
    for match in re.finditer(r"\n+", text):
        previous_line = text[: match.start()].rsplit("\n", 1)[-1].strip()
        next_line = text[match.end() :].split("\n", 1)[0].strip()
        if _YEAR_VALUE_LINE.match(previous_line) or _YEAR_VALUE_LINE.match(next_line):
            newline_boundaries.add((match.start(), match.end()))
    sentence_boundaries = tuple(
        (item.start(), item.end()) for item in _SENTENCE_BOUNDARY.finditer(text)
    )
    boundaries = sorted((*newline_boundaries, *sentence_boundaries))
    spans: list[tuple[int, int]] = []
    cursor = 0
    for boundary_start, boundary_end in boundaries:
        if boundary_start < cursor:
            continue
        if boundary_start > cursor:
            start, end = _trim_span(text, cursor, boundary_start)
            if end > start:
                spans.append((start, end))
        cursor = boundary_end
    if cursor < len(text):
        start, end = _trim_span(text, cursor, len(text))
        if end > start:
            spans.append((start, end))
    return tuple(spans)


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _value_phrase(text: str, predicate: str) -> str:
    if predicate in {"property_price", "vehicle_price", "management_fee", "maintenance_fee"}:
        match = _MONEY_VALUE.search(text)
    else:
        pattern = _UNIT_VALUE_PATTERNS.get(predicate)
        match = pattern.search(text) if pattern is not None else None
    if match is None:
        return text.strip()
    prefix = text[max(0, match.start() - 24) : match.start()]
    folded_prefix = _fold(prefix)
    operator_start = match.start()
    for marker in (
        "khong vuot qua",
        "khong lon hon",
        "khong thap hon",
        "khong qua",
        "toi thieu",
        "it nhat",
        "toi da",
        "xap xi",
        "khoang",
        "at least",
        "at most",
        "about",
        "around",
        "tu",
    ):
        position = folded_prefix.rfind(marker)
        if position >= 0:
            operator_start = max(0, match.start() - len(prefix) + position)
            break
    return text[operator_start : match.end()].strip()


def _parse_claim_value(value_text: str, claim_text: str, predicate: str) -> ValueExpression:
    if predicate == "service_feature":
        package = re.search(r"(?:goi ho tro dich vu|package)[-\s]*(\d+)", _fold(claim_text))
        value = f"package-{package.group(1)}" if package else _fold(claim_text)
        return ValueExpression(
            operator=ValueOperator.ENUM,
            value=value,
            raw_value=value_text,
            confidence=0.88,
        )
    return normalize_value_expression(value_text, predicate=predicate).expression


def _claim_qualifiers(
    qualifiers: ClaimQualifiers,
    predicate: str,
    text: str,
    expression: ValueExpression,
) -> ClaimQualifiers:
    key_aliases = {
        "commercial_price_basis": "price_basis",
        "commercial_price_type": "price_type",
        "product_bedrooms": "bedrooms",
        "product_property_type": "property_type",
        "vehicle_battery_variant": "battery_variant",
        "vehicle_market": "market",
        "vehicle_model_year": "model_year",
        "vehicle_test_protocol": "test_protocol",
        "vehicle_trim": "trim",
    }
    stable = {
        key_aliases.get(key, key): _canonical_qualifier_value(key_aliases.get(key, key), value)
        for key, value in qualifiers.stable
    }
    for scope_key in (
        "battery_variant",
        "bedrooms",
        "market",
        "model_year",
        "price_basis",
        "price_type",
        "property_type",
        "test_protocol",
        "trim",
    ):
        stable.pop(scope_key, None)
    if stable.get("price_type") == "sale_price":
        stable.pop("price_type")
    optional: dict[str, ConstraintValue] = dict(qualifiers.optional)
    if predicate in {"feature_availability", "amenity", "service_feature"}:
        feature_name = _feature_name(text, predicate)
        if feature_name:
            stable["feature_name"] = feature_name
    return ClaimQualifiers.from_mappings(stable=stable, optional=optional)


def _scope_with_value_dimensions(
    scope: BusinessScope,
    predicate: str,
    expression: ValueExpression,
) -> BusinessScope:
    if predicate not in {"property_price", "vehicle_price"}:
        commercial = scope.commercial
        if commercial.price_basis is not None or commercial.price_type is not None:
            return replace(
                scope,
                commercial=replace(commercial, price_basis=None, price_type=None),
            )
        return scope
    commercial = scope.commercial
    canonical_basis = _canonical_price_basis(commercial.price_basis)
    if canonical_basis is None and expression.basis is not None:
        canonical_basis = expression.basis
    if canonical_basis != commercial.price_basis:
        commercial = replace(commercial, price_basis=canonical_basis)
    return replace(scope, commercial=commercial)


def _canonical_qualifier_value(key: str, value: ConstraintValue) -> ConstraintValue:
    values = value if isinstance(value, tuple) else (value,)
    normalized = tuple(
        _canonical_price_basis_scalar(item) if key == "price_basis" else item for item in values
    )
    return normalized[0] if len(normalized) == 1 else normalized


def _canonical_price_basis(value: ConstraintValue | None) -> ConstraintValue | None:
    if isinstance(value, tuple):
        return tuple(_canonical_price_basis_scalar(item) for item in value)
    return _canonical_price_basis_scalar(value) if value is not None else None


def _canonical_price_basis_scalar(value: ScalarValue) -> ScalarValue:
    if not isinstance(value, str):
        return value
    folded = _fold(value)
    if folded in {"per unit", "per_unit", "total unit", "total_unit"}:
        return "total_unit"
    if folded in {"per sqm", "per_sqm", "per m2"}:
        return "per_sqm"
    return value


def _extraction_confidence(
    *,
    entity_confidence: float,
    predicate_confidence: float,
    value_confidence: float,
    has_temporal: bool,
    ocr_confidence: float,
) -> float:
    temporal_component = 1.0 if has_temporal else 0.9
    return round(
        min(
            entity_confidence,
            predicate_confidence,
            value_confidence,
            temporal_component,
            ocr_confidence,
        ),
        6,
    )


def _infer_predicate_from_value(value: str, domain: str | None) -> str | None:
    folded = _fold(value)
    if (
        domain == "vinhomes"
        and re.search(r"\b(?:ty|trieu|vnd|dong)\b|[$€]", folded)
        and (
            _YEAR_VALUE_LINE.match(value) is not None
            or "duoc ghi nhan" in folded
            or bool(re.match(r"^(?:19|20)\d{2}\s*:", value.strip()))
        )
    ):
        return "property_price"
    if domain == "vinfast" and re.search(r"\d[\d\s.,]*\s*(?:km|kilomet)", folded):
        return "driving_range"
    return None


def _claim_source_scope(
    scope: BusinessScope,
    predicate: str,
    text: str,
    domain: str | None,
) -> BusinessScope:
    """Attach conservative claim-local numeric roles absent from P2 facets."""
    if domain != "vinhomes" or predicate not in {"property_price", "property_area"}:
        return scope
    match = re.search(r"\bma\s*(\d{3,6})\b", _fold(text))
    if match is None or scope.location.unit is not None:
        return scope
    return replace(scope, location=replace(scope.location, unit=match.group(1)))


def _table_value_qualifiers(
    scope: BusinessScope,
    predicate: str,
    raw_value: str | None,
) -> BusinessScope:
    """Recover qualifiers encoded in a table value cell, with direct evidence."""
    if predicate != "driving_range" or not raw_value:
        return scope
    match = re.search(r"\b(WLTP|EPA|NEDC)\b", raw_value, re.IGNORECASE)
    if match is None:
        return scope
    return replace(
        scope,
        vehicle=replace(scope.vehicle, test_protocol=match.group(1).upper()),
    )


def _feature_name(text: str, predicate: str) -> str | None:
    folded = _fold(text)
    for prefix in ("tinh nang", "ho tro", "amenity", "goi ho tro dich vu"):
        if prefix in folded:
            suffix = folded.split(prefix, 1)[1]
            suffix = re.sub(
                r"\b(?:thu nghiem|khong duoc trang bi|khong|co|available|ho tro)\b",
                " ",
                suffix,
            )
            normalized = " ".join(suffix.split())
            return normalized[:120] or predicate
    return predicate if predicate in {"amenity", "service_feature"} else None


def _claim_domain(claim: StructuredClaim) -> str | None:
    for entity in claim.scope.entities:
        if entity.canonical_id == claim.subject_key or entity.entity_type in {
            "project",
            "vehicle_model",
        }:
            return entity.domain
    if claim.subject_key.startswith("vinfast_"):
        return "vinfast"
    if claim.subject_key.startswith("vinhomes_"):
        return "vinhomes"
    return None


def _canonical_table_subject_scope(
    claim: StructuredClaim,
    domain: str | None,
) -> tuple[str, BusinessScope]:
    scope = claim.scope
    for entity in scope.entities:
        if entity.entity_type in {"project", "vehicle_model"}:
            canonical_scope = (
                replace(scope, product=_canonical_table_product(scope.product))
                if entity.entity_type == "project"
                else scope
            )
            return entity.canonical_id, canonical_scope
    project = scope.location.project
    if isinstance(project, str) and project.strip():
        resolved = resolve_business_context(project, domain_hint="vinhomes")
        primary = resolved.primary_entity
        if primary is not None and primary.entity_type == "project":
            location = replace(
                scope.location,
                developer=primary.parent_id,
                project=primary.canonical_id,
            )
            product = _canonical_table_product(scope.product)
            return primary.canonical_id, replace(
                scope,
                location=location,
                product=product,
                entities=resolved.entities,
            )
    if domain == "vinhomes":
        return claim.subject_key, replace(scope, product=_canonical_table_product(scope.product))
    return claim.subject_key, scope


def _canonical_table_product(product: ProductScope) -> ProductScope:
    property_type = product.property_type
    if isinstance(property_type, str):
        match = re.fullmatch(r"([1-9])\s*pn", _fold(property_type))
        if match is not None:
            return replace(product, property_type="apartment", bedrooms=int(match.group(1)))
        if _fold(property_type) == "studio":
            return replace(product, property_type="studio", bedrooms=0)
        if _fold(property_type) in {"biet thu", "villa"}:
            return replace(product, property_type="villa")
    return product


def _p3_temporal_context(text: str, *, fallback_text: str = "") -> TemporalContext:
    years = [int(value) for value in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)]
    if not years and fallback_text:
        years = [
            int(value) for value in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", fallback_text)
        ]
    unique = sorted(set(years))
    if not unique:
        return TemporalContext()
    if len(unique) == 1:
        return _year_temporal(unique[0])
    return TemporalContext(
        effective_from=date(unique[0], 1, 1),
        effective_to=date(unique[-1], 12, 31),
        reference_period=f"{unique[0]}-{unique[-1]}",
        claim_periods=tuple(f"year:{year}" for year in unique),
    )


def _year_temporal(year: int) -> TemporalContext:
    return TemporalContext(
        effective_from=date(year, 1, 1),
        effective_to=date(year, 12, 31),
        reference_period=str(year),
        claim_periods=(f"year:{year}",),
    )


def _legacy_value_needs_parsing(value: NormalizedValue, predicate: str) -> bool:
    if predicate in {
        "driving_range",
        "battery_capacity",
        "charging_power",
        "motor_power",
        "torque",
    }:
        try:
            Decimal(str(value.value))
        except Exception:
            return True
    return False


def _looks_context_heading(text: str) -> bool:
    folded = _fold(text)
    return ":" in text or "vinhomes" in folded or bool(re.search(r"\bvf\s*\d{1,2}\b", folded))


def _as_scope_context(value: ScopeTextContext | str, index: int) -> ScopeTextContext:
    if isinstance(value, ScopeTextContext):
        return value
    return ScopeTextContext(
        value,
        EntityEvidenceSource.PARENT_CONTEXT,
        f"external-context:{index}",
    )


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    plain = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9%/.:_-]+", " ", plain).split())


__all__ = [
    "CLAIM_EXTRACTOR_VERSION",
    "MAX_CLAIMS_PER_CHUNK",
    "ClaimExtractionResult",
    "canonicalize_table_claims",
    "extract_structured_claims",
]
