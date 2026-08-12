"""Controlled P6 query-resolution, retrieval and citation evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from app.generation.application.citation_validation import (
    CitationValidationError,
    validate_p5_citation_contract,
)
from app.generation.application.enterprise_context import build_enterprise_generation_context
from app.generation.application.evidence_context import (
    EvidenceContextPolicy,
)
from app.retrieval.application.conversation_query import resolve_conversation_query
from app.retrieval.application.enterprise_evidence import (
    candidate_reference_year,
    select_enterprise_evidence,
)
from app.retrieval.domain.models import EvidenceChunk, RetrievalCandidate, RetrievalFilters

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "evaluation" / "p6_enterprise_query.json"
DATA = {
    split: ROOT / "datasets" / "rag_p6" / f"enterprise_p6_queries_v1_{split}.jsonl"
    for split in ("dev", "test")
}
REPORT = {
    split: (
        ROOT / "reports" / "evaluation" / f"enterprise_p6_retrieval_{split}.json",
        ROOT / "reports" / "evaluation" / f"enterprise_p6_retrieval_{split}.md",
    )
    for split in ("dev", "test")
}


def _candidate(cid: str, doc: str, text: str, score: float, **meta: object) -> RetrievalCandidate:
    return RetrievalCandidate(EvidenceChunk(cid, doc, text, meta), score, 1)


def _fixture(row: dict[str, Any]) -> tuple[tuple[RetrievalCandidate, ...], set[str], set[str]]:
    prefix = str(row["id"])
    entity, label, value = row["entity"], row["predicate_label"], row["value"]
    digest = hashlib.sha256(f"{entity}:{value}".encode()).hexdigest()
    common = {"owner_id": "owner-visible", "structured_predicate": row["predicate"]}
    candidates = [
        _candidate(
            f"{prefix}-method",
            f"{prefix}-method-doc",
            f"Phương pháp tổng hợp {label} năm 2025.",
            0.99,
            reference_year=2025,
            content_kind="methodology",
            **common,
        ),
        _candidate(
            f"{prefix}-2023",
            f"{prefix}-2023-doc",
            f"{entity}: 40 đơn vị năm 2023.",
            0.72,
            reference_year=2023,
            structured_value={"amount": 40},
            version_family_id=prefix,
            p4_relation_type="VERSION_UPDATE",
            is_current=False,
            **common,
        ),
        _candidate(
            f"{prefix}-2025",
            f"{prefix}-2025-doc",
            f"{label.capitalize()} {entity} năm 2025 là {value}.",
            0.97,
            reference_year=2025,
            structured_value={"display": value},
            version_family_id=prefix,
            p4_relation_type="VERSION_UPDATE",
            is_current=False,
            normalized_content_hash=digest,
            normalization_version="v2",
            content_kind="table_row",
            **common,
        ),
        _candidate(
            f"{prefix}-copy",
            f"{prefix}-copy-doc",
            f"{label.capitalize()} {entity} năm 2025 là {value}.",
            0.96,
            reference_year=2025,
            structured_value={"display": value},
            normalized_content_hash=digest,
            normalization_version="v2",
            **common,
        ),
        _candidate(
            f"{prefix}-2026",
            f"{prefix}-2026-doc",
            f"{entity}: 55 đơn vị năm 2026.",
            0.58,
            reference_year=2026,
            structured_value={"amount": 55},
            version_family_id=prefix,
            p4_relation_type="VERSION_UPDATE",
            is_current=True,
            **common,
        ),
        _candidate(
            f"{prefix}-hidden",
            f"{prefix}-hidden-doc",
            f"Bí mật: {entity} 999 năm 2025.",
            1.0,
            reference_year=2025,
            structured_value={"amount": 999},
            owner_id="owner-hidden",
        ),
    ]
    scenario = row["scenario"]
    expected = {f"{prefix}-2025"}
    values = set(expected)
    if scenario == "historical_explicit_year":
        expected = values = {f"{prefix}-2023"}
    elif scenario == "current_latest":
        expected = values = {f"{prefix}-2026"}
    elif scenario in {"temporal_comparison", "multi_document_comparison"}:
        expected = values = {f"{prefix}-2023", f"{prefix}-2025", f"{prefix}-2026"}
    elif scenario == "version_comparison":
        expected = values = {f"{prefix}-2023", f"{prefix}-2026"}
    elif scenario == "conditional_variant" or scenario == "followup_qualifier_override":
        candidates = [
            _candidate(
                f"{prefix}-wltp",
                f"{prefix}-wltp-doc",
                f"{entity} WLTP 450 km.",
                0.9,
                p4_relation_type="CONDITIONAL_VARIANT",
                conditional_variant_group_id=prefix,
                test_protocol="WLTP",
                **common,
            ),
            _candidate(
                f"{prefix}-epa",
                f"{prefix}-epa-doc",
                f"{entity} EPA 420 km.",
                0.8,
                p4_relation_type="CONDITIONAL_VARIANT",
                conditional_variant_group_id=prefix,
                test_protocol="EPA",
                **common,
            ),
        ]
        expected = values = {f"{prefix}-epa"}
    elif scenario == "conflict":
        candidates = [
            _candidate(
                f"{prefix}-left",
                f"{prefix}-left-doc",
                f"{entity} năm 2025 là 48 đơn vị.",
                0.8,
                reference_year=2025,
                conflict_group_id=prefix,
                p4_relation_type="CONFLICT",
                **common,
            ),
            _candidate(
                f"{prefix}-right",
                f"{prefix}-right-doc",
                f"{entity} năm 2025 là 52 đơn vị.",
                0.7,
                reference_year=2025,
                conflict_group_id=prefix,
                p4_relation_type="CONFLICT",
                **common,
            ),
        ]
        expected = values = {f"{prefix}-left", f"{prefix}-right"}
    elif scenario == "uncertain_evidence":
        candidates[2] = _candidate(
            f"{prefix}-2025",
            f"{prefix}-2025-doc",
            f"Ước tính {entity} năm 2025 là {value}.",
            0.61,
            reference_year=2025,
            structured_value={"display": value},
            p4_relation_type="UNCERTAIN",
            **common,
        )
        candidates = [candidates[0], candidates[2], candidates[-1]]
    return tuple(candidates), expected, values


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(round((len(ordered) - 1) * q), len(ordered) - 1)]


def evaluate(split: Literal["dev", "test"], *, overwrite_dev: bool = False) -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if split == "test":
        if config.get("status") != "frozen":
            raise ValueError("P6 TEST requires frozen config")
        if any(path.exists() for path in REPORT[split]):
            raise FileExistsError("P6 TEST report is immutable")
        for path, digest in config["frozen_inputs_sha256"].items():
            actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest().upper()
            if actual != digest:
                raise ValueError(f"Frozen P6 input changed: {path}")
    rows = [json.loads(line) for line in DATA[split].read_text(encoding="utf-8").splitlines()]
    cases, timings = [], []
    for row in rows:
        started = time.perf_counter_ns()
        query = resolve_conversation_query(
            row["query"], row["history"], owner_id="owner-visible", notebook_id=None
        )
        candidates, expected, value_ids = _fixture(row)
        filters = RetrievalFilters(owner_id="owner-visible")
        selection = select_enterprise_evidence(
            query,
            candidates,
            filters=filters,
            top_k=int(config["retrieval"]["top_k"]),
            max_chunks_per_document=int(config["retrieval"]["max_chunks_per_document"]),
        )
        context = build_enterprise_generation_context(
            query,
            selection.evidence,
            authorized_document_ids=frozenset(
                item.chunk.document_id
                for item in candidates
                if item.chunk.metadata.get("owner_id") == "owner-visible"
            ),
            policy=EvidenceContextPolicy(
                max_evidence_items=int(config["context"]["max_evidence_items"]),
                max_characters=int(config["context"]["max_characters"]),
                characters_per_token=float(config["context"]["characters_per_token"]),
                version="p6-enterprise-generation-context-v1",
            ),
        )
        selected = {item.chunk_id for item in context.evidence}
        aliases = tuple(item.evidence_id for item in context.evidence)
        answer = " ".join(
            f"{item.text.rstrip('.')} [{item.evidence_id}]." for item in context.evidence
        )
        citation_ok = True
        if aliases:
            try:
                validate_p5_citation_contract(answer, context=context, accepted_source_ids=aliases)
            except CitationValidationError:
                citation_ok = False
        expected_years = {
            candidate_reference_year(item) for item in candidates if item.chunk.id in expected
        }
        selected_years = {candidate_reference_year(item.candidate) for item in context.evidence}
        followup = str(row["scenario"]).startswith("followup")
        query_ok = (not followup or bool(query.inherited_dimensions)) and not (
            {2023, 2026} & set(query.reference_years)
            if row["scenario"] == "followup_year_override"
            else False
        )
        cases.append(
            {
                "scenario": row["scenario"],
                "recall": len(selected & expected) / len(expected),
                "precision": len(selected & expected) / max(len(selected), 1),
                "value_recall": len(selected & value_ids) / len(value_ids),
                "temporal": len((selected_years & expected_years) - {None})
                / max(len(expected_years - {None}), 1),
                "query_ok": query_ok,
                "conflict_ok": row["scenario"] != "conflict" or expected <= selected,
                "conditional_ok": row["scenario"]
                not in {"conditional_variant", "followup_qualifier_override"}
                or selected == expected,
                "current_ok": row["scenario"] != "current_latest" or selected == expected,
                "historical_ok": row["scenario"] != "historical_explicit_year"
                or selected == expected,
                "permission_leak": any("hidden" in item for item in selected),
                "citation_ok": citation_ok,
                "duplicate_slots": sum(
                    item.chunk.id.endswith("copy") for item in selection.evidence
                ),
                "baseline_duplicate_slots": sum(
                    item.chunk.id.endswith("copy") for item in candidates[:10]
                ),
                "provenance_ok": all(
                    (item.provenance.occurrence_count >= 2)
                    for item in context.evidence
                    if item.duplicate_group
                ),
            }
        )
        timings.append((time.perf_counter_ns() - started) / 1_000_000)

    def scoped(key: str, scenarios: set[str]) -> list[float]:
        return [float(case[key]) for case in cases if case["scenario"] in scenarios]

    metrics = {
        "evidence_recall_at_10": _mean([case["recall"] for case in cases]),
        "evidence_precision_at_10": _mean([case["precision"] for case in cases]),
        "temporal_coverage_recall": _mean(
            scoped(
                "temporal",
                {"temporal_comparison", "version_comparison", "multi_document_comparison"},
            )
        ),
        "requested_year_coverage": _mean(
            scoped("temporal", {"historical_explicit_year", "followup_year_override"})
        ),
        "followup_resolution_accuracy": _mean(
            scoped("query_ok", {"followup_year_override", "followup_qualifier_override"})
        ),
        "value_bearing_evidence_recall": _mean([case["value_recall"] for case in cases]),
        "historical_selection_accuracy": _mean(
            scoped("historical_ok", {"historical_explicit_year"})
        ),
        "current_version_accuracy": _mean(scoped("current_ok", {"current_latest"})),
        "conditional_selection_accuracy": _mean(
            scoped("conditional_ok", {"conditional_variant", "followup_qualifier_override"})
        ),
        "conflict_preservation_recall": _mean(scoped("conflict_ok", {"conflict"})),
        "permission_leakage": sum(case["permission_leak"] for case in cases),
        "citation_support_accuracy": _mean([float(case["citation_ok"]) for case in cases]),
        "provenance_retention": _mean([float(case["provenance_ok"]) for case in cases]),
        "duplicate_slot_waste_baseline": _mean(
            [case["baseline_duplicate_slots"] for case in cases]
        ),
        "duplicate_slot_waste_p6": _mean([case["duplicate_slots"] for case in cases]),
    }
    report = {
        "split": split,
        "dataset_count": len(rows),
        "category_counts": dict(Counter(row["scenario"] for row in rows)),
        "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest().upper(),
        "metrics": metrics,
        "latency_ms": {
            "controlled_pre_llm_mean": statistics.mean(timings),
            "controlled_pre_llm_p50": _pct(timings, 0.5),
            "controlled_pre_llm_p95": _pct(timings, 0.95),
            "production_db_explain": "not_executed",
        },
        "failures": [
            case
            for case in cases
            if case["recall"] < 1 or case["permission_leak"] or not case["citation_ok"]
        ],
        "test_policy": "immutable; one run; no post-TEST tuning"
        if split == "test"
        else "DEV tuning allowed",
    }
    json_path, md_path = REPORT[split]
    json_path.parent.mkdir(parents=True, exist_ok=True)
    if split == "dev" and json_path.exists() and not overwrite_dev:
        raise FileExistsError("DEV report exists; pass --overwrite-dev")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Enterprise P6 {str(report['split']).upper()} evaluation",
        "",
        f"Queries: **{report['dataset_count']}**",
        "",
        "## Metrics",
        "",
    ]
    lines.extend(f"- {key}: `{value:.6f}`" for key, value in report["metrics"].items())
    lines.extend(
        [
            "",
            "## Latency",
            "",
            "Controlled in-process timing only; production PostgreSQL EXPLAIN "
            "and SLA remain unresolved.",
            "",
            f"- mean: `{report['latency_ms']['controlled_pre_llm_mean']:.4f} ms`",
            f"- p50: `{report['latency_ms']['controlled_pre_llm_p50']:.4f} ms`",
            f"- p95: `{report['latency_ms']['controlled_pre_llm_p95']:.4f} ms`",
            "",
            f"Failures: **{len(report['failures'])}**",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--overwrite-dev", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.split, overwrite_dev=args.overwrite_dev)
    print(json.dumps(result["metrics"], indent=2))
