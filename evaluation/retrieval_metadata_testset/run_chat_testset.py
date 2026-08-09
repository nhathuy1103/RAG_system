"""Run the test set through the app's /chat endpoint and export citations.

This measures end-to-end chat latency, not pure retrieval latency, because the
current public API returns citations with the generated answer.

Example:

    python evaluation/retrieval_metadata_testset/run_chat_testset.py \
      --api-url http://127.0.0.1:8000 \
      --bearer-token <supabase-user-access-token> \
      --notebook-id <notebook-uuid> \
      --output evaluation/retrieval_metadata_testset/retrieval_results.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_TESTSET = Path(__file__).resolve().parent / "testset.jsonl"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def post_chat(
    *,
    api_url: str,
    token: str,
    question: str,
    notebook_id: str,
    document_ids: list[str] | None,
    timeout: float,
) -> tuple[dict[str, Any], float]:
    payload = {
        "question": question,
        "notebook_id": notebook_id,
        "document_ids": document_ids,
        "conversation_id": None,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        api_url.rstrip("/") + "/chat",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    latency_ms = (time.perf_counter() - start) * 1000
    return json.loads(raw.decode("utf-8")), latency_ms


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-url", default=os.getenv("RAG_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--bearer-token", default=os.getenv("RAG_BEARER_TOKEN"))
    parser.add_argument("--notebook-id", default=os.getenv("RAG_NOTEBOOK_ID"))
    parser.add_argument("--document-ids", default=os.getenv("RAG_DOCUMENT_IDS"))
    parser.add_argument("--mode", default="chat_end_to_end")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.bearer_token:
        raise SystemExit("Missing --bearer-token or RAG_BEARER_TOKEN")
    if not args.notebook_id:
        raise SystemExit("Missing --notebook-id or RAG_NOTEBOOK_ID")

    document_ids = None
    if args.document_ids:
        document_ids = [value.strip() for value in args.document_ids.split(",") if value.strip()]

    cases = load_jsonl(args.testset)
    if args.limit is not None:
        cases = cases[: args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for index, case in enumerate(cases, start=1):
            print(f"[{index}/{len(cases)}] {case['id']}: {case['query']}")
            row: dict[str, Any] = {
                "test_id": case["id"],
                "mode": args.mode,
                "query": case["query"],
                "results": [],
            }
            try:
                response, latency_ms = post_chat(
                    api_url=args.api_url,
                    token=args.bearer_token,
                    question=case["query"],
                    notebook_id=args.notebook_id,
                    document_ids=document_ids,
                    timeout=args.timeout,
                )
                row["latency_ms"] = round(latency_ms, 2)
                row["answer"] = response.get("answer", "")
                row["conversation_id"] = response.get("conversation_id")
                row["results"] = response.get("citations", [])
            except urllib.error.HTTPError as exc:
                row["error"] = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
                if args.stop_on_error:
                    raise
            except Exception as exc:  # noqa: BLE001 - keep long batch running by default.
                row["error"] = repr(exc)
                if args.stop_on_error:
                    raise

            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
