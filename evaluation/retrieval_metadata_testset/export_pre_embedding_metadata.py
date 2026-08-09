"""Export the deterministic pre-embedding payload for manual inspection."""

# ruff: noqa: E501 - The generated HTML keeps CSS and JavaScript readable in place.

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.pipeline.shared.text_utils import compute_checksum_text, normalize_text  # noqa: E402
from app.shared.contextual_text import (  # noqa: E402
    CONTEXTUAL_TEXT_VERSION,
    ChunkContext,
    build_embedding_text,
    build_search_text,
)

DEFAULT_CORPUS = (
    SCRIPT_DIR
    / "runs"
    / "real-benchmark-v3-context-quality-v3-openai"
    / "corpus.jsonl"
)
DEFAULT_OUTPUT_DIR = DEFAULT_CORPUS.parent / "pre_embedding_metadata_preview"
LLM_CONTEXT_FIELDS = frozenset(
    {"context_enrichment", "contextual_search_terms", "contextual_summary"}
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            rows.append(value)
    return rows


def _without_llm_context(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if key not in LLM_CONTEXT_FIELDS}


def build_preview_row(source: dict[str, Any]) -> dict[str, Any]:
    retrieval_metadata = _without_llm_context(source.get("current_metadata"))
    header_metadata = {
        key: retrieval_metadata[key]
        for key in (
            "title",
            "document_type",
            "section_title",
            "section_path",
            "content_kind",
            "table_header",
        )
        if retrieval_metadata.get(key) not in (None, "", [], {})
    }
    content = str(source.get("text") or "").strip()
    context = ChunkContext.from_metadata(header_metadata)
    embedding_text = build_embedding_text(content, context)
    search_text = build_search_text(content, context)
    provenance = source.get("provenance")
    provenance = dict(provenance) if isinstance(provenance, dict) else {}
    security = source.get("security")
    security = dict(security) if isinstance(security, dict) else {}

    metadata = {
        "retrieval_metadata": retrieval_metadata,
        "page_number": source.get("page_number"),
        "source_block_ids": provenance.get("source_block_ids", []),
        "table_identity": provenance.get("table_identity"),
        "table_location": provenance.get("table_location"),
        "bbox": provenance.get("bbox", []),
        **security,
        "embedding_text": embedding_text,
        "search_text": search_text,
    }
    return {
        "schema_version": "pre-embedding-preview-v1",
        "policy": {
            "name": "deterministic_header",
            "contextual_enrichment_enabled": False,
            "contextual_text_version": CONTEXTUAL_TEXT_VERSION,
        },
        "document_id": str(source.get("document_id") or ""),
        "document_title": str(source.get("document_title") or ""),
        "chunk_id": str(source.get("chunk_id") or ""),
        "chunk_index": int(source.get("chunk_index") or 0),
        "page_number": source.get("page_number"),
        "content_kind": retrieval_metadata.get("content_kind"),
        "section_title": retrieval_metadata.get("section_title"),
        "embedding_text_checksum": compute_checksum_text(normalize_text(embedding_text)),
        "metadata": metadata,
        "embedding_text": embedding_text,
        "search_text": search_text,
        "chunk_text": content,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    documents = Counter(str(row["document_title"]) for row in rows)
    kinds = Counter(str(row["content_kind"] or "unknown") for row in rows)
    retrieval_rows = [row["metadata"]["retrieval_metadata"] for row in rows]
    metadata_fields = (
        "title",
        "document_type",
        "section_title",
        "section_path",
        "content_kind",
        "table_header",
        "keyword_aliases",
        "domain",
    )
    header_prefixes = (
        "Document:",
        "Document type:",
        "Section:",
        "Content type:",
        "Table header:",
        "Context:",
    )
    return {
        "policy": "deterministic_header",
        "contextual_enrichment_enabled": False,
        "contextual_text_version": CONTEXTUAL_TEXT_VERSION,
        "chunk_count": len(rows),
        "document_count": len(documents),
        "chunks_by_document": dict(sorted(documents.items())),
        "chunks_by_content_kind": dict(sorted(kinds.items())),
        "metadata_field_coverage": {
            field: sum(metadata.get(field) not in (None, "", [], {}) for metadata in retrieval_rows)
            for field in metadata_fields
        },
        "embedding_header_coverage": {
            prefix.removesuffix(":"): sum(
                any(line.startswith(prefix) for line in str(row["embedding_text"]).splitlines())
                for row in rows
            )
            for prefix in header_prefixes
        },
        "embedding_inputs_with_context_line": sum(
            "Context:" in str(row["embedding_text"]) for row in rows
        ),
        "metadata_rows_with_llm_context": sum(
            bool(
                LLM_CONTEXT_FIELDS
                & set(row["metadata"]["retrieval_metadata"])
            )
            for row in rows
        ),
    }


def _write_html(
    path: Path,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    payload = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    summary_payload = json.dumps(summary, ensure_ascii=False).replace("<", "\\u003c")
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pre-embedding metadata preview</title>
  <style>
    :root { color-scheme: light; font-family: Inter, Segoe UI, Arial, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #17202a; background: #f3f5f7; }
    header { padding: 18px 24px; color: white; background: #173f5f; }
    h1 { margin: 0 0 6px; font-size: 22px; letter-spacing: 0; }
    header p { margin: 0; color: #dce8f2; font-size: 14px; }
    .stats { display: flex; gap: 22px; padding: 12px 24px; background: #e6eef3; border-bottom: 1px solid #c5d2db; }
    .stat strong { display: block; font-size: 18px; }
    .stat span { color: #52616b; font-size: 12px; }
    .filters { display: grid; grid-template-columns: minmax(220px, 1fr) 280px 180px; gap: 10px; padding: 12px 16px; background: white; border-bottom: 1px solid #d5dce1; }
    input, select { width: 100%; min-height: 38px; padding: 8px 10px; border: 1px solid #aebbc4; border-radius: 4px; background: white; font: inherit; }
    main { display: grid; grid-template-columns: minmax(280px, 34%) 1fr; height: calc(100vh - 167px); }
    #list { overflow: auto; border-right: 1px solid #cbd5dc; background: white; }
    .row { width: 100%; padding: 11px 14px; border: 0; border-bottom: 1px solid #e1e6ea; border-radius: 0; text-align: left; background: white; cursor: pointer; }
    .row:hover, .row.active { background: #e9f3f5; }
    .row strong, .row span { display: block; overflow-wrap: anywhere; }
    .row strong { margin-bottom: 4px; font-size: 13px; }
    .row span { color: #61717c; font-size: 12px; }
    #detail { overflow: auto; padding: 18px 22px 32px; }
    #detail h2 { margin: 0 0 4px; font-size: 18px; letter-spacing: 0; overflow-wrap: anywhere; }
    #detail .meta { margin-bottom: 14px; color: #60717c; font-size: 13px; }
    .tabs { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; border-bottom: 1px solid #bdc9d1; }
    .tab { padding: 8px 12px; border: 0; border-bottom: 3px solid transparent; border-radius: 0; background: transparent; cursor: pointer; }
    .tab.active { color: #0b6477; border-color: #0b6477; font-weight: 700; }
    pre { margin: 0; padding: 15px; border: 1px solid #c8d3da; border-radius: 4px; background: white; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.55 Consolas, monospace; }
    .empty { padding: 24px; color: #62727d; }
    @media (max-width: 760px) {
      .filters { grid-template-columns: 1fr; }
      main { grid-template-columns: 1fr; height: auto; }
      #list { max-height: 38vh; border-right: 0; border-bottom: 1px solid #cbd5dc; }
      #detail { min-height: 55vh; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Pre-embedding metadata preview</h1>
    <p>Production policy: deterministic document and section header, contextual enrichment disabled.</p>
  </header>
  <section class="stats" id="stats"></section>
  <section class="filters">
    <input id="query" type="search" placeholder="Search document, section, chunk or metadata">
    <select id="document"><option value="">All documents</option></select>
    <select id="kind"><option value="">All content types</option></select>
  </section>
  <main>
    <nav id="list" aria-label="Chunks"></nav>
    <section id="detail"><div class="empty">Select a chunk to inspect.</div></section>
  </main>
  <script>
    const rows = __ROWS__;
    const summary = __SUMMARY__;
    const state = { filtered: rows, selected: null, tab: "metadata" };
    const tabs = [
      ["metadata", "Metadata"],
      ["embedding_text", "Embedding input"],
      ["search_text", "Search input"],
      ["chunk_text", "Chunk text"]
    ];
    const stats = document.getElementById("stats");
    stats.innerHTML = [
      [summary.chunk_count, "chunks"],
      [summary.document_count, "documents"],
      [summary.embedding_inputs_with_context_line, "Context: lines"],
      [summary.metadata_rows_with_llm_context, "LLM metadata rows"]
    ].map(([value, label]) => `<div class="stat"><strong>${value}</strong><span>${label}</span></div>`).join("");

    const documentSelect = document.getElementById("document");
    const kindSelect = document.getElementById("kind");
    [...new Set(rows.map(row => row.document_title))].sort().forEach(value => documentSelect.add(new Option(value, value)));
    [...new Set(rows.map(row => row.content_kind || "unknown"))].sort().forEach(value => kindSelect.add(new Option(value, value)));

    function label(row) {
      return `${row.document_title} | chunk ${row.chunk_index}`;
    }
    function searchable(row) {
      return `${label(row)} ${row.section_title || ""} ${JSON.stringify(row.metadata)}`.toLocaleLowerCase();
    }
    function renderList() {
      const list = document.getElementById("list");
      if (!state.filtered.length) {
        list.innerHTML = '<div class="empty">No matching chunks.</div>';
        renderDetail();
        return;
      }
      if (!state.filtered.includes(state.selected)) state.selected = state.filtered[0];
      list.innerHTML = state.filtered.map((row, index) => `
        <button class="row ${row === state.selected ? "active" : ""}" data-index="${index}">
          <strong>${escapeHtml(label(row))}</strong>
          <span>${escapeHtml(row.section_title || "No semantic section")} | ${escapeHtml(row.content_kind || "unknown")}</span>
        </button>`).join("");
      list.querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
        state.selected = state.filtered[Number(button.dataset.index)];
        renderList();
        renderDetail();
      }));
      renderDetail();
    }
    function renderDetail() {
      const detail = document.getElementById("detail");
      const row = state.selected;
      if (!row) {
        detail.innerHTML = '<div class="empty">Select a chunk to inspect.</div>';
        return;
      }
      const value = state.tab === "metadata" ? JSON.stringify(row.metadata, null, 2) : row[state.tab];
      detail.innerHTML = `
        <h2>${escapeHtml(label(row))}</h2>
        <div class="meta">page ${row.page_number ?? "n/a"} | ${escapeHtml(row.embedding_text_checksum)}</div>
        <div class="tabs">${tabs.map(([key, text]) => `<button class="tab ${state.tab === key ? "active" : ""}" data-tab="${key}">${text}</button>`).join("")}</div>
        <pre>${escapeHtml(value || "")}</pre>`;
      detail.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => {
        state.tab = button.dataset.tab;
        renderDetail();
      }));
    }
    function applyFilters() {
      const query = document.getElementById("query").value.trim().toLocaleLowerCase();
      const documentValue = documentSelect.value;
      const kindValue = kindSelect.value;
      state.filtered = rows.filter(row =>
        (!query || searchable(row).includes(query)) &&
        (!documentValue || row.document_title === documentValue) &&
        (!kindValue || (row.content_kind || "unknown") === kindValue)
      );
      renderList();
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[character]);
    }
    document.getElementById("query").addEventListener("input", applyFilters);
    documentSelect.addEventListener("change", applyFilters);
    kindSelect.addEventListener("change", applyFilters);
    renderList();
  </script>
</body>
</html>
"""
    path.write_text(
        template.replace("__ROWS__", payload).replace("__SUMMARY__", summary_payload),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = [build_preview_row(row) for row in _load_jsonl(args.corpus)]
    if not rows:
        raise SystemExit(f"No corpus rows found in {args.corpus}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary(rows)
    jsonl_path = args.output_dir / "pre_embedding_metadata.jsonl"
    summary_path = args.output_dir / "pre_embedding_metadata.summary.json"
    html_path = args.output_dir / "pre_embedding_metadata.html"
    _write_jsonl(jsonl_path, rows)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_html(html_path, rows, summary)
    print(f"Wrote {len(rows)} pre-embedding rows to {jsonl_path}")
    print(f"Wrote summary to {summary_path}")
    print(f"Wrote interactive preview to {html_path}")


if __name__ == "__main__":
    main()
