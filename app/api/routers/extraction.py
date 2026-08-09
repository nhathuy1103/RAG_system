"""Authenticated endpoint for inspecting extraction output without persistence."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import asdict
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.dependencies.auth import get_current_user
from app.api.schemas.auth import CurrentUser
from app.api.schemas.extraction import ExtractionInspectionResponse
from app.pipeline.bootstrap.settings import Settings, get_settings
from app.pipeline.documents.adapters.parsers import ParserRegistry
from app.pipeline.documents.application.extraction_pipeline import (
    AdvancedExtractionPipeline,
    AdvancedExtractionResult,
)
from app.pipeline.documents.application.validation import validate_document_source
from app.pipeline.documents.domain.parsed import ParsedDocument
from app.pipeline.documents.domain.source import DocumentSource
from app.pipeline.indexing.application.chunker import ChunkData, Chunker
from app.pipeline.indexing.domain.retrieval_metadata import normalize_chunk_retrieval_metadata
from app.pipeline.shared.errors import AppError

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["extraction"])


@router.post(
    "/extraction-inspect",
    response_model=ExtractionInspectionResponse,
)
async def inspect_extraction(
    response: Response,
    file: Annotated[UploadFile, File(description="A single file to inspect")],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExtractionInspectionResponse:
    """Run extraction in memory and return its inspectable output.

    The source file, chunks, and embeddings are not persisted. This route is intended
    for authenticated debugging and evaluation of the configured extraction pipeline.
    """

    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Tên file không được để trống.",
        )

    try:
        content = await file.read(settings.max_file_size_bytes + 1)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể đọc file upload.",
        ) from exc
    finally:
        with suppress(OSError):
            await file.close()

    mime_type = (file.content_type or "application/octet-stream").split(";", 1)[0].strip()
    source = DocumentSource(
        document_id=f"inspection-{uuid4()}",
        owner_id=current_user.id,
        tenant_id="extraction-inspector",
        title=filename,
        content=content,
        mime_type=mime_type,
        metadata={"extraction_attempt_id": f"inspect-{uuid4()}"},
    )

    try:
        validate_document_source(source, settings.validation_config)
        pipeline = AdvancedExtractionPipeline(settings.advanced_extraction_config)
        result = await run_in_threadpool(
            pipeline.run,
            source,
            parser_catalog=ParserRegistry(ocr_enabled=settings.ocr_enabled),
        )
    except AppError as exc:
        raise HTTPException(
            status_code=exc.detail.status_code,
            detail=exc.detail.message,
        ) from exc
    except Exception as exc:
        LOGGER.exception("Extraction inspection failed for %r", filename)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Không thể trích xuất file. Hãy kiểm tra định dạng hoặc nội dung file.",
        ) from exc

    response.headers["Cache-Control"] = "private, no-store"
    return build_extraction_inspection_response(source, result, settings)


def build_extraction_inspection_response(
    source: DocumentSource,
    result: AdvancedExtractionResult,
    settings: Settings,
) -> ExtractionInspectionResponse:
    """Project internal extraction objects without repeating large canonical payloads."""

    parsed = result.parsed_document
    element_count = sum(len(page.elements) for page in parsed.pages)
    phase4 = result.phase4_tables
    chunks = (
        tuple(Chunker.from_settings(settings).chunk(source.document_id, source.version, parsed))
        if result.index_allowed
        else ()
    )

    return ExtractionInspectionResponse(
        source={
            "filename": source.title,
            "mime_type": source.mime_type,
            "extension": source.extension,
            "size_bytes": source.size_bytes,
            "checksum": source.checksum,
        },
        summary={
            "parser_name": parsed.parser_name,
            "parser_version": parsed.parser_version,
            "detected_language": parsed.detected_language,
            "ocr_used": parsed.ocr_used,
            "index_allowed": result.index_allowed,
            "quality_status": result.quality_report.status,
            "quality_action": result.quality_decision.action.value,
            "page_count": len(parsed.pages),
            "section_count": len(parsed.sections),
            "table_count": len(parsed.tables),
            "element_count": element_count,
            "image_count": len(parsed.images_metadata),
            "text_characters": len(parsed.text),
            "chunk_count": len(chunks),
            "quality_mode": settings.extraction_quality_mode,
            "ocr_enabled": settings.ocr_enabled,
        },
        content={
            "text": parsed.text,
            "markdown": parsed.content_markdown or parsed.text,
        },
        chunking={
            "status": "generated" if result.index_allowed else "blocked_by_quality",
            "strategy": settings.chunking_strategy,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "chunk_count": len(chunks),
            "contextual_enrichment_applied": False,
            "production_contextual_enrichment_enabled": settings.contextual_enrichment_enabled,
            "embedding_applied": False,
            "note": (
                "Inspector dừng trước contextual enrichment và embedding."
                if result.index_allowed
                else "Quality gate không cho phép tạo chunk dùng cho indexing."
            ),
        },
        chunks=[_chunk_payload(chunk, source=source, parsed=parsed) for chunk in chunks],
        parsed_document=_parsed_document_payload(parsed),
        quality_report=result.quality_report.to_dict(),
        quality_decision=result.quality_decision.to_dict(),
        canonical_ir=(result.canonical_ir.to_dict() if result.canonical_ir is not None else None),
        canonical_ir_validation=(
            result.canonical_ir_validation.to_dict()
            if result.canonical_ir_validation is not None
            else None
        ),
        canonical_ir_artifact=(
            result.canonical_ir_artifact.to_dict()
            if result.canonical_ir_artifact is not None
            else None
        ),
        phases={
            "layout": _phase_metadata(result.phase3_layout),
            "tables": {
                **(_phase_metadata(phase4) or {}),
                "structured_tables": (
                    [table.to_dict() for table in phase4.structured_tables]
                    if phase4 is not None
                    else []
                ),
            },
            "verification": _phase_metadata(result.phase5_verification),
            "multimodal": _phase_metadata(result.phase6_multimodal),
        },
        adaptive_routing={
            "page_profiles": [asdict(item) for item in result.page_profiles],
            "page_classifications": [asdict(item) for item in result.page_classifications],
            "routing_decisions": [asdict(item) for item in result.routing_decisions],
        },
    )


def _parsed_document_payload(parsed: ParsedDocument) -> dict[str, Any]:
    return {
        "pages": [asdict(page) for page in parsed.pages],
        "sections": [asdict(section) for section in parsed.sections],
        "tables": [asdict(table) for table in parsed.tables],
        "images_metadata": [asdict(image) for image in parsed.images_metadata],
        "document_metadata": dict(parsed.document_metadata),
        "warnings": list(parsed.warnings),
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
        "confidence": parsed.confidence,
        "ocr_used": parsed.ocr_used,
        "detected_language": parsed.detected_language,
    }


def _chunk_payload(
    chunk: ChunkData,
    *,
    source: DocumentSource,
    parsed: ParsedDocument,
) -> dict[str, Any]:
    retrieval_metadata = normalize_chunk_retrieval_metadata(
        chunk_metadata=chunk.metadata,
        document_metadata=parsed.document_metadata,
        source_metadata=source.metadata,
        title=source.title,
        section_title=chunk.section_title,
    )
    return {
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "embedding_text": chunk.embedding_text,
        "search_text": chunk.search_text,
        "character_count": len(chunk.text),
        "estimated_token_count": len(chunk.text.split()),
        "page_number": chunk.page_number,
        "section_title": chunk.section_title,
        "section_id": chunk.section_id,
        "offset_start": chunk.offset_start,
        "offset_end": chunk.offset_end,
        "strategy": chunk.strategy,
        "strategy_version": chunk.strategy_version,
        "config_checksum": chunk.config_checksum,
        "checksum": chunk.checksum,
        "content_checksum": chunk.content_checksum,
        "source_block_ids": list(chunk.source_block_ids),
        "table_identity": chunk.table_identity,
        "retrieval_metadata": retrieval_metadata,
        "metadata": dict(chunk.metadata),
    }


def _phase_metadata(phase: Any | None) -> dict[str, Any] | None:
    if phase is None:
        return None
    return dict(phase.metadata(artifact_reference=None))


__all__ = ["build_extraction_inspection_response", "inspect_extraction", "router"]
