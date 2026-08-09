from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import write_jsonl
from app.pipeline.documents.extraction.tables.engine import TableDocumentResult
from app.pipeline.documents.extraction.tables.models import (
    CrossPageTableLink,
    StructuredTable,
    TableCell,
    TableColumn,
    TableIssue,
    TableRow,
)


@dataclass(frozen=True)
class Phase4TableArtifact:
    reference: str
    checksum: str
    created_at: str
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "checksum": self.checksum,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class TableArtifactStore:
    output_dir: Path = Path("output")

    @property
    def structured_tables_path(self) -> Path:
        return self.output_dir / "structured_tables.jsonl"

    @property
    def rows_path(self) -> Path:
        return self.output_dir / "table_rows.jsonl"

    @property
    def columns_path(self) -> Path:
        return self.output_dir / "table_columns.jsonl"

    @property
    def cells_path(self) -> Path:
        return self.output_dir / "table_cells.jsonl"

    @property
    def issues_path(self) -> Path:
        return self.output_dir / "table_issues.jsonl"

    @property
    def cross_page_links_path(self) -> Path:
        return self.output_dir / "cross_page_table_links.jsonl"

    def persist_result(self, result: TableDocumentResult) -> None:
        tables = list(result.structured_tables)
        write_jsonl_atomic(self.structured_tables_path, [table.to_dict() for table in tables])
        write_jsonl_atomic(
            self.rows_path,
            [row.to_dict() for table in tables for row in table.rows],
        )
        write_jsonl_atomic(
            self.columns_path,
            [column.to_dict() for table in tables for column in table.columns],
        )
        write_jsonl_atomic(
            self.cells_path,
            [cell.to_dict() for table in tables for cell in table.cells],
        )
        write_jsonl_atomic(
            self.issues_path,
            [issue.to_dict() for issue in result.issues],
        )
        write_jsonl_atomic(
            self.cross_page_links_path,
            [link.to_dict() for link in result.cross_page_links],
        )


def build_table_artifact(
    result: TableDocumentResult,
    *,
    attempt_id: str,
) -> Phase4TableArtifact:
    payload = {
        "artifact_type": "phase4_generic_tables",
        "attempt_id": attempt_id,
        "mode": result.mode.value,
        "config_checksum": result.config_checksum,
        "structured_tables": [table.to_dict() for table in result.structured_tables],
        "cross_page_links": [link.to_dict() for link in result.cross_page_links],
        "issues": [issue.to_dict() for issue in result.issues],
        "comparison": result.comparison,
        "performance": result.performance,
    }
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return Phase4TableArtifact(
        reference=f"phase4-tables:{attempt_id}:{checksum[:16]}",
        checksum=checksum,
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        payload_json=payload_json,
    )


def persist_table_artifact(
    storage: Any,
    *,
    tenant_id: str,
    owner_id: str,
    document_id: str,
    version: int,
    attempt_id: str,
    result: TableDocumentResult,
) -> Phase4TableArtifact:
    built = build_table_artifact(result, attempt_id=attempt_id)
    if hasattr(storage, "save_bytes"):
        stored = storage.save_bytes(
            tenant_id=tenant_id,
            owner_id=owner_id,
            document_id=document_id,
            version=version,
            filename=f"phase4-tables-{attempt_id}.json",
            content=built.payload_json.encode("utf-8"),
        )
        return Phase4TableArtifact(
            reference=getattr(stored, "storage_path", built.reference),
            checksum=built.checksum,
            created_at=built.created_at,
            payload_json=built.payload_json,
        )
    return built


def read_structured_tables(path: Path) -> list[StructuredTable]:
    return [StructuredTable.from_mapping(item) for item in _read_jsonl(path)]


def read_table_rows(path: Path) -> list[TableRow]:
    return [TableRow.from_mapping(item) for item in _read_jsonl(path)]


def read_table_columns(path: Path) -> list[TableColumn]:
    return [TableColumn.from_mapping(item) for item in _read_jsonl(path)]


def read_table_cells(path: Path) -> list[TableCell]:
    return [TableCell.from_mapping(item) for item in _read_jsonl(path)]


def read_table_issues(path: Path) -> list[TableIssue]:
    return [TableIssue.from_mapping(item) for item in _read_jsonl(path)]


def read_cross_page_table_links(path: Path) -> list[CrossPageTableLink]:
    return [CrossPageTableLink.from_mapping(item) for item in _read_jsonl(path)]


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    write_jsonl(tmp_path, rows)
    os.replace(tmp_path, path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


__all__ = [
    "Phase4TableArtifact",
    "TableArtifactStore",
    "build_table_artifact",
    "persist_table_artifact",
    "read_cross_page_table_links",
    "read_structured_tables",
    "read_table_cells",
    "read_table_columns",
    "read_table_issues",
    "read_table_rows",
]
