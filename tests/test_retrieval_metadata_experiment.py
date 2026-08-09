from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

TESTSET_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "retrieval_metadata_testset"
sys.path.insert(0, str(TESTSET_DIR))

from align_production_metadata_corpus import align_corpora  # noqa: E402
from audit_context_quality import score_context  # noqa: E402
from build_experiment_report import build_report  # noqa: E402
from build_extended_metadata_field_diagnostic import (  # noqa: E402
    _candidate_rows,
    build_diagnostics,
)
from build_metadata_benchmark import PRIMARY_SLICES, build_benchmark  # noqa: E402
from build_real_metadata_benchmark import _first_phrase  # noqa: E402
from run_abcd_experiment import (  # noqa: E402
    EvalChunk,
    _candidate_allowed,
    _gold_metadata,
    _project,
    _semantic_metadata,
    _shuffled_context_summaries,
    _shuffled_metadata,
    build_projections,
    resolve_ground_truth,
    run_queries,
)
from score_experiment_comparison import (  # noqa: E402
    clustered_bootstrap_ci,
    clustered_permutation_p_value,
    select_metadata_field_subset,
    select_query_subset,
)
from score_retrieval_results import is_hit, score  # noqa: E402

from app.retrieval.domain.models import EvidenceChunk  # noqa: E402


def _chunk(index: int, *, text: str = "evidence") -> EvalChunk:
    metadata = {
        "title": f"doc-{index}.pdf",
        "document_type": "contract",
        "section_title": f"section-{index}",
    }
    return EvalChunk(
        id=f"chunk-{index}",
        document_id=f"doc-{index}",
        document_title=f"doc-{index}.pdf",
        chunk_index=index,
        page_number=index + 1,
        text=text,
        current_metadata=metadata,
        gold_metadata=metadata,
        gold_annotated=True,
    )


def test_extended_field_diagnostic_is_derived_without_mutating_frozen_test() -> None:
    source = {
        "id": "frozen-project",
        "query_id": "frozen-project",
        "query": "Mục P16 của Vinhomes Smart City",
        "answerable": True,
        "relevant_chunk_ids": ["chunk-p16"],
        "required_metadata_fields": ["project_code"],
        "retrieval_filters": {
            "metadata_conditions": [
                {"field": "project_name", "op": "eq", "value": "Vinhomes Smart City"}
            ],
            "unsupported_field_policy": "fail_closed",
        },
    }
    original = source.copy()
    chunks = [
        {
            "chunk_id": "chunk-p16",
            "current_metadata": {"document_type": "amenity_catalog"},
            "gold_metadata": {
                "document_type": "amenity_catalog",
                "project_name": "Vinhomes Smart City",
                "project_code": "P16",
            },
        }
    ]

    diagnostics = build_diagnostics([source], chunks)
    by_field = {
        row["retrieval_filters"]["metadata_conditions"][0]["field"]: row
        for row in diagnostics
    }

    assert set(by_field) == {"project_name", "project_code"}
    assert by_field["project_code"]["annotation_status"] == (
        "derived_diagnostic_requires_human_review"
    )
    assert by_field["project_code"]["diagnostic_provenance"]["frozen_test_unchanged"]
    assert source == original


def test_no_metadata_projection_contains_only_raw_chunk_text() -> None:
    chunk = _chunk(0, text="Nội dung gốc")

    projection = _project(chunk, chunk.current_metadata, mode="no_metadata")

    assert projection.embedding_text == "Nội dung gốc"
    assert projection.search_text == "Nội dung gốc"
    assert projection.retrieval_metadata == {}


def test_semantic_metadata_can_exclude_benchmark_profile_injection() -> None:
    chunk_metadata = {
        "retrieval_metadata": {
            "title": "actual.docx",
            "content_kind": "table",
        }
    }
    profile = {
        "current_document_metadata": {
            "document_type": "amenity_catalog",
            "effective_status": "current",
        }
    }

    metadata = _semantic_metadata(
        chunk_metadata,
        profile,
        inject_profile_metadata=False,
    )

    assert metadata == {"title": "actual.docx", "content_kind": "table"}


def test_candidate_audit_can_use_current_metadata_payload() -> None:
    diagnostic = {
        "id": "diag_project",
        "scenario_id": "project",
        "answerable": True,
        "relevant_chunk_ids": ["chunk-1"],
        "forbidden_chunk_ids": [],
        "diagnostic_provenance": {"source_test_id": "project", "basis": "frozen"},
        "retrieval_filters": {
            "metadata_conditions": [
                {"field": "project_code", "op": "eq", "value": "P16"}
            ]
        },
    }
    chunks = [
        {
            "chunk_id": "chunk-1",
            "current_metadata": {},
            "gold_metadata": {"project_code": "P16"},
        }
    ]

    details, summary = _candidate_rows(
        [diagnostic],
        chunks,
        metadata_source="current",
    )

    assert details[0]["candidate_count"] == 0
    assert details[0]["all_relevant_retained"] is False
    assert summary[0]["relevant_retention_rate"] == 0.0


def test_production_metadata_alignment_preserves_frozen_identity_and_text() -> None:
    frozen = [
        {
            "chunk_id": "approved-id",
            "document_id": "doc-1",
            "document_title": "source.docx",
            "chunk_index": 3,
            "text": "Heading\n\nBody",
            "current_metadata": {"project_code": "injected"},
        }
    ]
    production = [
        {
            "chunk_id": "new-id",
            "document_id": "doc-1",
            "document_title": "source.docx",
            "chunk_index": 3,
            "text": "# Heading\n\nBody",
            "current_metadata": {"project_code": "P16"},
        }
    ]

    aligned, stats = align_corpora(frozen, production)

    assert aligned[0]["chunk_id"] == "approved-id"
    assert aligned[0]["text"] == "Heading\n\nBody"
    assert aligned[0]["current_metadata"] == {"project_code": "P16"}
    assert stats["heading_normalized_text_match_count"] == 1


def test_v6_placement_modes_isolate_domain_metadata_channels() -> None:
    metadata = {
        "title": "market-report.docx",
        "document_type": "market_report",
        "section_title": "Price table",
        "contextual_summary": "Current project pricing.",
        "contextual_search_terms": ["tay-mo-alias"],
        "year": 2026,
        "project_name": "Tay Mo",
    }
    chunk = replace(
        _chunk(0, text="Raw price evidence."),
        current_metadata=metadata,
        gold_metadata=metadata,
    )

    filter_only = _project(chunk, metadata, mode="v6a_filter_only")
    search = _project(chunk, metadata, mode="v6b_filter_plus_search_text")
    embedding = _project(chunk, metadata, mode="v6c_filter_plus_embedding_text")
    combined = _project(chunk, metadata, mode="v6_domain_metadata")

    for projection in (filter_only, search, embedding, combined):
        assert projection.retrieval_metadata["year"] == 2026
        assert projection.retrieval_metadata["project_name"] == "Tay Mo"
        assert "tay-mo-alias" in projection.search_text

    markers = ("Year: 2026", "Project: Tay Mo")
    assert all(marker not in filter_only.search_text for marker in markers)
    assert all(marker not in filter_only.embedding_text for marker in markers)
    assert all(marker in search.search_text for marker in markers)
    assert all(marker not in search.embedding_text for marker in markers)
    assert all(marker not in embedding.search_text for marker in markers)
    assert all(marker in embedding.embedding_text for marker in markers)
    assert all(marker in combined.search_text for marker in markers)
    assert all(marker in combined.embedding_text for marker in markers)


def test_filter_capable_subset_requires_structured_metadata_condition() -> None:
    tests = [
        {
            "id": "content-only",
            "retrieval_filters": {"metadata_conditions": []},
        },
        {
            "id": "acl-scope-only",
            "query_context": {"document_ids": ["doc-1"]},
            "retrieval_filters": {"metadata_conditions": []},
        },
        {
            "id": "year-filter",
            "retrieval_filters": {
                "metadata_conditions": [
                    {"field": "year", "op": "eq", "value": 2026}
                ]
            },
        },
    ]

    selected = select_query_subset(tests, "filter_capable")

    assert [test["id"] for test in selected] == ["year-filter"]


def test_metadata_field_subset_selects_only_queries_using_that_condition() -> None:
    tests = [
        {"id": "year", "retrieval_filters": {"metadata_conditions": [{"field": "year"}]}},
        {
            "id": "project-year",
            "retrieval_filters": {
                "metadata_conditions": [{"field": "project_name"}, {"field": "year"}]
            },
        },
        {"id": "content", "retrieval_filters": {"metadata_conditions": []}},
    ]

    assert [test["id"] for test in select_metadata_field_subset(tests, "year")] == [
        "year",
        "project-year",
    ]
    assert select_metadata_field_subset(tests, "source") == []


def test_clustered_statistics_flip_and_resample_whole_scenarios() -> None:
    values = [1.0, 1.0, 0.0, 0.0]
    clusters = ["a", "a", "b", "b"]

    low, high = clustered_bootstrap_ci(values, clusters, seed=7, samples=1000)
    p_value = clustered_permutation_p_value(
        [1.0, 1.0, 1.0, 1.0], clusters, seed=7, samples=1000
    )

    assert low == 0.0
    assert high == 1.0
    assert 0.45 <= p_value <= 0.55


def test_shuffled_metadata_is_deterministic_distribution_preserving_derangement() -> None:
    chunks = [_chunk(index) for index in range(8)]

    first = _shuffled_metadata(chunks, seed=42)
    second = _shuffled_metadata(chunks, seed=42)

    assert first == second
    assert sorted(value["title"] for value in first.values()) == sorted(
        chunk.current_metadata["title"] for chunk in chunks
    )
    assert all(first[chunk.id]["title"] != chunk.current_metadata["title"] for chunk in chunks)


def test_context_quality_modes_isolate_header_raw_effective_and_shuffled_context() -> None:
    chunks: list[EvalChunk] = []
    for index in range(3):
        current = {
            "title": "context_document.docx",
            "document_type": "policy",
            "section_title": f"Section {index}",
            "contextual_summary": f"Raw context {index}.",
            "contextual_search_terms": [f"raw-term-{index}"],
            "year": 2026,
        }
        gold = {
            **current,
            "contextual_summary": f"Effective context {index}.",
            "contextual_search_terms": [f"gold-term-{index}"],
        }
        chunks.append(
            replace(
                _chunk(index, text=f"Chunk body {index}."),
                document_id="same-document",
                document_title="context_document.docx",
                current_metadata=current,
                gold_metadata=gold,
            )
        )

    modes = [
        "ctx_a_chunk_only",
        "ctx_b_deterministic_header",
        "ctx_c_raw_context_dense_only",
        "ctx_c_raw_context_sparse_only",
        "ctx_c_raw_context",
        "ctx_d_effective_context",
        "ctx_e_shuffled_context",
    ]
    projections = build_projections(chunks, modes, seed=42, ablation_source="gold")

    assert projections["ctx_a_chunk_only"][0].embedding_text == "Chunk body 0."
    assert projections["ctx_a_chunk_only"][0].retrieval_metadata["year"] == 2026
    header_text = projections["ctx_b_deterministic_header"][0].embedding_text
    assert header_text.startswith("Document: context document\nDocument type: policy\n")
    assert "Context:" not in header_text
    dense_only = projections["ctx_c_raw_context_dense_only"][0]
    assert "Raw context 0." in dense_only.embedding_text
    assert "Raw context 0." not in dense_only.search_text
    sparse_only = projections["ctx_c_raw_context_sparse_only"][0]
    assert "Raw context 0." not in sparse_only.embedding_text
    assert "Raw context 0." in sparse_only.search_text
    assert "Raw context 0." in projections["ctx_c_raw_context"][0].embedding_text
    assert "raw-term-0" not in projections["ctx_c_raw_context"][0].search_text
    assert "Effective context 0." in projections["ctx_d_effective_context"][0].embedding_text
    shuffled_text = projections["ctx_e_shuffled_context"][0].embedding_text
    assert "Raw context 0." not in shuffled_text
    assert any(f"Raw context {index}." in shuffled_text for index in (1, 2))


def test_filter_ablation_uses_selected_metadata_source() -> None:
    chunk = replace(
        _chunk(0),
        current_metadata={"content_kind": "table"},
        gold_metadata={"content_kind": "table", "project_code": "P16"},
    )

    current = build_projections(
        [chunk],
        ["filter_full"],
        seed=7,
        ablation_source="current",
    )
    gold = build_projections(
        [chunk],
        ["filter_full"],
        seed=7,
        ablation_source="gold",
    )

    assert current["filter_full"][0].retrieval_metadata == {"content_kind": "table"}
    assert gold["filter_full"][0].retrieval_metadata["project_code"] == "P16"


def test_shuffled_context_never_crosses_document_boundaries() -> None:
    chunks = []
    for document in ("a", "b"):
        for index in range(3):
            metadata = {
                "title": f"{document}.docx",
                "contextual_summary": f"{document}-context-{index}.",
            }
            chunks.append(
                replace(
                    _chunk(index),
                    id=f"{document}-{index}",
                    document_id=document,
                    document_title=f"{document}.docx",
                    current_metadata=metadata,
                )
            )

    shuffled = _shuffled_context_summaries(chunks, seed=7)

    for chunk in chunks:
        donor_summary = shuffled[chunk.id]
        assert donor_summary is not None
        assert donor_summary.startswith(f"{chunk.document_id}-context-")
        assert donor_summary != chunk.current_metadata["contextual_summary"]


def test_context_quality_audit_hard_rejects_incomplete_or_unsupported_context() -> None:
    metadata = {
        "title": "Chính sách đổi trả",
        "section_title": "Thời hạn",
        "department": "CSKH",
    }
    valid = score_context(
        "Quy định này áp dụng cho yêu cầu đổi trả do bộ phận CSKH tiếp nhận.",
        chunk_text="Khách hàng có thể gửi yêu cầu đổi trả.",
        metadata=metadata,
        max_words=45,
    )
    incomplete = score_context(
        "Quy định này áp dụng cho yêu cầu đổi trả chưa được",
        chunk_text="Khách hàng có thể gửi yêu cầu đổi trả.",
        metadata=metadata,
        max_words=45,
    )
    unsupported = score_context(
        "Thời hạn xử lý là 999 ngày.",
        chunk_text="Khách hàng có thể gửi yêu cầu đổi trả.",
        metadata=metadata,
        max_words=45,
    )
    boilerplate = score_context(
        "Đoạn thuộc mục Thời hạn, liên quan đến đổi trả.",
        chunk_text="Khách hàng có thể gửi yêu cầu đổi trả.",
        metadata=metadata,
        max_words=45,
    )

    assert valid["completeness_score"] == 2
    assert incomplete["decision"] == "reject"
    assert unsupported["groundedness_score"] == 0
    assert unsupported["decision"] == "reject"
    assert boilerplate["has_boilerplate"] is True
    assert boilerplate["decision"] == "reject"


def test_gold_metadata_fallback_summary_avoids_boilerplate() -> None:
    profile = {
        "document_metadata": {},
        "rules": [
            {
                "section_titles": ["Giao nhận Nhà Ở"],
                "metadata": {
                    "contextual_search_terms": [
                        "Thông Báo Bàn Giao",
                        "không đến nhận bàn giao",
                    ],
                },
            }
        ],
    }
    gold, annotated = _gold_metadata(
        {"section_title": "Giao nhận Nhà Ở"},
        profile,
        page=5,
        text="Thông Báo Bàn Giao quy định trường hợp không đến nhận bàn giao.",
    )

    assert annotated
    assert gold["contextual_summary"] == (
        "Giao nhận Nhà Ở xác định phạm vi liên quan đến "
        "Thông Báo Bàn Giao, không đến nhận bàn giao."
    )
    assert not gold["contextual_summary"].startswith("Đoạn")

    quality = score_context(
        gold["contextual_summary"],
        chunk_text="Thông Báo Bàn Giao quy định trường hợp không đến nhận bàn giao.",
        metadata=gold,
        max_words=45,
    )
    assert quality["has_boilerplate"] is False
    assert quality["completeness_score"] == 2


def test_ground_truth_resolves_to_exact_chunk_ids() -> None:
    chunks = [
        _chunk(0, text="không liên quan"),
        EvalChunk(
            **{
                **_chunk(1, text="Thời hạn đổi trả tối đa 30 ngày").__dict__,
                "document_title": "policy.docx",
            }
        ),
    ]
    test = {
        "id": "q1",
        "query_id": "q1",
        "source_file": "policy.docx",
        "expected": {
            "document_title": "policy.docx",
            "page": 2,
            "page_tolerance": 0,
            "must_include_terms": ["Thời hạn đổi trả", "30 ngày"],
        },
    }

    resolved, audit = resolve_ground_truth([test], chunks)

    assert resolved[0]["relevant_chunk_ids"] == ["chunk-1"]
    assert audit[0]["status"] == "exact_chunk"


def test_current_document_metadata_stays_separate_from_section_aware_gold() -> None:
    profile = {
        "current_document_metadata": {
            "title": "report.docx",
            "document_type": "market_report",
        },
        "document_metadata": {
            "title": "report.docx",
            "document_type": "market_report",
            "year": 2026,
            "lifecycle_status": "latest",
        },
        "rules": [
            {
                "section_titles": ["3. Price table"],
                "contains_any": ["Project | Price"],
                "metadata": {
                    "table_header": "Project | Price",
                    "project_name": ["Project A"],
                },
            }
        ],
    }
    current = _semantic_metadata(
        {
            "heading": "3. Price table",
            "block_type": "table",
            "retrieval_metadata": {"section_title": "3. Price table"},
        },
        profile,
    )

    assert current["title"] == "report.docx"
    assert "year" not in current

    gold, annotated = _gold_metadata(
        current,
        profile,
        page=1,
        text="| Project | Price |\n| Project A | 10 |",
    )

    assert annotated
    assert gold["year"] == 2026
    assert gold["table_header"] == "Project | Price"
    assert gold["project_name"] == ["Project A"]
    assert "contextual_summary" not in gold


def test_scorer_prefers_resolved_chunk_id_over_strict_term_matching() -> None:
    expected = {
        "document_title": "policy.docx",
        "must_include_terms": ["a term absent from the excerpt"],
        "relevant_chunk_ids": ["gold-chunk"],
    }

    assert is_hit({"chunk_id": "gold-chunk", "excerpt": "short evidence"}, expected)
    assert not is_hit({"chunk_id": "other", "excerpt": "short evidence"}, expected)


def test_hashing_run_is_never_reported_as_production_pass() -> None:
    modes = [
        {
            "mode": mode,
            "count": "1",
            "recall_at_5": "1",
            "mrr_at_10": "1",
            "term_hit_rate_at_5": "1",
            "forbidden_top1_rate": "0",
            "empty_result_rate": "0",
            "top1_mojibake_rate": "0",
            "latency_p95_ms": "10",
        }
        for mode in (
            "no_metadata",
            "current_metadata",
            "shuffled_metadata",
            "gold_metadata",
        )
    ]
    comparisons = [
        {
            "comparison": name,
            "metric": "recall_at_5",
            "absolute_delta": "0.1",
        }
        for name in ("B_minus_A", "B_minus_C", "D_minus_B")
    ]

    report = build_report(
        summary_rows=modes,
        comparison_rows=comparisons,
        manifest={
            "query_count": 1,
            "production_comparable": False,
            "embedding_provider": "hashing",
            "embedding_model": "hashing-char-trigram-256",
            "ground_truth_unresolved_count": 0,
        },
    )

    assert report["verdict"] == "proxy_only"


def test_benchmark_v2_has_300_queries_and_30_per_primary_slice() -> None:
    corpus, tests, manifest = build_benchmark()

    assert len(corpus) == 270
    assert len(tests) == 300
    assert set(manifest["primary_slice_counts"]) == set(PRIMARY_SLICES)
    assert all(count == 30 for count in manifest["primary_slice_counts"].values())
    assert manifest["split_counts"] == {"dev": 60, "test": 240}


def test_resolver_accepts_explicit_multi_hop_null_and_permission_ground_truth() -> None:
    chunks = [_chunk(0), _chunk(1), _chunk(2)]
    tests = [
        {
            "id": "multi",
            "source_file": "fixture",
            "target_type": "multi_hop",
            "relevant_chunk_ids": ["chunk-0", "chunk-1"],
            "relevant_chunk_groups": [["chunk-0"], ["chunk-1"]],
            "expected": {},
        },
        {
            "id": "null",
            "source_file": "fixture",
            "target_type": "null",
            "relevant_chunk_ids": [],
            "expected": {},
        },
        {
            "id": "permission",
            "source_file": "fixture",
            "target_type": "permission",
            "protected_chunk_ids": ["chunk-2"],
            "relevant_chunk_ids": [],
            "expected": {},
        },
        {
            "id": "permission-denied",
            "source_file": "fixture",
            "target_type": "permission_denied",
            "protected_chunk_ids": ["chunk-2"],
            "relevant_chunk_ids": [],
            "expected": {},
        },
        {
            "id": "permission-allowed",
            "source_file": "fixture",
            "target_type": "permission_allowed",
            "relevant_chunk_ids": ["chunk-2"],
            "expected": {},
        },
    ]

    _, audit = resolve_ground_truth(tests, chunks)

    assert [row["status"] for row in audit] == [
        "explicit_multi_hop",
        "negative_no_match",
        "protected_chunk",
        "protected_chunk",
        "explicit_chunk_ids",
    ]


def test_metadata_condition_and_acl_are_both_enforced() -> None:
    accessible = EvidenceChunk(
        id="allowed",
        document_id="doc",
        text="evidence",
        metadata={"year": 2026, "visibility": "internal"},
    )
    restricted = EvidenceChunk(
        id="restricted",
        document_id="secret",
        text="secret",
        metadata={
            "year": 2026,
            "visibility": "restricted",
            "allowed_groups": ["admin"],
        },
    )
    conditions = ({"field": "year", "op": "eq", "value": 2026},)

    assert _candidate_allowed(
        accessible,
        filterable_fields=frozenset({"year"}),
        metadata_conditions=conditions,
        user_groups=("student",),
    )
    assert not _candidate_allowed(
        restricted,
        filterable_fields=frozenset({"year"}),
        metadata_conditions=conditions,
        user_groups=("student",),
    )
    assert _candidate_allowed(
        restricted,
        filterable_fields=frozenset({"year"}),
        metadata_conditions=conditions,
        user_groups=("admin",),
    )


def test_scorer_uses_type_specific_success_for_multi_hop_null_and_permission() -> None:
    base = {
        "query_type": "benchmark",
        "category": "benchmark",
        "difficulty": "hard",
        "query": "q",
        "expected": {
            "document_title": "",
            "must_include_terms": [],
            "should_include_terms": [],
            "forbidden_document_titles": [],
        },
    }
    tests = [
        {
            **base,
            "id": "multi",
            "answerable": True,
            "target_type": "multi_hop",
            "relevant_chunk_ids": ["a", "b"],
            "relevant_chunk_groups": [["a"], ["b"]],
        },
        {**base, "id": "null", "answerable": False, "target_type": "null"},
        {
            **base,
            "id": "permission",
            "answerable": False,
            "target_type": "permission",
            "protected_chunk_ids": ["secret"],
        },
    ]
    results = [
        {
            "test_id": "multi",
            "mode": "m",
            "results": [{"chunk_id": "a"}, {"chunk_id": "b"}],
        },
        {"test_id": "null", "mode": "m", "results": []},
        {"test_id": "permission", "mode": "m", "results": []},
    ]

    details, summaries = score(tests, results, [1, 5, 10])
    by_id = {row["test_id"]: row for row in details}

    assert by_id["multi"]["all_evidence_groups_at_5"] == 1
    assert by_id["null"]["null_rejection_at_10"] == 1
    assert by_id["permission"]["permission_leak_at_10"] == 0
    assert summaries[0]["success_at_5"] == 1


def test_first_phrase_preserves_thousands_separator_and_unit() -> None:
    assert _first_phrase("hồ bơi nổi 5.000 m²; golf") == "hồ bơi nổi 5.000 m²"
    assert _first_phrase("cảng quốc tế và khoảng 7.000 phòng khách sạn") == (
        "cảng quốc tế và khoảng 7.000 phòng khách sạn"
    )


def test_fail_closed_skips_search_when_filter_field_is_not_indexed() -> None:
    class FakeIndex:
        filterable_fields = frozenset({"document_type"})

        def __init__(self) -> None:
            self.calls = 0

        def search(self, *_args: object, **_kwargs: object) -> tuple[object, ...]:
            self.calls += 1
            return ()

    index = FakeIndex()
    rows = run_queries(
        tests=[
                {
                    "id": "null",
                    "query_id": "null",
                    "query": "q",
                "query_context": {},
                "retrieval_filters": {
                    "metadata_conditions": [
                        {"field": "year", "op": "eq", "value": 2027}
                    ],
                    "unsupported_field_policy": "fail_closed",
                },
            }
        ],
        indexes={"mode": index},  # type: ignore[dict-item]
        query_vectors={"q": (1.0,)},
        chunks_by_id={},
        repeats=1,
        candidate_k=5,
        top_k=5,
        embedding_provider="hashing",
    )

    assert index.calls == 0
    assert rows[0]["results"] == []
    assert rows[0]["filter_preflight_pass"] is False
    assert rows[0]["filter_preflight_status"] == "failed_closed"


def test_filter_field_ablation_removes_only_the_selected_condition() -> None:
    class FakeIndex:
        filterable_fields = frozenset({"document_type", "year"})

        def __init__(self) -> None:
            self.conditions: list[tuple[dict[str, object], ...]] = []

        def search(self, *_args: object, **kwargs: object) -> tuple[object, ...]:
            self.conditions.append(kwargs["metadata_conditions"])  # type: ignore[arg-type]
            return ()

    full = FakeIndex()
    drop_year = FakeIndex()
    rows = run_queries(
        tests=[
            {
                "id": "q",
                "query_id": "q",
                "query": "q",
                "query_context": {},
                "retrieval_filters": {
                    "metadata_conditions": [
                        {"field": "document_type", "op": "eq", "value": "report"},
                        {"field": "year", "op": "eq", "value": 2026},
                    ],
                    "unsupported_field_policy": "fail_closed",
                },
            }
        ],
        indexes={
            "filter_full": full,  # type: ignore[dict-item]
            "filter_drop_year": drop_year,  # type: ignore[dict-item]
        },
        query_vectors={"q": (1.0,)},
        chunks_by_id={},
        repeats=1,
        candidate_k=5,
        top_k=5,
        embedding_provider="hashing",
    )

    by_mode = {row["mode"]: row for row in rows}
    assert by_mode["filter_full"]["removed_metadata_filter_fields"] == []
    assert by_mode["filter_drop_year"]["removed_metadata_filter_fields"] == ["year"]
    assert by_mode["filter_drop_year"]["applied_metadata_filter_fields"] == [
        "document_type"
    ]
    assert all(
        [condition["field"] for condition in call] == ["document_type"]
        for call in drop_year.conditions
    )


def test_dynamic_filter_field_ablation_removes_requested_field() -> None:
    class FakeIndex:
        filterable_fields = frozenset({"domain", "project_code"})

        def __init__(self) -> None:
            self.conditions: list[tuple[dict[str, object], ...]] = []

        def search(self, *_args: object, **kwargs: object) -> tuple[object, ...]:
            self.conditions.append(kwargs["metadata_conditions"])  # type: ignore[arg-type]
            return ()

    full = FakeIndex()
    drop_project_code = FakeIndex()
    rows = run_queries(
        tests=[
            {
                "id": "q-dynamic",
                "query_id": "q-dynamic",
                "query": "P16",
                "query_context": {},
                "retrieval_filters": {
                    "metadata_conditions": [
                        {"field": "domain", "op": "eq", "value": "real_estate"},
                        {"field": "project_code", "op": "eq", "value": "P16"},
                    ],
                    "unsupported_field_policy": "fail_closed",
                },
            }
        ],
        indexes={
            "filter_full": full,  # type: ignore[dict-item]
            "filter_drop_project_code": drop_project_code,  # type: ignore[dict-item]
        },
        query_vectors={"P16": (1.0,)},
        chunks_by_id={},
        repeats=1,
        candidate_k=5,
        top_k=5,
        embedding_provider="hashing",
    )

    by_mode = {row["mode"]: row for row in rows}
    assert by_mode["filter_drop_project_code"]["removed_metadata_filter_fields"] == [
        "project_code"
    ]
    assert all(
        [condition["field"] for condition in call] == ["domain"]
        for call in drop_project_code.conditions
    )


def test_scorer_checks_paired_permission_and_structured_table_contracts() -> None:
    base = {
        "query_type": "benchmark",
        "category": "benchmark",
        "difficulty": "hard",
        "query": "same query",
        "expected": {
            "document_title": "secret.docx",
            "must_include_terms": [],
            "should_include_terms": [],
            "forbidden_document_titles": [],
        },
    }
    tests = [
        {
            **base,
            "id": "allow",
            "answerable": True,
            "target_type": "permission_allowed",
            "relevant_chunk_ids": ["secret"],
            "expected": {
                **base["expected"],
                "must_cite_document_titles": ["secret.docx"],
            },
        },
        {
            **base,
            "id": "deny",
            "answerable": False,
            "target_type": "permission_denied",
            "protected_chunk_ids": ["secret"],
            "expected": {
                **base["expected"],
                "document_title": "",
                "must_not_include_terms": ["classified value"],
                "must_not_cite_document_titles": ["secret.docx"],
            },
        },
        {
            **base,
            "id": "table",
            "answerable": True,
            "target_type": "single",
            "relevant_chunk_ids": ["table-chunk"],
            "expected": {
                **base["expected"],
                "table_id": "docx-table-3",
                "expected_cell_value": "30 ngày",
            },
        },
    ]
    results = [
        {
            "test_id": "allow",
            "mode": "m",
            "results": [
                {
                    "chunk_id": "secret",
                    "document_title": "secret.docx",
                    "excerpt": "classified value",
                }
            ],
        },
        {"test_id": "deny", "mode": "m", "results": []},
        {
            "test_id": "table",
            "mode": "m",
            "results": [
                {
                    "chunk_id": "table-chunk",
                    "document_title": "secret.docx",
                    "table_id": "docx-table-3",
                    "excerpt": "Thời hạn đổi trả là 30 ngày",
                }
            ],
        },
    ]

    details, summaries = score(tests, results, [1, 5, 10])
    by_id = {row["test_id"]: row for row in details}

    assert by_id["allow"]["permission_allowed_hit_at_5"] == 1
    assert by_id["allow"]["all_required_documents_at_5"] == 1
    assert by_id["deny"]["permission_safe_at_5"] == 1
    assert by_id["deny"]["sensitive_term_leak_at_5"] == 0
    assert by_id["table"]["table_structured_hit_at_5"] == 1
    assert summaries[0]["permission_allowed_recall_at_5"] == 1
    assert summaries[0]["table_structured_success_at_5"] == 1
