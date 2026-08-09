"""Build and run an isolated A/B/C/D metadata retrieval experiment.

The harness reuses the repository parser, structure-aware chunker, BM25,
RRF, and MMR implementations. It never writes to Supabase or the production
vector store. Use ``--embedding-provider hashing`` for a free deterministic
smoke test and ``--embedding-provider openai`` for the production-like run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.pipeline.documents.adapters.parsers import ParserRegistry  # noqa: E402
from app.pipeline.documents.application.extraction_pipeline import (  # noqa: E402
    sanitize_parsed_document,
)
from app.pipeline.documents.domain.models import DocumentType  # noqa: E402
from app.pipeline.indexing.adapters.context_enrichers import (  # noqa: E402
    CONTEXT_ENRICHMENT_PROMPT_VERSION,
    OpenAIChunkContextEnricherConfig,
    create_openai_chunk_context_enricher,
)
from app.pipeline.indexing.adapters.embedding_providers import (  # noqa: E402
    OpenAIEmbeddingProvider,
)
from app.pipeline.indexing.application.chunker import Chunker  # noqa: E402
from app.pipeline.indexing.domain.context_enrichment import (  # noqa: E402
    ChunkContextEnrichmentRequest,
    select_context_scope_metadata,
)
from app.pipeline.indexing.domain.retrieval_metadata import (  # noqa: E402
    normalize_chunk_retrieval_metadata,
)
from app.retrieval.adapters.bm25_search import InMemoryBM25RetrievalAdapter  # noqa: E402
from app.retrieval.adapters.dense_search import embed as hashing_embed  # noqa: E402
from app.retrieval.adapters.fusion import ReciprocalRankFusion  # noqa: E402
from app.retrieval.adapters.mmr_reranker import (  # noqa: E402
    MaximalMarginalRelevanceReranker,
)
from app.retrieval.adapters.scope_filter import matches_scope  # noqa: E402
from app.retrieval.domain.models import (  # noqa: E402
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
)
from app.shared.contextual_text import (  # noqa: E402
    CONTEXTUAL_TEXT_VERSION,
    ChunkContext,
    build_embedding_text,
    build_search_text,
)

DEFAULT_TESTSET = SCRIPT_DIR / "testset.jsonl"
DEFAULT_GOLD = SCRIPT_DIR / "gold_metadata.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "runs" / "latest"
DEFAULT_CACHE = SCRIPT_DIR / ".cache" / "embedding_cache.json"
DEFAULT_CONTEXT_CACHE = SCRIPT_DIR / ".cache" / "context_enrichment_cache.json"
DEFAULT_MODES = (
    "no_metadata",
    "current_metadata",
    "shuffled_metadata",
    "gold_metadata",
)
V6_PLACEMENT_MODES = (
    "v6a_filter_only",
    "v6b_filter_plus_search_text",
    "v6c_filter_plus_embedding_text",
)
FILTER_FIELD_ABLATION_MODES = (
    "filter_full",
    "filter_drop_document_type",
    "filter_drop_project_name",
    "filter_drop_year",
    "filter_drop_lifecycle_status",
    "filter_drop_source",
    "filter_drop_all_domain",
)
FILTER_FIELDS_DROPPED_BY_MODE = {
    "filter_full": frozenset(),
    "filter_drop_document_type": frozenset({"document_type"}),
    "filter_drop_project_name": frozenset({"project_name"}),
    "filter_drop_year": frozenset({"year"}),
    "filter_drop_lifecycle_status": frozenset({"lifecycle_status"}),
    "filter_drop_source": frozenset({"source"}),
    "filter_drop_all_domain": frozenset(
        {"document_type", "project_name", "year", "lifecycle_status", "source"}
    ),
}


def _filter_fields_dropped_by_mode(mode: str) -> frozenset[str]:
    configured = FILTER_FIELDS_DROPPED_BY_MODE.get(mode)
    if configured is not None:
        return configured
    prefix = "filter_drop_"
    if mode.startswith(prefix):
        field = mode.removeprefix(prefix).strip()
        if field:
            return frozenset({field})
    return frozenset()


def _is_filter_ablation_mode(mode: str) -> bool:
    return mode == "filter_full" or mode.startswith("filter_drop_")
CONTEXT_QUALITY_MODES = (
    "ctx_a_chunk_only",
    "ctx_b_deterministic_header",
    "ctx_c_raw_context_dense_only",
    "ctx_c_raw_context_sparse_only",
    "ctx_c_raw_context",
    "ctx_d_effective_context",
    "ctx_e_shuffled_context",
    *FILTER_FIELD_ABLATION_MODES,
)
ABLATION_MODES = (
    "v0_raw_text",
    "v1_document_identity",
    "v2_section_structure",
    "v3_block_aware",
    "v4_context_summary",
    "v5_context_terms",
    "v6_domain_metadata",
    *V6_PLACEMENT_MODES,
)
ABLATION_LEVEL_BY_MODE = {
    "v0_raw_text": 0,
    "v1_document_identity": 1,
    "v2_section_structure": 2,
    "v3_block_aware": 3,
    "v4_context_summary": 4,
    "v5_context_terms": 5,
    "v6_domain_metadata": 6,
    **{mode: 6 for mode in V6_PLACEMENT_MODES},
}
DOMAIN_FILTER_MODES = frozenset(("v6_domain_metadata", *V6_PLACEMENT_MODES))
DOMAIN_SEARCH_TEXT_MODES = frozenset(
    ("v6_domain_metadata", "v6b_filter_plus_search_text")
)
DOMAIN_EMBEDDING_TEXT_MODES = frozenset(
    ("v6_domain_metadata", "v6c_filter_plus_embedding_text")
)
SEMANTIC_FIELDS = (
    "title",
    "document_type",
    "section_title",
    "section_path",
    "content_kind",
    "table_header",
    "figure_caption",
    "keyword_aliases",
    "contextual_summary",
    "contextual_search_terms",
    "domain",
    "clause_type",
    "policy_field",
    "fee_type",
    "deadline_type",
    "year",
    "faculty",
    "department",
    "source",
    "source_kind",
    "document_version",
    "effective_status",
    "lifecycle_status",
    "published_at",
    "as_of_date",
    "data_period",
    "project_name",
    "project_code",
    "project_status",
    "region",
    "market_type",
    "reliability_grade",
    "source_code",
)

DOMAIN_METADATA_FIELDS = (
    "domain",
    "clause_type",
    "policy_field",
    "fee_type",
    "deadline_type",
    "year",
    "faculty",
    "department",
    "source",
    "source_kind",
    "document_version",
    "effective_status",
    "lifecycle_status",
    "published_at",
    "as_of_date",
    "data_period",
    "project_name",
    "project_code",
    "project_status",
    "region",
    "market_type",
    "reliability_grade",
    "source_code",
)

SECURITY_METADATA_FIELDS = {
    "owner_id",
    "notebook_id",
    "visibility",
    "allowed_groups",
}


@dataclass(frozen=True)
class EvalChunk:
    id: str
    document_id: str
    document_title: str
    chunk_index: int
    page_number: int | None
    text: str
    current_metadata: dict[str, Any]
    gold_metadata: dict[str, Any]
    gold_annotated: bool
    owner_id: str = "eval-owner"
    notebook_id: str = "eval-notebook"
    visibility: str = "internal"
    allowed_groups: tuple[str, ...] = ()
    source_block_ids: tuple[str, ...] = ()
    table_identity: str | None = None
    table_location: str | None = None
    bbox: tuple[float, ...] = ()


@dataclass(frozen=True)
class Projection:
    chunk: EvalChunk
    retrieval_metadata: dict[str, Any]
    embedding_text: str
    search_text: str


@dataclass(frozen=True)
class ContextEnrichmentStats:
    source: str
    model: str | None
    cache_hits: int = 0
    generated_count: int = 0
    not_needed_count: int = 0
    fallback_count: int = 0
    estimated_new_input_tokens: int = 0


@dataclass
class DenseIndex:
    chunks: dict[str, EvidenceChunk]
    vectors: dict[str, tuple[float, ...]]

    def search(
        self,
        query_vector: tuple[float, ...],
        *,
        top_k: int,
        filters: RetrievalFilters,
        predicate: Callable[[EvidenceChunk], bool] | None = None,
    ) -> tuple[RetrievalCandidate, ...]:
        scored: list[tuple[float, str]] = []
        query_norm = _norm(query_vector)
        for chunk_id, vector in self.vectors.items():
            chunk = self.chunks[chunk_id]
            if not matches_scope(chunk, filters):
                continue
            if predicate is not None and not predicate(chunk):
                continue
            score = _cosine(query_vector, vector, query_norm=query_norm)
            if score > 0:
                scored.append((score, chunk_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            RetrievalCandidate(
                chunk=self.chunks[chunk_id],
                score=score,
                rank=rank,
                source="dense",
            )
            for rank, (score, chunk_id) in enumerate(scored[:top_k], start=1)
        )


@dataclass
class ModeIndex:
    sparse: InMemoryBM25RetrievalAdapter
    dense: DenseIndex
    fusion: ReciprocalRankFusion
    reranker: MaximalMarginalRelevanceReranker
    corpus_size: int
    filterable_fields: frozenset[str]

    def search(
        self,
        query: str,
        query_vector: tuple[float, ...],
        *,
        candidate_k: int,
        top_k: int,
        filters: RetrievalFilters,
        metadata_conditions: tuple[dict[str, Any], ...] = (),
        user_groups: tuple[str, ...] = (),
    ) -> tuple[RetrievalCandidate, ...]:
        def predicate(chunk: EvidenceChunk) -> bool:
            return _candidate_allowed(
                chunk,
                filterable_fields=self.filterable_fields,
                metadata_conditions=metadata_conditions,
                user_groups=user_groups,
            )

        sparse_limit = self.corpus_size if metadata_conditions or user_groups else candidate_k
        sparse = self.sparse.search(query, filters, top_k=sparse_limit)
        sparse = tuple(candidate for candidate in sparse if predicate(candidate.chunk))[
            :candidate_k
        ]
        dense = self.dense.search(
            query_vector,
            top_k=candidate_k,
            filters=filters,
            predicate=predicate,
        )
        fused = self.fusion.fuse(
            {"sparse": sparse, "dense": dense},
            top_k=max(candidate_k, top_k),
        )
        return self.reranker.rerank(query, fused, top_k=top_k)


class CachedEmbedder:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        cache_path: Path,
    ) -> None:
        self.provider_name = provider
        self.model = model if provider == "openai" else "hashing-char-trigram-256"
        self.cache_path = cache_path
        self.cache_hits = 0
        self.cache_misses = 0
        self.estimated_input_tokens = 0
        self._vectors: dict[str, list[float]] = {}
        self._provider: OpenAIEmbeddingProvider | None = None
        if provider == "openai":
            _load_dotenv(REPO_ROOT / ".env")
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise SystemExit(
                    "OPENAI_API_KEY is required for --embedding-provider openai. "
                    "Configure it in .env or the current PowerShell session."
                )
            self._provider = OpenAIEmbeddingProvider(
                api_key=api_key,
                model=model,
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
                batch_size=int(os.getenv("OPENAI_EMBEDDING_BATCH_SIZE", "64")),
            )
            self._load_cache()

    def _key(self, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self.provider_name}:{self.model}:{digest}"

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        vectors = payload.get("vectors", {}) if isinstance(payload, dict) else {}
        if isinstance(vectors, dict):
            self._vectors = {
                str(key): [float(value) for value in vector]
                for key, vector in vectors.items()
                if isinstance(vector, list)
            }

    def _save_cache(self) -> None:
        if self.provider_name != "openai":
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.cache_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps({"schema_version": 1, "vectors": self._vectors}, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(self.cache_path)

    def embed_many(self, texts: list[str]) -> dict[str, tuple[float, ...]]:
        unique = list(dict.fromkeys(texts))
        if self.provider_name == "hashing":
            self.cache_misses += len(unique)
            self.estimated_input_tokens += sum(_estimate_tokens(text) for text in unique)
            return {text: hashing_embed(text) for text in unique}

        missing: list[str] = []
        for text in unique:
            if self._key(text) in self._vectors:
                self.cache_hits += 1
            else:
                missing.append(text)
        if missing:
            assert self._provider is not None
            vectors = self._provider.embed(missing)
            for text, vector in zip(missing, vectors, strict=True):
                self._vectors[self._key(text)] = vector
            self.cache_misses += len(missing)
            self.estimated_input_tokens += sum(_estimate_tokens(text) for text in missing)
            self._save_cache()
        return {
            text: tuple(float(value) for value in self._vectors[self._key(text)]) for text in unique
        }


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _norm(vector: tuple[float, ...]) -> float:
    return math.sqrt(sum(value * value for value in vector)) or 1.0


def _cosine(
    left: tuple[float, ...],
    right: tuple[float, ...],
    *,
    query_norm: float | None = None,
) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimension mismatch in evaluation index")
    denominator = (query_norm or _norm(left)) * _norm(right)
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _estimate_tokens(text: str) -> int:
    return len(text.split())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
    return rows


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.casefold().split())


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _contains(text: str, term: str) -> bool:
    haystack = _normalize(text)
    needle = _normalize(term)
    return needle in haystack or _strip_accents(needle) in _strip_accents(haystack)


def _metadata_values(value: object) -> tuple[object, ...]:
    if isinstance(value, list | tuple | set):
        return tuple(value)
    return (value,)


def _metadata_condition_matches(metadata: dict[str, Any], condition: dict[str, Any]) -> bool:
    field = str(condition.get("field") or "").strip()
    if not field:
        return True
    actual = metadata.get(field)
    expected = condition.get("value")
    operator = str(condition.get("op") or "eq").lower()
    actual_values = _metadata_values(actual)
    expected_values = _metadata_values(expected)

    if operator == "eq":
        return any(
            _normalize(left) == _normalize(right)
            for left in actual_values
            for right in expected_values
        )
    if operator == "in":
        return any(
            _normalize(left) == _normalize(right)
            for left in actual_values
            for right in expected_values
        )
    if operator == "contains":
        return any(
            _contains(str(left), str(right)) for left in actual_values for right in expected_values
        )
    if operator in {"gte", "lte", "gt", "lt"}:
        try:
            left = float(actual)  # type: ignore[arg-type]
            right = float(expected)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        return {
            "gte": left >= right,
            "lte": left <= right,
            "gt": left > right,
            "lt": left < right,
        }[operator]
    raise ValueError(f"Unsupported metadata filter operator: {operator}")


def _candidate_allowed(
    chunk: EvidenceChunk,
    *,
    filterable_fields: frozenset[str],
    metadata_conditions: tuple[dict[str, Any], ...],
    user_groups: tuple[str, ...],
) -> bool:
    metadata = dict(chunk.metadata)
    visibility = _normalize(metadata.get("visibility"))
    allowed_groups = {
        _normalize(value) for value in _metadata_values(metadata.get("allowed_groups", [])) if value
    }
    if visibility == "restricted" and not (allowed_groups & {_normalize(v) for v in user_groups}):
        return False
    return all(
        _metadata_condition_matches(metadata, condition)
        for condition in metadata_conditions
        if str(condition.get("field") or "") in filterable_fields
    )


def _semantic_metadata(
    chunk_metadata: dict[str, Any],
    profile: dict[str, Any],
    *,
    inject_profile_metadata: bool = True,
) -> dict[str, Any]:
    nested = chunk_metadata.get("retrieval_metadata")
    metadata = dict(nested) if isinstance(nested, dict) else {}
    for key in (
        "heading",
        "section_path",
        "block_type",
        "table_header",
        "language",
    ):
        value = chunk_metadata.get(key)
        if value not in (None, ""):
            metadata.setdefault(key, value)
    if inject_profile_metadata:
        metadata.update(
            profile.get("current_document_metadata", profile.get("document_metadata", {}))
        )
    metadata["section_title"] = metadata.get("section_title") or metadata.get("heading")
    metadata["content_kind"] = metadata.get("content_kind") or metadata.get("block_type")
    metadata.pop("heading", None)
    metadata.pop("block_type", None)
    return {key: value for key, value in metadata.items() if value not in (None, "", [], {})}


def _rule_matches(
    rule: dict[str, Any],
    *,
    page: int | None,
    text: str,
    metadata: dict[str, Any],
) -> bool:
    pages = rule.get("pages")
    if isinstance(pages, list) and page not in pages:
        return False
    contains_any = rule.get("contains_any")
    if isinstance(contains_any, list) and not any(_contains(text, term) for term in contains_any):
        return False
    section_titles = rule.get("section_titles")
    if isinstance(section_titles, list):
        actual_section = metadata.get("section_title") or metadata.get("heading") or ""
        if not any(_normalize(actual_section) == _normalize(value) for value in section_titles):
            return False
    return bool(pages or contains_any or section_titles)


def _fallback_contextual_summary(gold: dict[str, Any]) -> str | None:
    terms = gold.get("contextual_search_terms")
    if not isinstance(terms, list):
        return None
    topics = [
        topic
        for term in terms[:4]
        if (topic := " ".join(str(term).split()).strip())
    ]
    if not topics:
        return None

    section = " ".join(str(gold.get("section_title") or "").split()).strip()
    section_key = section.casefold()
    if section_key in {"docx", "pdf", "document", "unknown", "n/a"} or section_key.startswith(
        ("page ", "trang ")
    ):
        section = ""

    topic_text = ", ".join(topics)
    if section:
        return f"{section} xác định phạm vi liên quan đến {topic_text}."
    return f"Ngữ cảnh định vị liên quan đến {topic_text}."


def _gold_metadata(
    current: dict[str, Any],
    profile: dict[str, Any],
    *,
    page: int | None,
    text: str,
) -> tuple[dict[str, Any], bool]:
    gold = {**current, **profile.get("document_metadata", {})}
    matched = False
    for rule in profile.get("rules", []):
        if not isinstance(rule, dict) or not _rule_matches(
            rule,
            page=page,
            text=text,
            metadata=current,
        ):
            continue
        values = rule.get("metadata")
        if isinstance(values, dict):
            gold.update(values)
            matched = True
    if (
        matched
        and not gold.get("contextual_summary")
        and (fallback_summary := _fallback_contextual_summary(gold))
    ):
        gold["contextual_summary"] = fallback_summary
    return gold, matched


def build_corpus(
    *,
    source_dir: Path,
    gold_config: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
    production_metadata_only: bool = False,
) -> tuple[list[EvalChunk], list[dict[str, Any]]]:
    registry = ParserRegistry()
    chunker = Chunker.structure_recursive(chunk_size=chunk_size, overlap=chunk_overlap)
    corpus: list[EvalChunk] = []
    snapshots: list[dict[str, Any]] = []

    for filename, profile_value in gold_config["documents"].items():
        profile = dict(profile_value)
        path = source_dir / filename
        if not path.exists():
            raise SystemExit(f"Missing source document: {path}")
        content = path.read_bytes()
        document_hash = hashlib.sha256(content).hexdigest()
        document_id = f"eval-{document_hash[:16]}"
        parsed = registry.get_parser(filename).parse(content)
        parsed = sanitize_parsed_document(parsed)
        document_metadata = (
            {}
            if production_metadata_only
            else profile.get(
                "current_document_metadata", profile.get("document_metadata", {})
            )
        )
        parsed.document_metadata.update(
            {
                **document_metadata,
                "document_id": document_id,
                "document_version": 1,
                "title": filename,
                "source_title": filename,
            }
        )
        parsed.logical_document = None
        logical = parsed.to_logical_document()
        logical.title = filename
        if not production_metadata_only:
            raw_document_type = str(document_metadata.get("document_type") or "unknown")
            try:
                logical.document_type = DocumentType(raw_document_type)
            except ValueError:
                logical.document_type = DocumentType.UNKNOWN

        chunk_rows = chunker.chunk(document_id, 1, parsed)
        for chunk in chunk_rows:
            if production_metadata_only:
                current = normalize_chunk_retrieval_metadata(
                    chunk_metadata=chunk.metadata,
                    document_metadata=parsed.document_metadata,
                    source_metadata={},
                    title=filename,
                    section_title=chunk.section_title,
                )
            else:
                current = _semantic_metadata(chunk.metadata, profile)
            current["page_number"] = chunk.page_number
            current["chunk_index"] = chunk.chunk_index
            gold, annotated = _gold_metadata(
                current,
                profile,
                page=chunk.page_number,
                text=chunk.text,
            )
            corpus.append(
                EvalChunk(
                    id=chunk.chunk_id,
                    document_id=document_id,
                    document_title=filename,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    text=chunk.text,
                    current_metadata=current,
                    gold_metadata=gold,
                    gold_annotated=annotated,
                    source_block_ids=tuple(chunk.source_block_ids),
                    table_identity=chunk.table_identity,
                    table_location=(
                        str(chunk.metadata.get("table_location"))
                        if chunk.metadata.get("table_location")
                        else None
                    ),
                    bbox=tuple(
                        float(value)
                        for value in chunk.metadata.get("bbox", [])
                        if isinstance(value, int | float)
                    ),
                )
            )
        stat = path.stat()
        snapshots.append(
            {
                "filename": filename,
                "path": str(path.resolve()),
                "sha256": document_hash,
                "size_bytes": stat.st_size,
                "modified_at_epoch": stat.st_mtime,
                "parser": parsed.parser_name,
                "parser_version": parsed.parser_version,
                "chunk_count": len(chunk_rows),
                "metadata_source": (
                    "production_pipeline" if production_metadata_only else "benchmark_profile"
                ),
            }
        )
    return corpus, snapshots


def load_fixture_corpus(path: Path) -> tuple[list[EvalChunk], list[dict[str, Any]]]:
    rows = _load_jsonl(path)
    corpus: list[EvalChunk] = []
    for line_number, row in enumerate(rows, start=1):
        security = row.get("security")
        security = security if isinstance(security, dict) else {}
        provenance = row.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        try:
            corpus.append(
                EvalChunk(
                    id=str(row["chunk_id"]),
                    document_id=str(row["document_id"]),
                    document_title=str(row["document_title"]),
                    chunk_index=int(row["chunk_index"]),
                    page_number=(
                        None if row.get("page_number") in (None, "") else int(row["page_number"])
                    ),
                    text=str(row["text"]),
                    current_metadata=dict(row.get("current_metadata") or {}),
                    gold_metadata=dict(row.get("gold_metadata") or {}),
                    gold_annotated=bool(row.get("gold_annotated", True)),
                    owner_id=str(security.get("owner_id") or "eval-owner"),
                    notebook_id=str(security.get("notebook_id") or "eval-notebook"),
                    visibility=str(security.get("visibility") or "internal"),
                    allowed_groups=tuple(
                        str(value) for value in security.get("allowed_groups", [])
                    ),
                    source_block_ids=tuple(
                        str(value) for value in provenance.get("source_block_ids", [])
                    ),
                    table_identity=(
                        str(provenance["table_identity"])
                        if provenance.get("table_identity")
                        else None
                    ),
                    table_location=(
                        str(provenance["table_location"])
                        if provenance.get("table_location")
                        else None
                    ),
                    bbox=tuple(
                        float(value)
                        for value in provenance.get("bbox", [])
                        if isinstance(value, int | float)
                    ),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"{path}:{line_number}: invalid corpus fixture row: {exc}") from exc
    ids = [chunk.id for chunk in corpus]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"Corpus fixture contains duplicate chunk IDs: {path}")
    return corpus, [
        {
            "filename": path.name,
            "path": str(path.resolve()),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
            "modified_at_epoch": path.stat().st_mtime,
            "parser": "jsonl_fixture",
            "parser_version": "2.0",
            "chunk_count": len(corpus),
        }
    ]


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _context_request_payload(request: ChunkContextEnrichmentRequest, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": CONTEXT_ENRICHMENT_PROMPT_VERSION,
        "document_title": request.document_title,
        "document_type": request.document_type,
        "language": request.language,
        "section_title": request.section_title,
        "section_path": list(request.section_path),
        "content_kind": request.content_kind,
        "table_header": request.table_header,
        "document_outline": request.document_outline,
        "document_context": request.document_excerpt,
        "source_scope": request.source_scope,
        "chunk_text": request.chunk_text,
        "scope_metadata": dict(request.scope_metadata),
    }


def _context_excerpt(chunks: list[EvalChunk], index: int, limit: int) -> str:
    selected: list[str] = []
    distance = 1
    while len("\n\n".join(selected)) < limit and (
        index - distance >= 0 or index + distance < len(chunks)
    ):
        if index - distance >= 0:
            selected.insert(0, chunks[index - distance].text)
        if index + distance < len(chunks):
            selected.append(chunks[index + distance].text)
        distance += 1
    return "\n\n".join(selected)[:limit]


def _save_context_cache(
    cache_path: Path,
    *,
    model: str,
    cache: dict[str, dict[str, Any]],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(
            {"schema_version": 1, "model": model, "entries": cache},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    temp_path.replace(cache_path)


def enrich_current_context(
    corpus: list[EvalChunk],
    *,
    source: str,
    cache_path: Path,
    gold_config: dict[str, Any],
) -> tuple[list[EvalChunk], ContextEnrichmentStats]:
    if source == "base":
        return corpus, ContextEnrichmentStats(source="base", model=None)

    _load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is required for --current-context-source openai. "
            "Configure it in .env or the current PowerShell session."
        )
    model = os.getenv(
        "CONTEXTUAL_ENRICHMENT_MODEL",
        os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
    )
    config = OpenAIChunkContextEnricherConfig(
        model=model,
        document_context_char_limit=_env_int("CONTEXTUAL_ENRICHMENT_DOCUMENT_MAX_CHARS", 12000),
        max_context_chars=_env_int("CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_CHARS", 600),
        max_context_words=_env_int("CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_WORDS", 45),
        max_search_terms=0,
        max_output_tokens=_env_int("CONTEXTUAL_ENRICHMENT_MAX_OUTPUT_TOKENS", 400),
        max_retries=_env_int("CONTEXTUAL_ENRICHMENT_MAX_RETRIES", 2),
        retry_backoff_seconds=(_env_int("CONTEXTUAL_ENRICHMENT_RETRY_BACKOFF_MS", 500) / 1000),
        strict=_env_bool("CONTEXTUAL_ENRICHMENT_STRICT", False),
    )
    enricher = create_openai_chunk_context_enricher(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout_seconds=_env_int("OPENAI_TIMEOUT_SECONDS", 30),
        config=config,
    )
    cache: dict[str, dict[str, Any]] = {}
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        raw_cache = payload.get("entries", {}) if isinstance(payload, dict) else {}
        if isinstance(raw_cache, dict):
            cache = {
                str(key): dict(value) for key, value in raw_cache.items() if isinstance(value, dict)
            }

    by_document: dict[str, list[EvalChunk]] = {}
    for chunk in corpus:
        by_document.setdefault(chunk.document_title, []).append(chunk)
    for chunks in by_document.values():
        chunks.sort(key=lambda item: item.chunk_index)

    cache_hits = 0
    generated_count = 0
    not_needed_count = 0
    fallback_count = 0
    estimated_tokens = 0
    unsaved_results = 0
    enriched_chunks: list[EvalChunk] = []
    for document_title, chunks in by_document.items():
        full_document = "\n\n".join(chunk.text for chunk in chunks)
        use_whole_document = len(full_document) <= config.document_context_char_limit
        sections = list(
            dict.fromkeys(
                str(chunk.current_metadata.get("section_title") or "") for chunk in chunks
            )
        )
        outline = "" if use_whole_document else "\n".join(
            section for section in sections if section
        )[:4000]
        profile = gold_config["documents"][document_title]
        excerpt_limit = (
            config.document_context_char_limit
            if use_whole_document
            else max(1, config.document_context_char_limit - len(outline))
        )
        for index, chunk in enumerate(chunks):
            context = ChunkContext.from_metadata(chunk.current_metadata)
            request = ChunkContextEnrichmentRequest(
                document_title=document_title,
                document_type=context.document_type,
                language=str(chunk.current_metadata.get("language") or "") or None,
                section_title=context.section_title,
                section_path=context.section_path,
                content_kind=context.content_kind,
                table_header=context.table_header,
                document_outline=outline,
                document_excerpt=(
                    full_document
                    if use_whole_document
                    else _context_excerpt(chunks, index, excerpt_limit)
                ),
                chunk_text=chunk.text,
                scope_metadata=select_context_scope_metadata(chunk.current_metadata),
                source_scope=(
                    "whole_document" if use_whole_document else "bounded_context_package"
                ),
            )
            request_payload = _context_request_payload(request, model)
            serialized = json.dumps(
                request_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            cache_key = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            cached = cache.get(cache_key)
            if cached is not None and str(cached.get("status") or "generated") not in {
                "generated",
                "not_needed",
            }:
                cached = None
            if cached is not None:
                cache_hits += 1
                result_context = cached.get("context")
                result_status = str(cached.get("status") or "generated")
                result_needs_context = bool(cached.get("needs_context", True))
                result_quality_flags = cached.get("quality_flags", [])
                result_source_scope = str(cached.get("source_scope") or request.source_scope)
            else:
                result = enricher.enrich(request)
                result_context = result.context_text
                result_status = result.status
                result_needs_context = result.needs_context
                result_quality_flags = list(result.quality_flags)
                result_source_scope = result.source_scope
                if result_status in {"generated", "not_needed"}:
                    cache[cache_key] = {
                        "context": result_context,
                        "status": result_status,
                        "needs_context": result_needs_context,
                        "quality_flags": result_quality_flags,
                        "source_scope": result_source_scope,
                        "model": result.model,
                        "prompt_version": result.prompt_version,
                        "input_checksum": result.input_checksum,
                        "error_code": result.error_code,
                    }
                else:
                    cache.pop(cache_key, None)
                estimated_tokens += _estimate_tokens(serialized)
                unsaved_results += 1
                if unsaved_results >= 10:
                    _save_context_cache(cache_path, model=model, cache=cache)
                    unsaved_results = 0
            if result_status == "generated":
                generated_count += 1
            elif result_status == "not_needed":
                not_needed_count += 1
            else:
                fallback_count += 1

            current = dict(chunk.current_metadata)
            if result_status == "generated" and result_context:
                current["contextual_summary"] = str(result_context)
            elif result_status == "not_needed":
                current.pop("contextual_summary", None)
            current.pop("contextual_search_terms", None)
            current["context_enrichment"] = {
                "status": result_status,
                "needs_context": result_needs_context,
                "provider": "openai",
                "model": model,
                "cache_key": cache_key,
                "source_scope": result_source_scope,
                "quality_flags": result_quality_flags,
            }
            gold, annotated = _gold_metadata(
                current,
                profile,
                page=chunk.page_number,
                text=chunk.text,
            )
            enriched_chunks.append(
                replace(
                    chunk,
                    current_metadata=current,
                    gold_metadata=gold,
                    gold_annotated=annotated,
                )
            )

    _save_context_cache(cache_path, model=model, cache=cache)
    return enriched_chunks, ContextEnrichmentStats(
        source="openai",
        model=model,
        cache_hits=cache_hits,
        generated_count=generated_count,
        not_needed_count=not_needed_count,
        fallback_count=fallback_count,
        estimated_new_input_tokens=estimated_tokens,
    )


def _resolve_case(
    test: dict[str, Any],
    chunks: list[EvalChunk],
) -> tuple[list[str], str, float, list[str]]:
    expected = test["expected"]
    relevant_doc = expected["document_title"]
    document_chunks = [chunk for chunk in chunks if chunk.document_title == relevant_doc]
    expected_page = expected.get("page")
    tolerance = int(expected.get("page_tolerance") or 0)
    scoped = document_chunks
    if expected_page not in (None, ""):
        scoped = [
            chunk
            for chunk in document_chunks
            if chunk.page_number is not None
            and abs(chunk.page_number - int(expected_page)) <= tolerance
        ]
    terms = [str(term) for term in expected.get("must_include_terms", [])]
    exact = [chunk for chunk in scoped if all(_contains(chunk.text, term) for term in terms)]
    if exact:
        ids = [chunk.id for chunk in exact]
        return ids, "exact_chunk", 1.0, []

    uncovered = set(range(len(terms)))
    selected: list[EvalChunk] = []
    candidates = list(scoped)
    while uncovered and candidates:
        best = max(
            candidates,
            key=lambda chunk: sum(_contains(chunk.text, terms[index]) for index in uncovered),
        )
        covered = {index for index in uncovered if _contains(best.text, terms[index])}
        if not covered:
            break
        selected.append(best)
        uncovered -= covered
        candidates.remove(best)
    coverage = 1.0 if not terms else (len(terms) - len(uncovered)) / len(terms)
    missing_terms = [terms[index] for index in sorted(uncovered)]
    if not uncovered and selected:
        return [chunk.id for chunk in selected], "page_bundle", coverage, []
    return [chunk.id for chunk in selected], "unresolved", coverage, missing_terms


def resolve_ground_truth(
    tests: list[dict[str, Any]],
    chunks: list[EvalChunk],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    known_chunk_ids = {chunk.id for chunk in chunks}
    for test in tests:
        target_type = str(test.get("target_type") or "single")
        explicit_ids = [str(value) for value in test.get("relevant_chunk_ids", [])]
        relevant_groups = [
            [str(value) for value in group]
            for group in test.get("relevant_chunk_groups", [])
            if isinstance(group, list)
        ]
        protected_ids = [str(value) for value in test.get("protected_chunk_ids", [])]
        referenced_ids = {
            *explicit_ids,
            *protected_ids,
            *(chunk_id for group in relevant_groups for chunk_id in group),
        }
        missing_ids = sorted(referenced_ids - known_chunk_ids)
        if explicit_ids or target_type in {
            "null",
            "permission",
            "permission_allowed",
            "permission_denied",
            "multi_hop",
        }:
            ids = explicit_ids
            missing = missing_ids
            coverage = (
                1.0
                if not missing
                else (len(referenced_ids) - len(missing)) / max(1, len(referenced_ids))
            )
            if missing:
                status = "unresolved"
            elif target_type == "null":
                status = "negative_no_match"
            elif target_type in {"permission", "permission_denied"}:
                status = "protected_chunk"
            elif target_type == "multi_hop":
                status = "explicit_multi_hop"
            else:
                status = "explicit_chunk_ids"
        else:
            ids, status, coverage, missing = _resolve_case(test, chunks)
        updated = dict(test)
        updated["relevant_chunk_ids"] = ids
        updated["ground_truth_status"] = status
        resolved.append(updated)
        audit.append(
            {
                "test_id": test["id"],
                "source_file": test.get("source_file", ""),
                "primary_slice": test.get("primary_slice", test.get("category", "")),
                "target_type": target_type,
                "expected_page": test.get("expected", {}).get("page") or "",
                "status": status,
                "term_coverage": round(coverage, 6),
                "relevant_chunk_count": len(ids),
                "relevant_chunk_ids": " | ".join(ids),
                "relevant_group_count": len(relevant_groups),
                "protected_chunk_count": len(protected_ids),
                "missing_terms": " | ".join(missing),
            }
        )
    return resolved, audit


def _filter_metadata(metadata: dict[str, Any], mode: str) -> dict[str, Any]:
    level = ABLATION_LEVEL_BY_MODE.get(mode)
    if level is None:
        raise ValueError(f"Unsupported ablation mode: {mode}")
    if level == 0:
        return {}
    allowed = {"title", "document_type"}
    if level >= 2:
        allowed.update({"section_title", "section_path"})
    if level >= 3:
        allowed.update({"content_kind", "table_header", "figure_caption"})
    if level >= 4:
        allowed.add("contextual_summary")
    if level >= 5:
        allowed.update({"contextual_search_terms", "keyword_aliases"})
    if level >= 6:
        allowed.update(DOMAIN_METADATA_FIELDS)
    return {key: value for key, value in metadata.items() if key in allowed}


def _projection_line(label: str, value: object) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, list | tuple | set):
        text = " | ".join(str(item) for item in value if str(item).strip())
    else:
        text = str(value).strip()
    return f"{label}: {text}" if text else None


def _domain_projection_lines(metadata: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    fields = (
        ("Domain", "domain"),
        ("Policy field", "policy_field"),
        ("Clause type", "clause_type"),
        ("Fee type", "fee_type"),
        ("Deadline type", "deadline_type"),
        ("Year", "year"),
        ("Faculty", "faculty"),
        ("Department", "department"),
        ("Source", "source"),
        ("Source kind", "source_kind"),
        ("Document version", "document_version"),
        ("Effective status", "effective_status"),
        ("Lifecycle status", "lifecycle_status"),
        ("Published at", "published_at"),
        ("As-of date", "as_of_date"),
        ("Data period", "data_period"),
        ("Project", "project_name"),
        ("Project code", "project_code"),
        ("Project status", "project_status"),
        ("Region", "region"),
        ("Market type", "market_type"),
        ("Reliability grade", "reliability_grade"),
        ("Source code", "source_code"),
    )
    for label, field in fields:
        if field == "department" and metadata.get("department") == metadata.get("faculty"):
            continue
        if line := _projection_line(label, metadata.get(field)):
            lines.append(line)
    return lines


def _prepend_projection_lines(
    text: str,
    lines: list[str],
    *,
    separate_body: bool,
) -> str:
    if not lines:
        return text
    separator = "\n\n" if separate_body else "\n"
    prefix = "\n".join(lines)
    return f"{prefix}{separator}{text}"


def _domain_channel_policy(mode: str) -> dict[str, bool]:
    if mode in CONTEXT_QUALITY_MODES or _is_filter_ablation_mode(mode):
        return {"filter": True, "search_text": False, "embedding_text": False}
    if mode in {"no_metadata", "v0_raw_text"}:
        return {"filter": False, "search_text": False, "embedding_text": False}
    if not mode.startswith("v"):
        return {"filter": True, "search_text": True, "embedding_text": True}
    return {
        "filter": mode in DOMAIN_FILTER_MODES,
        "search_text": mode in DOMAIN_SEARCH_TEXT_MODES,
        "embedding_text": mode in DOMAIN_EMBEDDING_TEXT_MODES,
    }


def _project(chunk: EvalChunk, metadata: dict[str, Any], *, mode: str) -> Projection:
    if mode in {"no_metadata", "v0_raw_text"}:
        return Projection(
            chunk=chunk, retrieval_metadata={}, embedding_text=chunk.text, search_text=chunk.text
        )
    filtered = _filter_metadata(metadata, mode) if mode.startswith("v") else metadata
    context = ChunkContext.from_metadata(filtered)
    embedding_text = build_embedding_text(chunk.text, context)
    search_text = build_search_text(chunk.text, context)
    domain_lines = _domain_projection_lines(filtered)
    policy = _domain_channel_policy(mode)
    if policy["embedding_text"]:
        embedding_text = _prepend_projection_lines(
            embedding_text,
            domain_lines,
            separate_body=True,
        )
    if policy["search_text"]:
        search_text = _prepend_projection_lines(
            search_text,
            domain_lines,
            separate_body=False,
        )
    if figure_line := _projection_line("Figure caption", filtered.get("figure_caption")):
        embedding_text = _prepend_projection_lines(
            embedding_text,
            [figure_line],
            separate_body=True,
        )
        search_text = _prepend_projection_lines(
            search_text,
            [figure_line],
            separate_body=False,
        )
    return Projection(
        chunk=chunk,
        retrieval_metadata=filtered,
        embedding_text=embedding_text,
        search_text=search_text,
    )


def _shuffled_metadata(chunks: list[EvalChunk], seed: int) -> dict[str, dict[str, Any]]:
    rng = random.Random(seed)
    indexes = list(range(len(chunks)))
    if len(indexes) > 1:
        for _ in range(1000):
            rng.shuffle(indexes)
            if all(index != donor for index, donor in enumerate(indexes)):
                break
        else:
            indexes = indexes[1:] + indexes[:1]
    return {
        chunk.id: dict(chunks[donor].current_metadata)
        for chunk, donor in zip(chunks, indexes, strict=True)
    }


def _shuffled_context_summaries(chunks: list[EvalChunk], seed: int) -> dict[str, str | None]:
    """Derange only summaries, and never move context across document boundaries."""

    by_document: dict[str, list[EvalChunk]] = {}
    for chunk in chunks:
        by_document.setdefault(chunk.document_id, []).append(chunk)

    rng = random.Random(seed)
    output: dict[str, str | None] = {}
    for document_id in sorted(by_document):
        document_chunks = sorted(by_document[document_id], key=lambda item: item.chunk_index)
        indexes = list(range(len(document_chunks)))
        donors = list(indexes)
        if len(donors) > 1:
            for _ in range(1000):
                rng.shuffle(donors)
                if all(index != donor for index, donor in zip(indexes, donors, strict=True)):
                    break
            else:
                donors = donors[1:] + donors[:1]
        for chunk, donor in zip(document_chunks, donors, strict=True):
            value = document_chunks[donor].current_metadata.get("contextual_summary")
            output[chunk.id] = str(value).strip() if value not in (None, "") else None
    return output


def _context_header_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "title",
        "document_type",
        "section_title",
        "section_path",
        "content_kind",
        "table_header",
    )
    return {
        field: metadata[field]
        for field in fields
        if metadata.get(field) not in (None, "", [], {})
    }


def _context_quality_projection(
    chunk: EvalChunk,
    *,
    mode: str,
    shuffled_summaries: dict[str, str | None],
    retrieval_metadata: dict[str, Any],
) -> Projection:
    retrieval_metadata = dict(retrieval_metadata)
    if mode == "ctx_a_chunk_only":
        return Projection(
            chunk=chunk,
            retrieval_metadata=retrieval_metadata,
            embedding_text=chunk.text,
            search_text=chunk.text,
        )

    header_metadata = _context_header_metadata(chunk.current_metadata)
    if mode in {
        "ctx_c_raw_context",
        "ctx_c_raw_context_dense_only",
        "ctx_c_raw_context_sparse_only",
    }:
        summary = chunk.current_metadata.get("contextual_summary")
    elif mode == "ctx_d_effective_context":
        summary = chunk.gold_metadata.get("contextual_summary")
    elif mode == "ctx_e_shuffled_context":
        summary = shuffled_summaries.get(chunk.id)
    else:
        summary = None
    dense_metadata = dict(header_metadata)
    sparse_metadata = dict(header_metadata)
    if summary not in (None, "") and mode != "ctx_c_raw_context_sparse_only":
        dense_metadata["contextual_summary"] = str(summary)
    if summary not in (None, "") and mode != "ctx_c_raw_context_dense_only":
        sparse_metadata["contextual_summary"] = str(summary)

    dense_context = ChunkContext.from_metadata(dense_metadata)
    sparse_context = ChunkContext.from_metadata(sparse_metadata)
    return Projection(
        chunk=chunk,
        retrieval_metadata=retrieval_metadata,
        embedding_text=build_embedding_text(chunk.text, dense_context),
        search_text=build_search_text(chunk.text, sparse_context),
    )


def build_projections(
    chunks: list[EvalChunk],
    modes: list[str],
    *,
    seed: int,
    ablation_source: str,
) -> dict[str, list[Projection]]:
    shuffled = _shuffled_metadata(chunks, seed)
    shuffled_summaries = _shuffled_context_summaries(chunks, seed)
    output: dict[str, list[Projection]] = {}
    for mode in modes:
        rows: list[Projection] = []
        for chunk in chunks:
            if mode in CONTEXT_QUALITY_MODES or _is_filter_ablation_mode(mode):
                retrieval_metadata = (
                    chunk.gold_metadata if ablation_source == "gold" else chunk.current_metadata
                )
                rows.append(
                    _context_quality_projection(
                        chunk,
                        mode=mode,
                        shuffled_summaries=shuffled_summaries,
                        retrieval_metadata=retrieval_metadata,
                    )
                )
                continue
            if mode == "no_metadata":
                metadata: dict[str, Any] = {}
            elif mode == "current_metadata":
                metadata = chunk.current_metadata
            elif mode == "shuffled_metadata":
                metadata = shuffled[chunk.id]
            elif mode == "gold_metadata":
                metadata = chunk.gold_metadata
            elif mode in ABLATION_MODES:
                metadata = (
                    chunk.gold_metadata if ablation_source == "gold" else chunk.current_metadata
                )
            else:
                raise SystemExit(f"Unsupported mode: {mode}")
            rows.append(_project(chunk, metadata, mode=mode))
        output[mode] = rows
    return output


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * pct)
    return ordered[index]


def write_metadata_audit(
    path: Path,
    projections: dict[str, list[Projection]],
) -> None:
    rows: list[dict[str, Any]] = []
    for mode, items in projections.items():
        embedding_tokens = [_estimate_tokens(item.embedding_text) for item in items]
        search_tokens = [_estimate_tokens(item.search_text) for item in items]
        row: dict[str, Any] = {
            "mode": mode,
            "chunk_count": len(items),
            "gold_annotated_count": sum(item.chunk.gold_annotated for item in items),
            "avg_embedding_tokens": round(statistics.mean(embedding_tokens), 3),
            "p95_embedding_tokens": _percentile(embedding_tokens, 0.95),
            "avg_search_tokens": round(statistics.mean(search_tokens), 3),
            "p95_search_tokens": _percentile(search_tokens, 0.95),
        }
        for field in SEMANTIC_FIELDS:
            present = sum(
                item.retrieval_metadata.get(field) not in (None, "", [], {}) for item in items
            )
            row[f"{field}_coverage"] = round(present / len(items), 6) if items else 0.0
        rows.append(row)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _build_indexes(
    projections: dict[str, list[Projection]],
    text_vectors: dict[str, tuple[float, ...]],
    *,
    rrf_k: int,
    mmr_lambda: float,
) -> tuple[dict[str, ModeIndex], dict[str, float]]:
    indexes: dict[str, ModeIndex] = {}
    build_times: dict[str, float] = {}
    for mode, items in projections.items():
        started = time.perf_counter()
        sparse = InMemoryBM25RetrievalAdapter()
        evidence: dict[str, EvidenceChunk] = {}
        vectors: dict[str, tuple[float, ...]] = {}
        filterable_fields = frozenset(
            key
            for item in items
            for key in item.retrieval_metadata
            if key not in SECURITY_METADATA_FIELDS
        )
        for item in items:
            metadata = {
                **item.retrieval_metadata,
                "owner_id": item.chunk.owner_id,
                "notebook_id": item.chunk.notebook_id,
                "visibility": item.chunk.visibility,
                "allowed_groups": list(item.chunk.allowed_groups),
                "page_number": item.chunk.page_number,
            }
            evidence_chunk = EvidenceChunk(
                id=item.chunk.id,
                document_id=item.chunk.document_id,
                text=item.chunk.text,
                metadata=metadata,
                search_text=item.search_text,
            )
            sparse.index(evidence_chunk)
            evidence[item.chunk.id] = evidence_chunk
            vectors[item.chunk.id] = text_vectors[item.embedding_text]
        indexes[mode] = ModeIndex(
            sparse=sparse,
            dense=DenseIndex(chunks=evidence, vectors=vectors),
            fusion=ReciprocalRankFusion(rank_constant=rrf_k),
            reranker=MaximalMarginalRelevanceReranker(lambda_param=mmr_lambda),
            corpus_size=len(items),
            filterable_fields=filterable_fields,
        )
        build_times[mode] = round((time.perf_counter() - started) * 1000, 3)
    return indexes, build_times


def run_queries(
    *,
    tests: list[dict[str, Any]],
    indexes: dict[str, ModeIndex],
    query_vectors: dict[str, tuple[float, ...]],
    chunks_by_id: dict[str, EvalChunk],
    repeats: int,
    candidate_k: int,
    top_k: int,
    embedding_provider: str,
) -> list[dict[str, Any]]:
    def query_scope(
        test: dict[str, Any],
    ) -> tuple[
        RetrievalFilters,
        tuple[dict[str, Any], ...],
        tuple[str, ...],
        str,
    ]:
        context = test.get("query_context")
        context = context if isinstance(context, dict) else {}
        document_ids: tuple[str, ...] | None = None
        if "document_ids" in context:
            document_ids = tuple(str(value) for value in context.get("document_ids") or [])
        filters = RetrievalFilters(
            owner_id=str(context.get("owner_id") or "eval-owner"),
            notebook_id=str(context.get("notebook_id") or "eval-notebook"),
            document_ids=document_ids,
        )
        retrieval_filters = test.get("retrieval_filters")
        retrieval_filters = retrieval_filters if isinstance(retrieval_filters, dict) else {}
        conditions = tuple(
            dict(value)
            for value in retrieval_filters.get("metadata_conditions", [])
            if isinstance(value, dict)
        )
        groups = tuple(str(value) for value in context.get("groups", []))
        unsupported_policy = str(
            retrieval_filters.get("unsupported_field_policy") or "skip"
        ).strip()
        if unsupported_policy not in {"skip", "fail_closed", "error"}:
            raise ValueError(f"Unsupported field policy: {unsupported_policy}")
        return filters, conditions, groups, unsupported_policy

    def conditions_for_mode(
        mode: str,
        conditions: tuple[dict[str, Any], ...],
    ) -> tuple[tuple[dict[str, Any], ...], list[str]]:
        dropped = _filter_fields_dropped_by_mode(mode)
        if not dropped:
            return conditions, []
        kept = tuple(
            condition
            for condition in conditions
            if str(condition.get("field") or "") not in dropped
        )
        removed = [
            str(condition.get("field") or "")
            for condition in conditions
            if str(condition.get("field") or "") in dropped
        ]
        return kept, removed

    rows: list[dict[str, Any]] = []
    first_test = tests[0] if tests else None
    if first_test is not None:
        first_query = first_test["query"]
        filters, original_conditions, groups, unsupported_policy = query_scope(first_test)
        for mode, index in indexes.items():
            conditions, _ = conditions_for_mode(mode, original_conditions)
            requested_fields = [str(value.get("field") or "") for value in conditions]
            skipped_fields = [
                field for field in requested_fields if field not in index.filterable_fields
            ]
            if skipped_fields and unsupported_policy in {"fail_closed", "error"}:
                continue
            index.search(
                first_query,
                query_vectors[first_query],
                candidate_k=candidate_k,
                top_k=top_k,
                filters=filters,
                metadata_conditions=conditions,
                user_groups=groups,
            )
    for mode, index in indexes.items():
        for test in tests:
            query = test["query"]
            filters, original_conditions, groups, unsupported_policy = query_scope(test)
            conditions, removed_fields = conditions_for_mode(mode, original_conditions)
            requested_fields = [str(value.get("field") or "") for value in conditions]
            applied_fields = [
                field for field in requested_fields if field in index.filterable_fields
            ]
            skipped_fields = [
                field for field in requested_fields if field not in index.filterable_fields
            ]
            preflight_pass = not skipped_fields
            if skipped_fields and unsupported_policy == "error":
                raise ValueError(
                    f"{test['id']} requests unsupported metadata fields in mode {mode}: "
                    f"{', '.join(skipped_fields)}"
                )
            latencies: list[float] = []
            results: tuple[RetrievalCandidate, ...] = ()
            if skipped_fields and unsupported_policy == "fail_closed":
                latencies = [0.0] * repeats
            else:
                for _ in range(repeats):
                    started = time.perf_counter()
                    results = index.search(
                        query,
                        query_vectors[query],
                        candidate_k=candidate_k,
                        top_k=top_k,
                        filters=filters,
                        metadata_conditions=conditions,
                        user_groups=groups,
                    )
                    latencies.append((time.perf_counter() - started) * 1000)
            output_results: list[dict[str, Any]] = []
            for rank, candidate in enumerate(results, start=1):
                source = chunks_by_id[candidate.chunk.id]
                output_results.append(
                    {
                        "rank": rank,
                        "chunk_id": source.id,
                        "document_id": source.document_id,
                        "document_title": source.document_title,
                        "page_number": source.page_number,
                        "section_title": candidate.chunk.typed_metadata.section_title,
                        "excerpt": source.text,
                        "retrieval_metadata": {
                            key: value
                            for key, value in candidate.chunk.metadata.items()
                            if key not in SECURITY_METADATA_FIELDS
                        },
                        "table_id": source.table_identity,
                        "table_location": source.table_location,
                        "source_block_ids": list(source.source_block_ids),
                        "bbox": list(source.bbox),
                        "retrieval_score": round(candidate.score, 10),
                    }
                )
            rows.append(
                {
                    "test_id": test["id"],
                    "query_id": test["query_id"],
                    "mode": mode,
                    "embedding_provider": embedding_provider,
                    "original_metadata_filter_fields": [
                        str(value.get("field") or "") for value in original_conditions
                    ],
                    "removed_metadata_filter_fields": removed_fields,
                    "applied_metadata_filter_fields": applied_fields,
                    "skipped_metadata_filter_fields": skipped_fields,
                    "unsupported_field_policy": unsupported_policy,
                    "filter_preflight_pass": preflight_pass,
                    "filter_preflight_status": (
                        "passed"
                        if preflight_pass
                        else (
                            "failed_closed"
                            if unsupported_policy == "fail_closed"
                            else "skipped_unsupported"
                        )
                    ),
                    "latency_ms": round(statistics.median(latencies), 3),
                    "latency_samples_ms": [round(value, 3) for value in latencies],
                    "results": output_results,
                }
            )
    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=Path.home() / "Downloads")
    parser.add_argument(
        "--corpus-fixture",
        type=Path,
        default=None,
        help="Optional JSONL corpus fixture; skips parsing files from --source-dir.",
    )
    parser.add_argument(
        "--corpus-fixture-kind",
        choices=("controlled_synthetic", "real_document_snapshot"),
        default="controlled_synthetic",
        help="Provenance label for --corpus-fixture; does not change retrieval behavior.",
    )
    parser.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    parser.add_argument("--gold-metadata", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--embedding-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--context-cache", type=Path, default=DEFAULT_CONTEXT_CACHE)
    parser.add_argument("--embedding-provider", choices=("hashing", "openai"), default="hashing")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument(
        "--current-context-source",
        choices=("base", "openai"),
        default="base",
        help="Use base structural metadata or run the production OpenAI chunk enricher.",
    )
    parser.add_argument("--chunk-size", type=int, default=600)
    parser.add_argument("--chunk-overlap", type=int, default=80)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--mmr-lambda", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES))
    parser.add_argument("--include-ablation", action="store_true")
    parser.add_argument("--ablation-source", choices=("current", "gold"), default="gold")
    parser.add_argument(
        "--production-metadata-only",
        action="store_true",
        help=(
            "Build current_metadata only from parser, chunker, and production normalization; "
            "gold/profile metadata remains available solely as the audit reference."
        ),
    )
    parser.add_argument("--allow-unresolved-ground-truth", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.repeats <= 0 or args.top_k <= 0 or args.candidate_k < args.top_k:
        raise SystemExit("Require repeats > 0, top-k > 0, and candidate-k >= top-k")
    if not 0 <= args.mmr_lambda <= 1:
        raise SystemExit("--mmr-lambda must be between 0 and 1")
    modes = [value.strip() for value in args.modes.split(",") if value.strip()]
    if args.include_ablation:
        modes.extend(mode for mode in ABLATION_MODES if mode not in modes)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    tests = _load_jsonl(args.testset)
    if args.corpus_fixture is not None:
        if args.current_context_source != "base":
            raise SystemExit(
                "--current-context-source openai is not supported with --corpus-fixture; "
                "the controlled fixture already contains deterministic context metadata."
            )
        corpus, source_snapshots = load_fixture_corpus(args.corpus_fixture)
        context_stats = ContextEnrichmentStats(source="fixture", model=None)
        gold_config: dict[str, Any] = {}
    else:
        gold_config = json.loads(args.gold_metadata.read_text(encoding="utf-8"))
        corpus, source_snapshots = build_corpus(
            source_dir=args.source_dir,
            gold_config=gold_config,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            production_metadata_only=args.production_metadata_only,
        )
        corpus, context_stats = enrich_current_context(
            corpus,
            source=args.current_context_source,
            cache_path=args.context_cache,
            gold_config=gold_config,
        )
    resolved_tests, ground_truth_audit = resolve_ground_truth(tests, corpus)
    unresolved = [row for row in ground_truth_audit if row["status"] == "unresolved"]

    corpus_rows = [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": chunk.document_title,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "text": chunk.text,
            "current_metadata": chunk.current_metadata,
            "gold_metadata": chunk.gold_metadata,
            "gold_annotated": chunk.gold_annotated,
            "security": {
                "owner_id": chunk.owner_id,
                "notebook_id": chunk.notebook_id,
                "visibility": chunk.visibility,
                "allowed_groups": list(chunk.allowed_groups),
            },
            "provenance": {
                "source_block_ids": list(chunk.source_block_ids),
                "table_identity": chunk.table_identity,
                "table_location": chunk.table_location,
                "bbox": list(chunk.bbox),
            },
        }
        for chunk in corpus
    ]
    _write_jsonl(args.output_dir / "corpus.jsonl", corpus_rows)
    _write_jsonl(args.output_dir / "testset.resolved.jsonl", resolved_tests)
    with (args.output_dir / "ground_truth_audit.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ground_truth_audit[0].keys()))
        writer.writeheader()
        writer.writerows(ground_truth_audit)

    if unresolved and not args.allow_unresolved_ground_truth:
        missing_ids = ", ".join(row["test_id"] for row in unresolved)
        raise SystemExit(
            f"Ground-truth audit found {len(unresolved)} unresolved case(s): {missing_ids}. "
            f"Inspect {args.output_dir / 'ground_truth_audit.csv'} before running retrieval."
        )

    projections = build_projections(
        corpus,
        modes,
        seed=args.seed,
        ablation_source=args.ablation_source,
    )
    write_metadata_audit(args.output_dir / "metadata_audit.csv", projections)

    embedder = CachedEmbedder(
        provider=args.embedding_provider,
        model=args.embedding_model,
        cache_path=args.embedding_cache,
    )
    projection_texts = [item.embedding_text for items in projections.values() for item in items]
    query_texts = [test["query"] for test in resolved_tests]
    vectors = embedder.embed_many([*projection_texts, *query_texts])
    indexes, index_build_ms = _build_indexes(
        projections,
        vectors,
        rrf_k=args.rrf_k,
        mmr_lambda=args.mmr_lambda,
    )
    results = run_queries(
        tests=resolved_tests,
        indexes=indexes,
        query_vectors={query: vectors[query] for query in query_texts},
        chunks_by_id={chunk.id: chunk for chunk in corpus},
        repeats=args.repeats,
        candidate_k=args.candidate_k,
        top_k=args.top_k,
        embedding_provider=args.embedding_provider,
    )
    results_path = args.output_dir / "retrieval_results.jsonl"
    _write_jsonl(results_path, results)

    snapshot = {
        "schema_version": "1.0",
        "created_at_epoch": time.time(),
        "source_documents": source_snapshots,
        "testset_path": str(args.testset.resolve()),
        "testset_sha256": _sha256_file(args.testset),
        "gold_metadata_path": (
            "" if args.corpus_fixture is not None else str(args.gold_metadata.resolve())
        ),
        "gold_metadata_sha256": (
            "" if args.corpus_fixture is not None else _sha256_file(args.gold_metadata)
        ),
        "corpus_fixture_path": (
            "" if args.corpus_fixture is None else str(args.corpus_fixture.resolve())
        ),
        "corpus_fixture_sha256": (
            "" if args.corpus_fixture is None else _sha256_file(args.corpus_fixture)
        ),
        "chunking": {
            "strategy": "jsonl_fixture"
            if args.corpus_fixture is not None
            else "structure_recursive",
            "chunk_size": args.chunk_size,
            "chunk_overlap": args.chunk_overlap,
        },
        "retrieval": {
            "method": "in_memory_bm25_plus_dense_rrf_mmr",
            "candidate_k": args.candidate_k,
            "top_k": args.top_k,
            "rrf_k": args.rrf_k,
            "mmr_lambda": args.mmr_lambda,
            "repeats": args.repeats,
        },
    }
    _write_json(args.output_dir / "frozen_snapshot.json", snapshot)
    manifest = {
        "schema_version": "1.0",
        "status": "completed",
        "embedding_provider": args.embedding_provider,
        "embedding_model": embedder.model,
        "current_context_source": context_stats.source,
        "context_enrichment_model": context_stats.model,
        "context_enrichment_prompt_version": (
            CONTEXT_ENRICHMENT_PROMPT_VERSION if context_stats.source == "openai" else None
        ),
        "contextual_text_version": CONTEXTUAL_TEXT_VERSION,
        "context_enrichment_max_context_words": _env_int(
            "CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_WORDS", 45
        ),
        "context_enrichment_cache_hits": context_stats.cache_hits,
        "context_enrichment_generated_count": context_stats.generated_count,
        "context_enrichment_not_needed_count": context_stats.not_needed_count,
        "context_enrichment_fallback_count": context_stats.fallback_count,
        "estimated_new_context_input_tokens": context_stats.estimated_new_input_tokens,
        "benchmark_kind": (
            args.corpus_fixture_kind
            if args.corpus_fixture is not None
            else str(gold_config.get("benchmark_kind") or "real_document_pilot")
        ),
        "production_comparable": (
            args.embedding_provider == "openai"
            and (
                (
                    args.corpus_fixture is not None
                    and args.corpus_fixture_kind == "real_document_snapshot"
                )
                or (args.corpus_fixture is None and context_stats.source == "openai")
            )
        ),
        "production_comparability_note": (
            (
                "Frozen real-document corpus snapshot with OpenAI dense embeddings and "
                "deterministic header projection; local BM25/RRF/MMR is production-like, "
                "but PostgreSQL FTS tokenization may still differ."
                if args.corpus_fixture_kind == "real_document_snapshot"
                else "Controlled synthetic stress benchmark; combine it with real-query "
                "evaluation before production sign-off."
            )
            if args.corpus_fixture is not None
            else (
                "OpenAI contextual enrichment and dense embeddings with local BM25/RRF/MMR; "
                "PostgreSQL FTS tokenization may still differ."
                if args.embedding_provider == "openai" and context_stats.source == "openai"
                else (
                    "This run is a structural/proxy check. Final production conclusions require "
                    "both --current-context-source openai and --embedding-provider openai."
                )
            )
        ),
        "modes": modes,
        "domain_metadata_channel_policy_by_mode": {
            mode: _domain_channel_policy(mode) for mode in modes
        },
        "ablation_metadata_source": args.ablation_source,
        "production_metadata_only": args.production_metadata_only,
        "seed": args.seed,
        "query_count": len(resolved_tests),
        "chunk_count": len(corpus),
        "gold_annotated_chunk_count": sum(chunk.gold_annotated for chunk in corpus),
        "ground_truth_unresolved_count": len(unresolved),
        "result_row_count": len(results),
        "embedding_cache_hits": embedder.cache_hits,
        "new_embedding_count": embedder.cache_misses,
        "estimated_new_embedding_input_tokens": embedder.estimated_input_tokens,
        "index_build_ms_by_mode": index_build_ms,
        "outputs": {
            "corpus": "corpus.jsonl",
            "resolved_testset": "testset.resolved.jsonl",
            "ground_truth_audit": "ground_truth_audit.csv",
            "metadata_audit": "metadata_audit.csv",
            "retrieval_results": "retrieval_results.jsonl",
            "frozen_snapshot": "frozen_snapshot.json",
        },
    }
    _write_json(args.output_dir / "run_manifest.json", manifest)
    print(
        f"Completed {len(modes)} mode(s), {len(resolved_tests)} queries, "
        f"{len(corpus)} chunks -> {results_path}"
    )
    print(
        f"Ground truth unresolved={len(unresolved)}; "
        f"new embeddings={embedder.cache_misses}; cache hits={embedder.cache_hits}"
    )
    if args.embedding_provider == "hashing":
        print(
            "NOTE: hashing is a smoke-test proxy. "
            "Use --embedding-provider openai for final numbers."
        )


if __name__ == "__main__":
    main()
