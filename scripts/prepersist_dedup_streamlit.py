"""Streamlit dry-run inspector for dedup actions before ingestion persistence."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ingestion.application.worker import IngestionWorker  # noqa: E402
from app.ingestion.domain.models import PersistedChunk  # noqa: E402
from app.knowledge_quality.application.analysis import (  # noqa: E402
    is_auto_identity_eligible,
)
from app.knowledge_quality.application.chunk_preembedding import (  # noqa: E402
    build_chunk_dedup_probes,
    plan_chunk_deduplication,
    simhash_hamming_distance,
    simhash_lsh_bands,
)
from app.knowledge_quality.application.detection import (  # noqa: E402
    detect_document_relation_candidates,
)
from app.knowledge_quality.domain.models import (  # noqa: E402
    CHUNK_PREEMBEDDING_DETECTOR_VERSION,
    DETECTOR_VERSION,
    ChunkDedupCandidate,
    ChunkDedupProbe,
    DocumentFingerprint,
    QualityRelationCandidate,
    RelationType,
)
from app.pipeline.documents.adapters.parsers import ParserRegistry  # noqa: E402
from app.pipeline.documents.application.content_identity import (  # noqa: E402
    build_parsed_document_fingerprint,
)
from app.pipeline.documents.application.extraction_pipeline import (  # noqa: E402
    AdvancedExtractionPipeline,
    AdvancedExtractionPipelineConfig,
)
from app.pipeline.documents.application.validation import (  # noqa: E402
    DEFAULT_EXTENSIONS,
    DocumentValidationConfig,
)
from app.pipeline.documents.domain.source import DocumentSource  # noqa: E402
from app.pipeline.indexing.adapters.embedding_providers import (  # noqa: E402
    EmbeddingProviderConfig,
    create_embedding_provider,
)
from app.pipeline.indexing.adapters.vector_indexes import InMemoryVectorIndex  # noqa: E402
from app.pipeline.indexing.application.chunker import (  # noqa: E402
    SUPPORTED_STRATEGIES,
    Chunker,
)
from app.pipeline.indexing.application.pipeline import (  # noqa: E402
    ChunkEmbeddingPlan,
    IngestionEmbeddingPipeline,
    IngestionEmbeddingPipelineConfig,
    PreparedIngestion,
)
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk  # noqa: E402

KnowledgeQualityMode = Literal["off", "shadow", "on"]

DEFAULT_OWNER_ID = str(uuid5(NAMESPACE_URL, "streamlit-prepersist-owner"))
DEFAULT_NOTEBOOK_ID = str(uuid5(NAMESPACE_URL, "streamlit-prepersist-notebook"))


@dataclass(frozen=True)
class UploadedAsset:
    name: str
    content: bytes
    mime_type: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class PreparedDocument:
    asset: UploadedAsset
    source: DocumentSource
    prepared: PreparedIngestion
    fingerprint: DocumentFingerprint
    embedded_chunks: tuple[EmbeddedChunk, ...] = ()
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class DocumentDuplicateMatch:
    reference: PreparedDocument
    canonical_document_id: UUID


@dataclass(frozen=True)
class InspectorConfig:
    owner_id: str
    notebook_id: str
    quality_mode: KnowledgeQualityMode
    chunk_size: int
    chunk_overlap: int
    chunking_strategy: str
    max_probe_chunks: int
    candidates_per_probe: int
    advanced_extraction_enabled: bool
    extraction_quality_mode: str
    ocr_enabled: bool
    embedding_provider: str
    openai_embedding_model: str
    continue_after_exact_suppression: bool


@dataclass(frozen=True)
class Inspection:
    target: PreparedDocument
    references: tuple[PreparedDocument, ...]
    duplicate_match: DocumentDuplicateMatch | None
    production_stops_at_duplicate: bool
    probes: tuple[ChunkDedupProbe, ...]
    chunk_candidates: tuple[ChunkDedupCandidate, ...]
    chunk_plan: object | None
    embedded_result_chunks: tuple[EmbeddedChunk, ...]
    post_embedding_relations: tuple[QualityRelationCandidate, ...]
    pending_relations: tuple[QualityRelationCandidate, ...]
    persisted_chunks: tuple[PersistedChunk, ...]
    embedding_model: str
    embedding_dimensions: int


def main() -> None:
    st.set_page_config(
        page_title="Pre-persist Dedup Inspector",
        layout="wide",
    )
    st.title("Pre-persist Dedup Inspector")
    st.caption(
        "Dry-run các bước sau khi extraction thành công và trước khi lưu chunks, "
        "vectors, pending relations. App không ghi Supabase, Qdrant hay pgvector."
    )

    target_upload, reference_uploads, config = _render_inputs()
    if target_upload is None:
        st.info("Upload file cần kiểm tra để bắt đầu.")
        return

    if not st.button("Chạy dry-run inspector", type="primary"):
        st.info("Nhấn nút run để chạy pipeline kiểm tra.")
        return

    with st.spinner("Đang chạy extraction, dedup gates và embedding dry-run..."):
        inspection = _inspect(
            target_upload,
            reference_uploads,
            config,
        )

    if inspection.target.error is not None:
        st.error(inspection.target.error)
        return
    _render_inspection(inspection, config)


def _render_inputs() -> tuple[UploadedAsset | None, tuple[UploadedAsset, ...], InspectorConfig]:
    registry = ParserRegistry()
    supported_extensions = tuple(
        sorted(set(DEFAULT_EXTENSIONS) & set(registry.supported_extensions))
    )
    with st.sidebar:
        st.header("Cấu hình pipeline")
        quality_mode = st.selectbox(
            "KNOWLEDGE_QUALITY_MODE",
            ["on", "shadow", "off"],
            index=0,
        )
        chunk_size = st.number_input(
            "CHUNK_SIZE",
            min_value=64,
            max_value=2000,
            value=600,
            step=32,
        )
        chunk_overlap = st.number_input(
            "CHUNK_OVERLAP",
            min_value=0,
            max_value=max(0, int(chunk_size) - 1),
            value=min(80, max(0, int(chunk_size) - 1)),
            step=8,
        )
        chunking_strategy = st.selectbox(
            "CHUNKING_STRATEGY",
            list(SUPPORTED_STRATEGIES),
            index=0,
        )
        max_probe_chunks = st.slider(
            "KNOWLEDGE_QUALITY_MAX_PROBE_CHUNKS",
            min_value=1,
            max_value=32,
            value=8,
        )
        candidates_per_probe = st.slider(
            "Candidates per probe",
            min_value=1,
            max_value=20,
            value=5,
        )
        st.divider()
        advanced_extraction_enabled = st.checkbox(
            "Advanced Extraction",
            value=True,
        )
        extraction_quality_mode = st.selectbox(
            "EXTRACTION_QUALITY_MODE",
            ["rag", "structured"],
            index=0,
        )
        ocr_enabled = st.checkbox(
            "OCR enabled",
            value=False,
        )
        st.divider()
        embedding_provider = st.selectbox(
            "Nhà cung cấp embedding",
            ["local", "openai"],
            index=0,
            help="Local là deterministic hash embedding dùng để inspect offline.",
        )
        openai_embedding_model = st.text_input(
            "OPENAI_EMBEDDING_MODEL",
            value=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        )
        continue_after_exact_suppression = st.checkbox(
            "Tiếp tục debug sau exact suppression",
            value=False,
            help=(
                "Production sẽ dừng ngay khi exact duplicate ở mode on. "
                "Bật tùy chọn này để xem tiếp chunk/vector plan cho mục đích debug."
            ),
        )
        st.divider()
        owner_id = st.text_input("Owner id", value=DEFAULT_OWNER_ID)
        notebook_id = st.text_input("Notebook id", value=DEFAULT_NOTEBOOK_ID)

    st.subheader("Upload file")
    left, right = st.columns(2)
    with left:
        target_raw = st.file_uploader(
            "File mới cần inspect",
            type=list(supported_extensions),
            accept_multiple_files=False,
        )
    with right:
        references_raw = st.file_uploader(
            "Corpus tham chiếu giả lập DB",
            type=list(supported_extensions),
            accept_multiple_files=True,
            help=(
                "Upload các file đã tồn tại để giả lập lookup content duplicate, "
                "chunk candidates và vector relation candidates."
            ),
        )

    target = _uploaded_asset(target_raw) if target_raw is not None else None
    references = tuple(_uploaded_asset(item) for item in references_raw)
    return (
        target,
        references,
        InspectorConfig(
            owner_id=owner_id.strip() or DEFAULT_OWNER_ID,
            notebook_id=notebook_id.strip() or DEFAULT_NOTEBOOK_ID,
            quality_mode=quality_mode,
            chunk_size=int(chunk_size),
            chunk_overlap=int(chunk_overlap),
            chunking_strategy=str(chunking_strategy),
            max_probe_chunks=int(max_probe_chunks),
            candidates_per_probe=int(candidates_per_probe),
            advanced_extraction_enabled=advanced_extraction_enabled,
            extraction_quality_mode=extraction_quality_mode,
            ocr_enabled=ocr_enabled,
            embedding_provider=embedding_provider,
            openai_embedding_model=openai_embedding_model.strip() or "text-embedding-3-small",
            continue_after_exact_suppression=continue_after_exact_suppression,
        ),
    )


def _uploaded_asset(uploaded: Any) -> UploadedAsset:
    content = uploaded.getvalue()
    return UploadedAsset(
        name=str(uploaded.name),
        content=content,
        mime_type=_guess_mime(str(uploaded.name), str(getattr(uploaded, "type", "") or "")),
    )


def _inspect(
    target_asset: UploadedAsset,
    reference_assets: tuple[UploadedAsset, ...],
    config: InspectorConfig,
) -> Inspection:
    pipeline = _build_pipeline(config)
    target = _prepare_document(
        target_asset,
        pipeline=pipeline,
        config=config,
        role="target",
        index=0,
        embed_reference=False,
    )
    if target.error is not None:
        return Inspection(
            target=target,
            references=(),
            duplicate_match=None,
            production_stops_at_duplicate=False,
            probes=(),
            chunk_candidates=(),
            chunk_plan=None,
            embedded_result_chunks=(),
            post_embedding_relations=(),
            pending_relations=(),
            persisted_chunks=(),
            embedding_model=pipeline.embedding_provider.model_name,
            embedding_dimensions=0,
        )

    references = tuple(
        item
        for item in (
            _prepare_document(
                asset,
                pipeline=pipeline,
                config=config,
                role="reference",
                index=index,
                embed_reference=True,
            )
            for index, asset in enumerate(reference_assets, start=1)
        )
        if item.ready
    )
    duplicate_match = (
        _find_document_duplicate(target.fingerprint, references)
        if config.quality_mode != "off"
        else None
    )
    production_stops = duplicate_match is not None and config.quality_mode == "on"
    continue_downstream = not production_stops or config.continue_after_exact_suppression

    probes: tuple[ChunkDedupProbe, ...] = ()
    chunk_candidates: tuple[ChunkDedupCandidate, ...] = ()
    chunk_plan = None
    embedded_chunks: tuple[EmbeddedChunk, ...] = ()
    post_embedding_relations: tuple[QualityRelationCandidate, ...] = ()
    pending_relations: tuple[QualityRelationCandidate, ...] = ()
    persisted_chunks: tuple[PersistedChunk, ...] = ()
    embedding_dimensions = 0

    if duplicate_match is not None and config.quality_mode == "shadow":
        pending_relations = (
            QualityRelationCandidate(
                target_document_id=duplicate_match.canonical_document_id,
                relation_type=RelationType.EXACT_CONTENT,
                confidence=1.0,
                signals={"strict_content_match": True},
                reason="strict_content_match",
            ),
        )

    if continue_downstream:
        if config.quality_mode != "off":
            probes = build_chunk_dedup_probes(
                target.prepared.chunks,
                max_fuzzy_probes=config.max_probe_chunks,
            )
            chunk_candidates = _build_in_memory_chunk_candidates(
                probes,
                references,
                embedding_model=pipeline.embedding_provider.model_name,
                candidates_per_probe=config.candidates_per_probe,
            )
            chunk_plan = plan_chunk_deduplication(
                probes,
                chunk_candidates,
                embedding_model=pipeline.embedding_provider.model_name,
                enable_exact_reuse=config.quality_mode == "on",
            )
            pending_relations = _merge_relation_candidates(
                pending_relations,
                chunk_plan.relations,
            )

        result = pipeline.embed(
            target.prepared,
            persist_vectors=False,
            chunk_plan=(
                ChunkEmbeddingPlan(
                    precomputed_vectors=chunk_plan.precomputed_vectors,
                    reuse_from_chunk_index=chunk_plan.reuse_from_chunk_index,
                    metadata_by_chunk_index=chunk_plan.metadata_by_chunk_index,
                )
                if chunk_plan is not None
                else None
            ),
        )
        embedded_chunks = result.embedded_chunks
        embedding_dimensions = embedded_chunks[0].vector_size if embedded_chunks else 0

        if (
            config.quality_mode != "off"
            and duplicate_match is None
            and any(reference.embedded_chunks for reference in references)
        ):
            vector_index = InMemoryVectorIndex()
            vector_index.upsert_chunks(
                tuple(chunk for reference in references for chunk in reference.embedded_chunks)
            )
            post_embedding_relations = detect_document_relation_candidates(
                vector_index=vector_index,
                chunks=embedded_chunks,
                max_probe_chunks=config.max_probe_chunks,
                candidates_per_probe=config.candidates_per_probe,
            )
            pending_relations = _merge_relation_candidates(
                pending_relations,
                post_embedding_relations,
            )

        persisted_chunks = IngestionWorker._to_persisted_chunks(result)

    return Inspection(
        target=target,
        references=references,
        duplicate_match=duplicate_match,
        production_stops_at_duplicate=production_stops,
        probes=probes,
        chunk_candidates=chunk_candidates,
        chunk_plan=chunk_plan,
        embedded_result_chunks=embedded_chunks,
        post_embedding_relations=post_embedding_relations,
        pending_relations=pending_relations,
        persisted_chunks=persisted_chunks,
        embedding_model=pipeline.embedding_provider.model_name,
        embedding_dimensions=embedding_dimensions,
    )


def _build_pipeline(config: InspectorConfig) -> IngestionEmbeddingPipeline:
    provider_config = EmbeddingProviderConfig(
        provider=config.embedding_provider,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_embedding_model=config.openai_embedding_model,
    )
    embedding_provider = create_embedding_provider(provider_config)
    extraction_pipeline = (
        AdvancedExtractionPipeline(
            AdvancedExtractionPipelineConfig(
                ocr_enabled=config.ocr_enabled,
                quality_mode=config.extraction_quality_mode,
            )
        )
        if config.advanced_extraction_enabled
        else None
    )
    return IngestionEmbeddingPipeline(
        parser_catalog=ParserRegistry(ocr_enabled=config.ocr_enabled),
        chunker=Chunker(
            config.chunk_size,
            config.chunk_overlap,
            strategy_name=config.chunking_strategy,
        ),
        embedding_provider=embedding_provider,
        vector_index=None,
        config=IngestionEmbeddingPipelineConfig(
            validation=DocumentValidationConfig(),
        ),
        extraction_pipeline=extraction_pipeline,
    )


def _prepare_document(
    asset: UploadedAsset,
    *,
    pipeline: IngestionEmbeddingPipeline,
    config: InspectorConfig,
    role: str,
    index: int,
    embed_reference: bool,
) -> PreparedDocument:
    source = _source_from_asset(asset, config=config, role=role, index=index)
    try:
        prepared = pipeline.prepare(source)
        fingerprint = build_parsed_document_fingerprint(prepared.parsed_document)
        embedded_chunks: tuple[EmbeddedChunk, ...] = ()
        if embed_reference:
            result = pipeline.embed(prepared, persist_vectors=False)
            embedded_chunks = result.embedded_chunks
        return PreparedDocument(
            asset=asset,
            source=source,
            prepared=prepared,
            fingerprint=fingerprint,
            embedded_chunks=embedded_chunks,
        )
    except Exception as exc:
        return PreparedDocument(
            asset=asset,
            source=source,
            prepared=_empty_prepared(source),
            fingerprint=_empty_fingerprint(),
            error=f"{asset.name}: {type(exc).__name__}: {exc}",
        )


def _source_from_asset(
    asset: UploadedAsset,
    *,
    config: InspectorConfig,
    role: str,
    index: int,
) -> DocumentSource:
    document_id = str(
        uuid5(
            NAMESPACE_URL,
            f"prepersist:{role}:{index}:{asset.name}:{asset.sha256}",
        )
    )
    return DocumentSource(
        document_id=document_id,
        owner_id=config.owner_id,
        tenant_id=config.notebook_id,
        title=asset.name,
        content=asset.content,
        version=1,
        mime_type=asset.mime_type,
        metadata={
            "notebook_id": config.notebook_id,
            "ingestion_job_id": str(
                uuid5(NAMESPACE_URL, f"prepersist-job:{role}:{index}:{asset.sha256}")
            ),
            "ingestion_attempt": 1,
            "ingestion_generation": str(
                uuid5(NAMESPACE_URL, f"prepersist-generation:{role}:{index}:{asset.sha256}")
            ),
            "storage_bucket": "streamlit-dry-run",
            "storage_object_path": f"dry-run/{document_id}/{asset.name}",
        },
    )


def _empty_prepared(source: DocumentSource) -> PreparedIngestion:
    from app.pipeline.documents.domain.parsed import ParsedDocument

    parsed = ParsedDocument(text="")
    return PreparedIngestion(
        source=source,
        parsed_document=parsed,
        chunks=(),
        stages=(),
        parser_name="",
        parser_version="",
    )


def _empty_fingerprint() -> DocumentFingerprint:
    return DocumentFingerprint(
        strict_hash="",
        loose_signature="0000000000000000",
        normalization_version="",
        character_count=0,
        token_count=0,
        identity_trusted=False,
    )


def _find_document_duplicate(
    fingerprint: DocumentFingerprint,
    references: Sequence[PreparedDocument],
) -> DocumentDuplicateMatch | None:
    if not is_auto_identity_eligible(fingerprint):
        return None
    for reference in references:
        if not is_auto_identity_eligible(reference.fingerprint):
            continue
        same_identity = (
            reference.fingerprint.strict_hash == fingerprint.strict_hash
            and reference.fingerprint.normalization_version
            == fingerprint.normalization_version
        )
        if same_identity:
            return DocumentDuplicateMatch(
                reference=reference,
                canonical_document_id=UUID(reference.source.document_id),
            )
    return None


def _build_in_memory_chunk_candidates(
    probes: Sequence[ChunkDedupProbe],
    references: Sequence[PreparedDocument],
    *,
    embedding_model: str,
    candidates_per_probe: int,
) -> tuple[ChunkDedupCandidate, ...]:
    candidates: list[ChunkDedupCandidate] = []
    reference_chunks = tuple(chunk for item in references for chunk in item.embedded_chunks)
    for probe in probes:
        scored: list[tuple[int, int, str, ChunkDedupCandidate]] = []
        for target in reference_chunks:
            candidate = _candidate_from_reference_chunk(
                probe,
                target,
                embedding_model=embedding_model,
            )
            if candidate is None:
                continue
            strict_match = int(
                candidate.normalized_content_hash == probe.fingerprint.strict_hash
                and candidate.normalization_version == probe.fingerprint.normalization_version
            )
            scored.append(
                (
                    strict_match,
                    candidate.lsh_band_matches,
                    candidate.target_chunk_id,
                    candidate,
                )
            )
        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        candidates.extend(item[3] for item in scored[:candidates_per_probe])
    return tuple(candidates)


def _candidate_from_reference_chunk(
    probe: ChunkDedupProbe,
    target: EmbeddedChunk,
    *,
    embedding_model: str,
) -> ChunkDedupCandidate | None:
    metadata = target.metadata
    normalized_hash = str(metadata.get("normalized_content_hash") or "")
    normalization_version = str(metadata.get("normalization_version") or "")
    loose_signature = str(metadata.get("loose_content_signature") or "")
    if not normalized_hash or not normalization_version or not loose_signature:
        return None
    if normalization_version != probe.fingerprint.normalization_version:
        return None
    strict_match = normalized_hash == probe.fingerprint.strict_hash
    lsh_band_matches = _lsh_band_match_count(
        probe.fingerprint.loose_signature,
        loose_signature,
    )
    if not strict_match and (not probe.include_fuzzy_candidates or lsh_band_matches <= 0):
        return None
    return ChunkDedupCandidate(
        source_chunk_index=probe.chunk_index,
        target_chunk_id=target.id,
        target_document_id=UUID(target.document_id),
        target_chunk_index=target.chunk_index,
        canonical_text=target.canonical_text,
        normalized_content_hash=normalized_hash,
        normalization_version=normalization_version,
        loose_content_signature=loose_signature,
        embedding_text_checksum=_metadata_str(metadata, "embedding_text_checksum"),
        embedding=target.embedding,
        embedding_model=target.embedding_model or embedding_model,
        lsh_band_matches=lsh_band_matches,
    )


def _merge_relation_candidates(
    existing: tuple[QualityRelationCandidate, ...],
    detected: tuple[QualityRelationCandidate, ...],
) -> tuple[QualityRelationCandidate, ...]:
    relation_priority = {
        RelationType.CONFLICT_CANDIDATE: 5,
        RelationType.VERSION_CANDIDATE: 4,
        RelationType.NEAR_DUPLICATE: 3,
        RelationType.EXACT_CONTENT: 2,
        RelationType.RELATED: 1,
        RelationType.DISTINCT: 0,
    }
    by_target = {candidate.target_document_id: candidate for candidate in existing}
    for candidate in detected:
        previous = by_target.get(candidate.target_document_id)
        if previous is None:
            by_target[candidate.target_document_id] = candidate
            continue
        if (
            relation_priority.get(candidate.relation_type, 0),
            candidate.confidence,
        ) > (
            relation_priority.get(previous.relation_type, 0),
            previous.confidence,
        ):
            by_target[candidate.target_document_id] = candidate
    return tuple(
        sorted(
            by_target.values(),
            key=lambda candidate: candidate.confidence,
            reverse=True,
        )
    )


def _render_inspection(inspection: Inspection, config: InspectorConfig) -> None:
    _render_metrics(inspection, config)
    tabs = st.tabs(
        [
            "Dễ hiểu",
            "Layer A-R",
            "Tóm tắt worker",
            "Extraction",
            "Cổng tài liệu",
            "Cổng chunk",
            "Kế hoạch embedding",
            "Payload trước lưu",
            "JSON báo cáo",
        ]
    )
    with tabs[0]:
        _render_plain_explanation(inspection, config)
    with tabs[1]:
        _render_layer_flow(inspection, config)
    with tabs[2]:
        _render_action_flow(inspection, config)
    with tabs[3]:
        _render_extraction(inspection)
    with tabs[4]:
        _render_document_gate(inspection, config)
    with tabs[5]:
        _render_chunk_gate(inspection, config)
    with tabs[6]:
        _render_embedding_plan(inspection, config)
    with tabs[7]:
        _render_pre_persist_payload(inspection)
    with tabs[8]:
        _render_report_json(inspection, config)


def _render_metrics(inspection: Inspection, config: InspectorConfig) -> None:
    cols = st.columns(5)
    cols[0].metric("Quality mode", config.quality_mode)
    cols[1].metric("Target chunks", len(inspection.target.prepared.chunks))
    cols[2].metric("Reference files", len(inspection.references))
    cols[3].metric("Chunk candidates", len(inspection.chunk_candidates))
    cols[4].metric("Pending relations", len(inspection.pending_relations))
    if inspection.production_stops_at_duplicate:
        st.warning(
            "Nhánh production dừng ở exact content duplicate khi mode=on. "
            "Sẽ không embedding và không lưu chunk/vector/relation mới cho file này."
        )
    else:
        st.success("Dry-run đã tới ranh giới pre-persist. Chưa có dữ liệu nào được lưu.")


def _render_plain_explanation(inspection: Inspection, config: InspectorConfig) -> None:
    st.subheader("Kết luận nhanh")
    conclusion = _plain_conclusion(inspection, config)
    if conclusion["tone"] == "warning":
        st.warning(str(conclusion["message"]))
    elif conclusion["tone"] == "success":
        st.success(str(conclusion["message"]))
    else:
        st.info(str(conclusion["message"]))

    st.dataframe(
        _plain_answer_rows(inspection, config),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Đọc luồng theo 6 chặng")
    for item in _plain_stage_cards(inspection, config):
        with st.expander(str(item["title"]), expanded=bool(item["expanded"])):
            st.write(str(item["explain"]))
            st.dataframe(
                item["facts"],
                use_container_width=True,
                hide_index=True,
            )

    with st.expander("Giải nghĩa thuật ngữ"):
        st.write(
            {
                "ParsedDocument": "kết quả text/bảng/trang sau khi trích xuất file",
                "sanitize": "làm sạch và chuẩn hóa text trước khi xử lý tiếp",
                "chunk": "một đoạn nhỏ của tài liệu dùng để embedding và tìm kiếm",
                "fingerprint": (
                    "dấu vân tay nội dung; dùng để biết hai tài liệu/đoạn "
                    "có giống nhau không"
                ),
                "normalized hash": (
                    "mã hash của nội dung đã chuẩn hóa, bỏ khác biệt do định dạng file"
                ),
                "auto alias": "không lưu bản mới, chỉ trỏ file mới về tài liệu canonical đã có",
                "embedding": "vector số biểu diễn nghĩa của chunk để tìm kiếm",
                "pending relation": (
                    "quan hệ cần review, ví dụ gần trùng, phiên bản khác, hoặc xung đột"
                ),
                "pre-persist": "điểm ngay trước khi ghi chunks/vectors/relations vào database",
            }
        )


def _plain_conclusion(
    inspection: Inspection,
    config: InspectorConfig,
) -> dict[str, str]:
    if inspection.production_stops_at_duplicate:
        if config.continue_after_exact_suppression:
            return {
                "tone": "warning",
                "message": (
                    "Production sẽ coi file này là exact duplicate và dừng trước khi lưu "
                    "chunks/vectors mới. Các kết quả phía sau chỉ đang được hiển thị để debug."
                ),
            }
        return {
            "tone": "warning",
            "message": (
                "File này trùng nội dung với tài liệu đã có. Nếu chạy thật ở mode=on, "
                "hệ thống sẽ auto alias về canonical document và không embedding/lưu chunk mới."
            ),
        }
    if config.quality_mode == "off":
        return {
            "tone": "info",
            "message": (
                "Quality mode đang off, nên hệ thống chỉ trích xuất, chia chunk và embedding. "
                "Các bước chống trùng nâng cao bị bỏ qua."
            ),
        }
    if not inspection.references:
        return {
            "tone": "info",
            "message": (
                "Bạn chưa upload corpus tham chiếu, nên app chỉ kiểm tra được nội bộ file mới. "
                "Muốn thấy chống trùng với tài liệu cũ, hãy upload thêm file ở ô corpus tham chiếu."
            ),
        }
    if inspection.pending_relations:
        return {
            "tone": "success",
            "message": (
                "File không bị auto chặn ở cấp tài liệu. Hệ thống đã đi tới ranh giới trước lưu "
                f"với {len(inspection.persisted_chunks)} chunk payload và "
                f"{len(inspection.pending_relations)} pending relation để review."
            ),
        }
    return {
        "tone": "success",
        "message": (
            "File không bị phát hiện trùng ở các lớp đang mô phỏng. Hệ thống đã chuẩn bị xong "
            f"{len(inspection.persisted_chunks)} chunk payload và dừng ngay trước bước lưu."
        ),
    }


def _plain_answer_rows(
    inspection: Inspection,
    config: InspectorConfig,
) -> list[dict[str, object]]:
    duplicate_name = (
        inspection.duplicate_match.reference.asset.name
        if inspection.duplicate_match is not None
        else None
    )
    return [
        {
            "Câu hỏi": "File này có bị chặn vì trùng tài liệu không?",
            "Trả lời": (
                f"Có, trùng với {duplicate_name}"
                if inspection.production_stops_at_duplicate
                else "Không ở nhánh production hiện tại"
            ),
            "Ý nghĩa": (
                "Không lưu chunk/vector mới"
                if inspection.production_stops_at_duplicate
                else "Tiếp tục qua các lớp chunk và embedding"
            ),
        },
        {
            "Câu hỏi": "Có chia được chunk không?",
            "Trả lời": f"Có, {len(inspection.target.prepared.chunks)} chunk",
            "Ý nghĩa": (
                "Đây là các đoạn sẽ được fingerprint/embedding nếu không bị "
                "duplicate cấp tài liệu"
            ),
        },
        {
            "Câu hỏi": "Có reuse embedding nào không?",
            "Trả lời": _plain_reuse_answer(inspection),
            "Ý nghĩa": "Reuse chỉ xảy ra khi exact chunk thật sự an toàn",
        },
        {
            "Câu hỏi": "Có relation nào cần review không?",
            "Trả lời": (
                f"Có, {len(inspection.pending_relations)} relation"
                if inspection.pending_relations
                else "Không"
            ),
            "Ý nghĩa": "Relation là gần trùng, version, conflict hoặc exact_content ở shadow mode",
        },
        {
            "Câu hỏi": "App đã ghi dữ liệu chưa?",
            "Trả lời": "Chưa",
            "Ý nghĩa": "Đây là dry-run; dừng trước bước lưu chunks/vectors/pending relations",
        },
    ]


def _plain_stage_cards(
    inspection: Inspection,
    config: InspectorConfig,
) -> list[dict[str, object]]:
    parsed = inspection.target.prepared.parsed_document
    fingerprint = inspection.target.fingerprint
    chunk_plan = inspection.chunk_plan
    chunk_stats = chunk_plan.to_stats() if chunk_plan is not None else {}
    return [
        {
            "title": "1. Đọc file và làm sạch nội dung",
            "expanded": True,
            "explain": (
                "App đọc file upload, trích xuất thành ParsedDocument, rồi normalize text. "
                "Nếu bước này fail thì các bước chống trùng phía sau không chạy."
            ),
            "facts": [
                {"Thông tin": "Parser", "Kết quả": inspection.target.prepared.parser_name or "-"},
                {"Thông tin": "Số trang", "Kết quả": len(parsed.pages)},
                {"Thông tin": "Số bảng", "Kết quả": len(parsed.tables)},
                {"Thông tin": "Số cảnh báo", "Kết quả": len(parsed.warnings)},
            ],
        },
        {
            "title": "2. Chia tài liệu thành chunk",
            "expanded": True,
            "explain": (
                "Sau khi text đã sạch, app chia tài liệu thành các đoạn nhỏ. "
                "Mỗi chunk sẽ có checksum, vị trí trang/section và text dùng cho embedding."
            ),
            "facts": [
                {"Thông tin": "Số chunk", "Kết quả": len(inspection.target.prepared.chunks)},
                {"Thông tin": "Chunk size", "Kết quả": config.chunk_size},
                {"Thông tin": "Overlap", "Kết quả": config.chunk_overlap},
                {"Thông tin": "Strategy", "Kết quả": config.chunking_strategy},
            ],
        },
        {
            "title": "3. Kiểm tra trùng ở cấp tài liệu",
            "expanded": True,
            "explain": (
                "App tạo fingerprint v2 cho cả tài liệu. Nếu fingerprint đủ tin cậy, "
                "nó so normalized hash với corpus tham chiếu trong cùng notebook."
            ),
            "facts": [
                {
                    "Thông tin": "Fingerprint đủ tin cậy?",
                    "Kết quả": "Có" if is_auto_identity_eligible(fingerprint) else "Không",
                },
                {
                    "Thông tin": "Tìm thấy exact document?",
                    "Kết quả": _duplicate_label(inspection.duplicate_match),
                },
                {
                    "Thông tin": "Quyết định",
                    "Kết quả": _plain_document_decision(inspection, config),
                },
            ],
        },
        {
            "title": "4. Kiểm tra trùng ở cấp chunk trước embedding",
            "expanded": not inspection.production_stops_at_duplicate,
            "explain": (
                "Nếu tài liệu không bị auto alias, app fingerprint từng chunk, tìm exact/LSH "
                "candidate trong corpus tham chiếu, rồi quyết định chunk nào có thể reuse vector."
            ),
            "facts": [
                {"Thông tin": "Số probe chunk", "Kết quả": len(inspection.probes)},
                {"Thông tin": "Số candidate tìm được", "Kết quả": len(inspection.chunk_candidates)},
                {
                    "Thông tin": "Exact chunk match",
                    "Kết quả": chunk_stats.get("exact_match_count", 0),
                },
                {
                    "Thông tin": "Vector reuse",
                    "Kết quả": _plain_reuse_answer(inspection),
                },
            ],
        },
        {
            "title": "5. Embedding phần còn lại và dò near/version/conflict",
            "expanded": bool(inspection.embedded_result_chunks),
            "explain": (
                "Các chunk chưa reuse vector sẽ được embedding. Sau đó app dùng ANN để dò "
                "near duplicate, version candidate hoặc conflict candidate."
            ),
            "facts": [
                {"Thông tin": "Model embedding", "Kết quả": inspection.embedding_model},
                {"Thông tin": "Số chiều vector", "Kết quả": inspection.embedding_dimensions},
                {
                    "Thông tin": "Relation sau embedding",
                    "Kết quả": len(inspection.post_embedding_relations),
                },
                {
                    "Thông tin": "Pending relation cuối cùng",
                    "Kết quả": len(inspection.pending_relations),
                },
            ],
        },
        {
            "title": "6. Dừng trước khi lưu thật",
            "expanded": True,
            "explain": (
                "Đây là điểm app cố tình dừng. Trong production, bước tiếp theo mới renew lease, "
                "lấy advisory lock, kiểm tra race duplicate lần cuối, rồi lưu "
                "chunks/vectors/relations."
            ),
            "facts": [
                {
                    "Thông tin": "Chunk payload sẵn sàng",
                    "Kết quả": len(inspection.persisted_chunks),
                },
                {
                    "Thông tin": "Pending relation payload",
                    "Kết quả": len(inspection.pending_relations),
                },
                {"Thông tin": "Đã ghi database?", "Kết quả": "Chưa"},
            ],
        },
    ]


def _plain_reuse_answer(inspection: Inspection) -> str:
    chunk_plan = inspection.chunk_plan
    if chunk_plan is None:
        return "Không có kế hoạch reuse"
    stats = chunk_plan.to_stats()
    reused = int(stats["database_vector_reuse_count"]) + int(stats["batch_vector_reuse_count"])
    if reused <= 0:
        return "Không"
    return f"Có, {reused} chunk reuse vector"


def _plain_document_decision(
    inspection: Inspection,
    config: InspectorConfig,
) -> str:
    if config.quality_mode == "off":
        return "Bỏ qua vì quality mode off"
    if inspection.production_stops_at_duplicate:
        return "Auto alias và dừng trước lưu chunk/vector"
    if inspection.duplicate_match is not None and config.quality_mode == "shadow":
        return "Không alias; chỉ tạo exact_content pending relation"
    return "Không auto duplicate cấp tài liệu; đi tiếp"


def _render_layer_flow(inspection: Inspection, config: InspectorConfig) -> None:
    st.subheader("Kết quả theo từng lớp")
    st.caption(
        "Map 1-1 theo flow A-R của bạn. Các lớp O/P/Q/R là DB transaction "
        "thật trong production nên inspector chỉ hiện payload/decision và dừng trước ghi."
    )
    rows = _layer_rows(inspection, config)
    summary = [
        {key: value for key, value in row.items() if key != "details"}
        for row in rows
    ]
    st.dataframe(summary, use_container_width=True, hide_index=True)
    selected = st.selectbox(
        "Xem chi tiết layer",
        options=[str(row["node"]) for row in rows],
        format_func=lambda node: (
            f"{node} - "
            f"{next(row['layer'] for row in rows if row['node'] == node)}"
        ),
    )
    selected_row = next(row for row in rows if row["node"] == selected)
    st.markdown(f"**{selected_row['node']} - {selected_row['layer']}**")
    st.write(
        {
            "status": selected_row["status"],
            "branch_result": selected_row["branch_result"],
            "writes": selected_row["writes"],
            "next_or_stop": selected_row["next_or_stop"],
        }
    )
    st.json(selected_row["details"])


def _layer_rows(
    inspection: Inspection,
    config: InspectorConfig,
) -> list[dict[str, object]]:
    target = inspection.target
    parsed = target.prepared.parsed_document
    fingerprint = target.fingerprint
    chunk_plan = inspection.chunk_plan
    chunk_stats = chunk_plan.to_stats() if chunk_plan is not None else {}
    eligible = is_auto_identity_eligible(fingerprint)
    exact_reference_matches = _exact_reference_matches(inspection)
    production_duplicate_stop = (
        inspection.production_stops_at_duplicate
        and not config.continue_after_exact_suppression
    )
    debug_after_duplicate = (
        inspection.production_stops_at_duplicate
        and config.continue_after_exact_suppression
    )
    provider_chunk_count = _provider_embedding_chunk_count(inspection)
    ann_ran = (
        config.quality_mode != "off"
        and not production_duplicate_stop
        and inspection.duplicate_match is None
        and bool(inspection.embedded_result_chunks)
        and any(reference.embedded_chunks for reference in inspection.references)
    )

    rows = [
        _layer_row(
            "A",
            "Extraction tạo ParsedDocument",
            "đã chạy",
            "ParsedDocument đã sẵn sàng",
            (
                f"{target.prepared.parser_name} {target.prepared.parser_version}; "
                f"pages={len(parsed.pages)}, tables={len(parsed.tables)}"
            ),
            "không",
            "B",
            {
                "parser_name": target.prepared.parser_name,
                "parser_version": target.prepared.parser_version,
                "page_count": len(parsed.pages),
                "section_count": len(parsed.sections),
                "table_count": len(parsed.tables),
                "warning_count": len(parsed.warnings),
                "text_characters": len(parsed.text),
                "advanced_extraction_enabled": config.advanced_extraction_enabled,
            },
        ),
        _layer_row(
            "B",
            "Sanitize nội dung",
            "đã chạy",
            "Đã normalize text và dựng lại logical document",
            f"chars={len(parsed.text)}, warnings={len(parsed.warnings)}",
            "không",
            "C",
            {
                "text_checksum": hashlib.sha256(parsed.text.encode("utf-8")).hexdigest(),
                "content_markdown_checksum": hashlib.sha256(
                    (parsed.content_markdown or parsed.text).encode("utf-8")
                ).hexdigest(),
                "logical_document_available": parsed.logical_document is not None,
                "document_metadata_keys": sorted(str(key) for key in parsed.document_metadata),
            },
        ),
        _layer_row(
            "C",
            "Chunking",
            "đã chạy",
            "ParsedDocument đã được chia thành ChunkData",
            f"{len(target.prepared.chunks)} chunks",
            "không",
            "D",
            {
                "chunk_count": len(target.prepared.chunks),
                "chunk_size": config.chunk_size,
                "chunk_overlap": config.chunk_overlap,
                "chunking_strategy": config.chunking_strategy,
                "chunks": [_chunk_layer_detail(chunk) for chunk in target.prepared.chunks],
            },
        ),
        _layer_row(
            "D",
            "Tạo document fingerprint v2",
            "chỉ inspector" if config.quality_mode == "off" else "đã chạy",
            (
                "Production bỏ qua identity khi mode=off"
                if config.quality_mode == "off"
                else "Đã tạo document identity"
            ),
            fingerprint.strict_hash or "-",
            "không",
            "E",
            _fingerprint_row("target", target),
        ),
        _layer_row(
            "E",
            "Fingerprint đủ tin cậy để auto identity?",
            "bỏ qua" if config.quality_mode == "off" else "đã chạy",
            (
                "mode=off"
                if config.quality_mode == "off"
                else ("có" if eligible else "không")
            ),
            _eligibility_label(fingerprint),
            "không",
            "F" if eligible and config.quality_mode != "off" else "I",
            {
                "eligible": eligible,
                "identity_trusted": fingerprint.identity_trusted,
                "token_count": fingerprint.token_count,
                "character_count": fingerprint.character_count,
                "fallback_used": fingerprint.fallback_used,
                "unrepresented_visual_count": fingerprint.unrepresented_visual_count,
                "quality_mode": config.quality_mode,
            },
        ),
        _layer_row(
            "F",
            "Tìm normalized hash giống trong notebook",
            _status_if(config.quality_mode != "off" and eligible),
            f"{len(exact_reference_matches)} exact reference matches",
            ", ".join(item.asset.name for item in exact_reference_matches) or "không có",
            "không",
            "G",
            {
                "lookup_scope": {
                    "owner_id": config.owner_id,
                    "notebook_id": config.notebook_id,
                },
                "simulated_reference_count": len(inspection.references),
                "matched_references": [
                    {
                        "filename": item.asset.name,
                        "document_id": item.source.document_id,
                        "strict_hash": item.fingerprint.strict_hash,
                    }
                    for item in exact_reference_matches
                ],
            },
        ),
        _layer_row(
            "G",
            "Tìm thấy exact document?",
            _status_if(config.quality_mode != "off" and eligible),
            "có" if inspection.duplicate_match is not None else "không",
            _duplicate_label(inspection.duplicate_match),
            "không",
            "H" if inspection.production_stops_at_duplicate else "I",
            {
                "duplicate_found": inspection.duplicate_match is not None,
                "quality_mode": config.quality_mode,
                "canonical_document_id": (
                    str(inspection.duplicate_match.canonical_document_id)
                    if inspection.duplicate_match is not None
                    else None
                ),
                "matched_filename": (
                    inspection.duplicate_match.reference.asset.name
                    if inspection.duplicate_match is not None
                    else None
                ),
            },
        ),
        _layer_row(
            "H",
            "Auto alias vào canonical document",
            (
                "production sẽ chạy bước này"
                if inspection.production_stops_at_duplicate
                else "chưa tới"
            ),
            (
                "mode=on và có exact duplicate"
                if inspection.production_stops_at_duplicate
                else "không có exact duplicate ở mode=on"
            ),
            (
                str(inspection.duplicate_match.canonical_document_id)
                if inspection.duplicate_match is not None
                else "-"
            ),
            "inspector chặn ghi",
            "H1" if inspection.production_stops_at_duplicate else "-",
            {
                "production_rpc": "complete_duplicate_ingestion_job",
                "inspector_wrote_database": False,
                "canonical_document_id": (
                    str(inspection.duplicate_match.canonical_document_id)
                    if inspection.duplicate_match is not None
                    else None
                ),
            },
        ),
        _layer_row(
            "H1",
            "Không embedding và không lưu chunk mới",
            (
                "đã xử lý trong nhánh production"
                if inspection.production_stops_at_duplicate
                else "chưa tới"
            ),
            (
                "production dừng tại đây"
                if inspection.production_stops_at_duplicate
                else "ingestion tiếp tục bình thường"
            ),
            (
                "debug tiếp tục sau điểm dừng"
                if debug_after_duplicate
                else f"persisted_chunks={len(inspection.persisted_chunks)}"
            ),
            "không ghi chunk/vector",
            "-" if production_duplicate_stop else "I/J",
            {
                "production_stops_at_duplicate": inspection.production_stops_at_duplicate,
                "continue_after_exact_suppression": config.continue_after_exact_suppression,
                "embedded_chunks_in_production": 0
                if inspection.production_stops_at_duplicate
                else len(inspection.embedded_result_chunks),
                "persisted_chunks_in_production": 0
                if inspection.production_stops_at_duplicate
                else len(inspection.persisted_chunks),
            },
        ),
        _layer_row(
            "I",
            "Bỏ qua auto duplicate cấp tài liệu",
            "đã chạy" if not production_duplicate_stop else "chưa tới",
            _skip_document_duplicate_reason(inspection, config, eligible),
            "tiếp tục tới chunk gates" if not production_duplicate_stop else "-",
            "không",
            "J" if config.quality_mode != "off" and not production_duplicate_stop else "M",
            {
                "reason": _skip_document_duplicate_reason(inspection, config, eligible),
                "shadow_exact_relation_staged": (
                    inspection.duplicate_match is not None
                    and config.quality_mode == "shadow"
                ),
            },
        ),
        _layer_row(
            "J",
            "Tạo fingerprint cho tất cả chunk",
            _chunk_quality_status(inspection, config),
            f"{len(inspection.probes)} probes",
            _debug_only_suffix("probes ready", debug_after_duplicate),
            "không",
            "K",
            {
                "probe_count": len(inspection.probes),
                "fuzzy_probe_count": sum(
                    probe.include_fuzzy_candidates for probe in inspection.probes
                ),
                "probes": [_probe_row(probe) for probe in inspection.probes],
            },
        ),
        _layer_row(
            "K",
            "Tìm exact/SimHash-LSH chunk candidates",
            _chunk_quality_status(inspection, config),
            f"{len(inspection.chunk_candidates)} candidates",
            _debug_only_suffix(_chunk_candidate_summary(inspection), debug_after_duplicate),
            "không",
            "L",
            {
                "candidate_count": len(inspection.chunk_candidates),
                "candidates_per_probe": config.candidates_per_probe,
                "candidates": [
                    _candidate_row(candidate, inspection.probes)
                    for candidate in inspection.chunk_candidates
                ],
            },
        ),
        _layer_row(
            "L",
            "Tái sử dụng embedding exact chunk nếu an toàn",
            _status_if(chunk_plan is not None),
            _reuse_summary(chunk_stats),
            _debug_only_suffix(_reuse_summary(chunk_stats), debug_after_duplicate),
            "không",
            "M",
            {
                "chunk_plan_stats": chunk_stats,
                "annotations": _chunk_annotation_rows(inspection),
                "enable_exact_reuse": config.quality_mode == "on",
            },
        ),
        _layer_row(
            "M",
            "Embedding các chunk còn lại",
            "đã chạy" if inspection.embedded_result_chunks else "chưa tới",
            f"{provider_chunk_count} provider calls planned",
            (
                f"embedded={len(inspection.embedded_result_chunks)}, "
                f"dim={inspection.embedding_dimensions}"
            ),
            "không",
            "N",
            {
                "embedding_model": inspection.embedding_model,
                "embedding_dimensions": inspection.embedding_dimensions,
                "total_chunks": len(target.prepared.chunks),
                "provider_chunk_count": provider_chunk_count,
                "reused_chunk_count": max(
                    0,
                    len(target.prepared.chunks) - provider_chunk_count,
                ),
            },
        ),
        _layer_row(
            "N",
            "ANN kiểm tra near duplicate/version/conflict",
            _ann_status(inspection, config, ann_ran),
            _ann_branch_result(inspection, config, ann_ran),
            f"{len(inspection.post_embedding_relations)} relations",
            "không",
            "O",
            {
                "ann_ran": ann_ran,
                "detector_version": DETECTOR_VERSION,
                "reference_vector_count": sum(
                    len(reference.embedded_chunks) for reference in inspection.references
                ),
                "post_embedding_relations": [
                    relation.to_payload()
                    for relation in inspection.post_embedding_relations
                ],
            },
        ),
        _layer_row(
            "O",
            "Renew lease và bắt đầu transaction completion",
            _transaction_boundary_status(inspection, config),
            _transaction_branch_result(inspection, config),
            "inspector không thực thi",
            "inspector chặn ghi",
            "P",
            {
                "production_operation": "renew_ingestion_job_lease before completion RPC",
                "inspector_wrote_database": False,
                "would_submit_chunks": len(inspection.persisted_chunks),
                "would_submit_relations": len(inspection.pending_relations),
            },
        ),
        _layer_row(
            "P",
            "Advisory lock theo normalized document hash",
            _transaction_boundary_status(inspection, config),
            "lock chỉ có trong database, không mô phỏng",
            fingerprint.strict_hash or "-",
            "inspector chặn ghi",
            "Q",
            {
                "production_operation": "advisory lock inside complete_ingestion_job",
                "lock_key_source": "normalized document hash",
                "normalized_content_hash": fingerprint.strict_hash or None,
                "inspector_wrote_database": False,
            },
        ),
        _layer_row(
            "Q",
            "Document giống vừa được worker khác commit?",
            _transaction_boundary_status(inspection, config),
            "chỉ biết trong DB transaction",
            "dry-run giả định chưa có commit đồng thời",
            "inspector chặn ghi",
            "H or R",
            {
                "production_operation": "transactional recheck for exact identity race",
                "possible_yes_result": "duplicate_suppressed / auto alias",
                "possible_no_result": "lưu chunks, vectors, pending relations",
                "dry_run_result": "không đánh giá với live database",
            },
        ),
        _layer_row(
            "R",
            "Lưu chunks, vectors và pending relations",
            _save_boundary_status(inspection, config),
            _save_boundary_result(inspection, config),
            (
                f"chunks={len(inspection.persisted_chunks)}, "
                f"relations={len(inspection.pending_relations)}"
            ),
            "inspector chặn ghi",
            "dừng",
            {
                "inspector_wrote_database": False,
                "chunks_payload_count": len(inspection.persisted_chunks),
                "pending_relations_payload_count": len(inspection.pending_relations),
                "completion_payload_sketch": _completion_payload_sketch(inspection),
            },
        ),
    ]
    return rows


def _layer_row(
    node: str,
    layer: str,
    status: str,
    branch_result: str,
    key_output: str,
    writes: str,
    next_or_stop: str,
    details: Mapping[str, object],
) -> dict[str, object]:
    return {
        "node": node,
        "layer": layer,
        "status": status,
        "branch_result": branch_result,
        "key_output": key_output,
        "writes": writes,
        "next_or_stop": next_or_stop,
        "details": _json_safe_mapping(details),
    }


def _render_action_flow(inspection: Inspection, config: InspectorConfig) -> None:
    st.subheader("Tóm tắt hành động sau extraction")
    rows: list[dict[str, object]] = []
    rows.append(
        {
            "step": 1,
            "stage": "extraction_success",
            "production_action": "dùng ParsedDocument và extraction artifacts",
            "status": "đã chạy",
            "writes": "không",
            "inspector_output": (
                f"{inspection.target.prepared.parser_name} "
                f"{inspection.target.prepared.parser_version}"
            ),
        }
    )
    if config.quality_mode == "off":
        rows.append(_flow_row(2, "document_identity", "bỏ qua vì quality mode đang off"))
        rows.append(_flow_row(3, "content_duplicate_gate", "bỏ qua vì quality mode đang off"))
        rows.append(_flow_row(4, "chunk_preembedding_gate", "bỏ qua vì quality mode đang off"))
    else:
        rows.append(
            {
                "step": 2,
                "stage": "document_identity",
                "production_action": "tạo format-neutral document fingerprint",
                "status": "đã chạy",
                "writes": "không",
                "inspector_output": _eligibility_label(inspection.target.fingerprint),
            }
        )
        rows.append(
            {
                "step": 3,
                "stage": "content_duplicate_gate",
                "production_action": _document_gate_action(inspection, config),
                "status": "đã chạy",
                "writes": "không",
                "inspector_output": _duplicate_label(inspection.duplicate_match),
            }
        )
        rows.append(
            {
                "step": 4,
                "stage": "chunk_preembedding_gate",
                "production_action": (
                    "tạo probes, lookup exact/LSH candidates, phân loại relation, "
                    "lập kế hoạch reuse exact vector"
                ),
                "status": "đã chạy" if inspection.probes else "chưa tới",
                "writes": "không",
                "inspector_output": _chunk_plan_label(inspection.chunk_plan),
            }
        )
    rows.append(
        {
            "step": 5,
            "stage": "embed_dry_run",
            "production_action": "embedding các chunk chưa có vector reuse an toàn",
            "status": "đã chạy" if inspection.embedded_result_chunks else "chưa tới",
            "writes": "không",
            "inspector_output": (
                f"{inspection.embedding_model}, dim={inspection.embedding_dimensions}"
                if inspection.embedding_dimensions
                else ""
            ),
        }
    )
    rows.append(
        {
            "step": 6,
            "stage": "post_embedding_relations",
            "production_action": "probe vector index và tạo relation candidates",
            "status": "đã chạy" if inspection.post_embedding_relations else "không có",
            "writes": "không",
            "inspector_output": len(inspection.post_embedding_relations),
        }
    )
    rows.append(
        {
            "step": 7,
            "stage": "pre_persist_boundary",
            "production_action": (
                "bước thật tiếp theo sẽ gọi complete_ingestion_job với chunks, "
                "vectors và pending relations"
            ),
            "status": "dừng tại đây",
            "writes": "inspector chặn ghi",
            "inspector_output": (
                f"{len(inspection.persisted_chunks)} chunks, "
                f"{len(inspection.pending_relations)} relations"
            ),
        }
    )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_extraction(inspection: Inspection) -> None:
    target = inspection.target
    parsed = target.prepared.parsed_document
    artifacts = target.prepared.extraction_artifacts
    st.subheader("Kết quả extraction")
    cols = st.columns(4)
    cols[0].metric("Parser", target.prepared.parser_name or "-")
    cols[1].metric("Trang", len(parsed.pages))
    cols[2].metric("Bảng", len(parsed.tables))
    cols[3].metric("Cảnh báo", len(parsed.warnings))
    _render_extraction_artifacts(artifacts)
    if parsed.warnings:
        with st.expander("Cảnh báo", expanded=True):
            for warning in parsed.warnings:
                st.warning(str(warning))
    st.text_area(
        "Text đã trích xuất",
        value=parsed.text,
        height=360,
        disabled=True,
    )


def _render_document_gate(inspection: Inspection, config: InspectorConfig) -> None:
    st.subheader("Cổng duplicate cấp tài liệu")
    target_row = _fingerprint_row("target", inspection.target)
    reference_rows = [_fingerprint_row("reference", item) for item in inspection.references]
    st.dataframe([target_row, *reference_rows], use_container_width=True, hide_index=True)
    if config.quality_mode == "off":
        st.info("Quality mode off: worker sẽ không tạo hoặc persist document identity.")
        return
    if inspection.duplicate_match is None:
        st.success("Không tìm thấy strict content duplicate trong corpus tham chiếu.")
        return
    match = inspection.duplicate_match
    st.warning(
        "Strict document identity trùng với reference "
        f"`{match.reference.asset.name}` ({match.canonical_document_id})."
    )
    st.write(
        {
            "mode_on_action": "complete_duplicate_ingestion_job và dừng trước chunks/vectors",
            "mode_shadow_action": "tiếp tục ingest và stage exact_content pending relation",
            "current_mode": config.quality_mode,
        }
    )


def _render_chunk_gate(inspection: Inspection, config: InspectorConfig) -> None:
    st.subheader("Cổng chunk pre-embedding")
    if config.quality_mode == "off":
        st.info("Quality mode off: bỏ qua chunk pre-embedding dedup.")
        return
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        st.info("Production đã dừng ở exact duplicate cấp tài liệu trước chunk dedup.")
        return
    st.caption(f"Detector version: `{CHUNK_PREEMBEDDING_DETECTOR_VERSION}`")
    st.write(_chunk_stats(inspection.chunk_plan))
    probe_rows = [_probe_row(probe) for probe in inspection.probes]
    with st.expander("Probes gửi vào candidate lookup", expanded=True):
        st.dataframe(probe_rows, use_container_width=True, hide_index=True)
    with st.expander("Candidates trả về từ corpus in-memory", expanded=True):
        rows = [
            _candidate_row(candidate, inspection.probes)
            for candidate in inspection.chunk_candidates
        ]
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("Không tìm thấy chunk candidate.")
    with st.expander("Chunk annotations dùng bởi embedding pipeline", expanded=True):
        rows = _chunk_annotation_rows(inspection)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("Không có dedup annotation cấp chunk.")


def _render_embedding_plan(inspection: Inspection, config: InspectorConfig) -> None:
    st.subheader("Kế hoạch embedding và relation")
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        st.info("Nhánh production chưa đi tới embedding.")
        return
    rows = []
    chunk_plan = inspection.chunk_plan
    precomputed = getattr(chunk_plan, "precomputed_vectors", {}) if chunk_plan else {}
    batch_reuse = getattr(chunk_plan, "reuse_from_chunk_index", {}) if chunk_plan else {}
    for chunk in inspection.target.prepared.chunks:
        if chunk.chunk_index in precomputed:
            action = "reuse exact vector đã persist"
        elif chunk.chunk_index in batch_reuse:
            action = f"reuse batch vector từ chunk {batch_reuse[chunk.chunk_index]}"
        else:
            action = "gọi embedding provider"
        rows.append(
            {
                "chunk_index": chunk.chunk_index,
                "action": action,
                "page": chunk.page_number,
                "tokens_estimate": len(chunk.text.split()),
                "embedding_text_checksum": chunk.checksum,
                "preview": _preview(chunk.embedding_text or chunk.text, 140),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.write(
        {
            "embedding_model": inspection.embedding_model,
            "embedding_dimensions": inspection.embedding_dimensions,
            "post_embedding_detector": DETECTOR_VERSION,
        }
    )
    relation_rows = [_relation_row(item) for item in inspection.post_embedding_relations]
    if relation_rows:
        st.dataframe(relation_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Không có post-embedding relation candidate.")


def _render_pre_persist_payload(inspection: Inspection) -> None:
    st.subheader("Payload sẽ được lưu ở bước tiếp theo")
    st.caption("Inspector dừng trước khi gửi payload này vào complete_ingestion_job.")
    cols = st.columns(3)
    cols[0].metric("Chunks payload", len(inspection.persisted_chunks))
    cols[1].metric("Pending relations payload", len(inspection.pending_relations))
    cols[2].metric(
        "Document fingerprint",
        "có" if inspection.target.fingerprint.strict_hash else "không",
    )
    with st.expander("Tóm tắt chunks payload", expanded=True):
        rows = [_persisted_chunk_row(chunk) for chunk in inspection.persisted_chunks]
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("Không có chunk payload vì nhánh production chưa tới persist boundary.")
    with st.expander("Pending relations payload", expanded=True):
        rows = [_relation_row(item) for item in inspection.pending_relations]
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("Không có pending relation payload.")
    with st.expander("Phác thảo input cho Completion RPC"):
        st.json(_completion_payload_sketch(inspection))


def _render_report_json(inspection: Inspection, config: InspectorConfig) -> None:
    report = _inspection_report(inspection, config)
    st.download_button(
        "Tải JSON report",
        data=json.dumps(report, ensure_ascii=False, indent=2),
        file_name="prepersist_dedup_report.json",
        mime="application/json",
    )
    st.json(report)


def _render_extraction_artifacts(artifacts: object | None) -> None:
    if artifacts is None:
        st.info("Advanced Extraction disabled; parser output was sanitized and chunked.")
        return
    quality_decision = getattr(artifacts, "quality_decision", None)
    quality_report = getattr(artifacts, "quality_report", None)
    rows = [
        {
            "phase": "quality_gate",
            "status": "index_allowed"
            if bool(getattr(artifacts, "index_allowed", False))
            else "blocked",
            "summary": _safe_to_dict(quality_decision),
        },
        {
            "phase": "canonical_ir",
            "status": "đã tạo" if getattr(artifacts, "canonical_ir", None) else "bỏ qua",
            "summary": _artifact_summary(getattr(artifacts, "canonical_ir_artifact", None)),
        },
        {
            "phase": "layout",
            "status": _artifact_status(getattr(artifacts, "phase3_layout", None)),
            "summary": _artifact_summary(getattr(artifacts, "phase3_layout", None)),
        },
        {
            "phase": "tables",
            "status": _artifact_status(getattr(artifacts, "phase4_tables", None)),
            "summary": _artifact_summary(getattr(artifacts, "phase4_tables", None)),
        },
        {
            "phase": "verification",
            "status": _artifact_status(getattr(artifacts, "phase5_verification", None)),
            "summary": _artifact_summary(getattr(artifacts, "phase5_verification", None)),
        },
        {
            "phase": "multimodal",
            "status": _artifact_status(getattr(artifacts, "phase6_multimodal", None)),
            "summary": _artifact_summary(getattr(artifacts, "phase6_multimodal", None)),
        },
        {
            "phase": "quality_report",
            "status": "có" if quality_report is not None else "thiếu",
            "summary": _safe_to_dict(quality_report),
        },
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _flow_row(step: int, stage: str, action: str) -> dict[str, object]:
    return {
        "step": step,
        "stage": stage,
        "production_action": action,
        "status": "bỏ qua",
        "writes": "không",
        "inspector_output": "",
    }


def _exact_reference_matches(inspection: Inspection) -> tuple[PreparedDocument, ...]:
    fingerprint = inspection.target.fingerprint
    return tuple(
        reference
        for reference in inspection.references
        if reference.fingerprint.strict_hash == fingerprint.strict_hash
        and reference.fingerprint.normalization_version == fingerprint.normalization_version
    )


def _status_if(condition: bool) -> str:
    return "đã chạy" if condition else "chưa tới"


def _chunk_layer_detail(chunk: Any) -> dict[str, object]:
    return {
        "chunk_index": chunk.chunk_index,
        "chunk_id": chunk.chunk_id,
        "page_number": chunk.page_number,
        "section_title": chunk.section_title,
        "text_checksum": chunk.checksum,
        "token_estimate": len(chunk.text.split()),
        "offset_start": chunk.offset_start,
        "offset_end": chunk.offset_end,
        "source_block_ids": list(chunk.source_block_ids),
        "preview": _preview(chunk.text, 160),
    }


def _skip_document_duplicate_reason(
    inspection: Inspection,
    config: InspectorConfig,
    eligible: bool,
) -> str:
    if config.quality_mode == "off":
        return "quality mode off"
    if not eligible:
        return "fingerprint không đủ điều kiện auto identity"
    if inspection.duplicate_match is not None and config.quality_mode == "shadow":
        return "tìm thấy exact document nhưng shadow mode vẫn tiếp tục ingest"
    if inspection.duplicate_match is None:
        return "không tìm thấy exact document"
    if config.continue_after_exact_suppression:
        return "tiếp tục debug sau nhánh production alias"
    return "nhánh production alias"


def _chunk_quality_status(
    inspection: Inspection,
    config: InspectorConfig,
) -> str:
    if config.quality_mode == "off":
        return "bỏ qua"
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        return "chưa tới"
    if inspection.production_stops_at_duplicate and config.continue_after_exact_suppression:
        return "chỉ debug"
    return "đã chạy" if inspection.probes else "chưa tới"


def _debug_only_suffix(value: str, debug_after_duplicate: bool) -> str:
    if not debug_after_duplicate:
        return value
    return f"{value} (chỉ debug; production đã dừng tại H1)"


def _chunk_candidate_summary(inspection: Inspection) -> str:
    exact_count = 0
    fuzzy_count = 0
    probes_by_index = {probe.chunk_index: probe for probe in inspection.probes}
    for candidate in inspection.chunk_candidates:
        probe = probes_by_index.get(candidate.source_chunk_index)
        if probe is None:
            continue
        strict_match = (
            candidate.normalized_content_hash == probe.fingerprint.strict_hash
            and candidate.normalization_version == probe.fingerprint.normalization_version
        )
        if strict_match:
            exact_count += 1
        else:
            fuzzy_count += 1
    return f"exact_candidates={exact_count}, fuzzy_candidates={fuzzy_count}"


def _reuse_summary(chunk_stats: Mapping[str, object]) -> str:
    database_reuse = int(chunk_stats.get("database_vector_reuse_count") or 0)
    batch_reuse = int(chunk_stats.get("batch_vector_reuse_count") or 0)
    exact_matches = int(chunk_stats.get("exact_match_count") or 0)
    return (
        f"exact_matches={exact_matches}, "
        f"database_reuse={database_reuse}, batch_reuse={batch_reuse}"
    )


def _provider_embedding_chunk_count(inspection: Inspection) -> int:
    if not inspection.embedded_result_chunks:
        return 0
    chunk_plan = inspection.chunk_plan
    if chunk_plan is None:
        return len(inspection.target.prepared.chunks)
    precomputed = getattr(chunk_plan, "precomputed_vectors", {})
    batch_reuse = getattr(chunk_plan, "reuse_from_chunk_index", {})
    return max(
        0,
        len(inspection.target.prepared.chunks) - len(precomputed) - len(batch_reuse),
    )


def _ann_status(
    inspection: Inspection,
    config: InspectorConfig,
    ann_ran: bool,
) -> str:
    if config.quality_mode == "off":
        return "bỏ qua"
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        return "chưa tới"
    if inspection.duplicate_match is not None:
        return "bỏ qua"
    if ann_ran:
        return "đã chạy"
    if not inspection.references:
        return "bỏ qua"
    return "chưa tới"


def _ann_branch_result(
    inspection: Inspection,
    config: InspectorConfig,
    ann_ran: bool,
) -> str:
    if config.quality_mode == "off":
        return "quality mode off"
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        return "production đã dừng trước embedding"
    if inspection.duplicate_match is not None:
        return "exact duplicate cấp tài liệu đã được quyết định"
    if not inspection.references:
        return "chưa upload corpus vector tham chiếu"
    if ann_ran:
        return f"{len(inspection.post_embedding_relations)} relation candidates"
    return "chưa đánh giá"


def _transaction_boundary_status(
    inspection: Inspection,
    config: InspectorConfig,
) -> str:
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        return "chưa tới"
    if inspection.production_stops_at_duplicate and config.continue_after_exact_suppression:
        return "chỉ debug"
    if inspection.persisted_chunks:
        return "bước production tiếp theo"
    return "chưa tới"


def _transaction_branch_result(
    inspection: Inspection,
    config: InspectorConfig,
) -> str:
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        return "production dùng nhánh duplicate completion"
    if inspection.production_stops_at_duplicate and config.continue_after_exact_suppression:
        return "chỉ có debug payload; production đã dừng tại H"
    if inspection.persisted_chunks:
        return "sẽ renew lease rồi gọi complete_ingestion_job"
    return "không có completion payload"


def _save_boundary_status(
    inspection: Inspection,
    config: InspectorConfig,
) -> str:
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        return "chưa tới"
    if inspection.production_stops_at_duplicate and config.continue_after_exact_suppression:
        return "chỉ debug"
    if inspection.persisted_chunks:
        return "inspector chặn ghi"
    return "chưa tới"


def _save_boundary_result(
    inspection: Inspection,
    config: InspectorConfig,
) -> str:
    if inspection.production_stops_at_duplicate and not config.continue_after_exact_suppression:
        return "không lưu chunks/vectors vì đã alias duplicate"
    if inspection.production_stops_at_duplicate and config.continue_after_exact_suppression:
        return "production không lưu; payload chỉ để debug"
    if inspection.persisted_chunks:
        return "payload đã sẵn sàng; inspector dừng trước khi ghi"
    return "không có payload"


def _document_gate_action(inspection: Inspection, config: InspectorConfig) -> str:
    if inspection.duplicate_match is None:
        return "không tìm thấy exact content duplicate; tiếp tục"
    if config.quality_mode == "on":
        return "complete duplicate alias và dừng trước chunks/vectors"
    return "stage exact_content relation; tiếp tục nhưng không auto alias"


def _chunk_plan_label(chunk_plan: object | None) -> str:
    if chunk_plan is None:
        return ""
    stats = chunk_plan.to_stats()
    return (
        f"exact={stats['exact_match_count']}, "
        f"near={stats['near_duplicate_count']}, "
        f"version={stats['version_candidate_count']}, "
        f"conflict={stats['conflict_candidate_count']}, "
        f"reuse={stats['database_vector_reuse_count'] + stats['batch_vector_reuse_count']}"
    )


def _chunk_stats(chunk_plan: object | None) -> dict[str, int | str]:
    if chunk_plan is None:
        return {"status": "chưa có"}
    return chunk_plan.to_stats()


def _fingerprint_row(label: str, document: PreparedDocument) -> dict[str, object]:
    fingerprint = document.fingerprint
    return {
        "role": label,
        "filename": document.asset.name,
        "document_id": document.source.document_id,
        "raw_sha256": document.asset.sha256,
        "normalization_version": fingerprint.normalization_version,
        "strict_hash": fingerprint.strict_hash,
        "loose_signature": fingerprint.loose_signature,
        "tokens": fingerprint.token_count,
        "chars": fingerprint.character_count,
        "eligible_for_auto_exact": is_auto_identity_eligible(fingerprint),
        "identity_trusted": fingerprint.identity_trusted,
        "projection_source": fingerprint.projection_source,
        "table_count": fingerprint.table_count,
        "fallback_used": fingerprint.fallback_used,
        "unrepresented_visual_count": fingerprint.unrepresented_visual_count,
    }


def _probe_row(probe: ChunkDedupProbe) -> dict[str, object]:
    return {
        "chunk_index": probe.chunk_index,
        "chunk_id": probe.chunk_id,
        "include_fuzzy": probe.include_fuzzy_candidates,
        "strict_hash": probe.fingerprint.strict_hash,
        "loose_signature": probe.fingerprint.loose_signature,
        "lsh_bands": " ".join(simhash_lsh_bands(probe.fingerprint.loose_signature)),
        "embedding_text_checksum": probe.embedding_text_checksum,
        "preview": _preview(probe.canonical_text, 160),
    }


def _candidate_row(
    candidate: ChunkDedupCandidate,
    probes: Sequence[ChunkDedupProbe],
) -> dict[str, object]:
    probe = next(
        item for item in probes if item.chunk_index == candidate.source_chunk_index
    )
    strict_match = (
        candidate.normalized_content_hash == probe.fingerprint.strict_hash
        and candidate.normalization_version == probe.fingerprint.normalization_version
    )
    distance = simhash_hamming_distance(
        probe.fingerprint.loose_signature,
        candidate.loose_content_signature,
    )
    return {
        "source_chunk_index": candidate.source_chunk_index,
        "target_document_id": str(candidate.target_document_id),
        "target_chunk_index": candidate.target_chunk_index,
        "target_chunk_id": candidate.target_chunk_id,
        "strict_match": strict_match,
        "lsh_band_matches": candidate.lsh_band_matches,
        "simhash_distance": distance,
        "embedding_model": candidate.embedding_model,
        "embedding_available": bool(candidate.embedding),
        "preview": _preview(candidate.canonical_text, 160),
    }


def _chunk_annotation_rows(inspection: Inspection) -> list[dict[str, object]]:
    chunk_plan = inspection.chunk_plan
    if chunk_plan is None:
        return []
    annotations = getattr(chunk_plan, "metadata_by_chunk_index", {})
    rows: list[dict[str, object]] = []
    for chunk_index, annotation in sorted(annotations.items()):
        rows.append(
            {
                "chunk_index": chunk_index,
                "action": annotation.get("action"),
                "relation_type": annotation.get("relation_type"),
                "confidence": annotation.get("confidence"),
                "embedding_reused": annotation.get("embedding_reused"),
                "match_source": annotation.get("match_source"),
                "target_document_id": annotation.get("target_document_id"),
                "target_chunk_index": annotation.get("target_chunk_index"),
                "reason_codes": ", ".join(
                    str(item) for item in annotation.get("reason_codes", [])
                ),
            }
        )
    return rows


def _relation_row(relation: QualityRelationCandidate) -> dict[str, object]:
    selected_pair = relation.signals.get("selected_chunk_pair")
    return {
        "target_document_id": str(relation.target_document_id),
        "relation_type": relation.relation_type.value,
        "confidence": round(relation.confidence, 6),
        "reason": relation.reason,
        "detector_version": relation.detector_version,
        "coverage": relation.signals.get("document_probe_coverage"),
        "matched_probe_count": relation.signals.get("matched_probe_count"),
        "selected_chunk_pair": selected_pair,
    }


def _persisted_chunk_row(chunk: PersistedChunk) -> dict[str, object]:
    metadata = chunk.metadata
    return {
        "id": str(chunk.id),
        "chunk_index": chunk.chunk_index,
        "token_count": chunk.token_count,
        "embedding_dimensions": len(chunk.embedding),
        "normalized_content_hash": metadata.get("normalized_content_hash"),
        "exact_duplicate_group_id": metadata.get("exact_duplicate_group_id"),
        "pre_embedding_action": (
            metadata.get("pre_embedding_quality", {}).get("action")
            if isinstance(metadata.get("pre_embedding_quality"), Mapping)
            else None
        ),
        "content_preview": _preview(chunk.content, 180),
    }


def _completion_payload_sketch(inspection: Inspection) -> dict[str, object]:
    fingerprint = inspection.target.fingerprint
    return {
        "p_embedding_model": inspection.embedding_model,
        "p_embedding_dimensions": inspection.embedding_dimensions,
        "p_chunks_count": len(inspection.persisted_chunks),
        "p_relations_count": len(inspection.pending_relations),
        "p_normalized_content_hash": fingerprint.strict_hash or None,
        "p_normalization_version": fingerprint.normalization_version or None,
        "p_loose_content_signature": fingerprint.loose_signature or None,
        "p_quality_metadata": fingerprint.to_metadata(),
        "p_relations": [relation.to_payload() for relation in inspection.pending_relations],
    }


def _inspection_report(
    inspection: Inspection,
    config: InspectorConfig,
) -> dict[str, object]:
    chunk_plan = inspection.chunk_plan
    report = {
        "schema": "prepersist-dedup-inspection-v1",
        "config": {
            "quality_mode": config.quality_mode,
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "chunking_strategy": config.chunking_strategy,
            "max_probe_chunks": config.max_probe_chunks,
            "candidates_per_probe": config.candidates_per_probe,
            "advanced_extraction_enabled": config.advanced_extraction_enabled,
            "extraction_quality_mode": config.extraction_quality_mode,
            "ocr_enabled": config.ocr_enabled,
            "embedding_provider": config.embedding_provider,
        },
        "target": _fingerprint_row("target", inspection.target),
        "references": [_fingerprint_row("reference", item) for item in inspection.references],
        "production_stops_at_duplicate": inspection.production_stops_at_duplicate,
        "duplicate_match": (
            {
                "filename": inspection.duplicate_match.reference.asset.name,
                "canonical_document_id": str(inspection.duplicate_match.canonical_document_id),
            }
            if inspection.duplicate_match is not None
            else None
        ),
        "chunk_plan_stats": chunk_plan.to_stats() if chunk_plan is not None else None,
        "chunk_annotations": _chunk_annotation_rows(inspection),
        "post_embedding_relations": [
            relation.to_payload() for relation in inspection.post_embedding_relations
        ],
        "pending_relations": [
            relation.to_payload() for relation in inspection.pending_relations
        ],
        "pre_persist_payload": _completion_payload_sketch(inspection),
        "layer_flow": _layer_rows(inspection, config),
    }
    return _json_safe_mapping(report)


def _guess_mime(filename: str, uploaded_mime: str) -> str:
    clean_uploaded = uploaded_mime.split(";")[0].strip().lower()
    if clean_uploaded and clean_uploaded != "application/octet-stream":
        return clean_uploaded
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _metadata_str(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    return str(value)


def _lsh_band_match_count(left_signature: str, right_signature: str) -> int:
    left_bands = simhash_lsh_bands(left_signature)
    right_bands = simhash_lsh_bands(right_signature)
    return sum(left == right for left, right in zip(left_bands, right_bands, strict=True))


def _eligibility_label(fingerprint: DocumentFingerprint) -> str:
    return "đủ điều kiện auto" if is_auto_identity_eligible(fingerprint) else "chỉ review"


def _duplicate_label(match: DocumentDuplicateMatch | None) -> str:
    if match is None:
        return "không trùng"
    return f"trùng {match.reference.asset.name}"


def _artifact_status(value: object | None) -> str:
    return "đã tạo" if value is not None else "bỏ qua"


def _artifact_summary(value: object | None) -> dict[str, object]:
    if value is None:
        return {}
    summary: dict[str, object] = {}
    for name in (
        "mode",
        "config_checksum",
        "issue_count",
        "table_count",
        "case_count",
        "request_count",
        "candidate_count",
        "asset_count",
    ):
        if hasattr(value, name):
            summary[name] = _json_safe(getattr(value, name))
    metadata = getattr(value, "metadata", None)
    if callable(metadata):
        with suppress(Exception):
            summary.update(_json_safe_mapping(metadata(artifact_reference=None)))
    return summary


def _safe_to_dict(value: object | None) -> dict[str, object]:
    if value is None:
        return {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            data = to_dict()
            if isinstance(data, Mapping):
                return _json_safe_mapping(data)
        except Exception:
            return {"repr": repr(value)}
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    return {"repr": repr(value)}


def _preview(value: str, limit: int) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _json_safe_mapping(value: Mapping[str, Any]) -> dict[str, object]:
    normalized = _json_safe(value)
    if not isinstance(normalized, dict):
        raise TypeError("Expected JSON object")
    return normalized


def _json_safe(value: Any) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        return _json_safe(to_payload())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict())
    return str(value)


if __name__ == "__main__":
    main()
