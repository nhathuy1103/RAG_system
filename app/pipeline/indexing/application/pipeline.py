from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from app.infrastructure.telemetry import Telemetry
from app.knowledge_quality.application.analysis import build_chunk_fingerprint
from app.pipeline.documents.application.extraction_pipeline import (
    AdvancedExtractionPipeline,
    ensure_index_allowed,
    sanitize_parsed_document,
)
from app.pipeline.documents.application.validation import (
    DocumentValidationConfig,
    validate_document_source,
)
from app.pipeline.documents.domain.parsed import ParsedDocument
from app.pipeline.documents.domain.source import DocumentSource
from app.pipeline.documents.ports.parser import ParserCatalog
from app.pipeline.indexing.application.chunker import ChunkData, Chunker
from app.pipeline.indexing.domain.context_enrichment import (
    ChunkContextEnrichmentRequest,
    ContextSourceScope,
    select_context_scope_metadata,
)
from app.pipeline.indexing.domain.document_metadata import (
    DOCUMENT_METADATA_FIELDS,
    DocumentMetadataAssertion,
    DocumentMetadataEnrichmentRequest,
    MetadataEvidenceBlock,
)
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.pipeline.indexing.domain.retrieval_metadata import (
    normalize_chunk_retrieval_metadata,
)
from app.pipeline.indexing.ports.context_enricher import ChunkContextEnricher
from app.pipeline.indexing.ports.document_metadata_enricher import DocumentMetadataEnricher
from app.pipeline.indexing.ports.embedding_provider import EmbeddingProvider
from app.pipeline.indexing.ports.vector_index import (
    GenerationAwareVectorIndex,
    VectorIndex,
)
from app.pipeline.shared.text_utils import compute_checksum_text, normalize_text
from app.shared.contextual_text import (
    CONTEXTUAL_TEXT_VERSION,
    ChunkContext,
    build_embedding_text,
    build_search_text,
)


class IngestionEmbeddingStage(StrEnum):
    VALIDATING = "validating"
    PARSING = "parsing"
    SANITIZING = "sanitizing"
    METADATA_ENRICHMENT = "metadata_enrichment"
    CHUNKING = "chunking"
    CONTEXTUALIZING = "contextualizing"
    EMBEDDING = "embedding"
    EMBEDDED = "embedded"


@dataclass(frozen=True)
class IngestionEmbeddingResult:
    source: DocumentSource
    parsed_document: ParsedDocument
    chunks: tuple[ChunkData, ...]
    embedded_chunks: tuple[EmbeddedChunk, ...]
    stages: tuple[IngestionEmbeddingStage, ...]
    parser_name: str
    parser_version: str
    embedding_model: str
    extraction_artifacts: object | None = None
    document_metadata_assertions: tuple[DocumentMetadataAssertion, ...] = ()
    document_metadata_profile: Mapping[str, object] | None = None


@dataclass(frozen=True)
class PreparedIngestion:
    """A parsed and chunked document that has not incurred embedding cost yet."""

    source: DocumentSource
    parsed_document: ParsedDocument
    chunks: tuple[ChunkData, ...]
    stages: tuple[IngestionEmbeddingStage, ...]
    parser_name: str
    parser_version: str
    extraction_artifacts: object | None = None
    document_metadata_assertions: tuple[DocumentMetadataAssertion, ...] = ()
    document_metadata_profile: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ChunkEmbeddingPlan:
    """Optional exact-vector reuse instructions keyed by stable chunk index."""

    precomputed_vectors: Mapping[int, Sequence[float]] = field(default_factory=dict)
    reuse_from_chunk_index: Mapping[int, int] = field(default_factory=dict)
    metadata_by_chunk_index: Mapping[int, Mapping[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestionEmbeddingPipelineConfig:
    validation: DocumentValidationConfig = field(default_factory=DocumentValidationConfig)
    replace_existing_document_version: bool = True


class IngestionEmbeddingPipeline:
    """Use case that preserves the ingest -> parse -> chunk -> embed flow."""

    def __init__(
        self,
        *,
        parser_catalog: ParserCatalog,
        chunker: Chunker,
        embedding_provider: EmbeddingProvider,
        vector_index: VectorIndex | None = None,
        config: IngestionEmbeddingPipelineConfig | None = None,
        extraction_pipeline: AdvancedExtractionPipeline | None = None,
        context_enricher: ChunkContextEnricher | None = None,
        document_metadata_enricher: DocumentMetadataEnricher | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self.parser_catalog = parser_catalog
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.vector_index = vector_index
        self.config = config or IngestionEmbeddingPipelineConfig()
        self.extraction_pipeline = extraction_pipeline
        self.context_enricher = context_enricher
        self.document_metadata_enricher = document_metadata_enricher
        self.telemetry = telemetry or Telemetry()

    def run(self, source: DocumentSource) -> IngestionEmbeddingResult:
        with self.telemetry.observe(
            "rag.ingestion.pipeline",
            as_type="chain",
            input={
                "document_id": source.document_id,
                "document_version": source.version,
                "filename": self.telemetry.content(source.title),
                "mime_type": source.mime_type,
                "size_bytes": len(source.content),
            },
            metadata={
                "document_id": source.document_id,
                "tenant_id": source.tenant_id,
                "document_version": source.version,
            },
            user_id=source.owner_id,
            session_id=source.tenant_id,
            tags=("rag", "ingestion"),
            trace_name="rag-ingestion",
        ) as observation:
            result = self._run(source)
            observation.update(
                output={
                    "parser": result.parser_name,
                    "chunk_count": len(result.chunks),
                    "embedding_model": result.embedding_model,
                    "embedding_dimensions": (
                        result.embedded_chunks[0].vector_size if result.embedded_chunks else 0
                    ),
                    "indexed": self.vector_index is not None,
                }
            )
            return result

    def _run(self, source: DocumentSource) -> IngestionEmbeddingResult:
        prepared = self.prepare(source)
        return self.embed(prepared, persist_vectors=True)

    @property
    def context_enrichment_profile(self) -> dict[str, object] | None:
        if self.context_enricher is None:
            return None
        return {
            **self.context_enricher.profile,
            "contextual_text_version": CONTEXTUAL_TEXT_VERSION,
        }

    @property
    def document_metadata_enrichment_profile(self) -> dict[str, object] | None:
        if self.document_metadata_enricher is None:
            return None
        profile = self.document_metadata_enricher.profile
        return {
            "document_metadata_enrichment_model": profile["model"],
            "document_metadata_enrichment_prompt_version": profile["prompt_version"],
            "document_metadata_enrichment_max_chars": profile["max_document_chars"],
            "document_metadata_enrichment_max_output_tokens": profile["max_output_tokens"],
            "document_metadata_enrichment_strict": profile["strict"],
            "document_metadata_enrichment_verification_policy": profile[
                "verification_policy"
            ],
        }

    def prepare(
        self,
        source: DocumentSource,
        *,
        contextualize: bool = True,
        metadata_enrich: bool | None = None,
    ) -> PreparedIngestion:
        """Validate, extract, sanitize, and chunk without embedding or indexing."""
        stages: list[IngestionEmbeddingStage] = []

        with self.telemetry.observe(
            "ingestion.validate",
            as_type="guardrail",
            input={"mime_type": source.mime_type, "size_bytes": len(source.content)},
        ) as observation:
            self._advance(stages, IngestionEmbeddingStage.VALIDATING)
            validate_document_source(source, self.config.validation)
            observation.update(output={"valid": True})

        extraction_artifacts = None
        if self.extraction_pipeline is not None:
            with self.telemetry.observe(
                "ingestion.advanced_extraction",
                as_type="chain",
                metadata={"advanced_extraction": True},
            ) as observation:
                self._advance(stages, IngestionEmbeddingStage.PARSING)
                extraction_artifacts = self.extraction_pipeline.run(
                    source,
                    parser_catalog=self.parser_catalog,
                )
                ensure_index_allowed(extraction_artifacts)
                parsed = extraction_artifacts.parsed_document
                self._advance(stages, IngestionEmbeddingStage.SANITIZING)
                observation.update(
                    output={
                        "parser": parsed.parser_name,
                        "parser_version": parsed.parser_version,
                        "page_count": len(parsed.pages),
                        "element_count": sum(len(page.elements) for page in parsed.pages),
                        "index_allowed": True,
                    }
                )
        else:
            with self.telemetry.observe(
                "ingestion.parse_and_sanitize",
                as_type="chain",
                metadata={"advanced_extraction": False},
            ) as observation:
                parser = self.parser_catalog.get_parser(source.title)
                parser.validate(source.content)

                self._advance(stages, IngestionEmbeddingStage.PARSING)
                parsed = parser.parse(source.content)

                self._advance(stages, IngestionEmbeddingStage.SANITIZING)
                parsed = sanitize_parsed_document(parsed)
                observation.update(
                    output={
                        "parser": parsed.parser_name,
                        "parser_version": parsed.parser_version,
                        "page_count": len(parsed.pages),
                        "element_count": sum(len(page.elements) for page in parsed.pages),
                    }
                )

        # Apply the same authoritative source layer to both the advanced and
        # fallback extraction paths before metadata enrichment and chunking.
        parsed.document_metadata.update(
            {
                **source.metadata,
                "document_id": source.document_id,
                "document_version": source.version,
                "title": source.title,
                "source_title": source.title,
                "tenant_id": source.tenant_id,
                "owner_id": source.owner_id,
            }
        )
        parsed.logical_document = None
        parsed.logical_document = parsed.to_logical_document()

        document_metadata_assertions: tuple[DocumentMetadataAssertion, ...] = ()
        document_metadata_profile: Mapping[str, object] | None = None
        metadata_enricher = self.document_metadata_enricher
        should_enrich_metadata = (
            metadata_enricher is not None
            if metadata_enrich is None
            else metadata_enrich
        )
        if should_enrich_metadata and metadata_enricher is None:
            raise RuntimeError(
                "Document metadata enrichment is enabled but no LLM enricher is configured"
            )
        if should_enrich_metadata:
            assert metadata_enricher is not None
            with self.telemetry.observe(
                "ingestion.enrich_document_metadata",
                as_type="chain",
                input={"document_id": source.document_id},
            ) as observation:
                self._advance(stages, IngestionEmbeddingStage.METADATA_ENRICHMENT)
                document_metadata_assertions = self._enrich_document_metadata(source, parsed)
                document_metadata_profile = dict(metadata_enricher.profile)
                observation.update(
                    output={
                        "assertion_count": len(document_metadata_assertions),
                        "fields": [item.field_name for item in document_metadata_assertions],
                        "verified_count": sum(
                            1 for item in document_metadata_assertions if item.verified
                        ),
                    }
                )

        with self.telemetry.observe(
            "ingestion.chunk",
            as_type="chain",
        ) as observation:
            self._advance(stages, IngestionEmbeddingStage.CHUNKING)
            chunks = tuple(
                self.chunker.chunk(
                    source.document_id,
                    source.version,
                    parsed,
                )
            )
            observation.update(
                output={
                    "chunk_count": len(chunks),
                    "total_characters": sum(len(chunk.text) for chunk in chunks),
                }
            )

        prepared = PreparedIngestion(
            source=source,
            parsed_document=parsed,
            chunks=chunks,
            stages=tuple(stages),
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            extraction_artifacts=extraction_artifacts,
            document_metadata_assertions=document_metadata_assertions,
            document_metadata_profile=document_metadata_profile,
        )
        return self.contextualize(prepared) if contextualize else prepared

    def contextualize(
        self,
        prepared: PreparedIngestion,
        *,
        enabled: bool | None = None,
    ) -> PreparedIngestion:
        """Generate per-chunk context after identity checks and before chunk dedup."""
        already_contextualized = IngestionEmbeddingStage.CONTEXTUALIZING in prepared.stages
        if already_contextualized:
            return prepared
        should_contextualize = self.context_enricher is not None if enabled is None else enabled
        if not should_contextualize:
            return prepared
        if self.context_enricher is None:
            raise RuntimeError("Contextual enrichment is enabled but no LLM enricher is configured")

        stages = list(prepared.stages)
        with self.telemetry.observe(
            "ingestion.contextualize_chunks",
            as_type="chain",
            input={"chunk_count": len(prepared.chunks)},
        ) as observation:
            self._advance(stages, IngestionEmbeddingStage.CONTEXTUALIZING)
            chunks = self._contextualize_chunks(
                prepared.source,
                prepared.parsed_document,
                prepared.chunks,
            )
            generated_count = sum(
                1 for chunk in chunks if _context_enrichment_status(chunk.metadata) == "generated"
            )
            not_needed_count = sum(
                1 for chunk in chunks if _context_enrichment_status(chunk.metadata) == "not_needed"
            )
            fallback_count = sum(
                1 for chunk in chunks if _context_enrichment_status(chunk.metadata) == "fallback"
            )
            observation.update(
                output={
                    "chunk_count": len(chunks),
                    "generated_count": generated_count,
                    "not_needed_count": not_needed_count,
                    "fallback_count": fallback_count,
                }
            )
        return replace(prepared, chunks=chunks, stages=tuple(stages))

    def _contextualize_chunks(
        self,
        source: DocumentSource,
        parsed: ParsedDocument,
        chunks: tuple[ChunkData, ...],
    ) -> tuple[ChunkData, ...]:
        enricher = self.context_enricher
        if enricher is None:
            return chunks

        context_limit = enricher.document_context_char_limit
        document_text = parsed.to_logical_document().text or parsed.text
        use_whole_document = len(document_text) <= context_limit
        outline_limit = 0 if use_whole_document else max(1, min(4000, context_limit // 4))
        outline = "" if use_whole_document else _build_document_outline(chunks, outline_limit)
        excerpt_limit = (
            context_limit if use_whole_document else max(1, context_limit - len(outline))
        )
        enriched_chunks: list[ChunkData] = []
        for chunk_position, chunk in enumerate(chunks):
            metadata = dict(chunk.metadata)
            base_context = ChunkContext.from_metadata(metadata)
            source_scope: ContextSourceScope = (
                "whole_document" if use_whole_document else "bounded_context_package"
            )
            document_context = (
                document_text.strip()
                if use_whole_document
                else _build_bounded_context_package(
                    document_text,
                    chunks,
                    chunk_position,
                    excerpt_limit,
                )
            )
            result = enricher.enrich(
                ChunkContextEnrichmentRequest(
                    document_title=base_context.title or source.title,
                    document_type=_known_value(base_context.document_type),
                    language=_known_value(
                        str(metadata.get("language") or parsed.detected_language or "")
                    ),
                    section_title=base_context.section_title,
                    section_path=base_context.section_path,
                    content_kind=_known_value(base_context.content_kind),
                    table_header=base_context.table_header,
                    document_outline=outline,
                    document_excerpt=document_context,
                    chunk_text=chunk.text,
                    scope_metadata=select_context_scope_metadata(
                        {**metadata, "document_version": source.version}
                    ),
                    source_scope=source_scope,
                )
            )
            if result.status == "generated":
                contextual_summary = result.context_text
            elif result.status == "not_needed":
                contextual_summary = None
            else:
                contextual_summary = base_context.contextual_summary
            enriched_context = replace(
                base_context,
                contextual_summary=contextual_summary,
                contextual_search_terms=(),
            )
            retrieval_metadata = metadata.get("retrieval_metadata")
            retrieval_values = (
                dict(retrieval_metadata) if isinstance(retrieval_metadata, Mapping) else {}
            )
            retrieval_values.pop("contextual_summary", None)
            retrieval_values.pop("contextual_search_terms", None)
            retrieval_values.update(enriched_context.as_retrieval_metadata())
            metadata["retrieval_metadata"] = retrieval_values
            metadata.pop("contextual_summary", None)
            metadata.pop("contextual_search_terms", None)
            metadata["contextual_text_version"] = CONTEXTUAL_TEXT_VERSION
            enrichment_metadata: dict[str, object] = {
                "status": result.status,
                "needs_context": result.needs_context,
                "provider": result.provider,
                "model": result.model,
                "prompt_version": result.prompt_version,
                "input_checksum": result.input_checksum,
                "source_scope": result.source_scope,
                "output_word_count": len((result.context_text or "").split()),
            }
            if result.quality_flags:
                enrichment_metadata["quality_flags"] = list(result.quality_flags)
            if result.error_code:
                enrichment_metadata["error_code"] = result.error_code
            metadata["context_enrichment"] = enrichment_metadata

            embedding_text = build_embedding_text(chunk.text, enriched_context)
            search_text = build_search_text(chunk.text, enriched_context)
            metadata["embedding_text"] = embedding_text
            metadata["search_text"] = search_text
            metadata["search_text_checksum"] = compute_checksum_text(search_text)
            enriched_chunks.append(
                replace(
                    chunk,
                    embedding_text=embedding_text,
                    search_text=search_text,
                    metadata=metadata,
                )
            )
        return tuple(enriched_chunks)

    def _enrich_document_metadata(
        self,
        source: DocumentSource,
        parsed: ParsedDocument,
    ) -> tuple[DocumentMetadataAssertion, ...]:
        enricher = self.document_metadata_enricher
        if enricher is None:
            return ()
        existing = {
            field_name
            for layer in (source.metadata, parsed.document_metadata)
            for field_name in DOCUMENT_METADATA_FIELDS
            if layer.get(field_name) not in (None, "")
        }
        missing = tuple(field for field in DOCUMENT_METADATA_FIELDS if field not in existing)
        logical = parsed.to_logical_document()
        blocks = tuple(
            MetadataEvidenceBlock(
                block_id=block.id,
                page_number=block.page,
                text=block.text,
            )
            for block in logical.blocks
            if block.text.strip()
        )
        result = enricher.enrich(
            DocumentMetadataEnrichmentRequest(
                document_title=source.title,
                language=parsed.detected_language or logical.language or "unknown",
                missing_fields=missing,
                evidence_blocks=blocks,
            )
        )
        # LLM assertions remain unverified. They may enrich projection/ranking,
        # but the canonical document row is updated only by an explicit review RPC.
        raw_inferred = parsed.document_metadata.get("inferred_metadata")
        inferred = dict(raw_inferred) if isinstance(raw_inferred, Mapping) else {}
        for assertion in result.assertions:
            inferred.setdefault(assertion.field_name, assertion.normalized_value)
        if inferred:
            parsed.document_metadata["inferred_metadata"] = inferred
        parsed.document_metadata["metadata_enrichment"] = {
            "status": result.status,
            "provider": result.provider,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "input_checksum": result.input_checksum,
            "error_code": result.error_code,
        }
        return result.assertions

    def embed(
        self,
        prepared: PreparedIngestion,
        *,
        persist_vectors: bool,
        chunk_plan: ChunkEmbeddingPlan | None = None,
    ) -> IngestionEmbeddingResult:
        """Embed a prepared document, optionally persisting vectors."""
        source = prepared.source
        parsed = prepared.parsed_document
        chunks = prepared.chunks
        stages = list(prepared.stages)
        effective_plan = chunk_plan or ChunkEmbeddingPlan()
        chunks_by_index = {chunk.chunk_index: chunk for chunk in chunks}
        if len(chunks_by_index) != len(chunks):
            raise ValueError("Prepared chunks must have unique chunk indexes")
        plan_indexes = (
            set(effective_plan.precomputed_vectors)
            | set(effective_plan.reuse_from_chunk_index)
            | set(effective_plan.metadata_by_chunk_index)
        )
        unknown_indexes = plan_indexes - set(chunks_by_index)
        if unknown_indexes:
            raise ValueError("Chunk embedding plan references unknown chunk indexes")
        ambiguous_indexes = set(effective_plan.precomputed_vectors).intersection(
            effective_plan.reuse_from_chunk_index
        )
        if ambiguous_indexes:
            raise ValueError("A chunk cannot have both a precomputed vector and a reuse dependency")

        embedding_texts = {
            chunk.chunk_index: normalize_text(chunk.embedding_text or chunk.text)
            for chunk in chunks
        }
        vectors_by_index: dict[int, tuple[float, ...]] = {
            chunk_index: tuple(float(value) for value in vector)
            for chunk_index, vector in effective_plan.precomputed_vectors.items()
        }
        provider_indexes = [
            chunk.chunk_index
            for chunk in chunks
            if chunk.chunk_index not in vectors_by_index
            and chunk.chunk_index not in effective_plan.reuse_from_chunk_index
        ]
        provider_texts = [embedding_texts[index] for index in provider_indexes]
        with self.telemetry.observe(
            "ingestion.embed_chunks",
            as_type="embedding",
            input={
                "texts": self.telemetry.content(provider_texts),
                "count": len(provider_texts),
                "total_chunk_count": len(chunks),
                "precomputed_vector_count": len(vectors_by_index),
                "batch_reuse_count": len(effective_plan.reuse_from_chunk_index),
            },
            model=self.embedding_provider.model_name,
        ) as observation:
            self._advance(stages, IngestionEmbeddingStage.EMBEDDING)
            provider_vectors = self.embedding_provider.embed(provider_texts)
            if len(provider_vectors) != len(provider_indexes):
                raise RuntimeError("Embedding provider returned a mismatched vector count.")
            for chunk_index, vector in zip(
                provider_indexes,
                provider_vectors,
                strict=True,
            ):
                vectors_by_index[chunk_index] = tuple(float(value) for value in vector)

            def resolve_vector(
                chunk_index: int,
                resolving: set[int],
            ) -> tuple[float, ...]:
                existing = vectors_by_index.get(chunk_index)
                if existing is not None:
                    return existing
                source_index = effective_plan.reuse_from_chunk_index.get(chunk_index)
                if source_index is None or source_index not in chunks_by_index:
                    raise ValueError("Chunk embedding reuse dependency has no valid source")
                if chunk_index in resolving:
                    raise ValueError("Chunk embedding reuse dependencies contain a cycle")
                resolving.add(chunk_index)
                resolved = resolve_vector(source_index, resolving)
                resolving.remove(chunk_index)
                vectors_by_index[chunk_index] = resolved
                return resolved

            vectors = tuple(resolve_vector(chunk.chunk_index, set()) for chunk in chunks)
            dimensions = {len(vector) for vector in vectors}
            if 0 in dimensions or len(dimensions) > 1:
                raise RuntimeError("Embedded and reused vectors must have one non-zero dimension")
            observation.update(
                output={
                    "vector_count": len(vectors),
                    "provider_vector_count": len(provider_vectors),
                    "reused_vector_count": len(vectors) - len(provider_vectors),
                    "dimensions": next(iter(dimensions)) if dimensions else 0,
                }
            )

        embedded_chunks = tuple(
            build_embedded_chunk(
                source=source,
                parsed=parsed,
                chunk=chunk,
                vector=vector,
                embedding_text=embedding_texts[chunk.chunk_index],
                embedding_model=self.embedding_provider.model_name,
                quality_annotation=effective_plan.metadata_by_chunk_index.get(chunk.chunk_index),
            )
            for chunk, vector in zip(
                chunks,
                vectors,
                strict=True,
            )
        )
        if persist_vectors:
            self.persist_vectors(source, embedded_chunks)

        self._advance(stages, IngestionEmbeddingStage.EMBEDDED)
        return IngestionEmbeddingResult(
            source=source,
            parsed_document=parsed,
            chunks=chunks,
            embedded_chunks=embedded_chunks,
            stages=tuple(stages),
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            embedding_model=self.embedding_provider.model_name,
            extraction_artifacts=prepared.extraction_artifacts,
            document_metadata_assertions=prepared.document_metadata_assertions,
            document_metadata_profile=prepared.document_metadata_profile,
        )

    def persist_vectors(
        self,
        source: DocumentSource,
        embedded_chunks: tuple[EmbeddedChunk, ...],
    ) -> None:
        """Replace one document version with a fully prepared vector batch."""
        if self.vector_index is None:
            return
        generation = _ingestion_generation(embedded_chunks)
        if self.config.replace_existing_document_version and generation is None:
            with self.telemetry.observe(
                "vector_store.delete_document_version",
                as_type="tool",
                input={
                    "document_id": source.document_id,
                    "document_version": source.version,
                },
            ):
                self.vector_index.delete_document_version_vectors(
                    source.document_id,
                    source.version,
                )
        with self.telemetry.observe(
            "vector_store.upsert_chunks",
            as_type="tool",
            input={"chunk_count": len(embedded_chunks)},
        ) as observation:
            self.vector_index.upsert_chunks(embedded_chunks)
            observation.update(output={"upserted": len(embedded_chunks)})

    @property
    def requires_external_vector_persistence(self) -> bool:
        return self.vector_index is not None and not (
            isinstance(self.vector_index, GenerationAwareVectorIndex)
            and self.vector_index.completion_is_transactional
        )

    def finalize_vector_generation(
        self,
        document_id: str,
        document_version: int,
        generation: str,
    ) -> None:
        if isinstance(self.vector_index, GenerationAwareVectorIndex):
            self.vector_index.finalize_document_generation(
                document_id,
                document_version,
                generation,
            )

    def delete_document_generation_vectors(
        self,
        document_id: str,
        generation: str,
    ) -> None:
        if isinstance(self.vector_index, GenerationAwareVectorIndex):
            self.vector_index.delete_document_generation_vectors(
                document_id,
                generation,
            )
        else:
            self.delete_document_vectors(document_id)

    def delete_document_vectors(self, document_id: str) -> None:
        """Remove all indexed versions of a document, when an index is configured."""
        if self.vector_index is not None:
            with self.telemetry.observe(
                "vector_store.delete_document",
                as_type="tool",
                input={"document_id": document_id},
            ):
                self.vector_index.delete_document_vectors(document_id)

    @staticmethod
    def _advance(
        stages: list[IngestionEmbeddingStage],
        stage: IngestionEmbeddingStage,
    ) -> None:
        stages.append(stage)


def build_embedded_chunk(
    *,
    source: DocumentSource,
    parsed: ParsedDocument,
    chunk: ChunkData,
    vector: Sequence[float],
    embedding_text: str,
    embedding_model: str,
    quality_annotation: Mapping[str, object] | None = None,
) -> EmbeddedChunk:
    source_metadata = dict(chunk.metadata or {})
    canonical_text = str(source_metadata.get("canonical_content") or chunk.text).strip()
    fingerprint = build_chunk_fingerprint(canonical_text)
    exact_duplicate_group_id = uuid5(
        NAMESPACE_URL,
        (
            "rag-chunk-exact-group:"
            f"{source.owner_id}:{source.tenant_id}:"
            f"{fingerprint.normalization_version}:{fingerprint.strict_hash}"
        ),
    )
    chunk_metadata: dict[str, object] = {
        "source_block_ids": list(chunk.source_block_ids),
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
        "strategy": chunk.strategy,
        "strategy_version": chunk.strategy_version,
        "config_checksum": chunk.config_checksum,
        "embedding_text_checksum": compute_checksum_text(embedding_text),
        "normalized_content_hash": fingerprint.strict_hash,
        "loose_content_signature": fingerprint.loose_signature,
        "normalization_version": fingerprint.normalization_version,
        "exact_duplicate_group_id": str(exact_duplicate_group_id),
        "char_start": chunk.offset_start,
        "char_end": chunk.offset_end,
    }
    ingestion_generation = str(source.metadata.get("ingestion_generation") or "").strip()
    if ingestion_generation:
        chunk_metadata["ingestion_generation"] = ingestion_generation
    if quality_annotation:
        chunk_metadata["pre_embedding_quality"] = dict(quality_annotation)
    for key in (
        "context_enrichment",
        "contextual_text_version",
        "search_text_checksum",
        "table_atomic",
        "table_row_group",
        "table_row_group_index",
        "table_data_row_start_ordinal",
        "table_data_row_end_ordinal",
        "table_location",
        "table_header",
        "table_header_repeated",
        "node_type",
        "parent_chunk_id",
        "parent_context_holder_source_chunk_id",
        "parent_context_version",
        "parent_section_id",
        "parent_section_title",
        "parent_section_path",
        "parent_child_index",
        "parent_child_count",
        "parent_token_count",
        "parent_content_checksum",
        "parent_context",
    ):
        if (value := source_metadata.get(key)) is not None:
            chunk_metadata[key] = value
    retrieval_metadata = normalize_chunk_retrieval_metadata(
        chunk_metadata=source_metadata,
        document_metadata=parsed.document_metadata,
        source_metadata=source.metadata,
        title=source.title,
        section_title=chunk.section_title,
        reference_date=date.today(),
    )
    return EmbeddedChunk(
        id=chunk.chunk_id,
        document_id=source.document_id,
        document_version=source.version,
        owner_id=source.owner_id,
        tenant_id=source.tenant_id,
        chunk_index=chunk.chunk_index,
        page_number=chunk.page_number,
        section_title=chunk.section_title,
        checksum=chunk.checksum,
        text=normalize_text(chunk.text),
        canonical_text=canonical_text,
        token_count=_metadata_int(source_metadata.get("token_count")),
        embedding=tuple(float(value) for value in vector),
        embedding_model=embedding_model,
        metadata=chunk_metadata,
        retrieval_metadata=retrieval_metadata,
        provenance_metadata=_mapping_metadata(source_metadata.get("provenance_metadata")),
        authority_metadata=_mapping_metadata(source_metadata.get("authority_metadata")),
        embedding_text=embedding_text,
        search_text=chunk.search_text,
    )


def _metadata_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float | str):
        try:
            return max(0, int(value))
        except ValueError:
            return 0
    return 0


def _mapping_metadata(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _context_enrichment_status(metadata: Mapping[str, object]) -> str | None:
    value = metadata.get("context_enrichment")
    if not isinstance(value, Mapping):
        return None
    status = str(value.get("status") or "").strip()
    return status or None


def _known_value(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or normalized.casefold() == "unknown":
        return None
    return normalized


def _build_document_outline(chunks: Sequence[ChunkData], limit: int) -> str:
    sections: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        context = ChunkContext.from_metadata(chunk.metadata)
        section = context.effective_section
        if not section:
            continue
        key = section.casefold()
        if key in seen:
            continue
        seen.add(key)
        sections.append(section)
    return _truncate_text("\n".join(sections), limit)


def _build_bounded_context_package(
    document_text: str,
    chunks: Sequence[ChunkData],
    index: int,
    limit: int,
) -> str:
    """Build a global-plus-local package when the whole document does not fit."""
    chunk = chunks[index]
    opening_limit = min(1200, max(200, limit // 8))
    section_limit = max(200, (limit * 3) // 8)
    neighbor_limit = max(200, limit // 5)
    local_limit = max(200, limit - opening_limit - section_limit - neighbor_limit - 160)

    opening = _truncate_text(document_text[:opening_limit].strip(), opening_limit)
    current_context = ChunkContext.from_metadata(chunk.metadata)
    section_key = (
        current_context.effective_section or current_context.section_title or ""
    ).casefold()
    section_chunks = [
        candidate.text
        for position, candidate in enumerate(chunks)
        if position != index
        and section_key
        and (
            ChunkContext.from_metadata(candidate.metadata).effective_section
            or ChunkContext.from_metadata(candidate.metadata).section_title
            or ""
        ).casefold()
        == section_key
    ]
    section_passage = _truncate_text("\n\n".join(section_chunks), section_limit)

    neighbor_chunks = [
        chunks[position].text
        for position in range(max(0, index - 2), min(len(chunks), index + 3))
        if position != index
    ]
    neighboring_passage = _truncate_text("\n\n".join(neighbor_chunks), neighbor_limit)
    local_passage = (
        _build_document_excerpt(
            document_text,
            chunk.offset_start,
            chunk.offset_end,
            local_limit,
        )
        .replace(chunk.text, "", 1)
        .strip()
    )

    parts = [("Document opening", opening)]
    if section_passage:
        parts.append(("Related section passage", section_passage))
    if neighboring_passage:
        parts.append(("Neighboring extracted chunks", neighboring_passage))
    if local_passage:
        parts.append(("Local source passage", local_passage))
    package = "\n\n".join(f"{label}:\n{text}" for label, text in parts if text)
    return _truncate_text(package, limit)


def _build_document_excerpt(text: str, start: int, end: int, limit: int) -> str:
    if len(text) <= limit:
        return text.strip()
    center = max(0, min(len(text), (max(0, start) + max(start, end)) // 2))
    local_start = max(0, center - limit // 2)
    local_end = min(len(text), local_start + limit)
    local_start = max(0, local_end - limit)
    local = text[local_start:local_end].strip()
    return _truncate_text(local, limit)


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].strip()
    return shortened or text[:limit].strip()


def _ingestion_generation(
    chunks: tuple[EmbeddedChunk, ...],
) -> str | None:
    if not chunks:
        return None
    generation = str(chunks[0].metadata.get("ingestion_generation") or "").strip()
    return generation or None


__all__ = [
    "ChunkEmbeddingPlan",
    "IngestionEmbeddingPipeline",
    "IngestionEmbeddingPipelineConfig",
    "IngestionEmbeddingResult",
    "IngestionEmbeddingStage",
    "PreparedIngestion",
    "build_embedded_chunk",
]
