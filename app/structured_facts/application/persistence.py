"""Map unified table/prose claims to migration-16 persistence payloads.

The domain models intentionally serialize as nested, review-friendly objects.
Migration 16 uses an indexed flat schema.  This module is the single explicit
anti-corruption layer between those contracts; callers must not pass raw
``StructuredClaim.to_payload()`` objects directly to the RPC.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5

from app.pipeline.documents.domain.parsed import ParsedTable
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.structured_facts.application.claim_extraction import canonicalize_table_claims
from app.structured_facts.application.table_analyzer import TableAnalysis
from app.structured_facts.domain.models import (
    ClaimProvenance,
    NormalizedValue,
    SourceAuthority,
    StructuredClaim,
    TemporalContext,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class StructuredFactPersistenceBatch:
    """RPC-ready snapshots and claims for one document extraction."""

    table_snapshots: tuple[dict[str, object], ...]
    claims: tuple[dict[str, object], ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "table_snapshots": [dict(item) for item in self.table_snapshots],
            "claims": [dict(item) for item in self.claims],
        }


def build_structured_fact_persistence_batch(
    *,
    analyses: Sequence[TableAnalysis],
    tables: Sequence[ParsedTable],
    embedded_chunks: Sequence[EmbeddedChunk],
    template_fingerprint: str | Mapping[str, str] | None = None,
    prose_claims: Sequence[StructuredClaim] = (),
) -> StructuredFactPersistenceBatch:
    """Build deterministic migration-16 payloads without storing raw sources.

    A claim citation is emitted only when its table source block and data-row
    ordinal can be proven to fall inside an embedded chunk.  An unproven
    citation remains null; no positional or nearest-chunk fallback is used.
    """

    table_by_id = _unique_tables(tables)
    document_ids = {
        *(analysis.document_id.strip() for analysis in analyses),
        *(claim.document_id.strip() for claim in prose_claims),
    }
    if "" in document_ids:
        raise ValueError("analysis document_id cannot be blank")
    if len(document_ids) > 1:
        raise ValueError("one persistence batch cannot span multiple documents")

    table_indexes = {table.table_id: index for index, table in enumerate(tables)}
    fingerprints = _template_fingerprints(template_fingerprint, analyses)
    snapshots: list[dict[str, object]] = []
    claims: list[dict[str, object]] = []
    seen_analysis_ids: set[str] = set()

    for analysis in analyses:
        if analysis.table_id in seen_analysis_ids:
            raise ValueError(f"duplicate table analysis: {analysis.table_id}")
        seen_analysis_ids.add(analysis.table_id)
        table = table_by_id.get(analysis.table_id)
        if table is None:
            raise ValueError(f"analysis references unknown parsed table: {analysis.table_id}")
        if not analysis.extractor_version.strip():
            raise ValueError("analysis extractor_version cannot be blank")

        persisted_claims = canonicalize_table_claims(analysis)
        persisted_analysis = replace(
            analysis,
            claims=persisted_claims,
            extractor_version=(
                persisted_claims[0].extractor_version
                if persisted_claims
                else f"{analysis.extractor_version}+p3-bridge-v1"
            ),
        )

        table_chunks = tuple(
            chunk for chunk in embedded_chunks if chunk.document_id == analysis.document_id
        )
        snapshots.append(
            _snapshot_payload(
                analysis=persisted_analysis,
                table=table,
                table_index=table_indexes[table.table_id],
                chunks=table_chunks,
                template_fingerprint=fingerprints.get(table.table_id),
            )
        )
        for claim in persisted_analysis.claims:
            claims.append(
                _claim_payload(
                    claim=claim,
                    analysis=persisted_analysis,
                    table=table,
                    chunks=table_chunks,
                )
            )

    prose_by_chunk: dict[str, list[StructuredClaim]] = {}
    for claim in prose_claims:
        chunk_id = claim.provenance.chunk_id
        if not chunk_id:
            raise ValueError("prose claim provenance chunk_id is required for persistence")
        prose_by_chunk.setdefault(chunk_id, []).append(claim)
    chunks_by_id = {chunk.id: chunk for chunk in embedded_chunks}
    for chunk_id in sorted(prose_by_chunk):
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            raise ValueError(f"prose claim references unknown embedded chunk: {chunk_id}")
        chunk_claims = tuple(prose_by_chunk[chunk_id])
        snapshot = _prose_snapshot_payload(chunk=chunk, claims=chunk_claims)
        snapshots.append(snapshot)
        claims.extend(
            _prose_claim_payload(
                claim=claim,
                chunk=chunk,
                snapshot_key=str(snapshot["snapshot_key"]),
            )
            for claim in chunk_claims
        )

    return StructuredFactPersistenceBatch(
        table_snapshots=tuple(snapshots),
        claims=tuple(claims),
    )


def _snapshot_payload(
    *,
    analysis: TableAnalysis,
    table: ParsedTable,
    table_index: int,
    chunks: Sequence[EmbeddedChunk],
    template_fingerprint: str | None,
) -> dict[str, object]:
    normalized_schema: dict[str, object] = {
        "source_form": "table",
        "columns": list(analysis.normalized_schema),
        "header_mapping": dict(sorted(analysis.header_mapping.items())),
    }
    input_content_hash = _stable_hash(_canonical_table_input(table))
    # The schema identity is semantic. Raw header spellings remain available
    # in ``header_mapping`` for audit, but aliases such as "Giá NY" and
    # "List price" must route to the same table family after normalization.
    schema_fingerprint = _stable_hash({"columns": list(analysis.normalized_schema)})
    source_chunk = _resolve_source_chunk(table=table, chunks=chunks, data_row_ordinal=None)
    source_chunk_id = _persisted_chunk_id(source_chunk) if source_chunk is not None else None
    page_from, page_to = _table_page_range(table, source_chunk)
    temporal = _common_temporal(analysis.claims)
    authority = _common_authority(analysis.claims)
    source_blocks = _table_source_block_ids(table)

    return {
        "table_id": table.table_id,
        "snapshot_key": analysis.table_id,
        "input_content_hash": input_content_hash,
        "schema_fingerprint": schema_fingerprint,
        "template_fingerprint": template_fingerprint,
        "table_index": table_index,
        "page_from": page_from,
        "page_to": page_to,
        "source_chunk_id": source_chunk_id,
        "source_locator": {
            "table_id": table.table_id,
            "location": table.location,
            "source_block_ids": list(source_blocks),
            "embedded_chunk_id": source_chunk.id if source_chunk is not None else None,
        },
        "normalized_schema": normalized_schema,
        "row_count": analysis.row_count,
        "column_count": table.columns,
        "extractor_name": "structured-fact-analyzer",
        "extractor_version": analysis.extractor_version,
        **_flat_temporal(temporal),
        **_flat_authority(authority),
        "extraction_confidence": analysis.confidence,
        "warnings": list(analysis.warnings),
    }


def _claim_payload(
    *,
    claim: StructuredClaim,
    analysis: TableAnalysis,
    table: ParsedTable,
    chunks: Sequence[EmbeddedChunk],
) -> dict[str, object]:
    if claim.document_id != analysis.document_id:
        raise ValueError("claim document_id does not match its table analysis")
    if claim.extractor_version != analysis.extractor_version:
        raise ValueError("claim extractor_version does not match its table analysis")
    provenance = claim.provenance
    if provenance.table_id != table.table_id:
        raise ValueError("claim provenance table_id does not match its parsed table")
    if provenance.row_index is None:
        raise ValueError("claim physical row_index is required for persistence")

    source_chunk = _resolve_source_chunk(
        table=table,
        chunks=chunks,
        data_row_ordinal=provenance.data_row_ordinal,
    )
    source_chunk_id = _persisted_chunk_id(source_chunk) if source_chunk is not None else None
    persisted_provenance = _provenance_payload(provenance, source_chunk, source_chunk_id)
    persisted_provenance["source_form"] = "table"
    persisted_provenance["claim_extractor_version"] = claim.extractor_version
    persisted_provenance["claim_temporal"] = claim.temporal.to_payload()
    persisted_provenance["claim_evidence"] = list(claim.evidence)
    subject_identity = _subject_identity(claim)
    expression = claim.value_expression
    if expression is None:  # pragma: no cover - guaranteed by StructuredClaim
        raise RuntimeError("StructuredClaim value expression invariant was violated")
    normalized_value = {
        **claim.value.to_payload(),
        **expression.to_payload(),
    }
    value_type = _migration_value_type(claim.value, claim.predicate)
    numeric_value = _numeric_value(claim.value, value_type)
    row_identity_hash = _text_hash(claim.subject_key)
    subject_identity_hash = _stable_hash(subject_identity)
    source_cells = _source_cells(claim, normalized_value)

    return {
        # Domain compatibility/debug fields.
        "id": claim.id,
        "document_id": claim.document_id,
        "subject_key": claim.subject_key,
        "scope": claim.scope.to_payload(),
        "value": normalized_value,
        "value_expression": expression.to_payload(),
        "temporal": claim.temporal.to_payload(),
        "authority": claim.authority.to_payload(),
        "claim_identity_hash": claim.claim_identity_hash,
        # Migration-16 indexed fields.
        "snapshot_key": analysis.table_id,
        "claim_key": claim.claim_identity_hash,
        "row_identity": claim.subject_key,
        "row_identity_hash": row_identity_hash,
        "row_index": provenance.row_index,
        "data_row_ordinal": provenance.data_row_ordinal,
        "page_number": provenance.page_number,
        "source_text": claim.value.raw_value,
        "source_cells": source_cells,
        "source_chunk_id": source_chunk_id,
        "provenance": persisted_provenance,
        "subject_identity": subject_identity,
        "subject_identity_hash": subject_identity_hash,
        "candidate_identity_hash": claim.candidate_identity_hash,
        "predicate": claim.predicate,
        "value_type": value_type,
        "normalized_value": normalized_value,
        "numeric_value": numeric_value,
        "unit": claim.value.unit,
        "currency": claim.value.currency.upper() if claim.value.currency else None,
        "qualifiers": claim.qualifiers.to_payload(),
        "qualifier_hash": claim.qualifiers.stable_identity_hash,
        **_flat_temporal(claim.temporal),
        **_flat_authority(claim.authority),
        # Keep the domain spelling alongside the indexed SQL column spelling.
        "extraction_confidence": claim.extraction_confidence,
        "confidence": claim.extraction_confidence,
        "is_derived": claim.derivation is not None,
        "derivation": claim.derivation.to_payload() if claim.derivation else {},
        "extractor_version": claim.extractor_version,
    }


def _prose_snapshot_payload(
    *,
    chunk: EmbeddedChunk,
    claims: Sequence[StructuredClaim],
) -> dict[str, object]:
    persisted_chunk_id = _persisted_chunk_id(chunk)
    snapshot_key = f"prose:{persisted_chunk_id}"
    schema = {
        "source_form": "prose",
        "predicates": sorted({claim.predicate for claim in claims}),
        "claim_extractor_versions": sorted({claim.extractor_version for claim in claims}),
    }
    confidence = min((claim.extraction_confidence for claim in claims), default=0.0)
    temporal = _common_temporal(claims)
    authority = _common_authority(claims)
    return {
        "table_id": snapshot_key,
        "snapshot_key": snapshot_key,
        "input_content_hash": (
            chunk.checksum if _SHA256_PATTERN.fullmatch(chunk.checksum) else _text_hash(chunk.text)
        ),
        "schema_fingerprint": _stable_hash(schema),
        "template_fingerprint": None,
        "table_index": chunk.chunk_index,
        "page_from": chunk.page_number,
        "page_to": chunk.page_number,
        "source_chunk_id": persisted_chunk_id,
        "source_locator": {
            "source_form": "prose",
            "embedded_chunk_id": chunk.id,
            "persisted_chunk_id": persisted_chunk_id,
        },
        "normalized_schema": schema,
        "row_count": len(claims),
        "column_count": 0,
        "extractor_name": "p3-prose-claim-extractor",
        "extractor_version": sorted({claim.extractor_version for claim in claims})[0],
        **_flat_temporal(temporal),
        **_flat_authority(authority),
        "extraction_confidence": confidence,
        "warnings": [],
    }


def _prose_claim_payload(
    *,
    claim: StructuredClaim,
    chunk: EmbeddedChunk,
    snapshot_key: str,
) -> dict[str, object]:
    if claim.document_id != chunk.document_id:
        raise ValueError("prose claim document_id does not match its embedded chunk")
    expression = claim.value_expression
    if expression is None:  # pragma: no cover - guaranteed by StructuredClaim
        raise RuntimeError("StructuredClaim value expression invariant was violated")
    source_chunk_id = _persisted_chunk_id(chunk)
    provenance = _provenance_payload(claim.provenance, chunk, source_chunk_id)
    provenance.update(
        {
            "source_form": "prose",
            "claim_extractor_version": claim.extractor_version,
            "claim_temporal": claim.temporal.to_payload(),
            "claim_evidence": list(claim.evidence),
        }
    )
    normalized_value = {**claim.value.to_payload(), **expression.to_payload()}
    value_type = _migration_value_type(claim.value, claim.predicate)
    subject_identity = _subject_identity(claim)
    source_text = _claim_source_text(claim, chunk)
    return {
        "id": claim.id,
        "document_id": claim.document_id,
        "subject_key": claim.subject_key,
        "scope": claim.scope.to_payload(),
        "value": normalized_value,
        "value_expression": expression.to_payload(),
        "temporal": claim.temporal.to_payload(),
        "authority": claim.authority.to_payload(),
        "claim_identity_hash": claim.claim_identity_hash,
        "snapshot_key": snapshot_key,
        "claim_key": claim.claim_identity_hash,
        "row_identity": claim.subject_key,
        "row_identity_hash": _text_hash(claim.subject_key),
        "row_index": chunk.chunk_index,
        "data_row_ordinal": None,
        "page_number": claim.provenance.page_number or chunk.page_number,
        "source_text": source_text,
        "source_cells": [],
        "source_chunk_id": source_chunk_id,
        "provenance": provenance,
        "subject_identity": subject_identity,
        "subject_identity_hash": _stable_hash(subject_identity),
        "candidate_identity_hash": claim.candidate_identity_hash,
        "predicate": claim.predicate,
        "value_type": value_type,
        "normalized_value": normalized_value,
        "numeric_value": _numeric_value(claim.value, value_type),
        "unit": expression.unit,
        "currency": expression.currency.upper() if expression.currency else None,
        "qualifiers": claim.qualifiers.to_payload(),
        "qualifier_hash": claim.qualifiers.stable_identity_hash,
        **_flat_temporal(claim.temporal),
        **_flat_authority(claim.authority),
        "extraction_confidence": claim.extraction_confidence,
        "confidence": claim.extraction_confidence,
        "is_derived": claim.derivation is not None,
        "derivation": claim.derivation.to_payload() if claim.derivation else {},
        "extractor_version": claim.extractor_version,
    }


def _claim_source_text(claim: StructuredClaim, chunk: EmbeddedChunk) -> str:
    canonical_text = str(chunk.canonical_text)
    span = claim.provenance.source_span
    if span is None:
        return claim.value.raw_value or canonical_text
    start, end = span
    if 0 <= start < end <= len(canonical_text):
        return canonical_text[start:end]
    return claim.value.raw_value or canonical_text


def _unique_tables(tables: Sequence[ParsedTable]) -> dict[str, ParsedTable]:
    result: dict[str, ParsedTable] = {}
    for table in tables:
        if not table.table_id.strip():
            raise ValueError("parsed table_id cannot be blank")
        if table.table_id in result:
            raise ValueError(f"duplicate parsed table_id: {table.table_id}")
        result[table.table_id] = table
    return result


def _template_fingerprints(
    value: str | Mapping[str, str] | None,
    analyses: Sequence[TableAnalysis],
) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        _validate_fingerprint(value)
        return {analysis.table_id: value for analysis in analyses}
    known_table_ids = {analysis.table_id for analysis in analyses}
    result: dict[str, str] = {}
    for table_id, fingerprint in value.items():
        if not table_id.strip():
            raise ValueError("template fingerprint table_id cannot be blank")
        if table_id not in known_table_ids:
            raise ValueError(f"template fingerprint references unknown table: {table_id}")
        _validate_fingerprint(fingerprint)
        result[table_id] = fingerprint
    return result


def _validate_fingerprint(value: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError("template_fingerprint must be a lowercase SHA-256 hex digest")


def _canonical_table_input(table: ParsedTable) -> dict[str, object]:
    return {
        "header": [_normalize_cell(value) for value in table.header],
        "rows": [[_normalize_cell(value) for value in row] for row in table.rows],
        "columns": table.columns,
    }


def _normalize_cell(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(normalized.split())


def _subject_identity(claim: StructuredClaim) -> dict[str, object]:
    # document_type is routing metadata and must not enter business identity.
    return {
        "subject_key": claim.subject_key,
        "location": claim.scope.location.to_payload(),
        "product": claim.scope.product.to_payload(),
        "commercial": claim.scope.commercial.to_payload(),
        "vehicle": claim.scope.vehicle.to_payload(),
        "entities": [entity.to_payload() for entity in claim.scope.entities],
        "explicit_breadth": list(claim.scope.explicit_breadth),
        "scope_identity_hash": claim.scope.scope_identity_hash,
    }


def _source_cells(
    claim: StructuredClaim,
    normalized_value: Mapping[str, object],
) -> list[dict[str, object]]:
    provenance = claim.provenance
    if provenance.column_name is None and provenance.cell_id is None:
        return []
    return [
        {
            "cell_id": provenance.cell_id,
            "column_name": provenance.column_name,
            "raw_value": claim.value.raw_value,
            "normalized_value": dict(normalized_value),
        }
    ]


def _provenance_payload(
    provenance: ClaimProvenance,
    chunk: EmbeddedChunk | None,
    persisted_chunk_id: str | None,
) -> dict[str, object]:
    payload = dict(provenance.to_payload())
    # Never retain a stale/unverified chunk id from upstream domain metadata.
    payload["chunk_id"] = persisted_chunk_id
    payload["embedded_chunk_id"] = chunk.id if chunk is not None else None
    return payload


def _migration_value_type(value: NormalizedValue, predicate: str) -> str:
    if value.currency:
        return "money"
    if isinstance(value.value, datetime):
        return "datetime"
    if isinstance(value.value, date):
        return "date"
    if isinstance(value.value, bool):
        return "boolean"
    if _is_numeric(value.value):
        normalized_unit = (value.unit or "").casefold()
        if normalized_unit in {"percent", "percentage", "%"}:
            return "percentage"
        return "quantity" if value.unit else "number"
    normalized_predicate = predicate.casefold()
    if normalized_predicate.endswith(("_id", "_code", "_identifier")):
        return "identifier"
    return "text"


def _numeric_value(value: NormalizedValue, value_type: str) -> str | None:
    if value_type not in {"money", "number", "percentage", "quantity"}:
        return None
    try:
        number = Decimal(str(value.value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _is_numeric(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float | Decimal):
        return not isinstance(value, float) or math.isfinite(value)
    if isinstance(value, str):
        try:
            return Decimal(value).is_finite()
        except InvalidOperation:
            return False
    return False


def _flat_temporal(temporal: TemporalContext) -> dict[str, object]:
    return dict(temporal.to_payload())


def _flat_authority(authority: SourceAuthority) -> dict[str, object]:
    metadata = {key: _json_scalar(value) for key, value in authority.metadata}
    if authority.approval_status is not None:
        metadata["approval_status"] = authority.approval_status
    if authority.officiality is not None:
        metadata["officiality"] = authority.officiality
    return {
        "source_publisher": authority.publisher,
        "source_type": authority.source_type or "unknown",
        "authority_level": authority.authority_level,
        "authority_metadata": metadata,
    }


def _common_temporal(claims: Sequence[StructuredClaim]) -> TemporalContext:
    if not claims:
        return TemporalContext()
    first = claims[0].temporal
    return first if all(claim.temporal == first for claim in claims) else TemporalContext()


def _common_authority(claims: Sequence[StructuredClaim]) -> SourceAuthority:
    if not claims:
        return SourceAuthority()
    first = claims[0].authority
    return first if all(claim.authority == first for claim in claims) else SourceAuthority()


def _table_source_block_ids(table: ParsedTable) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("source_block_id", "source_block_ids"):
        values.extend(_string_values(table.metadata.get(key)))
    if not values:
        values.append(table.table_id)
    return tuple(dict.fromkeys(value for value in values if value))


def _chunk_source_block_ids(chunk: EmbeddedChunk) -> tuple[str, ...]:
    values: list[str] = []
    for metadata in (chunk.metadata, chunk.provenance_metadata, chunk.retrieval_metadata):
        for key in ("source_block_id", "source_block_ids"):
            values.extend(_string_values(metadata.get(key)))
    return tuple(dict.fromkeys(value for value in values if value))


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list | tuple | set | frozenset):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _resolve_source_chunk(
    *,
    table: ParsedTable,
    chunks: Sequence[EmbeddedChunk],
    data_row_ordinal: int | None,
) -> EmbeddedChunk | None:
    table_blocks = set(_table_source_block_ids(table))
    candidates: list[EmbeddedChunk] = []
    for chunk in chunks:
        if not table_blocks.intersection(_chunk_source_block_ids(chunk)):
            continue
        row_start = _optional_int(chunk.metadata.get("table_data_row_start_ordinal"))
        row_end = _optional_int(chunk.metadata.get("table_data_row_end_ordinal"))
        has_range = row_start is not None and row_end is not None
        if data_row_ordinal is not None and row_start is not None and row_end is not None:
            if not row_start <= data_row_ordinal <= row_end:
                continue
        elif data_row_ordinal is not None and not bool(chunk.metadata.get("table_atomic")):
            # A row-group without a complete range cannot prove row coverage.
            continue
        elif data_row_ordinal is None and has_range:
            # A snapshot may cite the first deterministic row-group anchor.
            pass
        elif data_row_ordinal is None or not has_range:
            pass
        candidates.append(chunk)
    if not candidates:
        return None
    candidates.sort(
        key=lambda chunk: (
            not bool(chunk.metadata.get("table_atomic")),
            _optional_int(chunk.metadata.get("table_data_row_start_ordinal")) or 0,
            chunk.chunk_index,
            chunk.id,
        )
    )
    return candidates[0]


def _persisted_chunk_id(chunk: EmbeddedChunk) -> str:
    return str(uuid5(NAMESPACE_URL, f"chunk:{chunk.id}"))


def _table_page_range(
    table: ParsedTable,
    source_chunk: EmbeddedChunk | None,
) -> tuple[int | None, int | None]:
    pages: list[int] = []
    for key in ("page_from", "page_to", "page_number", "page"):
        value = _optional_positive_int(table.metadata.get(key))
        if value is not None:
            pages.append(value)
    for cell in table.cells:
        for key in ("page_number", "page"):
            value = _optional_positive_int(cell.get(key))
            if value is not None:
                pages.append(value)
    if not pages:
        page_matches = re.findall(
            r"(?:page|trang)[:#-]?(\d+)",
            table.location,
            re.I,
        )
        pages.extend(int(value) for value in page_matches)
    if not pages and source_chunk is not None and source_chunk.page_number is not None:
        pages.append(source_chunk.page_number)
    positive_pages = [value for value in pages if value > 0]
    return (
        min(positive_pages) if positive_pages else None,
        max(positive_pages) if positive_pages else None,
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _optional_positive_int(value: object) -> int | None:
    parsed = _optional_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _text_hash(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return hashlib.sha256(" ".join(normalized.split()).encode("utf-8")).hexdigest()


def _stable_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_scalar,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_scalar(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


__all__ = [
    "StructuredFactPersistenceBatch",
    "build_structured_fact_persistence_batch",
]
