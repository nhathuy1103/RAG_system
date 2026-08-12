"""Deterministic P4 version direction and acyclic lineage construction."""

from __future__ import annotations

from dataclasses import dataclass

from app.knowledge_quality.domain.relation_models import (
    DocumentRelationContext,
    VersionDirection,
    temporal_business_key,
)


@dataclass(frozen=True, slots=True)
class VersionLineageEdge:
    previous_document_id: str
    next_document_id: str
    family_id: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VersionLineageResult:
    edges: tuple[VersionLineageEdge, ...]
    uncertain_document_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


def determine_version_direction(
    source: DocumentRelationContext,
    target: DocumentRelationContext,
) -> tuple[VersionDirection, tuple[str, ...]]:
    """Use business version/effective evidence; never use ``ingested_at``."""
    signals: list[tuple[VersionDirection, str]] = []
    if (
        source.document_family_id
        and target.document_family_id
        and source.document_family_id != target.document_family_id
    ):
        return VersionDirection.UNKNOWN, ("different_document_families",)
    if (
        source.version_number is not None
        and target.version_number is not None
        and source.version_number != target.version_number
    ):
        signals.append(
            (
                VersionDirection.SOURCE_SUPERSEDES_TARGET
                if source.version_number > target.version_number
                else VersionDirection.TARGET_SUPERSEDES_SOURCE,
                "explicit_version_number",
            )
        )
    source_effective = temporal_business_key(source.temporal.effective_from)
    target_effective = temporal_business_key(target.temporal.effective_from)
    if source_effective != (0, 0, 0, 0, 0, 0) and source_effective != target_effective:
        signals.append(
            (
                VersionDirection.SOURCE_SUPERSEDES_TARGET
                if source_effective > target_effective
                else VersionDirection.TARGET_SUPERSEDES_SOURCE,
                "effective_from_progression",
            )
        )
    if not signals:
        source_publication = temporal_business_key(source.temporal.publication_time)
        target_publication = temporal_business_key(target.temporal.publication_time)
        if (
            source.document_family_id
            and source.document_family_id == target.document_family_id
            and source_publication != (0, 0, 0, 0, 0, 0)
            and source_publication != target_publication
        ):
            signals.append(
                (
                    VersionDirection.SOURCE_SUPERSEDES_TARGET
                    if source_publication > target_publication
                    else VersionDirection.TARGET_SUPERSEDES_SOURCE,
                    "publication_time_progression",
                )
            )
    if not signals:
        return VersionDirection.UNKNOWN, ("ambiguous_version_direction",)
    directions = {direction for direction, _ in signals}
    if len(directions) != 1:
        return VersionDirection.UNKNOWN, ("conflicting_version_direction_evidence",)
    return signals[0][0], tuple(reason for _, reason in signals)


def build_version_lineage(
    documents: tuple[DocumentRelationContext, ...],
) -> VersionLineageResult:
    """Build only adjacent, uniquely ordered edges inside each tenant/family."""
    grouped: dict[tuple[str, str, str], list[DocumentRelationContext]] = {}
    uncertain: set[str] = set()
    for document in documents:
        if not document.document_family_id:
            uncertain.add(document.document_id)
            continue
        grouped.setdefault(
            (document.owner_id, document.notebook_id, document.document_family_id), []
        ).append(document)

    edges: list[VersionLineageEdge] = []
    reasons: set[str] = set()
    for (_, _, family_id), members in sorted(grouped.items()):
        ordered: list[
            tuple[tuple[int, tuple[int, int, int, int, int, int]], DocumentRelationContext]
        ] = []
        seen_keys: set[tuple[int, tuple[int, int, int, int, int, int]]] = set()
        for member in members:
            key = (
                member.version_number if member.version_number is not None else -1,
                temporal_business_key(member.temporal.effective_from),
            )
            if key == (-1, (0, 0, 0, 0, 0, 0)) or key in seen_keys:
                uncertain.add(member.document_id)
                reasons.add("version_lineage_ambiguous")
                continue
            seen_keys.add(key)
            ordered.append((key, member))
        ordered.sort(key=lambda item: (item[0], item[1].document_id))
        for (_, previous), (_, following) in zip(ordered, ordered[1:], strict=False):
            if previous.document_id == following.document_id:
                reasons.add("version_lineage_self_cycle_rejected")
                continue
            edges.append(
                VersionLineageEdge(
                    previous_document_id=previous.document_id,
                    next_document_id=following.document_id,
                    family_id=family_id,
                    reason_codes=("adjacent_business_version",),
                )
            )
    return VersionLineageResult(
        edges=tuple(edges),
        uncertain_document_ids=tuple(sorted(uncertain)),
        reason_codes=tuple(sorted(reasons)),
    )


def lineage_has_cycle(edges: tuple[VersionLineageEdge, ...]) -> bool:
    """Small deterministic graph guard used before persistence."""
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.previous_document_id, set()).add(edge.next_document_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(target) for target in adjacency.get(node, ())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in tuple(adjacency))


__all__ = [
    "VersionLineageEdge",
    "VersionLineageResult",
    "build_version_lineage",
    "determine_version_direction",
    "lineage_has_cycle",
]
