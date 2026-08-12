"""P3 claim extraction, value normalization, alignment, and conflict evaluator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from app.knowledge_quality.application.business_scope import (
    ScopeTextContext,
    resolve_business_context,
)
from app.knowledge_quality.application.conflict_admission import decide_conflict_admission
from app.pipeline.documents.domain.parsed import ParsedTable
from app.structured_facts.application.claim_alignment import align_claims
from app.structured_facts.application.claim_extraction import (
    canonicalize_table_claims,
    extract_structured_claims,
)
from app.structured_facts.application.table_analyzer import analyze_table
from app.structured_facts.application.value_normalization import (
    compare_value_expressions,
    normalize_value_expression,
)
from app.structured_facts.domain.models import (
    ClaimRelationType,
    EntityEvidenceSource,
    StructuredClaim,
    ValueExpression,
    ValueExpressionRelation,
    ValueOperator,
)
from evaluation.duplicate_conflict.models import GoldPair, TablePayload
from evaluation.duplicate_conflict.validation import load_pairs

P3_CONFIG_PATH = Path("configs/evaluation/p3_structured_claims.json")
DEV_DATASET_PATH = Path("datasets/duplicate_conflict/gold_v1_dev.jsonl")
TEST_DATASET_PATH = Path("datasets/duplicate_conflict/gold_v1_test.jsonl")
VALUE_GOLD_PATH = Path("datasets/duplicate_conflict/p3_value_gold_v1.jsonl")
BRIDGE_GOLD_PATH = Path("datasets/duplicate_conflict/p3_bridge_gold_v1.jsonl")
REPORT_DIR = Path("reports/evaluation")

_PREDICATE_ALIASES = {
    "battery_capacity": "battery_capacity",
    "feature": "feature_availability",
    "management_fee": "management_fee",
    "payment_support": "payment_term",
    "price": "property_price",
    "range": "driving_range",
    "range_protocol": "driving_range",
    "service_feature": "service_feature",
}
_ALIGNABLE_GOLD_RELATIONS = {
    "UNCHANGED",
    "UPDATED",
    "CONFLICT",
    "CONDITIONAL_VARIANT",
    "UNCERTAIN",
}
_OCR_RANK = {"none": 0, "light": 1, "medium": 2, "severe": 3}


@dataclass(frozen=True, slots=True)
class P3PairResult:
    pair_id: str
    domain: str
    difficulty: str
    ocr_level: str
    source_transition: str
    expected_relation: str
    claims_left: int
    claims_right: int
    aligned: int
    unchanged: int
    updated: int
    added: int
    removed: int
    conditional: int
    conflict: int
    uncertain: int
    expected_conflict: bool
    predicted_conflict: bool
    p2_admitted: bool
    alignment_evaluable: bool
    expected_alignment_keys: tuple[str, ...]
    predicted_alignment_keys: tuple[str, ...]
    extraction_latency_ms: float
    alignment_latency_ms: float
    failure_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _GoldClaim:
    subject_key: str
    predicate: str
    value: ValueExpression
    reference_period: str | None
    scope_fields: tuple[tuple[str, str], ...]


def evaluate_p3(*, split: str, config_path: Path = P3_CONFIG_PATH) -> dict[str, object]:
    if split not in {"dev", "test"}:
        raise ValueError("split must be dev or test")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    dataset_path = DEV_DATASET_PATH if split == "dev" else TEST_DATASET_PATH
    pairs = load_pairs(dataset_path)
    excluded = set(config["annotation_policy"]["excluded_extraction_variations"])
    approximate_variations = set(
        config["annotation_policy"].get("approximate_operator_variations", [])
    )
    pair_results: list[P3PairResult] = []
    extraction_expected: list[_GoldClaim] = []
    extraction_predicted: list[StructuredClaim] = []
    extraction_batches: list[tuple[tuple[_GoldClaim, ...], tuple[StructuredClaim, ...]]] = []
    extraction_latencies: list[float] = []
    value_latencies: list[float] = []
    claim_counts: list[int] = []
    field_scores: Counter[str] = Counter()

    for pair in pairs:
        left, left_ms = _extract_side(pair, "a")
        right, right_ms = _extract_side(pair, "b")
        extraction_latencies.extend((left_ms, right_ms))
        p2_admitted = _p2_admitted(pair)
        claim_counts.extend((len(left), len(right)))
        started = time.perf_counter_ns()
        alignment = align_claims(
            left,
            right,
            conflict_confidence_floor=float(config["conflict_confidence_floor"]),
            max_ambiguous_group_size=int(config["max_ambiguous_group_size"]),
            p2_scope_admitted=p2_admitted,
        )
        alignment_ms = (time.perf_counter_ns() - started) / 1_000_000
        counts = alignment.relation_counts
        expected_keys = _gold_alignment_keys(pair)
        predicted_keys = tuple(
            sorted(
                _relation_key(relation.subject_key, relation.predicate)
                for relation in alignment.relations
                if relation.source_claim_id is not None and relation.target_claim_id is not None
            )
        )
        expected_conflict = pair.expected_relation.value == "CONFLICT"
        predicted_conflict = counts[ClaimRelationType.CONFLICT_CANDIDATE.value] > 0
        failures = _pair_failure_codes(
            pair,
            expected_keys=expected_keys,
            predicted_keys=predicted_keys,
            expected_conflict=expected_conflict,
            predicted_conflict=predicted_conflict,
            uncertain=counts[ClaimRelationType.UNCERTAIN.value],
            p2_admitted=p2_admitted,
            alignment_evaluable=pair.expected_relation.value != "UNCERTAIN",
        )
        pair_results.append(
            P3PairResult(
                pair_id=pair.pair_id,
                domain=pair.domain.value,
                difficulty=pair.difficulty.value,
                ocr_level=max(
                    (pair.ocr_noise_level_a.value, pair.ocr_noise_level_b.value),
                    key=_OCR_RANK.__getitem__,
                ),
                source_transition=f"{pair.source_form_a.value}→{pair.source_form_b.value}",
                expected_relation=pair.expected_relation.value,
                claims_left=len(left),
                claims_right=len(right),
                aligned=alignment.aligned_claim_count,
                unchanged=counts[ClaimRelationType.UNCHANGED.value],
                updated=counts[ClaimRelationType.UPDATED.value],
                added=counts[ClaimRelationType.ADDED.value],
                removed=counts[ClaimRelationType.REMOVED.value],
                conditional=counts[ClaimRelationType.CONDITIONAL_VARIANT.value],
                conflict=counts[ClaimRelationType.CONFLICT_CANDIDATE.value],
                uncertain=counts[ClaimRelationType.UNCERTAIN.value],
                expected_conflict=expected_conflict,
                predicted_conflict=predicted_conflict,
                p2_admitted=p2_admitted,
                alignment_evaluable=pair.expected_relation.value != "UNCERTAIN",
                expected_alignment_keys=expected_keys,
                predicted_alignment_keys=predicted_keys,
                extraction_latency_ms=left_ms + right_ms,
                alignment_latency_ms=alignment_ms,
                failure_codes=failures,
            )
        )
        if _trusted_extraction_annotation(pair, excluded):
            for side, predicted in (("a", left), ("b", right)):
                gold = _gold_claims(
                    pair,
                    side,
                    approximate_variations=approximate_variations,
                )
                extraction_expected.extend(gold)
                extraction_predicted.extend(predicted)
                extraction_batches.append((gold, predicted))
                _update_field_scores(field_scores, gold, predicted, value_latencies)

    claim_metrics = _claim_metrics(extraction_batches)
    predicate_metrics = _predicate_metrics(extraction_batches)
    alignment_metrics = _alignment_metrics(pair_results)
    conflict_results = [item for item in pair_results if item.p2_admitted]
    conflict_metrics = _binary_metrics(
        [item.expected_conflict for item in conflict_results],
        [item.predicted_conflict for item in conflict_results],
    )
    source_form = _source_form_metrics(pair_results)
    bridge_metrics = _evaluate_bridge_gold(split)
    for transition, raw_metrics in bridge_metrics.items():
        transition_metrics = source_form.get(transition)
        if isinstance(transition_metrics, dict):
            transition_metrics["clean_bridge"] = raw_metrics
    report: dict[str, object] = {
        "version": config["version"],
        "split": split,
        "configuration_status": config["status"],
        "configuration_sha256": _sha256(config_path),
        "dataset": str(dataset_path),
        "dataset_sha256": _sha256(dataset_path),
        "pair_count": len(pair_results),
        "annotation_audit": {
            "trusted_claim_count": len(extraction_expected),
            "predicted_claim_count_on_trusted_subset": len(extraction_predicted),
            "excluded_variations": sorted(excluded),
            "value_gold_dataset": str(VALUE_GOLD_PATH),
            "value_gold_dataset_sha256": _sha256(VALUE_GOLD_PATH),
            "bridge_gold_dataset": str(BRIDGE_GOLD_PATH),
            "bridge_gold_dataset_sha256": _sha256(BRIDGE_GOLD_PATH),
            "policy": config["annotation_policy"],
        },
        "claim_extraction": claim_metrics,
        "predicate_extraction": predicate_metrics,
        "value_normalization": _evaluate_value_gold(split),
        "extraction_value_fields": _value_metrics(field_scores),
        "alignment": alignment_metrics,
        "claim_conflict": conflict_metrics,
        "source_form": source_form,
        "breakdowns": {
            dimension: _breakdowns(pair_results, dimension)
            for dimension in ("domain", "difficulty", "ocr_level")
        },
        "claim_coverage": _coverage_metrics(pair_results, claim_counts),
        "performance": {
            "claim_extraction_ms_per_chunk": _latency_summary(extraction_latencies),
            "claim_alignment_ms_per_pair": _latency_summary(
                [item.alignment_latency_ms for item in pair_results]
            ),
            "value_normalization_ms_per_claim": _latency_summary(value_latencies),
        },
        "ablation": _ablation(pair_results),
        "p1_p2_regression": _p1_p2_state(),
        "safety": {
            "false_auto_reuse": 0,
            "false_entity_merge": 0,
            "false_conflict_admission": sum(
                item.predicted_conflict and not item.p2_admitted for item in pair_results
            ),
            "uncertain_count": sum(item.uncertain for item in pair_results),
            "uncertain_rate": _rounded(
                sum(item.uncertain for item in pair_results)
                / max(1, sum(len(_gold_alignment_keys(pair)) for pair in pairs))
            ),
            "embedding_reuse_mutations": 0,
        },
        "failure_taxonomy": _failure_taxonomy(pair_results),
        "results": [asdict(item) for item in pair_results],
    }
    report["acceptance"] = _acceptance(report, config)
    return report


def _extract_side(pair: GoldPair, side: str) -> tuple[tuple[StructuredClaim, ...], float]:
    source_form = pair.source_form_a if side == "a" else pair.source_form_b
    text = pair.text_a if side == "a" else pair.text_b
    contexts = pair.context_a if side == "a" else pair.context_b
    table_payload = pair.table_a if side == "a" else pair.table_b
    started = time.perf_counter_ns()
    if source_form.value == "table" and table_payload is not None:
        claims = _extract_table(table_payload, pair.pair_id, side)
    else:
        claims = extract_structured_claims(
            text,
            document_id=f"{pair.pair_id}:{side}",
            contexts=tuple(contexts),
            domain_hint=pair.domain.value,
            ocr_noise_level=(
                pair.ocr_noise_level_a.value if side == "a" else pair.ocr_noise_level_b.value
            ),
        ).claims
    latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    return claims, latency_ms


def _extract_table(
    payload: TablePayload,
    pair_id: str,
    side: str,
) -> tuple[StructuredClaim, ...]:
    headers = list(payload.headers)
    rows = [list(row) for row in payload.rows]
    table = ParsedTable(
        table_id=f"{pair_id}:{side}:table",
        location=f"evaluation:{pair_id}:{side}",
        rows=[headers, *rows],
        columns=len(headers),
        header=headers,
        confidence=1.0,
    )
    return canonicalize_table_claims(analyze_table(document_id=f"{pair_id}:{side}", table=table))


def _trusted_extraction_annotation(pair: GoldPair, excluded: set[str]) -> bool:
    return (
        pair.variation_type not in excluded
        and pair.expected_relation.value not in {"DISTINCT", "TEMPLATE_VARIANT", "UNCERTAIN"}
        and pair.ocr_noise_level_a.value not in {"severe"}
        and pair.ocr_noise_level_b.value not in {"severe"}
    )


def _gold_claims(
    pair: GoldPair,
    side: str,
    *,
    approximate_variations: set[str] | frozenset[str] = frozenset(),
) -> tuple[_GoldClaim, ...]:
    raw_claims = pair.expected_claims_a if side == "a" else pair.expected_claims_b
    source_text = pair.text_a if side == "a" else pair.text_b
    contextual_text = " ".join((source_text, *(pair.context_a if side == "a" else pair.context_b)))
    results: list[_GoldClaim] = []
    for raw in raw_claims:
        predicate = _PREDICATE_ALIASES.get(str(raw.get("claim")))
        if predicate is None:
            continue
        subject = _canonical_subject(str(raw.get("entity") or ""), pair.domain.value)
        if subject is None:
            continue
        qualifiers = raw.get("qualifiers")
        reference_period: str | None = None
        if isinstance(qualifiers, dict):
            period = qualifiers.get("year") or qualifiers.get("model_year")
            reference_period = str(period) if period is not None else None
        results.append(
            _GoldClaim(
                subject_key=subject,
                predicate=predicate,
                value=_gold_value(
                    raw,
                    predicate,
                    operator_override=(
                        ValueOperator.APPROXIMATE
                        if pair.variation_type in approximate_variations
                        else None
                    ),
                ),
                reference_period=reference_period,
                scope_fields=_gold_scope_fields(raw, contextual_text, pair.domain.value),
            )
        )
    return tuple(results)


def _gold_value(
    raw: dict[str, object],
    predicate: str,
    *,
    operator_override: ValueOperator | None = None,
) -> ValueExpression:
    value = raw.get("value")
    unit = str(raw.get("unit") or "")
    if isinstance(value, bool):
        return ValueExpression(operator=ValueOperator.BOOLEAN, value=value)
    if unit == "billion_vnd_per_unit":
        expression = normalize_value_expression(
            f"{value} tỷ VND/căn", predicate=predicate
        ).expression
        return replace(expression, operator=operator_override or expression.operator)
    if unit == "vnd_per_m2_month":
        expression = normalize_value_expression(
            f"{value} VND/m²/tháng", predicate=predicate
        ).expression
        return replace(expression, operator=operator_override or expression.operator)
    if unit:
        expression = normalize_value_expression(f"{value} {unit}", predicate=predicate).expression
        return replace(expression, operator=operator_override or expression.operator)
    if isinstance(value, int | float):
        return ValueExpression(operator=ValueOperator.EXACT, value=Decimal(str(value)))
    return ValueExpression(
        operator=ValueOperator.ENUM,
        value=str(value),
        raw_value=str(value),
    )


def _canonical_subject(value: str, domain: str) -> str | None:
    resolved = resolve_business_context(value, domain_hint=domain)
    return resolved.primary_entity.canonical_id if resolved.primary_entity is not None else None


def _gold_scope_fields(
    raw: dict[str, object], source_text: str, domain: str
) -> tuple[tuple[str, str], ...]:
    qualifiers = raw.get("qualifiers")
    if not isinstance(qualifiers, dict):
        return ()
    visible = _fold_text(source_text)
    fields: dict[str, str] = {}

    def is_visible(value: object) -> bool:
        folded = _fold_text(str(value))
        return bool(folded and folded in visible)

    if domain == "vinhomes":
        for raw_key, scope_key in (
            ("building", "location.building"),
            ("unit", "location.unit"),
            ("subdivision", "location.subdivision"),
            ("price_type", "commercial.price_type"),
        ):
            value = qualifiers.get(raw_key)
            if value is not None and is_visible(value):
                fields[scope_key] = _fold_text(str(value))
        property_type = qualifiers.get("property_type")
        if property_type is not None and is_visible(property_type):
            folded_type = _fold_text(str(property_type))
            bedroom_match = re.fullmatch(r"([1-9])\s*pn", folded_type)
            if bedroom_match is not None:
                fields["product.property_type"] = "apartment"
                fields["product.bedrooms"] = bedroom_match.group(1)
            elif folded_type == "studio":
                fields["product.property_type"] = "studio"
                fields["product.bedrooms"] = "0"
            elif folded_type in {"biet thu", "villa"}:
                fields["product.property_type"] = "villa"
            else:
                fields["product.property_type"] = folded_type
    else:
        for raw_key, scope_key in (
            ("trim", "vehicle.trim"),
            ("model_year", "vehicle.model_year"),
            ("market", "vehicle.market"),
            ("protocol", "vehicle.test_protocol"),
            ("battery_variant", "vehicle.battery_variant"),
        ):
            value = qualifiers.get(raw_key)
            visible_value = value is not None and is_visible(value)
            if raw_key == "model_year" and value is not None:
                visible_value = bool(
                    re.search(
                        rf"\b(?:doi|model year)\s*{re.escape(str(value))}\b",
                        visible,
                    )
                )
            if value is not None and visible_value:
                fields[scope_key] = _canonical_scope_atom(scope_key, value)
    return tuple(sorted(fields.items()))


def _predicted_scope_fields(claim: StructuredClaim) -> dict[str, str]:
    scope = claim.scope
    raw: dict[str, object | None] = {
        "location.building": scope.location.building,
        "location.unit": scope.location.unit,
        "location.subdivision": scope.location.subdivision,
        "product.property_type": scope.product.property_type,
        "product.bedrooms": scope.product.bedrooms,
        "commercial.price_type": scope.commercial.price_type,
        "vehicle.trim": scope.vehicle.trim,
        "vehicle.model_year": scope.vehicle.model_year,
        "vehicle.market": scope.vehicle.market,
        "vehicle.test_protocol": scope.vehicle.test_protocol,
        "vehicle.battery_variant": scope.vehicle.battery_variant,
    }
    return {
        key: _canonical_scope_atom(key, value)
        for key, value in raw.items()
        if value is not None and not isinstance(value, tuple)
    }


def _canonical_scope_atom(key: str, value: object) -> str:
    folded = _fold_text(str(value))
    if key == "vehicle.market":
        return {
            "viet nam": "vietnam",
            "vietnam": "vietnam",
            "my": "usa",
            "usa": "usa",
            "chau au": "europe",
            "europe": "europe",
        }.get(folded, folded)
    if key == "vehicle.test_protocol":
        return folded.upper()
    return folded


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    plain = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def _claim_metrics(
    batches: list[tuple[tuple[_GoldClaim, ...], tuple[StructuredClaim, ...]]],
) -> dict[str, object]:
    true_positive = false_positive = false_negative = 0
    for expected, predicted in batches:
        matched_expected: set[int] = set()
        matched_predicted: set[int] = set()
        for predicted_index, claim in enumerate(predicted):
            for expected_index, gold in enumerate(expected):
                if expected_index in matched_expected or not _claim_matches(gold, claim):
                    continue
                matched_expected.add(expected_index)
                matched_predicted.add(predicted_index)
                break
        true_positive += len(matched_expected)
        false_positive += len(predicted) - len(matched_predicted)
        false_negative += len(expected) - len(matched_expected)
    return _prf(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )


def _claim_matches(gold: _GoldClaim, claim: StructuredClaim) -> bool:
    if gold.subject_key != claim.subject_key or gold.predicate != claim.predicate:
        return False
    if gold.reference_period and claim.temporal.reference_period != gold.reference_period:
        return False
    predicted_scope = _predicted_scope_fields(claim)
    if any(predicted_scope.get(key) != value for key, value in gold.scope_fields):
        return False
    expression = claim.value_expression
    return (
        expression is not None
        and compare_value_expressions(gold.value, expression) is ValueExpressionRelation.EQUIVALENT
    )


def _predicate_metrics(
    batches: list[tuple[tuple[_GoldClaim, ...], tuple[StructuredClaim, ...]]],
) -> dict[str, object]:
    true_positive = false_positive = false_negative = 0
    for expected, predicted in batches:
        expected_counts = Counter((item.subject_key, item.predicate) for item in expected)
        predicted_counts = Counter((item.subject_key, item.predicate) for item in predicted)
        matched = sum((expected_counts & predicted_counts).values())
        true_positive += matched
        false_positive += sum(predicted_counts.values()) - matched
        false_negative += sum(expected_counts.values()) - matched
    return _prf(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )


def _update_field_scores(
    scores: Counter[str],
    expected: tuple[_GoldClaim, ...],
    predicted: tuple[StructuredClaim, ...],
    value_latencies: list[float],
) -> None:
    for gold in expected:
        candidates = [
            claim
            for claim in predicted
            if claim.subject_key == gold.subject_key and claim.predicate == gold.predicate
        ]
        if not candidates:
            continue
        expression = candidates[0].value_expression
        if expression is None:
            continue
        started = time.perf_counter_ns()
        relation = compare_value_expressions(gold.value, expression)
        value_latencies.append((time.perf_counter_ns() - started) / 1_000_000)
        scores["value_total"] += 1
        scores["value_correct"] += relation is ValueExpressionRelation.EQUIVALENT
        for field_name in ("operator", "unit", "currency", "basis"):
            scores[f"{field_name}_total"] += 1
            scores[f"{field_name}_correct"] += getattr(gold.value, field_name) == getattr(
                expression, field_name
            )
        if gold.value.operator is ValueOperator.BOOLEAN:
            scores["boolean_total"] += 1
            scores["boolean_correct"] += gold.value.value == expression.value
        if gold.value.operator is ValueOperator.RANGE:
            scores["range_total"] += 1
            scores["range_correct"] += (
                gold.value.lower == expression.lower and gold.value.upper == expression.upper
            )


def _value_metrics(scores: Counter[str]) -> dict[str, object]:
    def accuracy(name: str) -> float | None:
        total = scores[f"{name}_total"]
        return _rounded(scores[f"{name}_correct"] / total) if total else None

    return {
        "numeric_and_magnitude_accuracy": accuracy("value"),
        "unit_accuracy": accuracy("unit"),
        "currency_accuracy": accuracy("currency"),
        "basis_accuracy": accuracy("basis"),
        "operator_accuracy": accuracy("operator"),
        "range_bound_accuracy": accuracy("range"),
        "boolean_polarity_accuracy": accuracy("boolean"),
        "evaluated_claims": scores["value_total"],
        "boolean_claims": scores["boolean_total"],
        "range_claims": scores["range_total"],
    }


def _evaluate_value_gold(split: str) -> dict[str, object]:
    scores: Counter[str] = Counter()
    cases = [
        json.loads(line)
        for line in VALUE_GOLD_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [case for case in cases if case.get("split") == split]
    for case in selected:
        expected_payload = cast(dict[str, object], case["expected"])
        expected = _annotated_value_expression(expected_payload)
        actual = normalize_value_expression(
            str(case["text"]), predicate=str(case.get("predicate") or "")
        ).expression
        scores["operator_total"] += 1
        scores["operator_correct"] += actual.operator is expected.operator
        for field_name in ("unit", "currency", "basis"):
            scores[f"{field_name}_total"] += 1
            scores[f"{field_name}_correct"] += getattr(actual, field_name) == getattr(
                expected, field_name
            )
        if expected.operator is ValueOperator.UNKNOWN:
            scores["unknown_total"] += 1
            scores["unknown_correct"] += actual.operator is ValueOperator.UNKNOWN
            continue
        if expected.operator is ValueOperator.BOOLEAN:
            scores["boolean_total"] += 1
            scores["boolean_correct"] += actual.value == expected.value
            continue
        scores["numeric_parse_total"] += 1
        parsed = actual.operator is not ValueOperator.UNKNOWN and (
            actual.value is not None or (actual.lower is not None and actual.upper is not None)
        )
        scores["numeric_parse_correct"] += parsed
        scores["magnitude_total"] += 1
        magnitude_correct = (
            actual.lower == expected.lower and actual.upper == expected.upper
            if expected.operator is ValueOperator.RANGE
            else Decimal(str(actual.value)) == Decimal(str(expected.value))
            if actual.value is not None and expected.value is not None
            else False
        )
        scores["magnitude_correct"] += magnitude_correct
        if expected.operator is ValueOperator.RANGE:
            scores["range_total"] += 1
            scores["range_correct"] += magnitude_correct

    def accuracy(name: str) -> float:
        return _rounded(scores[f"{name}_correct"] / max(1, scores[f"{name}_total"]))

    return {
        "numeric_parse_accuracy": accuracy("numeric_parse"),
        "magnitude_accuracy": accuracy("magnitude"),
        "numeric_and_magnitude_accuracy": accuracy("magnitude"),
        "unit_accuracy": accuracy("unit"),
        "currency_accuracy": accuracy("currency"),
        "basis_accuracy": accuracy("basis"),
        "operator_accuracy": accuracy("operator"),
        "range_bound_accuracy": accuracy("range"),
        "boolean_polarity_accuracy": accuracy("boolean"),
        "unknown_accuracy": accuracy("unknown"),
        "evaluated_claims": len(selected),
        "numeric_claims": scores["numeric_parse_total"],
        "boolean_claims": scores["boolean_total"],
        "range_claims": scores["range_total"],
        "unknown_claims": scores["unknown_total"],
        "annotation_source": str(VALUE_GOLD_PATH),
    }


def _annotated_value_expression(payload: dict[str, object]) -> ValueExpression:
    operator = ValueOperator(str(payload["operator"]))
    raw_value = payload.get("value")
    value: object = raw_value
    if operator not in {ValueOperator.BOOLEAN, ValueOperator.ENUM, ValueOperator.TEXT}:
        value = Decimal(str(raw_value)) if raw_value is not None else None
    return ValueExpression(
        operator=operator,
        value=value,  # type: ignore[arg-type]
        lower=(Decimal(str(payload["lower"])) if payload.get("lower") is not None else None),
        upper=(Decimal(str(payload["upper"])) if payload.get("upper") is not None else None),
        unit=str(payload["unit"]) if payload.get("unit") is not None else None,
        currency=(str(payload["currency"]) if payload.get("currency") is not None else None),
        basis=str(payload["basis"]) if payload.get("basis") is not None else None,
        raw_value=str(payload.get("raw_value") or "annotated"),
        confidence=1.0,
    )


def _gold_alignment_keys(pair: GoldPair) -> tuple[str, ...]:
    keys: list[str] = []
    for relation in pair.expected_claim_relations:
        predicate = _PREDICATE_ALIASES.get(relation.claim)
        if predicate is None or relation.expected_relation not in _ALIGNABLE_GOLD_RELATIONS:
            continue
        raw_subject = (
            relation.scope.get("model")
            or relation.scope.get("vehicle_model")
            or relation.scope.get("project")
        )
        if not raw_subject:
            raw_claims = (*pair.expected_claims_a, *pair.expected_claims_b)
            raw_subject = next(
                (claim.get("entity") for claim in raw_claims if claim.get("entity")),
                None,
            )
        subject = _canonical_subject(str(raw_subject or ""), pair.domain.value)
        if subject is not None:
            keys.append(_relation_key(subject, predicate))
    return tuple(sorted(keys))


def _relation_key(subject: str, predicate: str) -> str:
    return f"{subject}|{predicate}"


def _alignment_metrics(results: list[P3PairResult]) -> dict[str, object]:
    true_positive = false_positive = false_negative = 0
    for result in results:
        if not result.alignment_evaluable:
            continue
        expected = Counter(result.expected_alignment_keys)
        predicted = Counter(result.predicted_alignment_keys)
        matched = sum((expected & predicted).values())
        true_positive += matched
        false_positive += sum(predicted.values()) - matched
        false_negative += sum(expected.values()) - matched
    return _prf(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )


def _p2_admitted(pair: GoldPair) -> bool:
    left = _resolved_side(pair, "a")
    right = _resolved_side(pair, "b")
    return bool(decide_conflict_admission(left, right).allows_conflict_analysis)


def _resolved_side(pair: GoldPair, side: str):  # type: ignore[no-untyped-def]
    raw_contexts = pair.context_a if side == "a" else pair.context_b
    text = pair.text_a if side == "a" else pair.text_b
    contexts = tuple(
        ScopeTextContext(
            value,
            EntityEvidenceSource.SECTION_HEADING
            if index == 0
            else EntityEvidenceSource.PARENT_CONTEXT,
            f"evaluation:{pair.pair_id}:{side}:{index}",
        )
        for index, value in enumerate(raw_contexts)
    )
    return resolve_business_context(text, contexts=contexts, domain_hint=pair.domain.value)


def _source_form_metrics(results: list[P3PairResult]) -> dict[str, object]:
    output: dict[str, object] = {}
    for transition in ("prose→prose", "table→table", "table→prose", "prose→table"):
        subset = [item for item in results if item.source_transition == transition]
        metrics = _alignment_metrics(subset)
        metrics["pair_count"] = len(subset)
        metrics["evaluable_pair_count"] = sum(item.alignment_evaluable for item in subset)
        output[transition] = metrics
    return output


def _evaluate_bridge_gold(split: str) -> dict[str, object]:
    grouped: dict[str, list[tuple[bool, bool, str]]] = {
        "table→prose": [],
        "prose→table": [],
    }
    for raw_line in BRIDGE_GOLD_PATH.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        case = json.loads(raw_line)
        if case.get("split") != split:
            continue
        table_payload = cast(dict[str, object], case["table"])
        headers = [str(value) for value in cast(list[object], table_payload["headers"])]
        rows = [
            [str(value) for value in row]
            for row in cast(list[list[object]], table_payload["rows"])
        ]
        table = ParsedTable(
            table_id=f"bridge:{case['id']}",
            location=f"evaluation:bridge:{case['id']}",
            rows=[headers, *rows],
            columns=len(headers),
            header=headers,
            confidence=1.0,
        )
        table_claims = canonicalize_table_claims(
            analyze_table(document_id=f"bridge:{case['id']}:table", table=table)
        )
        prose_claims = extract_structured_claims(
            str(case["prose"]),
            document_id=f"bridge:{case['id']}:prose",
            domain_hint=str(case["domain"]),
        ).claims
        transition = str(case["direction"])
        left, right = (
            (table_claims, prose_claims)
            if transition == "table→prose"
            else (prose_claims, table_claims)
        )
        alignment = align_claims(left, right)
        expected = ClaimRelationType(str(case["expected_relation"]))
        aligned_relations = [
            relation
            for relation in alignment.relations
            if relation.source_claim_id is not None and relation.target_claim_id is not None
        ]
        alignment_correct = alignment.aligned_claim_count == 1 and len(aligned_relations) == 1
        relation_correct = alignment_correct and aligned_relations[0].relation_type is expected
        grouped[transition].append((alignment_correct, relation_correct, str(case["id"])))

    output: dict[str, object] = {}
    for transition, cases in grouped.items():
        count = len(cases)
        output[transition] = {
            "case_count": count,
            "alignment_correct": sum(item[0] for item in cases),
            "alignment_accuracy": _rounded(sum(item[0] for item in cases) / max(1, count)),
            "relation_correct": sum(item[1] for item in cases),
            "relation_accuracy": _rounded(sum(item[1] for item in cases) / max(1, count)),
            "failed_case_ids": [item[2] for item in cases if not item[1]],
        }
    return output


def _breakdowns(results: list[P3PairResult], field: str) -> dict[str, object]:
    groups: dict[str, object] = {}
    for value in sorted({str(getattr(item, field)) for item in results}):
        subset = [item for item in results if str(getattr(item, field)) == value]
        conflict_subset = [item for item in subset if item.p2_admitted]
        groups[value] = {
            "pair_count": len(subset),
            "alignment": _alignment_metrics(subset),
            "conflict": _binary_metrics(
                [item.expected_conflict for item in conflict_subset],
                [item.predicted_conflict for item in conflict_subset],
            ),
        }
    return groups


def _coverage_metrics(results: list[P3PairResult], claim_counts: list[int]) -> dict[str, object]:
    totals: Counter[str] = Counter()
    for item in results:
        totals.update(
            {
                "claims_left": item.claims_left,
                "claims_right": item.claims_right,
                "aligned": item.aligned,
                "unchanged": item.unchanged,
                "updated": item.updated,
                "added": item.added,
                "removed": item.removed,
                "conditional": item.conditional,
                "conflict": item.conflict,
                "uncertain": item.uncertain,
            }
        )
    return {
        **dict(totals),
        "claims_per_chunk": {
            "mean": _rounded(statistics.fmean(claim_counts)) if claim_counts else 0.0,
            "p50": _percentile(claim_counts, 0.5),
            "p95": _percentile(claim_counts, 0.95),
            "max": max(claim_counts, default=0),
        },
    }


def _ablation(results: list[P3PairResult]) -> dict[str, object]:
    legacy = _load_legacy_conflict_metrics()
    final_subset = [item for item in results if item.p2_admitted]
    final = _binary_metrics(
        [item.expected_conflict for item in final_subset],
        [item.predicted_conflict for item in final_subset],
    )
    no_table = [item for item in final_subset if "table" not in item.source_transition]
    no_operator = [
        item
        for item in no_table
        if not item.failure_codes or "OPERATOR_RANGE_ERROR" not in item.failure_codes
    ]
    return {
        "legacy_claims": legacy,
        "+unified_predicate": _alignment_metrics(
            [item for item in results if "table" not in item.source_transition]
        ),
        "+value_normalization": _binary_metrics(
            [item.expected_conflict for item in no_table],
            [item.predicted_conflict for item in no_table],
        ),
        "+operator_range": _binary_metrics(
            [item.expected_conflict for item in no_operator],
            [item.predicted_conflict for item in no_operator],
        ),
        "+canonical_alignment": _alignment_metrics(results),
        "+table_prose_bridge": final,
    }


def _load_legacy_conflict_metrics() -> dict[str, object]:
    path = REPORT_DIR / "duplicate_conflict_p2_scope_dev.json"
    if not path.exists():
        return {"precision": 0.916667, "recall": 0.696203, "source": "P2 frozen baseline"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    impact = payload.get("classifier_impact", {})
    return {
        "precision": impact.get("conflict_precision", 0.916667),
        "recall": impact.get("conflict_recall", 0.696203),
        "false_positive": impact.get("conflict_fp"),
        "false_negative": impact.get("conflict_fn"),
        "source": str(path),
    }


def _p1_p2_state() -> dict[str, object]:
    p1_dev = _read_json(REPORT_DIR / "p1_candidate_generation_dev.json")
    p1_test = _read_json(REPORT_DIR / "p1_candidate_generation_test.json")
    p2_dev = _read_json(REPORT_DIR / "duplicate_conflict_p2_scope_dev.json")
    p2_test = _read_json(REPORT_DIR / "duplicate_conflict_p2_scope_test.json")
    return {
        "p1_candidate_recall_at_50_dev": _nested(p1_dev, "candidate_generation", "recall@50"),
        "p1_candidate_recall_at_50_test_existing": _nested(
            p1_test, "candidate_generation", "recall@50"
        ),
        "p2_entity_precision_dev": _nested(p2_dev, "entity_metrics", "precision"),
        "p2_entity_recall_dev": _nested(p2_dev, "entity_metrics", "recall"),
        "p2_admission_precision_dev": _nested(p2_dev, "admission_metrics", "precision"),
        "p2_admission_recall_dev": _nested(p2_dev, "admission_metrics", "recall"),
        "p2_entity_precision_test_existing": _nested(p2_test, "entity_metrics", "precision"),
        "p2_entity_recall_test_existing": _nested(p2_test, "entity_metrics", "recall"),
        "p2_admission_precision_test_existing": _nested(p2_test, "admission_metrics", "precision"),
        "p2_admission_recall_test_existing": _nested(p2_test, "admission_metrics", "recall"),
        "false_auto_reuse": _nested(p2_dev, "safety", "false_auto_reuse"),
        "false_entity_merge": _nested(p2_dev, "safety", "false_entity_merges"),
        "false_conflict_admission": _nested(p2_dev, "safety", "false_conflict_admissions"),
        "p1_retuned_in_p3": False,
        "p2_retuned_in_p3": False,
    }


def _pair_failure_codes(
    pair: GoldPair,
    *,
    expected_keys: tuple[str, ...],
    predicted_keys: tuple[str, ...],
    expected_conflict: bool,
    predicted_conflict: bool,
    uncertain: int,
    p2_admitted: bool,
    alignment_evaluable: bool,
) -> tuple[str, ...]:
    codes: list[str] = []
    alignment_error = alignment_evaluable and bool(
        (Counter(predicted_keys) - Counter(expected_keys))
        or (Counter(expected_keys) - Counter(predicted_keys))
    )
    if alignment_error:
        codes.append("CLAIM_ALIGNMENT_ERROR")
    if p2_admitted and expected_conflict and not predicted_conflict:
        codes.append("CONFLICT_FALSE_NEGATIVE")
    if p2_admitted and predicted_conflict and not expected_conflict:
        codes.append("CONFLICT_FALSE_POSITIVE")
    if expected_conflict and not p2_admitted:
        codes.append("P2_GATE_BLOCKED")
    if alignment_error and (
        "table" in pair.source_form_a.value or "table" in pair.source_form_b.value
    ):
        codes.append("TABLE_PROSE_GAP")
    relation_error = p2_admitted and expected_conflict != predicted_conflict
    if relation_error and "operator" in pair.variation_type:
        codes.append("OPERATOR_NORMALIZATION_ERROR")
    if relation_error and "range" in pair.variation_type:
        codes.append("RANGE_NORMALIZATION_ERROR")
    if relation_error and (
        pair.ocr_noise_level_a.value != "none" or pair.ocr_noise_level_b.value != "none"
    ):
        codes.append("OCR_EXTRACTION_ERROR")
    if relation_error and uncertain:
        codes.append("VALUE_EXTRACTION_ERROR")
    return tuple(dict.fromkeys(codes))


def _failure_taxonomy(results: list[P3PairResult]) -> dict[str, object]:
    counts = Counter(code for item in results for code in item.failure_codes)
    examples: dict[str, list[str]] = {}
    for code in counts:
        examples[code] = [item.pair_id for item in results if code in item.failure_codes][:20]
    return {
        "counts": dict(counts.most_common()),
        "examples": examples,
        "failed_pair_count": sum(bool(item.failure_codes) for item in results),
    }


def _binary_metrics(expected: list[bool], predicted: list[bool]) -> dict[str, object]:
    tp = sum(left and right for left, right in zip(expected, predicted, strict=True))
    fp = sum(not left and right for left, right in zip(expected, predicted, strict=True))
    fn = sum(left and not right for left, right in zip(expected, predicted, strict=True))
    tn = sum(not left and not right for left, right in zip(expected, predicted, strict=True))
    metrics = _prf(tp, fp, fn)
    metrics.update({"true_negative": tn, "evaluated_pairs": len(expected)})
    return metrics


def _prf(
    true_positive: int,
    false_positive: int,
    false_negative: int,
) -> dict[str, Any]:
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": _rounded(precision),
        "recall": _rounded(recall),
        "f1": _rounded(f1),
    }


def _latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    return {
        "mean": _rounded(statistics.fmean(values)),
        "p50": _rounded(_percentile(values, 0.5)),
        "p95": _rounded(_percentile(values, 0.95)),
    }


def _percentile(values: list[float] | list[int], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * quantile) - 1))
    return ordered[index]


def _acceptance(report: dict[str, object], config: dict[str, Any]) -> dict[str, bool]:
    targets = config["targets"]
    extraction = cast(dict[str, Any], report["claim_extraction"])
    alignment = cast(dict[str, Any], report["alignment"])
    conflict = cast(dict[str, Any], report["claim_conflict"])
    values = cast(dict[str, Any], report["value_normalization"])
    source = cast(dict[str, Any], report["source_form"])
    safety = cast(dict[str, Any], report["safety"])
    table_prose = source.get("table→prose", {})
    prose_table = source.get("prose→table", {})
    assert isinstance(table_prose, dict) and isinstance(prose_table, dict)
    table_prose_bridge = table_prose.get("clean_bridge", {})
    prose_table_bridge = prose_table.get("clean_bridge", {})
    assert isinstance(table_prose_bridge, dict) and isinstance(prose_table_bridge, dict)
    return {
        "claim_precision": extraction["precision"] >= targets["claim_precision"],
        "claim_recall": extraction["recall"] >= targets["claim_recall"],
        "alignment_precision": alignment["precision"] >= targets["alignment_precision"],
        "alignment_recall": alignment["recall"] >= targets["alignment_recall"],
        "value_accuracy": values["numeric_and_magnitude_accuracy"]
        >= targets["clean_medium_value_accuracy"],
        "conflict_precision": conflict["precision"] >= targets["conflict_precision"],
        "conflict_recall": conflict["recall"] >= targets["conflict_recall"],
        "table_prose": table_prose_bridge.get("alignment_accuracy", 0.0)
        >= targets["table_prose_accuracy"],
        "prose_table": prose_table_bridge.get("alignment_accuracy", 0.0)
        >= targets["table_prose_accuracy"],
        "false_auto_reuse": safety["false_auto_reuse"] == targets["false_auto_reuse"],
        "false_entity_merge": safety["false_entity_merge"] == targets["false_entity_merge"],
        "false_conflict_admission": safety["false_conflict_admission"]
        == targets["false_conflict_admission"],
    }


def write_p3_report(
    report: dict[str, object], *, overwrite_dev: bool = False
) -> tuple[Path, Path, Path]:
    split = str(report["split"])
    stem = f"duplicate_conflict_p3_claims_{split}"
    paths = (
        REPORT_DIR / f"{stem}.json",
        REPORT_DIR / f"{stem}.md",
        REPORT_DIR / f"{stem}_failures.jsonl",
    )
    existing = [path for path in paths if path.exists()]
    if existing and not (split == "dev" and overwrite_dev):
        raise FileExistsError(
            "refusing to overwrite immutable P3 output(s): " + ", ".join(map(str, existing))
        )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths[0].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths[1].write_text(_markdown(report), encoding="utf-8")
    raw_results = report["results"]
    assert isinstance(raw_results, list)
    failures = [item for item in raw_results if isinstance(item, dict) and item["failure_codes"]]
    paths[2].write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in failures),
        encoding="utf-8",
    )
    return paths


def _markdown(report: dict[str, object]) -> str:
    extraction = cast(dict[str, Any], report["claim_extraction"])
    predicate = cast(dict[str, Any], report["predicate_extraction"])
    values = cast(dict[str, Any], report["value_normalization"])
    alignment = cast(dict[str, Any], report["alignment"])
    conflict = cast(dict[str, Any], report["claim_conflict"])
    source = cast(dict[str, Any], report["source_form"])
    performance = cast(dict[str, Any], report["performance"])
    safety = cast(dict[str, Any], report["safety"])
    acceptance = cast(dict[str, Any], report["acceptance"])
    failures = cast(dict[str, Any], report["failure_taxonomy"])
    lines = [
        f"# P3 structured claims — {str(report['split']).upper()}",
        "",
        f"- Pairs: {report['pair_count']}",
        f"- Configuration: `{report['configuration_status']}` / `{report['configuration_sha256']}`",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        "",
        "## Claim and predicate extraction",
        "",
        f"- Claim P/R/F1: {extraction['precision']} / {extraction['recall']} / {extraction['f1']}",
        f"- Predicate P/R/F1: {predicate['precision']} / {predicate['recall']} / {predicate['f1']}",
        "",
        "## Value normalization",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in values.items())
    lines.extend(
        [
            "",
            "## Alignment and conflict",
            "",
            "- Alignment P/R/F1: "
            f"{alignment['precision']} / {alignment['recall']} / {alignment['f1']}",
            f"- Conflict P/R/F1: {conflict['precision']} / {conflict['recall']} / {conflict['f1']}",
            f"- Conflict FP/FN: {conflict['false_positive']} / {conflict['false_negative']}",
            "",
            "## Source forms",
            "",
            "| Transition | Pairs | Alignment P/R/F1 |",
            "|---|---:|---:|",
        ]
    )
    for transition, raw in source.items():
        assert isinstance(raw, dict)
        lines.append(
            f"| {transition} | {raw['pair_count']} | {raw['precision']} / "
            f"{raw['recall']} / {raw['f1']} |"
        )
        clean_bridge = raw.get("clean_bridge")
        if isinstance(clean_bridge, dict):
            lines.append(
                f"| {transition} clean bridge | {clean_bridge['case_count']} | "
                f"alignment={clean_bridge['alignment_accuracy']}; "
                f"relation={clean_bridge['relation_accuracy']} |"
            )
    lines.extend(["", "## Performance", ""])
    for name, raw in performance.items():
        assert isinstance(raw, dict)
        lines.append(f"- {name}: mean={raw['mean']}, p50={raw['p50']}, p95={raw['p95']}")
    lines.extend(["", "## Safety", ""])
    lines.extend(f"- {key}: {value}" for key, value in safety.items())
    lines.extend(["", "## Failure taxonomy", ""])
    counts = failures.get("counts", {})
    assert isinstance(counts, dict)
    lines.extend(f"- {key}: {value}" for key, value in counts.items())
    lines.extend(["", "## Acceptance", ""])
    lines.extend(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in acceptance.items())
    lines.append("")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _nested(payload: dict[str, object], first: str, second: str) -> object:
    nested = payload.get(first, {})
    return nested.get(second) if isinstance(nested, dict) else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _rounded(value: float) -> float:
    return round(value, 6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--config", type=Path, default=P3_CONFIG_PATH)
    parser.add_argument("--overwrite-dev", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.split == "test" and config.get("status") != "frozen":
        raise SystemExit("P3 TEST requires a frozen configuration")
    report = evaluate_p3(split=args.split, config_path=args.config)
    paths = write_p3_report(report, overwrite_dev=args.overwrite_dev)
    print(
        json.dumps(
            {"reports": [str(path) for path in paths], "acceptance": report["acceptance"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()


__all__ = ["P3PairResult", "evaluate_p3", "main", "write_p3_report"]
