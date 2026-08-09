from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.pipeline.documents.extraction.tables.models import normalize_cell_text, numeric_candidate
from app.pipeline.documents.extraction.verification.config import Phase5Config
from app.pipeline.documents.extraction.verification.models import (
    ArbitrationDecision,
    ConsensusResult,
    Disagreement,
    NormalizedEvidence,
    ProviderResult,
    VerificationCase,
    _sha256_json,
    stable_id,
)
from app.pipeline.documents.extraction.verification.providers import ProviderRegistry


@dataclass(frozen=True)
class EvidenceDecisionBundle:
    evidence: tuple[NormalizedEvidence, ...]
    disagreements: tuple[Disagreement, ...]
    consensus: tuple[ConsensusResult, ...]
    decisions: tuple[ArbitrationDecision, ...]


def normalize_provider_results(
    results: tuple[ProviderResult, ...],
    *,
    registry: ProviderRegistry,
) -> tuple[NormalizedEvidence, ...]:
    evidence: list[NormalizedEvidence] = []
    for result in results:
        descriptor = registry.get(result.provider_id)
        if descriptor is None:
            continue
        normalized = _normalize_value(result.value_kind, result.raw_value)
        numeric_value = _numeric_value(normalized) if result.value_kind == "numeric" else None
        payload = {
            "case_id": result.case_id,
            "provider_id": result.provider_id,
            "value_kind": result.value_kind,
            "raw_value": result.raw_value,
            "normalized_value": normalized,
            "numeric_value": numeric_value,
            "confidence": result.confidence,
            "reliability_weight": descriptor.reliability_weight,
            "correlated_group": descriptor.correlated_group,
        }
        evidence.append(
            NormalizedEvidence(
                evidence_id=stable_id("evidence", result.result_id),
                case_id=result.case_id,
                provider_id=result.provider_id,
                value_kind=result.value_kind,
                raw_value=result.raw_value,
                normalized_value=normalized,
                numeric_value=numeric_value,
                confidence=result.confidence,
                reliability_weight=descriptor.reliability_weight,
                correlated_group=descriptor.correlated_group or result.provider_id,
                source_type=descriptor.adapter_name,
                checksum=_sha256_json(payload),
                reason_codes=("normalized_provider_output",),
            )
        )
    return tuple(evidence)


def decide_cases(
    cases: tuple[VerificationCase, ...],
    evidence: tuple[NormalizedEvidence, ...],
    *,
    config: Phase5Config,
) -> EvidenceDecisionBundle:
    evidence_by_case: dict[str, list[NormalizedEvidence]] = defaultdict(list)
    for item in evidence:
        evidence_by_case[item.case_id].append(item)
    disagreements: list[Disagreement] = []
    consensus_results: list[ConsensusResult] = []
    decisions: list[ArbitrationDecision] = []
    for case in cases:
        case_evidence = sorted(
            evidence_by_case.get(case.case_id, []),
            key=lambda item: item.provider_id,
        )
        disagreement = _detect_disagreement(case, case_evidence)
        if disagreement is not None:
            disagreements.append(disagreement)
        consensus = _consensus(case, case_evidence, disagreement, config=config)
        consensus_results.append(consensus)
        decisions.append(_arbitrate(case, case_evidence, disagreement, consensus, config=config))
    return EvidenceDecisionBundle(
        evidence=evidence,
        disagreements=tuple(disagreements),
        consensus=tuple(consensus_results),
        decisions=tuple(decisions),
    )


def _detect_disagreement(
    case: VerificationCase,
    evidence: list[NormalizedEvidence],
) -> Disagreement | None:
    values = sorted({item.normalized_value for item in evidence})
    if len(values) <= 1:
        return None
    disagreement_type = f"{case.value_kind}_conflict"
    if case.value_kind == "numeric" and any(_looks_negative(value) for value in values):
        disagreement_type = "negative_sign_conflict"
    severity = "high" if case.risk_level == "high" else "medium"
    return Disagreement(
        disagreement_id=stable_id("disagreement", case.case_id, "|".join(values)),
        case_id=case.case_id,
        disagreement_type=disagreement_type,
        severity=severity,
        provider_ids=tuple(item.provider_id for item in evidence),
        normalized_values=tuple(values),
        reason_codes=("provider_values_differ", case.value_kind),
    )


def _consensus(
    case: VerificationCase,
    evidence: list[NormalizedEvidence],
    disagreement: Disagreement | None,
    *,
    config: Phase5Config,
) -> ConsensusResult:
    verification = config.provider_verification
    if not evidence:
        return ConsensusResult(
            consensus_id=stable_id("consensus", case.case_id, "no_evidence"),
            case_id=case.case_id,
            status="no_evidence",
            normalized_value=None,
            confidence=0.0,
            support_provider_ids=(),
            conflicting_provider_ids=(),
            rule="no_provider_result",
            reason_codes=("no_evidence",),
        )
    scored = _score_values(evidence)
    top_value, top_score, support = scored[0]
    conflict_providers = tuple(
        item.provider_id for item in evidence if item.normalized_value != top_value
    )
    status = "agreed" if disagreement is None else "ranked_conflict"
    if top_score < verification.min_consensus_confidence:
        status = "low_confidence"
    return ConsensusResult(
        consensus_id=stable_id("consensus", case.case_id, top_value, round(top_score, 6)),
        case_id=case.case_id,
        status=status,
        normalized_value=top_value,
        confidence=round(top_score, 6),
        support_provider_ids=tuple(item.provider_id for item in support),
        conflicting_provider_ids=conflict_providers,
        rule="weighted_capability_consensus",
        reason_codes=("not_blind_majority", "correlated_sources_deduped"),
    )


def _arbitrate(
    case: VerificationCase,
    evidence: list[NormalizedEvidence],
    disagreement: Disagreement | None,
    consensus: ConsensusResult,
    *,
    config: Phase5Config,
) -> ArbitrationDecision:
    verification = config.provider_verification
    groups = {item.correlated_group for item in evidence}
    required_groups = 2 if (case.risk_level == "high" or case.high_value) else 1
    if len(groups) < required_groups:
        return _manual_review_decision(
            case,
            evidence,
            "insufficient_independent_evidence",
            ("high_risk_requires_two_sources",),
        )
    if consensus.normalized_value is None:
        return _manual_review_decision(case, evidence, "no_consensus", ("no_evidence",))
    if consensus.confidence < verification.min_arbitration_confidence:
        return _manual_review_decision(case, evidence, "low_confidence", ("low_confidence",))
    if disagreement is not None and case.value_kind in {"text", "header"}:
        scored = _score_values(evidence)
        second = scored[1][1] if len(scored) > 1 else 0.0
        if consensus.confidence - second < 0.10:
            return _manual_review_decision(
                case,
                evidence,
                "unresolved_text_disagreement",
                ("close_provider_scores",),
            )
    provider_ids = tuple(item.provider_id for item in evidence)
    evidence_ids = tuple(item.evidence_id for item in evidence)
    return ArbitrationDecision(
        decision_id=stable_id("decision", case.case_id, consensus.normalized_value),
        case_id=case.case_id,
        status="accepted",
        verified_value=consensus.normalized_value,
        raw_value_preserved=case.raw_value,
        confidence=consensus.confidence,
        provider_ids=provider_ids,
        evidence_ids=evidence_ids,
        decision_reason=(
            "evidence_agreement" if disagreement is None else "weighted_resolver_arbitration"
        ),
        review_required=False,
        unsafe_acceptance=False,
        reason_codes=tuple(
            sorted(
                {
                    "raw_value_preserved",
                    "deterministic_arbitration",
                    *consensus.reason_codes,
                }
            )
        ),
    )


def _manual_review_decision(
    case: VerificationCase,
    evidence: list[NormalizedEvidence],
    reason: str,
    reason_codes: tuple[str, ...],
) -> ArbitrationDecision:
    return ArbitrationDecision(
        decision_id=stable_id("decision", case.case_id, reason),
        case_id=case.case_id,
        status="manual_review",
        verified_value=None,
        raw_value_preserved=case.raw_value,
        confidence=0.0,
        provider_ids=tuple(item.provider_id for item in evidence),
        evidence_ids=tuple(item.evidence_id for item in evidence),
        decision_reason=reason,
        review_required=True,
        unsafe_acceptance=False,
        reason_codes=tuple(sorted({"raw_value_preserved", *reason_codes})),
    )


def _score_values(
    evidence: list[NormalizedEvidence],
) -> list[tuple[str, float, list[NormalizedEvidence]]]:
    by_value: dict[str, list[NormalizedEvidence]] = defaultdict(list)
    for item in evidence:
        by_value[item.normalized_value].append(item)
    scored: list[tuple[str, float, list[NormalizedEvidence]]] = []
    for value, items in by_value.items():
        best_by_group: dict[str, NormalizedEvidence] = {}
        for item in items:
            current = best_by_group.get(item.correlated_group)
            if current is None or _evidence_score(item) > _evidence_score(current):
                best_by_group[item.correlated_group] = item
        supporting = list(best_by_group.values())
        score = max(_evidence_score(item) for item in supporting)
        if len(supporting) > 1:
            score = min(1.0, score + 0.05 * (len(supporting) - 1))
        scored.append((value, round(score, 6), supporting))
    return sorted(scored, key=lambda item: (-item[1], item[0]))


def _evidence_score(item: NormalizedEvidence) -> float:
    return float(item.reliability_weight) * float(item.confidence)


def _normalize_value(value_kind: str, raw_value: str) -> str:
    if value_kind == "numeric":
        _numeric_text, parsed, _value_type = numeric_candidate(raw_value)
        if parsed is None:
            return normalize_cell_text(raw_value)
        if float(parsed).is_integer():
            return str(int(parsed))
        return str(parsed)
    return normalize_cell_text(raw_value)


def _numeric_value(value: str) -> float | None:
    _numeric_text, parsed, _value_type = numeric_candidate(value)
    return parsed


def _looks_negative(value: str) -> bool:
    return str(value).strip().startswith("-")


__all__ = [
    "EvidenceDecisionBundle",
    "decide_cases",
    "normalize_provider_results",
]
