"""Conservative deterministic planning of structured pre-retrieval filters."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from app.retrieval.domain.models import RetrievalFilters, StructuredMetadataFilters

_PROJECT_CODE = re.compile(r"(?<![A-Z0-9])(P\d{1,6})(?![A-Z0-9])", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_QUARTER = re.compile(r"(?:\bq|\bquy\s*)([1-4])\s*[/\-]?\s*((?:19|20)\d{2})\b")
SUPPORTED_FILTER_FIELDS = frozenset(
    {
        "document_type",
        "content_kind",
        "project_id",
        "project_code",
        "year",
        "data_period",
        "effective_status",
    }
)


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str | None
    project_code: str | None
    project_name: str
    aliases: tuple[str, ...] = ()


class ProjectAliasRegistry:
    """Resolve configured names/aliases; ambiguous matches intentionally abstain."""

    def __init__(self, projects: tuple[ProjectIdentity, ...] = ()) -> None:
        self.projects = projects

    @classmethod
    def from_json_file(cls, path: str | Path | None) -> ProjectAliasRegistry:
        if path is None:
            return cls()
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Project registry must be a JSON array")
        projects: list[ProjectIdentity] = []
        for row in raw:
            if not isinstance(row, dict) or not str(row.get("project_name") or "").strip():
                raise ValueError("Every project registry row needs project_name")
            aliases = row.get("aliases") or []
            if not isinstance(aliases, list):
                raise ValueError("Project aliases must be an array")
            projects.append(
                ProjectIdentity(
                    project_id=_optional_text(row.get("project_id")),
                    project_code=_optional_text(row.get("project_code")),
                    project_name=str(row["project_name"]).strip(),
                    aliases=tuple(str(value).strip() for value in aliases if str(value).strip()),
                )
            )
        return cls(tuple(projects))

    def resolve(self, query: str) -> ProjectIdentity | None:
        folded_query = f" {_fold(query)} "
        matches: list[tuple[int, ProjectIdentity]] = []
        for project in self.projects:
            names = (project.project_name, *project.aliases)
            scores = [
                len(folded_name)
                for name in names
                if (folded_name := _fold(name)) and f" {folded_name} " in folded_query
            ]
            if scores:
                matches.append((max(scores), project))
        if not matches:
            return None
        best_score = max(score for score, _ in matches)
        best_matches = [project for score, project in matches if score == best_score]
        unique = {(item.project_id, item.project_code) for item in best_matches}
        return best_matches[0] if len(unique) == 1 else None


@dataclass(frozen=True)
class DeterministicMetadataFilterPlanner:
    project_registry: ProjectAliasRegistry = ProjectAliasRegistry()
    allowed_fields: frozenset[str] = SUPPORTED_FILTER_FIELDS

    def __post_init__(self) -> None:
        unsupported = self.allowed_fields - SUPPORTED_FILTER_FIELDS
        if unsupported:
            raise ValueError(
                f"Unsupported structured filter field(s): {', '.join(sorted(unsupported))}"
            )

    def plan(self, query: str, filters: RetrievalFilters) -> RetrievalFilters:
        current = filters.metadata
        values = {
            field: value
            for field, value in current.as_dict().items()
            if field in self.allowed_fields
        }
        folded = _fold(query)

        code_matches = {value.upper() for value in _PROJECT_CODE.findall(query)}
        if (
            "project_code" in self.allowed_fields
            and "project_code" not in values
            and len(code_matches) == 1
        ):
            values["project_code"] = next(iter(code_matches))
        elif (
            {"project_code", "project_id"} & self.allowed_fields
            and "project_code" not in values
            and "project_id" not in values
        ):
            project = self.project_registry.resolve(query)
            if project is not None:
                if project.project_code and "project_code" in self.allowed_fields:
                    values["project_code"] = project.project_code.upper()
                elif project.project_id and "project_id" in self.allowed_fields:
                    values["project_id"] = project.project_id

        years = {int(value) for value in _YEAR.findall(query)}
        if "year" in self.allowed_fields and "year" not in values and len(years) == 1:
            values["year"] = next(iter(years))

        quarter_matches = {(quarter, year) for quarter, year in _QUARTER.findall(folded)}
        if (
            "data_period" in self.allowed_fields
            and "data_period" not in values
            and len(quarter_matches) == 1
        ):
            quarter, year = next(iter(quarter_matches))
            values["data_period"] = f"Q{quarter}/{year}"

        current_cues = (" hien hanh ", " moi nhat ", " dang ap dung ", " current ", " latest ")
        padded_folded = f" {folded} "
        if (
            "effective_status" in self.allowed_fields
            and "effective_status" not in values
            and any(cue in padded_folded for cue in current_cues)
        ):
            values["effective_status"] = "current"

        table_cues = (" bang ", " bieu ", " table ")
        if (
            "content_kind" in self.allowed_fields
            and "content_kind" not in values
            and any(cue in padded_folded for cue in table_cues)
        ):
            values["content_kind"] = "table"

        planned = StructuredMetadataFilters(
            document_type=_text_value(values.get("document_type")),
            content_kind=_text_value(values.get("content_kind")),
            project_id=_text_value(values.get("project_id")),
            project_code=_text_value(values.get("project_code")),
            year=_year_value(values.get("year")),
            data_period=_text_value(values.get("data_period")),
            effective_status=_text_value(values.get("effective_status")),
        )
        return replace(filters, metadata=planned)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _text_value(value: str | int | None) -> str | None:
    return str(value) if value is not None else None


def _year_value(value: str | int | None) -> int | None:
    return int(value) if value is not None else None


__all__ = [
    "DeterministicMetadataFilterPlanner",
    "ProjectAliasRegistry",
    "ProjectIdentity",
    "SUPPORTED_FILTER_FIELDS",
]
