"""Permission-scoped PostgREST enrichment for P4 relation-aware retrieval."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace
from uuid import UUID

import httpx2 as httpx

from app.retrieval.domain.metadata import EvidenceMetadata
from app.retrieval.domain.models import RetrievalCandidate, RetrievalFilters

_COLUMNS = (
    "source_document_id,target_document_id,relation_type,status,signals,"
    "detector_version,preferred_document_id"
)
_PRIMARY_PRIORITY = {
    "CONFLICT": 90,
    "UNCERTAIN": 80,
    "VERSION_UPDATE": 70,
    "TEMPORAL_VARIANT": 60,
    "CONDITIONAL_VARIANT": 50,
    "NEAR_DUPLICATE": 40,
    "EXACT_DUPLICATE": 30,
    "TEMPLATE_VARIANT": 20,
    "DISTINCT": 10,
}


class PostgrestRelationMetadataAdapter:
    """Read only edges whose two endpoints are already visible in retrieval."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def enrich(
        self,
        candidates: tuple[RetrievalCandidate, ...],
        filters: RetrievalFilters,
    ) -> tuple[RetrievalCandidate, ...]:
        document_ids = tuple(
            sorted(
                {
                    normalized
                    for candidate in candidates
                    if (normalized := _uuid_text(candidate.chunk.document_id)) is not None
                }
            )
        )
        if len(document_ids) < 2:
            return candidates
        in_filter = ",".join(document_ids)
        payload: list[object] = []
        document_payload: list[object] = []
        if filters.notebook_id is not None:
            response = self._client.get(
                "/document_relations",
                params={
                    "owner_id": f"eq.{filters.owner_id}",
                    "notebook_id": f"eq.{filters.notebook_id}",
                    "status": "neq.dismissed",
                    "or": (
                        f"(source_document_id.in.({in_filter}),target_document_id.in.({in_filter}))"
                    ),
                    "select": _COLUMNS,
                    "limit": "1000",
                },
            )
            response.raise_for_status()
            legacy_payload = response.json()
            if not isinstance(legacy_payload, list):
                raise TypeError("PostgREST relation metadata response must be an array")
            payload.extend(legacy_payload)
            documents_response = self._client.get(
                "/documents",
                params={
                    "id": f"in.({in_filter})",
                    "owner_id": f"eq.{filters.owner_id}",
                    "notebook_id": f"eq.{filters.notebook_id}",
                    "select": "id,version_number,is_current,status",
                    "limit": str(len(document_ids)),
                },
            )
            documents_response.raise_for_status()
            legacy_documents = documents_response.json()
            if not isinstance(legacy_documents, list):
                raise TypeError("PostgREST relation document response must be an array")
            document_payload.extend(legacy_documents)

        if not payload:
            enterprise_response = self._client.get(
                "/knowledge_document_relations",
                params={
                    "status": "neq.dismissed",
                    "or": (
                        f"(source_document_id.in.({in_filter}),target_document_id.in.({in_filter}))"
                    ),
                    "select": _COLUMNS,
                    "limit": "1000",
                },
            )
            enterprise_response.raise_for_status()
            enterprise_payload = enterprise_response.json()
            if not isinstance(enterprise_payload, list):
                raise TypeError("Enterprise relation metadata response must be an array")
            payload.extend(enterprise_payload)
        return enrich_visible_candidates(candidates, payload, document_payload, filters)


def enrich_visible_candidates(
    candidates: tuple[RetrievalCandidate, ...],
    rows: list[object],
    document_rows: list[object],
    filters: RetrievalFilters,
) -> tuple[RetrievalCandidate, ...]:
    visible = {candidate.chunk.document_id for candidate in candidates}
    edges: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    relation_labels: dict[str, set[str]] = defaultdict(set)
    preferred_documents: set[str] = set()
    retrieval_versions: dict[str, set[str]] = defaultdict(set)
    reason_codes: dict[str, set[str]] = defaultdict(set)
    claim_relations: dict[str, list[object]] = defaultdict(list)
    conflict_claims: dict[str, list[object]] = defaultdict(list)
    claim_ids: dict[str, set[str]] = defaultdict(set)
    review_statuses: dict[str, set[str]] = defaultdict(set)
    preference_reasons: dict[str, set[str]] = defaultdict(set)
    document_metadata: dict[str, dict[str, object]] = {}
    for row in document_rows:
        if not isinstance(row, Mapping):
            continue
        document_id = str(row.get("id") or "")
        if document_id not in visible:
            continue
        metadata: dict[str, object] = {}
        if row.get("version_number") is not None:
            metadata["version_number"] = int(str(row["version_number"]))
        if row.get("is_current") is not None:
            metadata["is_current"] = row["is_current"] is True or str(
                row["is_current"]
            ).casefold() in {"true", "1"}
        if row.get("status") is not None:
            metadata["document_status"] = str(row["status"])
        document_metadata[document_id] = metadata
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        source = str(row.get("source_document_id") or "")
        target = str(row.get("target_document_id") or "")
        # This is the critical non-disclosure gate: an edge with a hidden
        # endpoint contributes no group, label, preference, or provenance.
        if source not in visible or target not in visible or source == target:
            continue
        signals = row.get("signals")
        signal_map = signals if isinstance(signals, Mapping) else {}
        primary = str(signal_map.get("p4_primary_relation") or "").upper()
        if not primary:
            primary = _legacy_primary(str(row.get("relation_type") or ""))
        facets = signal_map.get("p4_facets")
        facet_map = facets if isinstance(facets, Mapping) else {}
        detector_version = str(row.get("detector_version") or "unknown")
        for group_type in _group_types(primary, facet_map):
            edges[group_type].append((source, target, detector_version))
        if primary:
            relation_labels[source].add(primary)
            relation_labels[target].add(primary)
        for value in _string_sequence(signal_map.get("p4_reason_codes")):
            reason_codes[source].add(value)
            reason_codes[target].add(value)
        for relation_payload in _mapping_sequence(signal_map.get("p4_claim_relations")):
            claim_relations[source].append(relation_payload)
            claim_relations[target].append(relation_payload)
            for key in ("source_claim_id", "target_claim_id"):
                claim_id = str(relation_payload.get(key) or "").strip()
                if claim_id:
                    claim_ids[source].add(claim_id)
                    claim_ids[target].add(claim_id)
        for conflict_payload in _mapping_sequence(signal_map.get("p4_conflict_claims")):
            conflict_claims[source].append(conflict_payload)
            conflict_claims[target].append(conflict_payload)
        review_status = str(signal_map.get("p4_review_status") or "").strip()
        if review_status:
            review_statuses[source].add(review_status)
            review_statuses[target].add(review_status)
        preference = signal_map.get("p4_preference")
        if isinstance(preference, Mapping):
            preferred = str(preference.get("document_id") or "")
            if preferred in {source, target}:
                preferred_documents.add(preferred)
            preference_reason = str(preference.get("reason") or "").strip()
            if preference_reason:
                preference_reasons[source].add(preference_reason)
                preference_reasons[target].add(preference_reason)
        versions = signal_map.get("p4_versions")
        if isinstance(versions, Mapping) and versions.get("retrieval"):
            version = str(versions["retrieval"])
            retrieval_versions[source].add(version)
            retrieval_versions[target].add(version)

    assignments: dict[str, dict[str, str]] = defaultdict(dict)
    for group_type, group_edges in edges.items():
        for members, versions in _components(group_edges):
            group_id = _group_id(
                group_type,
                filters.owner_id,
                filters.notebook_id or "",
                members,
                versions,
            )
            metadata_key = {
                "exact": "p4_exact_duplicate_group_id",
                "near": "near_duplicate_group_id",
                "version": "version_family_id",
                "conflict": "conflict_group_id",
                "conditional": "conditional_variant_group_id",
                "temporal": "temporal_series_group_id",
            }[group_type]
            for document_id in members:
                assignments[document_id][metadata_key] = group_id

    output: list[RetrievalCandidate] = []
    for candidate in candidates:
        document_id = candidate.chunk.document_id
        metadata = dict(candidate.chunk.metadata)
        metadata.update(document_metadata.get(document_id, {}))
        metadata.update(assignments.get(document_id, {}))
        labels = relation_labels.get(document_id, set())
        if labels:
            metadata["p4_relation_type"] = max(
                labels,
                key=lambda item: (_PRIMARY_PRIORITY.get(item, 0), item),
            )
        if document_id in preferred_documents:
            metadata["p4_preferred_evidence"] = True
        if reason_codes[document_id]:
            metadata["p4_reason_codes"] = sorted(reason_codes[document_id])
        if claim_relations[document_id]:
            metadata["p4_claim_relations"] = claim_relations[document_id]
        if conflict_claims[document_id]:
            metadata["p4_conflict_claims"] = conflict_claims[document_id]
        if claim_ids[document_id]:
            metadata["p4_claim_ids"] = sorted(claim_ids[document_id])
        if review_statuses[document_id]:
            metadata["p4_review_status"] = sorted(review_statuses[document_id])
        if preference_reasons[document_id]:
            metadata["authority_reason"] = "; ".join(sorted(preference_reasons[document_id]))
        versions = retrieval_versions.get(document_id, set())
        if len(versions) == 1:
            metadata["p4_relation_policy_version"] = next(iter(versions))
        output.append(
            replace(
                candidate,
                chunk=replace(
                    candidate.chunk,
                    metadata=EvidenceMetadata.from_mapping(metadata),
                ),
            )
        )
    return tuple(output)


def _group_types(primary: str, facets: Mapping[object, object]) -> tuple[str, ...]:
    output: list[str] = []
    if primary == "EXACT_DUPLICATE":
        output.append("exact")
    elif primary == "NEAR_DUPLICATE":
        output.append("near")
    if primary == "VERSION_UPDATE" or facets.get("has_version_changes") is True:
        output.append("version")
    if primary == "CONFLICT" or facets.get("has_conflict") is True:
        output.append("conflict")
    if primary == "CONDITIONAL_VARIANT" or facets.get("has_conditional_variants") is True:
        output.append("conditional")
    if primary == "TEMPORAL_VARIANT" or facets.get("has_temporal_variants") is True:
        output.append("temporal")
    return tuple(output)


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _mapping_sequence(value: object) -> tuple[Mapping[object, object], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _legacy_primary(relation_type: str) -> str:
    return {
        "exact_content": "EXACT_DUPLICATE",
        "technical_duplicate": "EXACT_DUPLICATE",
        "near_duplicate": "NEAR_DUPLICATE",
        "version": "VERSION_UPDATE",
        "version_candidate": "UNCERTAIN",
        "temporal_series": "TEMPORAL_VARIANT",
        "conflict": "CONFLICT",
        "conflict_candidate": "UNCERTAIN",
        "template_variant": "TEMPLATE_VARIANT",
        "distinct": "DISTINCT",
    }.get(relation_type, "")


def _components(
    edges: list[tuple[str, str, str]],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    versions_by_node: dict[str, set[str]] = defaultdict(set)
    for source, target, version in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
        versions_by_node[source].add(version)
        versions_by_node[target].add(version)
    remaining = set(adjacency)
    output: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    while remaining:
        stack = [min(remaining)]
        members: set[str] = set()
        versions: set[str] = set()
        while stack:
            node = stack.pop()
            if node in members:
                continue
            members.add(node)
            versions.update(versions_by_node[node])
            stack.extend(sorted(adjacency[node] - members, reverse=True))
        remaining.difference_update(members)
        output.append((tuple(sorted(members)), tuple(sorted(versions))))
    return tuple(output)


def _group_id(
    group_type: str,
    owner_id: str,
    notebook_id: str,
    members: tuple[str, ...],
    versions: tuple[str, ...],
) -> str:
    payload = "|".join((group_type, owner_id, notebook_id, *versions, *members))
    return f"p4-{group_type}-{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _uuid_text(value: str) -> str | None:
    try:
        return str(UUID(value))
    except ValueError:
        return None


__all__ = ["PostgrestRelationMetadataAdapter", "enrich_visible_candidates"]
