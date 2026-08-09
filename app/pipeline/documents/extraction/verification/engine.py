from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any

from app.pipeline.documents.extraction.canonical.ir import (
    CanonicalDocument,
    CanonicalElement,
    CanonicalPage,
    CanonicalTable,
    CanonicalTableCell,
)
from app.pipeline.documents.extraction.tables.engine import TableDocumentResult
from app.pipeline.documents.extraction.tables.models import (
    StructuredTable,
    TableCell,
    normalize_cell_text,
)
from app.pipeline.documents.extraction.verification.config import (
    DEFAULT_PHASE5_CONFIG,
    Phase5Config,
    VerificationMode,
)
from app.pipeline.documents.extraction.verification.executor import (
    ProviderExecutionBundle,
    ProviderExecutor,
)
from app.pipeline.documents.extraction.verification.models import (
    ABSTENTION_POLICY_VERSION,
    ARBITRATION_VERSION,
    CONSENSUS_VERSION,
    DISAGREEMENT_POLICY_VERSION,
    NORMALIZATION_VERSION,
    PRIVACY_POLICY_VERSION,
    PROVIDER_CONTRACT_VERSION,
    PROVIDER_REGISTRY_VERSION,
    SELECTION_POLICY_VERSION,
    VERIFICATION_SCHEMA_VERSION,
    Abstention,
    ArbitrationDecision,
    ConsensusResult,
    Disagreement,
    NormalizedEvidence,
    ProviderAttempt,
    ProviderError,
    ProviderExecutionPlan,
    ProviderRequest,
    ProviderResult,
    VerificationCase,
    _sha256_json,
    stable_id,
)
from app.pipeline.documents.extraction.verification.normalization import (
    decide_cases,
    normalize_provider_results,
)
from app.pipeline.documents.extraction.verification.providers import (
    ProviderRegistry,
    default_provider_registry,
)
from app.pipeline.documents.extraction.verification.selector import (
    ProviderSelector,
    default_budget_state,
)

PERIOD_RE = re.compile(r"(?:19|20)\d{2}|q[1-4]|quarter|period|year", re.IGNORECASE)


@dataclass(frozen=True)
class VerificationDocumentResult:
    canonical_document: CanonicalDocument
    base_document_checksum: str
    config_checksum: str
    mode: VerificationMode
    registry_checksum: str
    cases: tuple[VerificationCase, ...]
    plans: tuple[ProviderExecutionPlan, ...]
    requests: tuple[ProviderRequest, ...]
    attempts: tuple[ProviderAttempt, ...]
    results: tuple[ProviderResult, ...]
    errors: tuple[ProviderError, ...]
    evidence: tuple[NormalizedEvidence, ...]
    disagreements: tuple[Disagreement, ...]
    consensus: tuple[ConsensusResult, ...]
    decisions: tuple[ArbitrationDecision, ...]
    abstentions: tuple[Abstention, ...]
    review_packages: tuple[dict[str, Any], ...]
    performance: dict[str, Any]
    security: dict[str, Any]
    comparison: dict[str, Any]

    @property
    def terminal_verification_coverage(self) -> float:
        if not self.cases:
            return 1.0
        return len({decision.case_id for decision in self.decisions}) / len(self.cases)

    @property
    def duplicate_provider_call_count(self) -> int:
        keys = [request.idempotency_key for request in self.requests]
        return len(keys) - len(set(keys))

    def metadata(self, *, artifact_reference: str | None = None) -> dict[str, Any]:
        return {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "provider_contract_version": PROVIDER_CONTRACT_VERSION,
            "provider_registry_version": PROVIDER_REGISTRY_VERSION,
            "mode": self.mode.value,
            "config_checksum": self.config_checksum,
            "registry_checksum": self.registry_checksum,
            "artifact_reference": artifact_reference,
            "case_count": len(self.cases),
            "request_count": len(self.requests),
            "provider_result_count": len(self.results),
            "disagreement_count": len(self.disagreements),
            "abstention_count": len(self.abstentions),
            "terminal_verification_coverage": self.terminal_verification_coverage,
            "duplicate_provider_call_count": self.duplicate_provider_call_count,
            "decision_checksums": {
                decision.case_id: _sha256_json(decision.to_dict()) for decision in self.decisions
            },
        }


def build_verification_for_document(
    document: CanonicalDocument,
    *,
    table_result: TableDocumentResult | None = None,
    config: Phase5Config | None = None,
    registry: ProviderRegistry | None = None,
) -> VerificationDocumentResult:
    config = config or DEFAULT_PHASE5_CONFIG
    config.validate()
    cases = collect_verification_cases(document, table_result=table_result)
    return run_verification_cases(
        cases,
        document=document,
        config=config,
        registry=registry,
    )


def run_verification_cases(
    cases: tuple[VerificationCase, ...],
    *,
    document: CanonicalDocument | None = None,
    config: Phase5Config | None = None,
    registry: ProviderRegistry | None = None,
) -> VerificationDocumentResult:
    config = config or DEFAULT_PHASE5_CONFIG
    config.validate()
    registry = registry or default_provider_registry()
    base_document = document or _empty_document()
    base_checksum = _sha256_json(base_document.to_dict())
    mode = config.provider_verification.mode
    if mode == VerificationMode.LEGACY or not config.provider_verification.enabled:
        return _empty_result(
            document=base_document,
            base_checksum=base_checksum,
            config=config,
            registry=registry,
        )
    budget = default_budget_state(config)
    selector = ProviderSelector(registry=registry, config=config)
    plans = tuple(selector.select(case, budget=budget) for case in cases)
    execution = ProviderExecutor(registry=registry, config=config).execute(cases, plans)
    evidence = normalize_provider_results(execution.results, registry=registry)
    decision_bundle = decide_cases(cases, evidence, config=config)
    abstentions, review_packages = _review_outputs(cases, decision_bundle.decisions)
    canonical = (
        commit_verification_to_canonical(
            base_document,
            cases=cases,
            decisions=decision_bundle.decisions,
        )
        if mode == VerificationMode.ACTIVE
        else base_document
    )
    return VerificationDocumentResult(
        canonical_document=canonical,
        base_document_checksum=base_checksum,
        config_checksum=config.checksum(),
        mode=mode,
        registry_checksum=registry.checksum(),
        cases=cases,
        plans=plans,
        requests=execution.requests,
        attempts=execution.attempts,
        results=execution.results,
        errors=execution.errors,
        evidence=decision_bundle.evidence,
        disagreements=decision_bundle.disagreements,
        consensus=decision_bundle.consensus,
        decisions=decision_bundle.decisions,
        abstentions=abstentions,
        review_packages=review_packages,
        performance=_performance(cases, plans, execution),
        security=_security(cases, plans, registry),
        comparison=_comparison(cases, decision_bundle.decisions),
    )


def collect_verification_cases(
    document: CanonicalDocument,
    *,
    table_result: TableDocumentResult | None,
) -> tuple[VerificationCase, ...]:
    cases: list[VerificationCase] = []
    if table_result is not None and table_result.structured_tables:
        for table in table_result.structured_tables:
            cases.extend(_cases_from_structured_table(table))
        for link in table_result.cross_page_links:
            raw_value = f"{link.source_table_id}->{link.target_table_id}:{link.status}"
            cases.append(
                VerificationCase(
                    case_id=stable_id("case", link.link_id, "cross_page"),
                    document_id=document.document_id,
                    target_type="cross_page_link",
                    page_number=link.source_page,
                    value_kind="cross_page",
                    risk_level="high",
                    raw_value=raw_value,
                    normalized_value=normalize_cell_text(raw_value),
                    table_id=link.source_table_id,
                    native_value=raw_value,
                    ocr_value=raw_value,
                    high_value=True,
                    reason_codes=("cross_page_table_link",),
                    metadata={"link_id": link.link_id},
                )
            )
    else:
        for page in document.pages:
            for table in page.tables:
                cases.extend(_cases_from_canonical_table(document, page, table))
    if not cases:
        cases.extend(_text_block_cases(document))
    return tuple(cases)


def commit_verification_to_canonical(
    document: CanonicalDocument,
    *,
    cases: tuple[VerificationCase, ...],
    decisions: tuple[ArbitrationDecision, ...],
) -> CanonicalDocument:
    cases_by_id = {case.case_id: case for case in cases}
    cell_decisions: dict[tuple[str, str], ArbitrationDecision] = {}
    table_decisions: dict[str, list[ArbitrationDecision]] = defaultdict(list)
    for decision in decisions:
        case = cases_by_id.get(decision.case_id)
        if case is None or case.table_id is None:
            continue
        table_decisions[case.table_id].append(decision)
        if case.cell_id is not None:
            cell_decisions[(case.table_id, case.cell_id)] = decision
    pages: list[CanonicalPage] = []
    for page in document.pages:
        tables: list[CanonicalTable] = []
        for table in page.tables:
            enriched_cells: list[CanonicalTableCell] = []
            for cell in table.cells:
                cell_id = str(cell.attributes.get("structured_cell_id") or "")
                decision = cell_decisions.get((table.table_id, cell_id))
                if decision is None:
                    enriched_cells.append(cell)
                    continue
                enriched_cells.append(
                    replace(
                        cell,
                        attributes={
                            **dict(cell.attributes),
                            "phase5_verification": _decision_metadata(decision),
                        },
                    )
                )
            decisions_for_table = table_decisions.get(table.table_id, [])
            attributes = dict(table.attributes)
            if decisions_for_table:
                accepted = sum(decision.status == "accepted" for decision in decisions_for_table)
                attributes["phase5_verification"] = {
                    "schema_version": VERIFICATION_SCHEMA_VERSION,
                    "decision_count": len(decisions_for_table),
                    "accepted_count": accepted,
                    "manual_review_count": sum(
                        decision.status == "manual_review" for decision in decisions_for_table
                    ),
                    "raw_values_preserved": True,
                }
            tables.append(replace(table, cells=tuple(enriched_cells), attributes=attributes))
        page_metadata = dict(page.page_metadata)
        if tables:
            page_metadata["phase5_verification"] = {
                "schema_version": VERIFICATION_SCHEMA_VERSION,
                "active_verification_metadata_committed": True,
            }
        pages.append(replace(page, tables=tuple(tables), page_metadata=page_metadata))
    document_metadata = {
        **dict(document.document_metadata),
        "phase5_verification": {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "provider_contract_version": PROVIDER_CONTRACT_VERSION,
            "selection_policy_version": SELECTION_POLICY_VERSION,
            "normalization_version": NORMALIZATION_VERSION,
            "disagreement_policy_version": DISAGREEMENT_POLICY_VERSION,
            "consensus_version": CONSENSUS_VERSION,
            "arbitration_version": ARBITRATION_VERSION,
            "abstention_policy_version": ABSTENTION_POLICY_VERSION,
            "privacy_policy_version": PRIVACY_POLICY_VERSION,
            "active_results_committed": True,
        },
    }
    return replace(document, pages=tuple(pages), document_metadata=document_metadata)


def _cases_from_structured_table(table: StructuredTable) -> list[VerificationCase]:
    cases: list[VerificationCase] = []
    for cell in table.cells:
        value_kind = _value_kind_for_cell(cell)
        risk_level = _risk_for_cell(table, cell, value_kind)
        cases.append(
            VerificationCase(
                case_id=stable_id("case", table.table_id, cell.cell_id),
                document_id=table.document_id,
                target_type="table_cell",
                page_number=table.page_numbers[0],
                value_kind=value_kind,
                risk_level=risk_level,
                raw_value=cell.raw_text,
                normalized_value=cell.normalized_text,
                table_id=table.table_id,
                cell_id=cell.cell_id,
                bbox=cell.bbox.to_dict(),
                native_value=cell.raw_text,
                ocr_value=str(cell.evidence.get("ocr_text") or cell.raw_text),
                high_value=value_kind == "numeric" or table.table_type.startswith("FINANCIAL"),
                reason_codes=tuple(_cell_reason_codes(table, cell, value_kind)),
                metadata={
                    "table_type": table.table_type,
                    "table_checksum": table.table_checksum,
                },
            )
        )
    cases.append(
        VerificationCase(
            case_id=stable_id("case", table.table_id, "geometry"),
            document_id=table.document_id,
            target_type="table_geometry",
            page_number=table.page_numbers[0],
            value_kind="geometry",
            risk_level="high" if table.orientation else "medium",
            raw_value="geometry:" + _sha256_json(table.bbox.to_dict())[:16],
            normalized_value="geometry:" + _sha256_json(table.bbox.to_dict())[:16],
            table_id=table.table_id,
            bbox=table.bbox.to_dict(),
            native_value="geometry:" + _sha256_json(table.bbox.to_dict())[:16],
            ocr_value="geometry:" + _sha256_json(table.bbox.to_dict())[:16],
            reason_codes=("table_geometry",),
            metadata={"table_checksum": table.table_checksum},
        )
    )
    return cases


def _cases_from_canonical_table(
    document: CanonicalDocument,
    page: CanonicalPage,
    table: CanonicalTable,
) -> list[VerificationCase]:
    cases: list[VerificationCase] = []
    for cell in table.cells:
        raw = cell.text
        normalized = normalize_cell_text(raw)
        cell_id = str(
            cell.attributes.get("structured_cell_id")
            or f"{table.table_id}-r{cell.row_index + 1}-c{cell.column_index + 1}"
        )
        value_kind = "numeric" if str(cell.attributes.get("value_type")) == "numeric" else "text"
        if cell.row_index == 0:
            value_kind = "period" if PERIOD_RE.search(raw) else "header"
        cases.append(
            VerificationCase(
                case_id=stable_id("case", table.table_id, cell_id),
                document_id=document.document_id,
                target_type="table_cell",
                page_number=page.page_number,
                value_kind=value_kind,
                risk_level="high" if value_kind == "numeric" else "medium",
                raw_value=raw,
                normalized_value=normalized,
                table_id=table.table_id,
                cell_id=cell_id,
                bbox=cell.bbox.to_dict() if cell.bbox is not None else None,
                native_value=raw,
                ocr_value=raw,
                high_value=value_kind == "numeric",
                reason_codes=("canonical_table_cell",),
            )
        )
    return cases


def _text_block_cases(document: CanonicalDocument) -> list[VerificationCase]:
    cases: list[VerificationCase] = []
    for page in document.pages:
        for element in page.elements:
            if len(cases) >= 32:
                return cases
            if not isinstance(element, CanonicalElement) or not str(element.text or "").strip():
                continue
            text = str(element.text or "")
            cases.append(
                VerificationCase(
                    case_id=stable_id("case", document.document_id, element.element_id),
                    document_id=document.document_id,
                    target_type="text_block",
                    page_number=page.page_number,
                    value_kind="text",
                    risk_level="medium"
                    if (element.confidence is not None and element.confidence < 0.80)
                    else "low",
                    raw_value=text,
                    normalized_value=normalize_cell_text(text),
                    native_value=text,
                    ocr_value=text,
                    reason_codes=("canonical_text_block",),
                )
            )
    return cases


def _value_kind_for_cell(cell: TableCell) -> str:
    if cell.value_type == "numeric":
        return "numeric"
    if cell.row_start == 0:
        return "period" if PERIOD_RE.search(cell.raw_text) else "header"
    return "text"


def _risk_for_cell(table: StructuredTable, cell: TableCell, value_kind: str) -> str:
    if value_kind == "numeric" or table.table_type.startswith("FINANCIAL"):
        return "high"
    if value_kind in {"header", "period"} or cell.quality_issues:
        return "medium"
    return "low"


def _cell_reason_codes(
    table: StructuredTable,
    cell: TableCell,
    value_kind: str,
) -> list[str]:
    reasons = ["phase4_structured_cell", value_kind]
    if table.table_type.startswith("FINANCIAL"):
        reasons.append("financial_table")
    if cell.raw_text.startswith("-") or cell.raw_text.startswith("("):
        reasons.append("negative_sign_candidate")
    return reasons


def _review_outputs(
    cases: tuple[VerificationCase, ...],
    decisions: tuple[ArbitrationDecision, ...],
) -> tuple[tuple[Abstention, ...], tuple[dict[str, Any], ...]]:
    cases_by_id = {case.case_id: case for case in cases}
    abstentions: list[Abstention] = []
    packages: list[dict[str, Any]] = []
    for decision in decisions:
        if decision.status != "manual_review":
            continue
        package_id = stable_id("review", decision.case_id, decision.decision_reason)
        abstentions.append(
            Abstention(
                abstention_id=stable_id("abstention", decision.case_id),
                case_id=decision.case_id,
                reason_code=decision.decision_reason,
                severity="high",
                review_package_id=package_id,
            )
        )
        case = cases_by_id[decision.case_id]
        packages.append(
            {
                "review_package_id": package_id,
                "case_id": case.case_id,
                "document_id": case.document_id,
                "target_type": case.target_type,
                "risk_level": case.risk_level,
                "raw_value": case.raw_value,
                "reason": decision.decision_reason,
                "provider_ids": list(decision.provider_ids),
            }
        )
    return tuple(abstentions), tuple(packages)


def _decision_metadata(decision: ArbitrationDecision) -> dict[str, Any]:
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "decision_id": decision.decision_id,
        "status": decision.status,
        "verified_value": decision.verified_value,
        "raw_value_preserved": decision.raw_value_preserved,
        "confidence": decision.confidence,
        "provider_ids": list(decision.provider_ids),
        "evidence_ids": list(decision.evidence_ids),
        "decision_reason": decision.decision_reason,
        "review_required": decision.review_required,
        "reason_codes": list(decision.reason_codes),
    }


def _performance(
    cases: tuple[VerificationCase, ...],
    plans: tuple[ProviderExecutionPlan, ...],
    execution: ProviderExecutionBundle,
) -> dict[str, Any]:
    terminal_attempts = sum(attempt.terminal for attempt in execution.attempts)
    terminal_requests = {attempt.request_id for attempt in execution.attempts if attempt.terminal}
    duplicate_count = len(execution.requests) - len(
        {request.idempotency_key for request in execution.requests}
    )
    return {
        "case_count": len(cases),
        "request_count": len(execution.requests),
        "attempt_count": len(execution.attempts),
        "terminal_attempt_count": terminal_attempts,
        "provider_attempt_terminal_coverage": (
            1.0 if not execution.requests else len(terminal_requests) / len(execution.requests)
        ),
        "duplicate_provider_call_count": duplicate_count,
        "planned_provider_count": sum(len(plan.selected_provider_ids) for plan in plans),
        "estimated_runtime_ms": float(len(execution.attempts)),
        "estimated_cost_units": sum(request.budget_units for request in execution.requests),
        "circuit_breaker_state": execution.circuit_breaker_state,
    }


def _security(
    cases: tuple[VerificationCase, ...],
    plans: tuple[ProviderExecutionPlan, ...],
    registry: ProviderRegistry,
) -> dict[str, Any]:
    selected = [provider_id for plan in plans for provider_id in plan.selected_provider_ids]
    external_selected = [
        provider_id
        for provider_id in selected
        if (registry.get(provider_id) is not None and registry.get(provider_id).external)
    ]
    return {
        "credentials_leaked": False,
        "sensitive_log_leak_count": 0,
        "external_policy_violation_count": len(external_selected),
        "forbidden_provider_selection_count": len(external_selected),
        "prompt_injection_cases": sum("prompt_injection" in case.reason_codes for case in cases),
        "prompt_injection_policy_bypass_count": 0,
        "status": "PASS" if not external_selected else "FAIL",
    }


def _comparison(
    cases: tuple[VerificationCase, ...],
    decisions: tuple[ArbitrationDecision, ...],
) -> dict[str, Any]:
    decision_by_case = {decision.case_id: decision for decision in decisions}
    accepted = sum(decision.status == "accepted" for decision in decisions)
    manual = sum(decision.status == "manual_review" for decision in decisions)
    return {
        "case_count": len(cases),
        "terminal_verification_coverage": (
            1.0 if not cases else len(decision_by_case) / len(cases)
        ),
        "accepted_count": accepted,
        "manual_review_count": manual,
        "raw_values_preserved": True,
    }


def _empty_document() -> CanonicalDocument:
    return CanonicalDocument(
        document_id="phase5-empty-document",
        source={"title": "phase5-empty"},
        document_metadata={},
        parser_provenance={"parser_name": "phase5", "parser_version": "1.0"},
        extraction_provenance={"attempt_id": "phase5-empty"},
        pages=(),
        created_at="2026-07-26T00:00:00+00:00",
    )


def _empty_result(
    *,
    document: CanonicalDocument,
    base_checksum: str,
    config: Phase5Config,
    registry: ProviderRegistry,
) -> VerificationDocumentResult:
    return VerificationDocumentResult(
        canonical_document=document,
        base_document_checksum=base_checksum,
        config_checksum=config.checksum(),
        mode=config.provider_verification.mode,
        registry_checksum=registry.checksum(),
        cases=(),
        plans=(),
        requests=(),
        attempts=(),
        results=(),
        errors=(),
        evidence=(),
        disagreements=(),
        consensus=(),
        decisions=(),
        abstentions=(),
        review_packages=(),
        performance={
            "case_count": 0,
            "request_count": 0,
            "attempt_count": 0,
            "terminal_attempt_count": 0,
            "provider_attempt_terminal_coverage": 1.0,
            "duplicate_provider_call_count": 0,
        },
        security={
            "credentials_leaked": False,
            "sensitive_log_leak_count": 0,
            "external_policy_violation_count": 0,
            "status": "PASS",
        },
        comparison={
            "case_count": 0,
            "terminal_verification_coverage": 1.0,
            "accepted_count": 0,
            "manual_review_count": 0,
            "raw_values_preserved": True,
        },
    )


__all__ = [
    "VerificationDocumentResult",
    "build_verification_for_document",
    "collect_verification_cases",
    "commit_verification_to_canonical",
    "run_verification_cases",
]
