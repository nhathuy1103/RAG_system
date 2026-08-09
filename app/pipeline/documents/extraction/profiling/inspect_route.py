from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.pipeline.documents.extraction.profiling.config import Phase2Config, RoutingMode
from app.pipeline.documents.extraction.profiling.profiler import PageProfiler
from app.pipeline.documents.extraction.profiling.router import AdaptiveRouter


def inspect_route(
    *,
    document_path: Path,
    page: int,
    document_id: str | None = None,
    config: Phase2Config | None = None,
) -> dict[str, object]:
    selected_config = config or Phase2Config.from_mapping(
        {
            "profiling": {"enabled": True},
            "routing": {"mode": RoutingMode.ADAPTIVE.value},
        }
    )
    content = document_path.read_bytes()
    profiler = PageProfiler(selected_config.profiling)
    router = AdaptiveRouter(selected_config.routing)
    profiles = profiler.profile_document(
        document_path.name,
        content,
        document_id=document_id or document_path.stem,
    )
    profile = next((item for item in profiles if item.page_number == page), None)
    if profile is None:
        raise SystemExit(f"page not found: {page}")
    classification = router.classify(profile)
    decision = router.decide(profile)
    return {
        "document_id": profile.document_id,
        "page": page,
        "raw_signals": profile.evidence,
        "normalized_signals": profile.to_dict(),
        "page_profile": profile.to_dict(),
        "classification": classification.to_dict(),
        "policy_thresholds": decision.evidence["policy_thresholds"],
        "decision": decision.to_dict(),
        "reason_codes": decision.reason_codes,
        "attempts": {
            "maximum_attempts": decision.maximum_attempts,
            "maximum_orientation_candidates": decision.maximum_orientation_candidates,
            "maximum_page_deadline_ms": decision.maximum_page_deadline_ms,
        },
        "selected_result": decision.route.value,
        "fallback": decision.fallback_route.value if decision.fallback_route else None,
        "quality_outcome": "NOT_RUN_BY_INSPECTOR",
        "downstream_hints": decision.downstream_hints.to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect one Phase 2 page route.")
    parser.add_argument("--document-id")
    parser.add_argument("--document-path", type=Path, required=True)
    parser.add_argument("--page", type=int, required=True)
    args = parser.parse_args()
    payload = inspect_route(
        document_path=args.document_path,
        page=args.page,
        document_id=args.document_id,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
