from __future__ import annotations

from dataclasses import dataclass, field

from app.pipeline.documents.extraction.verification.config import Phase5Config
from app.pipeline.documents.extraction.verification.models import (
    ProviderDescriptor,
    ProviderExecutionPlan,
    VerificationCase,
    stable_id,
)
from app.pipeline.documents.extraction.verification.providers import ProviderRegistry


@dataclass
class ProviderBudgetState:
    max_calls_per_document: int
    max_budget_units_per_document: int
    max_calls_per_page: int
    calls_used: int = 0
    budget_units_used: int = 0
    calls_by_page: dict[int, int] = field(default_factory=dict)

    def can_spend(self, *, page_number: int, call_count: int, budget_units: int) -> bool:
        page_calls = self.calls_by_page.get(page_number, 0)
        return (
            self.calls_used + call_count <= self.max_calls_per_document
            and self.budget_units_used + budget_units <= self.max_budget_units_per_document
            and page_calls + call_count <= self.max_calls_per_page
        )

    def spend(self, *, page_number: int, call_count: int, budget_units: int) -> None:
        self.calls_used += call_count
        self.budget_units_used += budget_units
        self.calls_by_page[page_number] = self.calls_by_page.get(page_number, 0) + call_count


@dataclass(frozen=True)
class ProviderSelector:
    registry: ProviderRegistry
    config: Phase5Config

    def select(
        self,
        case: VerificationCase,
        *,
        budget: ProviderBudgetState,
    ) -> ProviderExecutionPlan:
        verification = self.config.provider_verification
        rejected: list[str] = []
        reason_codes: list[str] = []
        candidates = []
        for provider in self.registry.enabled():
            if provider.provider_id not in verification.enabled_provider_ids:
                rejected.append(provider.provider_id)
                reason_codes.append(f"provider_disabled:{provider.provider_id}")
                continue
            if provider.provider_id in verification.forbidden_provider_ids:
                rejected.append(provider.provider_id)
                reason_codes.append(f"provider_forbidden:{provider.provider_id}")
                continue
            if provider.external and not verification.allow_external_providers:
                rejected.append(provider.provider_id)
                reason_codes.append(f"external_forbidden:{provider.provider_id}")
                continue
            if case.value_kind not in provider.capabilities.value_kinds:
                rejected.append(provider.provider_id)
                reason_codes.append(f"capability_mismatch:{provider.provider_id}")
                continue
            candidates.append(provider)

        selected = _ranked_candidates(case, candidates)
        required_count = _required_count(case, verification)
        selected = selected[:required_count]
        selected = _dedupe_correlated(selected)
        if len(selected) > verification.max_providers_per_case:
            selected = selected[: verification.max_providers_per_case]
        budget_units = sum(
            provider.cost.fixed_cost_units + provider.cost.per_case_cost_units
            for provider in selected
        )
        if not budget.can_spend(
            page_number=case.page_number,
            call_count=len(selected),
            budget_units=budget_units,
        ):
            rejected.extend(provider.provider_id for provider in selected)
            reason_codes.append("budget_exceeded")
            selected = []
            budget_units = 0
        budget.spend(
            page_number=case.page_number,
            call_count=len(selected),
            budget_units=budget_units,
        )
        if len(selected) < required_count:
            reason_codes.append("insufficient_independent_providers")
        if not selected:
            reason_codes.append("terminal_without_provider")
        return ProviderExecutionPlan(
            plan_id=stable_id(
                "plan",
                case.case_id,
                ",".join(provider.provider_id for provider in selected),
                ",".join(sorted(set(rejected))),
            ),
            case_id=case.case_id,
            selected_provider_ids=tuple(provider.provider_id for provider in selected),
            rejected_provider_ids=tuple(sorted(set(rejected))),
            reason_codes=tuple(sorted(set(reason_codes))),
            budget_units=budget_units,
            terminal_without_provider=not selected,
        )


def default_budget_state(config: Phase5Config) -> ProviderBudgetState:
    verification = config.provider_verification
    return ProviderBudgetState(
        max_calls_per_document=verification.max_provider_calls_per_document,
        max_budget_units_per_document=verification.max_budget_units_per_document,
        max_calls_per_page=verification.max_provider_calls_per_page,
    )


def _required_count(case: VerificationCase, verification: object) -> int:
    if case.risk_level == "high" or case.high_value:
        return int(verification.high_risk_provider_count)
    if case.risk_level == "medium":
        return int(verification.medium_risk_provider_count)
    return int(verification.low_risk_provider_count)


def _ranked_candidates(
    case: VerificationCase,
    candidates: list[ProviderDescriptor],
) -> list[ProviderDescriptor]:
    preferred = {
        "numeric": ("native_phase4", "local_numeric_rules", "local_ocr_evidence"),
        "period": ("native_phase4", "local_numeric_rules", "local_ocr_evidence"),
        "header": ("native_phase4", "local_ocr_evidence", "local_geometry_rules"),
        "text": ("native_phase4", "local_ocr_evidence", "local_geometry_rules"),
        "geometry": ("native_phase4", "local_geometry_rules"),
        "cross_page": ("native_phase4", "local_geometry_rules"),
    }
    order = preferred.get(case.value_kind, ("native_phase4",))
    order_index = {provider_id: index for index, provider_id in enumerate(order)}
    return sorted(
        candidates,
        key=lambda provider: (
            order_index.get(provider.provider_id, 99),
            -provider.reliability_weight,
            provider.provider_id,
        ),
    )


def _dedupe_correlated(
    providers: list[ProviderDescriptor],
) -> list[ProviderDescriptor]:
    selected: list[ProviderDescriptor] = []
    correlated_groups: set[str] = set()
    for provider in providers:
        group = provider.correlated_group or provider.provider_id
        if group in correlated_groups:
            continue
        selected.append(provider)
        correlated_groups.add(group)
    return selected


__all__ = [
    "ProviderBudgetState",
    "ProviderSelector",
    "default_budget_state",
]
