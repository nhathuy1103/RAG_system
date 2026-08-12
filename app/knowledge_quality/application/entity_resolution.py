"""Conservative mention detection and registry-backed entity resolution."""

from __future__ import annotations

from dataclasses import dataclass

from app.knowledge_quality.application.entity_registry import (
    EntityRegistry,
    RegistryEntry,
    load_entity_registry,
    normalize_entity_alias,
    normalized_text_with_source_map,
)
from app.structured_facts.domain.models import (
    EntityEvidence,
    EntityEvidenceSource,
    EntityMatchMethod,
    EntityRef,
)

_SOURCE_PRIORITY = {
    EntityEvidenceSource.CLAIM_TEXT: 0,
    EntityEvidenceSource.TABLE_CELL: 1,
    EntityEvidenceSource.TABLE_HEADER: 2,
    EntityEvidenceSource.SECTION_HEADING: 3,
    EntityEvidenceSource.PARENT_CONTEXT: 4,
    EntityEvidenceSource.DOCUMENT_METADATA: 5,
    EntityEvidenceSource.REGISTRY_FALLBACK: 6,
}
_MATCH_CONFIDENCE = {
    EntityMatchMethod.EXACT_CODE: 1.0,
    EntityMatchMethod.CANONICAL_NAME: 1.0,
    EntityMatchMethod.EXACT_ALIAS: 1.0,
    EntityMatchMethod.NORMALIZED_ALIAS: 0.99,
    EntityMatchMethod.CONTEXT_FALLBACK: 0.90,
}


@dataclass(frozen=True, slots=True)
class EntityTextContext:
    text: str
    source: EntityEvidenceSource
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class EntityResolutionResult:
    entities: tuple[EntityRef, ...]
    ambiguous_entity_types: tuple[str, ...]
    registry_versions: tuple[str, ...]

    @property
    def primary_entity(self) -> EntityRef | None:
        priority = {
            "vehicle_model": 0,
            "project": 0,
            "unit": 1,
            "building": 2,
            "manufacturer": 3,
            "developer": 3,
        }
        return min(
            self.entities,
            key=lambda item: (priority.get(item.entity_type, 10), item.canonical_id),
            default=None,
        )


@dataclass(frozen=True, slots=True)
class _MentionMatch:
    entry: RegistryEntry
    evidence: EntityEvidence


def resolve_entities(
    text: str,
    *,
    contexts: tuple[EntityTextContext, ...] = (),
    domain_hint: str | None = None,
) -> EntityResolutionResult:
    """Resolve canonical refs using source precedence and fail-closed ambiguity."""
    registries = (
        (load_entity_registry(domain_hint),)
        if domain_hint in {"vinhomes", "vinfast"}
        else (load_entity_registry("vinhomes"), load_entity_registry("vinfast"))
    )
    blocks = (
        EntityTextContext(text, EntityEvidenceSource.CLAIM_TEXT),
        *sorted(contexts, key=lambda item: _SOURCE_PRIORITY[item.source]),
    )
    selected: dict[tuple[str, str], list[_MentionMatch]] = {}
    selected_priority: dict[tuple[str, str], int] = {}
    for block in blocks:
        priority = _SOURCE_PRIORITY[block.source]
        for registry in registries:
            for match in _matches_in_block(block, registry):
                key = (registry.domain, match.entry.entity_type)
                previous_priority = selected_priority.get(key)
                if previous_priority is None or priority < previous_priority:
                    selected[key] = [match]
                    selected_priority[key] = priority
                elif priority == previous_priority:
                    selected[key].append(match)

    entities: list[EntityRef] = []
    ambiguous: list[str] = []
    for (domain, entity_type), matches in sorted(selected.items()):
        by_id: dict[str, list[_MentionMatch]] = {}
        for match in matches:
            by_id.setdefault(match.entry.canonical_id, []).append(match)
        if len(by_id) != 1:
            ambiguous.append(f"{domain}:{entity_type}")
            continue
        canonical_id, entity_matches = next(iter(by_id.items()))
        entry = entity_matches[0].entry
        evidence = tuple(
            sorted(
                {item.evidence for item in entity_matches},
                key=lambda item: (
                    _SOURCE_PRIORITY[item.source],
                    item.span_start if item.span_start is not None else -1,
                    -len(item.raw_text),
                ),
            )
        )
        confidence = min(item.confidence for item in evidence)
        entities.append(
            EntityRef(
                domain=domain,
                entity_type=entity_type,
                canonical_id=canonical_id,
                canonical_name=entry.canonical_name,
                parent_id=entry.parent_id,
                confidence=confidence,
                registry_version=evidence[0].registry_version,
                evidence=evidence,
            )
        )
    return EntityResolutionResult(
        entities=tuple(entities),
        ambiguous_entity_types=tuple(ambiguous),
        registry_versions=tuple(registry.registry_version for registry in registries),
    )


def _matches_in_block(
    block: EntityTextContext,
    registry: EntityRegistry,
) -> tuple[_MentionMatch, ...]:
    normalized_text, source_map = normalized_text_with_source_map(block.text)
    if not normalized_text:
        return ()
    matches: list[_MentionMatch] = []
    occupied: set[tuple[str, int, int]] = set()
    for alias, entries in sorted(
        registry.alias_index.items(), key=lambda item: (-len(item[0]), item[0])
    ):
        if len(entries) != 1:
            # An ambiguous registry alias must never silently select an entity.
            continue
        start = 0
        while True:
            index = normalized_text.find(alias, start)
            if index < 0:
                break
            end_index = index + len(alias)
            start = index + 1
            if (index > 0 and normalized_text[index - 1].isalnum()) or (
                end_index < len(normalized_text) and normalized_text[end_index].isalnum()
            ):
                continue
            source_start = source_map[index]
            source_end = source_map[end_index - 1] + 1
            entry = entries[0]
            occupied_key = (entry.canonical_id, source_start, source_end)
            if occupied_key in occupied:
                continue
            occupied.add(occupied_key)
            raw_text = block.text[source_start:source_end]
            method = _match_method(raw_text, entry)
            matches.append(
                _MentionMatch(
                    entry=entry,
                    evidence=EntityEvidence(
                        raw_text=raw_text,
                        match_method=method,
                        source=block.source,
                        confidence=_MATCH_CONFIDENCE[method],
                        registry_version=registry.registry_version,
                        span_start=source_start
                        if block.source is EntityEvidenceSource.CLAIM_TEXT
                        else None,
                        span_end=source_end
                        if block.source is EntityEvidenceSource.CLAIM_TEXT
                        else None,
                        source_id=block.source_id,
                    ),
                )
            )
    # Prefer the longest mention for one entity/source span neighborhood.
    best: dict[str, _MentionMatch] = {}
    for match in matches:
        previous = best.get(match.entry.canonical_id)
        if previous is None or len(match.evidence.raw_text) > len(previous.evidence.raw_text):
            best[match.entry.canonical_id] = match
    return tuple(best.values())


def _match_method(raw_text: str, entry: RegistryEntry) -> EntityMatchMethod:
    raw_folded = raw_text.casefold().strip()
    if any(raw_folded == code.casefold() for code in entry.codes):
        return EntityMatchMethod.EXACT_CODE
    if raw_folded == entry.canonical_name.casefold():
        return EntityMatchMethod.CANONICAL_NAME
    if any(raw_folded == alias.casefold() for alias in entry.aliases):
        return EntityMatchMethod.EXACT_ALIAS
    if any(
        normalize_entity_alias(raw_text) == normalize_entity_alias(alias)
        for alias in (*entry.aliases, *entry.codes, entry.canonical_name)
    ):
        return EntityMatchMethod.NORMALIZED_ALIAS
    return EntityMatchMethod.CONTEXT_FALLBACK


__all__ = [
    "EntityResolutionResult",
    "EntityTextContext",
    "resolve_entities",
]
