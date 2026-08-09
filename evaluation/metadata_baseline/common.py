"""Shared, dependency-free primitives for metadata baseline tools.

The helpers in this module deliberately operate on exported JSONL files. They
never import a production repository adapter and never mutate source records.
"""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

MISSING = object()
PLACEHOLDER_VALUES = frozenset(
    {
        "-",
        "n/a",
        "na",
        "none",
        "not available",
        "null",
        "unknown",
        "undefined",
    }
)
MUTABILITY_VALUES = frozenset({"false", "true", "recomputed_on_reingestion"})

SCHEMA_REQUIRED_COLUMNS = frozenset(
    {
        "field_name",
        "category",
        "level",
        "actual_data_type",
        "expected_data_type",
        "required",
        "source_generator",
        "generation_method",
        "allowed_values",
        "default_value",
        "normalized",
        "mutable_over_time",
        "used_in_embedding",
        "used_in_filter",
        "used_in_boost",
        "used_in_reranker",
        "used_in_citation",
        "used_in_access_control",
        "usage_locations",
        "importance",
        "risk_if_missing",
        "risk_if_incorrect",
        "notes",
    }
)


class MetadataBaselineError(RuntimeError):
    """Raised for invalid input or unsafe output operations."""


def parse_bool(value: object, *, default: bool = False) -> bool:
    """Parse a CSV/config boolean without Python's truthy-string behavior."""

    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise MetadataBaselineError(f"Invalid boolean value: {value!r}")


def _optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text else None


def _optional_float(value: object) -> float | None:
    text = str(value or "").strip()
    return float(text) if text else None


@dataclass(frozen=True, slots=True)
class SchemaField:
    """One metadata field contract loaded from ``metadata_schema.csv``."""

    field_name: str
    category: str
    level: str
    actual_data_type: str
    expected_data_type: str
    required: bool
    source_generator: str
    generation_method: str
    allowed_values: tuple[str, ...]
    default_value: str
    normalized: bool
    used_in_embedding: bool
    used_in_filter: bool
    used_in_boost: bool
    used_in_reranker: bool
    used_in_citation: bool
    used_in_access_control: bool
    usage_locations: str
    importance: str
    risk_if_missing: str
    risk_if_incorrect: str
    notes: str
    path_aliases: tuple[str, ...] = ()
    regex: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    max_length: int | None = None
    max_items: int | None = None
    consistency_scope: str = ""
    unique_scope: str = ""
    reference_target: str = ""
    conflict_group: bool = False
    conflict_sensitive: bool = False
    annotation_candidate: bool = False
    ordinal_values: tuple[str, ...] = ()
    conflict_roles: tuple[str, ...] = ()
    mutable_over_time: str = "false"

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.field_name, *self.path_aliases)))

    def applies_to(self, record_type: str) -> bool:
        """Return whether this persisted field applies to a corpus record."""

        levels = {item.strip() for item in self.level.split("|") if item.strip()}
        return record_type in levels or "both" in levels


def load_schema(path: Path) -> tuple[SchemaField, ...]:
    """Load and validate the metadata inventory used by every tool."""

    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise MetadataBaselineError(f"Cannot read schema: {path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or ())
        missing = sorted(SCHEMA_REQUIRED_COLUMNS - headers)
        if missing:
            raise MetadataBaselineError(f"Schema is missing required columns: {', '.join(missing)}")
        fields: list[SchemaField] = []
        for row_number, row in enumerate(reader, start=2):
            name = str(row.get("field_name") or "").strip()
            if not name:
                raise MetadataBaselineError(f"Schema row {row_number} has no field_name")
            try:
                fields.append(
                    SchemaField(
                        field_name=name,
                        category=str(row.get("category") or "").strip(),
                        level=str(row.get("level") or "").strip(),
                        actual_data_type=str(row.get("actual_data_type") or "").strip(),
                        expected_data_type=str(row.get("expected_data_type") or "").strip(),
                        required=parse_bool(row.get("required")),
                        source_generator=str(row.get("source_generator") or "").strip(),
                        generation_method=str(row.get("generation_method") or "").strip(),
                        allowed_values=_pipe_values(row.get("allowed_values")),
                        default_value=str(row.get("default_value") or "").strip(),
                        normalized=parse_bool(row.get("normalized")),
                        used_in_embedding=parse_bool(row.get("used_in_embedding")),
                        used_in_filter=parse_bool(row.get("used_in_filter")),
                        used_in_boost=parse_bool(row.get("used_in_boost")),
                        used_in_reranker=parse_bool(row.get("used_in_reranker")),
                        used_in_citation=parse_bool(row.get("used_in_citation")),
                        used_in_access_control=parse_bool(row.get("used_in_access_control")),
                        usage_locations=str(row.get("usage_locations") or "").strip(),
                        importance=str(row.get("importance") or "").strip(),
                        risk_if_missing=str(row.get("risk_if_missing") or "").strip(),
                        risk_if_incorrect=str(row.get("risk_if_incorrect") or "").strip(),
                        notes=str(row.get("notes") or "").strip(),
                        path_aliases=_pipe_values(row.get("path_aliases")),
                        regex=str(row.get("regex") or "").strip() or None,
                        min_value=_optional_float(row.get("min_value")),
                        max_value=_optional_float(row.get("max_value")),
                        max_length=_optional_int(row.get("max_length")),
                        max_items=_optional_int(row.get("max_items")),
                        consistency_scope=str(row.get("consistency_scope") or "").strip(),
                        unique_scope=str(row.get("unique_scope") or "").strip(),
                        reference_target=str(row.get("reference_target") or "").strip(),
                        conflict_group=parse_bool(row.get("conflict_group")),
                        conflict_sensitive=parse_bool(row.get("conflict_sensitive")),
                        annotation_candidate=parse_bool(row.get("annotation_candidate")),
                        ordinal_values=_pipe_values(row.get("ordinal_values")),
                        conflict_roles=_pipe_values(row.get("conflict_roles")),
                        mutable_over_time=str(row.get("mutable_over_time") or "").strip(),
                    )
                )
            except (TypeError, ValueError, MetadataBaselineError) as exc:
                raise MetadataBaselineError(f"Invalid schema row {row_number}: {exc}") from exc
    duplicates = _duplicates(field.field_name for field in fields)
    if duplicates:
        raise MetadataBaselineError(f"Duplicate schema fields: {', '.join(duplicates)}")
    invalid_mutability = sorted(
        field.field_name
        for field in fields
        if field.mutable_over_time not in MUTABILITY_VALUES
    )
    if invalid_mutability:
        raise MetadataBaselineError(
            "Schema fields have invalid mutable_over_time values: "
            + ", ".join(invalid_mutability)
        )
    return tuple(fields)


def _pipe_values(value: object) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split("|") if item.strip())


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    """A normalized view over one exported document or chunk JSON object."""

    record_type: str
    record_id: str
    document_id: str | None
    chunk_id: str | None
    content: str
    raw: Mapping[str, Any]
    line_number: int

    def get(self, field: SchemaField | str, default: object = MISSING) -> object:
        """Resolve a canonical field against top-level and nested metadata paths."""

        paths = field.paths if isinstance(field, SchemaField) else (field,)
        metadata = self.raw.get("metadata")
        roots: tuple[Mapping[str, Any], ...] = (
            self.raw,
            metadata if isinstance(metadata, Mapping) else {},
        )
        for path in paths:
            for root in roots:
                value = lookup_path(root, path)
                if value is not MISSING:
                    return value
        return default


def load_records(path: Path) -> tuple[CorpusRecord, ...]:
    """Read a UTF-8 JSONL export and reject malformed or ambiguous records."""

    records: list[CorpusRecord] = []
    try:
        handle = path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        raise MetadataBaselineError(f"Cannot read metadata export: {path}") from exc
    with handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MetadataBaselineError(
                    f"Invalid JSON at {path}:{line_number}: {exc.msg}"
                ) from exc
            if not isinstance(raw, dict):
                raise MetadataBaselineError(f"Record at {path}:{line_number} is not an object")
            record_type = str(raw.get("record_type") or "").strip().casefold()
            if record_type not in {"document", "chunk"}:
                raise MetadataBaselineError(
                    f"Record at {path}:{line_number} needs record_type=document|chunk"
                )
            document_id = _clean_identifier(raw.get("document_id"))
            chunk_id = _clean_identifier(raw.get("chunk_id"))
            fallback_id = document_id if record_type == "document" else chunk_id
            record_id = _clean_identifier(raw.get("record_id") or raw.get("id") or fallback_id)
            if not record_id:
                raise MetadataBaselineError(f"Record at {path}:{line_number} has no record_id")
            if record_type == "document" and not document_id:
                document_id = record_id
            if record_type == "chunk" and not chunk_id:
                chunk_id = record_id
            content = str(raw.get("content") or "")
            metadata = raw.get("metadata", {})
            if metadata is not None and not isinstance(metadata, dict):
                raise MetadataBaselineError(f"metadata at {path}:{line_number} must be an object")
            records.append(
                CorpusRecord(
                    record_type=record_type,
                    record_id=record_id,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    content=content,
                    raw=raw,
                    line_number=line_number,
                )
            )
    if not records:
        raise MetadataBaselineError(f"Metadata export is empty: {path}")
    return tuple(records)


def _clean_identifier(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def lookup_path(root: Mapping[str, Any], path: str) -> object:
    """Look up a dotted path without conflating a present null with absence."""

    current: object = root
    for part in (item for item in path.split(".") if item):
        if not isinstance(current, Mapping) or part not in current:
            return MISSING
        current = current[part]
    return current


def classify_missing(value: object) -> str | None:
    """Return the reason a value is unusable, or ``None`` when populated."""

    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "empty_string"
        if stripped.casefold() in PLACEHOLDER_VALUES:
            return "placeholder"
    if isinstance(value, Sequence) and not isinstance(value, str | bytes) and not value:
        return "empty_list"
    if isinstance(value, Mapping) and not value:
        return "empty_object"
    return None


def validate_value(field: SchemaField, value: object) -> tuple[str, ...]:
    """Validate one populated value using only rules declared in the schema."""

    errors: list[str] = []
    expected = field.expected_data_type.strip().casefold()
    if not _matches_type(value, expected):
        return (f"expected_{expected or 'unspecified'}",)
    allowed_surface = str(value).casefold() if isinstance(value, bool) else str(value)
    if field.allowed_values and allowed_surface not in field.allowed_values:
        errors.append("not_in_allowed_values")
    if field.regex and isinstance(value, str) and re.fullmatch(field.regex, value) is None:
        errors.append("regex_mismatch")
    if (
        field.min_value is not None
        and isinstance(value, int | float)
        and not isinstance(value, bool)
        and float(value) < field.min_value
    ):
        errors.append("below_min_value")
    if (
        field.max_value is not None
        and isinstance(value, int | float)
        and not isinstance(value, bool)
        and float(value) > field.max_value
    ):
        errors.append("above_max_value")
    if field.max_length is not None and isinstance(value, str) and len(value) > field.max_length:
        errors.append("too_long")
    if (
        field.max_items is not None
        and isinstance(value, Sequence)
        and not isinstance(value, str | bytes)
        and len(value) > field.max_items
    ):
        errors.append("too_many_items")
    return tuple(errors)


def _matches_type(value: object, expected: str) -> bool:
    options = {item.strip() for item in expected.split("|") if item.strip()}
    if not options or "any" in options:
        return True
    return any(_matches_single_type(value, option) for option in options)


def _matches_single_type(value: object, expected: str) -> bool:
    if expected in {"string", "text"}:
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected in {"number", "float"}:
        return _is_number(value)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, Sequence) and not isinstance(value, str | bytes)
    if expected == "array[string]":
        return (
            isinstance(value, Sequence)
            and not isinstance(value, str | bytes)
            and all(isinstance(item, str) for item in value)
        )
    if expected == "date":
        return isinstance(value, str) and parse_date(value) is not None
    if expected == "datetime":
        return isinstance(value, str) and parse_datetime(value) is not None
    if expected == "uuid":
        if not isinstance(value, str):
            return False
        try:
            UUID(value)
        except ValueError:
            return False
        return True
    if expected in {"url", "uri"}:
        return isinstance(value, str) and bool(urlparse(value).scheme)
    return True


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_date(value: object) -> date | None:
    """Parse strict ISO date/datetime values used by the current database."""

    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalized_surface(value: object) -> str:
    """Normalize representation for consistency grouping, not for mutation."""

    text = stable_value(value)
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def punctuation_insensitive_surface(value: object) -> str:
    normalized = normalized_surface(value)
    return "".join(character for character in normalized if character.isalnum())


def stable_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def entropy(values: Iterable[str]) -> float:
    counts: dict[str, int] = {}
    total = 0
    for value in values:
        counts[value] = counts.get(value, 0) + 1
        total += 1
    if not total:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def generation_family(field: SchemaField) -> str:
    """Collapse verbose provenance into stable audit strata."""

    surface = f"{field.source_generator} {field.generation_method}".casefold()
    if "llm" in surface or "openai" in surface:
        return "llm"
    if "parser" in surface or "ocr" in surface or "extract" in surface:
        return "parser"
    if "database" in surface or "auth" in surface or "server timestamp" in surface:
        return "database"
    if "user" in surface:
        return "user"
    rule_markers = (
        "rule",
        "deterministic",
        "hash",
        "fingerprint",
        "chunker",
        "classifier",
        "normalizer",
        "knowledge-quality",
        "uuidv5",
    )
    return "rule" if any(marker in surface for marker in rule_markers) else "source"


def ensure_outputs(paths: Iterable[Path], *, overwrite: bool) -> None:
    """Fail before writing anything when an output would be overwritten."""

    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        rendered = ", ".join(str(path) for path in existing[:5])
        raise MetadataBaselineError(
            f"Refusing to overwrite existing output(s): {rendered}. Pass --overwrite."
        )


def write_csv(path: Path, rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _duplicates(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


__all__ = [
    "MISSING",
    "CorpusRecord",
    "MetadataBaselineError",
    "SchemaField",
    "classify_missing",
    "ensure_outputs",
    "entropy",
    "generation_family",
    "load_records",
    "load_schema",
    "lookup_path",
    "normalized_surface",
    "parse_bool",
    "parse_date",
    "parse_datetime",
    "punctuation_insensitive_surface",
    "stable_value",
    "validate_value",
    "write_csv",
    "write_json",
    "write_text",
]
