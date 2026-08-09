"""Export document and chunk metadata from Supabase PostgREST without mutation.

Only HTTP GET requests are issued. Embedding vectors are intentionally omitted;
chunk content is included by default because human annotation needs evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.metadata_baseline.common import (  # noqa: E402
    MetadataBaselineError,
    ensure_outputs,
    write_json,
)

LOGGER = logging.getLogger("metadata_baseline.export")

DOCUMENT_SELECT = (
    "id,owner_id,notebook_id,original_filename,storage_bucket,storage_object_path,"
    "mime_type,size_bytes,content_hash,status,error_message,is_active,created_at,updated_at,"
    "normalized_content_hash,normalization_version,loose_content_signature,"
    "canonical_document_id,version_group_id,version_number,effective_from,effective_to,"
    "supersedes_document_id,is_current,quality_status,quality_metadata"
)
CHUNK_SELECT_WITH_CONTENT = (
    "id,owner_id,notebook_id,document_id,chunk_index,content,token_count,metadata,created_at,"
    "normalized_content_hash,normalization_version,loose_content_signature,"
    "exact_duplicate_group_id"
)
CHUNK_SELECT_WITHOUT_CONTENT = CHUNK_SELECT_WITH_CONTENT.replace("content,", "")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _rest_url(supabase_url: str) -> str:
    value = supabase_url.rstrip("/")
    return value if value.endswith("/rest/v1") else f"{value}/rest/v1"


def iter_postgrest_rows(
    *,
    rest_url: str,
    table: str,
    select: str,
    service_role_key: str,
    page_size: int,
) -> Iterator[dict[str, Any]]:
    """Page through one PostgREST table using read-only GET requests."""

    offset = 0
    while True:
        query = urlencode(
            {
                "select": select,
                "order": "id.asc",
                "limit": str(page_size),
                "offset": str(offset),
            }
        )
        request = Request(
            f"{rest_url}/{table}?{query}",
            method="GET",
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-supplied URL
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MetadataBaselineError(
                f"PostgREST GET {table} failed with HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise MetadataBaselineError(f"PostgREST GET {table} failed: {exc}") from exc
        if not isinstance(payload, list):
            raise MetadataBaselineError(f"PostgREST {table} response is not an array")
        for row in payload:
            if not isinstance(row, dict):
                raise MetadataBaselineError(f"PostgREST {table} returned a non-object row")
            yield row
        if len(payload) < page_size:
            break
        offset += page_size


def export_records(
    *,
    rest_url: str,
    service_role_key: str,
    output: Path,
    include_content: bool,
    page_size: int,
    overwrite: bool,
) -> dict[str, object]:
    """Write a point-in-time JSONL export and return its redacted manifest."""

    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    ensure_outputs((output, manifest_path), overwrite=overwrite)
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {"document": 0, "chunk": 0}
    started_at = datetime.now(UTC)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            for row in iter_postgrest_rows(
                rest_url=rest_url,
                table="documents",
                select=DOCUMENT_SELECT,
                service_role_key=service_role_key,
                page_size=page_size,
            ):
                record = {
                    "record_type": "document",
                    "record_id": str(row["id"]),
                    "document_id": str(row["id"]),
                    **row,
                }
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                counts["document"] += 1
            for row in iter_postgrest_rows(
                rest_url=rest_url,
                table="document_chunks",
                select=(
                    CHUNK_SELECT_WITH_CONTENT if include_content else CHUNK_SELECT_WITHOUT_CONTENT
                ),
                service_role_key=service_role_key,
                page_size=page_size,
            ):
                chunk_id = str(row["id"])
                record = {
                    "record_type": "chunk",
                    "record_id": chunk_id,
                    "chunk_id": chunk_id,
                    **row,
                }
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                counts["chunk"] += 1
        temporary_path.replace(output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    origin = rest_url.split("/rest/v1", 1)[0]
    manifest: dict[str, object] = {
        "created_at": datetime.now(UTC).isoformat(),
        "started_at": started_at.isoformat(),
        "source": "Supabase PostgREST documents + document_chunks",
        "rest_origin_sha256": hashlib.sha256(origin.encode("utf-8")).hexdigest(),
        "document_count": counts["document"],
        "chunk_count": counts["chunk"],
        "content_included": include_content,
        "embedding_exported": False,
        "read_only_methods": ["GET"],
        "snapshot_consistency": "best-effort paginated export; not a database transaction",
    }
    write_json(manifest_path, manifest)
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--supabase-url-env", default="SUPABASE_URL")
    parser.add_argument("--service-role-key-env", default="SUPABASE_SERVICE_ROLE_KEY")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument(
        "--exclude-content",
        action="store_true",
        help="Omit chunk content; gold-sample context will then be unavailable",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if not 1 <= args.page_size <= 1000:
            raise MetadataBaselineError("--page-size must be between 1 and 1000")
        _load_dotenv(args.env_file)
        supabase_url = os.getenv(args.supabase_url_env, "").strip()
        service_role_key = os.getenv(args.service_role_key_env, "").strip()
        if not supabase_url or not service_role_key:
            raise MetadataBaselineError(
                "Supabase URL and service-role key must be configured through environment variables"
            )
        LOGGER.info("Starting read-only metadata export")
        manifest = export_records(
            rest_url=_rest_url(supabase_url),
            service_role_key=service_role_key,
            output=args.output,
            include_content=not args.exclude_content,
            page_size=args.page_size,
            overwrite=args.overwrite,
        )
        LOGGER.info(
            "Exported %s documents and %s chunks",
            manifest["document_count"],
            manifest["chunk_count"],
        )
    except MetadataBaselineError as exc:
        LOGGER.error("Metadata export failed: %s", exc)
        return 2
    except Exception:
        LOGGER.exception("Unexpected metadata export failure")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["export_records", "iter_postgrest_rows", "main"]
