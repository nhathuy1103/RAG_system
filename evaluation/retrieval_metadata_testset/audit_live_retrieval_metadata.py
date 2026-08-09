"""Export reproducible coverage evidence for live retrieval metadata.

The audit is read-only. It selects the same ready/active/current document scope
used by the live document-scope ablation and inspects only the nested
``document_chunks.metadata.retrieval_metadata`` object.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2 as httpx

from app.bootstrap.settings import get_settings as get_app_settings
from app.pipeline.bootstrap.settings import get_settings as get_ingestion_settings

DEFAULT_OUTPUT = Path(__file__).parent / "runs" / "live-retrieval-metadata-audit"
DEFAULT_NOTEBOOK_ID = "7769d606-146c-4a4d-8d9d-3889aa2d5d33"

REVIEW_FIELDS = (
    "title",
    "document_type",
    "section_title",
    "section_path",
    "content_kind",
    "table_header",
    "keyword_aliases",
    "contextual_summary",
    "contextual_search_terms",
    "project_id",
    "project_code",
    "project_name",
    "project_aliases",
    "year",
    "data_period",
    "effective_status",
    "lifecycle_status",
    "domain",
    "clause_type",
    "region",
    "source",
)


def _present(value: object) -> bool:
    return value not in (None, "", [], {}, ())


def _display(value: object) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _fetch_live_state(
    client: httpx.Client,
    notebook_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    documents_response = client.get(
        "/documents",
        params={
            "notebook_id": f"eq.{notebook_id}",
            "status": "eq.ready",
            "is_active": "eq.true",
            "is_current": "eq.true",
            "canonical_document_id": "is.null",
            "select": "id,original_filename,status,is_active,is_current,canonical_document_id",
        },
    )
    documents_response.raise_for_status()
    chunks_response = client.get(
        "/document_chunks",
        params={
            "notebook_id": f"eq.{notebook_id}",
            "select": "id,document_id,chunk_index,metadata",
            "limit": "10000",
        },
    )
    chunks_response.raise_for_status()
    documents = documents_response.json()
    chunks = chunks_response.json()
    if not isinstance(documents, list) or not isinstance(chunks, list):
        raise TypeError("Supabase audit responses must be arrays")
    return documents, chunks


def run(args: argparse.Namespace) -> None:
    app_settings = get_app_settings()
    ingestion_settings = get_ingestion_settings()
    if app_settings.supabase_rest_url is None or app_settings.supabase_service_role_key is None:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    service_key = app_settings.supabase_service_role_key.get_secret_value()
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
    }
    with httpx.Client(
        base_url=str(app_settings.supabase_rest_url),
        headers=headers,
        timeout=30.0,
    ) as client:
        documents, all_chunks = _fetch_live_state(client, args.notebook_id)

    active_document_ids = {str(row["id"]) for row in documents}
    chunks = [
        row for row in all_chunks if str(row.get("document_id")) in active_document_ids
    ]
    values_by_field: dict[str, Counter[str]] = defaultdict(Counter)
    chunks_per_document: Counter[str] = Counter()
    for chunk in chunks:
        chunks_per_document[str(chunk.get("document_id"))] += 1
        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            continue
        retrieval = metadata.get("retrieval_metadata")
        if not isinstance(retrieval, dict):
            continue
        for field, value in retrieval.items():
            if _present(value):
                values_by_field[str(field)][_display(value)] += 1

    fields = sorted(set(REVIEW_FIELDS) | set(values_by_field))
    total = len(chunks)
    field_rows: list[dict[str, object]] = []
    for field in fields:
        values = values_by_field[field]
        count = sum(values.values())
        field_rows.append(
            {
                "field": field,
                "present_chunk_count": count,
                "total_active_chunk_count": total,
                "coverage_rate": round(count / total, 6) if total else 0.0,
                "distinct_value_count": len(values),
                "sample_values": " | ".join(value for value, _ in values.most_common(5)),
            }
        )

    document_rows = [
        {
            "document_id": str(document["id"]),
            "original_filename": str(document["original_filename"]),
            "active_chunk_count": chunks_per_document[str(document["id"])],
        }
        for document in sorted(documents, key=lambda row: str(row["original_filename"]))
    ]
    summary = {
        "schema_version": "live-retrieval-metadata-audit-v1",
        "audited_at_utc": datetime.now(UTC).isoformat(),
        "source": "live_supabase_document_chunks",
        "vector_store_backend": ingestion_settings.vector_store_backend,
        "notebook_id": args.notebook_id,
        "scope": {
            "document_status": "ready",
            "is_active": True,
            "is_current": True,
            "canonical_document_id": None,
        },
        "active_document_count": len(documents),
        "active_chunk_count": total,
        "inspected_path": "document_chunks.metadata.retrieval_metadata",
        "gold_metadata_injected": False,
        "documents": document_rows,
        "fields": field_rows,
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (args.output / "field_coverage.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(field_rows[0]))
        writer.writeheader()
        writer.writerows(field_rows)
    with (args.output / "documents.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(document_rows[0]))
        writer.writeheader()
        writer.writerows(document_rows)
    print(
        f"Wrote live metadata audit: documents={len(documents)} chunks={total} "
        f"output={args.output}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook-id", default=DEFAULT_NOTEBOOK_ID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output = args.output.resolve()
    run(args)


if __name__ == "__main__":
    main()
