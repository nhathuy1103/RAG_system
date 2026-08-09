from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.pipeline.documents.extraction.canonical.ir import CanonicalDocument
from app.pipeline.documents.extraction.canonical.serialization import canonical_document_to_json


@dataclass(frozen=True)
class CanonicalIRArtifact:
    reference: str
    checksum: str
    schema_name: str
    schema_version: str
    attempt_id: str
    created_at: str
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "checksum": self.checksum,
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "created_at": self.created_at,
        }


def build_canonical_ir_artifact(
    document: CanonicalDocument,
    *,
    attempt_id: str,
    reference: str | None = None,
) -> CanonicalIRArtifact:
    payload_json = canonical_document_to_json(document)
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return CanonicalIRArtifact(
        reference=reference
        or f"canonical-ir-v2:{document.document_id}:{attempt_id}:{checksum[:16]}",
        checksum=checksum,
        schema_name=document.schema_name,
        schema_version=document.schema_version,
        attempt_id=attempt_id,
        created_at=datetime.now(UTC).isoformat(),
        payload_json=payload_json,
    )


def persist_canonical_ir_artifact(
    storage: Any,
    *,
    tenant_id: str,
    owner_id: str,
    document_id: str,
    version: int,
    attempt_id: str,
    artifact: CanonicalDocument,
) -> CanonicalIRArtifact:
    built = build_canonical_ir_artifact(artifact, attempt_id=attempt_id)
    if hasattr(storage, "save_bytes"):
        stored = storage.save_bytes(
            tenant_id=tenant_id,
            owner_id=owner_id,
            document_id=document_id,
            version=version,
            filename=f"canonical-ir-v2-{attempt_id}.json",
            content=built.payload_json.encode("utf-8"),
        )
        return CanonicalIRArtifact(
            reference=getattr(stored, "storage_path", built.reference),
            checksum=built.checksum,
            schema_name=built.schema_name,
            schema_version=built.schema_version,
            attempt_id=built.attempt_id,
            created_at=built.created_at,
            payload_json=built.payload_json,
        )
    return built
