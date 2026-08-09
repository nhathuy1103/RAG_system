from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from app.pipeline.indexing.adapters.context_enrichers import (
    OpenAIChunkContextEnricher,
    OpenAIChunkContextEnricherConfig,
)
from app.pipeline.indexing.domain.context_enrichment import (
    ChunkContextEnrichmentRequest,
    select_context_scope_metadata,
)


class FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, FakeModelResponse):
            content = response.content
            finish_reason = response.finish_reason
        else:
            if not isinstance(response, str):
                raise TypeError("Fake response must be a string or FakeModelResponse")
            content = response
            finish_reason = "stop"
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason=finish_reason,
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=30),
        )


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


@dataclass(frozen=True)
class FakeModelResponse:
    content: str
    finish_reason: str = "stop"


def _request() -> ChunkContextEnrichmentRequest:
    return ChunkContextEnrichmentRequest(
        document_title="Chinh sach cong tac",
        document_type="policy",
        language="vi",
        section_title="Luu tru",
        section_path=("Chi phi", "Luu tru"),
        content_kind="paragraph",
        table_header=None,
        document_outline="Chi phi\nChi phi > Luu tru",
        document_excerpt="Quy dinh ISO 27001 ap dung cho chi phi luu tru tai Bangkok.",
        chunk_text="Muc toi da duoc phe duyet la 120 USD.",
        scope_metadata=(
            ("document_version", "3"),
            ("data_period", "2026"),
            ("region", "Bangkok"),
            ("currency", "USD"),
        ),
    )


def _config(**overrides: object) -> OpenAIChunkContextEnricherConfig:
    values: dict[str, object] = {
        "max_retries": 0,
        "retry_backoff_seconds": 0,
    }
    values.update(overrides)
    return OpenAIChunkContextEnricherConfig(**values)  # type: ignore[arg-type]


def test_generates_grounded_context_and_caches_by_input() -> None:
    client = FakeClient(
        [
            json.dumps(
                {
                    "context": (
                        "ISO 27001 governs this lodging allowance for travel in Bangkok."
                    ),
                    "needs_context": True,
                    "quality_flags": [],
                }
            )
        ]
    )
    enricher = OpenAIChunkContextEnricher(client=client, config=_config())

    first = enricher.enrich(_request())
    second = enricher.enrich(_request())

    assert first == second
    assert first.status == "generated"
    assert first.search_terms == ()
    assert first.needs_context is True
    assert len(client.completions.calls) == 1
    call = client.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["max_tokens"] == 400
    payload = json.loads(call["messages"][1]["content"])
    assert payload["scope_metadata"] == {
        "currency": "USD",
        "data_period": "2026",
        "document_version": "3",
        "region": "Bangkok",
    }
    assert payload["max_context_words"] == 45
    assert payload["source_scope"] == "bounded_context_package"
    assert "max_search_terms" not in payload
    system_prompt = call["messages"][0]["content"]
    assert 'Set "needs_context" to false' in system_prompt
    assert "Never add search terms" in system_prompt
    assert not {
        "document_id",
        "owner_id",
        "tenant_id",
        "access_level",
        "allowed_groups",
        "page_number",
        "content_hash",
    }.intersection(payload)


def test_scope_metadata_is_whitelisted_and_never_contains_acl_fields() -> None:
    selected = select_context_scope_metadata(
        {
            "document_version": 4,
            "owner_id": "owner-secret",
            "visibility": "restricted",
            "retrieval_metadata": {
                "year": 2026,
                "project_name": "Vinhomes Smart City",
                "allowed_groups": ["admin"],
            },
        }
    )

    assert selected == (
        ("document_version", "4"),
        ("year", "2026"),
        ("project_name", "Vinhomes Smart City"),
    )


def test_accepts_numeric_scope_claim_when_number_is_supplied_by_metadata() -> None:
    response = json.dumps(
        {
            "context": (
                "Hạn mức lưu trú áp dụng trong kỳ 2026 theo phiên bản 3."
            ),
            "needs_context": True,
            "quality_flags": [],
        }
    )
    enricher = OpenAIChunkContextEnricher(
        client=FakeClient([response]),
        config=_config(),
    )

    result = enricher.enrich(_request())

    assert result.status == "generated"
    assert result.context_text is not None


def test_accepts_semantic_context_without_repeating_document_or_section() -> None:
    response = json.dumps(
        {
            "context": "ISO 27001 governs this lodging allowance.",
            "needs_context": True,
            "quality_flags": [],
        }
    )
    enricher = OpenAIChunkContextEnricher(
        client=FakeClient([response]),
        config=_config(),
    )

    result = enricher.enrich(_request())

    assert result.status == "generated"
    assert result.context_text == "ISO 27001 governs this lodging allowance."
    assert len(enricher.client.completions.calls) == 1


def test_fallback_warning_includes_validation_detail(caplog: pytest.LogCaptureFixture) -> None:
    response = json.dumps(
        {
            "context": "Noi dung thuoc muc Luu tru va neu muc toi da 999 USD.",
            "needs_context": True,
            "quality_flags": [],
        }
    )
    enricher = OpenAIChunkContextEnricher(
        client=FakeClient([response]),
        config=_config(),
    )
    caplog.set_level(
        logging.WARNING,
        logger="app.pipeline.indexing.adapters.context_enrichers",
    )

    result = enricher.enrich(_request())

    assert result.status == "fallback"
    assert "detail=Context enrichment introduced unsupported numeric claims" in caplog.text


def test_retries_validation_failure_with_a_corrective_message() -> None:
    client = FakeClient(
        [
            json.dumps(
                {
                    "context": "Noi dung quy dinh muc toi da 999 USD.",
                    "needs_context": True,
                    "quality_flags": [],
                }
            ),
            json.dumps(
                {
                    "context": "ISO 27001 governs this lodging allowance.",
                    "needs_context": True,
                    "quality_flags": [],
                }
            ),
        ]
    )
    enricher = OpenAIChunkContextEnricher(
        client=client,
        config=_config(max_retries=1),
    )

    result = enricher.enrich(_request())

    assert result.status == "generated"
    assert len(client.completions.calls) == 2
    repair_message = client.completions.calls[1]["messages"][-1]["content"]
    assert "failed validation" in repair_message
    assert "unsupported numeric claims" in repair_message
    assert "45 words or fewer" in repair_message


def test_word_limit_failure_retries_with_shorter_target() -> None:
    overlong_response = json.dumps(
        {
            "context": " ".join(["word"] * 46) + ".",
            "needs_context": True,
            "quality_flags": [],
        }
    )
    client = FakeClient(
        [
            overlong_response,
            json.dumps(
                {
                    "context": "ISO 27001 governs this lodging allowance.",
                    "needs_context": True,
                    "quality_flags": [],
                }
            ),
        ]
    )
    enricher = OpenAIChunkContextEnricher(
        client=client,
        config=_config(max_retries=1),
    )

    result = enricher.enrich(_request())

    assert result.status == "generated"
    repair_message = client.completions.calls[1]["messages"][-1]["content"]
    assert "target 35 words or fewer" in repair_message
    assert "hard limit is 45 words" in repair_message
    previous_response = client.completions.calls[1]["messages"][-2]
    assert previous_response == {"role": "assistant", "content": overlong_response}
    assert "Revise the assistant JSON immediately above" in repair_message


def test_multi_sentence_failure_retries_with_stricter_sentence_constraint() -> None:
    client = FakeClient(
        [
            json.dumps(
                {
                    "context": "First sentence. Second sentence.",
                    "needs_context": True,
                    "quality_flags": [],
                }
            ),
            json.dumps(
                {
                    "context": "ISO 27001 governs this lodging allowance.",
                    "needs_context": True,
                    "quality_flags": [],
                }
            ),
        ]
    )
    enricher = OpenAIChunkContextEnricher(
        client=client,
        config=_config(max_retries=1),
    )

    result = enricher.enrich(_request())

    assert result.status == "generated"
    repair_message = client.completions.calls[1]["messages"][-1]["content"]
    assert "target 35 words or fewer" in repair_message
    assert "exactly one terminal punctuation mark" in repair_message
    assert "periods in abbreviations" in repair_message


def test_retries_truncated_output_with_validation_feedback() -> None:
    client = FakeClient(
        [
            FakeModelResponse(
                content='{"needs_context":true,"context":"unfinished',
                finish_reason="length",
            ),
            json.dumps(
                {
                    "context": "ISO 27001 governs this lodging allowance.",
                    "needs_context": True,
                    "quality_flags": [],
                }
            ),
        ]
    )
    enricher = OpenAIChunkContextEnricher(
        client=client,
        config=_config(max_retries=1),
    )

    result = enricher.enrich(_request())

    assert result.status == "generated"
    assert len(client.completions.calls) == 2
    assert "truncated at 400 tokens" in client.completions.calls[1]["messages"][-1]["content"]
    assert "45 words or fewer" in client.completions.calls[1]["messages"][-1]["content"]


def test_retries_provider_failure_then_returns_generated_context() -> None:
    client = FakeClient(
        [
            RuntimeError("temporary provider failure"),
            json.dumps(
                {
                    "context": "ISO 27001 governs this lodging allowance.",
                    "needs_context": True,
                    "quality_flags": [],
                }
            ),
        ]
    )
    enricher = OpenAIChunkContextEnricher(
        client=client,
        config=_config(max_retries=1),
    )

    result = enricher.enrich(_request())

    assert result.status == "generated"
    assert len(client.completions.calls) == 2


def test_fail_open_rejects_unsupported_number_and_caches_fallback() -> None:
    response = json.dumps(
        {
            "context": "Noi dung quy dinh muc toi da 999 USD.",
            "needs_context": True,
            "quality_flags": [],
        }
    )
    client = FakeClient([response])
    enricher = OpenAIChunkContextEnricher(client=client, config=_config())

    first = enricher.enrich(_request())
    second = enricher.enrich(_request())

    assert first == second
    assert first.status == "fallback"
    assert first.context_text is None
    assert first.error_code == "ContextResponseValidationError"
    assert len(client.completions.calls) == 1


@pytest.mark.parametrize(
    "context",
    [
        "Câu ngữ cảnh chưa hoàn chỉnh",
        "Đoạn này thuộc tài liệu chính sách và mô tả điều khoản.",
        "Ngữ cảnh được lấy từ policy.pdf để mô tả điều khoản.",
        "Điều khoản áp dụng tại Page 14 của hồ sơ.",
        "Câu thứ nhất hoàn chỉnh. Câu thứ hai không được phép.",
        " ".join(["ngữ"] * 46) + ".",
    ],
)
def test_rejects_context_that_is_not_safe_to_index(context: str) -> None:
    response = json.dumps(
        {
            "context": context,
            "needs_context": True,
            "quality_flags": [],
        }
    )
    enricher = OpenAIChunkContextEnricher(
        client=FakeClient([response]),
        config=_config(max_retries=0),
    )

    result = enricher.enrich(_request())

    assert result.status == "fallback"
    assert result.context_text is None


def test_returns_not_needed_without_indexing_a_positioning_sentence() -> None:
    response = json.dumps(
        {
            "needs_context": False,
            "context": "",
            "quality_flags": [],
        }
    )
    client = FakeClient([response])
    enricher = OpenAIChunkContextEnricher(client=client, config=_config())

    first = enricher.enrich(_request())
    second = enricher.enrich(_request())

    assert first == second
    assert first.status == "not_needed"
    assert first.needs_context is False
    assert first.context_text is None
    assert len(client.completions.calls) == 1


def test_rejects_context_that_only_restates_chunk_and_headers() -> None:
    response = json.dumps(
        {
            "needs_context": True,
            "context": "Muc toi da duoc phe duyet la 120 USD.",
            "quality_flags": [],
        }
    )
    enricher = OpenAIChunkContextEnricher(
        client=FakeClient([response]),
        config=_config(),
    )

    result = enricher.enrich(_request())

    assert result.status == "fallback"
    assert result.error_code == "ContextResponseValidationError"


def test_marks_missing_source_evidence_as_fallback_without_indexing_context() -> None:
    response = json.dumps(
        {
            "needs_context": True,
            "context": "",
            "quality_flags": ["insufficient_evidence"],
        }
    )
    enricher = OpenAIChunkContextEnricher(
        client=FakeClient([response]),
        config=_config(),
    )

    result = enricher.enrich(_request())

    assert result.status == "fallback"
    assert result.needs_context is True
    assert result.quality_flags == ("insufficient_evidence",)
    assert result.error_code == "InsufficientContextEvidence"


def test_strict_mode_raises_after_invalid_schema() -> None:
    client = FakeClient([json.dumps({"context": "Valid text", "extra": "not allowed"})])
    enricher = OpenAIChunkContextEnricher(
        client=client,
        config=_config(strict=True),
    )

    with pytest.raises(RuntimeError, match="Chunk context enrichment failed"):
        enricher.enrich(_request())
