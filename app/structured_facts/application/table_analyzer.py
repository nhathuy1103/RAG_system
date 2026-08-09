"""Deterministic extraction of row-level facts from parsed tables.

The generic knowledge-quality detector samples chunks to find candidates.  A
business table needs a different contract: every data row is inspected, row
identity is independent from mutable values, and every extracted fact points
back to its exact source cell.  This module deliberately contains no fuzzy or
embedding based matching.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.pipeline.documents.domain.parsed import ParsedTable
from app.structured_facts.domain.models import (
    BusinessScope,
    ClaimDerivation,
    ClaimProvenance,
    ClaimQualifiers,
    ConstraintValue,
    NormalizedValue,
    ScalarValue,
    SourceAuthority,
    StructuredClaim,
    TemporalContext,
)

TABLE_FACT_EXTRACTOR_VERSION = "structured-table-v1"
MIN_TRUSTED_CLAIM_CONFIDENCE = 0.70


@dataclass(frozen=True, slots=True)
class TableAnalysis:
    """Complete deterministic result for one physical table."""

    document_id: str
    table_id: str
    claims: tuple[StructuredClaim, ...]
    row_count: int
    normalized_schema: tuple[str, ...]
    header_mapping: dict[str, str]
    confidence: float
    warnings: tuple[str, ...] = ()
    extractor_version: str = TABLE_FACT_EXTRACTOR_VERSION

    def to_payload(self) -> dict[str, object]:
        """Return a stable persistence payload without duplicating raw table text."""

        return {
            "document_id": self.document_id,
            "table_id": self.table_id,
            "extractor_version": self.extractor_version,
            "row_count": self.row_count,
            "normalized_schema": list(self.normalized_schema),
            "header_mapping": dict(sorted(self.header_mapping.items())),
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "claims": [claim.to_payload() for claim in self.claims],
        }


@dataclass(frozen=True, slots=True)
class HeaderSpec:
    index: int
    raw_name: str
    canonical_name: str
    kind: str
    predicate: str | None
    confidence: float
    stable_qualifiers: dict[str, ConstraintValue] = field(default_factory=dict)
    optional_qualifiers: dict[str, ConstraintValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _RowIdentity:
    subject_key: str
    scope: BusinessScope
    confidence: float
    used_columns: tuple[int, ...]
    fallback_used: bool


_EXACT_HEADER_ALIASES: dict[str, str] = {
    # Business/location identity.
    "chu dau tu": "developer",
    "developer": "developer",
    "ten du an": "project",
    "du an": "project",
    "project": "project",
    "project name": "project",
    "giai doan": "phase",
    "phase": "phase",
    "phan khu": "subdivision",
    "subdivision": "subdivision",
    "khu": "subdivision",
    "toa": "building",
    "toa nha": "building",
    "thap": "building",
    "block": "building",
    "building": "building",
    "ma can": "unit",
    "ma can ho": "unit",
    "can ho": "unit",
    "so can": "unit",
    "unit": "unit",
    "unit code": "unit",
    "apartment code": "unit",
    # Product identity/dimensions.
    "loai can": "property_type",
    "loai san pham": "property_type",
    "property type": "property_type",
    "so phong ngu": "bedrooms",
    "phong ngu": "bedrooms",
    "pn": "bedrooms",
    "bedrooms": "bedrooms",
    "ma san pham": "product_variant",
    "product variant": "product_variant",
    "bien the": "product_variant",
    "ma": "code",
    "ma hang": "code",
    "sku": "code",
    "code": "code",
    "id": "id",
    "ten": "name",
    "name": "name",
    "mo ta": "description",
    "description": "description",
    "tang": "floor",
    "floor": "floor",
    "huong": "direction",
    "direction": "direction",
    "mat bang": "layout",
    "layout": "layout",
    # Price/value aliases.
    "gia ny": "list_price",
    "gia niem yet": "list_price",
    "list price": "list_price",
    "gia sau ck": "discounted_price",
    "gia sau chiet khau": "discounted_price",
    "discounted price": "discounted_price",
    "net price": "discounted_price",
    "gia ban": "sale_price",
    "tong gia": "sale_price",
    "gia can": "sale_price",
    "sale price": "sale_price",
    "don gia": "price_per_sqm",
    "gia m2": "price_per_sqm",
    "gia m 2": "price_per_sqm",
    "price per sqm": "price_per_sqm",
    "unit price": "price_per_sqm",
    # Area and commercial qualifiers.
    "dien tich": "area",
    "dt": "area",
    "area": "area",
    "dien tich thong thuy": "carpet_area",
    "dt thong thuy": "carpet_area",
    "carpet area": "carpet_area",
    "net area": "carpet_area",
    "dien tich tim tuong": "gross_area",
    "dt tim tuong": "gross_area",
    "gross area": "gross_area",
    "built up area": "gross_area",
    "loai gia": "price_type",
    "price type": "price_type",
    "co so gia": "price_basis",
    "price basis": "price_basis",
    "vat": "vat_included",
    "thue vat": "vat_included",
    "phi bao tri": "maintenance_fee_included",
    "maintenance fee": "maintenance_fee_included",
    "phuong an thanh toan": "payment_plan",
    "tien do thanh toan": "payment_plan",
    "payment plan": "payment_plan",
    "chuong trinh chiet khau": "discount_program",
    "discount program": "discount_program",
    "tien te": "currency",
    "currency": "currency",
    # Time columns.
    "ngay hieu luc": "effective_date",
    "effective date": "effective_date",
    "hieu luc tu": "effective_from",
    "tu ngay": "effective_from",
    "valid from": "effective_from",
    "effective from": "effective_from",
    "hieu luc den": "effective_to",
    "den ngay": "effective_to",
    "valid to": "effective_to",
    "effective to": "effective_to",
    "ngay cong bo": "publication_time",
    "publication date": "publication_time",
    "publication time": "publication_time",
    "ngay quan sat": "observed_at",
    "observed at": "observed_at",
    "ngay nap": "ingested_at",
    "ingested at": "ingested_at",
    # Generic values.
    "so luong": "quantity",
    "quantity": "quantity",
    "trang thai": "status",
    "status": "status",
}

_SCOPE_FIELDS = {
    "developer",
    "project",
    "phase",
    "subdivision",
    "building",
    "unit",
    "property_type",
    "bedrooms",
    "product_variant",
}
_EXPLICIT_IDENTITY_FIELDS = {"id", "code", "name"}
_QUALIFIER_FIELDS = {
    "price_type",
    "price_basis",
    "vat_included",
    "maintenance_fee_included",
    "payment_plan",
    "discount_program",
    "currency",
}
_TEMPORAL_FIELDS = {
    "effective_date",
    "effective_from",
    "effective_to",
    "publication_time",
    "observed_at",
    "ingested_at",
}
_PRICE_FIELDS = {"list_price", "discounted_price", "sale_price", "price_per_sqm"}
_AREA_FIELDS = {"area", "carpet_area", "gross_area"}
_NON_VALUE_FIELDS = _SCOPE_FIELDS | _EXPLICIT_IDENTITY_FIELDS | _QUALIFIER_FIELDS | _TEMPORAL_FIELDS


def analyze_table(
    *,
    document_id: str,
    table: ParsedTable,
    base_scope: BusinessScope | None = None,
    extractor_version: str = TABLE_FACT_EXTRACTOR_VERSION,
) -> TableAnalysis:
    """Extract every row-level value claim from ``table``.

    ``ParsedTable.rows`` conventionally includes its header as row zero, but a
    few adapters provide a detached header.  Header removal is therefore based
    on equality, never on position alone.
    """

    if not document_id.strip():
        raise ValueError("document_id is required")

    headers, data_rows, first_data_row_index, warnings = _split_header_and_rows(table)
    specs = tuple(_header_spec(index, name) for index, name in enumerate(headers))
    normalized_schema = tuple(spec.canonical_name for spec in specs)
    duplicate_headers = sorted(
        name for name in set(normalized_schema) if normalized_schema.count(name) > 1
    )
    if duplicate_headers:
        warnings.append("duplicate_semantic_headers:" + ",".join(duplicate_headers))

    metadata = dict(table.metadata or {})
    owner_id = _optional_text(metadata.get("owner_id"))
    notebook_id = _optional_text(metadata.get("notebook_id"))
    source_authority = _source_authority(metadata)
    table_confidence = _bounded_confidence(table.confidence, default=1.0)
    base = base_scope or BusinessScope()
    claims: list[StructuredClaim] = []
    seen_subjects: dict[str, int] = {}

    for offset, raw_row in enumerate(data_rows):
        physical_row_index = first_data_row_index + offset
        row = _padded_row(raw_row, len(specs))
        if not any(cell.strip() for cell in row):
            continue
        values_by_field = _values_by_field(specs, row)
        identity = _row_identity(
            table=table,
            physical_row_index=physical_row_index,
            specs=specs,
            row=row,
            values_by_field=values_by_field,
            base_scope=base,
        )
        seen_subjects[identity.subject_key] = seen_subjects.get(identity.subject_key, 0) + 1
        if identity.fallback_used:
            warnings.append(f"fallback_row_identity:{physical_row_index}")

        row_temporal, temporal_confidence, temporal_warning = _temporal_context(
            metadata, values_by_field
        )
        if temporal_warning is not None:
            warnings.append(f"{temporal_warning}:{physical_row_index}")
        row_commercial = _row_commercial_qualifiers(values_by_field)
        row_claim_start = len(claims)
        for spec in specs:
            if spec.canonical_name in _NON_VALUE_FIELDS:
                continue
            raw_value = row[spec.index].strip()
            if not raw_value:
                continue
            normalized_value, value_confidence, value_warning = _normalize_value(spec, raw_value)
            if spec.canonical_name in _PRICE_FIELDS:
                currency_override = _canonical_currency(values_by_field.get("currency"))
                basis_override = _canonical_price_basis(values_by_field.get("price_basis"))
                if currency_override is not None:
                    normalized_value = replace(normalized_value, currency=currency_override)
                if basis_override is not None:
                    normalized_value = replace(normalized_value, basis=basis_override)
            if value_warning is not None:
                warnings.append(f"{value_warning}:{physical_row_index}:{spec.index}")

            stable = dict(spec.stable_qualifiers)
            optional = dict(spec.optional_qualifiers)
            if spec.canonical_name in _PRICE_FIELDS:
                stable.update(
                    {
                        key: value
                        for key, value in row_commercial.items()
                        if key in {"price_type", "price_basis", "payment_plan", "discount_program"}
                        and value is not None
                    }
                )
                optional.update(
                    {
                        key: value
                        for key, value in row_commercial.items()
                        if key in {"vat_included", "maintenance_fee_included"} and value is not None
                    }
                )
            qualifiers = ClaimQualifiers.from_mappings(stable=stable, optional=optional)
            provenance = _claim_provenance(
                document_id=document_id,
                table=table,
                row_index=physical_row_index,
                data_row_ordinal=offset,
                spec=spec,
            )
            cell_confidence = _cell_confidence(table, physical_row_index, spec.index)
            extraction_confidence = min(
                table_confidence,
                spec.confidence,
                identity.confidence,
                value_confidence,
                cell_confidence,
                temporal_confidence,
            )
            predicate = spec.predicate or spec.canonical_name
            claim_id = _claim_id(
                document_id=document_id,
                table_id=table.table_id,
                row_index=physical_row_index,
                column_index=spec.index,
                subject_key=identity.subject_key,
                predicate=predicate,
                qualifier_identity=qualifiers.stable_identity(),
            )
            claims.append(
                StructuredClaim(
                    id=claim_id,
                    owner_id=owner_id,
                    notebook_id=notebook_id,
                    document_id=document_id,
                    subject_key=identity.subject_key,
                    predicate=predicate,
                    value=normalized_value,
                    scope=identity.scope,
                    qualifiers=qualifiers,
                    temporal=row_temporal,
                    provenance=provenance,
                    extraction_confidence=extraction_confidence,
                    extractor_version=extractor_version,
                    authority=source_authority,
                )
            )
        derived_claim = _derive_total_price_claim(
            claims=tuple(claims[row_claim_start:]),
            document_id=document_id,
            table_id=table.table_id,
            physical_row_index=physical_row_index,
            extractor_version=extractor_version,
        )
        if derived_claim is not None:
            claims.append(derived_claim)
            warnings.append(f"derived_total_price:{physical_row_index}")

    duplicate_subjects = sorted(key for key, count in seen_subjects.items() if count > 1)
    if duplicate_subjects:
        warnings.append(f"duplicate_row_identities:{len(duplicate_subjects)}")
    unique_warnings = tuple(dict.fromkeys(warnings))
    confidence = (
        min(table_confidence, sum(claim.extraction_confidence for claim in claims) / len(claims))
        if claims
        else 0.0
    )
    return TableAnalysis(
        document_id=document_id,
        table_id=table.table_id,
        claims=tuple(claims),
        row_count=sum(1 for row in data_rows if any(cell.strip() for cell in row)),
        normalized_schema=normalized_schema,
        header_mapping={spec.raw_name: spec.canonical_name for spec in specs},
        confidence=confidence,
        warnings=unique_warnings,
        extractor_version=extractor_version,
    )


def normalize_header(value: str) -> str:
    """Map a generic or real-estate header to a stable semantic name."""

    folded = _fold(value)
    if not folded:
        return "unknown"
    exact = _EXACT_HEADER_ALIASES.get(folded)
    if exact is not None:
        return exact

    # Time/qualifier columns must be recognized before broad words such as
    # ``gia`` and ``phi``.
    if "hieu luc" in folded or folded.startswith("valid "):
        if any(token in folded for token in (" den", "to", "end", "expiry")):
            return "effective_to"
        if any(token in folded for token in (" tu", "from", "start")):
            return "effective_from"
        return "effective_date"
    if any(token in folded for token in ("ngay cong bo", "publication")):
        return "publication_time"
    if "vat" in folded and not _looks_like_price(folded):
        return "vat_included"
    if ("bao tri" in folded or "maintenance fee" in folded) and not _looks_like_price(folded):
        return "maintenance_fee_included"
    if "payment plan" in folded or "thanh toan" in folded and "gia" not in folded:
        return "payment_plan"
    if "discount program" in folded or "chuong trinh" in folded and "chiet khau" in folded:
        return "discount_program"

    if _looks_like_price(folded):
        if _is_per_square_metre(folded):
            return "price_per_sqm"
        if any(token in folded for token in ("niem yet", "gia ny", "list price")):
            return "list_price"
        if any(token in folded for token in ("sau chiet khau", "sau ck", "discounted", "net")):
            return "discounted_price"
        return "sale_price"

    if any(token in folded for token in ("dien tich", " area", "area")) or folded.startswith("dt "):
        if any(token in folded for token in ("thong thuy", "carpet", "net area")):
            return "carpet_area"
        if any(token in folded for token in ("tim tuong", "gross", "built up")):
            return "gross_area"
        return "area"

    for canonical, tokens in (
        ("developer", ("chu dau tu", "developer")),
        ("project", ("du an", "project")),
        ("subdivision", ("phan khu", "subdivision")),
        ("building", ("toa", "thap", "building", "block")),
        ("unit", ("ma can", "can ho", "unit", "apartment")),
        ("property_type", ("loai can", "loai san pham", "property type")),
        ("bedrooms", ("phong ngu", "bedroom")),
        ("quantity", ("so luong", "quantity")),
    ):
        if any(token in folded for token in tokens):
            return canonical

    slug = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    return f"field_{slug}" if slug else "unknown"


def normalize_money(value: str, *, header: str = "") -> tuple[NormalizedValue, float]:
    """Normalize common Vietnamese/English money notation without floats."""

    folded_value = _fold(value)
    folded_header = _fold(header)
    magnitude, explicit_magnitude = _money_magnitude(folded_value, folded_header)
    number = _parse_decimal(
        value,
        prefer_decimal=explicit_magnitude,
    )
    currency = _currency(folded_value, folded_header)
    confidence = 1.0
    if number is None:
        return (
            NormalizedValue(
                value=_fold(value),
                unit="money",
                currency=currency,
                basis="per_sqm" if _is_per_square_metre(folded_header) else "total_unit",
                raw_value=value,
            ),
            0.35,
        )
    if not explicit_magnitude and abs(number) < Decimal("100000"):
        # A bare ``4.5`` in a price column may mean VND, million or billion.
        confidence = 0.55
    normalized = number * magnitude
    return (
        NormalizedValue(
            value=_decimal_text(normalized),
            unit="money",
            currency=currency,
            basis=(
                "per_sqm"
                if _is_per_square_metre(folded_value) or _is_per_square_metre(folded_header)
                else "total_unit"
            ),
            raw_value=value,
        ),
        confidence,
    )


def normalize_area(value: str, *, header: str = "") -> tuple[NormalizedValue, float]:
    """Normalize square-metre area while retaining the raw cell."""

    number = _parse_decimal(value)
    folded = _fold(f"{header} {value}")
    area_type = "carpet" if any(token in folded for token in ("thong thuy", "carpet")) else None
    if any(token in folded for token in ("tim tuong", "gross", "built up")):
        area_type = "gross"
    if number is None:
        return (
            NormalizedValue(value=_fold(value), unit="m2", basis=area_type, raw_value=value),
            0.35,
        )
    explicit_unit = bool(re.search(r"(?:m\s*(?:2|\u00b2)|sqm|square\s*met(?:er|re))", folded))
    return (
        NormalizedValue(value=_decimal_text(number), unit="m2", basis=area_type, raw_value=value),
        1.0 if explicit_unit else 0.9,
    )


def _header_spec(index: int, raw_name: str) -> HeaderSpec:
    canonical = normalize_header(raw_name)
    folded = _fold(raw_name)
    confidence = 0.98 if not canonical.startswith("field_") and canonical != "unknown" else 0.72
    kind = "generic"
    predicate: str | None = canonical
    stable: dict[str, ConstraintValue] = {}
    optional: dict[str, ConstraintValue] = {}
    if canonical in _SCOPE_FIELDS | _EXPLICIT_IDENTITY_FIELDS:
        kind, predicate = "identity", None
    elif canonical in _QUALIFIER_FIELDS:
        kind, predicate = "qualifier", None
    elif canonical in _TEMPORAL_FIELDS:
        kind, predicate = "temporal", None
    elif canonical in _PRICE_FIELDS:
        kind, predicate = "money", "sale_price"
        stable["price_type"] = {
            "list_price": "list_price",
            "discounted_price": "discounted_price",
            "price_per_sqm": "sale_price",
            "sale_price": "sale_price",
        }[canonical]
        stable["price_basis"] = "per_sqm" if canonical == "price_per_sqm" else "total_unit"
        if any(token in folded for token in ("da vat", "bao gom vat", "incl vat", "including vat")):
            optional["vat_included"] = True
        elif any(
            token in folded for token in ("chua vat", "khong vat", "excl vat", "excluding vat")
        ):
            optional["vat_included"] = False
        if any(token in folded for token in ("thanh toan som", "tt som", "early payment")):
            stable["payment_plan"] = "early_payment"
        if any(
            token in folded
            for token in ("bao gom phi bao tri", "da phi bao tri", "incl maintenance")
        ):
            optional["maintenance_fee_included"] = True
        elif any(
            token in folded
            for token in ("chua phi bao tri", "khong phi bao tri", "excl maintenance")
        ):
            optional["maintenance_fee_included"] = False
    elif canonical in _AREA_FIELDS:
        kind, predicate = "area", "property_area"
        stable["area_type"] = {
            "carpet_area": "carpet",
            "gross_area": "gross",
            "area": "unspecified",
        }[canonical]
    elif canonical == "quantity":
        kind, predicate = "number", "quantity"
    return HeaderSpec(
        index=index,
        raw_name=raw_name,
        canonical_name=canonical,
        kind=kind,
        predicate=predicate,
        confidence=confidence,
        stable_qualifiers=stable,
        optional_qualifiers=optional,
    )


def _split_header_and_rows(
    table: ParsedTable,
) -> tuple[list[str], list[list[str]], int, list[str]]:
    warnings = list(table.warnings or [])
    rows = [list(row) for row in table.rows]
    if table.header:
        headers = list(table.header)
        if rows and _rows_equal(headers, rows[0]):
            return headers, rows[1:], 1, warnings
        return headers, rows, 0, warnings
    if rows:
        warnings.append("inferred_first_row_as_header")
        return list(rows[0]), rows[1:], 1, warnings
    warnings.append("missing_table_header")
    width = max(0, int(table.columns or 0))
    return [f"column_{index + 1}" for index in range(width)], [], 0, warnings


def _row_identity(
    *,
    table: ParsedTable,
    physical_row_index: int,
    specs: tuple[HeaderSpec, ...],
    row: list[str],
    values_by_field: dict[str, str],
    base_scope: BusinessScope,
) -> _RowIdentity:
    location = replace(
        base_scope.location,
        developer=_identity_value(values_by_field.get("developer"))
        or base_scope.location.developer,
        project=_identity_value(values_by_field.get("project")) or base_scope.location.project,
        phase=_identity_value(values_by_field.get("phase")) or base_scope.location.phase,
        subdivision=_identity_value(values_by_field.get("subdivision"))
        or base_scope.location.subdivision,
        building=_identity_value(values_by_field.get("building")) or base_scope.location.building,
        unit=_identity_value(values_by_field.get("unit")) or base_scope.location.unit,
    )
    product = replace(
        base_scope.product,
        property_type=_identity_value(values_by_field.get("property_type"))
        or base_scope.product.property_type,
        bedrooms=_normalized_bedrooms(values_by_field.get("bedrooms"))
        if values_by_field.get("bedrooms")
        else base_scope.product.bedrooms,
        area_type=base_scope.product.area_type,
        product_variant=_identity_value(values_by_field.get("product_variant"))
        or base_scope.product.product_variant,
    )
    scope = replace(base_scope, location=location, product=product)

    pairs: list[tuple[str, str]] = []
    used: list[int] = []
    for field_name in ("project", "phase", "subdivision", "building", "unit"):
        value = getattr(location, field_name)
        if value:
            pairs.append((field_name, str(value)))
            used.extend(spec.index for spec in specs if spec.canonical_name == field_name)

    # A project alone is not a row identity.  Append explicit row identifiers
    # and stable product dimensions before considering a composite fallback.
    for field_name in ("id", "code", "name", "product_variant"):
        value = _identity_value(values_by_field.get(field_name))
        if value and (not location.unit or field_name == "product_variant"):
            pairs.append((field_name, value))
            used.extend(spec.index for spec in specs if spec.canonical_name == field_name)

    has_specific_location = bool(location.unit)
    if pairs and (has_specific_location or any(key in {"id", "code", "name"} for key, _ in pairs)):
        confidence = 1.0 if location.unit else 0.9
        return _RowIdentity(
            subject_key="|".join(f"{key}={value}" for key, value in pairs),
            scope=scope,
            confidence=confidence,
            used_columns=tuple(sorted(set(used))),
            fallback_used=False,
        )

    fallback_pairs: list[tuple[str, str]] = []
    fallback_columns: list[int] = []
    preferred = {
        "property_type",
        "bedrooms",
        "product_variant",
        "floor",
        "direction",
        "layout",
        "area",
        "carpet_area",
        "gross_area",
    }
    for spec in specs:
        if spec.canonical_name not in preferred:
            continue
        value = row[spec.index].strip()
        if value:
            normalized = _identity_value(value)
            if normalized:
                fallback_pairs.append((spec.canonical_name, normalized))
                fallback_columns.append(spec.index)
    if pairs or fallback_pairs:
        combined = pairs + fallback_pairs
        return _RowIdentity(
            subject_key="|".join(f"{key}={value}" for key, value in combined),
            scope=scope,
            confidence=0.76 if len(combined) >= 2 else 0.66,
            used_columns=tuple(sorted(set(used + fallback_columns))),
            fallback_used=True,
        )

    # Positional identity preserves provenance but intentionally receives low
    # confidence so it can never drive an automatic update/conflict decision.
    return _RowIdentity(
        subject_key=f"unresolved:{table.table_id}:row:{physical_row_index}",
        scope=scope,
        confidence=0.35,
        used_columns=(),
        fallback_used=True,
    )


def _normalize_value(spec: HeaderSpec, raw_value: str) -> tuple[NormalizedValue, float, str | None]:
    if spec.kind == "money":
        normalized, confidence = normalize_money(raw_value, header=spec.raw_name)
        return normalized, confidence, "ambiguous_money_value" if confidence < 0.7 else None
    if spec.kind == "area":
        normalized, confidence = normalize_area(raw_value, header=spec.raw_name)
        return normalized, confidence, "ambiguous_area_value" if confidence < 0.7 else None
    if spec.kind == "number":
        number = _parse_decimal(raw_value)
        if number is None:
            return (
                NormalizedValue(value=_fold(raw_value), raw_value=raw_value),
                0.4,
                "invalid_numeric_value",
            )
        return (
            NormalizedValue(value=_decimal_text(number), unit="count", raw_value=raw_value),
            0.95,
            None,
        )
    return NormalizedValue(value=_normalized_text(raw_value), raw_value=raw_value), 0.85, None


def _row_commercial_qualifiers(values: dict[str, str]) -> dict[str, ConstraintValue | None]:
    return {
        "price_type": _canonical_price_type(values.get("price_type")),
        "price_basis": _canonical_price_basis(values.get("price_basis")),
        "payment_plan": _identity_value(values.get("payment_plan")),
        "discount_program": _identity_value(values.get("discount_program")),
        "vat_included": _optional_boolean(values.get("vat_included")),
        "maintenance_fee_included": _optional_boolean(values.get("maintenance_fee_included")),
    }


def _derive_total_price_claim(
    *,
    claims: tuple[StructuredClaim, ...],
    document_id: str,
    table_id: str,
    physical_row_index: int,
    extractor_version: str,
) -> StructuredClaim | None:
    per_sqm = [
        claim
        for claim in claims
        if claim.predicate == "sale_price" and claim.value.basis == "per_sqm"
    ]
    totals = [
        claim
        for claim in claims
        if claim.predicate == "sale_price" and claim.value.basis == "total_unit"
    ]
    areas = [claim for claim in claims if claim.predicate == "property_area"]
    if len(per_sqm) != 1 or totals or not areas:
        return None
    preferred_areas = [claim for claim in areas if claim.value.basis == "carpet"]
    if len(preferred_areas) == 1:
        area = preferred_areas[0]
    elif len(areas) == 1:
        area = areas[0]
    else:
        return None
    price = per_sqm[0]
    price_number = _decimal_from_value(price.value.value)
    area_number = _decimal_from_value(area.value.value)
    if price_number is None or area_number is None or price.id is None or area.id is None:
        return None

    stable_qualifiers = dict(price.qualifiers.stable)
    stable_qualifiers["price_basis"] = "total_unit"
    qualifiers = ClaimQualifiers.from_mappings(
        stable=stable_qualifiers,
        optional=dict(price.qualifiers.optional),
    )
    total_value = price_number * area_number
    claim_id = _claim_id(
        document_id=document_id,
        table_id=table_id,
        row_index=physical_row_index,
        column_index=-1,
        subject_key=price.subject_key,
        predicate="sale_price",
        qualifier_identity=qualifiers.stable_identity(),
    )
    return StructuredClaim(
        id=claim_id,
        owner_id=price.owner_id,
        notebook_id=price.notebook_id,
        document_id=document_id,
        subject_key=price.subject_key,
        predicate="sale_price",
        value=NormalizedValue(
            value=_decimal_text(total_value),
            unit="money",
            currency=price.value.currency,
            basis="total_unit",
            raw_value=f"derived({price.value.raw_value} * {area.value.raw_value})",
        ),
        scope=price.scope,
        qualifiers=qualifiers,
        temporal=price.temporal,
        provenance=price.provenance,
        extraction_confidence=min(price.extraction_confidence, area.extraction_confidence) * 0.95,
        extractor_version=extractor_version,
        derivation=ClaimDerivation(
            formula="price_per_sqm * property_area",
            input_claim_ids=(price.id, area.id),
            absolute_tolerance=Decimal("10000000"),
            relative_tolerance=Decimal("0.002"),
        ),
        authority=price.authority,
    )


def _source_authority(metadata: dict[str, object]) -> SourceAuthority:
    raw_level = _optional_int(metadata.get("authority_level"))
    authority_level = raw_level if raw_level is not None and 0 <= raw_level <= 100 else None
    raw_officiality = metadata.get("officiality")
    officiality = (
        raw_officiality if isinstance(raw_officiality, bool) else _optional_text(raw_officiality)
    )
    raw_metadata = metadata.get("authority_metadata")
    authority_metadata: dict[str, ScalarValue] = {}
    if isinstance(raw_metadata, dict):
        for raw_key, raw_value in raw_metadata.items():
            if isinstance(raw_value, str | int | float | bool | Decimal | datetime):
                authority_metadata[str(raw_key)] = raw_value
    return SourceAuthority.from_mapping(
        source_type=_optional_text(metadata.get("source_type")),
        publisher=_optional_text(metadata.get("publisher")),
        approval_status=_optional_text(metadata.get("approval_status")),
        officiality=officiality,
        authority_level=authority_level,
        metadata=authority_metadata,
    )


def _temporal_context(
    metadata: dict[str, object], values: dict[str, str]
) -> tuple[TemporalContext, float, str | None]:
    publication = _parse_datetime(
        values.get("publication_time") or metadata.get("publication_time")
    )
    observed = _parse_datetime(values.get("observed_at") or metadata.get("observed_at"))
    ingested = _parse_datetime(values.get("ingested_at") or metadata.get("ingested_at"))
    raw_from = values.get("effective_from") or metadata.get("effective_from")
    raw_to = values.get("effective_to") or metadata.get("effective_to")
    effective_from = _parse_temporal_range(raw_from)[0] if raw_from is not None else None
    effective_to = _parse_temporal_range(raw_to)[1] if raw_to is not None else None
    point_value = values.get("effective_date") or metadata.get("effective_date")
    if point_value and effective_from is None and effective_to is None:
        effective_from, effective_to = _parse_temporal_range(point_value)
    explicit_effective_value = raw_from is not None or raw_to is not None or point_value is not None
    invalid_bound = (raw_from is not None and effective_from is None) or (
        raw_to is not None and effective_to is None
    )
    if invalid_bound or (
        explicit_effective_value and effective_from is None and effective_to is None
    ):
        return (
            TemporalContext(
                publication_time=publication,
                observed_at=observed,
                ingested_at=ingested,
            ),
            0.4,
            "invalid_effective_interval",
        )
    try:
        context = TemporalContext(
            publication_time=publication,
            effective_from=effective_from,
            effective_to=effective_to,
            observed_at=observed,
            ingested_at=ingested,
        )
    except ValueError:
        return (
            TemporalContext(
                publication_time=publication,
                observed_at=observed,
                ingested_at=ingested,
            ),
            0.4,
            "invalid_effective_interval",
        )
    return context, 1.0, None


def _claim_provenance(
    *,
    document_id: str,
    table: ParsedTable,
    row_index: int,
    data_row_ordinal: int,
    spec: HeaderSpec,
) -> ClaimProvenance:
    cell = _find_cell(table, row_index, spec.index)
    cell_id = _optional_text(cell.get("cell_id") or cell.get("id")) if cell else None
    page_number: int | None = None
    if cell:
        page_number = _optional_int(cell.get("page_number") or cell.get("page"))
    if page_number is None:
        page_number = _optional_int(table.metadata.get("page_number"))
    if page_number is None:
        match = re.search(r"(?:page|trang)\s*[:#-]?\s*(\d+)", table.location, re.IGNORECASE)
        page_number = int(match.group(1)) if match else None
    sheet_match = re.search(r"(?:sheet)\s*:\s*([^:]+)", table.location, re.IGNORECASE)
    return ClaimProvenance(
        document_id=document_id,
        table_id=table.table_id,
        row_index=row_index,
        data_row_ordinal=data_row_ordinal,
        column_name=spec.raw_name,
        cell_id=cell_id or f"{table.table_id}:r{row_index}:c{spec.index}",
        page_number=page_number,
        source_span=None,
        sheet_name=sheet_match.group(1).strip() if sheet_match else None,
    )


def _cell_confidence(table: ParsedTable, row_index: int, column_index: int) -> float:
    cell = _find_cell(table, row_index, column_index)
    if cell is None:
        return 1.0
    return _bounded_confidence(cell.get("confidence"), default=1.0)


def _find_cell(table: ParsedTable, row_index: int, column_index: int) -> dict[str, object] | None:
    for cell in table.cells or []:
        candidate_row = _optional_int(cell.get("row_index", cell.get("row")))
        candidate_column = _optional_int(cell.get("column_index", cell.get("column")))
        if candidate_row == row_index and candidate_column == column_index:
            return cell
    return None


def _values_by_field(specs: tuple[HeaderSpec, ...], row: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for spec in specs:
        value = row[spec.index].strip()
        if value and spec.canonical_name not in result:
            result[spec.canonical_name] = value
    return result


def _claim_id(
    *,
    document_id: str,
    table_id: str,
    row_index: int,
    column_index: int,
    subject_key: str,
    predicate: str,
    qualifier_identity: object,
) -> str:
    material = "\x1f".join(
        (
            document_id,
            table_id,
            str(row_index),
            str(column_index),
            subject_key,
            predicate,
            repr(qualifier_identity),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _rows_equal(left: list[str], right: list[str]) -> bool:
    width = max(len(left), len(right))
    return _padded_row(left, width) == _padded_row(right, width)


def _padded_row(row: list[str], width: int) -> list[str]:
    return [str(row[index] if index < len(row) else "").strip() for index in range(width)]


def _looks_like_price(folded: str) -> bool:
    return any(
        token in folded
        for token in (
            "gia",
            "price",
            "don gia",
            "vnd",
            "usd",
            "dong",
        )
    )


def _is_per_square_metre(folded: str) -> bool:
    compact = folded.replace(" ", "")
    return any(
        token in compact
        for token in (
            "/m2",
            "m2",
            "/m\u00b2",
            "m\u00b2",
            "/sqm",
            "persqm",
            "squaremetre",
            "squaremeter",
        )
    )


def _money_magnitude(value: str, header: str) -> tuple[Decimal, bool]:
    combined = f"{value} {header}"
    for tokens, factor in (
        (("ty", "billion", " bn"), Decimal("1000000000")),
        (("trieu", "million", " mn"), Decimal("1000000")),
        (("nghin", "ngan", "thousand"), Decimal("1000")),
    ):
        if any(
            re.search(rf"(?:^|\s){re.escape(token.strip())}(?:\s|/|$)", combined)
            for token in tokens
        ):
            return factor, True
    return Decimal("1"), False


def _currency(value: str, header: str) -> str:
    combined = f"{value} {header}"
    if "usd" in combined or "$" in combined:
        return "USD"
    if "eur" in combined or "€" in combined:
        return "EUR"
    return "VND"


def _parse_decimal(value: str, *, prefer_decimal: bool = False) -> Decimal | None:
    match = re.search(r"[-+]?\d[\d\s.,]*", str(value))
    if match is None:
        return None
    raw = re.sub(r"\s+", "", match.group(0))
    sign = ""
    if raw[:1] in {"-", "+"}:
        sign, raw = raw[0], raw[1:]
    if not raw:
        return None
    comma_count, dot_count = raw.count(","), raw.count(".")
    if comma_count and dot_count:
        decimal_separator = "," if raw.rfind(",") > raw.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        raw = raw.replace(grouping_separator, "").replace(decimal_separator, ".")
    elif comma_count or dot_count:
        separator = "," if comma_count else "."
        pieces = raw.split(separator)
        grouped = not prefer_decimal and (
            (len(pieces) > 2 and all(len(piece) == 3 for piece in pieces[1:]))
            or (
                len(pieces) == 2
                and len(pieces[1]) == 3
                and pieces[0] not in {"0", ""}
                and len(pieces[0]) <= 3
            )
        )
        raw = "".join(pieces) if grouped else ".".join(pieces)
    try:
        return Decimal(sign + raw)
    except InvalidOperation:
        return None


def _decimal_text(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _decimal_from_value(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_temporal_range(value: object) -> tuple[datetime | None, datetime | None]:
    text = _optional_text(value)
    if text is None:
        return None, None
    month_match = re.fullmatch(r"\s*(\d{1,2})[/-](\d{4})\s*", text)
    if month_match:
        month, year = int(month_match.group(1)), int(month_match.group(2))
        if not 1 <= month <= 12:
            return None, None
        start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            next_month = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            next_month = datetime(year, month + 1, 1, tzinfo=UTC)
        return start, next_month - timedelta(microseconds=1)
    point = _parse_datetime(text)
    return (point, point) if point is not None else (None, None)


def _parse_datetime(value: object) -> datetime | None:
    text = _optional_text(value)
    if text is None:
        return None
    normalized = text.strip()
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(normalized, pattern).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _canonical_price_type(value: str | None) -> str | None:
    folded = _identity_value(value)
    if folded is None:
        return None
    if any(token in folded for token in ("niem yet", "list")):
        return "list_price"
    if any(token in folded for token in ("chiet khau", "sau ck", "discount", "net")):
        return "discounted_price"
    if any(token in folded for token in ("chao ban", "asking", "offer")):
        return "offer_price"
    if any(token in folded for token in ("giao dich", "transaction")):
        return "transaction_price"
    return folded


def _canonical_price_basis(value: str | None) -> str | None:
    folded = _identity_value(value)
    if folded is None:
        return None
    if _is_per_square_metre(folded):
        return "per_sqm"
    if any(token in folded for token in ("tong", "toan can", "total", "unit")):
        return "total_unit"
    return folded


def _canonical_currency(value: str | None) -> str | None:
    folded = _identity_value(value)
    if folded is None:
        return None
    if any(token in folded for token in ("usd", "us dollar", "$")):
        return "USD"
    if any(token in folded for token in ("eur", "euro")):
        return "EUR"
    if any(token in folded for token in ("vnd", "dong", "vn d")):
        return "VND"
    return None


def _optional_boolean(value: str | None) -> bool | None:
    folded = _identity_value(value)
    if folded is None:
        return None
    false_tokens = ("khong", "chua", "no", "false", "excluded", "excl")
    true_tokens = ("co", "da", "yes", "true", "included", "incl", "bao gom")
    if any(token in folded for token in false_tokens):
        return False
    if any(token in folded for token in true_tokens):
        return True
    return None


def _normalized_bedrooms(value: str | None) -> int | str | None:
    if value is None:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else _identity_value(value)


def _identity_value(value: object) -> str | None:
    text = _optional_text(value)
    return _fold(text) if text is not None else None


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split())


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold()).replace("\u0111", "d")
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9$\u20ac\u00b2/]+", " ", without_marks).split())


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, str | int | float | Decimal):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bounded_confidence(value: object, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        return default
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


__all__ = [
    "MIN_TRUSTED_CLAIM_CONFIDENCE",
    "TABLE_FACT_EXTRACTOR_VERSION",
    "HeaderSpec",
    "TableAnalysis",
    "analyze_table",
    "normalize_area",
    "normalize_header",
    "normalize_money",
]
