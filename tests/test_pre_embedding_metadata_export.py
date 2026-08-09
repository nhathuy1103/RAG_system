from __future__ import annotations

from evaluation.retrieval_metadata_testset.export_pre_embedding_metadata import (
    LLM_CONTEXT_FIELDS,
    build_preview_row,
)


def test_preview_uses_deterministic_header_and_removes_llm_context() -> None:
    row = build_preview_row(
        {
            "chunk_id": "chunk-1",
            "chunk_index": 1,
            "document_id": "document-1",
            "document_title": "policy.docx",
            "page_number": 3,
            "text": "Employees submit receipts within five days.",
            "current_metadata": {
                "title": "policy.docx",
                "document_type": "policy",
                "section_title": "Expenses",
                "section_path": ["Finance", "Expenses"],
                "content_kind": "paragraph",
                "contextual_summary": "Generated summary.",
                "contextual_search_terms": ["generated"],
                "context_enrichment": {"status": "generated"},
                "domain": "finance",
            },
            "provenance": {"source_block_ids": ["block-1"]},
            "security": {"visibility": "internal"},
        }
    )

    metadata = row["metadata"]["retrieval_metadata"]
    assert not LLM_CONTEXT_FIELDS.intersection(metadata)
    assert metadata["domain"] == "finance"
    assert row["embedding_text"].startswith(
        "Document: policy\nDocument type: policy\nSection: Finance > Expenses\n\n"
    )
    assert "Context:" not in row["embedding_text"]
    assert row["policy"]["contextual_enrichment_enabled"] is False
