from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.pipeline.indexing.ports.vector_index import VectorSearchHit
from app.pipeline.shared.errors import AppError

_FILTERABLE_RETRIEVAL_FIELDS = (
    "document_type",
    "content_kind",
    "project_id",
    "project_code",
    "year",
    "data_period",
    "effective_status",
)


class InMemoryVectorIndex:
    completion_is_transactional = False

    def __init__(self) -> None:
        self._chunks_by_id: dict[str, EmbeddedChunk] = {}

    def is_ready(self) -> bool:
        return True

    def upsert_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
        for chunk in chunks:
            self._chunks_by_id[chunk.id] = chunk

    def delete_document_vectors(self, document_id: str) -> None:
        self._chunks_by_id = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks_by_id.items()
            if chunk.document_id != document_id
        }

    def delete_document_version_vectors(
        self,
        document_id: str,
        document_version: int,
    ) -> None:
        self._chunks_by_id = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks_by_id.items()
            if not (chunk.document_id == document_id and chunk.document_version == document_version)
        }

    def delete_document_generation_vectors(
        self,
        document_id: str,
        generation: str,
    ) -> None:
        self._chunks_by_id = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks_by_id.items()
            if not (
                chunk.document_id == document_id
                and chunk.metadata.get("ingestion_generation") == generation
            )
        }

    def finalize_document_generation(
        self,
        document_id: str,
        document_version: int,
        generation: str,
    ) -> None:
        self._chunks_by_id = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks_by_id.items()
            if not (
                chunk.document_id == document_id
                and chunk.document_version == document_version
                and chunk.metadata.get("ingestion_generation") != generation
            )
        }

    def list_chunks(self) -> list[EmbeddedChunk]:
        return list(self._chunks_by_id.values())

    def query(
        self,
        embedding: Sequence[float],
        *,
        owner_id: str,
        document_ids: Sequence[str] | None,
        limit: int,
        tenant_id: str | None = None,
        metadata_filters: Mapping[str, str | int] | None = None,
    ) -> list[VectorSearchHit]:
        if document_ids is not None and not document_ids:
            return []
        allowed = set(document_ids) if document_ids is not None else None
        scored: list[tuple[float, EmbeddedChunk]] = []
        for chunk in self._chunks_by_id.values():
            if chunk.owner_id != owner_id:
                continue
            if tenant_id is not None and chunk.tenant_id != tenant_id:
                continue
            if allowed is not None and chunk.document_id not in allowed:
                continue
            if not _matches_retrieval_metadata(chunk.retrieval_metadata, metadata_filters):
                continue
            similarity = _cosine_similarity(embedding, chunk.embedding)
            scored.append((similarity, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            VectorSearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                score=score,
                text=chunk.text,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                document_version=chunk.document_version,
                checksum=chunk.checksum,
                chunk_index=chunk.chunk_index,
                normalized_content_hash=str(chunk.metadata.get("normalized_content_hash") or "")
                or None,
                exact_duplicate_group_id=str(chunk.metadata.get("exact_duplicate_group_id") or "")
                or None,
                metadata={
                    **dict(chunk.metadata),
                    "retrieval_metadata": dict(chunk.retrieval_metadata),
                },
            )
            for score, chunk in scored[:limit]
        ]


class QdrantVectorIndex:
    completion_is_transactional = False

    FILTER_INDEX_SCHEMAS = {
        "owner_id": "keyword",
        "tenant_id": "keyword",
        "document_id": "keyword",
        "document_version": "integer",
        "embedding_model": "keyword",
        "ingestion_generation": "keyword",
        "checksum": "keyword",
        "normalized_content_hash": "keyword",
        "exact_duplicate_group_id": "keyword",
        "retrieval_metadata.document_type": "keyword",
        "retrieval_metadata.content_kind": "keyword",
        "retrieval_metadata.project_id": "keyword",
        "retrieval_metadata.project_code": "keyword",
        "retrieval_metadata.year": "integer",
        "retrieval_metadata.data_period": "keyword",
        "retrieval_metadata.effective_status": "keyword",
    }

    def __init__(
        self,
        client: Any,
        collection_name: str,
        *,
        max_retries: int = 2,
        retry_backoff_ms: int = 100,
        upsert_batch_size: int = 64,
    ) -> None:
        if not collection_name:
            raise ValueError("Qdrant collection name must not be empty.")
        if upsert_batch_size <= 0:
            raise ValueError("Qdrant upsert batch size must be > 0.")
        from qdrant_client.http import models as qdrant_models

        self.client = client
        self.collection_name = collection_name
        self.max_retries = max_retries
        self.retry_backoff_ms = retry_backoff_ms
        self.upsert_batch_size = upsert_batch_size
        self._models = qdrant_models

    def is_ready(self) -> bool:
        try:
            self._retry(self.client.get_collections)
        except Exception:
            return False
        return True

    def upsert_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
        if not chunks:
            return
        vector_size = chunks[0].vector_size
        embedding_model = self._resolve_embedding_model(chunks)
        for chunk in chunks:
            if chunk.vector_size != vector_size:
                raise AppError(
                    "vector_dimension_mismatch",
                    "All embeddings in the same batch must have the same dimension.",
                    status_code=500,
                )
        self._ensure_collection(
            vector_size=vector_size,
            embedding_model=embedding_model,
        )
        for start in range(0, len(chunks), self.upsert_batch_size):
            batch = chunks[start : start + self.upsert_batch_size]
            points = [
                self._models.PointStruct(
                    id=self._point_id(chunk.id),
                    vector=list(chunk.embedding),
                    payload=self._chunk_payload(chunk),
                )
                for chunk in batch
            ]
            self._retry(
                lambda points=points: self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                    wait=True,
                )
            )

    def delete_document_vectors(self, document_id: str) -> None:
        if not self.client.collection_exists(self.collection_name):
            return
        self._retry(
            lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=self._models.FilterSelector(
                    filter=self._models.Filter(
                        must=[
                            self._models.FieldCondition(
                                key="document_id",
                                match=self._models.MatchValue(value=document_id),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        )

    def delete_document_version_vectors(
        self,
        document_id: str,
        document_version: int,
    ) -> None:
        if not self.client.collection_exists(self.collection_name):
            return
        self._retry(
            lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=self._models.FilterSelector(
                    filter=self._models.Filter(
                        must=[
                            self._models.FieldCondition(
                                key="document_id",
                                match=self._models.MatchValue(value=document_id),
                            ),
                            self._models.FieldCondition(
                                key="document_version",
                                match=self._models.MatchValue(value=document_version),
                            ),
                        ]
                    )
                ),
                wait=True,
            )
        )

    def delete_document_generation_vectors(
        self,
        document_id: str,
        generation: str,
    ) -> None:
        if not self.client.collection_exists(self.collection_name):
            return
        self._retry(
            lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=self._models.FilterSelector(
                    filter=self._models.Filter(
                        must=[
                            self._models.FieldCondition(
                                key="document_id",
                                match=self._models.MatchValue(value=document_id),
                            ),
                            self._models.FieldCondition(
                                key="ingestion_generation",
                                match=self._models.MatchValue(value=generation),
                            ),
                        ]
                    )
                ),
                wait=True,
            )
        )

    def finalize_document_generation(
        self,
        document_id: str,
        document_version: int,
        generation: str,
    ) -> None:
        if not self.client.collection_exists(self.collection_name):
            return
        self._retry(
            lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=self._models.FilterSelector(
                    filter=self._models.Filter(
                        must=[
                            self._models.FieldCondition(
                                key="document_id",
                                match=self._models.MatchValue(value=document_id),
                            ),
                            self._models.FieldCondition(
                                key="document_version",
                                match=self._models.MatchValue(value=document_version),
                            ),
                        ],
                        must_not=[
                            self._models.FieldCondition(
                                key="ingestion_generation",
                                match=self._models.MatchValue(value=generation),
                            )
                        ],
                    )
                ),
                wait=True,
            )
        )

    def query(
        self,
        embedding: Sequence[float],
        *,
        owner_id: str,
        document_ids: Sequence[str] | None,
        limit: int,
        tenant_id: str | None = None,
        metadata_filters: Mapping[str, str | int] | None = None,
    ) -> list[VectorSearchHit]:
        if document_ids is not None and not document_ids:
            return []
        if not self.client.collection_exists(self.collection_name):
            return []
        must = [
            self._models.FieldCondition(
                key="owner_id",
                match=self._models.MatchValue(value=owner_id),
            )
        ]
        if tenant_id is not None:
            must.append(
                self._models.FieldCondition(
                    key="tenant_id",
                    match=self._models.MatchValue(value=tenant_id),
                )
            )
        if document_ids is not None:
            must.append(
                self._models.FieldCondition(
                    key="document_id",
                    match=self._models.MatchAny(any=list(document_ids)),
                )
            )
        for field_name, value in (metadata_filters or {}).items():
            must.append(
                self._models.FieldCondition(
                    key=f"retrieval_metadata.{field_name}",
                    match=self._models.MatchValue(value=value),
                )
            )
        response = self._retry(
            lambda: self.client.query_points(
                collection_name=self.collection_name,
                query=list(embedding),
                query_filter=self._models.Filter(must=must),
                limit=limit,
                with_payload=True,
            )
        )
        hits: list[VectorSearchHit] = []
        for point in response.points:
            hits.append(self._search_hit(point))
        return hits

    @staticmethod
    def _search_hit(point: Any) -> VectorSearchHit:
        """Map a Qdrant point using its canonical UUID as the retrieval chunk ID.

        Existing points may still carry the chunker's composite source ID in
        ``payload.chunk_id``. The point ID is already the deterministic UUID
        shared with ``document_chunks.id``, so reading it directly keeps old
        indexes compatible while making BM25, dense, RRF, and citations agree.
        """
        payload = point.payload or {}
        raw_metadata = payload.get("metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        raw_retrieval_metadata = payload.get("retrieval_metadata")
        if isinstance(raw_retrieval_metadata, Mapping):
            metadata["retrieval_metadata"] = dict(raw_retrieval_metadata)
        return VectorSearchHit(
            chunk_id=str(point.id),
            document_id=str(payload.get("document_id")),
            score=float(point.score),
            text=str(payload.get("text") or ""),
            page_number=(
                int(payload["page_number"]) if payload.get("page_number") is not None else None
            ),
            section_title=(
                str(payload["section_title"]) if payload.get("section_title") is not None else None
            ),
            document_version=int(payload.get("document_version") or 1),
            checksum=(str(payload["checksum"]) if payload.get("checksum") is not None else None),
            chunk_index=(
                int(payload["chunk_index"]) if payload.get("chunk_index") is not None else None
            ),
            normalized_content_hash=(
                str(payload["normalized_content_hash"])
                if payload.get("normalized_content_hash") is not None
                else None
            ),
            exact_duplicate_group_id=(
                str(payload["exact_duplicate_group_id"])
                if payload.get("exact_duplicate_group_id") is not None
                else None
            ),
            metadata=metadata,
        )

    def _ensure_collection(
        self,
        *,
        vector_size: int,
        embedding_model: str,
    ) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=self._models.VectorParams(
                    size=vector_size,
                    distance=self._models.Distance.COSINE,
                ),
            )
            self._ensure_payload_indexes()
            return
        info = self._retry(lambda: self.client.get_collection(self.collection_name))
        self._validate_collection_contract(info, vector_size)
        if self._collection_requires_embedding_model_migration(embedding_model):
            raise AppError(
                "embedding_profile_mismatch",
                "Embedding model does not match existing Qdrant collection.",
                status_code=500,
            )
        self._ensure_payload_indexes(info)

    def _validate_collection_contract(
        self,
        info: Any,
        vector_size: int,
    ) -> None:
        existing_vectors = info.config.params.vectors
        if isinstance(existing_vectors, dict):
            raise AppError(
                "named_vectors_not_supported",
                "Qdrant collection must use an unnamed vector.",
                status_code=500,
            )
        existing_vector_size = getattr(existing_vectors, "size", None)
        if existing_vector_size != vector_size:
            raise AppError(
                "vector_dimension_mismatch",
                "Embedding dimension does not match existing Qdrant collection.",
                status_code=500,
            )
        existing_distance = getattr(existing_vectors, "distance", None)
        existing_distance_value = getattr(
            existing_distance,
            "value",
            existing_distance,
        )
        cosine_value = getattr(
            self._models.Distance.COSINE,
            "value",
            self._models.Distance.COSINE,
        )
        if str(existing_distance_value).lower() != str(cosine_value).lower():
            raise AppError(
                "vector_distance_mismatch",
                "Qdrant collection must use cosine distance.",
                status_code=500,
            )

    def _collection_requires_embedding_model_migration(
        self,
        embedding_model: str,
    ) -> bool:
        points, _ = self._retry(
            lambda: self.client.scroll(
                collection_name=self.collection_name,
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
        )
        if not points:
            return False
        existing_model = (points[0].payload or {}).get("embedding_model")
        return bool(existing_model and existing_model != embedding_model)

    def _ensure_payload_indexes(self, collection_info: Any | None = None) -> None:
        if self._is_local_qdrant():
            return
        payload_schema = getattr(collection_info, "payload_schema", None) or {}
        schema_type = self._models.PayloadSchemaType
        required = {
            "owner_id": schema_type.KEYWORD,
            "tenant_id": schema_type.KEYWORD,
            "document_id": schema_type.KEYWORD,
            "document_version": schema_type.INTEGER,
            "embedding_model": schema_type.KEYWORD,
            "ingestion_generation": schema_type.KEYWORD,
            "checksum": schema_type.KEYWORD,
            "normalized_content_hash": schema_type.KEYWORD,
            "exact_duplicate_group_id": schema_type.KEYWORD,
            "retrieval_metadata.document_type": schema_type.KEYWORD,
            "retrieval_metadata.content_kind": schema_type.KEYWORD,
            "retrieval_metadata.project_id": schema_type.KEYWORD,
            "retrieval_metadata.project_code": schema_type.KEYWORD,
            "retrieval_metadata.year": schema_type.INTEGER,
            "retrieval_metadata.data_period": schema_type.KEYWORD,
            "retrieval_metadata.effective_status": schema_type.KEYWORD,
        }
        for field_name, field_schema in required.items():
            existing_index = payload_schema.get(field_name)
            if existing_index is not None:
                continue
            self._retry(
                lambda field_name=field_name, field_schema=field_schema: (
                    self.client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field_name,
                        field_schema=field_schema,
                        wait=True,
                    )
                )
            )

    def _retry(self, func: Callable[[], Any]) -> Any:
        attempts = self.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return func()
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                delay_ms = self.retry_backoff_ms * attempt
                time.sleep(delay_ms / 1000)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Qdrant operation failed.")

    def _is_local_qdrant(self) -> bool:
        return self.client._client.__class__.__name__ == "QdrantLocal"

    @staticmethod
    def _resolve_embedding_model(
        chunks: Sequence[EmbeddedChunk],
    ) -> str:
        models = {chunk.embedding_model for chunk in chunks}
        if len(models) != 1:
            raise AppError(
                "embedding_model_mismatch",
                "All chunks in one batch must use the same embedding model.",
                status_code=500,
            )
        return next(iter(models))

    @staticmethod
    def _chunk_payload(chunk: EmbeddedChunk) -> dict[str, object]:
        source_block_ids = _source_block_ids(chunk.metadata.get("source_block_ids"))
        compact_metadata: dict[str, object] = {
            "source_block_ids": source_block_ids,
            "strategy": str(
                chunk.metadata.get("strategy") or chunk.metadata.get("chunk_strategy") or ""
            ),
            "strategy_version": str(chunk.metadata.get("strategy_version") or ""),
        }
        claim_scope = chunk.metadata.get("claim_scope")
        if claim_scope is not None:
            compact_metadata["claim_scope"] = claim_scope
        payload: dict[str, object] = {
            "chunk_id": QdrantVectorIndex._point_id(chunk.id),
            "source_chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_version": chunk.document_version,
            "owner_id": chunk.owner_id,
            "tenant_id": chunk.tenant_id,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "section_title": chunk.section_title,
            "checksum": chunk.checksum,
            "text": chunk.text,
            "embedding_model": chunk.embedding_model,
            "metadata": compact_metadata,
            "retrieval_metadata": _filterable_retrieval_metadata(chunk.retrieval_metadata),
        }
        ingestion_generation = str(chunk.metadata.get("ingestion_generation") or "").strip()
        if ingestion_generation:
            payload["ingestion_generation"] = ingestion_generation
        normalized_content_hash = str(chunk.metadata.get("normalized_content_hash") or "").strip()
        if normalized_content_hash:
            payload["normalized_content_hash"] = normalized_content_hash
        exact_duplicate_group_id = str(chunk.metadata.get("exact_duplicate_group_id") or "").strip()
        if exact_duplicate_group_id:
            payload["exact_duplicate_group_id"] = exact_duplicate_group_id
        return payload

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"chunk:{chunk_id}"))


class PgVectorIndex:
    """VectorIndex backed by Supabase pgvector, via PostgREST.

    Upserts (never delete+insert) so this never races complete_ingestion_job.
    """

    completion_is_transactional = True

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str],
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        retry_backoff_ms: int = 100,
        upsert_batch_size: int = 64,
    ) -> None:
        if not base_url:
            raise ValueError("pgvector base_url must not be empty.")
        if upsert_batch_size <= 0:
            raise ValueError("pgvector upsert batch size must be > 0.")
        import httpx2 as httpx

        self._client = httpx.Client(
            base_url=base_url,
            headers={**headers, "Content-Type": "application/json"},
            timeout=timeout_seconds,
        )
        self.max_retries = max_retries
        self.retry_backoff_ms = retry_backoff_ms
        self.upsert_batch_size = upsert_batch_size

    def is_ready(self) -> bool:
        try:
            response = self._retry(
                lambda: self._client.get(
                    "/document_chunks",
                    params={"limit": "1", "select": "id"},
                )
            )
            response.raise_for_status()
        except Exception:
            return False
        return True

    def upsert_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
        if not chunks:
            return
        vector_size = chunks[0].vector_size
        for chunk in chunks:
            if chunk.vector_size != vector_size:
                raise AppError(
                    "vector_dimension_mismatch",
                    "All embeddings in the same batch must have the same dimension.",
                    status_code=500,
                )
        for start in range(0, len(chunks), self.upsert_batch_size):
            batch = chunks[start : start + self.upsert_batch_size]
            rows = [self._chunk_row(chunk) for chunk in batch]
            self._retry(lambda rows=rows: self._upsert_rows(rows))

    def _upsert_rows(self, rows: list[dict[str, object]]) -> None:
        response = self._client.post(
            "/document_chunks",
            params={"on_conflict": "id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=rows,
        )
        response.raise_for_status()

    def delete_document_vectors(self, document_id: str) -> None:
        response = self._retry(
            lambda: self._client.delete(
                "/document_chunks",
                params={"document_id": f"eq.{document_id}"},
            )
        )
        response.raise_for_status()

    def delete_document_version_vectors(
        self,
        document_id: str,
        document_version: int,
    ) -> None:
        response = self._retry(
            lambda: self._client.delete(
                "/document_chunks",
                params={
                    "document_id": f"eq.{document_id}",
                    "metadata->>document_version": f"eq.{document_version}",
                },
            )
        )
        response.raise_for_status()

    def delete_document_generation_vectors(
        self,
        document_id: str,
        generation: str,
    ) -> None:
        del document_id, generation

    def finalize_document_generation(
        self,
        document_id: str,
        document_version: int,
        generation: str,
    ) -> None:
        del document_id, document_version, generation

    def query(
        self,
        embedding: Sequence[float],
        *,
        owner_id: str,
        document_ids: Sequence[str] | None,
        limit: int,
        tenant_id: str | None = None,
        metadata_filters: Mapping[str, str | int] | None = None,
    ) -> list[VectorSearchHit]:
        body: dict[str, object] = {
            "p_query_embedding": list(embedding),
            "p_owner_id": owner_id,
            "p_notebook_id": tenant_id,
            "p_document_ids": list(document_ids) if document_ids is not None else None,
            "p_limit": limit,
            **_metadata_rpc_parameters(metadata_filters),
        }
        response = self._retry(lambda: self._client.post("/rpc/match_document_chunks", json=body))
        response.raise_for_status()
        rows = response.json()
        hits: list[VectorSearchHit] = []
        for row in rows:
            metadata = row.get("metadata") or {}
            hits.append(
                VectorSearchHit(
                    chunk_id=str(row["chunk_id"]),
                    document_id=str(row["document_id"]),
                    score=float(row["score"]),
                    text=str(row.get("content") or ""),
                    page_number=(
                        int(metadata["page_number"])
                        if metadata.get("page_number") is not None
                        else None
                    ),
                    section_title=(
                        str(metadata["section_title"])
                        if metadata.get("section_title") is not None
                        else None
                    ),
                    document_version=int(row.get("document_version") or 1),
                    checksum=(
                        str(metadata["checksum"]) if metadata.get("checksum") is not None else None
                    ),
                    chunk_index=(
                        int(row["chunk_index"]) if row.get("chunk_index") is not None else None
                    ),
                    normalized_content_hash=(
                        str(row["normalized_content_hash"])
                        if row.get("normalized_content_hash") is not None
                        else None
                    ),
                    exact_duplicate_group_id=(
                        str(row["exact_duplicate_group_id"])
                        if row.get("exact_duplicate_group_id") is not None
                        else None
                    ),
                    metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
                )
            )
        return hits

    def _retry(self, func: Callable[[], Any]) -> Any:
        attempts = self.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return func()
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                delay_ms = self.retry_backoff_ms * attempt
                time.sleep(delay_ms / 1000)
        if last_error is not None:
            raise last_error
        raise RuntimeError("pgvector operation failed.")

    @staticmethod
    def _chunk_row(chunk: EmbeddedChunk) -> dict[str, object]:
        source_block_ids = _source_block_ids(chunk.metadata.get("source_block_ids"))
        return {
            "id": _point_id(chunk.id),
            "owner_id": chunk.owner_id,
            "notebook_id": chunk.tenant_id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "content": chunk.text,
            "token_count": chunk.token_count,
            "metadata": {
                "document_version": chunk.document_version,
                "page_number": chunk.page_number,
                "section_title": chunk.section_title,
                "checksum": chunk.checksum,
                "embedding_model": chunk.embedding_model,
                "source_block_ids": source_block_ids,
                "strategy": str(
                    chunk.metadata.get("strategy") or chunk.metadata.get("chunk_strategy") or ""
                ),
                "strategy_version": str(chunk.metadata.get("strategy_version") or ""),
                "retrieval_metadata": dict(chunk.retrieval_metadata),
            },
            "embedding": list(chunk.embedding),
        }


def _point_id(chunk_id: str) -> str:
    """Same deterministic id the ingestion RPC uses for document_chunks.id."""
    return str(uuid5(NAMESPACE_URL, f"chunk:{chunk_id}"))


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _source_block_ids(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _matches_retrieval_metadata(
    metadata: Mapping[str, object],
    filters: Mapping[str, str | int] | None,
) -> bool:
    for field_name, expected in (filters or {}).items():
        actual = metadata.get(field_name)
        if actual is None:
            return False
        if field_name == "year":
            try:
                if not isinstance(actual, str | int | float) or isinstance(actual, bool):
                    return False
                if int(actual) != expected:
                    return False
            except (TypeError, ValueError):
                return False
        elif str(actual).strip().casefold() != str(expected).strip().casefold():
            return False
    return True


def _filterable_retrieval_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    return {
        field_name: metadata[field_name]
        for field_name in _FILTERABLE_RETRIEVAL_FIELDS
        if metadata.get(field_name) is not None
    }


def _metadata_rpc_parameters(
    filters: Mapping[str, str | int] | None,
) -> dict[str, str | int]:
    values = filters or {}
    return {
        f"p_{field_name}": values[field_name]
        for field_name in _FILTERABLE_RETRIEVAL_FIELDS
        if values.get(field_name) is not None
    }


@dataclass(frozen=True)
class QdrantVectorIndexConfig:
    collection_name: str = "rag_chunks_openai_v1"
    max_retries: int = 2
    retry_backoff_ms: int = 100
    upsert_batch_size: int = 64


__all__ = [
    "InMemoryVectorIndex",
    "PgVectorIndex",
    "QdrantVectorIndex",
    "QdrantVectorIndexConfig",
]
