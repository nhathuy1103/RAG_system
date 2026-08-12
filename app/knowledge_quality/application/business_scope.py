"""Domain-aware business-scope assembly for Vinhomes and VinFast evidence."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from app.knowledge_quality.application.entity_resolution import (
    EntityTextContext,
    resolve_entities,
)
from app.knowledge_quality.domain.scope_models import (
    ResolvedBusinessContext,
    ScopeFacetEvidence,
)
from app.structured_facts.domain.models import (
    BusinessScope,
    ClaimQualifiers,
    CommercialScope,
    ConstraintValue,
    EntityEvidence,
    EntityEvidenceSource,
    EntityMatchMethod,
    EntityRef,
    LocationScope,
    ProductScope,
    TemporalContext,
    VehicleScope,
)

_YEAR_PATTERN = re.compile(r"(?<![\w./-])((?:19|20)\d{2})(?![\w./-])")
_MODEL_YEAR_PATTERN = re.compile(
    r"\b(?:doi|nam|model\s*year|model-year|my)\s*[:#-]?\s*((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_BUILDING_PATTERN = re.compile(
    r"\b(?:toa|building|block)\s*[:#-]?\s*([a-z]\d{1,2}(?:[.-]\d{1,3})?)\b",
    re.IGNORECASE,
)
_UNIT_PATTERN = re.compile(
    r"\b(?:ma\s*can|unit|can)\s*[:#-]?\s*(\d{3,6})\b",
    re.IGNORECASE,
)
_PHASE_PATTERN = re.compile(r"\b(?:giai\s*doan|phase)\s*[:#-]?\s*([a-z0-9.-]+)", re.I)
_SUBDIVISION_PATTERN = re.compile(
    r"\b(?:phan\s*khu|subdivision|zone)\s*[:#-]?\s*([a-z0-9.-]+)", re.I
)
_TRIM_PATTERN = re.compile(r"\b(eco|plus|base|premium)\b", re.IGNORECASE)
_PROTOCOL_PATTERN = re.compile(r"\b(wltp|epa|nedc)\b", re.IGNORECASE)
_BATTERY_VARIANT_PATTERN = re.compile(
    r"\b(?:pin|battery)(?:\s+(?:ban|variant))?\s*[:#-]?\s*(standard|extended)\b",
    re.IGNORECASE,
)
_DRIVETRAIN_PATTERN = re.compile(r"\b(awd|rwd|fwd|4wd)\b", re.IGNORECASE)
_CHARGING_WINDOW_PATTERN = re.compile(
    r"\b(?:sac|charge)[^\n.;]{0,30}?\b(?:tu|from)\s*(\d{1,3})\s*%?"
    r"[^\n.;]{0,20}?\b(?:len|den|to)\s*(\d{1,3})\s*%",
    re.IGNORECASE,
)
_OPAQUE_VARIANT_PATTERN = re.compile(
    r"\b(trim_variant|market_variant|battery_variant|price_type)\s+([ab])\b",
    re.IGNORECASE,
)

_PROPERTY_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, int | None]], ...] = (
    (re.compile(r"\bstudio\b", re.I), ("studio", 0)),
    (re.compile(r"\b([1-9])\s*pn\b", re.I), ("apartment", None)),
    (re.compile(r"\b(?:can\s*ho|apartment)\b", re.I), ("apartment", None)),
    (re.compile(r"\b(?:biet\s*thu|villa)\b", re.I), ("villa", None)),
    (re.compile(r"\b(?:nha\s*pho|townhouse)\b", re.I), ("townhouse", None)),
    (re.compile(r"\bshophouse\b", re.I), ("shophouse", None)),
)

_MARKET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:viet\s*nam|vietnam)\b", re.I), "vietnam"),
    (re.compile(r"\b(?:my|hoa\s*ky|usa|united\s*states)\b", re.I), "usa"),
    (re.compile(r"\b(?:chau\s*au|europe|eu)\b", re.I), "europe"),
    (re.compile(r"\bcanada\b", re.I), "canada"),
)

_PRICE_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:gia\s*chinh\s*thuc|official\s*price)\b", re.I), "official_price"),
    (re.compile(r"\b(?:thi\s*truong\s*so\s*cap|primary\s*market)\b", re.I), "primary_market"),
    (re.compile(r"\b(?:chao\s*thu\s*cap|secondary\s*market)\b", re.I), "secondary_market"),
    (re.compile(r"\b(?:gia\s*chao|asking\s*price)\b", re.I), "asking_price"),
    (re.compile(r"\b(?:gia\s*giao\s*dich|transaction\s*price)\b", re.I), "transaction_price"),
    (
        re.compile(r"\b(?:(?:gia\s*)?(?:tham\s*chieu|tham\s*khao)|reference\s*price)\b", re.I),
        "reference_price",
    ),
    (re.compile(r"\b(?:gia\s*trung\s*binh|average\s*price)\b", re.I), "average_price"),
    (re.compile(r"\b(?:gia\s*tu\s*muc|from\s*price)\b", re.I), "from_price"),
    (re.compile(r"\b(?:list\s*price|gia\s*niem\s*yet)\b", re.I), "list_price"),
    (re.compile(r"\b(?:promo(?:tional)?\s*price|gia\s*khuyen\s*mai)\b", re.I), "promo_price"),
)

_PREDICATE_STABLE_FACETS: dict[str, tuple[str, ...]] = {
    "vehicle_range": (
        "vehicle.trim",
        "vehicle.model_year",
        "vehicle.battery_variant",
        "vehicle.market",
        "vehicle.test_protocol",
    ),
    "vehicle_price": (
        "vehicle.trim",
        "vehicle.model_year",
        "vehicle.market",
        "commercial.price_type",
        "commercial.price_basis",
    ),
    "vehicle_battery_capacity": (
        "vehicle.trim",
        "vehicle.model_year",
        "vehicle.battery_variant",
        "vehicle.market",
    ),
    "vehicle_charging_time": (
        "vehicle.trim",
        "vehicle.model_year",
        "vehicle.market",
        "vehicle.charging_variant",
    ),
    "vehicle_feature": ("vehicle.trim", "vehicle.model_year", "vehicle.market"),
    "property_price": (
        "product.property_type",
        "product.bedrooms",
        "commercial.price_type",
        "commercial.price_basis",
        "commercial.payment_plan",
        "commercial.discount_program",
    ),
}


@dataclass(frozen=True, slots=True)
class ScopeTextContext:
    text: str
    source: EntityEvidenceSource
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Block:
    raw_text: str
    folded_text: str
    source: EntityEvidenceSource
    source_id: str | None


def resolve_business_context(
    text: str,
    *,
    contexts: tuple[ScopeTextContext, ...] = (),
    domain_hint: str | None = None,
) -> ResolvedBusinessContext:
    """Resolve entity, scope, qualifier, and temporal evidence with provenance."""
    entity_contexts = tuple(
        EntityTextContext(item.text, item.source, item.source_id) for item in contexts
    )
    resolution = resolve_entities(text, contexts=entity_contexts, domain_hint=domain_hint)
    inferred_domain = domain_hint or _domain_from_entities(resolution.entities)
    blocks = (
        _Block(text, _fold(text), EntityEvidenceSource.CLAIM_TEXT, None),
        *(_Block(item.text, _fold(item.text), item.source, item.source_id) for item in contexts),
    )
    evidence: list[ScopeFacetEvidence] = []

    predicate = _detect_predicate(blocks[0].folded_text, inferred_domain)

    location_values = _extract_location(blocks, evidence)
    product_values = _extract_product(blocks, evidence)
    commercial_values = _extract_commercial(blocks, evidence, predicate=predicate)
    vehicle_values = _extract_vehicle(blocks, evidence) if inferred_domain == "vinfast" else {}
    if inferred_domain == "vinfast":
        _apply_opaque_variants(blocks[0], vehicle_values, commercial_values, evidence)

    project_ref = _entity_of_type(resolution.entities, "project")
    model_ref = _entity_of_type(resolution.entities, "vehicle_model")
    if project_ref is not None:
        location_values["project"] = project_ref.canonical_id
        if project_ref.parent_id is not None:
            location_values.setdefault("developer", project_ref.parent_id)
    if model_ref is not None:
        vehicle_values["model"] = model_ref.canonical_id
        if model_ref.parent_id is not None:
            vehicle_values.setdefault("manufacturer", model_ref.parent_id)

    local_entities = _hierarchical_entity_refs(
        inferred_domain,
        project_ref,
        location_values,
        tuple(evidence),
    )
    entities = (*resolution.entities, *local_entities)
    explicit_breadth = _explicit_breadth(blocks, inferred_domain)
    scope = BusinessScope(
        location=LocationScope(**location_values),
        product=ProductScope(**product_values),
        commercial=CommercialScope(**commercial_values),
        vehicle=VehicleScope(**vehicle_values),
        entities=tuple(entities),
        explicit_breadth=explicit_breadth,
    )
    temporal = _extract_temporal(blocks, evidence)
    qualifiers = _predicate_qualifiers(
        predicate,
        scope,
        value_operator=_extract_value_operator(blocks[0].folded_text),
    )
    return ResolvedBusinessContext(
        entities=tuple(entities),
        business_scope=scope,
        qualifiers=qualifiers,
        temporal=temporal,
        predicate=predicate,
        facet_evidence=tuple(evidence),
        ambiguous_entity_types=resolution.ambiguous_entity_types,
    )


def load_or_resolve_business_context(
    text: str,
    *,
    persisted_metadata: object = None,
    contexts: tuple[ScopeTextContext, ...] = (),
    domain_hint: str | None = None,
) -> ResolvedBusinessContext:
    """Prefer valid P2 metadata and deterministically backfill legacy chunks."""
    persisted = ResolvedBusinessContext.from_metadata(persisted_metadata)
    return persisted or resolve_business_context(text, contexts=contexts, domain_hint=domain_hint)


def _extract_location(
    blocks: tuple[_Block, ...], evidence: list[ScopeFacetEvidence]
) -> dict[str, ConstraintValue]:
    values: dict[str, ConstraintValue] = {}
    for facet, pattern in (
        ("building", _BUILDING_PATTERN),
        ("unit", _UNIT_PATTERN),
        ("phase", _PHASE_PATTERN),
        ("subdivision", _SUBDIVISION_PATTERN),
    ):
        found = _first_pattern(blocks, pattern)
        if found is None:
            continue
        block, match = found
        raw = match.group(1)
        values[facet] = _scope_code(raw)
        evidence.append(_facet_evidence(f"location.{facet}", block, match.start(1), match.end(1)))
    return values


def _extract_product(
    blocks: tuple[_Block, ...], evidence: list[ScopeFacetEvidence]
) -> dict[str, ConstraintValue]:
    for block in blocks:
        for pattern, (property_type, fixed_bedrooms) in _PROPERTY_PATTERNS:
            match = pattern.search(block.folded_text)
            if match is None:
                continue
            bedrooms = fixed_bedrooms
            if pattern.pattern.startswith("\\b([1-9])"):
                bedrooms = int(match.group(1))
            result: dict[str, ConstraintValue] = {"property_type": property_type}
            if bedrooms is not None:
                result["bedrooms"] = bedrooms
            evidence.append(
                _facet_evidence("product.property_type", block, match.start(), match.end())
            )
            if bedrooms is not None:
                evidence.append(
                    _facet_evidence("product.bedrooms", block, match.start(), match.end())
                )
            return result
    return {}


def _extract_commercial(
    blocks: tuple[_Block, ...],
    evidence: list[ScopeFacetEvidence],
    *,
    predicate: str,
) -> dict[str, ConstraintValue]:
    values: dict[str, ConstraintValue] = {}
    for block in blocks:
        if predicate in {"property_price", "vehicle_price"} and "price_type" not in values:
            for pattern, price_type in _PRICE_TYPE_PATTERNS:
                match = pattern.search(block.folded_text)
                if match:
                    values["price_type"] = price_type
                    evidence.append(
                        _facet_evidence("commercial.price_type", block, match.start(), match.end())
                    )
                    break
        if "price_basis" not in values:
            basis_candidates: list[tuple[int, str, re.Match[str]]] = []
            for basis, pattern in (
                ("per_m2", re.compile(r"/(?:m2|m\s*2|met\s*vuong)|\bper\s*(?:sqm|m2)\b")),
                ("per_unit", re.compile(r"/(?:can|unit)|\b(?:moi\s*can|per\s*unit)\b")),
            ):
                if match := pattern.search(block.folded_text):
                    basis_candidates.append((match.start(), basis, match))
            if (
                not basis_candidates
                and re.search(r"\bma\s*can\b", block.folded_text)
                and re.search(r"\bgia\s*ban\b", block.folded_text)
            ):
                match = re.search(r"\bma\s*can\b", block.folded_text)
                assert match is not None
                basis_candidates.append((match.start(), "per_unit", match))
            if basis_candidates:
                _, basis, basis_match = min(basis_candidates, key=lambda item: item[0])
                values["price_basis"] = basis
                evidence.append(
                    _facet_evidence(
                        "commercial.price_basis", block, basis_match.start(), basis_match.end()
                    )
                )
        for field_name, pattern in (
            ("vat_included", re.compile(r"\b(?:bao\s*gom|included?)\s*vat\b", re.I)),
            (
                "maintenance_fee_included",
                re.compile(r"\b(?:bao\s*gom|included?)\s*(?:phi\s*bao\s*tri|maintenance)\b", re.I),
            ),
        ):
            if field_name not in values and (match := pattern.search(block.folded_text)):
                values[field_name] = True
                evidence.append(
                    _facet_evidence(f"commercial.{field_name}", block, match.start(), match.end())
                )
    return values


def _extract_vehicle(
    blocks: tuple[_Block, ...], evidence: list[ScopeFacetEvidence]
) -> dict[str, ConstraintValue]:
    values: dict[str, ConstraintValue] = {}
    for block in blocks:
        if "trim" not in values and (match := _TRIM_PATTERN.search(block.folded_text)):
            values["trim"] = match.group(1).casefold()
            evidence.append(_facet_evidence("vehicle.trim", block, match.start(), match.end()))
        if "test_protocol" not in values and (match := _PROTOCOL_PATTERN.search(block.folded_text)):
            values["test_protocol"] = match.group(1).upper()
            evidence.append(
                _facet_evidence("vehicle.test_protocol", block, match.start(), match.end())
            )
        if "battery_variant" not in values and (
            match := _BATTERY_VARIANT_PATTERN.search(block.folded_text)
        ):
            values["battery_variant"] = match.group(1).casefold()
            evidence.append(
                _facet_evidence("vehicle.battery_variant", block, match.start(), match.end())
            )
        if "drivetrain" not in values and (match := _DRIVETRAIN_PATTERN.search(block.folded_text)):
            values["drivetrain"] = match.group(1).upper()
            evidence.append(
                _facet_evidence("vehicle.drivetrain", block, match.start(), match.end())
            )
        if "market" not in values:
            for pattern, market in _MARKET_PATTERNS:
                match = pattern.search(block.folded_text)
                if match:
                    values["market"] = market
                    evidence.append(
                        _facet_evidence("vehicle.market", block, match.start(), match.end())
                    )
                    break
        if "model_year" not in values and (match := _MODEL_YEAR_PATTERN.search(block.folded_text)):
            values["model_year"] = int(match.group(1))
            evidence.append(
                _facet_evidence("vehicle.model_year", block, match.start(1), match.end(1))
            )
        if "model_year" not in values and (
            match := re.search(r"(?<!\d)((?:19|20)\d{2})-\d{2}-\d{2}", block.folded_text)
        ):
            values["model_year"] = int(match.group(1))
            evidence.append(
                _facet_evidence("vehicle.model_year", block, match.start(1), match.end(1))
            )
        if "charging_variant" not in values and (
            match := _CHARGING_WINDOW_PATTERN.search(block.folded_text)
        ):
            values["charging_variant"] = f"{int(match.group(1))}-{int(match.group(2))}"
            evidence.append(
                _facet_evidence("vehicle.charging_variant", block, match.start(), match.end())
            )
    return values


def _apply_opaque_variants(
    block: _Block,
    vehicle: dict[str, ConstraintValue],
    commercial: dict[str, ConstraintValue],
    evidence: list[ScopeFacetEvidence],
) -> None:
    match = _OPAQUE_VARIANT_PATTERN.search(block.folded_text)
    if match is None:
        return
    variant_type, variant = match.group(1).casefold(), match.group(2).casefold()
    field_by_variant = {
        "trim_variant": (vehicle, "trim", "vehicle.trim"),
        "market_variant": (vehicle, "market", "vehicle.market"),
        "battery_variant": (vehicle, "battery_variant", "vehicle.battery_variant"),
        "price_type": (commercial, "price_type", "commercial.price_type"),
    }
    target, key, facet = field_by_variant[variant_type]
    target[key] = f"opaque_variant_{variant}"
    evidence.append(_facet_evidence(facet, block, match.start(), match.end()))


def _extract_temporal(
    blocks: tuple[_Block, ...], evidence: list[ScopeFacetEvidence]
) -> TemporalContext:
    for block in blocks:
        year_matches = [*_YEAR_PATTERN.finditer(block.folded_text)]
        iso_matches = [*re.finditer(r"(?<!\d)((?:19|20)\d{2})-\d{2}-\d{2}", block.folded_text)]
        years = sorted({int(match.group(1)) for match in (*year_matches, *iso_matches)})
        if not years:
            continue
        for match in (*year_matches, *iso_matches):
            evidence.append(
                _facet_evidence("temporal.reference_period", block, match.start(), match.end())
            )
        start_year, end_year = years[0], years[-1]
        return TemporalContext(
            effective_from=date(start_year, 1, 1),
            effective_to=date(end_year, 12, 31),
            reference_period=(
                str(start_year) if start_year == end_year else f"{start_year}-{end_year}"
            ),
            claim_periods=tuple(f"year:{year}" for year in years),
        )
    return TemporalContext()


def _predicate_qualifiers(
    predicate: str,
    scope: BusinessScope,
    *,
    value_operator: str | None,
) -> ClaimQualifiers:
    all_values = {
        "product.property_type": scope.product.property_type,
        "product.bedrooms": scope.product.bedrooms,
        "commercial.price_type": scope.commercial.price_type,
        "commercial.price_basis": scope.commercial.price_basis,
        "commercial.payment_plan": scope.commercial.payment_plan,
        "commercial.discount_program": scope.commercial.discount_program,
        "vehicle.trim": scope.vehicle.trim,
        "vehicle.model_year": scope.vehicle.model_year,
        "vehicle.battery_variant": scope.vehicle.battery_variant,
        "vehicle.market": scope.vehicle.market,
        "vehicle.test_protocol": scope.vehicle.test_protocol,
        "vehicle.charging_variant": scope.vehicle.charging_variant,
    }
    stable_keys = _PREDICATE_STABLE_FACETS.get(predicate, ())
    stable = {key: all_values[key] for key in stable_keys if all_values.get(key) is not None}
    if value_operator is not None:
        stable["value.operator"] = value_operator
    optional = {
        key: value
        for key, value in all_values.items()
        if value is not None and key not in stable_keys
    }
    return ClaimQualifiers.from_mappings(stable=stable, optional=optional)


def _extract_value_operator(text: str) -> str | None:
    patterns = (
        ("range", r"\b(?:trong\s*khoang|between)\b"),
        ("at_least", r"\b(?:it\s*nhat|at\s*least|minimum)\b"),
        ("at_most", r"\b(?:khong\s*qua|at\s*most|up\s*to|maximum)\b"),
        ("from", r"\b(?:gia\s*)?(?:tu\s*muc|from)\b"),
    )
    for operator, pattern in patterns:
        if re.search(pattern, text):
            return operator
    return None


def _detect_predicate(text: str, domain: str | None) -> str:
    if domain == "vinfast":
        if re.search(r"\b(?:tam|pham\s*vi|range|km|kilomet)\b", text):
            return "vehicle_range"
        if re.search(r"\b(?:sac|charge|charging)\b", text):
            return "vehicle_charging_time"
        if re.search(r"\b(?:kwh|dung\s*luong\s*pin|battery\s*capacity)\b", text):
            return "vehicle_battery_capacity"
        if re.search(r"\b(?:gia|price|vnd|usd)\b", text):
            return "vehicle_price"
        return "vehicle_feature"
    if domain == "vinhomes" or re.search(r"\b(?:gia|ty|vnd|price)\b", text):
        return "property_price"
    return "unknown"


def _explicit_breadth(blocks: tuple[_Block, ...], domain: str | None) -> tuple[str, ...]:
    text = blocks[0].folded_text
    breadth: list[str] = []
    if domain == "vinfast" and re.search(
        r"\b(?:all|tat\s*ca|moi)\s+(?:vf\s*\d+\s+)?(?:variants?|phien\s*ban)\b", text
    ):
        breadth.append("vehicle.trim")
    if domain == "vinhomes" and re.search(
        r"\b(?:all|tat\s*ca|moi)\s+(?:loai\s*can|san\s*pham|units?)\b", text
    ):
        breadth.extend(("product.property_type", "product.bedrooms"))
    return tuple(breadth)


def _hierarchical_entity_refs(
    domain: str | None,
    project: EntityRef | None,
    location: dict[str, ConstraintValue],
    facet_evidence: tuple[ScopeFacetEvidence, ...],
) -> tuple[EntityRef, ...]:
    if domain != "vinhomes" or project is None:
        return ()
    refs: list[EntityRef] = []
    parent_id = project.canonical_id
    for entity_type in ("phase", "subdivision", "building", "unit"):
        raw_value = location.get(entity_type)
        if raw_value is None:
            continue
        canonical_id = f"{parent_id}_{entity_type}_{_slug(str(raw_value))}"
        facet = next(
            (item for item in facet_evidence if item.facet == f"location.{entity_type}"),
            None,
        )
        entity_evidence = (
            (
                EntityEvidence(
                    raw_text=facet.raw_text,
                    match_method=EntityMatchMethod.EXACT_CODE,
                    source=facet.source,
                    confidence=facet.confidence,
                    registry_version=project.registry_version,
                    span_start=facet.span_start,
                    span_end=facet.span_end,
                    source_id=facet.source_id,
                ),
            )
            if facet is not None
            else ()
        )
        refs.append(
            EntityRef(
                domain="vinhomes",
                entity_type=entity_type,
                canonical_id=canonical_id,
                canonical_name=str(raw_value),
                parent_id=parent_id,
                confidence=facet.confidence if facet is not None else 0.99,
                registry_version=project.registry_version,
                evidence=entity_evidence,
            )
        )
        parent_id = canonical_id
    return tuple(refs)


def _first_pattern(
    blocks: tuple[_Block, ...], pattern: re.Pattern[str]
) -> tuple[_Block, re.Match[str]] | None:
    for block in blocks:
        if match := pattern.search(block.folded_text):
            return block, match
    return None


def _facet_evidence(facet: str, block: _Block, start: int, end: int) -> ScopeFacetEvidence:
    # Folded offsets are exact for ASCII domain codes and approximate for
    # diacritic-bearing prose; inherited evidence intentionally has no direct span.
    direct = block.source is EntityEvidenceSource.CLAIM_TEXT
    raw_text = (
        block.raw_text[start:end] if end <= len(block.raw_text) else block.folded_text[start:end]
    )
    if not raw_text.strip():
        raw_text = block.folded_text[start:end]
    if not raw_text.strip():
        raw_text = facet
    return ScopeFacetEvidence(
        facet=facet,
        raw_text=raw_text,
        source=block.source,
        confidence=1.0 if direct else 0.98,
        span_start=start if direct else None,
        span_end=end if direct else None,
        source_id=block.source_id,
    )


def _domain_from_entities(entities: tuple[EntityRef, ...]) -> str | None:
    domains = {item.domain for item in entities if item.entity_type in {"project", "vehicle_model"}}
    return next(iter(domains)) if len(domains) == 1 else None


def _entity_of_type(entities: tuple[EntityRef, ...], entity_type: str) -> EntityRef | None:
    return next((item for item in entities if item.entity_type == entity_type), None)


def _scope_code(value: str) -> str:
    return value.strip().replace("-", ".").upper()


def _slug(value: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", _fold(value)))


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    plain = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9%/.-]+", " ", plain).split())


__all__ = [
    "ScopeTextContext",
    "load_or_resolve_business_context",
    "resolve_business_context",
]
