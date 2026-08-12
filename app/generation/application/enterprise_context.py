"""P6 Enterprise adapter around the frozen P5 GenerationContext builder."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import replace

from app.generation.application.evidence_context import (
    EvidenceContextPolicy,
    build_generation_context,
)
from app.generation.domain.evidence import EvidenceProvenance, GenerationContext
from app.retrieval.application.query_context import QueryContext
from app.retrieval.domain.models import RetrievalCandidate


def build_enterprise_generation_context(
    query: QueryContext,
    candidates: tuple[RetrievalCandidate, ...],
    *,
    authorized_document_ids: frozenset[str],
    policy: EvidenceContextPolicy,
) -> GenerationContext:
    """Build P5 context and retain only authorized collapsed provenance."""

    context = build_generation_context(
        query,
        candidates,
        authorized_document_ids=authorized_document_ids,
        policy=policy,
    )
    source = {item.chunk.id: item for item in candidates}
    repaired = []
    for evidence in context.evidence:
        candidate = source.get(evidence.chunk_id)
        chunk_ids = _strings(
            candidate.chunk.metadata.get("p4_provenance_chunk_ids") if candidate else None
        )
        document_ids = _strings(
            candidate.chunk.metadata.get("p4_provenance_document_ids") if candidate else None
        )
        visible_documents = tuple(
            value for value in document_ids if value in authorized_document_ids
        )
        if chunk_ids or visible_documents:
            all_chunks = tuple(dict.fromkeys((evidence.chunk_id, *chunk_ids)))
            all_documents = tuple(dict.fromkeys((evidence.document_id, *visible_documents)))
            evidence = replace(
                evidence,
                provenance=EvidenceProvenance(
                    document_ids=all_documents,
                    chunk_ids=all_chunks,
                    occurrence_count=max(len(all_chunks), len(all_documents), 1),
                ),
            )
        repaired.append(evidence)
    return replace(context, evidence=tuple(repaired))


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Iterable) and not isinstance(value, bytes | Mapping | str):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


__all__ = ["build_enterprise_generation_context"]
