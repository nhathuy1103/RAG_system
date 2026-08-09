from __future__ import annotations

import json
from pathlib import Path

from app.retrieval.application.metadata_filter_planner import (
    DeterministicMetadataFilterPlanner,
    ProjectAliasRegistry,
)
from app.retrieval.domain.models import RetrievalFilters, StructuredMetadataFilters


def test_planner_extracts_only_explicit_high_confidence_filters() -> None:
    planner = DeterministicMetadataFilterPlanner()

    result = planner.plan(
        "Cho tôi bảng tiện ích hiện hành của P16 trong quý 3/2026",
        RetrievalFilters(owner_id="owner-1"),
    )

    assert result.metadata.as_dict() == {
        "content_kind": "table",
        "project_code": "P16",
        "year": 2026,
        "data_period": "Q3/2026",
        "effective_status": "current",
    }


def test_planner_allowlist_keeps_only_production_approved_filter() -> None:
    planner = DeterministicMetadataFilterPlanner(
        allowed_fields=frozenset({"project_code"})
    )

    result = planner.plan(
        "Cho tôi bảng tiện ích hiện hành của P16 trong quý 3/2026",
        RetrievalFilters(owner_id="owner-1"),
    )

    assert result.metadata.as_dict() == {"project_code": "P16"}


def test_planner_allowlist_removes_unapproved_explicit_filters() -> None:
    planner = DeterministicMetadataFilterPlanner(
        allowed_fields=frozenset({"project_code"})
    )
    supplied = RetrievalFilters(
        owner_id="owner-1",
        metadata=StructuredMetadataFilters(project_code="P16", year=2026),
    )

    result = planner.plan("P16 năm 2026", supplied)

    assert result.metadata.as_dict() == {"project_code": "P16"}


def test_planner_does_not_guess_from_ambiguous_alias(tmp_path: Path) -> None:
    registry_path = tmp_path / "projects.json"
    registry_path.write_text(
        json.dumps(
            [
                {"project_code": "P16", "project_name": "Smart City", "aliases": ["Smart"]},
                {"project_code": "P17", "project_name": "Smart Ocean", "aliases": ["Smart"]},
            ]
        ),
        encoding="utf-8",
    )
    planner = DeterministicMetadataFilterPlanner(ProjectAliasRegistry.from_json_file(registry_path))

    result = planner.plan("Tiện ích Smart có gì?", RetrievalFilters(owner_id="owner-1"))

    assert result.metadata.project_code is None
    assert result.metadata.project_id is None


def test_planner_resolves_unique_alias_to_canonical_code(tmp_path: Path) -> None:
    registry_path = tmp_path / "projects.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "project_id": "project-smart-city",
                    "project_code": "P16",
                    "project_name": "Vinhomes Smart City",
                    "aliases": ["Smart City"],
                }
            ]
        ),
        encoding="utf-8",
    )
    planner = DeterministicMetadataFilterPlanner(ProjectAliasRegistry.from_json_file(registry_path))

    result = planner.plan(
        "Tiện ích Smart City có gì?",
        RetrievalFilters(owner_id="owner-1"),
    )

    assert result.metadata.project_code == "P16"
    assert result.metadata.project_id is None


def test_registry_prefers_longest_overlapping_project_name(tmp_path: Path) -> None:
    registry_path = tmp_path / "projects.json"
    registry_path.write_text(
        json.dumps(
            [
                {"project_code": "P11", "project_name": "Vinhomes Global Gate"},
                {
                    "project_code": "P04",
                    "project_name": "Vinhomes Global Gate Hạ Long",
                },
            ]
        ),
        encoding="utf-8",
    )
    registry = ProjectAliasRegistry.from_json_file(registry_path)

    project = registry.resolve("Tiến độ Vinhomes Global Gate Hạ Long")

    assert project is not None
    assert project.project_code == "P04"
