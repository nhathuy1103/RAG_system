from __future__ import annotations

from app.generation.application.enterprise_context import build_enterprise_generation_context
from app.generation.application.evidence_context import EvidenceContextPolicy
from app.retrieval.application.enterprise_evidence import select_enterprise_evidence
from app.retrieval.application.query_context import parse_query_context
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate, RetrievalFilters


def _candidate(
    chunk_id: str,
    document_id: str,
    text: str,
    *,
    score: float,
    year: int | None = None,
    content_kind: str = "paragraph",
    **metadata: object,
) -> RetrievalCandidate:
    values: dict[str, object] = {
        "content_kind": content_kind,
        "normalization_version": "chunk-normalization-v2",
        **metadata,
    }
    if year is not None:
        values.update({"year": year, "reference_year": year})
    return RetrievalCandidate(
        chunk=EvidenceChunk(chunk_id, document_id, text, values),
        score=score,
        rank=int(chunk_id.rsplit("-", maxsplit=1)[-1]),
    )


def _select(query: str, candidates: tuple[RetrievalCandidate, ...], *, top_k: int = 3):
    context = parse_query_context(query, owner_id="actor", notebook_id=None)
    return select_enterprise_evidence(
        context,
        candidates,
        filters=RetrievalFilters(owner_id="actor"),
        top_k=top_k,
        max_chunks_per_document=2,
    )


def test_temporal_comparison_reserves_value_bearing_evidence_for_each_year() -> None:
    candidates = (
        _candidate("chunk-1", "doc-2023", "Giới thiệu dữ liệu giá năm 2023", score=0.90, year=2023),
        _candidate(
            "chunk-2",
            "doc-2023",
            "Grand Park: 40 triệu/m2",
            score=0.40,
            year=2023,
            content_kind="table",
        ),
        _candidate(
            "chunk-3", "doc-2025", "Phương pháp so sánh giá năm 2025", score=0.95, year=2025
        ),
        _candidate(
            "chunk-4",
            "doc-2025",
            "Grand Park: 48 triệu/m2",
            score=0.30,
            year=2025,
            content_kind="table",
        ),
        _candidate(
            "chunk-5",
            "doc-2026",
            "Grand Park: 55 triệu/m2",
            score=0.80,
            year=2026,
            content_kind="table",
        ),
    )

    result = _select("So sánh giá căn hộ qua các năm", candidates)

    assert result.diagnostics.final_years == (2023, 2025, 2026)
    assert {item.chunk.id for item in result.evidence} == {"chunk-2", "chunk-4", "chunk-5"}
    assert set(result.diagnostics.value_bearing_ids) == {"chunk-2", "chunk-4", "chunk-5"}


def test_explicit_year_never_guesses_unknown_or_different_year() -> None:
    candidates = (
        _candidate("chunk-1", "doc-unknown", "Grand Park: 44 triệu/m2", score=0.99),
        _candidate("chunk-2", "doc-2026", "Grand Park: 55 triệu/m2", score=0.90, year=2026),
        _candidate("chunk-3", "doc-2025", "Grand Park: 48 triệu/m2", score=0.30, year=2025),
    )

    result = _select("Giá Grand Park năm 2025?", candidates)

    assert [item.chunk.id for item in result.evidence] == ["chunk-3"]


def test_normalized_hash_collapses_copy_and_retains_visible_provenance() -> None:
    digest = "a" * 64
    candidates = (
        _candidate(
            "chunk-1",
            "doc-original",
            "Giá 48 triệu/m2",
            score=0.9,
            year=2025,
            normalized_content_hash=digest,
        ),
        _candidate(
            "chunk-2",
            "doc-copy",
            "Giá 48 triệu/m2",
            score=0.8,
            year=2025,
            normalized_content_hash=digest,
        ),
        _candidate("chunk-3", "doc-2026", "Giá 55 triệu/m2", score=0.7, year=2026),
    )

    result = _select("So sánh giá năm 2025 và 2026", candidates)

    assert (
        len(
            {
                item.chunk.document_id
                for item in result.evidence
                if item.chunk.metadata.get("year") == 2025
            }
        )
        == 1
    )
    representative = next(
        item for item in result.evidence if item.chunk.metadata.get("year") == 2025
    )
    assert representative.chunk.metadata["p4_provenance_count"] == 2
    assert set(result.diagnostics.duplicate_suppressed_ids) == {"chunk-2"}


def test_conflict_counterparts_are_mandatory_even_when_top_k_is_one() -> None:
    candidates = (
        _candidate(
            "chunk-1",
            "doc-a",
            "Phạm vi 450 km",
            score=0.8,
            year=2026,
            conflict_group_id="conflict-1",
        ),
        _candidate(
            "chunk-2",
            "doc-b",
            "Phạm vi 480 km",
            score=0.7,
            year=2026,
            conflict_group_id="conflict-1",
        ),
        _candidate("chunk-3", "doc-c", "Giới thiệu thông số", score=0.99, year=2026),
    )

    result = _select("Thông số 2026 là bao nhiêu?", candidates, top_k=1)

    assert {item.chunk.id for item in result.evidence} == {"chunk-1", "chunk-2"}
    assert set(result.diagnostics.conflict_reserved_ids) == {"chunk-1", "chunk-2"}


def test_conflict_pair_is_not_collapsed_by_bad_duplicate_annotation() -> None:
    digest = "b" * 64
    candidates = (
        _candidate(
            "chunk-1",
            "doc-a",
            "Giá 5 tỷ",
            score=0.8,
            year=2026,
            conflict_group_id="conflict-1",
            normalized_content_hash=digest,
        ),
        _candidate(
            "chunk-2",
            "doc-b",
            "Giá 6 tỷ",
            score=0.7,
            year=2026,
            conflict_group_id="conflict-1",
            normalized_content_hash=digest,
        ),
    )

    result = _select("Hai nguồn có mâu thuẫn không?", candidates, top_k=1)

    assert {item.chunk.id for item in result.evidence} == {"chunk-1", "chunk-2"}


def test_answer_bearing_prose_can_beat_non_value_table() -> None:
    candidates = (
        _candidate(
            "chunk-1", "doc-a", "Bảng danh mục dự án", score=0.95, year=2025, content_kind="table"
        ),
        _candidate(
            "chunk-2", "doc-a", "Giá Grand Park là 48 triệu đồng mỗi m2.", score=0.50, year=2025
        ),
    )

    result = _select("Giá Grand Park năm 2025 là bao nhiêu?", candidates, top_k=1)

    assert [item.chunk.id for item in result.evidence] == ["chunk-2"]


def test_methodology_is_preferred_when_method_itself_is_requested() -> None:
    candidates = (
        _candidate(
            "chunk-1",
            "doc-a",
            "Phương pháp so sánh dùng giá giao dịch đã chuẩn hóa.",
            score=0.60,
            year=2025,
        ),
        _candidate(
            "chunk-2",
            "doc-a",
            "Grand Park: 48 triệu/m2",
            score=0.70,
            year=2025,
            content_kind="table",
        ),
    )

    result = _select("Phương pháp so sánh giá là gì?", candidates, top_k=1)

    assert [item.chunk.id for item in result.evidence] == ["chunk-1"]


def test_requested_conditional_qualifier_does_not_merge_other_protocol() -> None:
    candidates = (
        _candidate(
            "chunk-1",
            "doc-wltp",
            "WLTP 450 km",
            score=0.8,
            p4_relation_type="CONDITIONAL_VARIANT",
            conditional_variant_group_id="protocol",
            test_protocol="WLTP",
        ),
        _candidate(
            "chunk-2",
            "doc-epa",
            "EPA 420 km",
            score=0.9,
            p4_relation_type="CONDITIONAL_VARIANT",
            conditional_variant_group_id="protocol",
            test_protocol="EPA",
        ),
    )

    result = _select("Phạm vi WLTP là bao nhiêu?", candidates)

    assert [item.chunk.id for item in result.evidence] == ["chunk-1"]


def test_current_query_keeps_only_explicit_current_version() -> None:
    candidates = (
        _candidate(
            "chunk-1",
            "doc-old",
            "Giá năm 2025 là 48 triệu/m2",
            score=0.99,
            year=2025,
            version_family_id="family-1",
            p4_relation_type="VERSION_UPDATE",
            is_current=False,
        ),
        _candidate(
            "chunk-2",
            "doc-current",
            "Giá hiện tại là 55 triệu/m2",
            score=0.40,
            year=2026,
            version_family_id="family-1",
            p4_relation_type="VERSION_UPDATE",
            is_current=True,
        ),
    )

    result = _select("Giá hiện tại là bao nhiêu?", candidates)

    assert [item.chunk.id for item in result.evidence] == ["chunk-2"]


def test_generation_context_retains_only_visible_duplicate_provenance() -> None:
    digest = "c" * 64
    candidates = (
        _candidate(
            "chunk-1",
            "doc-a",
            "Giá 48 triệu/m2",
            score=0.9,
            year=2025,
            normalized_content_hash=digest,
        ),
        _candidate(
            "chunk-2",
            "doc-b",
            "Giá 48 triệu/m2",
            score=0.8,
            year=2025,
            normalized_content_hash=digest,
        ),
    )
    query = parse_query_context("Giá năm 2025?", owner_id="actor", notebook_id=None)
    selection = select_enterprise_evidence(
        query,
        candidates,
        filters=RetrievalFilters(owner_id="actor"),
        top_k=2,
        max_chunks_per_document=2,
    )

    context = build_enterprise_generation_context(
        query,
        selection.evidence,
        authorized_document_ids=frozenset({"doc-a", "doc-b"}),
        policy=EvidenceContextPolicy(),
    )

    assert len(context.evidence) == 1
    assert context.evidence[0].provenance.occurrence_count == 2
    assert set(context.evidence[0].provenance.document_ids) == {"doc-a", "doc-b"}
