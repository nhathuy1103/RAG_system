"""Deterministic, semantic P4 relation clusters with tenant boundaries."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from app.knowledge_quality.domain.relation_models import (
    FinalRelationType,
    RelationEvidenceSummary,
)


class RelationClusterType(StrEnum):
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    VERSION_FAMILY = "version_family"
    CONFLICT_GROUP = "conflict_group"


@dataclass(frozen=True, slots=True)
class RelationCluster:
    cluster_id: str
    cluster_type: RelationClusterType
    owner_id: str
    notebook_id: str
    document_ids: tuple[str, ...]
    aggregation_version: str


def build_relation_clusters(
    summaries: tuple[RelationEvidenceSummary, ...],
) -> tuple[RelationCluster, ...]:
    """Build separate connected components; no universal lossy cluster exists."""
    edges: dict[tuple[str, str, RelationClusterType, str], list[tuple[str, str]]] = {}
    for summary in summaries:
        for cluster_type in _cluster_types(summary):
            key = (
                summary.owner_id,
                summary.notebook_id,
                cluster_type,
                summary.aggregation_version,
            )
            edges.setdefault(key, []).append(
                (summary.source_document_id, summary.target_document_id)
            )

    clusters: list[RelationCluster] = []
    for (owner_id, notebook_id, cluster_type, version), group_edges in sorted(
        edges.items(), key=lambda item: tuple(str(value) for value in item[0])
    ):
        for members in _components(group_edges):
            cluster_id = _cluster_id(cluster_type, owner_id, notebook_id, members, version)
            clusters.append(
                RelationCluster(
                    cluster_id=cluster_id,
                    cluster_type=cluster_type,
                    owner_id=owner_id,
                    notebook_id=notebook_id,
                    document_ids=members,
                    aggregation_version=version,
                )
            )
    return tuple(sorted(clusters, key=lambda item: (item.cluster_type.value, item.cluster_id)))


def _cluster_types(summary: RelationEvidenceSummary) -> tuple[RelationClusterType, ...]:
    values: list[RelationClusterType] = []
    if summary.primary_relation is FinalRelationType.EXACT_DUPLICATE:
        values.append(RelationClusterType.EXACT_DUPLICATE)
    elif summary.primary_relation is FinalRelationType.NEAR_DUPLICATE:
        values.append(RelationClusterType.NEAR_DUPLICATE)
    if (
        summary.primary_relation is FinalRelationType.VERSION_UPDATE
        or summary.facets.has_version_changes
    ):
        values.append(RelationClusterType.VERSION_FAMILY)
    if summary.primary_relation is FinalRelationType.CONFLICT or summary.facets.has_conflict:
        values.append(RelationClusterType.CONFLICT_GROUP)
    return tuple(values)


def _components(edges: list[tuple[str, str]]) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, set[str]] = {}
    for source, target in edges:
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    remaining = set(adjacency)
    output: list[tuple[str, ...]] = []
    while remaining:
        root = min(remaining)
        stack = [root]
        members: set[str] = set()
        while stack:
            node = stack.pop()
            if node in members:
                continue
            members.add(node)
            stack.extend(sorted(adjacency.get(node, ()), reverse=True))
        remaining.difference_update(members)
        output.append(tuple(sorted(members)))
    return tuple(output)


def _cluster_id(
    cluster_type: RelationClusterType,
    owner_id: str,
    notebook_id: str,
    members: tuple[str, ...],
    version: str,
) -> str:
    payload = "|".join((cluster_type.value, owner_id, notebook_id, version, *members))
    return f"p4-{cluster_type.value}-{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


__all__ = [
    "RelationCluster",
    "RelationClusterType",
    "build_relation_clusters",
]
