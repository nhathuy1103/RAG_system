from __future__ import annotations

import json
import logging
from pathlib import Path

from app.pipeline.documents.extraction.canonical.ir import (
    CANONICAL_IR_SCHEMA_NAME,
    CanonicalDocument,
    is_supported_schema_version,
)

logger = logging.getLogger(__name__)


def canonical_document_to_json(document: CanonicalDocument) -> str:
    return json.dumps(
        document.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_document_from_json(payload: str | bytes) -> CanonicalDocument:
    raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("canonical IR payload must be a JSON object")
    if value.get("schema_name") != CANONICAL_IR_SCHEMA_NAME:
        logger.warning(
            "schema_version_rejected",
            extra={
                "schema_name": value.get("schema_name"),
                "schema_version": value.get("schema_version"),
            },
        )
        raise ValueError("unsupported canonical IR schema name")
    version = str(value.get("schema_version") or "")
    if not is_supported_schema_version(version):
        logger.warning(
            "schema_version_rejected",
            extra={
                "schema_name": value.get("schema_name"),
                "schema_version": version,
            },
        )
        raise ValueError(f"unsupported canonical IR schema version: {version}")
    document = CanonicalDocument.from_dict(value)
    logger.info(
        "canonical_ir_loaded",
        extra={
            "document_id": document.document_id,
            "schema_version": document.schema_version,
        },
    )
    return document


def write_canonical_document(path: str | Path, document: CanonicalDocument) -> None:
    Path(path).write_text(canonical_document_to_json(document), encoding="utf-8")


def read_canonical_document(path: str | Path) -> CanonicalDocument:
    return canonical_document_from_json(Path(path).read_text(encoding="utf-8"))
