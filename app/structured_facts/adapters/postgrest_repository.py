"""Service-role PostgREST adapter for structured fact replacement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from uuid import UUID

import httpx2 as httpx

from app.structured_facts.domain.review import (
    StructuredClaimRelation,
    StructuredClaimRelationEvidence,
    StructuredClaimRelationType,
    StructuredClaimResolutionAction,
    StructuredClaimReviewStatus,
    StructuredFactClaimEvidence,
    StructuredFactSnapshotEvidence,
)
from app.structured_facts.ports.repositories import (
    StructuredClaimCandidate,
    StructuredFactEvidence,
    StructuredFactRepositoryError,
    StructuredFactReviewConflictError,
    StructuredFactReviewRepository,
    StructuredFactReviewRepositoryError,
    StructuredFactSearch,
    StructuredFactWriteResult,
)

RELATION_REVIEW_COLUMNS = (
    "id,owner_id,notebook_id,source_snapshot_id,target_snapshot_id,"
    "source_claim_id,target_claim_id,relation_type,scope_relation,"
    "qualifier_compatibility,temporal_compatibility,confidence,evidence,reason,"
    "detector_name,detector_version,review_status,resolved_by,resolved_at,"
    "created_at,updated_at"
)
SNAPSHOT_EVIDENCE_COLUMNS = (
    "id,document_id,source_chunk_id,snapshot_key,schema_fingerprint,"
    "template_fingerprint,table_index,page_from,page_to,source_locator,"
    "normalized_schema,row_count,column_count,extractor_name,extractor_version,"
    "publication_time,effective_from,effective_to,observed_at,ingested_at,"
    "source_publisher,source_type,authority_level,authority_metadata,warnings,"
    "extraction_confidence,created_at,updated_at"
)
CLAIM_EVIDENCE_COLUMNS = (
    "id,document_id,snapshot_id,source_chunk_id,claim_key,row_identity,"
    "row_identity_hash,row_index,data_row_ordinal,page_number,source_text,"
    "source_cells,provenance,subject_identity,subject_identity_hash,"
    "candidate_identity_hash,predicate,value_type,normalized_value,numeric_value,"
    "unit,currency,qualifiers,qualifier_hash,publication_time,effective_from,"
    "effective_to,observed_at,ingested_at,source_publisher,source_type,"
    "authority_level,authority_metadata,confidence,is_derived,derivation,"
    "extractor_version,created_at,updated_at"
)


class PostgrestStructuredFactRepository:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def replace_for_document(
        self,
        *,
        job_id: UUID,
        document_id: UUID,
        extractor_version: str,
        table_snapshots: Sequence[Mapping[str, object]],
        claims: Sequence[Mapping[str, object]],
        relations: Sequence[Mapping[str, object]] = (),
    ) -> StructuredFactWriteResult:
        if not extractor_version.strip():
            raise ValueError("extractor_version is required")
        try:
            response = await self._client.post(
                "/rpc/replace_structured_facts_for_document",
                json={
                    "p_job_id": str(job_id),
                    "p_document_id": str(document_id),
                    "p_extractor_version": extractor_version,
                    "p_table_snapshots": [dict(item) for item in table_snapshots],
                    "p_claims": [dict(item) for item in claims],
                    "p_relations": [dict(item) for item in relations],
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise TypeError("Structured fact replacement response must be an object")
            return StructuredFactWriteResult(
                table_count=int(payload.get("table_count") or 0),
                claim_count=int(payload.get("claim_count") or 0),
                relation_count=int(payload.get("relation_count") or 0),
            )
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            raise StructuredFactRepositoryError(
                "Failed to replace structured facts for document"
            ) from exc

    async def search(
        self,
        query: StructuredFactSearch,
    ) -> tuple[StructuredFactEvidence, ...]:
        if not query.document_ids:
            return ()
        try:
            response = await self._client.post(
                "/rpc/search_structured_claims",
                json=_search_body(query),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Structured fact search response must be a list")
            evidence: list[StructuredFactEvidence] = []
            for item in payload:
                if not isinstance(item, Mapping):
                    raise TypeError("Structured fact search row must be an object")
                evidence.append(_search_evidence(item))
            return tuple(evidence)
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            raise StructuredFactRepositoryError("Failed to search structured facts") from exc

    async def load_claim_candidates(
        self,
        *,
        notebook_id: UUID,
        document_id: UUID,
        candidate_identity_hashes: Sequence[str],
        schema_fingerprints: Sequence[str] = (),
        limit: int = 10000,
    ) -> tuple[StructuredClaimCandidate, ...]:
        if not candidate_identity_hashes and not schema_fingerprints:
            return ()
        try:
            response = await self._client.post(
                "/rpc/load_structured_claim_candidates",
                json={
                    "p_notebook_id": str(notebook_id),
                    "p_document_id": str(document_id),
                    "p_candidate_hashes": sorted(set(candidate_identity_hashes)),
                    "p_limit": limit,
                    "p_schema_fingerprints": sorted(set(schema_fingerprints)),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Structured candidate response must be a list")
            candidates: list[StructuredClaimCandidate] = []
            for item in payload:
                if not isinstance(item, Mapping):
                    raise TypeError("Structured candidate row must be an object")
                claim = item.get("claim")
                if not isinstance(claim, Mapping):
                    raise TypeError("Structured candidate claim must be an object")
                candidates.append(
                    StructuredClaimCandidate(
                        claim_id=UUID(str(item["claim_id"])),
                        snapshot_id=UUID(str(item["snapshot_id"])),
                        document_id=UUID(str(item["document_id"])),
                        document_version=max(1, int(item.get("document_version") or 1)),
                        snapshot_key=str(item["snapshot_key"]),
                        schema_fingerprint=str(item["schema_fingerprint"]),
                        template_fingerprint=(
                            str(item["template_fingerprint"])
                            if item.get("template_fingerprint")
                            else None
                        ),
                        normalized_schema=(
                            dict(item["normalized_schema"])
                            if isinstance(item.get("normalized_schema"), Mapping)
                            else {}
                        ),
                        candidate_identity_hash=str(item["candidate_identity_hash"]),
                        claim=dict(claim),
                    )
                )
            return tuple(candidates)
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            raise StructuredFactRepositoryError(
                "Failed to load structured claim candidates"
            ) from exc


class PostgrestStructuredFactReviewRepository(StructuredFactReviewRepository):
    """Review structured relations through a user-JWT-scoped Data API client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def list_pending_relations(
        self,
        notebook_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[StructuredClaimRelation], int]:
        try:
            response = await self._client.get(
                "/claim_relations",
                params={
                    "notebook_id": f"eq.{notebook_id}",
                    "review_status": "eq.pending",
                    "select": RELATION_REVIEW_COLUMNS,
                    "order": "confidence.desc,created_at.desc,id.asc",
                    "limit": str(limit),
                    "offset": str(offset),
                },
                headers={"Prefer": "count=exact"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Structured relation response must be an array")
            total_count = _parse_total_count(response.headers.get("content-range"))
            return [_parse_review_relation(row) for row in payload], total_count
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            raise StructuredFactReviewRepositoryError(
                "Failed to list pending structured claim relations"
            ) from exc

    async def get_relation_evidence(
        self,
        notebook_id: UUID,
        relation_id: UUID,
    ) -> StructuredClaimRelationEvidence | None:
        try:
            relation_response = await self._client.get(
                "/claim_relations",
                params={
                    "id": f"eq.{relation_id}",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": RELATION_REVIEW_COLUMNS,
                    "limit": "1",
                },
            )
            relation_response.raise_for_status()
            relation_payload = relation_response.json()
            if not isinstance(relation_payload, list):
                raise TypeError("Structured relation response must be an array")
            if not relation_payload:
                return None
            if len(relation_payload) != 1:
                raise TypeError("Structured relation lookup returned multiple rows")
            relation = _parse_review_relation(relation_payload[0])

            snapshot_ids = tuple(
                dict.fromkeys((relation.source_snapshot_id, relation.target_snapshot_id))
            )
            snapshot_filter = ",".join(str(value) for value in snapshot_ids)
            snapshots_response = await self._client.get(
                "/table_snapshots",
                params={
                    "id": f"in.({snapshot_filter})",
                    "notebook_id": f"eq.{notebook_id}",
                    "select": SNAPSHOT_EVIDENCE_COLUMNS,
                },
            )
            snapshots_response.raise_for_status()
            snapshots_payload = snapshots_response.json()
            if not isinstance(snapshots_payload, list):
                raise TypeError("Structured snapshot response must be an array")
            snapshots = {
                snapshot.id: snapshot
                for snapshot in (_parse_snapshot_evidence(row) for row in snapshots_payload)
            }
            source_snapshot = snapshots.get(relation.source_snapshot_id)
            target_snapshot = snapshots.get(relation.target_snapshot_id)
            if source_snapshot is None or target_snapshot is None:
                raise TypeError("Structured relation snapshot evidence is incomplete")

            claim_ids = tuple(
                dict.fromkeys(
                    value
                    for value in (
                        relation.source_claim_id,
                        relation.target_claim_id,
                    )
                    if value is not None
                )
            )
            claims: dict[UUID, StructuredFactClaimEvidence] = {}
            if claim_ids:
                claim_filter = ",".join(str(value) for value in claim_ids)
                claims_response = await self._client.get(
                    "/structured_claims",
                    params={
                        "id": f"in.({claim_filter})",
                        "notebook_id": f"eq.{notebook_id}",
                        "select": CLAIM_EVIDENCE_COLUMNS,
                    },
                )
                claims_response.raise_for_status()
                claims_payload = claims_response.json()
                if not isinstance(claims_payload, list):
                    raise TypeError("Structured claim response must be an array")
                claims = {
                    claim.id: claim
                    for claim in (_parse_claim_evidence(row) for row in claims_payload)
                }

            source_claim = (
                claims.get(relation.source_claim_id)
                if relation.source_claim_id is not None
                else None
            )
            target_claim = (
                claims.get(relation.target_claim_id)
                if relation.target_claim_id is not None
                else None
            )
            if relation.source_claim_id is not None and source_claim is None:
                raise TypeError("Structured source claim evidence is incomplete")
            if relation.target_claim_id is not None and target_claim is None:
                raise TypeError("Structured target claim evidence is incomplete")
            if source_claim is not None and source_claim.snapshot_id != source_snapshot.id:
                raise TypeError("Structured source claim does not belong to source snapshot")
            if target_claim is not None and target_claim.snapshot_id != target_snapshot.id:
                raise TypeError("Structured target claim does not belong to target snapshot")

            return StructuredClaimRelationEvidence(
                relation=relation,
                source_snapshot=source_snapshot,
                target_snapshot=target_snapshot,
                source_claim=source_claim,
                target_claim=target_claim,
            )
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            raise StructuredFactReviewRepositoryError(
                "Failed to load structured claim relation evidence"
            ) from exc

    async def resolve_relation(
        self,
        notebook_id: UUID,
        relation_id: UUID,
        action: StructuredClaimResolutionAction,
        expected_updated_at: datetime,
        reason: str,
    ) -> StructuredClaimRelation | None:
        try:
            response = await self._client.post(
                "/rpc/resolve_structured_claim_relation",
                json={
                    "p_relation_id": str(relation_id),
                    "p_notebook_id": str(notebook_id),
                    "p_action": action.value,
                    "p_expected_updated_at": expected_updated_at.isoformat(),
                    "p_reason": reason,
                },
            )
            if response.status_code >= 400 and _is_not_found(response):
                return None
            if response.status_code >= 400 and _is_conflict(response):
                raise StructuredFactReviewConflictError(
                    "Structured relation changed before this decision was saved"
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Structured resolve response must be an array")
            if not payload:
                return None
            if len(payload) != 1:
                raise TypeError("Structured resolve response must contain one relation")
            return _parse_review_relation(payload[0])
        except StructuredFactReviewConflictError:
            raise
        except (httpx.HTTPError, OSError, KeyError, TypeError, ValueError) as exc:
            raise StructuredFactReviewRepositoryError(
                "Failed to resolve structured claim relation"
            ) from exc


class PostgrestStructuredFactReader:
    """Request-scoped synchronous reader used by the threaded chat boundary."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def search(
        self,
        query: StructuredFactSearch,
    ) -> tuple[StructuredFactEvidence, ...]:
        if not query.document_ids:
            return ()
        try:
            response = self._client.post(
                "/rpc/search_structured_claims",
                json=_search_body(query),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError("Structured fact search response must be a list")
            return tuple(_search_evidence(item) for item in payload if isinstance(item, Mapping))
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            raise StructuredFactRepositoryError("Failed to search structured facts") from exc


def _search_body(query: StructuredFactSearch) -> dict[str, object]:
    return {
        "p_notebook_id": str(query.notebook_id),
        "p_document_ids": [str(value) for value in query.document_ids],
        "p_predicate": query.predicate,
        "p_subject_query": query.subject_query,
        "p_valid_from": _serialize_time_bound(query.valid_from, end=False),
        "p_valid_to": _serialize_time_bound(query.valid_to, end=True),
        "p_limit": query.limit,
        "p_qualifiers": dict(query.qualifiers),
    }


def _serialize_time_bound(value: date | datetime | None, *, end: bool) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    boundary = time.max if end else time.min
    return datetime.combine(value, boundary, tzinfo=UTC).isoformat()


def _search_evidence(item: Mapping[str, object]) -> StructuredFactEvidence:
    def mapping(key: str) -> Mapping[str, object]:
        value = item.get(key)
        return dict(value) if isinstance(value, Mapping) else {}

    raw_warnings = item.get("relation_warnings")
    warnings = (
        tuple(dict(value) for value in raw_warnings if isinstance(value, Mapping))
        if isinstance(raw_warnings, list | tuple)
        else ()
    )
    return StructuredFactEvidence(
        claim_id=str(item["claim_id"]),
        document_id=UUID(str(item["document_id"])),
        source_chunk_id=UUID(str(item["source_chunk_id"])),
        document_version=max(1, _int_value(item.get("document_version"), default=1)),
        subject_key=str(item["subject_key"]),
        predicate=str(item["predicate"]),
        normalized_value=mapping("normalized_value"),
        qualifiers=mapping("qualifiers"),
        temporal=mapping("temporal"),
        provenance=mapping("provenance"),
        confidence=_float_value(item.get("confidence"), default=0.0),
        source_text=str(item.get("source_text") or ""),
        relation_warnings=warnings,
        authority=mapping("authority_metadata"),
    )


def _parse_review_relation(row: object) -> StructuredClaimRelation:
    item = _row_mapping(row, "Structured relation")
    return StructuredClaimRelation(
        id=UUID(str(item["id"])),
        owner_id=UUID(str(item["owner_id"])),
        notebook_id=UUID(str(item["notebook_id"])),
        source_snapshot_id=UUID(str(item["source_snapshot_id"])),
        target_snapshot_id=UUID(str(item["target_snapshot_id"])),
        source_claim_id=_optional_uuid(item.get("source_claim_id")),
        target_claim_id=_optional_uuid(item.get("target_claim_id")),
        relation_type=StructuredClaimRelationType(str(item["relation_type"])),
        scope_relation=str(item["scope_relation"]),
        qualifier_compatibility=str(item["qualifier_compatibility"]),
        temporal_compatibility=str(item["temporal_compatibility"]),
        confidence=_required_float(item.get("confidence"), "confidence"),
        evidence=_json_mapping(item.get("evidence"), "relation evidence"),
        reason=_optional_text(item.get("reason")),
        detector_name=str(item["detector_name"]),
        detector_version=str(item["detector_version"]),
        review_status=StructuredClaimReviewStatus(str(item["review_status"])),
        resolved_by=_optional_uuid(item.get("resolved_by")),
        resolved_at=_optional_datetime(item.get("resolved_at")),
        created_at=_required_datetime(item.get("created_at"), "created_at"),
        updated_at=_required_datetime(item.get("updated_at"), "updated_at"),
    )


def _parse_snapshot_evidence(row: object) -> StructuredFactSnapshotEvidence:
    item = _row_mapping(row, "Structured snapshot")
    raw_schema = item.get("normalized_schema")
    if isinstance(raw_schema, Mapping):
        normalized_schema: Mapping[str, object] | tuple[object, ...] = dict(raw_schema)
    elif isinstance(raw_schema, list | tuple):
        normalized_schema = tuple(raw_schema)
    else:
        raise TypeError("normalized_schema must be an object or array")
    return StructuredFactSnapshotEvidence(
        id=UUID(str(item["id"])),
        document_id=UUID(str(item["document_id"])),
        source_chunk_id=_optional_uuid(item.get("source_chunk_id")),
        snapshot_key=str(item["snapshot_key"]),
        schema_fingerprint=str(item["schema_fingerprint"]),
        template_fingerprint=_optional_text(item.get("template_fingerprint")),
        table_index=_required_int(item.get("table_index"), "table_index"),
        page_from=_optional_int(item.get("page_from")),
        page_to=_optional_int(item.get("page_to")),
        source_locator=_json_mapping(item.get("source_locator"), "source_locator"),
        normalized_schema=normalized_schema,
        row_count=_required_int(item.get("row_count"), "row_count"),
        column_count=_required_int(item.get("column_count"), "column_count"),
        extractor_name=str(item["extractor_name"]),
        extractor_version=str(item["extractor_version"]),
        publication_time=_optional_datetime(item.get("publication_time")),
        effective_from=_optional_datetime(item.get("effective_from")),
        effective_to=_optional_datetime(item.get("effective_to")),
        observed_at=_optional_datetime(item.get("observed_at")),
        ingested_at=_required_datetime(item.get("ingested_at"), "ingested_at"),
        source_publisher=_optional_text(item.get("source_publisher")),
        source_type=str(item["source_type"]),
        authority_level=_optional_int(item.get("authority_level")),
        authority_metadata=_json_mapping(
            item.get("authority_metadata"),
            "authority_metadata",
        ),
        warnings=_json_array(item.get("warnings"), "warnings"),
        extraction_confidence=_required_float(
            item.get("extraction_confidence"),
            "extraction_confidence",
        ),
        created_at=_required_datetime(item.get("created_at"), "created_at"),
        updated_at=_required_datetime(item.get("updated_at"), "updated_at"),
    )


def _parse_claim_evidence(row: object) -> StructuredFactClaimEvidence:
    item = _row_mapping(row, "Structured claim")
    return StructuredFactClaimEvidence(
        id=UUID(str(item["id"])),
        document_id=UUID(str(item["document_id"])),
        snapshot_id=UUID(str(item["snapshot_id"])),
        source_chunk_id=_optional_uuid(item.get("source_chunk_id")),
        claim_key=str(item["claim_key"]),
        row_identity=str(item["row_identity"]),
        row_identity_hash=str(item["row_identity_hash"]),
        row_index=_required_int(item.get("row_index"), "row_index"),
        data_row_ordinal=_optional_int(item.get("data_row_ordinal")),
        page_number=_optional_int(item.get("page_number")),
        source_text=_optional_text(item.get("source_text")),
        source_cells=_json_array(item.get("source_cells"), "source_cells"),
        provenance=_json_mapping(item.get("provenance"), "provenance"),
        subject_identity=_json_mapping(
            item.get("subject_identity"),
            "subject_identity",
        ),
        subject_identity_hash=str(item["subject_identity_hash"]),
        candidate_identity_hash=str(item["candidate_identity_hash"]),
        predicate=str(item["predicate"]),
        value_type=str(item["value_type"]),
        normalized_value=_json_mapping(
            item.get("normalized_value"),
            "normalized_value",
        ),
        numeric_value=(
            str(item["numeric_value"]) if item.get("numeric_value") is not None else None
        ),
        unit=_optional_text(item.get("unit")),
        currency=_optional_text(item.get("currency")),
        qualifiers=_json_mapping(item.get("qualifiers"), "qualifiers"),
        qualifier_hash=str(item["qualifier_hash"]),
        publication_time=_optional_datetime(item.get("publication_time")),
        effective_from=_optional_datetime(item.get("effective_from")),
        effective_to=_optional_datetime(item.get("effective_to")),
        observed_at=_optional_datetime(item.get("observed_at")),
        ingested_at=_required_datetime(item.get("ingested_at"), "ingested_at"),
        source_publisher=_optional_text(item.get("source_publisher")),
        source_type=str(item["source_type"]),
        authority_level=_optional_int(item.get("authority_level")),
        authority_metadata=_json_mapping(
            item.get("authority_metadata"),
            "authority_metadata",
        ),
        confidence=_required_float(item.get("confidence"), "confidence"),
        is_derived=bool(item["is_derived"]),
        derivation=_json_mapping(item.get("derivation"), "derivation"),
        extractor_version=str(item["extractor_version"]),
        created_at=_required_datetime(item.get("created_at"), "created_at"),
        updated_at=_required_datetime(item.get("updated_at"), "updated_at"),
    )


def _row_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} row must be an object")
    return value


def _json_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return dict(value)


def _json_array(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{label} must be an array")
    return tuple(value)


def _optional_uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value is not None else None


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _required_int(value, "integer value")


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"{label} must be an integer")


def _required_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be numeric")
    if isinstance(value, int | float | str):
        return float(value)
    raise TypeError(f"{label} must be numeric")


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _required_datetime(value: object, label: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise TypeError(f"{label} is required")
    return parsed


def _parse_total_count(content_range: str | None) -> int:
    if content_range is None or "/" not in content_range:
        raise ValueError("PostgREST count response is missing Content-Range")
    total = content_range.rsplit("/", maxsplit=1)[1]
    if total == "*":
        raise ValueError("PostgREST did not return an exact count")
    return int(total)


def _is_not_found(response: httpx.Response) -> bool:
    try:
        payload = response.json()
    except ValueError:
        return response.status_code == 404
    return (
        response.status_code == 404
        or isinstance(payload, Mapping)
        and payload.get("code") == "P0002"
    )


def _is_conflict(response: httpx.Response) -> bool:
    try:
        payload = response.json()
    except ValueError:
        return response.status_code == 409
    return (
        response.status_code == 409
        or isinstance(payload, Mapping)
        and payload.get("code") == "40001"
    )


def _int_value(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str | float):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default
    return default


def _float_value(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return default
    return default


__all__ = [
    "CLAIM_EVIDENCE_COLUMNS",
    "RELATION_REVIEW_COLUMNS",
    "SNAPSHOT_EVIDENCE_COLUMNS",
    "PostgrestStructuredFactReader",
    "PostgrestStructuredFactRepository",
    "PostgrestStructuredFactReviewRepository",
]
