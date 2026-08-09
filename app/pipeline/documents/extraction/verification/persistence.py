from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    write_json,
    write_jsonl,
)
from app.pipeline.documents.extraction.verification.engine import VerificationDocumentResult
from app.pipeline.documents.extraction.verification.providers import ProviderRegistry


@dataclass(frozen=True)
class Phase5VerificationArtifact:
    reference: str
    checksum: str
    created_at: str
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "checksum": self.checksum,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class VerificationArtifactStore:
    output_dir: Path = Path("output")

    @property
    def provider_registry_path(self) -> Path:
        return self.output_dir / "provider_registry.json"

    @property
    def provider_requests_path(self) -> Path:
        return self.output_dir / "provider_requests.jsonl"

    @property
    def provider_attempts_path(self) -> Path:
        return self.output_dir / "provider_attempts.jsonl"

    @property
    def provider_results_path(self) -> Path:
        return self.output_dir / "provider_results.jsonl"

    @property
    def provider_errors_path(self) -> Path:
        return self.output_dir / "provider_errors.jsonl"

    @property
    def extraction_evidence_path(self) -> Path:
        return self.output_dir / "extraction_evidence.jsonl"

    @property
    def verification_cases_path(self) -> Path:
        return self.output_dir / "verification_cases.jsonl"

    @property
    def disagreements_path(self) -> Path:
        return self.output_dir / "disagreements.jsonl"

    @property
    def consensus_results_path(self) -> Path:
        return self.output_dir / "consensus_results.jsonl"

    @property
    def arbitration_decisions_path(self) -> Path:
        return self.output_dir / "arbitration_decisions.jsonl"

    @property
    def abstentions_path(self) -> Path:
        return self.output_dir / "abstentions.jsonl"

    @property
    def review_packages_path(self) -> Path:
        return self.output_dir / "review_packages.jsonl"

    @property
    def verified_results_path(self) -> Path:
        return self.output_dir / "verified_results.jsonl"

    def persist_result(
        self,
        result: VerificationDocumentResult,
        *,
        registry: ProviderRegistry,
    ) -> None:
        write_json(self.provider_registry_path, registry.to_dict())
        write_jsonl_atomic(
            self.provider_requests_path,
            [item.to_dict() for item in result.requests],
        )
        write_jsonl_atomic(
            self.provider_attempts_path,
            [item.to_dict() for item in result.attempts],
        )
        write_jsonl_atomic(
            self.provider_results_path,
            [item.to_dict() for item in result.results],
        )
        write_jsonl_atomic(
            self.provider_errors_path,
            [item.to_dict() for item in result.errors],
        )
        write_jsonl_atomic(
            self.extraction_evidence_path,
            [item.to_dict() for item in result.evidence],
        )
        write_jsonl_atomic(
            self.verification_cases_path,
            [item.to_dict() for item in result.cases],
        )
        write_jsonl_atomic(
            self.disagreements_path,
            [item.to_dict() for item in result.disagreements],
        )
        write_jsonl_atomic(
            self.consensus_results_path,
            [item.to_dict() for item in result.consensus],
        )
        write_jsonl_atomic(
            self.arbitration_decisions_path,
            [item.to_dict() for item in result.decisions],
        )
        write_jsonl_atomic(
            self.abstentions_path,
            [item.to_dict() for item in result.abstentions],
        )
        write_jsonl_atomic(self.review_packages_path, result.review_packages)
        write_jsonl_atomic(
            self.verified_results_path,
            [
                {
                    "case_id": decision.case_id,
                    "status": decision.status,
                    "verified_value": decision.verified_value,
                    "raw_value_preserved": decision.raw_value_preserved,
                    "confidence": decision.confidence,
                    "provider_ids": list(decision.provider_ids),
                    "decision_id": decision.decision_id,
                }
                for decision in result.decisions
            ],
        )


def build_verification_artifact(
    result: VerificationDocumentResult,
    *,
    attempt_id: str,
) -> Phase5VerificationArtifact:
    payload = {
        "artifact_type": "phase5_provider_verification",
        "attempt_id": attempt_id,
        "mode": result.mode.value,
        "config_checksum": result.config_checksum,
        "registry_checksum": result.registry_checksum,
        "cases": [item.to_dict() for item in result.cases],
        "requests": [item.to_dict() for item in result.requests],
        "attempts": [item.to_dict() for item in result.attempts],
        "results": [item.to_dict() for item in result.results],
        "errors": [item.to_dict() for item in result.errors],
        "evidence": [item.to_dict() for item in result.evidence],
        "disagreements": [item.to_dict() for item in result.disagreements],
        "consensus": [item.to_dict() for item in result.consensus],
        "decisions": [item.to_dict() for item in result.decisions],
        "abstentions": [item.to_dict() for item in result.abstentions],
        "review_packages": list(result.review_packages),
        "performance": result.performance,
        "security": result.security,
        "comparison": result.comparison,
    }
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return Phase5VerificationArtifact(
        reference=f"phase5-verification:{attempt_id}:{checksum[:16]}",
        checksum=checksum,
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        payload_json=payload_json,
    )


def persist_verification_artifact(
    storage: Any,
    *,
    tenant_id: str,
    owner_id: str,
    document_id: str,
    version: int,
    attempt_id: str,
    result: VerificationDocumentResult,
) -> Phase5VerificationArtifact:
    built = build_verification_artifact(result, attempt_id=attempt_id)
    if hasattr(storage, "save_bytes"):
        stored = storage.save_bytes(
            tenant_id=tenant_id,
            owner_id=owner_id,
            document_id=document_id,
            version=version,
            filename=f"phase5-verification-{attempt_id}.json",
            content=built.payload_json.encode("utf-8"),
        )
        return Phase5VerificationArtifact(
            reference=getattr(stored, "storage_path", built.reference),
            checksum=built.checksum,
            created_at=built.created_at,
            payload_json=built.payload_json,
        )
    return built


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    write_jsonl(tmp_path, rows)
    os.replace(tmp_path, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


__all__ = [
    "Phase5VerificationArtifact",
    "VerificationArtifactStore",
    "build_verification_artifact",
    "persist_verification_artifact",
    "read_jsonl",
    "write_jsonl_atomic",
]
