from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.documents.extraction.profiling.models import (
    PageClassification,
    PageProfile,
    RouteAttempt,
    RoutingDecision,
)


@dataclass(frozen=True)
class ProfileArtifactStore:
    output_dir: Path = Path("output")

    @property
    def profiles_path(self) -> Path:
        return self.output_dir / "page_profiles.jsonl"

    @property
    def classifications_path(self) -> Path:
        return self.output_dir / "page_classifications.jsonl"

    @property
    def decisions_path(self) -> Path:
        return self.output_dir / "routing_decisions.jsonl"

    @property
    def attempts_path(self) -> Path:
        return self.output_dir / "route_attempts.jsonl"

    def persist_profiles(self, profiles: Iterable[PageProfile]) -> None:
        _write_jsonl_atomic(self.profiles_path, [item.to_dict() for item in profiles])

    def persist_classifications(self, classifications: Iterable[PageClassification]) -> None:
        _write_jsonl_atomic(
            self.classifications_path,
            [item.to_dict() for item in classifications],
        )

    def persist_decisions(self, decisions: Iterable[RoutingDecision]) -> None:
        _write_jsonl_atomic(self.decisions_path, [item.to_dict() for item in decisions])

    def persist_attempts(self, attempts: Iterable[RouteAttempt]) -> None:
        _write_jsonl_atomic(self.attempts_path, [item.to_dict() for item in attempts])


def read_profiles(path: Path) -> list[PageProfile]:
    return [PageProfile.from_mapping(item) for item in _read_jsonl(path)]


def read_decisions(path: Path) -> list[RoutingDecision]:
    return [RoutingDecision.from_mapping(item) for item in _read_jsonl(path)]


def _write_jsonl_atomic(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    os.replace(tmp_path, path)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


__all__ = ["ProfileArtifactStore", "read_decisions", "read_profiles"]
