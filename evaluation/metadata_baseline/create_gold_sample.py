"""Create a deterministic, stratified metadata annotation sample.

Sampling is performed over records, then expanded to field-level annotation
rows. This preserves document/chunk context while allowing field-specific gold
values and two independent annotators.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import math
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
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
    generation_family,
    load_records,
    load_schema,
    stable_value,
    write_csv,
    write_json,
)

LOGGER = logging.getLogger("metadata_baseline.gold_sample")

ANNOTATION_COLUMNS = (
    "sample_id",
    "record_id",
    "record_type",
    "document_id",
    "chunk_id",
    "document_type",
    "source",
    "version_group_id",
    "document_version",
    "status",
    "quality_status",
    "content_excerpt",
    "parent_context",
    "field_name",
    "generation_method",
    "generation_family",
    "current_value",
    "gold_value",
    "is_correct",
    "error_type",
    "confidence",
    "annotator",
    "annotation_notes",
    "review_status",
    "sampling_strata",
    "annotator_a_value",
    "annotator_a_is_correct",
    "annotator_a_error_type",
    "annotator_a_confidence",
    "annotator_a_notes",
    "annotator_b_value",
    "annotator_b_is_correct",
    "annotator_b_error_type",
    "annotator_b_confidence",
    "annotator_b_notes",
    "agreement",
    "adjudicated_value",
    "adjudicated_is_correct",
    "adjudicator",
    "adjudication_notes",
)

ISSUE_FILES = (
    "metadata_validity.csv",
    "metadata_consistency_issues.csv",
    "metadata_duplicate_ids.csv",
    "metadata_referential_errors.csv",
    "metadata_temporal_errors.csv",
    "metadata_version_errors.csv",
    "metadata_conflicts.csv",
    "metadata_outliers.csv",
)

_IMPORTANCE_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# These existing lifecycle fields carry the highest wrong-version/filter risk.
# Security identifiers would also be selected if the schema made them human-
# annotatable; in the current repository they remain source-authoritative.
_FIELD_OVERSAMPLE_ORDER = (
    "status",
    "quality_status",
    "version_group_id",
    "version_number",
    "is_current",
    "effective_from",
    "effective_to",
    "canonical_document_id",
    "supersedes_document_id",
    "owner_id",
    "notebook_id",
)


def collect_flagged_records(audit_dir: Path | None) -> dict[str, set[str]]:
    """Collect record IDs from prior audit issue files without requiring them."""

    flags: dict[str, set[str]] = defaultdict(set)
    if audit_dir is None:
        return flags
    for filename in ISSUE_FILES:
        path = audit_dir / filename
        if not path.exists():
            continue
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise MetadataBaselineError(f"Cannot read audit issue file: {path}") from exc
        with handle:
            for row in csv.DictReader(handle):
                if row.get("row_type") == "summary":
                    continue
                record_id = str(row.get("record_id") or "").strip()
                if not record_id:
                    continue
                issue_type = str(row.get("issue_type") or row.get("error") or filename).strip()
                flags[record_id].add(issue_type)
    return flags


def select_records(
    records: Sequence[CorpusRecord],
    schema: Sequence[SchemaField],
    *,
    sample_size: int,
    seed: int,
    flagged: Mapping[str, set[str]] | None = None,
) -> tuple[CorpusRecord, ...]:
    """Select records with issue oversampling and round-robin strata coverage."""

    if sample_size <= 0:
        raise MetadataBaselineError("sample_size must be > 0")
    if not records:
        return ()
    target = min(sample_size, len(records))
    rng = random.Random(seed)
    flagged = flagged or {}
    ordered = sorted(records, key=lambda record: (record.record_type, record.record_id))
    by_id = {record.record_id: record for record in ordered}
    selected: list[CorpusRecord] = []
    selected_ids: set[str] = set()

    issue_candidates = [by_id[record_id] for record_id in flagged if record_id in by_id]
    rng.shuffle(issue_candidates)
    issue_target = min(len(issue_candidates), math.ceil(target * 0.5))
    for record in issue_candidates[:issue_target]:
        selected.append(record)
        selected_ids.add(record.record_id)

    strata: dict[str, list[CorpusRecord]] = defaultdict(list)
    rarity = _rare_record_ids(ordered, schema)
    global_labels = _global_record_labels(ordered)
    documents_by_id = {
        record.document_id: record
        for record in ordered
        if record.record_type == "document" and record.document_id
    }
    for record in ordered:
        labels = record_strata(
            record,
            flagged.get(record.record_id, set()),
            schema=schema,
            parent=documents_by_id.get(record.document_id or ""),
        )
        labels.update(global_labels.get(record.record_id, set()))
        if record.record_id in rarity:
            labels.add("rare_metadata:true")
        for label in labels:
            strata[label].append(record)
    for bucket in strata.values():
        rng.shuffle(bucket)

    while len(selected) < target:
        progress = False
        for label in sorted(strata, key=lambda item: (len(strata[item]), item)):
            bucket = strata[label]
            while bucket and bucket[-1].record_id in selected_ids:
                bucket.pop()
            if not bucket:
                continue
            record = bucket.pop()
            selected.append(record)
            selected_ids.add(record.record_id)
            progress = True
            if len(selected) >= target:
                break
        if not progress:
            break

    if len(selected) < target:
        remaining = [record for record in ordered if record.record_id not in selected_ids]
        rng.shuffle(remaining)
        selected.extend(remaining[: target - len(selected)])
    return tuple(selected)


def record_strata(
    record: CorpusRecord,
    issue_types: Iterable[str] = (),
    *,
    schema: Sequence[SchemaField] = (),
    parent: CorpusRecord | None = None,
) -> set[str]:
    """Return explicit strata labels used to explain why a record was sampled."""

    labels = {f"record_type:{record.record_type}"}
    for label, paths in (
        ("document_type", ("retrieval_metadata.document_type", "document_type")),
        (
            "source",
            (
                "source",
                "provenance_metadata.source",
                "storage_object_path",
                "original_filename",
                "storage_bucket",
            ),
        ),
        ("year", ("effective_from", "created_at")),
        ("version", ("version_number", "document_version")),
        ("status", ("status",)),
        ("quality_status", ("quality_status",)),
        (
            "department",
            (
                "department",
                "retrieval_metadata.department",
                "authority_metadata.department",
            ),
        ),
    ):
        value = _first_with_parent(record, parent, *paths)
        if classify_missing(value) is None:
            text = str(value)
            labels.add(f"{label}:{text[:4] if label == 'year' else text}")
    applicable_fields = [field for field in schema if field.applies_to(record.record_type)]
    populated_annotation_fields = 0
    annotation_field_count = 0
    for field in applicable_fields:
        value = record.get(field)
        if field.annotation_candidate:
            annotation_field_count += 1
            if classify_missing(value) is None:
                populated_annotation_fields += 1
        if classify_missing(value) is None:
            labels.add(f"generator:{generation_family(field)}")
    if str(_first(record, "context_enrichment.status")).casefold() == "generated":
        labels.add("generator:llm")
    if classify_missing(_first(record, "parser_name")) is None:
        labels.add("generator:parser")
    if annotation_field_count and populated_annotation_fields / annotation_field_count < 0.6:
        labels.add("coverage:low")
    confidence = _first(
        record,
        "pre_embedding_quality.confidence",
        "analysis_confidence",
    )
    if isinstance(confidence, int | float) and not isinstance(confidence, bool):
        bucket = "low" if confidence < 0.5 else "medium" if confidence < 0.8 else "high"
        labels.add(f"metadata_confidence:{bucket}")
    for issue_type in issue_types:
        labels.add(f"audit_issue:{issue_type}")
    return labels


def create_annotation_rows(
    selected: Sequence[CorpusRecord],
    all_records: Sequence[CorpusRecord],
    schema: Sequence[SchemaField],
    *,
    flagged: Mapping[str, set[str]] | None = None,
    fields_per_record: int = 8,
) -> list[dict[str, object]]:
    """Expand selected records into annotation-ready field rows with context."""

    if fields_per_record <= 0:
        raise MetadataBaselineError("fields_per_record must be > 0")
    flagged = flagged or {}
    chunks_by_document: dict[str, list[CorpusRecord]] = defaultdict(list)
    documents_by_id: dict[str, CorpusRecord] = {}
    for record in all_records:
        if record.record_type == "chunk" and record.document_id:
            chunks_by_document[record.document_id].append(record)
        if record.record_type == "document" and record.document_id:
            documents_by_id[record.document_id] = record
    for chunks in chunks_by_document.values():
        chunks.sort(key=_chunk_sort_key)

    rows: list[dict[str, object]] = []
    sample_counter = 0
    global_labels = _global_record_labels(all_records)
    for record in selected:
        candidate_fields = [
            field
            for field in schema
            if field.annotation_candidate and field.applies_to(record.record_type)
        ]
        candidate_fields.sort(
            key=lambda field: (
                _IMPORTANCE_ORDER.get(field.importance.casefold(), 9),
                0 if "llm" in field.generation_method.casefold() else 1,
                field.field_name,
            )
        )
        selected_fields = _balanced_fields(candidate_fields, fields_per_record)
        parent = documents_by_id.get(record.document_id or "")
        strata = record_strata(
            record,
            flagged.get(record.record_id, set()),
            schema=schema,
            parent=parent,
        )
        strata.update(global_labels.get(record.record_id, set()))
        for field in selected_fields:
            sample_counter += 1
            value = record.get(field)
            rows.append(
                {
                    "sample_id": f"META-{sample_counter:06d}",
                    "record_id": record.record_id,
                    "record_type": record.record_type,
                    "document_id": record.document_id or "",
                    "chunk_id": record.chunk_id or "",
                    "document_type": _display_value(
                        _first_with_parent(
                            record,
                            parent,
                            "retrieval_metadata.document_type",
                            "document_type",
                        )
                    ),
                    "source": _display_value(
                        _first_with_parent(
                            record,
                            parent,
                            "source",
                            "provenance_metadata.source",
                            "storage_object_path",
                            "original_filename",
                            "storage_bucket",
                        )
                    ),
                    "version_group_id": _display_value(
                        _first(record, "version_group_id")
                        if record.record_type == "document"
                        else _first(parent, "version_group_id")
                        if parent
                        else MISSING
                    ),
                    "document_version": _display_value(
                        _first_with_parent(
                            record,
                            parent,
                            "version_number",
                            "document_version",
                        )
                    ),
                    "status": _display_value(
                        _first_with_parent(record, parent, "status")
                    ),
                    "quality_status": _display_value(
                        _first_with_parent(record, parent, "quality_status")
                    ),
                    "content_excerpt": _excerpt(record.content, 700),
                    "parent_context": _parent_context(
                        record,
                        parent,
                        chunks_by_document.get(record.document_id or "", []),
                    ),
                    "field_name": field.field_name,
                    "generation_method": field.generation_method,
                    "generation_family": generation_family(field),
                    "current_value": _display_value(value),
                    "gold_value": "",
                    "is_correct": "",
                    "error_type": "",
                    "confidence": "",
                    "annotator": "",
                    "annotation_notes": "",
                    "review_status": "pending",
                    "sampling_strata": "|".join(sorted(strata)),
                    "annotator_a_value": "",
                    "annotator_a_is_correct": "",
                    "annotator_a_error_type": "",
                    "annotator_a_confidence": "",
                    "annotator_a_notes": "",
                    "annotator_b_value": "",
                    "annotator_b_is_correct": "",
                    "annotator_b_error_type": "",
                    "annotator_b_confidence": "",
                    "annotator_b_notes": "",
                    "agreement": "",
                    "adjudicated_value": "",
                    "adjudicated_is_correct": "",
                    "adjudicator": "",
                    "adjudication_notes": "",
                }
            )
    return rows


def _rare_record_ids(records: Sequence[CorpusRecord], schema: Sequence[SchemaField]) -> set[str]:
    values: dict[str, Counter[str]] = defaultdict(Counter)
    by_record: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for field in schema:
        if not field.annotation_candidate:
            continue
        for record in records:
            if not field.applies_to(record.record_type):
                continue
            value = record.get(field)
            if classify_missing(value) is not None:
                continue
            serialized = stable_value(value)
            key = f"{record.record_type}.{field.field_name}"
            values[key][serialized] += 1
            by_record[record.record_id].append((key, serialized))
    return {
        record_id
        for record_id, field_values in by_record.items()
        if any(values[key][value] == 1 for key, value in field_values)
    }


def _global_record_labels(records: Sequence[CorpusRecord]) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = defaultdict(set)
    documents_by_id: dict[str, CorpusRecord] = {}
    groups: dict[str, list[CorpusRecord]] = defaultdict(list)
    for record in records:
        if record.record_type != "document" or not record.document_id:
            continue
        documents_by_id[record.document_id] = record
        group_id = _first(record, "version_group_id")
        if classify_missing(group_id) is None:
            groups[str(group_id)].append(record)
    multiversion_ids = {
        record.record_id for group in groups.values() if len(group) > 1 for record in group
    }
    for record in records:
        parent = documents_by_id.get(record.document_id or "")
        if record.record_id in multiversion_ids or (
            parent is not None and parent.record_id in multiversion_ids
        ):
            labels[record.record_id].add("version_group:multiple")
    return labels


def _balanced_fields(fields: Sequence[SchemaField], limit: int) -> tuple[SchemaField, ...]:
    selected: list[SchemaField] = []
    by_name = {field.field_name: field for field in fields}
    for field_name in _FIELD_OVERSAMPLE_ORDER:
        field = by_name.get(field_name)
        if field is not None:
            selected.append(field)
            if len(selected) >= limit:
                return tuple(selected)

    methods_seen: set[str] = set()
    methods_seen.update(field.generation_method for field in selected)
    for field in fields:
        if field not in selected and field.generation_method not in methods_seen:
            selected.append(field)
            methods_seen.add(field.generation_method)
            if len(selected) >= limit:
                return tuple(selected)
    for field in fields:
        if field not in selected:
            selected.append(field)
            if len(selected) >= limit:
                break
    return tuple(selected)


def _parent_context(
    record: CorpusRecord,
    parent: CorpusRecord | None,
    sibling_chunks: Sequence[CorpusRecord],
) -> str:
    parts: list[str] = []
    if parent:
        title = _first(parent, "original_filename", "title")
        if classify_missing(title) is None:
            parts.append(f"Document: {title}")
        metadata_parts: list[str] = []
        for label, paths in (
            ("status", ("status",)),
            ("quality_status", ("quality_status",)),
            ("version", ("version_number",)),
            ("mime_type", ("mime_type",)),
            ("source", ("storage_object_path", "original_filename")),
        ):
            value = _first(parent, *paths)
            if classify_missing(value) is None:
                metadata_parts.append(f"{label}={_display_value(value)}")
        if metadata_parts:
            parts.append("Parent metadata: " + "; ".join(metadata_parts))
    section = _first(record, "retrieval_metadata.section_path", "section_title")
    if classify_missing(section) is None:
        parts.append(f"Section: {_display_value(section)}")
    if record.record_type == "chunk" and sibling_chunks:
        try:
            position = next(
                index
                for index, sibling in enumerate(sibling_chunks)
                if sibling.record_id == record.record_id
            )
        except StopIteration:
            position = -1
        for label, index in (("Previous", position - 1), ("Next", position + 1)):
            if 0 <= index < len(sibling_chunks):
                sibling = sibling_chunks[index]
                heading = _first(sibling, "section_title", "retrieval_metadata.section_title")
                parts.append(
                    f"{label}: heading={_display_value(heading)}; "
                    f"content={_excerpt(sibling.content, 180)}"
                )
    return "\n".join(parts)


def _chunk_sort_key(record: CorpusRecord) -> tuple[int, str]:
    value = _first(record, "chunk_index")
    return (value if isinstance(value, int) else 10**9, record.record_id)


def _first(record: CorpusRecord | None, *paths: str) -> object:
    if record is None:
        return MISSING
    for path in paths:
        value = record.get(path)
        if value is not MISSING:
            return value
    return MISSING


def _first_with_parent(
    record: CorpusRecord,
    parent: CorpusRecord | None,
    *paths: str,
) -> object:
    value = _first(record, *paths)
    return _first(parent, *paths) if classify_missing(value) is not None else value


def _display_value(value: object) -> str:
    if value is MISSING:
        return ""
    return stable_value(value)


def _excerpt(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3] + "..."


def _build_parser() -> argparse.ArgumentParser:
    default_schema = Path(__file__).with_name("metadata_schema.csv")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=default_schema)
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--sample-size", type=int, default=300)
    parser.add_argument("--fields-per-record", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
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
        manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
        ensure_outputs((args.output, manifest_path), overwrite=args.overwrite)
        schema = load_schema(args.schema)
        records = load_records(args.input)
        flags = collect_flagged_records(args.audit_dir)
        selected = select_records(
            records,
            schema,
            sample_size=args.sample_size,
            seed=args.random_seed,
            flagged=flags,
        )
        rows = create_annotation_rows(
            selected,
            records,
            schema,
            flagged=flags,
            fields_per_record=args.fields_per_record,
        )
        write_csv(args.output, rows, ANNOTATION_COLUMNS)
        write_json(
            manifest_path,
            {
                "input": str(args.input),
                "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
                "schema": str(args.schema),
                "schema_sha256": hashlib.sha256(args.schema.read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "random_seed": args.random_seed,
                "requested_sample_size": args.sample_size,
                "selected_record_count": len(selected),
                "annotation_row_count": len(rows),
                "fields_per_record": args.fields_per_record,
                "audit_dir": str(args.audit_dir) if args.audit_dir else None,
            },
        )
    except MetadataBaselineError as exc:
        LOGGER.error("Gold-sample creation failed: %s", exc)
        return 2
    except Exception:
        LOGGER.exception("Unexpected gold-sample creation failure")
        return 1
    LOGGER.info(
        "Created %d annotation rows from %d unique records at %s",
        len(rows),
        len(selected),
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ANNOTATION_COLUMNS",
    "collect_flagged_records",
    "create_annotation_rows",
    "main",
    "record_strata",
    "select_records",
]
