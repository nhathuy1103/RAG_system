from __future__ import annotations

from typing import Any

from evaluation.metadata_baseline.common import CorpusRecord, SchemaField


def field(
    name: str,
    *,
    level: str = "both",
    expected_type: str = "string",
    required: bool = False,
    allowed_values: tuple[str, ...] = (),
    regex: str | None = None,
    consistency_scope: str = "",
    unique_scope: str = "",
    reference_target: str = "",
    conflict_roles: tuple[str, ...] = (),
) -> SchemaField:
    return SchemaField(
        field_name=name,
        category="derived",
        level=level,
        actual_data_type=expected_type,
        expected_data_type=expected_type,
        required=required,
        source_generator="test",
        generation_method="rule",
        allowed_values=allowed_values,
        default_value="",
        normalized=True,
        used_in_embedding=False,
        used_in_filter=False,
        used_in_boost=False,
        used_in_reranker=False,
        used_in_citation=False,
        used_in_access_control=False,
        usage_locations="test",
        importance="high",
        risk_if_missing="test risk",
        risk_if_incorrect="test risk",
        notes="fixture",
        regex=regex,
        consistency_scope=consistency_scope,
        unique_scope=unique_scope,
        reference_target=reference_target,
        conflict_roles=conflict_roles,
    )


def record(
    record_type: str,
    record_id: str,
    *,
    document_id: str | None = None,
    content: str = "fixture content",
    metadata: dict[str, Any] | None = None,
    **values: Any,
) -> CorpusRecord:
    effective_document_id = (
        record_id if record_type == "document" and document_id is None else document_id
    )
    raw: dict[str, Any] = {
        "record_type": record_type,
        "record_id": record_id,
        "content": content,
        "metadata": metadata or {},
        **values,
    }
    if effective_document_id is not None:
        raw["document_id"] = effective_document_id
    chunk_id = record_id if record_type == "chunk" else None
    if chunk_id:
        raw["chunk_id"] = chunk_id
    return CorpusRecord(
        record_type=record_type,
        record_id=record_id,
        document_id=effective_document_id,
        chunk_id=chunk_id,
        content=content,
        raw=raw,
        line_number=1,
    )
