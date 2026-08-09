"""Regression gates for the Vietnamese knowledge-quality benchmark."""

from __future__ import annotations

from typing import cast

from tests.evaluation.knowledge_quality_benchmark import (
    DEFAULT_JSON_REPORT_PATH,
    DEFAULT_MARKDOWN_REPORT_PATH,
    RELATION_LABELS,
    load_dataset,
    predict_relation_label,
    render_json_report,
    render_markdown_report,
    run_benchmark,
)


def test_dataset_is_versioned_balanced_and_covers_required_vietnamese_cases() -> None:
    cases = load_dataset()

    assert len(cases) == 29
    assert {case.relation_label for case in cases} == set(RELATION_LABELS)
    eligible_counts = {
        label: sum(case.eligible_for_comparison and case.relation_label == label for case in cases)
        for label in RELATION_LABELS
    }
    assert all(count >= 5 for count in eligible_counts.values())

    phenomena = {phenomenon for case in cases for phenomenon in case.phenomena}
    assert {
        "unit",
        "date",
        "negation",
        "policy",
        "permission-scope",
        "cross-owner",
        "cross-notebook",
    }.issubset(phenomena)
    assert all(
        any("\u00c0" <= character <= "\u1ef9" for character in case.source.text)
        or any("\u00c0" <= character <= "\u1ef9" for character in case.target.text)
        for case in cases
    )


def test_cross_scope_pairs_are_never_compared_or_reused() -> None:
    cross_scope_cases = tuple(case for case in load_dataset() if not case.same_permission_scope)

    assert len(cross_scope_cases) == 3
    assert all(not case.eligible_for_comparison for case in cross_scope_cases)
    assert all(not case.expected_auto_reuse for case in cross_scope_cases)
    assert all(predict_relation_label(case) is None for case in cross_scope_cases)


def test_unit_date_negation_and_policy_conflicts_are_mandatory_regressions() -> None:
    cases = load_dataset()
    mandatory_ids = {
        "conflict-unit-only-05",
        "conflict-effective-date-02",
        "conflict-remote-negation-03",
        "conflict-expense-approval-04",
    }
    mandatory = {case.id: case for case in cases if case.id in mandatory_ids}

    assert set(mandatory) == mandatory_ids
    assert {case_id: predict_relation_label(case) for case_id, case in mandatory.items()} == {
        case_id: "conflict" for case_id in mandatory_ids
    }


def test_benchmark_passes_safety_classification_and_mode_gates() -> None:
    report = run_benchmark()
    classification = cast(dict[str, object], report["classification"])
    safety = cast(dict[str, object], report["safety"])
    retrieval = cast(dict[str, object], report["retrieval_proxy"])
    modes = cast(dict[str, dict[str, object]], retrieval["modes"])
    gates = cast(dict[str, object], report["gates"])

    assert gates["all_passed"] is True
    assert safety["exact_auto_reuse_false_positive_rate"] == 0.0
    assert safety["cross_scope_suppression_rate"] == 1.0
    assert classification["errors"] == []
    assert modes["shadow"] == modes["off"]
    on_quality = modes["on"]["retrieval_quality_proxy"]
    off_quality = modes["off"]["retrieval_quality_proxy"]
    assert isinstance(on_quality, int | float)
    assert isinstance(off_quality, int | float)
    assert on_quality > off_quality
    assert modes["on"]["duplicate_redundancy_rate"] == 0.0
    assert modes["on"]["stale_version_exposure_rate"] == 0.0
    assert modes["on"]["conflict_both_sides_rate"] == 1.0
    assert modes["on"]["distinct_preservation_rate"] == 1.0


def test_benchmark_is_deterministic_and_checked_in_reports_are_current() -> None:
    first = run_benchmark()
    second = run_benchmark()

    assert first == second
    assert DEFAULT_JSON_REPORT_PATH.read_text(encoding="utf-8") == (render_json_report(first))
    assert DEFAULT_MARKDOWN_REPORT_PATH.read_text(encoding="utf-8") == (
        render_markdown_report(first)
    )
