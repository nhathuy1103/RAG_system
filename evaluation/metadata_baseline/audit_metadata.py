"""Read-only, schema-driven audit for exported RAG metadata.

The script consumes document/chunk JSONL records and writes aggregate and
record-level diagnostics. It never connects to or modifies a production store.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.metadata_baseline.common import (  # noqa: E402
    MISSING,
    CorpusRecord,
    MetadataBaselineError,
    SchemaField,
    classify_missing,
    ensure_outputs,
    entropy,
    load_records,
    load_schema,
    normalized_surface,
    parse_date,
    parse_datetime,
    punctuation_insensitive_surface,
    stable_value,
    validate_value,
    write_csv,
    write_json,
    write_text,
)

LOGGER = logging.getLogger("metadata_baseline.audit")

OUTPUT_FILES = {
    "field_summary": "metadata_field_summary.csv",
    "coverage": "metadata_coverage.csv",
    "validity": "metadata_validity.csv",
    "consistency": "metadata_consistency_issues.csv",
    "duplicates": "metadata_duplicate_ids.csv",
    "referential": "metadata_referential_errors.csv",
    "temporal": "metadata_temporal_errors.csv",
    "version": "metadata_version_errors.csv",
    "conflicts": "metadata_conflicts.csv",
    "outliers": "metadata_outliers.csv",
    "distributions": "metadata_distributions.json",
    "summary": "metadata_audit_summary.json",
    "report": "metadata_audit_report.md",
}

FIELD_SUMMARY_COLUMNS = (
    "field_name",
    "category",
    "level",
    "record_type",
    "required",
    "total_records",
    "non_empty_count",
    "valid_count",
    "coverage",
    "valid_coverage",
    "validity",
    "missing_count",
    "null_count",
    "empty_string_count",
    "empty_list_count",
    "empty_object_count",
    "placeholder_count",
    "unique_count",
    "cardinality_ratio",
    "entropy",
    "importance",
)

COVERAGE_COLUMNS = (
    "field_name",
    "record_type",
    "dimension",
    "dimension_value",
    "total_records",
    "non_empty_count",
    "valid_count",
    "coverage",
    "valid_coverage",
)

VALIDITY_COLUMNS = (
    "row_type",
    "field_name",
    "record_type",
    "record_id",
    "document_id",
    "total_non_empty",
    "valid_count",
    "invalid_count",
    "validity",
    "value",
    "error",
)

ISSUE_COLUMNS = (
    "severity",
    "issue_type",
    "field_name",
    "record_type",
    "record_id",
    "document_id",
    "related_record_id",
    "value",
    "expected",
    "details",
)


@dataclass(frozen=True, slots=True)
class AuditResult:
    """All deterministic outputs of one corpus audit."""

    field_summary: tuple[dict[str, object], ...]
    coverage: tuple[dict[str, object], ...]
    validity: tuple[dict[str, object], ...]
    consistency: tuple[dict[str, object], ...]
    duplicates: tuple[dict[str, object], ...]
    referential: tuple[dict[str, object], ...]
    temporal: tuple[dict[str, object], ...]
    version: tuple[dict[str, object], ...]
    conflicts: tuple[dict[str, object], ...]
    outliers: tuple[dict[str, object], ...]
    distributions: Mapping[str, object]
    summary: Mapping[str, object]
    report: str


def audit_records(
    records: Sequence[CorpusRecord],
    schema: Sequence[SchemaField],
    *,
    input_name: str = "metadata export",
) -> AuditResult:
    """Run every audit family over an immutable sequence of records."""

    field_summary, coverage, validity, distributions = audit_field_quality(records, schema)
    consistency = audit_consistency(records, schema)
    duplicates = audit_duplicate_ids(records, schema)
    referential = audit_referential_integrity(records, schema)
    temporal = audit_temporal_consistency(records)
    version = audit_version_consistency(records)
    conflicts = audit_metadata_conflicts(records, schema)
    outliers = audit_outliers(records, schema, distributions)
    summary = _build_summary(
        records,
        field_summary,
        consistency=consistency,
        duplicates=duplicates,
        referential=referential,
        temporal=temporal,
        version=version,
        conflicts=conflicts,
        outliers=outliers,
        input_name=input_name,
    )
    report = _render_report(summary, field_summary, schema)
    return AuditResult(
        field_summary=tuple(field_summary),
        coverage=tuple(coverage),
        validity=tuple(validity),
        consistency=tuple(consistency),
        duplicates=tuple(duplicates),
        referential=tuple(referential),
        temporal=tuple(temporal),
        version=tuple(version),
        conflicts=tuple(conflicts),
        outliers=tuple(outliers),
        distributions=distributions,
        summary=summary,
        report=report,
    )


def audit_field_quality(
    records: Sequence[CorpusRecord],
    schema: Sequence[SchemaField],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
]:
    """Compute coverage, validity, cardinality and distributions per field."""

    summaries: list[dict[str, object]] = []
    coverage_rows: list[dict[str, object]] = []
    validity_rows: list[dict[str, object]] = []
    distributions: dict[str, object] = {}

    for field in schema:
        for record_type in ("document", "chunk"):
            applicable = [
                record
                for record in records
                if record.record_type == record_type and field.applies_to(record_type)
            ]
            if not applicable:
                continue
            state_counts: Counter[str] = Counter()
            populated: list[tuple[CorpusRecord, object]] = []
            valid: list[tuple[CorpusRecord, object]] = []
            invalid: list[tuple[CorpusRecord, object, tuple[str, ...]]] = []
            for record in applicable:
                value = record.get(field)
                missing_reason = classify_missing(value)
                if missing_reason is not None:
                    state_counts[missing_reason] += 1
                    continue
                populated.append((record, value))
                errors = validate_value(field, value)
                if errors:
                    invalid.append((record, value, errors))
                else:
                    valid.append((record, value))

            serialized = [stable_value(value) for _, value in populated]
            counts = Counter(serialized)
            total = len(applicable)
            non_empty_count = len(populated)
            valid_count = len(valid)
            summary: dict[str, object] = {
                "field_name": field.field_name,
                "category": field.category,
                "level": field.level,
                "record_type": record_type,
                "required": field.required,
                "total_records": total,
                "non_empty_count": non_empty_count,
                "valid_count": valid_count,
                "coverage": _ratio(non_empty_count, total),
                "valid_coverage": _ratio(valid_count, total),
                "validity": _ratio(valid_count, non_empty_count),
                "missing_count": state_counts["missing"],
                "null_count": state_counts["null"],
                "empty_string_count": state_counts["empty_string"],
                "empty_list_count": state_counts["empty_list"],
                "empty_object_count": state_counts["empty_object"],
                "placeholder_count": state_counts["placeholder"],
                "unique_count": len(counts),
                "cardinality_ratio": _ratio(len(counts), non_empty_count),
                "entropy": round(entropy(serialized), 6),
                "importance": field.importance,
            }
            summaries.append(summary)
            validity_rows.append(
                {
                    "row_type": "summary",
                    "field_name": field.field_name,
                    "record_type": record_type,
                    "record_id": "",
                    "document_id": "",
                    "total_non_empty": non_empty_count,
                    "valid_count": valid_count,
                    "invalid_count": len(invalid),
                    "validity": _ratio(valid_count, non_empty_count),
                    "value": "",
                    "error": "",
                }
            )
            validity_rows.extend(
                {
                    "row_type": "issue",
                    "field_name": field.field_name,
                    "record_type": record_type,
                    "record_id": record.record_id,
                    "document_id": record.document_id or "",
                    "total_non_empty": "",
                    "valid_count": "",
                    "invalid_count": "",
                    "validity": "",
                    "value": _truncate(stable_value(value), 500),
                    "error": "|".join(errors),
                }
                for record, value, errors in invalid
            )

            grouped: dict[tuple[str, str], list[CorpusRecord]] = defaultdict(list)
            for record in applicable:
                for dimension, dimension_value in _dimensions(record):
                    grouped[(dimension, dimension_value)].append(record)
            for (dimension, dimension_value), group_records in sorted(grouped.items()):
                group_non_empty = 0
                group_valid = 0
                for record in group_records:
                    value = record.get(field)
                    if classify_missing(value) is not None:
                        continue
                    group_non_empty += 1
                    if not validate_value(field, value):
                        group_valid += 1
                coverage_rows.append(
                    {
                        "field_name": field.field_name,
                        "record_type": record_type,
                        "dimension": dimension,
                        "dimension_value": dimension_value,
                        "total_records": len(group_records),
                        "non_empty_count": group_non_empty,
                        "valid_count": group_valid,
                        "coverage": _ratio(group_non_empty, len(group_records)),
                        "valid_coverage": _ratio(group_valid, len(group_records)),
                    }
                )

            key = f"{record_type}.{field.field_name}"
            distributions[key] = {
                "record_type": record_type,
                "field_name": field.field_name,
                "non_empty_count": non_empty_count,
                "unique_count": len(counts),
                "cardinality_ratio": _ratio(len(counts), non_empty_count),
                "entropy": round(entropy(serialized), 6),
                "top_values": [
                    {"value": _truncate(value, 500), "count": count}
                    for value, count in counts.most_common(20)
                ],
                "long_tail_singleton_count": sum(count == 1 for count in counts.values()),
                "long_tail_singleton_ratio": _ratio(
                    sum(count == 1 for count in counts.values()), len(counts)
                ),
                "dominant_value_ratio": _ratio(
                    counts.most_common(1)[0][1] if counts else 0,
                    non_empty_count,
                ),
            }
    distributions["__schema_inventory__"] = _observed_schema_inventory(records, schema)
    return summaries, coverage_rows, validity_rows, distributions


def audit_consistency(
    records: Sequence[CorpusRecord], schema: Sequence[SchemaField]
) -> list[dict[str, object]]:
    """Detect representation variants and unexpected within-document drift."""

    issues: list[dict[str, object]] = []
    for field in schema:
        if not any(field.applies_to(kind) for kind in ("document", "chunk")):
            continue
        surface_groups: dict[str, set[str]] = defaultdict(set)
        punctuation_groups: dict[str, set[str]] = defaultdict(set)
        records_by_surface: dict[tuple[str, str], list[CorpusRecord]] = defaultdict(list)
        for record in records:
            if not field.applies_to(record.record_type):
                continue
            value = record.get(field)
            if classify_missing(value) is not None or not isinstance(value, str):
                continue
            normalized = normalized_surface(value)
            surface_groups[normalized].add(value)
            records_by_surface[("surface", normalized)].append(record)
            punctuation = punctuation_insensitive_surface(value)
            if punctuation:
                punctuation_groups[punctuation].add(value)
                records_by_surface[("punctuation", punctuation)].append(record)
        for normalized, variants in sorted(surface_groups.items()):
            if len(variants) > 1:
                record = records_by_surface[("surface", normalized)][0]
                issues.append(
                    _issue(
                        "medium",
                        "case_whitespace_or_unicode_variant",
                        field.field_name,
                        record,
                        value=" | ".join(sorted(variants)),
                        expected=normalized,
                        details="Values collapse to the same NFKC/casefold/whitespace form.",
                    )
                )
        for normalized, variants in sorted(punctuation_groups.items()):
            if len(variants) > 1 and len({normalized_surface(item) for item in variants}) > 1:
                record = records_by_surface[("punctuation", normalized)][0]
                issues.append(
                    _issue(
                        "low",
                        "punctuation_format_variant",
                        field.field_name,
                        record,
                        value=" | ".join(sorted(variants)),
                        expected=normalized,
                        details="Values differ only after punctuation-insensitive normalization.",
                    )
                )

        unique_values = sorted(
            {
                str(record.get(field))
                for record in records
                if field.applies_to(record.record_type)
                and isinstance(record.get(field), str)
                and classify_missing(record.get(field)) is None
            }
        )
        acronym_groups: dict[str, set[str]] = defaultdict(set)
        morphology_groups: dict[str, set[str]] = defaultdict(set)
        for value in unique_values:
            words = _word_tokens(value)
            if len(words) >= 2:
                acronym_groups["".join(word[0] for word in words)].add(value)
            if words:
                morphology_groups[" ".join(_english_singular(word) for word in words)].add(value)
        normalized_values = {normalized_surface(value): value for value in unique_values}
        for acronym, variants in sorted(acronym_groups.items()):
            short = normalized_values.get(acronym)
            if short and any(normalized_surface(item) != acronym for item in variants):
                variants.add(short)
                representative = next(
                    record
                    for record in records
                    if field.applies_to(record.record_type)
                    and isinstance(record.get(field), str)
                    and str(record.get(field)) in variants
                )
                issues.append(
                    _issue(
                        "medium",
                        "possible_acronym_variant",
                        field.field_name,
                        representative,
                        value=" | ".join(sorted(variants)),
                        expected="review one controlled surface form",
                        details=(
                            "Initialism matches another multi-token value; semantic review "
                            "is required."
                        ),
                    )
                )
        for signature, variants in sorted(morphology_groups.items()):
            if len(variants) <= 1 or len(variants) > 20:
                continue
            representative = next(
                record
                for record in records
                if field.applies_to(record.record_type)
                and isinstance(record.get(field), str)
                and str(record.get(field)) in variants
            )
            issues.append(
                _issue(
                    "low",
                    "possible_singular_plural_variant",
                    field.field_name,
                    representative,
                    value=" | ".join(sorted(variants)),
                    expected=signature,
                    details="English token singularization produced one surface group.",
                )
            )

        if field.expected_data_type.casefold() in {"date", "datetime"}:
            formats: dict[str, list[CorpusRecord]] = defaultdict(list)
            for record in records:
                if not field.applies_to(record.record_type):
                    continue
                value = record.get(field)
                if isinstance(value, str) and classify_missing(value) is None:
                    formats[_date_format_signature(value)].append(record)
            if len(formats) > 1:
                representative = next(iter(next(iter(formats.values()))))
                issues.append(
                    _issue(
                        "medium",
                        "date_format_variant",
                        field.field_name,
                        representative,
                        value=" | ".join(sorted(formats)),
                        expected="one ISO-8601 representation",
                    )
                )

        if field.consistency_scope == "document":
            chunks_by_document: dict[str, list[CorpusRecord]] = defaultdict(list)
            for record in records:
                if record.record_type == "chunk" and record.document_id:
                    chunks_by_document[record.document_id].append(record)
            for document_id, chunks in chunks_by_document.items():
                values: dict[str, list[CorpusRecord]] = defaultdict(list)
                for chunk in chunks:
                    value = chunk.get(field)
                    if classify_missing(value) is None:
                        values[normalized_surface(value)].append(chunk)
                if len(values) > 1:
                    first = chunks[0]
                    issues.append(
                        _issue(
                            "high",
                            "inconsistent_within_document",
                            field.field_name,
                            first,
                            value=" | ".join(sorted(values)),
                            expected="one normalized value per document",
                            details=(
                                f"Document {document_id} has {len(values)} values across "
                                "chunks."
                            ),
                        )
                    )
    return _deduplicate_issues(issues)


def audit_duplicate_ids(
    records: Sequence[CorpusRecord], schema: Sequence[SchemaField]
) -> list[dict[str, object]]:
    """Detect duplicate document/chunk IDs and schema-declared unique fields."""

    issues: list[dict[str, object]] = []
    for record_type, identifier_name in (("document", "document_id"), ("chunk", "chunk_id")):
        id_groups: dict[str, list[CorpusRecord]] = defaultdict(list)
        for record in records:
            if record.record_type != record_type:
                continue
            identifier = record.document_id if record_type == "document" else record.chunk_id
            if identifier:
                id_groups[identifier].append(record)
        for identifier, group in id_groups.items():
            if len(group) <= 1:
                continue
            payload_hashes = {
                hashlib.sha256(stable_value(record.raw).encode("utf-8")).hexdigest()
                for record in group
            }
            severity = "critical" if len(payload_hashes) > 1 else "high"
            issues.append(
                _issue(
                    severity,
                    "duplicate_id_different_payload" if len(payload_hashes) > 1 else "duplicate_id",
                    identifier_name,
                    group[0],
                    value=identifier,
                    expected="globally unique within record type",
                    details=(
                        f"Found {len(group)} records and {len(payload_hashes)} payload "
                        "variants."
                    ),
                )
            )

    for field in schema:
        if field.unique_scope != "global":
            continue
        unique_groups: dict[str, list[CorpusRecord]] = defaultdict(list)
        for record in records:
            if not field.applies_to(record.record_type):
                continue
            value = record.get(field)
            if classify_missing(value) is None:
                unique_groups[stable_value(value)].append(record)
        for value, group in unique_groups.items():
            if len(group) > 1:
                issues.append(
                    _issue(
                        "high",
                        "duplicate_unique_field",
                        field.field_name,
                        group[0],
                        value=value,
                        expected="unique",
                        details=f"Value occurs in {len(group)} records.",
                    )
                )
    return _deduplicate_issues(issues)


def audit_referential_integrity(
    records: Sequence[CorpusRecord], schema: Sequence[SchemaField]
) -> list[dict[str, object]]:
    """Validate parent document and schema-declared references."""

    issues: list[dict[str, object]] = []
    document_ids = {
        record.document_id
        for record in records
        if record.record_type == "document" and record.document_id
    }
    chunk_ids = {
        record.chunk_id for record in records if record.record_type == "chunk" and record.chunk_id
    }
    source_chunk_ids = {
        str(value)
        for record in records
        if record.record_type == "chunk"
        and (value := _first_value(record, "source_chunk_id", "metadata.source_chunk_id"))
        not in (MISSING, None, "")
    }
    targets = {
        "document_id": document_ids,
        "chunk_id": chunk_ids,
        # Database matches point to persisted chunk UUIDs, while same-batch
        # matches point to the deterministic source chunk identifier.
        "chunk_id_or_source_chunk_id": chunk_ids | source_chunk_ids,
    }
    for record in records:
        if record.record_type == "chunk" and (
            not record.document_id or record.document_id not in document_ids
        ):
            issues.append(
                _issue(
                    "critical",
                    "missing_parent_document",
                    "document_id",
                    record,
                    value=record.document_id or "",
                    expected="existing document_id",
                    details="Chunk parent is absent from this export snapshot.",
                )
            )

    for field in schema:
        if field.reference_target not in targets:
            continue
        valid_targets = targets[field.reference_target]
        for record in records:
            if not field.applies_to(record.record_type):
                continue
            value = record.get(field)
            if classify_missing(value) is not None:
                continue
            values = value if isinstance(value, list) else [value]
            for item in values:
                if str(item) not in valid_targets:
                    issues.append(
                        _issue(
                            "high",
                            "dangling_reference",
                            field.field_name,
                            record,
                            value=str(item),
                            expected=f"existing {field.reference_target}",
                            details="Referenced record is absent from the export snapshot.",
                        )
                    )

    for record in records:
        if record.record_type != "chunk":
            continue
        path = _first_value(record, "retrieval_metadata.section_path", "section_path")
        title = _first_value(record, "retrieval_metadata.section_title", "section_title")
        if isinstance(path, list) and title not in (MISSING, None, ""):
            normalized_path = {normalized_surface(item) for item in path}
            if normalized_surface(title) not in normalized_path:
                issues.append(
                    _issue(
                        "medium",
                        "section_title_not_in_path",
                        "retrieval_metadata.section_path",
                        record,
                        value=stable_value(path),
                        expected=str(title),
                        details="Section path does not contain the chunk section title.",
                    )
                )
    return _deduplicate_issues(issues)


def audit_temporal_consistency(records: Sequence[CorpusRecord]) -> list[dict[str, object]]:
    """Check the date relationships represented by the current document schema."""

    issues: list[dict[str, object]] = []
    today = datetime.now(UTC).date()
    for record in records:
        raw_created = _first_value(record, "created_at")
        raw_updated = _first_value(record, "updated_at")
        raw_effective_from = _first_value(record, "effective_from")
        raw_effective_to = _first_value(record, "effective_to", "expiry_date")
        created = parse_datetime(raw_created)
        updated = parse_datetime(raw_updated)
        effective_from = parse_date(raw_effective_from)
        effective_to = parse_date(raw_effective_to)
        status = str(_first_value(record, "status", "quality_status") or "").casefold()
        for name, raw_value, parsed in (
            ("created_at", raw_created, created),
            ("updated_at", raw_updated, updated),
            ("effective_from", raw_effective_from, effective_from),
            ("effective_to", raw_effective_to, effective_to),
        ):
            if classify_missing(raw_value) is None and parsed is None:
                issues.append(
                    _issue(
                        "high",
                        "unparseable_date",
                        name,
                        record,
                        value=str(raw_value),
                        expected="ISO-8601 date/datetime",
                    )
                )
        if created and updated and created > updated:
            issues.append(
                _issue(
                    "high",
                    "created_after_updated",
                    "created_at|updated_at",
                    record,
                    value=f"{created.isoformat()} > {updated.isoformat()}",
                    expected="created_at <= updated_at",
                )
            )
        if effective_from and effective_to and effective_from > effective_to:
            issues.append(
                _issue(
                    "critical",
                    "effective_after_expiry",
                    "effective_from|effective_to",
                    record,
                    value=f"{effective_from.isoformat()} > {effective_to.isoformat()}",
                    expected="effective_from <= effective_to",
                )
            )
        if status == "active" and effective_to and effective_to < today:
            issues.append(
                _issue(
                    "high",
                    "active_but_expired",
                    "status|effective_to",
                    record,
                    value=effective_to.isoformat(),
                    expected=f">= {today.isoformat()}",
                )
            )
        if status == "expired" and effective_to and effective_to >= today:
            issues.append(
                _issue(
                    "high",
                    "expired_before_expiry_date",
                    "status|effective_to",
                    record,
                    value=effective_to.isoformat(),
                    expected=f"< {today.isoformat()}",
                )
            )
        for name, parsed in (
            ("created_at", created.date() if created else None),
            ("updated_at", updated.date() if updated else None),
            ("effective_from", effective_from),
            ("effective_to", effective_to),
        ):
            if parsed and (parsed.year < 1970 or parsed.year > today.year + 20):
                issues.append(
                    _issue(
                        "medium",
                        "date_outside_reasonable_range",
                        name,
                        record,
                        value=parsed.isoformat(),
                        expected=f"1970..{today.year + 20}",
                    )
                )
    return issues


def audit_version_consistency(records: Sequence[CorpusRecord]) -> list[dict[str, object]]:
    """Validate version groups, current flags and chunk/parent version agreement."""

    issues: list[dict[str, object]] = []
    documents = [record for record in records if record.record_type == "document"]
    groups: dict[str, list[CorpusRecord]] = defaultdict(list)
    for document in documents:
        group_id = _first_value(document, "version_group_id")
        if classify_missing(group_id) is None:
            groups[str(group_id)].append(document)

    for group_id, group in groups.items():
        current = [record for record in group if _as_bool(_first_value(record, "is_current"))]
        if len(current) > 1:
            issues.append(
                _issue(
                    "critical",
                    "multiple_current_versions",
                    "is_current",
                    current[0],
                    value="|".join(record.record_id for record in current),
                    expected="one current document per version_group_id",
                    details=f"version_group_id={group_id}",
                )
            )
        versions: list[tuple[int, CorpusRecord]] = []
        for record in group:
            raw_version = _first_value(record, "version_number")
            if not isinstance(raw_version, int) or isinstance(raw_version, bool):
                if len(group) > 1:
                    issues.append(
                        _issue(
                            "high",
                            "missing_version_in_multiversion_group",
                            "version_number",
                            record,
                            value=stable_value(raw_version),
                            expected="positive integer",
                        )
                    )
                continue
            versions.append((raw_version, record))
        numbers = sorted(version for version, _ in versions)
        if len(numbers) != len(set(numbers)):
            issues.append(
                _issue(
                    "critical",
                    "duplicate_version_number",
                    "version_number",
                    group[0],
                    value=stable_value(numbers),
                    expected="unique within version group",
                    details=f"version_group_id={group_id}",
                )
            )
        if numbers and numbers != list(range(min(numbers), max(numbers) + 1)):
            issues.append(
                _issue(
                    "medium",
                    "version_sequence_gap",
                    "version_number",
                    group[0],
                    value=stable_value(numbers),
                    expected=f"continuous sequence {min(numbers)}..{max(numbers)}",
                    details=f"version_group_id={group_id}",
                )
            )
        ordered = sorted(versions)
        previous_date = None
        for _, record in ordered:
            current_date = parse_date(_first_value(record, "effective_from"))
            if previous_date and current_date and current_date < previous_date:
                issues.append(
                    _issue(
                        "high",
                        "newer_version_has_older_effective_date",
                        "version_number|effective_from",
                        record,
                        value=current_date.isoformat(),
                        expected=f">= {previous_date.isoformat()}",
                    )
                )
            previous_date = current_date or previous_date

    documents_by_id = {
        record.document_id: record for record in documents if record.document_id is not None
    }
    for record in records:
        if record.record_type != "chunk" or not record.document_id:
            continue
        parent = documents_by_id.get(record.document_id)
        if parent is None:
            continue
        chunk_version = _first_value(record, "document_version", "metadata.document_version")
        parent_version = _first_value(parent, "version_number")
        if (
            classify_missing(chunk_version) is None
            and classify_missing(parent_version) is None
            and str(chunk_version) != str(parent_version)
        ):
            issues.append(
                _issue(
                    "critical",
                    "chunk_parent_version_mismatch",
                    "document_version",
                    record,
                    value=str(chunk_version),
                    expected=str(parent_version),
                    related_record_id=parent.record_id,
                )
            )
    for record in documents:
        quality_status = str(_first_value(record, "quality_status") or "").casefold()
        if quality_status in {"superseded", "duplicate"} and _as_bool(
            _first_value(record, "is_current")
        ):
            issues.append(
                _issue(
                    "high",
                    "noncanonical_document_marked_current",
                    "quality_status|is_current",
                    record,
                    value=quality_status,
                    expected="is_current=false",
                )
            )
    return issues


def audit_metadata_conflicts(
    records: Sequence[CorpusRecord], schema: Sequence[SchemaField]
) -> list[dict[str, object]]:
    """Detect contradictory values under schema-declared equivalent keys."""

    issues: list[dict[str, object]] = []
    role_groups: dict[str, list[SchemaField]] = defaultdict(list)
    role_comparisons: dict[str, list[SchemaField]] = defaultdict(list)
    for field in schema:
        for role in field.conflict_roles:
            kind, separator, scope = role.partition(":")
            if not separator or not scope:
                continue
            if kind == "group":
                role_groups[scope].append(field)
            elif kind == "compare":
                role_comparisons[scope].append(field)
    if role_groups:
        for scope, grouping_fields in sorted(role_groups.items()):
            role_group_records: dict[tuple[str, ...], list[CorpusRecord]] = defaultdict(list)
            for record in records:
                applicable = [
                    field for field in grouping_fields if field.applies_to(record.record_type)
                ]
                if len(applicable) != len(grouping_fields):
                    continue
                group_values = [record.get(field) for field in applicable]
                if any(classify_missing(value) is not None for value in group_values):
                    continue
                role_group_records[
                    tuple(normalized_surface(value) for value in group_values)
                ].append(record)
            for group_key, group in role_group_records.items():
                if len(group) <= 1:
                    continue
                for sensitive in role_comparisons.get(scope, ()):
                    relevant = [
                        record for record in group if sensitive.applies_to(record.record_type)
                    ]
                    comparison_values: dict[str, list[CorpusRecord]] = defaultdict(list)
                    for record in relevant:
                        value = record.get(sensitive)
                        if classify_missing(value) is None:
                            comparison_values[normalized_surface(value)].append(record)
                    if len(comparison_values) <= 1:
                        continue
                    issues.append(
                        _issue(
                            "high",
                            "metadata_conflict",
                            sensitive.field_name,
                            relevant[0],
                            value=" | ".join(sorted(comparison_values)),
                            expected=f"consistent under {scope}={stable_value(group_key)}",
                            details="Schema conflict role found contradictory normalized values.",
                        )
                    )
        return _deduplicate_issues(issues)

    grouping_fields = [field for field in schema if field.conflict_group]
    sensitive_fields = [field for field in schema if field.conflict_sensitive]
    for grouping_field in grouping_fields:
        legacy_groups: dict[tuple[str, str], list[CorpusRecord]] = defaultdict(list)
        for record in records:
            if not grouping_field.applies_to(record.record_type):
                continue
            value = record.get(grouping_field)
            if classify_missing(value) is None:
                legacy_groups[(record.record_type, normalized_surface(value))].append(record)
        for (_, group_value), group in legacy_groups.items():
            if len(group) <= 1:
                continue
            for sensitive in sensitive_fields:
                relevant = [record for record in group if sensitive.applies_to(record.record_type)]
                legacy_values: dict[str, list[CorpusRecord]] = defaultdict(list)
                for record in relevant:
                    value = record.get(sensitive)
                    if classify_missing(value) is None:
                        legacy_values[normalized_surface(value)].append(record)
                if len(legacy_values) <= 1:
                    continue
                first = relevant[0]
                issues.append(
                    _issue(
                        "high",
                        "metadata_conflict",
                        sensitive.field_name,
                        first,
                        value=" | ".join(sorted(legacy_values)),
                        expected=f"consistent under {grouping_field.field_name}={group_value}",
                        details="Conflicting normalized values in an equivalent-record group.",
                    )
                )
    return _deduplicate_issues(issues)


def audit_outliers(
    records: Sequence[CorpusRecord],
    schema: Sequence[SchemaField],
    distributions: Mapping[str, object],
) -> list[dict[str, object]]:
    """Flag declared length limits, near constants, high cardinality and chunk-count tails."""

    issues: list[dict[str, object]] = []
    for field in schema:
        for record in records:
            if not field.applies_to(record.record_type):
                continue
            value = record.get(field)
            if classify_missing(value) is not None:
                continue
            if (
                field.max_length is not None
                and isinstance(value, str)
                and len(value) > field.max_length
            ):
                issues.append(
                    _issue(
                        "medium",
                        "text_length_outlier",
                        field.field_name,
                        record,
                        value=str(len(value)),
                        expected=f"<= {field.max_length}",
                    )
                )
            if (
                field.max_items is not None
                and isinstance(value, list)
                and len(value) > field.max_items
            ):
                issues.append(
                    _issue(
                        "medium",
                        "list_length_outlier",
                        field.field_name,
                        record,
                        value=str(len(value)),
                        expected=f"<= {field.max_items}",
                    )
                )

    for key, raw_distribution in distributions.items():
        if not isinstance(raw_distribution, Mapping):
            continue
        non_empty = int(raw_distribution.get("non_empty_count") or 0)
        unique = int(raw_distribution.get("unique_count") or 0)
        top_values = raw_distribution.get("top_values")
        if non_empty < 10 or not isinstance(top_values, list) or not top_values:
            continue
        top = top_values[0]
        if isinstance(top, Mapping) and int(top.get("count") or 0) / non_empty >= 0.95:
            record_type, _, field_name = key.partition(".")
            representative = next(
                (record for record in records if record.record_type == record_type), records[0]
            )
            issues.append(
                _issue(
                    "low",
                    "near_constant_field",
                    field_name,
                    representative,
                    value=str(top.get("value") or ""),
                    expected="inspect whether the field discriminates records",
                    details=f"Top value covers {int(top.get('count') or 0)}/{non_empty} records.",
                )
            )
        if non_empty >= 20 and unique / non_empty >= 0.98:
            record_type, _, field_name = key.partition(".")
            representative = next(
                (record for record in records if record.record_type == record_type), records[0]
            )
            issues.append(
                _issue(
                    "low",
                    "very_high_cardinality",
                    field_name,
                    representative,
                    value=f"{unique}/{non_empty}",
                    expected="review indexing/filtering suitability",
                )
            )

    chunk_counts = Counter(
        record.document_id
        for record in records
        if record.record_type == "chunk" and record.document_id
    )
    if len(chunk_counts) >= 4:
        values = list(chunk_counts.values())
        q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
        threshold = q3 + 1.5 * (q3 - q1)
        for document_id, count in chunk_counts.items():
            if count <= threshold:
                continue
            representative = next(
                record
                for record in records
                if record.record_type == "chunk" and record.document_id == document_id
            )
            issues.append(
                _issue(
                    "medium",
                    "document_chunk_count_outlier",
                    "chunk_count",
                    representative,
                    value=str(count),
                    expected=f"<= IQR threshold {threshold:.2f}",
                )
            )
    return _deduplicate_issues(issues)


def write_audit_result(result: AuditResult, output_dir: Path, *, overwrite: bool) -> None:
    """Write the complete audit atomically with a preflight overwrite check."""

    paths = {key: output_dir / name for key, name in OUTPUT_FILES.items()}
    ensure_outputs(paths.values(), overwrite=overwrite)
    write_csv(paths["field_summary"], result.field_summary, FIELD_SUMMARY_COLUMNS)
    write_csv(paths["coverage"], result.coverage, COVERAGE_COLUMNS)
    write_csv(paths["validity"], result.validity, VALIDITY_COLUMNS)
    for name in (
        "consistency",
        "duplicates",
        "referential",
        "temporal",
        "version",
        "conflicts",
        "outliers",
    ):
        write_csv(paths[name], getattr(result, name), ISSUE_COLUMNS)
    write_json(paths["distributions"], result.distributions)
    write_json(paths["summary"], result.summary)
    write_text(paths["report"], result.report)


def _observed_schema_inventory(
    records: Sequence[CorpusRecord], schema: Sequence[SchemaField]
) -> dict[str, object]:
    """List observed leaf paths so open JSONB drift remains visible."""

    observed: Counter[str] = Counter()
    for record in records:
        for path in _leaf_paths(record.raw):
            canonical = path.removeprefix("metadata.")
            if canonical in {"record_type", "record_id"}:
                continue
            observed[f"{record.record_type}.{canonical}"] += 1
    known_by_type: dict[str, set[str]] = {"document": set(), "chunk": set()}
    for field in schema:
        for record_type in known_by_type:
            if not field.applies_to(record_type):
                continue
            for path in field.paths:
                known_by_type[record_type].add(path.removeprefix("metadata."))
    wrapper_paths = {"id", "document_id", "chunk_id", "content"}
    unregistered = [
        {"path": path, "record_count": count}
        for typed_path, count in sorted(observed.items())
        for record_type, separator, path in (typed_path.partition("."),)
        if separator
        and path not in wrapper_paths
        and path not in known_by_type.get(record_type, set())
    ]
    return {
        "observed_leaf_path_count": len(observed),
        "registered_canonical_field_count": len(schema),
        "unregistered_leaf_path_count": len(unregistered),
        "unregistered_leaf_paths": unregistered,
    }


def _leaf_paths(value: object, prefix: str = "") -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return (prefix,) if prefix else ()
    paths: list[str] = []
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping) and item:
            paths.extend(_leaf_paths(item, path))
        else:
            paths.append(path)
    return tuple(paths)


def _word_tokens(value: str) -> tuple[str, ...]:
    words: list[str] = []
    current: list[str] = []
    for character in normalized_surface(value):
        if character.isalnum():
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return tuple(words)


def _english_singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _date_format_signature(value: str) -> str:
    stripped = value.strip()
    date_separator = "-" if "-" in stripped[:10] else "/" if "/" in stripped[:10] else "other"
    time_part = "datetime" if "T" in stripped or " " in stripped else "date"
    timezone = (
        "z"
        if stripped.endswith("Z")
        else "offset"
        if time_part == "datetime" and ("+" in stripped[10:] or "-" in stripped[10:])
        else "naive"
    )
    return f"{time_part}:{date_separator}:{timezone}"


def _dimensions(record: CorpusRecord) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = [("all", "all"), ("record_type", record.record_type)]
    document_type = _first_value(
        record,
        "retrieval_metadata.document_type",
        "document_type",
    )
    source = _first_value(
        record,
        "source",
        "provenance_metadata.source",
        "storage_bucket",
    )
    version = _first_value(record, "version_number", "document_version")
    year = _record_year(record)
    for dimension, value in (
        ("document_type", document_type),
        ("source", source),
        ("year", year),
        ("version", version),
    ):
        if classify_missing(value) is None:
            values.append((dimension, str(value)))
    return tuple(values)


def _record_year(record: CorpusRecord) -> object:
    for field in ("effective_from", "created_at", "creation_date", "updated_at"):
        value = _first_value(record, field)
        parsed = parse_date(value)
        if parsed:
            return parsed.year
    return MISSING


def _first_value(record: CorpusRecord, *paths: str) -> object:
    for path in paths:
        value = record.get(path)
        if value is not MISSING:
            return value
    return MISSING


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def _issue(
    severity: str,
    issue_type: str,
    field_name: str,
    record: CorpusRecord,
    *,
    value: str = "",
    expected: str = "",
    related_record_id: str = "",
    details: str = "",
) -> dict[str, object]:
    return {
        "severity": severity,
        "issue_type": issue_type,
        "field_name": field_name,
        "record_type": record.record_type,
        "record_id": record.record_id,
        "document_id": record.document_id or "",
        "related_record_id": related_record_id,
        "value": _truncate(value, 1000),
        "expected": _truncate(expected, 1000),
        "details": _truncate(details, 2000),
    }


def _deduplicate_issues(issues: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    unique: dict[tuple[str, ...], dict[str, object]] = {}
    for issue in issues:
        key = tuple(str(issue.get(column) or "") for column in ISSUE_COLUMNS)
        unique[key] = issue
    return list(unique.values())


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _metric_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _metric_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _build_summary(
    records: Sequence[CorpusRecord],
    field_summary: Sequence[Mapping[str, object]],
    *,
    consistency: Sequence[Mapping[str, object]],
    duplicates: Sequence[Mapping[str, object]],
    referential: Sequence[Mapping[str, object]],
    temporal: Sequence[Mapping[str, object]],
    version: Sequence[Mapping[str, object]],
    conflicts: Sequence[Mapping[str, object]],
    outliers: Sequence[Mapping[str, object]],
    input_name: str,
) -> dict[str, object]:
    document_count = sum(record.record_type == "document" for record in records)
    chunk_count = sum(record.record_type == "chunk" for record in records)
    critical = sum(
        str(issue.get("severity")) == "critical"
        for family in (duplicates, referential, temporal, version, conflicts)
        for issue in family
    )
    version_group_count = len(
        {
            str(value)
            for record in records
            if record.record_type == "document"
            and classify_missing(value := _first_value(record, "version_group_id")) is None
        }
    )
    multiple_current = sum(
        issue.get("issue_type") == "multiple_current_versions" for issue in version
    )
    missing_version = sum(
        issue.get("issue_type") == "missing_version_in_multiversion_group" for issue in version
    )
    invalid_sequence = sum(
        issue.get("issue_type") in {"duplicate_version_number", "version_sequence_gap"}
        for issue in version
    )
    relation_candidates: Counter[str] = Counter()
    relation_candidate_documents: set[str] = set()
    for record in records:
        if record.record_type != "chunk":
            continue
        relation_type = _first_value(
            record,
            "pre_embedding_quality.relation_type",
            "metadata.pre_embedding_quality.relation_type",
        )
        if classify_missing(relation_type) is None:
            relation_candidates[str(relation_type)] += 1
            if record.document_id:
                relation_candidate_documents.add(record.document_id)
    issue_families = {
        "consistency": consistency,
        "duplicate_ids": duplicates,
        "referential": referential,
        "temporal": temporal,
        "version": version,
        "conflicts": conflicts,
        "outliers": outliers,
    }
    critical_issues = [
        {
            "family": family,
            "issue_type": issue.get("issue_type"),
            "field_name": issue.get("field_name"),
            "record_id": issue.get("record_id"),
            "document_id": issue.get("document_id"),
        }
        for family, family_issues in issue_families.items()
        for issue in family_issues
        if str(issue.get("severity")) == "critical"
    ]
    limitations = [
        "Semantic synonym equivalence requires a reviewed vocabulary or human annotation.",
        "Referential checks are bounded to records present in this export snapshot.",
        "Structural conflict checks do not establish whether natural-language claims agree.",
    ]
    if "sample_data" in input_name or "sample_input" in input_name:
        limitations.append(
            "The bundled sample is a tool smoke test, not a production-corpus result."
        )
    else:
        limitations.append(
            "Snapshot consistency and completeness must be read from the export manifest."
        )
    return {
        "audit_name": "metadata-current-baseline",
        "audit_version": "v1",
        "created_at": datetime.now(UTC).isoformat(),
        "input": input_name,
        "record_count": len(records),
        "document_count": document_count,
        "chunk_count": chunk_count,
        "audited_field_scope_count": len(field_summary),
        "issue_counts": {
            "consistency": len(consistency),
            "duplicate_ids": len(duplicates),
            "referential": len(referential),
            "temporal": len(temporal),
            "version": len(version),
            "conflicts": len(conflicts),
            "outliers": len(outliers),
            "critical": critical,
        },
        "version_metrics": {
            "version_group_count": version_group_count,
            "multiple_active_version_rate": _ratio(multiple_current, version_group_count),
            "missing_version_rate": _ratio(missing_version, document_count),
            "invalid_version_sequence_rate": _ratio(invalid_sequence, version_group_count),
        },
        "quality_relation_candidates": {
            "chunk_count": sum(relation_candidates.values()),
            "source_document_count": len(relation_candidate_documents),
            "by_relation_type": dict(sorted(relation_candidates.items())),
            "confirmation_state": "candidate_only",
        },
        "critical_issues": critical_issues[:100],
        "limitations": limitations,
    }


def _render_report(
    summary: Mapping[str, object],
    field_summary: Sequence[Mapping[str, object]],
    schema: Sequence[SchemaField],
) -> str:
    populated = [row for row in field_summary if _metric_int(row.get("total_records")) > 0]
    ranked_coverage = sorted(
        populated,
        key=lambda row: (_metric_float(row.get("valid_coverage")), str(row.get("field_name"))),
    )
    ranked_validity = sorted(
        (row for row in populated if _metric_int(row.get("non_empty_count")) > 0),
        key=lambda row: (
            _metric_float(row.get("validity"), -1.0),
            str(row.get("field_name")),
        ),
    )
    best = list(reversed(ranked_coverage[-5:]))
    worst_coverage = ranked_coverage[:5]
    worst_validity = ranked_validity[:5]
    if worst_validity and all(
        _metric_float(row.get("validity")) >= 1.0 for row in worst_validity
    ):
        validity_lines = ["- All non-empty values passed the schema validity rules."]
    else:
        validity_lines = _metric_lines(worst_validity, "validity")
    issue_counts = summary.get("issue_counts", {})
    if not isinstance(issue_counts, Mapping):
        issue_counts = {}
    critical_issues = summary.get("critical_issues", [])
    if not isinstance(critical_issues, list):
        critical_issues = []
    limitations = summary.get("limitations", [])
    if not isinstance(limitations, list):
        limitations = []
    quality_candidates = summary.get("quality_relation_candidates", {})
    if not isinstance(quality_candidates, Mapping):
        quality_candidates = {}
    candidate_types = quality_candidates.get("by_relation_type", {})
    if not isinstance(candidate_types, Mapping):
        candidate_types = {}
    fields_by_name = {field.field_name: field for field in schema}
    retrieval_risks = [
        row
        for row in populated
        if (
            (field := fields_by_name.get(str(row.get("field_name"))))
            and (
                field.used_in_embedding
                or field.used_in_boost
                or (field.used_in_filter and field.required)
            )
            and _metric_float(row.get("valid_coverage")) < 1.0
        )
    ]
    citation_risks = [
        row
        for row in populated
        if (field := fields_by_name.get(str(row.get("field_name"))))
        and field.used_in_citation
        and _metric_float(row.get("valid_coverage")) < 1.0
    ]
    filter_risks = [
        row
        for row in populated
        if (field := fields_by_name.get(str(row.get("field_name"))))
        and field.used_in_filter
        and field.required
        and _metric_float(row.get("valid_coverage")) < 1.0
    ]
    return "\n".join(
        [
            "# Metadata audit report",
            "",
            f"- Audit: `{summary.get('audit_name')}` / `{summary.get('audit_version')}`",
            f"- Input: `{summary.get('input')}`",
            f"- Documents: **{summary.get('document_count')}**",
            f"- Chunks: **{summary.get('chunk_count')}**",
            f"- Generated at: `{summary.get('created_at')}`",
            "",
            "## Highest valid coverage",
            "",
            *_metric_lines(best, "valid_coverage"),
            "",
            "## Lowest valid coverage",
            "",
            *_metric_lines(worst_coverage, "valid_coverage"),
            "",
            "## Lowest validity",
            "",
            *validity_lines,
            "",
            "## Structural issue counts",
            "",
            *[f"- `{key}`: {value}" for key, value in sorted(issue_counts.items())],
            "",
            "## Critical errors",
            "",
            *(
                [
                    f"- `{item.get('family')}.{item.get('issue_type')}` on "
                    f"`{item.get('field_name')}` record `{item.get('record_id')}`"
                    for item in critical_issues[:20]
                    if isinstance(item, Mapping)
                ]
                or ["- No critical structural error detected."]
            ),
            "",
            "## Pre-embedding quality candidates",
            "",
            f"- Candidate chunks: **{quality_candidates.get('chunk_count', 0)}** across "
            f"**{quality_candidates.get('source_document_count', 0)}** source documents.",
            *(
                [f"- `{key}`: {value}" for key, value in sorted(candidate_types.items())]
                or ["- No persisted relation candidate in this export."]
            ),
            "- These are detector candidates/actions, not confirmed semantic truth.",
            "",
            "## Retrieval risks",
            "",
            *_risk_lines(retrieval_risks),
            "",
            "## Citation risks",
            "",
            *_risk_lines(citation_risks),
            "",
            "## Version and hard-filter risks",
            "",
            f"- Version issues: **{issue_counts.get('version', 0)}**",
            f"- Conflict issues: **{issue_counts.get('conflicts', 0)}**",
            f"- Referential issues: **{issue_counts.get('referential', 0)}**",
            *(
                _risk_lines(filter_risks)
                if filter_risks
                else ["- No incomplete active filter field in this export."]
            ),
            "",
            "## Manual checks required",
            "",
            "- Review semantic correctness of title, document type, section path and LLM context.",
            "- Review synonym and department-name equivalence; this audit does not "
            "guess semantics.",
            "- Review all version, conflict and referential rows before trusting hard filters.",
            "- Confirm that the export is a complete, point-in-time corpus snapshot.",
            "",
            "## Known limitations",
            "",
            *[f"- {item}" for item in limitations],
            "",
            "## Interpretation boundary",
            "",
            "This report measures the current metadata only. It does not propose a "
            "replacement schema.",
        ]
    )


def _metric_lines(rows: Sequence[Mapping[str, object]], metric: str) -> list[str]:
    if not rows:
        return ["- No applicable fields."]
    return [
        f"- `{row.get('record_type')}.{row.get('field_name')}`: {row.get(metric)}" for row in rows
    ]


def _risk_lines(rows: Sequence[Mapping[str, object]]) -> list[str]:
    if not rows:
        return ["- No incomplete field detected in this export."]
    return [
        f"- `{row.get('record_type')}.{row.get('field_name')}` valid coverage="
        f"{row.get('valid_coverage')}"
        for row in sorted(
            rows,
            key=lambda item: (
                _metric_float(item.get("valid_coverage")),
                str(item.get("field_name")),
            ),
        )[:20]
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="UTF-8 JSONL metadata export")
    parser.add_argument("--schema", type=Path, required=True, help="Metadata schema CSV")
    parser.add_argument("--output-dir", type=Path, required=True, help="Result directory")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing existing generated result files",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        LOGGER.info("Loading schema from %s", args.schema)
        schema = load_schema(args.schema)
        LOGGER.info("Loading records from %s", args.input)
        records = load_records(args.input)
        LOGGER.info("Auditing %d records and %d inventory fields", len(records), len(schema))
        result = audit_records(records, schema, input_name=str(args.input))
        write_audit_result(result, args.output_dir, overwrite=args.overwrite)
    except MetadataBaselineError as exc:
        LOGGER.error("Metadata audit failed: %s", exc)
        return 2
    except Exception:
        LOGGER.exception("Unexpected metadata audit failure")
        return 1
    LOGGER.info("Audit complete: %s", args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuditResult",
    "audit_consistency",
    "audit_duplicate_ids",
    "audit_field_quality",
    "audit_metadata_conflicts",
    "audit_outliers",
    "audit_records",
    "audit_referential_integrity",
    "audit_temporal_consistency",
    "audit_version_consistency",
    "main",
    "write_audit_result",
]
