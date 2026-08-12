"""Run the frozen P0 baseline against current deterministic production logic."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from app.bootstrap.settings import Settings
from app.knowledge_quality.application.analysis import (
    analyze_text_relation,
    build_chunk_fingerprint,
    strict_normalize_text,
)
from app.knowledge_quality.application.chunk_preembedding import (
    DEFAULT_MAX_SIMHASH_DISTANCE,
    build_chunk_dedup_probes,
    simhash_hamming_distance,
    simhash_lsh_bands,
)
from app.pipeline.documents.domain.parsed import ParsedTable
from app.pipeline.indexing.application.chunker import ChunkData
from app.pipeline.shared.text_utils import compute_checksum_text, normalize_text
from app.structured_facts.application.table_analyzer import analyze_table
from app.structured_facts.application.table_diff import diff_table_analyses
from evaluation.duplicate_conflict.constants import (
    CANDIDATE_DISTRACTOR_COUNT,
    CANDIDATE_EVALUATION_LIMIT,
    FULL_DATASET_PATH,
    JSON_REPORT_PATH,
    MARKDOWN_REPORT_PATH,
    RUNTIME_CANDIDATES_PER_PROBE,
    SCHEMA_VERSION,
    STRESS_CASES_PATH,
)
from evaluation.duplicate_conflict.metrics import (
    classification_metrics,
    distribution,
    recall_at_k,
)
from evaluation.duplicate_conflict.models import (
    FailureCategory,
    GoldPair,
    GoldRelation,
    SourceForm,
)
from evaluation.duplicate_conflict.validation import load_pairs, validate_pairs

RELATION_MAPPING = {
    "exact_content": GoldRelation.EXACT_DUPLICATE.value,
    "technical_duplicate": GoldRelation.EXACT_DUPLICATE.value,
    "near_duplicate": GoldRelation.NEAR_DUPLICATE.value,
    "version_candidate": GoldRelation.VERSION_UPDATE.value,
    "version": GoldRelation.VERSION_UPDATE.value,
    "temporal_series": GoldRelation.TEMPORAL_VARIANT.value,
    "template_variant": GoldRelation.TEMPLATE_VARIANT.value,
    "conflict_candidate": GoldRelation.CONFLICT.value,
    "conflict": GoldRelation.CONFLICT.value,
    "distinct": GoldRelation.DISTINCT.value,
    "related": GoldRelation.UNCERTAIN.value,
}
LABELS = tuple(relation.value for relation in GoldRelation)
NOISE_RANK = {"none": 0, "light": 1, "medium": 2, "severe": 3}


@dataclass(frozen=True, slots=True)
class CandidateResult:
    rank: int | None
    returned_count: int
    exact_identity: bool
    lsh_band_matches: int
    hamming_distance: int
    admitted_to_classifier: bool


@dataclass(frozen=True, slots=True)
class PairResult:
    pair_id: str
    split: str
    domain: str
    category: str
    expected: str
    oracle_prediction: str
    runtime_prediction: str | None
    raw_relation: str
    confidence: float
    reason_codes: tuple[str, ...]
    candidate: CandidateResult
    auto_reuse_eligible: bool
    false_auto_reuse: bool
    failure_category: str | None


def _stable_order(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _distractors(pair: GoldPair, pairs: tuple[GoldPair, ...]) -> tuple[GoldPair, ...]:
    others = [other for other in pairs if other.pair_id != pair.pair_id]
    ordered = sorted(
        others,
        key=lambda other: (
            other.category != pair.category,
            other.domain != pair.domain,
            _stable_order(pair.pair_id, other.pair_id),
        ),
    )
    return tuple(ordered[:CANDIDATE_DISTRACTOR_COUNT])


def _candidate_result(pair: GoldPair, pairs: tuple[GoldPair, ...]) -> CandidateResult:
    query = build_chunk_fingerprint(pair.text_a)
    candidates = (pair, *_distractors(pair, pairs))
    eligible: list[tuple[bool, int, str, GoldPair, int]] = []
    target_exact = False
    target_bands = 0
    target_distance = 64
    query_bands = simhash_lsh_bands(query.loose_signature)
    for candidate in candidates:
        fingerprint = build_chunk_fingerprint(candidate.text_b)
        exact = fingerprint.strict_hash == query.strict_hash
        bands = sum(
            left == right
            for left, right in zip(
                query_bands,
                simhash_lsh_bands(fingerprint.loose_signature),
                strict=True,
            )
        )
        distance = simhash_hamming_distance(query.loose_signature, fingerprint.loose_signature)
        if candidate.pair_id == pair.pair_id:
            target_exact, target_bands, target_distance = exact, bands, distance
        # Mirrors the SQL predicate: exact hash OR at least one aligned band.
        if exact or bands:
            eligible.append((exact, bands, candidate.pair_id, candidate, distance))
    eligible.sort(key=lambda item: (-int(item[0]), -item[1], item[2]))
    returned = eligible[:CANDIDATE_EVALUATION_LIMIT]
    rank = next(
        (index for index, item in enumerate(returned, 1) if item[3].pair_id == pair.pair_id),
        None,
    )
    admitted = bool(
        rank is not None
        and rank <= RUNTIME_CANDIDATES_PER_PROBE
        and (target_exact or target_distance <= DEFAULT_MAX_SIMHASH_DISTANCE)
    )
    return CandidateResult(
        rank=rank,
        returned_count=len(returned),
        exact_identity=target_exact,
        lsh_band_matches=target_bands,
        hamming_distance=target_distance,
        admitted_to_classifier=admitted,
    )


def _classify(pair: GoldPair) -> tuple[str, str, float, tuple[str, ...]]:
    analysis = analyze_text_relation(pair.text_a, pair.text_b)
    raw = analysis.relation_type.value
    return (
        RELATION_MAPPING[raw],
        raw,
        analysis.confidence,
        analysis.reason_codes,
    )


def _structured_table_prediction(pair: GoldPair) -> tuple[str, dict[str, int]]:
    if pair.table_a is None or pair.table_b is None:
        raise ValueError("Structured table prediction requires table payloads on both sides")

    def parsed(side: str) -> ParsedTable:
        payload = pair.table_a if side == "a" else pair.table_b
        assert payload is not None
        headers = list(payload.headers)
        return ParsedTable(
            table_id=f"{pair.pair_id}-{side}",
            location="evaluation",
            rows=[headers, *(list(row) for row in payload.rows)],
            columns=len(headers),
            header=headers,
            confidence=1.0,
        )

    left = analyze_table(document_id=f"{pair.pair_id}-a", table=parsed("a"))
    right = analyze_table(document_id=f"{pair.pair_id}-b", table=parsed("b"))
    summary = diff_table_analyses(left, right).summary
    if summary["conflict_candidate"]:
        prediction = GoldRelation.CONFLICT.value
    elif summary["conditional_variant"]:
        prediction = GoldRelation.CONDITIONAL_VARIANT.value
    elif summary["uncertain"]:
        prediction = GoldRelation.UNCERTAIN.value
    elif summary["updated"]:
        prediction = GoldRelation.TEMPORAL_VARIANT.value
    elif summary["added"] or summary["removed"]:
        prediction = GoldRelation.VERSION_UPDATE.value
    elif summary["unchanged"]:
        prediction = GoldRelation.NEAR_DUPLICATE.value
    else:
        prediction = GoldRelation.DISTINCT.value
    return prediction, summary


def _classifier_failure_category(pair: GoldPair, prediction: str) -> str | None:
    if prediction == pair.expected_relation.value:
        return None
    if pair.source_form_a is not pair.source_form_b:
        return FailureCategory.TABLE_PROSE_GAP.value
    if pair.context_a or pair.context_b:
        return FailureCategory.CROSS_CHUNK_CONTEXT_MISSING.value
    if pair.diagnostic_hints:
        return pair.diagnostic_hints[0].value
    if pair.expected_relation is GoldRelation.TEMPORAL_VARIANT:
        return FailureCategory.TEMPORAL_SCOPE_ERROR.value
    if pair.expected_relation in {GoldRelation.CONDITIONAL_VARIANT, GoldRelation.TEMPLATE_VARIANT}:
        return FailureCategory.SCOPE_ERROR.value
    if pair.expected_relation is GoldRelation.CONFLICT:
        return FailureCategory.CLAIM_ALIGNMENT_ERROR.value
    return FailureCategory.CLASSIFIER_THRESHOLD_ERROR.value


def _failure_category(pair: GoldPair, candidate: CandidateResult, prediction: str) -> str | None:
    if pair.candidate_retrieval_required and not candidate.admitted_to_classifier:
        return FailureCategory.CANDIDATE_MISS.value
    if not pair.candidate_retrieval_required and not candidate.admitted_to_classifier:
        return None
    return _classifier_failure_category(pair, prediction)


def evaluate_pair(pair: GoldPair, pairs: tuple[GoldPair, ...]) -> PairResult:
    candidate = _candidate_result(pair, pairs)
    prediction, raw, confidence, reasons = _classify(pair)
    runtime_prediction = prediction if candidate.admitted_to_classifier else None
    strict_identity = strict_normalize_text(pair.text_a) == strict_normalize_text(pair.text_b)
    embedding_identity = compute_checksum_text(
        normalize_text(pair.text_a)
    ) == compute_checksum_text(normalize_text(pair.text_b))
    auto_reuse_eligible = strict_identity and embedding_identity
    false_auto_reuse = auto_reuse_eligible and not pair.expected_auto_reuse
    return PairResult(
        pair_id=pair.pair_id,
        split=pair.split,
        domain=pair.domain.value,
        category=pair.category,
        expected=pair.expected_relation.value,
        oracle_prediction=prediction,
        runtime_prediction=runtime_prediction,
        raw_relation=raw,
        confidence=round(confidence, 6),
        reason_codes=reasons,
        candidate=candidate,
        auto_reuse_eligible=auto_reuse_eligible,
        false_auto_reuse=false_auto_reuse,
        failure_category=_failure_category(pair, candidate, prediction),
    )


def _chunk(index: int) -> ChunkData:
    text = (
        f"Khối tổng hợp số {index + 1} có nội dung vận hành độc lập và đủ dài để "
        "tham gia phép lấy mẫu fuzzy trong kiểm thử tài liệu dài."
    )
    return ChunkData(
        chunk_id=f"stress-{index}",
        chunk_index=index,
        text=text,
        embedding_text=text,
        search_text=text,
        page_number=index // 4 + 1,
        section_title=None,
        checksum=compute_checksum_text(text),
        document_id="stress-document",
        document_version=1,
        section_id=None,
        parent_chunk_id=None,
        offset_start=index * 200,
        offset_end=index * 200 + len(text),
        strategy="stress",
        strategy_version="1",
        config_checksum="stress",
        content_checksum=compute_checksum_text(text),
        source_block_ids=(f"block-{index}",),
        table_identity=None,
        metadata={},
    )


def _stress_results() -> dict[str, object]:
    payload = json.loads(STRESS_CASES_PATH.read_text(encoding="utf-8"))
    long_case = payload["long_document"]
    chunks = tuple(_chunk(index) for index in range(int(long_case["chunk_count"])))
    probes = build_chunk_dedup_probes(chunks, max_fuzzy_probes=int(long_case["max_fuzzy_probes"]))
    sampled = [probe.chunk_index + 1 for probe in probes if probe.include_fuzzy_candidates]
    meaningful = list(long_case["meaningful_positions_1_based"])
    covered = sorted(set(sampled) & set(meaningful))

    lsh_case = payload["simhash_lsh"]
    left = build_chunk_fingerprint(lsh_case["text_a"])
    right = build_chunk_fingerprint(lsh_case["text_b"])
    distance = simhash_hamming_distance(left.loose_signature, right.loose_signature)
    band_overlap = sum(
        a == b
        for a, b in zip(
            simhash_lsh_bands(left.loose_signature),
            simhash_lsh_bands(right.loose_signature),
            strict=True,
        )
    )
    relation = analyze_text_relation(lsh_case["text_a"], lsh_case["text_b"])
    return {
        "long_document_sampling": {
            "chunk_count": len(chunks),
            "max_fuzzy_probes": long_case["max_fuzzy_probes"],
            "sampled_positions_1_based": sampled,
            "meaningful_positions_1_based": meaningful,
            "covered_positions_1_based": covered,
            "meaningful_position_recall": round(len(covered) / len(meaningful), 6),
        },
        "simhash_lsh_counterexample": {
            "hamming_distance": distance,
            "maximum_hamming_distance": DEFAULT_MAX_SIMHASH_DISTANCE,
            "aligned_band_overlap": band_overlap,
            "raw_relation": relation.relation_type.value,
            "candidate_generated": band_overlap > 0,
            "demonstrates_lsh_false_negative": (
                distance <= DEFAULT_MAX_SIMHASH_DISTANCE and band_overlap == 0
            ),
        },
    }


def _effective_defaults() -> dict[str, object]:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    return {
        "knowledge_quality_mode": settings.knowledge_quality_mode,
        "knowledge_quality_max_probe_chunks": settings.knowledge_quality_max_probe_chunks,
        "knowledge_quality_candidates_per_probe": settings.knowledge_quality_candidates_per_probe,
        "knowledge_quality_conflict_prompt_enabled": (
            settings.knowledge_quality_conflict_prompt_enabled
        ),
        "structured_fact_mode": settings.structured_fact_mode,
        "simhash_max_hamming_distance": DEFAULT_MAX_SIMHASH_DISTANCE,
        "simhash_lsh_bands": 8,
        "simhash_lsh_bits_per_band": 8,
    }


def build_report(
    pairs: tuple[GoldPair, ...], *, require_full_dataset: bool = True
) -> dict[str, object]:
    validation = validate_pairs(pairs, require_full=require_full_dataset)
    if not validation.valid:
        raise ValueError("Dataset validation failed: " + "; ".join(validation.errors))
    results = tuple(evaluate_pair(pair, pairs) for pair in pairs)
    required = tuple(
        result
        for result, pair in zip(results, pairs, strict=True)
        if pair.candidate_retrieval_required
    )
    ranks = tuple(result.candidate.rank for result in required)
    reached = tuple(result for result in results if result.candidate.admitted_to_classifier)
    failures = Counter(
        result.failure_category for result in results if result.failure_category is not None
    )
    classifier_failures = Counter(
        category
        for pair, result in zip(pairs, results, strict=True)
        if (category := _classifier_failure_category(pair, result.oracle_prediction)) is not None
    )
    conflict_results = tuple(
        result for result in results if result.expected == GoldRelation.CONFLICT
    )
    non_conflicts = tuple(result for result in results if result.expected != GoldRelation.CONFLICT)
    exact_results = tuple(
        result for result in results if result.expected == GoldRelation.EXACT_DUPLICATE
    )
    form_groups: dict[str, list[PairResult]] = {
        "prose_to_prose": [],
        "table_to_table": [],
        "table_to_prose": [],
    }
    for pair, result in zip(pairs, results, strict=True):
        if pair.source_form_a is SourceForm.PROSE and pair.source_form_b is SourceForm.PROSE:
            key = "prose_to_prose"
        elif pair.source_form_a is SourceForm.TABLE and pair.source_form_b is SourceForm.TABLE:
            key = "table_to_table"
        else:
            key = "table_to_prose"
        form_groups[key].append(result)
    source_form_metrics = {
        key: classification_metrics(
            [result.expected for result in values],
            [result.oracle_prediction for result in values],
            labels=LABELS,
        )
        for key, values in form_groups.items()
    }
    table_pairs = tuple(
        pair
        for pair in pairs
        if pair.source_form_a is SourceForm.TABLE and pair.source_form_b is SourceForm.TABLE
    )
    structured_predictions = tuple(_structured_table_prediction(pair)[0] for pair in table_pairs)
    structured_table_metrics = classification_metrics(
        [pair.expected_relation.value for pair in table_pairs],
        list(structured_predictions),
        labels=LABELS,
    )
    examples: dict[str, list[dict[str, object]]] = {}
    example_categories = set(failures) | set(classifier_failures)
    for category in sorted(
        example_categories,
        key=lambda name: (-max(failures[name], classifier_failures[name]), name),
    ):
        selected: list[dict[str, object]] = []
        for pair, result in zip(pairs, results, strict=True):
            classifier_category = _classifier_failure_category(pair, result.oracle_prediction)
            if category not in {result.failure_category, classifier_category}:
                continue
            selected.append(
                {
                    "pair_id": pair.pair_id,
                    "variation_type": pair.variation_type,
                    "expected": result.expected,
                    "oracle_prediction": result.oracle_prediction,
                    "runtime_prediction": result.runtime_prediction,
                    "text_a": pair.text_a[:180],
                    "text_b": pair.text_b[:180],
                }
            )
            if len(selected) == 5:
                break
        examples[category] = selected
    return {
        "benchmark_version": SCHEMA_VERSION,
        "scope": "deterministic pre-embedding chunk candidate and text-relation baseline",
        "dataset": validation.to_payload(),
        "dataset_breakdown": {
            "difficulty": dict(sorted(Counter(pair.difficulty.value for pair in pairs).items())),
            "source_form": dict(
                sorted(
                    Counter(
                        f"{pair.source_form_a.value}_to_{pair.source_form_b.value}"
                        for pair in pairs
                    ).items()
                )
            ),
            "ocr_noise": dict(
                sorted(
                    Counter(
                        max(
                            (pair.ocr_noise_level_a.value, pair.ocr_noise_level_b.value),
                            key=NOISE_RANK.__getitem__,
                        )
                        for pair in pairs
                    ).items()
                )
            ),
        },
        "runtime_defaults": _effective_defaults(),
        "candidate_generation": {
            "population": len(required),
            **recall_at_k(ranks, (1, 5, 10, 20, 50)),
            "classifier_admission_recall": round(
                sum(result.candidate.admitted_to_classifier for result in required)
                / max(1, len(required)),
                6,
            ),
            "returned_candidate_count": distribution(
                result.candidate.returned_count for result in required
            ),
            "ranked_by": "exact hash, aligned LSH band count, stable identifier",
        },
        "oracle_pair_classification": classification_metrics(
            [result.expected for result in results],
            [result.oracle_prediction for result in results],
            labels=LABELS,
        ),
        "reached_classifier_classification": classification_metrics(
            [result.expected for result in reached],
            [result.oracle_prediction for result in reached],
            labels=LABELS,
        ),
        "source_form_classification": source_form_metrics,
        "structured_table_to_table_classification": structured_table_metrics,
        "safety": {
            "false_auto_reuse_count": sum(result.false_auto_reuse for result in results),
            "auto_reuse_eligible_count": sum(result.auto_reuse_eligible for result in results),
            "exact_pair_count": len(exact_results),
            "exact_pairs_not_reuse_eligible_due_embedding_input_change": sum(
                not result.auto_reuse_eligible for result in exact_results
            ),
            "conflict_false_negative_count_oracle": sum(
                result.oracle_prediction != GoldRelation.CONFLICT for result in conflict_results
            ),
            "conflict_false_negative_rate_oracle": round(
                sum(
                    result.oracle_prediction != GoldRelation.CONFLICT for result in conflict_results
                )
                / max(1, len(conflict_results)),
                6,
            ),
            "conflict_false_positive_count_oracle": sum(
                result.oracle_prediction == GoldRelation.CONFLICT for result in non_conflicts
            ),
            "conflict_false_positive_rate_oracle": round(
                sum(result.oracle_prediction == GoldRelation.CONFLICT for result in non_conflicts)
                / max(1, len(non_conflicts)),
                6,
            ),
            "false_auto_reuse_rate_non_exact": round(
                sum(result.false_auto_reuse for result in results)
                / max(1, len(results) - len(exact_results)),
                6,
            ),
            "conflict_auto_reuse_count": sum(
                result.auto_reuse_eligible for result in conflict_results
            ),
        },
        "failure_taxonomy": dict(sorted(failures.items(), key=lambda item: (-item[1], item[0]))),
        "classifier_failure_taxonomy": dict(
            sorted(classifier_failures.items(), key=lambda item: (-item[1], item[0]))
        ),
        "representative_failures": examples,
        "stress_tests": _stress_results(),
        "execution_limits": {
            "ann_candidate_path_executed": False,
            "reason": (
                "Production ingestion requires OpenAI embeddings; the frozen P0 run makes no "
                "external model/API calls. ANN quality is therefore explicitly unmeasured."
            ),
            "structured_fact_mode_executed": True,
            "structured_fact_reason": (
                "The table-to-table capability diagnostic calls the real analyzer/diff. "
                "The aggregate baseline still preserves the code default mode of off."
            ),
        },
        "pair_results": [
            {**asdict(result), "candidate": asdict(result.candidate)} for result in results
        ],
    }


def _pct(value: float | int) -> str:
    return f"{float(value) * 100:.1f}%"


def _markdown(report: dict[str, object]) -> str:
    dataset = cast(dict[str, Any], report["dataset"])
    breakdown = cast(dict[str, Any], report["dataset_breakdown"])
    candidate = cast(dict[str, Any], report["candidate_generation"])
    oracle = cast(dict[str, Any], report["oracle_pair_classification"])
    reached = cast(dict[str, Any], report["reached_classifier_classification"])
    form_metrics = cast(dict[str, Any], report["source_form_classification"])
    structured_table = cast(dict[str, Any], report["structured_table_to_table_classification"])
    safety = cast(dict[str, Any], report["safety"])
    stress = cast(dict[str, Any], report["stress_tests"])
    failures = cast(dict[str, Any], report["failure_taxonomy"])
    classifier_failures = cast(dict[str, Any], report["classifier_failure_taxonomy"])
    examples = cast(dict[str, list[dict[str, Any]]], report["representative_failures"])
    returned_counts = cast(dict[str, Any], candidate["returned_candidate_count"])

    lines = [
        "# Duplicate/conflict P0 baseline",
        "",
        (
            "> Frozen deterministic baseline. No production algorithm, threshold, "
            "or runtime default was changed."
        ),
        "",
        "## Dataset",
        "",
        f"- Valid: `{dataset['valid']}`; pairs: **{dataset['pair_count']}**.",
        f"- Domains: `{json.dumps(dataset['domain_counts'], ensure_ascii=False, sort_keys=True)}`.",
        f"- Splits: `{json.dumps(dataset['split_counts'], sort_keys=True)}`.",
        f"- Labels: `{json.dumps(dataset['relation_counts'], sort_keys=True)}`.",
        f"- Difficulty: `{json.dumps(breakdown['difficulty'], sort_keys=True)}`.",
        f"- Source forms: `{json.dumps(breakdown['source_form'], sort_keys=True)}`.",
        "- Maximum OCR-noise level per pair: "
        f"`{json.dumps(breakdown['ocr_noise'], sort_keys=True)}`.",
        (
            "- All facts and values are synthetic; source DOCX files informed only "
            "domain patterns and qualifier coverage."
        ),
        "",
        "## Candidate generation",
        "",
        f"- Population requiring retrieval: **{candidate['population']}**.",
        f"- Recall@1/5/10/20/50: **{_pct(candidate['recall@1'])} / {_pct(candidate['recall@5'])} / "
        f"{_pct(candidate['recall@10'])} / {_pct(candidate['recall@20'])} / "
        f"{_pct(candidate['recall@50'])}**.",
        f"- Admission to current classifier (`top {RUNTIME_CANDIDATES_PER_PROBE}`, Hamming <= "
        f"{DEFAULT_MAX_SIMHASH_DISTANCE}): **{_pct(candidate['classifier_admission_recall'])}**.",
        f"- Returned candidate count mean / p50 / p95: **{returned_counts['mean']} / "
        f"{returned_counts['p50']} / {returned_counts['p95']}**.",
        "",
        "## Classification",
        "",
        f"- Oracle-pair accuracy / macro-F1: **{_pct(oracle['accuracy'])} / "
        f"{_pct(oracle['macro_f1'])}**.",
        f"- Reached-classifier accuracy / macro-F1: **{_pct(reached['accuracy'])} / "
        f"{_pct(reached['macro_f1'])}**.",
        (
            "- Oracle-pair means the gold pair is supplied directly to the current "
            "deterministic classifier; it does not hide candidate misses."
        ),
        "",
        "### Per-label oracle-pair metrics",
        "",
        "| Label | Precision | Recall | F1 | Support |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    per_class = cast(dict[str, Any], oracle["per_class"])
    for label in LABELS:
        label_metrics = per_class[label]
        lines.append(
            f"| {label} | {_pct(label_metrics['precision'])} | {_pct(label_metrics['recall'])} | "
            f"{_pct(label_metrics['f1'])} | {label_metrics['support']} |"
        )
    lines.extend(
        [
            "",
            "### Source-form oracle-pair metrics (active text path)",
            "",
            "| Source form | Pairs | Accuracy | Macro-F1 |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for form, metrics in form_metrics.items():
        lines.append(
            f"| {form} | {metrics['count']} | {_pct(metrics['accuracy'])} | "
            f"{_pct(metrics['macro_f1'])} |"
        )
    lines.extend(
        [
            "",
            "The rows above use the active generic text relation path. A separate call to the "
            "real structured table analyzer/diff produced:",
            "",
            f"- Table-to-table structured accuracy / macro-F1: "
            f"**{_pct(structured_table['accuracy'])} / {_pct(structured_table['macro_f1'])}** "
            f"over **{structured_table['count']}** pairs.",
        ]
    )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- False automatic embedding reuse: **{safety['false_auto_reuse_count']} "
            f"({_pct(safety['false_auto_reuse_rate_non_exact'])})**.",
            "- Conflict false negatives / false positives (oracle-pair): "
            f"**{safety['conflict_false_negative_count_oracle']} / "
            f"{safety['conflict_false_positive_count_oracle']}** "
            f"(**{_pct(safety['conflict_false_negative_rate_oracle'])} / "
            f"{_pct(safety['conflict_false_positive_rate_oracle'])}**).",
            "- Conflict pairs eligible for automatic reuse: "
            f"**{safety['conflict_auto_reuse_count']}**.",
            f"- Strict-exact pairs blocked from reuse because embedding input checksum changed: "
            f"**{safety['exact_pairs_not_reuse_eligible_due_embedding_input_change']}**.",
            "",
            "## Failure attribution",
            "",
            "Primary end-to-end attribution (candidate miss takes precedence):",
            "",
        ]
    )
    lines.extend(f"- `{name}`: **{count}**" for name, count in failures.items())
    lines.extend(["", "Oracle-pair classifier attribution (candidate stage bypassed):", ""])
    lines.extend(f"- `{name}`: **{count}**" for name, count in classifier_failures.items())
    lines.extend(["", "### Representative failures", ""])
    for category, category_examples in examples.items():
        lines.extend([f"#### {category}", ""])
        for example in category_examples:
            lines.append(
                f"- `{example['pair_id']}` ({example['variation_type']}): expected "
                f"`{example['expected']}`, oracle `{example['oracle_prediction']}`, "
                f"runtime `{example['runtime_prediction']}`; A: {example['text_a']!r}; "
                f"B: {example['text_b']!r}."
            )
        lines.append("")

    long_case = cast(dict[str, Any], stress["long_document_sampling"])
    lsh_case = cast(dict[str, Any], stress["simhash_lsh_counterexample"])
    lines.extend(
        [
            "## Stress tests",
            "",
            "- Long-document meaningful-position recall: "
            f"**{_pct(long_case['meaningful_position_recall'])}**; "
            f"sampled positions: `{long_case['sampled_positions_1_based']}`.",
            f"- SimHash counterexample: Hamming **{lsh_case['hamming_distance']}** <= "
            f"{lsh_case['maximum_hamming_distance']}, aligned-band overlap "
            f"**{lsh_case['aligned_band_overlap']}**, "
            f"candidate generated: **{lsh_case['candidate_generated']}**.",
            "",
            "## Explicit limits",
            "",
            (
                "- ANN candidate quality is unmeasured because the production path requires "
                "external OpenAI embeddings and this run is offline."
            ),
            (
                "- The code default for structured facts is `off`; a separate deterministic "
                "table-to-table capability diagnostic is reported, while table-to-prose has no "
                "structured bridge."
            ),
            (
                "- See the JSON report for the full confusion matrix and all 600 pair-level "
                "diagnostics."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, object]) -> None:
    JSON_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    MARKDOWN_REPORT_PATH.write_text(_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", type=Path, default=FULL_DATASET_PATH)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    pairs = load_pairs(args.dataset)
    report = build_report(
        pairs,
        require_full_dataset=args.dataset.resolve() == FULL_DATASET_PATH.resolve(),
    )
    if not args.no_write:
        write_report(report)
    summary: dict[str, Any] = {
        "pairs": len(pairs),
        "candidate_recall_at_5": report["candidate_generation"]["recall@5"],  # type: ignore[index]
        "oracle_accuracy": report["oracle_pair_classification"]["accuracy"],  # type: ignore[index]
        "false_auto_reuse": report["safety"]["false_auto_reuse_count"],  # type: ignore[index]
        "report": str(JSON_REPORT_PATH),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_report", "evaluate_pair", "write_report"]
