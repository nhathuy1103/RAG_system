"""Tests for structured citation location metadata."""

from datetime import UTC, datetime
from uuid import UUID

from app.chat.application.services import (
    ChatContext,
    _annotate_confirmed_conflicts,
    _apply_preferred_relations,
    _build_structured_fact_search,
    _deduplicate_citations,
    _format_page_or_section,
    _parse_page_number,
    _parse_section_title,
    _resolve_allowed_document_ids,
    _resolve_structured_document_ids,
    _structured_candidates,
)
from app.chat.domain.models import NewCitation
from app.documents.domain.models import Document
from app.knowledge_quality.domain.models import (
    DocumentRelation,
    RelationStatus,
    RelationType,
)
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate
from app.structured_facts.application.query import parse_structured_fact_query
from app.structured_facts.ports.repositories import StructuredFactEvidence

OWNER_ID = UUID("20000000-0000-0000-0000-000000000002")
NOTEBOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 30, tzinfo=UTC)


def test_duplicate_claim_citations_sharing_one_chunk_are_persisted_once() -> None:
    document_id = UUID("30000000-0000-0000-0000-000000000003")
    chunk_id = UUID("60000000-0000-0000-0000-000000000006")
    citations = (
        NewCitation(document_id, chunk_id, 1, "List price", 1.9),
        NewCitation(document_id, chunk_id, 2, "Discounted price", 1.8),
    )

    selected = _deduplicate_citations(citations)

    assert selected == (citations[0],)


def _document(
    document_id: str,
    *,
    canonical_id: str | None = None,
    is_current: bool = True,
    is_active: bool = True,
) -> Document:
    return Document(
        id=UUID(document_id),
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        original_filename=f"{document_id[-1]}.txt",
        storage_bucket="documents",
        storage_object_path=(f"{OWNER_ID}/{NOTEBOOK_ID}/{document_id}/{document_id[-1]}.txt"),
        mime_type="text/plain",
        size_bytes=10,
        content_hash=None,
        status="ready",
        error_message=None,
        is_active=is_active,
        created_at=NOW,
        updated_at=NOW,
        canonical_document_id=UUID(canonical_id) if canonical_id else None,
        is_current=is_current,
    )


def test_structures_page_and_section_metadata() -> None:
    metadata = {
        "page_number": "7",
        "section_title": "  Scaled Dot-Product Attention  ",
    }

    page_number = _parse_page_number(metadata)
    section_title = _parse_section_title(metadata)

    assert page_number == 7
    assert section_title == "Scaled Dot-Product Attention"
    assert _format_page_or_section(page_number, section_title) == (
        "Trang 7 · Scaled Dot-Product Attention"
    )


def test_rejects_invalid_page_metadata_without_losing_section() -> None:
    metadata = {
        "page_number": "not-a-page",
        "section_title": "Attention",
    }

    page_number = _parse_page_number(metadata)
    section_title = _parse_section_title(metadata)

    assert page_number is None
    assert section_title == "Attention"
    assert _format_page_or_section(page_number, section_title) == "Attention"


def test_default_retrieval_uses_only_canonical_current_documents() -> None:
    canonical_id = "30000000-0000-0000-0000-000000000003"
    alias_id = "40000000-0000-0000-0000-000000000004"
    historical_id = "50000000-0000-0000-0000-000000000005"
    current_id = "60000000-0000-0000-0000-000000000006"
    documents = (
        _document(canonical_id),
        _document(alias_id, canonical_id=canonical_id, is_current=False),
        _document(historical_id, is_current=False),
        _document(current_id),
    )

    allowed = _resolve_allowed_document_ids(documents, None)

    assert set(allowed) == {UUID(canonical_id), UUID(current_id)}


def test_explicit_alias_resolves_to_canonical_and_history_stays_selectable() -> None:
    canonical_id = "30000000-0000-0000-0000-000000000003"
    alias_id = "40000000-0000-0000-0000-000000000004"
    historical_id = "50000000-0000-0000-0000-000000000005"
    documents = (
        _document(canonical_id),
        _document(alias_id, canonical_id=canonical_id, is_current=False),
        _document(historical_id, is_current=False),
    )

    allowed = _resolve_allowed_document_ids(
        documents,
        (UUID(alias_id), UUID(historical_id)),
    )

    assert set(allowed) == {UUID(canonical_id), UUID(historical_id)}


def test_structured_scope_keeps_active_historical_canonical_documents() -> None:
    current_id = "30000000-0000-0000-0000-000000000003"
    alias_id = "40000000-0000-0000-0000-000000000004"
    historical_id = "50000000-0000-0000-0000-000000000005"
    inactive_id = "60000000-0000-0000-0000-000000000006"
    documents = (
        _document(current_id),
        _document(
            alias_id,
            canonical_id=current_id,
            is_current=False,
            is_active=False,
        ),
        _document(historical_id, is_current=False),
        _document(inactive_id, is_current=False, is_active=False),
    )

    assert set(_resolve_structured_document_ids(documents, None)) == {
        UUID(current_id),
        UUID(historical_id),
    }
    assert _resolve_structured_document_ids(documents, (UUID(alias_id),)) == (UUID(current_id),)


def test_structured_search_uses_claim_scope_time_and_qualifiers() -> None:
    historical_id = UUID("50000000-0000-0000-0000-000000000005")
    intent = parse_structured_fact_query(
        "Đơn giá đã bao gồm VAT căn A101 tháng 3/2025 là bao nhiêu?"
    )
    assert intent is not None
    context = ChatContext(
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        conversation_id=UUID("70000000-0000-0000-0000-000000000007"),
        assistant_message_id=UUID("80000000-0000-0000-0000-000000000008"),
        question="question",
        history=(),
        allowed_document_ids=(),
        document_titles={},
        structured_query=intent,
        structured_document_ids=(historical_id,),
    )

    search = _build_structured_fact_search(context, intent, retrieval_top_k=8)

    assert search.document_ids == (historical_id,)
    assert search.valid_from is not None and search.valid_from.isoformat() == "2025-03-01"
    assert search.valid_to is not None and search.valid_to.isoformat() == "2025-03-31"
    assert search.qualifiers == {
        "stable": {"price_basis": "per_sqm"},
        "optional": {"vat_included": True},
    }
    assert search.limit == 16


def test_reviewed_conflict_preference_keeps_both_sources_available() -> None:
    source_id = UUID("30000000-0000-0000-0000-000000000003")
    target_id = UUID("40000000-0000-0000-0000-000000000004")
    unrelated_id = UUID("50000000-0000-0000-0000-000000000005")
    relation = DocumentRelation(
        id=UUID("70000000-0000-0000-0000-000000000007"),
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        source_document_id=source_id,
        target_document_id=target_id,
        relation_type=RelationType.CONFLICT,
        status=RelationStatus.CONFIRMED,
        confidence=0.98,
        signals={},
        reason="Policy owner selected the updated source",
        detector_version="test",
        preferred_document_id=source_id,
        resolved_by=OWNER_ID,
        resolved_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )

    allowed = _apply_preferred_relations(
        (source_id, target_id, unrelated_id),
        (relation,),
    )

    assert set(allowed) == {source_id, target_id, unrelated_id}


def test_unresolved_or_unpreferred_conflicts_keep_both_documents() -> None:
    source_id = UUID("30000000-0000-0000-0000-000000000003")
    target_id = UUID("40000000-0000-0000-0000-000000000004")
    relation = DocumentRelation(
        id=UUID("70000000-0000-0000-0000-000000000007"),
        owner_id=OWNER_ID,
        notebook_id=NOTEBOOK_ID,
        source_document_id=source_id,
        target_document_id=target_id,
        relation_type=RelationType.CONFLICT_CANDIDATE,
        status=RelationStatus.PENDING,
        confidence=0.81,
        signals={},
        reason=None,
        detector_version="test",
        preferred_document_id=None,
        resolved_by=None,
        resolved_at=None,
        created_at=NOW,
        updated_at=NOW,
    )

    allowed = _apply_preferred_relations((source_id, target_id), (relation,))

    assert set(allowed) == {source_id, target_id}


def test_confirmed_conflict_annotation_only_links_retrieved_pair() -> None:
    source_id = UUID("30000000-0000-0000-0000-000000000003")
    target_id = UUID("40000000-0000-0000-0000-000000000004")
    absent_id = UUID("50000000-0000-0000-0000-000000000005")
    evidence = tuple(
        RetrievalCandidate(
            chunk=EvidenceChunk(
                id=f"60000000-0000-0000-0000-00000000000{index}",
                document_id=str(document_id),
                text=f"Evidence {index}",
            ),
            score=1.0 - index / 10,
            rank=index,
        )
        for index, document_id in enumerate(
            (source_id, target_id),
            start=1,
        )
    )

    annotated = _annotate_confirmed_conflicts(
        evidence,
        (
            (source_id, target_id),
            (source_id, absent_id),
        ),
    )

    assert annotated[0].chunk.metadata["confirmed_conflict_peer_document_ids"] == str(target_id)
    assert annotated[1].chunk.metadata["confirmed_conflict_peer_document_ids"] == str(source_id)
    assert "confirmed_conflict_peer_document_ids" not in evidence[0].chunk.metadata


def test_structured_fact_uses_real_source_chunk_for_cell_citation() -> None:
    document_id = UUID("30000000-0000-0000-0000-000000000003")
    chunk_id = UUID("60000000-0000-0000-0000-000000000006")
    candidates = _structured_candidates(
        (
            StructuredFactEvidence(
                claim_id="claim-1",
                document_id=document_id,
                source_chunk_id=chunk_id,
                document_version=2,
                subject_key="project=ocean-park|building=s1|unit=a101",
                predicate="sale_price",
                normalized_value={"value": "4500000000", "currency": "VND"},
                qualifiers={"stable": {"price_type": "list_price"}},
                temporal={"effective_from": "2025-03-01T00:00:00+00:00"},
                provenance={
                    "table_id": "table-1",
                    "data_row_ordinal": 3,
                    "page_number": 5,
                },
                confidence=0.98,
                authority={
                    "source_type": "official_price_list",
                    "publisher": "Developer A",
                    "authority_level": 90,
                },
                relation_warnings=(
                    {
                        "relation_id": "relation-1",
                        "relation_type": "conflict_candidate",
                        "review_status": "pending",
                    },
                ),
                source_text="4,5 tá»· VND",
            ),
        )
    )

    assert candidates[0].source == "structured"
    assert candidates[0].chunk.id == str(chunk_id)
    assert candidates[0].chunk.metadata["page_number"] == 5
    assert "Source cell" in candidates[0].chunk.text
    assert candidates[0].chunk.metadata["structured_relation_warnings"] == [
        {
            "relation_id": "relation-1",
            "relation_type": "conflict_candidate",
            "review_status": "pending",
        }
    ]
    assert '"relation_id": "relation-1"' in candidates[0].chunk.text
    assert "Source authority" in candidates[0].chunk.text
    assert candidates[0].chunk.metadata["structured_authority"] == {
        "source_type": "official_price_list",
        "publisher": "Developer A",
        "authority_level": 90,
    }
