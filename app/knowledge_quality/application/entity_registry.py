"""Versioned deterministic entity registries for domain identity resolution."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ENTITY_NORMALIZATION_VERSION = "p2-entity-normalization-v1"
_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs" / "domain_entities"
_IGNORABLE = {"\u200b", "\u200c", "\u200d", "\ufeff"}


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    canonical_id: str
    entity_type: str
    canonical_name: str
    aliases: tuple[str, ...]
    codes: tuple[str, ...]
    parent_id: str | None
    domain: str


@dataclass(frozen=True, slots=True)
class EntityRegistry:
    domain: str
    registry_version: str
    normalization_version: str
    entries: tuple[RegistryEntry, ...]

    def __post_init__(self) -> None:
        if self.normalization_version != ENTITY_NORMALIZATION_VERSION:
            raise ValueError(
                f"unsupported entity normalization version: {self.normalization_version}"
            )
        ids = [entry.canonical_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate canonical entity id in {self.domain} registry")

    @property
    def by_id(self) -> dict[str, RegistryEntry]:
        return {entry.canonical_id: entry for entry in self.entries}

    @property
    def alias_index(self) -> dict[str, tuple[RegistryEntry, ...]]:
        values: dict[str, list[RegistryEntry]] = {}
        for entry in self.entries:
            for raw_alias in (*entry.aliases, *entry.codes, entry.canonical_name):
                alias = normalize_entity_alias(raw_alias)
                if alias:
                    values.setdefault(alias, []).append(entry)
        return {
            alias: tuple(sorted(set(entries), key=lambda item: item.canonical_id))
            for alias, entries in values.items()
        }


def normalize_entity_alias(value: str) -> str:
    """Normalize lookup text without inventing fuzzy equivalence."""
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    characters = [
        character
        for character in normalized
        if character not in _IGNORABLE and not unicodedata.combining(character)
    ]
    return " ".join(re.findall(r"[^\W_]+", "".join(characters), re.UNICODE))


def normalized_text_with_source_map(value: str) -> tuple[str, tuple[int, ...]]:
    """Return normalized text and an output-character to source-index map."""
    output: list[str] = []
    source_indexes: list[int] = []
    pending_separator_index: int | None = None
    for source_index, source_character in enumerate(value):
        decomposed = unicodedata.normalize("NFKD", source_character.casefold()).replace("đ", "d")
        emitted = False
        for character in decomposed:
            if character in _IGNORABLE or unicodedata.combining(character):
                continue
            if character.isalnum():
                if pending_separator_index is not None and output and output[-1] != " ":
                    output.append(" ")
                    source_indexes.append(pending_separator_index)
                pending_separator_index = None
                output.append(character)
                source_indexes.append(source_index)
                emitted = True
            else:
                pending_separator_index = source_index
        if not emitted and source_character.isspace():
            pending_separator_index = source_index
    return "".join(output), tuple(source_indexes)


@lru_cache(maxsize=4)
def load_entity_registry(domain: str) -> EntityRegistry:
    """Load and validate one checked-in registry snapshot."""
    normalized_domain = domain.strip().casefold()
    path = _CONFIG_DIR / f"{normalized_domain}_entities.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("domain") != normalized_domain:
        raise ValueError(f"registry domain mismatch in {path}")
    entries = tuple(
        RegistryEntry(
            canonical_id=str(item["canonical_id"]),
            entity_type=str(item["entity_type"]),
            canonical_name=str(item["canonical_name"]),
            aliases=tuple(str(alias) for alias in item.get("aliases", [])),
            codes=tuple(str(code) for code in item.get("codes", [])),
            parent_id=(str(item["parent_id"]) if item.get("parent_id") is not None else None),
            domain=normalized_domain,
        )
        for item in payload.get("entities", [])
    )
    return EntityRegistry(
        domain=normalized_domain,
        registry_version=str(payload["registry_version"]),
        normalization_version=str(payload["normalization_version"]),
        entries=entries,
    )


__all__ = [
    "ENTITY_NORMALIZATION_VERSION",
    "EntityRegistry",
    "RegistryEntry",
    "load_entity_registry",
    "normalize_entity_alias",
    "normalized_text_with_source_map",
]
