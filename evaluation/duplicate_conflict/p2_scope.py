"""P2 evaluator for deterministic entity, business-scope, and admission logic."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from app.knowledge_quality.application.analysis import analyze_text_relation, strict_normalize_text
from app.knowledge_quality.application.business_scope import (
    ScopeTextContext,
    resolve_business_context,
)
from app.knowledge_quality.application.conflict_admission import decide_conflict_admission
from app.knowledge_quality.application.scope import (
    compare_claim_scopes,
    extract_claim_scope,
)
from app.knowledge_quality.domain.models import ScopeComparison
from app.knowledge_quality.domain.scope_models import (
    ConflictAdmissionDisposition,
    ResolvedBusinessContext,
)
from app.pipeline.shared.text_utils import compute_checksum_text, normalize_text
from app.structured_facts.application.scope import explain_business_scope_relation
from app.structured_facts.domain.models import (
    EntityEvidenceSource,
    ScopeRelation,
)
from evaluation.duplicate_conflict.models import GoldPair, GoldRelation
from evaluation.duplicate_conflict.validation import load_pairs

P2_CONFIG_PATH = Path("configs/evaluation/p2_domain_scope.json")
DEV_DATASET_PATH = Path("datasets/duplicate_conflict/gold_v1_dev.jsonl")
TEST_DATASET_PATH = Path("datasets/duplicate_conflict/gold_v1_test.jsonl")
REPORT_DIR = Path("reports/evaluation")
_RELATION_MAPPING = {
    "exact_content": "EXACT_DUPLICATE",
    "technical_duplicate": "EXACT_DUPLICATE",
    "near_duplicate": "NEAR_DUPLICATE",
    "version_candidate": "VERSION_UPDATE",
    "version": "VERSION_UPDATE",
    "temporal_series": "TEMPORAL_VARIANT",
    "template_variant": "TEMPLATE_VARIANT",
    "conflict_candidate": "CONFLICT",
    "conflict": "CONFLICT",
    "distinct": "DISTINCT",
    "related": "UNCERTAIN",
}
_SCOPE_RELIABLE_VALUE_ONLY_VARIATIONS = {"ocr_semantic_value_corruption"}


@dataclass(frozen=True, slots=True)
class P2PairResult:
    pair_id: str
    expected_relation: str
    domain: str
    difficulty: str
    ocr_level: str
    expected_entity_a: str
    expected_entity_b: str
    predicted_entity_a: str | None
    predicted_entity_b: str | None
    expected_same_entity: bool
    predicted_same_entity: bool | None
    expected_scope_relation: str
    predicted_scope_relation: str
    expected_temporal_compatible: bool
    predicted_temporal_relation: str
    expected_qualifier_compatible: bool
    predicted_qualifier_compatibility: str
    expected_admission: bool
    predicted_admission: bool
    admission_disposition: str
    reason_codes: tuple[str, ...]
    unknown: bool
    legacy_scope: str
    oracle_classifier_prediction: str
    combined_prediction: str
    false_auto_reuse: bool
    ablation_admissions: dict[str, bool]


def evaluate_p2(
    *,
    split: str,
    config_path: Path = P2_CONFIG_PATH,
) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    dataset_path = DEV_DATASET_PATH if split == "dev" else TEST_DATASET_PATH
    pairs = load_pairs(dataset_path)
    results = tuple(_evaluate_pair(pair) for pair in pairs)
    entity = _entity_metrics(results)
    admission = _binary_metrics(
        [item.expected_admission for item in results],
        [item.predicted_admission for item in results],
    )
    report = {
        "version": config["version"],
        "split": split,
        "configuration_status": config["status"],
        "configuration_sha256": _sha256(config_path),
        "dataset": str(dataset_path),
        "dataset_sha256": _sha256(dataset_path),
        "pair_count": len(results),
        "p1_state": _p1_state(config),
        "entity_metrics": entity,
        "scope_metrics": _scope_metrics(results),
        "temporal_metrics": _temporal_metrics(results),
        "qualifier_metrics": _qualifier_metrics(results),
        "admission_metrics": admission,
        "breakdowns": {
            "domain": _breakdowns(results, "domain"),
            "difficulty": _breakdowns(results, "difficulty"),
            "ocr_level": _breakdowns(results, "ocr_level"),
        },
        "ablation": _ablation(results),
        "critical_case_matrix": _critical_case_matrix(),
        "classifier_impact": _classifier_impact(results),
        "safety": {
            "false_auto_reuse": sum(item.false_auto_reuse for item in results),
            "false_entity_merges": entity["false_entity_merges"],
            "false_conflict_admissions": admission["false_positive"],
            "unknown_count": sum(item.unknown for item in results),
            "unknown_rate": _rounded(sum(item.unknown for item in results) / len(results)),
        },
        "errors": _errors(results),
        "gold_admission_policy": config["gold_admission_policy"],
        "results": [asdict(item) for item in results],
    }
    report["acceptance"] = _acceptance(report, config)
    return report


def _evaluate_pair(pair: GoldPair) -> P2PairResult:
    left = _resolve_side(pair, "a")
    right = _resolve_side(pair, "b")
    legacy = compare_claim_scopes(
        extract_claim_scope(pair.text_a),
        extract_claim_scope(pair.text_b),
    )
    decision = decide_conflict_admission(left, right, legacy_scope=legacy.value)
    left_expected = _expected_entity_id(pair, "a")
    right_expected = _expected_entity_id(pair, "b")
    left_predicted = left.primary_entity.canonical_id if left.primary_entity else None
    right_predicted = right.primary_entity.canonical_id if right.primary_entity else None
    predicted_same = (
        left_predicted == right_predicted
        if left_predicted is not None and right_predicted is not None
        else None
    )
    predicted_scope = (
        ScopeRelation.DISJOINT.value if predicted_same is False else decision.scope_relation.value
    )
    expected_scope = (
        ScopeRelation.SAME.value
        if pair.same_entity and pair.same_business_scope
        else ScopeRelation.DISJOINT.value
    )
    expected_admission = _expected_admission(pair)
    classifier = analyze_text_relation(pair.text_a, pair.text_b, domain_scope_mode="off")
    classifier_prediction = _RELATION_MAPPING[classifier.relation_type.value]
    combined_prediction = (
        classifier_prediction
        if decision.allows_conflict_analysis
        else _blocked_prediction(decision.disposition)
    )
    strict_identity = strict_normalize_text(pair.text_a) == strict_normalize_text(pair.text_b)
    embedding_identity = compute_checksum_text(
        normalize_text(pair.text_a)
    ) == compute_checksum_text(normalize_text(pair.text_b))
    ocr_rank = {"none": 0, "light": 1, "medium": 2, "severe": 3}
    return P2PairResult(
        pair_id=pair.pair_id,
        expected_relation=pair.expected_relation.value,
        domain=pair.domain.value,
        difficulty=pair.difficulty.value,
        ocr_level=max(
            (pair.ocr_noise_level_a.value, pair.ocr_noise_level_b.value),
            key=ocr_rank.__getitem__,
        ),
        expected_entity_a=left_expected,
        expected_entity_b=right_expected,
        predicted_entity_a=left_predicted,
        predicted_entity_b=right_predicted,
        expected_same_entity=pair.same_entity,
        predicted_same_entity=predicted_same,
        expected_scope_relation=expected_scope,
        predicted_scope_relation=predicted_scope,
        expected_temporal_compatible=pair.same_temporal_scope,
        predicted_temporal_relation=decision.temporal_relation.value,
        expected_qualifier_compatible=pair.same_business_scope,
        predicted_qualifier_compatibility=decision.qualifier_compatibility.value,
        expected_admission=expected_admission,
        predicted_admission=decision.allows_conflict_analysis,
        admission_disposition=decision.disposition.value,
        reason_codes=decision.reason_codes,
        unknown=decision.disposition is ConflictAdmissionDisposition.UNCERTAIN,
        legacy_scope=legacy.value,
        oracle_classifier_prediction=classifier_prediction,
        combined_prediction=combined_prediction,
        false_auto_reuse=(strict_identity and embedding_identity and not pair.expected_auto_reuse),
        ablation_admissions=_ablation_predictions(
            pair, left, right, legacy, decision.allows_conflict_analysis
        ),
    )


def _resolve_side(pair: GoldPair, side: str) -> ResolvedBusinessContext:
    raw_contexts = pair.context_a if side == "a" else pair.context_b
    contexts = tuple(
        ScopeTextContext(
            text,
            EntityEvidenceSource.SECTION_HEADING
            if index == 0
            else EntityEvidenceSource.PARENT_CONTEXT,
            f"{pair.pair_id}:{side}:context:{index}",
        )
        for index, text in enumerate(raw_contexts)
    )
    return resolve_business_context(
        pair.text_a if side == "a" else pair.text_b,
        contexts=contexts,
        domain_hint=pair.domain.value,
    )


def _expected_entity_id(pair: GoldPair, side: str) -> str:
    entity = pair.entity_a if side == "a" else pair.entity_b
    if pair.domain.value == "vinfast":
        number = re.search(r"\d+", str(entity["model"]))
        if number is None:
            raise ValueError(f"missing model number for {pair.pair_id}")
        return f"vinfast_vf{number.group()}"
    project = _fold(str(entity["project"]))
    return project.replace(" ", "_")


def _expected_admission(pair: GoldPair) -> bool:
    scope_reliable = (
        pair.extraction_reliability_a.value == "high"
        and pair.extraction_reliability_b.value == "high"
    ) or pair.variation_type in _SCOPE_RELIABLE_VALUE_ONLY_VARIATIONS
    return bool(
        pair.same_entity
        and pair.same_business_scope
        and pair.same_temporal_scope
        and pair.same_claim
        and scope_reliable
    )


def _entity_metrics(results: tuple[P2PairResult, ...]) -> dict[str, object]:
    true_positive = false_positive = false_negative = 0
    for item in results:
        for expected, predicted in (
            (item.expected_entity_a, item.predicted_entity_a),
            (item.expected_entity_b, item.predicted_entity_b),
        ):
            if expected == predicted:
                true_positive += 1
            else:
                false_negative += 1
                false_positive += predicted is not None
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    )
    same_rows = [item for item in results if item.expected_same_entity]
    different_rows = [item for item in results if not item.expected_same_entity]
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": _rounded(precision),
        "recall": _rounded(recall),
        "f1": _rounded(_f1(precision, recall)),
        "same_entity_pair_accuracy": _rounded(
            sum(item.predicted_same_entity is True for item in same_rows) / len(same_rows)
        )
        if same_rows
        else 0.0,
        "different_entity_pair_accuracy": _rounded(
            sum(item.predicted_same_entity is False for item in different_rows)
            / len(different_rows)
        )
        if different_rows
        else 0.0,
        "unknown_rate": _rounded(
            sum(item.predicted_same_entity is None for item in results) / len(results)
        ),
        "false_entity_merges": sum(
            item.predicted_same_entity is True and not item.expected_same_entity for item in results
        ),
    }


def _scope_metrics(results: tuple[P2PairResult, ...]) -> dict[str, object]:
    expected = [item.expected_scope_relation for item in results]
    predicted = [item.predicted_scope_relation for item in results]
    disjoint = _binary_metrics(
        [value == ScopeRelation.DISJOINT.value for value in expected],
        [value == ScopeRelation.DISJOINT.value for value in predicted],
    )
    return {
        "accuracy": _rounded(
            sum(a == b for a, b in zip(expected, predicted, strict=True)) / len(results)
        ),
        "disjoint_precision": disjoint["precision"],
        "disjoint_recall": disjoint["recall"],
        "unknown_rate": _rounded(
            sum(value == ScopeRelation.UNKNOWN.value for value in predicted) / len(results)
        ),
        "predicted_distribution": dict(sorted(Counter(predicted).items())),
    }


def _temporal_metrics(results: tuple[P2PairResult, ...]) -> dict[str, object]:
    predicted_compatible = [
        item.predicted_temporal_relation
        in {"same", "left_contains_right", "right_contains_left", "overlaps"}
        for item in results
    ]
    metrics = _binary_metrics(
        [item.expected_temporal_compatible for item in results], predicted_compatible
    )
    metrics["unknown_rate"] = _rounded(
        sum(item.predicted_temporal_relation == "unknown" for item in results) / len(results)
    )
    return metrics


def _qualifier_metrics(results: tuple[P2PairResult, ...]) -> dict[str, object]:
    compatible = {"equal", "compatible"}
    return _binary_metrics(
        [item.expected_qualifier_compatible for item in results],
        [item.predicted_qualifier_compatibility in compatible for item in results],
    )


def _breakdowns(results: tuple[P2PairResult, ...], field: str) -> dict[str, object]:
    groups: dict[str, list[P2PairResult]] = defaultdict(list)
    for item in results:
        groups[str(getattr(item, field))].append(item)
    output: dict[str, object] = {}
    for key, values in sorted(groups.items()):
        subset = tuple(values)
        output[key] = {
            "count": len(subset),
            "entity": _entity_metrics(subset),
            "admission": _binary_metrics(
                [item.expected_admission for item in subset],
                [item.predicted_admission for item in subset],
            ),
        }
    return output


def _ablation(results: tuple[P2PairResult, ...]) -> dict[str, object]:
    names = (
        "legacy_scope_only",
        "entity_registry",
        "plus_vinhomes_scope",
        "plus_vinfast_scope",
        "full_p2_scope_temporal_qualifiers",
    )
    expected = [item.expected_admission for item in results]
    return {
        name: {
            **_binary_metrics(expected, [item.ablation_admissions[name] for item in results]),
            "false_admissions_removed_vs_registry": (
                sum(
                    item.ablation_admissions["entity_registry"] and not item.expected_admission
                    for item in results
                )
                - sum(
                    item.ablation_admissions[name] and not item.expected_admission
                    for item in results
                )
            ),
        }
        for name in names
    }


def _ablation_predictions(
    pair: GoldPair,
    left: ResolvedBusinessContext,
    right: ResolvedBusinessContext,
    legacy: ScopeComparison,
    full: bool,
) -> dict[str, bool]:
    left_entity = left.primary_entity
    right_entity = right.primary_entity
    entity_same = bool(
        left_entity and right_entity and left_entity.canonical_id == right_entity.canonical_id
    )
    scope_comparable = explain_business_scope_relation(
        left.business_scope, right.business_scope
    ).relation in {
        ScopeRelation.SAME,
        ScopeRelation.LEFT_CONTAINS_RIGHT,
        ScopeRelation.RIGHT_CONTAINS_LEFT,
        ScopeRelation.OVERLAPS,
    }
    return {
        "legacy_scope_only": legacy is ScopeComparison.SAME_SCOPE,
        "entity_registry": entity_same,
        "plus_vinhomes_scope": (
            entity_same and scope_comparable if pair.domain.value == "vinhomes" else entity_same
        ),
        "plus_vinfast_scope": entity_same and scope_comparable,
        "full_p2_scope_temporal_qualifiers": full,
    }


def _classifier_impact(results: tuple[P2PairResult, ...]) -> dict[str, object]:
    expected = [item.expected_relation for item in results]
    oracle = [item.oracle_classifier_prediction for item in results]
    reached = [item for item in results if item.predicted_admission]
    combined = [item.combined_prediction for item in results]
    conflict = _binary_metrics(
        [value == GoldRelation.CONFLICT.value for value in expected],
        [value == GoldRelation.CONFLICT.value for value in combined],
    )
    return {
        "oracle_pair_count": len(results),
        "oracle_pair_accuracy": _rounded(
            sum(a == b for a, b in zip(expected, oracle, strict=True)) / len(results)
        ),
        "reached_classifier_count": len(reached),
        "reached_classifier_accuracy": _rounded(
            sum(item.expected_relation == item.oracle_classifier_prediction for item in reached)
            / len(reached)
        )
        if reached
        else 0.0,
        "combined_accuracy": _rounded(
            sum(a == b for a, b in zip(expected, combined, strict=True)) / len(results)
        ),
        "conflict_precision": conflict["precision"],
        "conflict_recall": conflict["recall"],
        "conflict_fp": conflict["false_positive"],
        "conflict_fn": conflict["false_negative"],
        "classifier_thresholds_changed": False,
    }


def _errors(results: tuple[P2PairResult, ...]) -> dict[str, object]:
    false_merges = [
        item.pair_id
        for item in results
        if item.predicted_same_entity is True and not item.expected_same_entity
    ]
    misses = [
        item.pair_id
        for item in results
        if item.predicted_entity_a is None or item.predicted_entity_b is None
    ]
    false_admissions = [
        item.pair_id for item in results if item.predicted_admission and not item.expected_admission
    ]
    blocked = [
        {
            "pair_id": item.pair_id,
            "reason_codes": list(item.reason_codes),
            "taxonomy": _p2_error_taxonomy(item),
        }
        for item in results
        if item.expected_admission and not item.predicted_admission
    ]
    taxonomy = Counter(item["taxonomy"] for item in blocked)
    return {
        "false_entity_merges": false_merges,
        "missed_entity_resolution": misses,
        "false_conflict_admissions": false_admissions,
        "blocked_true_conflicts": blocked,
        "taxonomy": dict(sorted(taxonomy.items())),
    }


def _p2_error_taxonomy(item: P2PairResult) -> str:
    reasons = " ".join(item.reason_codes)
    if "vehicle" in reasons:
        return "VEHICLE_SCOPE_ERROR"
    if "commercial" in reasons:
        return "COMMERCIAL_SCOPE_ERROR"
    if "product" in reasons:
        return "PRODUCT_SCOPE_ERROR"
    if "temporal" in reasons:
        return "TEMPORAL_SCOPE_ERROR"
    if "qualifier" in reasons:
        return "QUALIFIER_SCOPE_ERROR"
    if "entity" in reasons:
        return "ENTITY_MENTION_MISS"
    return "SCOPE_ERROR"


def _critical_case_matrix() -> dict[str, object]:
    cases = (
        (
            "vinhomes_different_project",
            "Giá căn 2PN tại Project Alpha năm 2026 là 6 tỷ/căn.",
            "Giá căn 2PN tại Project Beta năm 2026 là 7 tỷ/căn.",
            False,
        ),
        (
            "vinhomes_different_phase",
            "Project Alpha giai đoạn 1 căn 2PN năm 2026 giá 6 tỷ/căn.",
            "Project Alpha giai đoạn 2 căn 2PN năm 2026 giá 7 tỷ/căn.",
            False,
        ),
        (
            "vinhomes_different_building",
            "Project Alpha tòa S1 căn 2PN năm 2026 giá 6 tỷ/căn.",
            "Project Alpha tòa S2 căn 2PN năm 2026 giá 7 tỷ/căn.",
            False,
        ),
        (
            "vinhomes_different_unit",
            "Project Alpha unit 1208 năm 2026 giá 6 tỷ/căn.",
            "Project Alpha unit 1508 năm 2026 giá 7 tỷ/căn.",
            False,
        ),
        (
            "vinhomes_2pn_vs_3pn",
            "Project Alpha căn 2PN năm 2026 giá 6 tỷ/căn.",
            "Project Alpha căn 3PN năm 2026 giá 7 tỷ/căn.",
            False,
        ),
        (
            "vinhomes_official_vs_secondary",
            "Project Alpha căn 2PN năm 2026 giá chính thức 6 tỷ/căn.",
            "Project Alpha căn 2PN năm 2026 giá chào thứ cấp 7 tỷ/căn.",
            False,
        ),
        (
            "vinhomes_asking_vs_transaction",
            "Project Alpha căn 2PN năm 2026 giá chào 6 tỷ/căn.",
            "Project Alpha căn 2PN năm 2026 giá giao dịch 7 tỷ/căn.",
            False,
        ),
        (
            "vinhomes_per_unit_vs_per_m2",
            "Project Alpha căn 2PN năm 2026 giá 6 tỷ/căn.",
            "Project Alpha căn 2PN năm 2026 giá 100 triệu/m2.",
            False,
        ),
        (
            "vinhomes_2025_vs_2026",
            "Project Alpha căn 2PN năm 2025 giá 6 tỷ/căn.",
            "Project Alpha căn 2PN năm 2026 giá 7 tỷ/căn.",
            False,
        ),
        (
            "vinfast_vf8_vs_vf9",
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF9 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            False,
        ),
        (
            "vinfast_eco_vs_plus",
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF8 Plus đời 2025 tại Việt Nam tầm 470 km WLTP.",
            False,
        ),
        (
            "vinfast_model_year",
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF8 Eco đời 2026 tại Việt Nam tầm 470 km WLTP.",
            False,
        ),
        (
            "vinfast_market",
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF8 Eco đời 2025 tại Mỹ tầm 470 km WLTP.",
            False,
        ),
        (
            "vinfast_protocol",
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VF8 Eco đời 2025 tại Việt Nam tầm 420 km EPA.",
            False,
        ),
        (
            "vinfast_battery_variant",
            "VF8 Eco đời 2025 pin standard tại Việt Nam tầm 450 km WLTP.",
            "VF8 Eco đời 2025 pin extended tại Việt Nam tầm 470 km WLTP.",
            False,
        ),
        (
            "vinfast_charging_condition",
            "VF8 Eco đời 2025 tại Việt Nam sạc từ 10% đến 70% trong 25 phút.",
            "VF8 Eco đời 2025 tại Việt Nam sạc từ 10% đến 80% trong 25 phút.",
            False,
        ),
        (
            "true_vinhomes_price",
            "Project Alpha căn 2PN năm 2026 giá thị trường sơ cấp 6,2 tỷ/căn.",
            "Vinhomes Project Alpha căn 2PN năm 2026 giá thị trường sơ cấp 7,1 tỷ/căn.",
            True,
        ),
        (
            "true_vinfast_range",
            "VF8 Eco đời 2025 tại Việt Nam tầm 450 km WLTP.",
            "VinFast VF 8 Eco đời 2025 tại Việt Nam tầm 480 km WLTP.",
            True,
        ),
    )
    output: dict[str, object] = {}
    for name, left_text, right_text, expected in cases:
        left = resolve_business_context(left_text)
        right = resolve_business_context(right_text)
        decision = decide_conflict_admission(left, right)
        output[name] = {
            "expected_admission": expected,
            "predicted_admission": decision.allows_conflict_analysis,
            "status": "PASS" if decision.allows_conflict_analysis is expected else "FAIL",
            "disposition": decision.disposition.value,
            "reason_codes": list(decision.reason_codes),
        }
    return output


def _blocked_prediction(disposition: ConflictAdmissionDisposition) -> str:
    return {
        ConflictAdmissionDisposition.DISTINCT_ENTITY: "DISTINCT",
        ConflictAdmissionDisposition.CONDITIONAL_VARIANT: "CONDITIONAL_VARIANT",
        ConflictAdmissionDisposition.TEMPORAL_VARIANT: "TEMPORAL_VARIANT",
        ConflictAdmissionDisposition.UNCERTAIN: "UNCERTAIN",
        ConflictAdmissionDisposition.ADMIT: "UNCERTAIN",
    }[disposition]


def _binary_metrics(expected: list[bool], predicted: list[bool]) -> dict[str, object]:
    true_positive = sum(a and b for a, b in zip(expected, predicted, strict=True))
    false_positive = sum(not a and b for a, b in zip(expected, predicted, strict=True))
    false_negative = sum(a and not b for a, b in zip(expected, predicted, strict=True))
    true_negative = sum(not a and not b for a, b in zip(expected, predicted, strict=True))
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    )
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": _rounded(precision),
        "recall": _rounded(recall),
        "f1": _rounded(_f1(precision, recall)),
        "accuracy": _rounded((true_positive + true_negative) / len(expected)) if expected else 0.0,
    }


def _p1_state(config: dict[str, Any]) -> dict[str, object]:
    p1_path = Path(str(config["p1_config"]))
    p1_dev = json.loads(
        Path("reports/evaluation/p1_candidate_generation_dev.json").read_text(encoding="utf-8")
    )
    p1_test = json.loads(
        Path("reports/evaluation/p1_candidate_generation_test.json").read_text(encoding="utf-8")
    )
    return {
        "config_sha256": _sha256(p1_path),
        "retuned_in_p2": False,
        "dev_recall_at_50": p1_dev["candidate_generation"]["recall@50"],
        "test_recall_at_50_frozen_existing": p1_test["candidate_generation"]["recall@50"],
        "test_report_rerun_by_p2_evaluator": False,
    }


def _acceptance(report: dict[str, object], config: dict[str, Any]) -> dict[str, object]:
    targets = config["targets"]
    entity = cast(dict[str, Any], report["entity_metrics"])
    admission = cast(dict[str, Any], report["admission_metrics"])
    safety = cast(dict[str, Any], report["safety"])
    critical = cast(dict[str, dict[str, Any]], report["critical_case_matrix"])
    return {
        "entity_precision": float(entity["precision"]) >= float(targets["entity_precision"]),
        "entity_recall": float(entity["recall"]) >= float(targets["entity_recall"]),
        "admission_precision": float(admission["precision"])
        >= float(targets["admission_precision"]),
        "admission_recall": float(admission["recall"]) >= float(targets["admission_recall"]),
        "false_auto_reuse": int(safety["false_auto_reuse"]) == int(targets["false_auto_reuse"]),
        "critical_matrix": all(item["status"] == "PASS" for item in critical.values()),
    }


def write_p2_report(report: dict[str, object], *, overwrite_dev: bool = False) -> tuple[Path, Path]:
    split = str(report["split"])
    json_path = REPORT_DIR / f"duplicate_conflict_p2_scope_{split}.json"
    markdown_path = REPORT_DIR / f"duplicate_conflict_p2_scope_{split}.md"
    existing = [path for path in (json_path, markdown_path) if path.exists()]
    if existing and not (split == "dev" and overwrite_dev):
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"refusing to overwrite immutable P2 output(s): {joined}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _markdown(report: dict[str, object]) -> str:
    entity = cast(dict[str, Any], report["entity_metrics"])
    scope = cast(dict[str, Any], report["scope_metrics"])
    temporal = cast(dict[str, Any], report["temporal_metrics"])
    qualifier = cast(dict[str, Any], report["qualifier_metrics"])
    admission = cast(dict[str, Any], report["admission_metrics"])
    classifier = cast(dict[str, Any], report["classifier_impact"])
    safety = cast(dict[str, Any], report["safety"])
    p1_state = cast(dict[str, Any], report["p1_state"])
    breakdowns = cast(dict[str, dict[str, Any]], report["breakdowns"])
    ablation = cast(dict[str, dict[str, Any]], report["ablation"])
    critical = cast(dict[str, dict[str, Any]], report["critical_case_matrix"])
    errors = cast(dict[str, Any], report["errors"])
    acceptance = cast(dict[str, bool], report["acceptance"])
    lines = [
        f"# P2 domain entity and business scope — {str(report['split']).upper()}",
        "",
        f"- Pairs: {report['pair_count']}",
        f"- Configuration status: `{report['configuration_status']}`",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        f"- Configuration SHA-256: `{report['configuration_sha256']}`",
        "",
        "## Frozen P1 state",
        "",
        f"- DEV Candidate Recall@50: {p1_state['dev_recall_at_50']}",
        "- Existing frozen TEST Candidate Recall@50: "
        f"{p1_state['test_recall_at_50_frozen_existing']}",
        f"- P1 retuned in P2: {p1_state['retuned_in_p2']}",
        "",
        "## Entity resolution",
        "",
        f"- Precision: {entity['precision']}",
        f"- Recall: {entity['recall']}",
        f"- F1: {entity['f1']}",
        f"- Same-entity pair accuracy: {entity['same_entity_pair_accuracy']}",
        f"- Different-entity pair accuracy: {entity['different_entity_pair_accuracy']}",
        f"- Entity unknown rate: {entity['unknown_rate']}",
        f"- False merges: {entity['false_entity_merges']}",
        "",
        "## Scope and conflict admission",
        "",
        f"- Scope relation accuracy: {scope['accuracy']}",
        "- Scope disjoint precision / recall: "
        f"{scope['disjoint_precision']} / {scope['disjoint_recall']}",
        f"- Admission precision / recall: {admission['precision']} / {admission['recall']}",
        f"- Admission FP / FN: {admission['false_positive']} / {admission['false_negative']}",
        f"- Unknown rate: {safety['unknown_rate']}",
        "",
        "## Temporal and qualifier compatibility",
        "",
        "- Temporal precision / recall / F1: "
        f"{temporal['precision']} / {temporal['recall']} / {temporal['f1']}",
        f"- Temporal unknown rate: {temporal['unknown_rate']}",
        "- Qualifier precision / recall / F1: "
        f"{qualifier['precision']} / {qualifier['recall']} / {qualifier['f1']}",
        "",
        "## Existing classifier after gate",
        "",
        f"- Oracle-pair accuracy: {classifier['oracle_pair_accuracy']}",
        f"- Reached-classifier accuracy: {classifier['reached_classifier_accuracy']}",
        "- Conflict precision / recall: "
        f"{classifier['conflict_precision']} / {classifier['conflict_recall']}",
        f"- Conflict FP / FN: {classifier['conflict_fp']} / {classifier['conflict_fn']}",
        "",
        "## Safety",
        "",
        f"- False auto-reuse: {safety['false_auto_reuse']}",
        f"- False entity merges: {safety['false_entity_merges']}",
        f"- False conflict admissions: {safety['false_conflict_admissions']}",
        "",
    ]
    for dimension in ("domain", "difficulty", "ocr_level"):
        groups = breakdowns[dimension]
        assert isinstance(groups, dict)
        lines.extend(
            [
                f"## {dimension.replace('_', ' ').title()} breakdown",
                "",
                "| Group | Pairs | Entity P/R/F1 | Admission P/R | Admission FP/FN |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for name, raw_metrics in groups.items():
            assert isinstance(raw_metrics, dict)
            group_entity = raw_metrics["entity"]
            group_admission = raw_metrics["admission"]
            assert isinstance(group_entity, dict) and isinstance(group_admission, dict)
            lines.append(
                f"| {name} | {raw_metrics['count']} | "
                f"{group_entity['precision']} / {group_entity['recall']} / "
                f"{group_entity['f1']} | {group_admission['precision']} / "
                f"{group_admission['recall']} | {group_admission['false_positive']} / "
                f"{group_admission['false_negative']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Ablation",
            "",
            "| Layer | Precision | Recall | F1 | False admissions removed vs registry |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, raw_metrics in ablation.items():
        assert isinstance(raw_metrics, dict)
        lines.append(
            f"| `{name}` | {raw_metrics['precision']} | {raw_metrics['recall']} | "
            f"{raw_metrics['f1']} | {raw_metrics['false_admissions_removed_vs_registry']} |"
        )

    lines.extend(["", "## Critical case matrix", "", "| Case | Result |", "|---|---:|"])
    for name, raw_case in critical.items():
        assert isinstance(raw_case, dict)
        lines.append(f"| `{name}` | {raw_case['status']} |")

    taxonomy = errors.get("taxonomy", {})
    assert isinstance(taxonomy, dict)
    lines.extend(
        [
            "",
            "## Remaining P2 errors",
            "",
            f"- Missed entity resolutions: {len(errors['missed_entity_resolution'])}",
            f"- False conflict admissions: {len(errors['false_conflict_admissions'])}",
            f"- Blocked true conflicts: {len(errors['blocked_true_conflicts'])}",
            "- Taxonomy: "
            + (", ".join(f"{name}={count}" for name, count in taxonomy.items()) or "none"),
            "",
            "## Acceptance",
            "",
        ]
    )
    lines.extend(
        f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in acceptance.items()
    )
    lines.extend(
        [
            "",
            "Pair-level evidence and complete error records are retained in the JSON report.",
            "",
        ]
    )
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    plain = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _rounded(value: float) -> float:
    return round(value, 6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--config", type=Path, default=P2_CONFIG_PATH)
    parser.add_argument("--overwrite-dev", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.split == "test" and config.get("status") != "frozen":
        raise SystemExit("P2 TEST requires a frozen configuration")
    report = evaluate_p2(split=args.split, config_path=args.config)
    paths = write_p2_report(report, overwrite_dev=args.overwrite_dev)
    print(
        json.dumps(
            {"reports": [str(path) for path in paths], "acceptance": report["acceptance"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()


__all__ = ["P2PairResult", "evaluate_p2", "main", "write_p2_report"]
