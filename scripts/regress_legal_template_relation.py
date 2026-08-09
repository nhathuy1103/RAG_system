"""Run the bounded pre-embedding relation plan for two local PDF documents."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from app.knowledge_quality.application.chunk_preembedding import (
    build_chunk_dedup_probes,
    plan_chunk_deduplication,
    simhash_lsh_bands,
)
from app.knowledge_quality.application.scope import extract_claim_scope
from app.knowledge_quality.domain.models import (
    ChunkDedupCandidate,
    ChunkDedupProbe,
    ClaimScope,
    RelationType,
)
from app.pipeline.documents.adapters.parsers import PdfParser
from app.pipeline.documents.domain.parsed import ParsedDocument
from app.pipeline.indexing.application.chunker import ChunkData, Chunker

EMBEDDING_MODEL = "regression-dummy-v1"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--chunk-size", type=int, default=600)
    parser.add_argument("--overlap", type=int, default=80)
    parser.add_argument("--max-probes", type=int, default=8)
    parser.add_argument("--candidates-per-probe", type=int, default=5)
    args = parser.parse_args()

    left = _load(args.left, chunk_size=args.chunk_size, overlap=args.overlap)
    right = _load(args.right, chunk_size=args.chunk_size, overlap=args.overlap)
    left_to_right = _run_direction(
        left,
        right,
        max_probes=args.max_probes,
        candidates_per_probe=args.candidates_per_probe,
    )
    right_to_left = _run_direction(
        right,
        left,
        max_probes=args.max_probes,
        candidates_per_probe=args.candidates_per_probe,
    )
    result = {
        "left": left.path.name,
        "right": right.path.name,
        "left_pages": len(left.parsed.pages),
        "right_pages": len(right.parsed.pages),
        "left_chunks": len(left.chunks),
        "right_chunks": len(right.chunks),
        "exact_line_matches": len(_raw_lines(left.parsed.text) & _raw_lines(right.parsed.text)),
        "normalized_line_matches": len(
            _normalized_lines(left.parsed.text) & _normalized_lines(right.parsed.text)
        ),
        "left_scope": left.scope.to_metadata(),
        "right_scope": right.scope.to_metadata(),
        "left_to_right": left_to_right,
        "right_to_left": right_to_left,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    for direction in (left_to_right, right_to_left):
        if direction["validated_conflict_count"] != 0:
            raise SystemExit("Regression failed: validated document conflict remains")
        if direction["document_relation"] == RelationType.CONFLICT_CANDIDATE.value:
            raise SystemExit("Regression failed: document relation remains conflict_candidate")
    if left_to_right["document_relation"] != right_to_left["document_relation"]:
        raise SystemExit("Regression failed: relation type depends on upload order")


@dataclass(frozen=True, slots=True)
class _LoadedDocument:
    path: Path
    parsed: ParsedDocument
    chunks: list[ChunkData]
    scope: ClaimScope


def _load(path: Path, *, chunk_size: int, overlap: int) -> _LoadedDocument:
    parsed = PdfParser().parse(path.read_bytes())
    document_id = str(uuid5(NAMESPACE_URL, str(path.resolve())))
    chunks = Chunker.structure_recursive(chunk_size=chunk_size, overlap=overlap).chunk(
        document_id,
        1,
        parsed,
    )
    scope = extract_claim_scope(
        parsed.text,
        document_id=document_id,
        filename=path.name,
        version_id="1",
    )
    return _LoadedDocument(path, parsed, chunks, scope)


def _run_direction(
    source: _LoadedDocument,
    target: _LoadedDocument,
    *,
    max_probes: int,
    candidates_per_probe: int,
) -> dict[str, object]:
    source_probes = build_chunk_dedup_probes(
        source.chunks,
        max_fuzzy_probes=max_probes,
        scope=source.scope,
    )
    target_probes = build_chunk_dedup_probes(
        target.chunks,
        max_fuzzy_probes=max(1, len(target.chunks)),
        scope=target.scope,
    )
    target_document_id = UUID(str(target.scope.document_id))
    candidates: list[ChunkDedupCandidate] = []
    for source_probe in source_probes:
        if not source_probe.include_fuzzy_candidates:
            continue
        ranked: list[tuple[bool, int, ChunkDedupProbe]] = []
        source_bands = simhash_lsh_bands(source_probe.fingerprint.loose_signature)
        for target_probe in target_probes:
            target_bands = simhash_lsh_bands(target_probe.fingerprint.loose_signature)
            band_matches = sum(
                left == right for left, right in zip(source_bands, target_bands, strict=True)
            )
            exact = source_probe.fingerprint.strict_hash == target_probe.fingerprint.strict_hash
            if not exact and band_matches == 0:
                continue
            ranked.append((exact, band_matches, target_probe))
        ranked.sort(key=lambda item: (-int(item[0]), -item[1], item[2].chunk_index))
        for _, band_matches, target_probe in ranked[:candidates_per_probe]:
            candidates.append(
                ChunkDedupCandidate(
                    source_chunk_index=source_probe.chunk_index,
                    target_chunk_id=target_probe.chunk_id,
                    target_document_id=target_document_id,
                    target_chunk_index=target_probe.chunk_index,
                    canonical_text=target_probe.canonical_text,
                    normalized_content_hash=target_probe.fingerprint.strict_hash,
                    normalization_version=target_probe.fingerprint.normalization_version,
                    loose_content_signature=target_probe.fingerprint.loose_signature,
                    embedding_text_checksum=target_probe.embedding_text_checksum,
                    embedding=(0.0,),
                    embedding_model=EMBEDDING_MODEL,
                    lsh_band_matches=band_matches,
                    scope=target.scope,
                )
            )
    plan = plan_chunk_deduplication(
        source_probes,
        candidates,
        embedding_model=EMBEDDING_MODEL,
        enable_exact_reuse=False,
    )
    relation = plan.relations[0] if plan.relations else None
    validated_conflicts = (
        int(relation.signals.get("validated_conflict_count", 0)) if relation else 0
    )
    return {
        "candidate_pairs": len(candidates),
        "chunk_conflict_candidates": plan.conflict_candidate_count,
        "template_variant_chunks": plan.template_variant_count,
        "validated_conflict_count": validated_conflicts,
        "document_relation": (
            relation.relation_type.value if relation else RelationType.DISTINCT.value
        ),
        "confidence": round(relation.confidence, 6) if relation else 0.0,
        "reason_codes": relation.signals.get("reason_codes", []) if relation else [],
    }


def _normalized_lines(text: str) -> set[str]:
    return {" ".join(line.split()) for line in text.splitlines() if line.strip()}


def _raw_lines(text: str) -> set[str]:
    return {line for line in text.splitlines() if line.strip()}


if __name__ == "__main__":
    main()
