from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.pipeline.documents.extraction.verification.config import Phase5Config
from app.pipeline.documents.extraction.verification.models import (
    ProviderAttempt,
    ProviderError,
    ProviderExecutionPlan,
    ProviderRequest,
    ProviderResult,
    VerificationCase,
    stable_id,
)
from app.pipeline.documents.extraction.verification.providers import (
    ProviderExecutionError,
    ProviderRegistry,
)

DETERMINISTIC_ARTIFACT_TIME = "2026-07-26T00:00:00Z"


@dataclass(frozen=True)
class ProviderExecutionBundle:
    requests: tuple[ProviderRequest, ...]
    attempts: tuple[ProviderAttempt, ...]
    results: tuple[ProviderResult, ...]
    errors: tuple[ProviderError, ...]
    circuit_breaker_state: dict[str, Any]


@dataclass
class ProviderExecutor:
    registry: ProviderRegistry
    config: Phase5Config

    def execute(
        self,
        cases: tuple[VerificationCase, ...],
        plans: tuple[ProviderExecutionPlan, ...],
    ) -> ProviderExecutionBundle:
        verification = self.config.provider_verification
        cases_by_id = {case.case_id: case for case in cases}
        requests: list[ProviderRequest] = []
        attempts: list[ProviderAttempt] = []
        results: list[ProviderResult] = []
        errors: list[ProviderError] = []
        failure_counts: dict[str, int] = {}
        opened_circuits: set[str] = set()
        seen_request_keys: set[str] = set()
        for plan in plans:
            case = cases_by_id[plan.case_id]
            for provider_id in plan.selected_provider_ids:
                descriptor = self.registry.get(provider_id)
                if descriptor is None:
                    continue
                request = ProviderRequest(
                    request_id=stable_id("request", case.case_id, provider_id),
                    case_id=case.case_id,
                    provider_id=provider_id,
                    idempotency_key=stable_id(
                        "idempotency",
                        case.case_id,
                        provider_id,
                        verification.selection_policy_version,
                    ),
                    status="executed",
                    payload={
                        "case_checksum": case.checksum(),
                        "target_type": case.target_type,
                        "value_kind": case.value_kind,
                        "risk_level": case.risk_level,
                        "raw_value": case.raw_value,
                        "normalized_value": case.normalized_value,
                    },
                    timeout_ms=min(
                        verification.provider_timeout_ms,
                        descriptor.cost.timeout_ms,
                    ),
                    budget_units=(
                        descriptor.cost.fixed_cost_units + descriptor.cost.per_case_cost_units
                    ),
                    created_at=DETERMINISTIC_ARTIFACT_TIME,
                )
                if request.idempotency_key in seen_request_keys:
                    continue
                seen_request_keys.add(request.idempotency_key)
                requests.append(request)
                if provider_id in opened_circuits:
                    attempts.append(
                        ProviderAttempt(
                            attempt_id=stable_id("attempt", request.request_id, 1),
                            request_id=request.request_id,
                            case_id=case.case_id,
                            provider_id=provider_id,
                            attempt_index=1,
                            status="skipped",
                            terminal=True,
                            latency_ms=0.0,
                            retryable=False,
                            error_code="circuit_open",
                            reason="provider circuit breaker open",
                        )
                    )
                    errors.append(
                        ProviderError(
                            error_id=stable_id("error", request.request_id, "circuit_open"),
                            request_id=request.request_id,
                            case_id=case.case_id,
                            provider_id=provider_id,
                            error_code="circuit_open",
                            retryable=False,
                            terminal=True,
                            message="provider circuit breaker open",
                        )
                    )
                    continue
                adapter = self.registry.adapter(provider_id)
                for attempt_index in range(1, verification.max_provider_attempts + 1):
                    try:
                        result = adapter.execute(request, case)
                    except ProviderExecutionError as exc:
                        terminal = (
                            not exc.retryable or attempt_index >= verification.max_provider_attempts
                        )
                        status = "timeout" if "timeout" in exc.error_code else "failed"
                        attempts.append(
                            ProviderAttempt(
                                attempt_id=stable_id(
                                    "attempt",
                                    request.request_id,
                                    attempt_index,
                                ),
                                request_id=request.request_id,
                                case_id=case.case_id,
                                provider_id=provider_id,
                                attempt_index=attempt_index,
                                status=status,
                                terminal=terminal,
                                latency_ms=float(
                                    request.timeout_ms if status == "timeout" else 1.0
                                ),
                                retryable=exc.retryable and not terminal,
                                error_code=exc.error_code,
                                reason=str(exc),
                            )
                        )
                        if terminal:
                            failure_counts[provider_id] = failure_counts.get(provider_id, 0) + 1
                            errors.append(
                                ProviderError(
                                    error_id=stable_id(
                                        "error",
                                        request.request_id,
                                        exc.error_code,
                                    ),
                                    request_id=request.request_id,
                                    case_id=case.case_id,
                                    provider_id=provider_id,
                                    error_code=exc.error_code,
                                    retryable=exc.retryable,
                                    terminal=True,
                                    message=str(exc),
                                )
                            )
                            if (
                                failure_counts[provider_id]
                                >= verification.circuit_breaker_failure_threshold
                            ):
                                opened_circuits.add(provider_id)
                        if terminal:
                            break
                        continue
                    attempts.append(
                        ProviderAttempt(
                            attempt_id=stable_id(
                                "attempt",
                                request.request_id,
                                attempt_index,
                            ),
                            request_id=request.request_id,
                            case_id=case.case_id,
                            provider_id=provider_id,
                            attempt_index=attempt_index,
                            status="succeeded",
                            terminal=True,
                            latency_ms=1.0,
                            retryable=False,
                        )
                    )
                    results.append(result)
                    break
        return ProviderExecutionBundle(
            requests=tuple(requests),
            attempts=tuple(attempts),
            results=tuple(results),
            errors=tuple(errors),
            circuit_breaker_state={
                "opened": sorted(opened_circuits),
                "failure_counts": dict(sorted(failure_counts.items())),
            },
        )


__all__ = [
    "DETERMINISTIC_ARTIFACT_TIME",
    "ProviderExecutionBundle",
    "ProviderExecutor",
]
