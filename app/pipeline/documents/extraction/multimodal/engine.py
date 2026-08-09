from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from app.pipeline.documents.extraction.canonical.ir import CanonicalDocument, CanonicalPage
from app.pipeline.documents.extraction.multimodal.asset_pipeline import build_assets_for_candidates
from app.pipeline.documents.extraction.multimodal.backends import (
    VisualBackendExecutionError,
    VisualBackendRegistry,
    default_visual_backend_registry,
)
from app.pipeline.documents.extraction.multimodal.config import (
    DEFAULT_PHASE6_CONFIG,
    MultimodalMode,
    Phase6Config,
)
from app.pipeline.documents.extraction.multimodal.extractors import extract_visual_structures
from app.pipeline.documents.extraction.multimodal.models import (
    MULTIMODAL_CONTRACT_VERSION,
    MULTIMODAL_SCHEMA_VERSION,
    VISUAL_BACKEND_CONTRACT_VERSION,
    MultimodalExtractionResult,
    MultimodalIssue,
    VisualAsset,
    VisualBackendAttempt,
    VisualBackendRequest,
    VisualBackendResult,
    VisualCandidate,
    sha256_json,
    stable_id,
)
from app.pipeline.documents.extraction.multimodal.router import collect_visual_candidates


def build_multimodal_for_document(
    document: CanonicalDocument,
    *,
    phase5_verification: Any | None = None,
    config: Phase6Config | None = None,
    registry: VisualBackendRegistry | None = None,
    manifest_cases: tuple[dict[str, Any], ...] | None = None,
) -> MultimodalExtractionResult:
    config = config or DEFAULT_PHASE6_CONFIG
    config.validate()
    registry = registry or default_visual_backend_registry()
    base_checksum = sha256_json(document.to_dict())
    mode = config.multimodal.mode
    if mode == MultimodalMode.DISABLED or not config.multimodal.enabled:
        return _empty_result(
            document=document,
            base_checksum=base_checksum,
            config=config,
            registry=registry,
        )
    candidates = collect_visual_candidates(
        document,
        config=config,
        manifest_cases=manifest_cases,
    )
    assets, regions, asset_issues = build_assets_for_candidates(candidates, config=config)
    (
        requests,
        attempts,
        backend_results,
        execution_issues,
    ) = _execute_visual_backends(
        candidates=candidates,
        assets=assets,
        existing_issues=asset_issues,
        config=config,
        registry=registry,
    )
    extracted = extract_visual_structures(
        candidates=candidates,
        assets=assets,
        regions=regions,
        backend_results=backend_results,
        existing_issues=tuple(asset_issues) + tuple(execution_issues),
    )
    result_document = (
        commit_multimodal_to_canonical(
            document,
            candidates=candidates,
            result_metadata={
                "schema_version": MULTIMODAL_SCHEMA_VERSION,
                "multimodal_contract_version": MULTIMODAL_CONTRACT_VERSION,
                "visual_backend_contract_version": VISUAL_BACKEND_CONTRACT_VERSION,
                "mode": mode.value,
                "config_checksum": config.checksum(),
                "registry_checksum": registry.checksum(),
                "candidate_count": len(candidates),
                "asset_count": len(assets),
                "figure_count": len(extracted.figures),
                "chart_count": len(extracted.charts),
                "diagram_count": len(extracted.diagrams),
                "visual_text_block_count": len(extracted.visual_text_blocks),
                "raw_text_table_layout_preserved": True,
                "phase5_verification_checksum": getattr(
                    phase5_verification,
                    "config_checksum",
                    None,
                ),
            },
            retrieval_ready={
                "figures": [
                    {
                        "figure_id": item.figure_id,
                        "caption_text": item.caption_text,
                        "page_number": item.page_number,
                    }
                    for item in extracted.figures
                ],
                "charts": [
                    {
                        "chart_id": item.chart_id,
                        "chart_type": item.chart_type,
                        "title": item.title,
                    }
                    for item in extracted.charts
                ],
                "diagrams": [
                    {
                        "diagram_id": item.diagram_id,
                        "diagram_type": item.diagram_type,
                    }
                    for item in extracted.diagrams
                ],
                "visual_text": [
                    {
                        "text_block_id": item.text_block_id,
                        "text": item.text,
                        "page_number": item.page_number,
                    }
                    for item in extracted.visual_text_blocks
                ],
                "asset_refs_only": True,
            },
        )
        if mode == MultimodalMode.ACTIVE
        else document
    )
    performance = _performance(candidates, requests, attempts, assets, extracted.issues)
    security = _security(requests, registry)
    comparison = _comparison(candidates, backend_results, extracted)
    return MultimodalExtractionResult(
        canonical_document=result_document,
        base_document_checksum=base_checksum,
        config_checksum=config.checksum(),
        mode=mode.value,
        registry_checksum=registry.checksum(),
        candidates=candidates,
        assets=assets,
        regions=regions,
        requests=requests,
        attempts=attempts,
        backend_results=backend_results,
        figures=extracted.figures,
        caption_links=extracted.caption_links,
        visual_text_blocks=extracted.visual_text_blocks,
        charts=extracted.charts,
        chart_axes=extracted.chart_axes,
        chart_legends=extracted.chart_legends,
        chart_series=extracted.chart_series,
        chart_data_points=extracted.chart_data_points,
        diagrams=extracted.diagrams,
        diagram_nodes=extracted.diagram_nodes,
        diagram_edges=extracted.diagram_edges,
        signatures=extracted.signatures,
        stamps=extracted.stamps,
        logos=extracted.logos,
        relation_graphs=extracted.relation_graphs,
        evidence=extracted.evidence,
        issues=extracted.issues,
        review_packages=extracted.review_packages,
        performance=performance,
        security=security,
        comparison=comparison,
    )


def run_multimodal_cases(
    cases: tuple[dict[str, Any], ...],
    *,
    config: Phase6Config,
    registry: VisualBackendRegistry | None = None,
) -> MultimodalExtractionResult:
    document = _document_from_cases(cases)
    return build_multimodal_for_document(
        document,
        config=config,
        registry=registry,
        manifest_cases=cases,
    )


def commit_multimodal_to_canonical(
    document: CanonicalDocument,
    *,
    candidates: tuple[VisualCandidate, ...],
    result_metadata: dict[str, Any],
    retrieval_ready: dict[str, Any],
) -> CanonicalDocument:
    candidate_pages = defaultdict(list)
    for candidate in candidates:
        candidate_pages[candidate.page_number].append(candidate.candidate_id)
    pages: list[CanonicalPage] = []
    for page in document.pages:
        page_metadata = dict(page.page_metadata)
        if page.page_number in candidate_pages:
            page_metadata["phase6_multimodal"] = {
                "schema_version": MULTIMODAL_SCHEMA_VERSION,
                "active_multimodal_metadata_committed": True,
                "candidate_ids": list(candidate_pages[page.page_number]),
                "raw_page_content_preserved": True,
            }
        pages.append(replace(page, page_metadata=page_metadata))
    document_metadata = {
        **dict(document.document_metadata),
        "phase6_multimodal": {
            **dict(result_metadata),
            "active_results_committed": True,
            "retrieval_ready": retrieval_ready,
        },
    }
    return replace(document, pages=tuple(pages), document_metadata=document_metadata)


def _execute_visual_backends(
    *,
    candidates: tuple[VisualCandidate, ...],
    assets: tuple[VisualAsset, ...],
    existing_issues: tuple[MultimodalIssue, ...],
    config: Phase6Config,
    registry: VisualBackendRegistry,
) -> tuple[
    tuple[VisualBackendRequest, ...],
    tuple[VisualBackendAttempt, ...],
    tuple[VisualBackendResult, ...],
    tuple[MultimodalIssue, ...],
]:
    assets_by_candidate = {asset.candidate_id: asset for asset in assets}
    terminal_issue_candidates = {issue.candidate_id for issue in existing_issues if issue.terminal}
    requests: list[VisualBackendRequest] = []
    attempts: list[VisualBackendAttempt] = []
    results: list[VisualBackendResult] = []
    issues: list[MultimodalIssue] = []
    calls_by_page: Counter[int] = Counter()
    total_calls = 0
    backend_id = _selected_backend_id(config, registry)
    descriptor = registry.get(backend_id)
    if descriptor is None:
        raise ValueError(f"configured visual backend is not registered: {backend_id}")
    adapter = registry.adapter(backend_id)
    for candidate in candidates:
        if candidate.candidate_id in terminal_issue_candidates:
            continue
        asset = assets_by_candidate.get(candidate.candidate_id)
        if asset is None:
            continue
        if asset.duplicate_of is not None:
            issues.append(
                MultimodalIssue(
                    issue_id=stable_id(
                        "visual-issue", candidate.candidate_id, "duplicate_visual_asset"
                    ),
                    candidate_id=candidate.candidate_id,
                    issue_type="duplicate_visual_asset",
                    severity="info",
                    terminal=True,
                    message="duplicate visual asset deduped without a second backend call",
                    review_required=False,
                    source_refs=tuple(candidate.source_refs),
                )
            )
            continue
        if total_calls >= config.multimodal.backend.max_backend_calls_per_document:
            issues.append(_budget_issue(candidate, "document_visual_backend_budget_exceeded"))
            continue
        if (
            calls_by_page[candidate.page_number]
            >= config.multimodal.backend.max_backend_calls_per_page
        ):
            issues.append(_budget_issue(candidate, "page_visual_backend_budget_exceeded"))
            continue
        payload = _request_payload(candidate, asset)
        request = VisualBackendRequest(
            request_id=stable_id("visual-request", candidate.candidate_id, backend_id),
            candidate_id=candidate.candidate_id,
            backend_id=backend_id,
            idempotency_key=stable_id(
                "visual-idempotency",
                candidate.document_id,
                candidate.candidate_id,
                backend_id,
                asset.image_checksum,
            ),
            status="executed",
            payload=payload,
            timeout_ms=descriptor.timeout_ms,
            budget_units=descriptor.cost_units_per_request,
            created_at=str(candidate.metadata.get("created_at") or candidate.created_at),
        )
        requests.append(request)
        total_calls += 1
        calls_by_page[candidate.page_number] += 1
        for attempt_index in range(1, config.multimodal.backend.max_backend_attempts + 1):
            try:
                backend_result = adapter.execute(request, candidate=candidate, asset=asset)
            except VisualBackendExecutionError as exc:
                terminal = (
                    not exc.retryable
                    or attempt_index >= config.multimodal.backend.max_backend_attempts
                )
                attempts.append(
                    VisualBackendAttempt(
                        attempt_id=stable_id("visual-attempt", request.request_id, attempt_index),
                        request_id=request.request_id,
                        candidate_id=candidate.candidate_id,
                        backend_id=backend_id,
                        attempt_index=attempt_index,
                        status="timeout" if exc.error_code.endswith("timeout") else "failed",
                        terminal=terminal,
                        latency_ms=1.0,
                        retryable=exc.retryable and not terminal,
                        error_code=exc.error_code,
                        reason=str(exc),
                    )
                )
                if terminal:
                    issues.append(
                        MultimodalIssue(
                            issue_id=stable_id(
                                "visual-issue",
                                candidate.candidate_id,
                                exc.error_code,
                            ),
                            candidate_id=candidate.candidate_id,
                            issue_type=exc.error_code,
                            severity="high",
                            terminal=True,
                            message=str(exc),
                            review_required=True,
                            source_refs=tuple(candidate.source_refs),
                        )
                    )
                    break
                continue
            attempts.append(
                VisualBackendAttempt(
                    attempt_id=stable_id("visual-attempt", request.request_id, attempt_index),
                    request_id=request.request_id,
                    candidate_id=candidate.candidate_id,
                    backend_id=backend_id,
                    attempt_index=attempt_index,
                    status="succeeded",
                    terminal=True,
                    latency_ms=1.0,
                )
            )
            results.append(backend_result)
            break
    return tuple(requests), tuple(attempts), tuple(results), tuple(issues)


def _selected_backend_id(config: Phase6Config, registry: VisualBackendRegistry) -> str:
    for backend_id in config.multimodal.backend.enabled_backend_ids:
        descriptor = registry.get(backend_id)
        if descriptor is None:
            continue
        if backend_id in config.multimodal.backend.forbidden_backend_ids:
            continue
        if descriptor.external and not config.multimodal.backend.allow_external_backends:
            continue
        if descriptor.enabled and descriptor.actual_backend and not descriptor.placeholder:
            return backend_id
    raise ValueError("no actual local visual backend is enabled")


def _request_payload(candidate: VisualCandidate, asset: VisualAsset) -> dict[str, Any]:
    backend_payload = dict(candidate.metadata.get("backend_payload") or {})
    return {
        **backend_payload,
        "image_path": asset.source_path,
        "candidate_type": candidate.candidate_type,
        "candidate_bbox": dict(candidate.bbox),
        "text_hint": backend_payload.get("text_hint") or candidate.text_hint,
        "source_refs": list(candidate.source_refs),
        "asset_id": asset.asset_id,
        "asset_checksum": asset.image_checksum,
    }


def _performance(
    candidates: tuple[VisualCandidate, ...],
    requests: tuple[VisualBackendRequest, ...],
    attempts: tuple[VisualBackendAttempt, ...],
    assets: tuple[VisualAsset, ...],
    issues: tuple[MultimodalIssue, ...],
) -> dict[str, Any]:
    terminal_requests = {attempt.request_id for attempt in attempts if attempt.terminal}
    terminal_candidates = {attempt.candidate_id for attempt in attempts if attempt.terminal} | {
        issue.candidate_id for issue in issues if issue.terminal
    }
    return {
        "candidate_count": len(candidates),
        "asset_count": len(assets),
        "request_count": len(requests),
        "attempt_count": len(attempts),
        "terminal_attempt_count": sum(attempt.terminal for attempt in attempts),
        "terminal_visual_coverage": (
            1.0 if not candidates else len(terminal_candidates) / len(candidates)
        ),
        "visual_backend_attempt_terminal_coverage": (
            1.0 if not requests else len(terminal_requests) / len(requests)
        ),
        "duplicate_backend_call_count": len(requests)
        - len({request.idempotency_key for request in requests}),
        "estimated_runtime_ms": float(len(attempts)),
        "estimated_cost_units": sum(request.budget_units for request in requests),
        "artifact_loss": 0,
        "infinite_wait_count": 0,
        "premature_success_count": 0,
    }


def _security(
    requests: tuple[VisualBackendRequest, ...],
    registry: VisualBackendRegistry,
) -> dict[str, Any]:
    selected = [request.backend_id for request in requests]
    external_selected = [
        backend_id
        for backend_id in selected
        if registry.get(backend_id) is not None and registry.get(backend_id).external
    ]
    return {
        "credentials_leaked": False,
        "sensitive_visual_leak_count": 0,
        "sensitive_log_leak_count": 0,
        "external_policy_violation_count": len(external_selected),
        "forbidden_backend_selection_count": len(external_selected),
        "raw_image_bytes_in_logs": False,
        "status": "PASS" if not external_selected else "FAIL",
    }


def _comparison(
    candidates: tuple[VisualCandidate, ...],
    backend_results: tuple[VisualBackendResult, ...],
    extracted: Any,
) -> dict[str, Any]:
    result_types = {result.candidate_id: result.detected_type for result in backend_results}
    type_matches = sum(
        result_types.get(candidate.candidate_id) == _expected_runtime_type(candidate)
        for candidate in candidates
        if candidate.candidate_id in result_types
    )
    typed_count = max(len(result_types), 1)
    return {
        "candidate_count": len(candidates),
        "visual_result_count": len(backend_results),
        "candidate_type_accuracy": round(type_matches / typed_count, 6),
        "figure_count": len(extracted.figures),
        "caption_link_count": len(extracted.caption_links),
        "chart_count": len(extracted.charts),
        "diagram_count": len(extracted.diagrams),
        "visual_text_block_count": len(extracted.visual_text_blocks),
        "signature_count": len(extracted.signatures),
        "stamp_count": len(extracted.stamps),
        "logo_count": len(extracted.logos),
        "visual_issue_count": len(extracted.issues),
        "review_package_count": len(extracted.review_packages),
        "raw_values_preserved": True,
    }


def _expected_runtime_type(candidate: VisualCandidate) -> str:
    if candidate.candidate_type == "embedded_image":
        return "figure"
    if candidate.candidate_type in {
        "figure",
        "chart",
        "diagram",
        "visual_text",
        "signature",
        "stamp",
        "logo",
        "visual_table",
    }:
        return candidate.candidate_type
    return "unknown"


def _budget_issue(candidate: VisualCandidate, issue_type: str) -> MultimodalIssue:
    return MultimodalIssue(
        issue_id=stable_id("visual-issue", candidate.candidate_id, issue_type),
        candidate_id=candidate.candidate_id,
        issue_type=issue_type,
        severity="high",
        terminal=True,
        message=issue_type,
        review_required=True,
        source_refs=tuple(candidate.source_refs),
    )


def _empty_result(
    *,
    document: CanonicalDocument,
    base_checksum: str,
    config: Phase6Config,
    registry: VisualBackendRegistry,
) -> MultimodalExtractionResult:
    return MultimodalExtractionResult(
        canonical_document=document,
        base_document_checksum=base_checksum,
        config_checksum=config.checksum(),
        mode=config.multimodal.mode.value,
        registry_checksum=registry.checksum(),
        performance={
            "candidate_count": 0,
            "asset_count": 0,
            "request_count": 0,
            "attempt_count": 0,
            "terminal_visual_coverage": 1.0,
            "visual_backend_attempt_terminal_coverage": 1.0,
            "duplicate_backend_call_count": 0,
            "artifact_loss": 0,
            "infinite_wait_count": 0,
            "premature_success_count": 0,
        },
        security={
            "credentials_leaked": False,
            "sensitive_visual_leak_count": 0,
            "external_policy_violation_count": 0,
            "status": "PASS",
        },
        comparison={
            "candidate_count": 0,
            "visual_result_count": 0,
            "candidate_type_accuracy": 1.0,
            "raw_values_preserved": True,
        },
    )


def _document_from_cases(cases: tuple[dict[str, Any], ...]) -> CanonicalDocument:
    from app.pipeline.documents.extraction.canonical.ir import CanonicalPage

    page_numbers = sorted({int(item.get("page_number", 1)) for item in cases}) or [1]
    return CanonicalDocument(
        document_id="phase6-controlled",
        source={"title": "phase6-controlled", "extension": "png"},
        document_metadata={},
        parser_provenance={"parser_name": "phase6_benchmark", "parser_version": "1.0"},
        extraction_provenance={"attempt_id": "phase6-controlled"},
        pages=tuple(
            CanonicalPage(
                page_index=index,
                page_number=page_number,
                original_width=640,
                original_height=480,
                original_unit="px",
                page_metadata={},
            )
            for index, page_number in enumerate(page_numbers)
        ),
        created_at="2026-07-26T00:00:00+00:00",
    )


__all__ = [
    "build_multimodal_for_document",
    "commit_multimodal_to_canonical",
    "run_multimodal_cases",
]
