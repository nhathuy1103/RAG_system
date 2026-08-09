"""Typed retrieval metadata with lossless support for additional JSON fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

type MetadataScalar = str | int | float | bool | None
type MetadataValue = MetadataScalar | list[MetadataValue] | dict[str, MetadataValue]

_INTEGER_KEYS = {"page_number", "document_version", "chunk_index", "year"}
_SEMANTIC_KEYS = {
    "title",
    "document_type",
    "language",
    "section_title",
    "section_path",
    "content_kind",
    "table_header",
    "keyword_aliases",
    "contextual_summary",
    "contextual_search_terms",
    "project_id",
    "project_code",
    "project_name",
    "project_aliases",
    "year",
    "data_period",
    "effective_status",
    "domain",
    "clause_type",
    "region",
    "region_code",
    "source",
    "source_code",
}


def _json_value(value: object) -> MetadataValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return [_json_value(item) for item in value]
    return str(value)


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if not isinstance(value, str | int | float):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class EvidenceMetadata(dict[str, MetadataValue]):
    """Dictionary-compatible metadata with typed access to retrieval fields."""

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object] | None = None,
        **overrides: object,
    ) -> EvidenceMetadata:
        raw: dict[str, object] = dict(value or {})
        raw.update({key: item for key, item in overrides.items() if item is not None})

        nested = raw.get("retrieval_metadata")
        if isinstance(nested, Mapping):
            for key in _SEMANTIC_KEYS:
                if raw.get(key) in (None, "") and nested.get(key) not in (None, ""):
                    raw[key] = nested[key]

        normalized = {key: _json_value(item) for key, item in raw.items()}
        for key in _INTEGER_KEYS:
            parsed = _integer(raw.get(key))
            if parsed is None:
                normalized.pop(key, None)
            else:
                normalized[key] = parsed

        section_path = raw.get("section_path")
        if isinstance(section_path, str):
            path = [part.strip() for part in section_path.split(">") if part.strip()]
            if path:
                normalized["section_path"] = _json_value(path)
        elif isinstance(section_path, Sequence) and not isinstance(section_path, bytes):
            path = [str(part).strip() for part in section_path if str(part).strip()]
            if path:
                normalized["section_path"] = _json_value(path)
        return cls(normalized)

    def text(self, key: str) -> str | None:
        value = self.get(key)
        if value is None or isinstance(value, dict | list):
            return None
        text = str(value).strip()
        return text or None

    def integer(self, key: str) -> int | None:
        return _integer(self.get(key))

    def strings(self, key: str) -> tuple[str, ...]:
        value = self.get(key)
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        if isinstance(value, list):
            return tuple(str(part).strip() for part in value if str(part).strip())
        return ()

    @property
    def page_number(self) -> int | None:
        return self.integer("page_number")

    @property
    def document_version(self) -> int:
        return self.integer("document_version") or 1

    @property
    def chunk_index(self) -> int | None:
        return self.integer("chunk_index")

    @property
    def section_title(self) -> str | None:
        return self.text("section_title")

    def with_updates(self, **values: object) -> EvidenceMetadata:
        return self.from_mapping(self, **values)


__all__ = ["EvidenceMetadata", "MetadataScalar", "MetadataValue"]
