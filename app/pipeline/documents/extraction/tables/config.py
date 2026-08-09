from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from app.pipeline.documents.extraction.tables.models import (
    CROSS_PAGE_STRATEGY_VERSION,
    FINANCIAL_STRATEGY_VERSION,
    GRID_STRATEGY_VERSION,
    SUBSIDIARY_STRATEGY_VERSION,
    TABLE_ENGINE_VERSION,
    TABLE_SCHEMA_VERSION,
    TABLE_VALIDATOR_VERSION,
    TOC_STRATEGY_VERSION,
)


class TableMode(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    ACTIVE = "active"


@dataclass(frozen=True)
class TableEngineConfig:
    enabled: bool = False
    mode: TableMode = TableMode.LEGACY
    schema_version: str = TABLE_SCHEMA_VERSION
    engine_version: str = TABLE_ENGINE_VERSION
    grid_strategy_version: str = GRID_STRATEGY_VERSION
    financial_strategy_version: str = FINANCIAL_STRATEGY_VERSION
    toc_strategy_version: str = TOC_STRATEGY_VERSION
    subsidiary_strategy_version: str = SUBSIDIARY_STRATEGY_VERSION
    cross_page_strategy_version: str = CROSS_PAGE_STRATEGY_VERSION
    validator_version: str = TABLE_VALIDATOR_VERSION
    table_type_threshold: float = 0.50
    cell_assignment_iou_threshold: float = 0.30
    header_confidence_threshold: float = 0.60
    maximum_table_regions_per_page: int = 64
    maximum_blocks_per_table: int = 800
    maximum_cells_per_table: int = 2000
    maximum_table_deadline_ms: int = 60_000
    static_fallback_enabled: bool = True

    def validate(self) -> None:
        if not isinstance(self.mode, TableMode):
            TableMode(str(self.mode))
        if self.mode != TableMode.LEGACY and not self.enabled:
            raise ValueError("tables.enabled=true is required for shadow or active mode.")
        for name in (
            "schema_version",
            "engine_version",
            "grid_strategy_version",
            "financial_strategy_version",
            "toc_strategy_version",
            "subsidiary_strategy_version",
            "cross_page_strategy_version",
            "validator_version",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"tables.{name} is required.")
        for name in (
            "table_type_threshold",
            "cell_assignment_iou_threshold",
            "header_confidence_threshold",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"tables.{name} must be in [0, 1].")
        for name in (
            "maximum_table_regions_per_page",
            "maximum_blocks_per_table",
            "maximum_cells_per_table",
            "maximum_table_deadline_ms",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"tables.{name} must be positive.")


@dataclass(frozen=True)
class FinancialTableConfig:
    enabled: bool = True
    negative_parentheses_enabled: bool = True
    required_period_columns: int = 1
    numeric_density_threshold: float = 0.35

    def validate(self) -> None:
        if self.required_period_columns < 0:
            raise ValueError("financial_tables.required_period_columns must not be negative.")
        if not 0.0 <= self.numeric_density_threshold <= 1.0:
            raise ValueError("financial_tables.numeric_density_threshold must be in [0, 1].")


@dataclass(frozen=True)
class CrossPageTableConfig:
    enabled: bool = True
    schema_similarity_threshold: float = 0.95
    header_similarity_threshold: float = 0.90
    max_page_gap: int = 1

    def validate(self) -> None:
        for name in ("schema_similarity_threshold", "header_similarity_threshold"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"cross_page_tables.{name} must be in [0, 1].")
        if self.max_page_gap < 1:
            raise ValueError("cross_page_tables.max_page_gap must be positive.")


@dataclass(frozen=True)
class TablePerformanceConfig:
    max_parallel_table_tasks: int = 4
    cache_enabled: bool = True
    overlay_enabled: bool = True
    artifact_size_limit: int = 20_000_000

    def validate(self) -> None:
        for name in ("max_parallel_table_tasks", "artifact_size_limit"):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"table_performance.{name} must be positive.")


@dataclass(frozen=True)
class Phase4Config:
    tables: TableEngineConfig = TableEngineConfig()
    financial_tables: FinancialTableConfig = FinancialTableConfig()
    cross_page_tables: CrossPageTableConfig = CrossPageTableConfig()
    performance: TablePerformanceConfig = TablePerformanceConfig()

    def validate(self) -> None:
        self.tables.validate()
        self.financial_tables.validate()
        self.cross_page_tables.validate()
        self.performance.validate()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "tables": asdict(self.tables),
            "financial_tables": asdict(self.financial_tables),
            "cross_page_tables": asdict(self.cross_page_tables),
            "performance": asdict(self.performance),
        }
        payload["tables"]["mode"] = self.tables.mode.value
        return payload

    def checksum(self) -> str:
        return _sha256_json(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Phase4Config:
        value = dict(value or {})
        tables_payload = dict(value.get("tables") or {})
        if "mode" in tables_payload and not isinstance(tables_payload["mode"], TableMode):
            tables_payload["mode"] = TableMode(str(tables_payload["mode"]).strip().lower())
        config = cls(
            tables=_dataclass_from_mapping(TableEngineConfig, tables_payload),
            financial_tables=_dataclass_from_mapping(
                FinancialTableConfig,
                value.get("financial_tables") or {},
            ),
            cross_page_tables=_dataclass_from_mapping(
                CrossPageTableConfig,
                value.get("cross_page_tables") or {},
            ),
            performance=_dataclass_from_mapping(
                TablePerformanceConfig,
                value.get("performance") or {},
            ),
        )
        config.validate()
        return config


DEFAULT_PHASE4_CONFIG = Phase4Config()


def _dataclass_from_mapping(cls: type[Any], payload: Mapping[str, Any]) -> Any:
    allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    return cls(**{key: value for key, value in dict(payload).items() if key in allowed})


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CrossPageTableConfig",
    "DEFAULT_PHASE4_CONFIG",
    "FinancialTableConfig",
    "Phase4Config",
    "TableEngineConfig",
    "TableMode",
    "TablePerformanceConfig",
]
