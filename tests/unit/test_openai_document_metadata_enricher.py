from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.pipeline.indexing.adapters.document_metadata_enrichers import (
    DOCUMENT_METADATA_PROMPT_VERSION,
    OpenAIDocumentMetadataEnricher,
    OpenAIDocumentMetadataEnricherConfig,
    normalize_metadata_value,
)
from app.pipeline.indexing.domain.document_metadata import (
    DocumentMetadataEnrichmentRequest,
    MetadataEvidenceBlock,
)


class FakeCompletions:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.responses.pop(0)),
                    finish_reason="stop",
                )
            ]
        )


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


def _request() -> DocumentMetadataEnrichmentRequest:
    return DocumentMetadataEnrichmentRequest(
        document_title="quy_dinh_116_2025.pdf",
        language="vi",
        missing_fields=("document_number", "project_code", "effective_from"),
        evidence_blocks=(
            MetadataEvidenceBlock(
                block_id="block-1",
                page_number=1,
                text="Số: QĐ-116/2025. Áp dụng cho dự án Alpha từ ngày 2025-03-01.",
            ),
        ),
    )


def test_structured_extraction_is_evidence_bound_unverified_and_cached() -> None:
    client = FakeClient(
        [
            json.dumps(
                {
                    "assertions": [
                        {
                            "field_name": "document_number",
                            "value": "QĐ-116/2025",
                            "confidence": 0.98,
                            "evidence": [
                                {
                                    "block_id": "block-1",
                                    "page": 1,
                                    "text": "Số: QĐ-116/2025",
                                }
                            ],
                        },
                        {
                            "field_name": "project_code",
                            "value": "ALPHA",
                            "confidence": 0.82,
                            "evidence": [
                                {
                                    "block_id": "block-1",
                                    "page": 1,
                                    "text": "dự án Alpha",
                                }
                            ],
                        },
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )
    enricher = OpenAIDocumentMetadataEnricher(client=client)

    first = enricher.enrich(_request())
    second = enricher.enrich(_request())

    assert first == second
    assert len(client.completions.calls) == 1
    assert [item.field_name for item in first.assertions] == [
        "document_number",
        "project_code",
    ]
    assert all(item.source == "llm_inferred" for item in first.assertions)
    assert all(item.verified is False for item in first.assertions)
    assert first.assertions[0].confidence == 0.89
    assert first.assertions[0].normalized_value == "qd1162025"
    assert first.assertions[0].input_checksum == first.input_checksum
    call = client.completions.calls[0]
    assert "Bạn" in call["messages"][0]["content"]
    assert "bằng chứng" in call["messages"][0]["content"]
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    assert DOCUMENT_METADATA_PROMPT_VERSION in first.assertions[0].prompt_version


def test_unsupported_evidence_quote_fails_open_without_persistable_assertions() -> None:
    response = json.dumps(
        {
            "assertions": [
                {
                    "field_name": "project_code",
                    "value": "BETA",
                    "confidence": 0.8,
                    "evidence": [
                        {
                            "block_id": "block-1",
                            "page": 1,
                            "text": "dự án Beta",
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )
    enricher = OpenAIDocumentMetadataEnricher(client=FakeClient([response]))

    result = enricher.enrich(_request())

    assert result.status == "fallback"
    assert result.assertions == ()


def test_strict_mode_rejects_an_assertion_for_a_nonrequested_field() -> None:
    response = json.dumps(
        {
            "assertions": [
                {
                    "field_name": "domain",
                    "value": "finance",
                    "confidence": 0.8,
                    "evidence": [
                        {
                            "block_id": "block-1",
                            "page": 1,
                            "text": "dự án Alpha",
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )
    enricher = OpenAIDocumentMetadataEnricher(
        client=FakeClient([response]),
        config=OpenAIDocumentMetadataEnricherConfig(strict=True),
    )

    with pytest.raises(RuntimeError, match="metadata enrichment failed"):
        enricher.enrich(_request())


def test_new_retrieval_fields_are_normalized_deterministically() -> None:
    assert normalize_metadata_value("year", "2026") == "2026"
    assert normalize_metadata_value("data_period", "Q3/2026") == "Q3-2026"
    assert normalize_metadata_value("project_name", "Vinhomes Ocean Park 3") == (
        "Vinhomes Ocean Park 3"
    )
    with pytest.raises(ValueError, match="between 1900 and 2100"):
        normalize_metadata_value("year", "2200")
