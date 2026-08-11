"""OpenAI-backed answer generator: closed-book synthesis with inline citations.

Evidence receives short, turn-local aliases such as ``SRC-1`` before it is
shown to the model. The alias keeps internal chunk UUIDs out of generated text
and avoids models shortening or corrupting long identifiers. Literal markers
remain in the stream so the frontend can replace them with clickable ``[N]``
references while citation events carry the matching alias and evidence.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any

from app.generation.application.citation_validation import build_evidence_aliases
from app.generation.domain import CitationHit, GenerationEvent, TokenChunk, UsageInfo
from app.infrastructure.telemetry import Telemetry
from app.knowledge_quality.application.analysis import detect_conflicts
from app.retrieval.domain.models import RetrievalCandidate

_SOURCE_REFERENCE_PATTERN = re.compile(r"\[(SRC-\d+)\]")

_CONFLICT_INSTRUCTION = (
    "Nếu các nguồn mâu thuẫn nhau về cùng một sự việc, phải nêu rõ điều đó "
    "trong câu trả lời và trích dẫn cả hai nguồn liên quan; không được tự ý "
    "chọn một bên và bỏ qua bên còn lại."
)

_CLOSED_BOOK_SYSTEM_PROMPT = (
    "Bạn là trợ lý trả lời câu hỏi dựa HOÀN TOÀN vào các nguồn tài liệu được "
    "cung cấp bên dưới, không dùng kiến thức nền của bạn. Nếu các nguồn không "
    "đủ để trả lời, hãy nói rõ là bạn không tìm thấy thông tin thay vì đoán. "
    "Mỗi khi dùng thông tin từ một nguồn, hãy chèn ngay sau đó ký hiệu "
    "[SRC-<số>] đúng như nhãn ngắn trong danh sách nguồn; không rút gọn hoặc thay đổi nhãn. "
    f"{_CONFLICT_INSTRUCTION} "
    "Trả lời bằng tiếng Việt, định dạng Markdown. Với công thức toán học, chỉ dùng "
    "$...$ cho công thức nội tuyến và $$...$$ cho công thức riêng dòng; không dùng "
    "\\(...\\) hoặc \\[...\\]."
)

_OPEN_BOOK_SYSTEM_PROMPT = (
    "Bạn là trợ lý trả lời câu hỏi, ưu tiên dùng các nguồn tài liệu được cung "
    "cấp bên dưới. Nếu các nguồn không đủ để trả lời, bạn có thể bổ sung bằng "
    "kiến thức nền của mình, nhưng phải nói rõ phần nào đến từ nguồn và phần "
    "nào là kiến thức chung. Mỗi khi dùng thông tin từ một nguồn, hãy chèn "
    "ngay sau đó ký hiệu [SRC-<id>] với <id> là mã nguồn chính xác như trong "
    f"danh sách nguồn. {_CONFLICT_INSTRUCTION} "
    "Trả lời bằng tiếng Việt, định dạng Markdown."
)


class OpenAIAnswerGenerator:
    """Streams a chat completion, surfacing citations as they're referenced."""

    def __init__(
        self,
        *,
        client: Any,
        model: str,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        allow_outside_knowledge: bool = False,
        conflict_annotations_enabled: bool = True,
        telemetry: Telemetry | None = None,
    ) -> None:
        if not model:
            raise ValueError("OpenAI chat model must not be empty.")
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._conflict_annotations_enabled = conflict_annotations_enabled
        self._telemetry = telemetry or Telemetry()
        selected_prompt = (
            _OPEN_BOOK_SYSTEM_PROMPT if allow_outside_knowledge else _CLOSED_BOOK_SYSTEM_PROMPT
        )
        self._system_prompt = (
            selected_prompt
            if conflict_annotations_enabled
            else selected_prompt.replace(f"{_CONFLICT_INSTRUCTION} ", "")
        )

    async def stream(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalCandidate, ...],
    ) -> AsyncIterator[GenerationEvent]:
        evidence_by_alias = build_evidence_aliases(evidence)
        evidence_trace_metadata = _evidence_trace_metadata(evidence)
        conflict_alias_pairs = (
            _conflict_alias_pairs(evidence_by_alias) if self._conflict_annotations_enabled else ()
        )
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": _build_user_prompt(
                    question,
                    evidence_by_alias,
                    include_conflict_notice=self._conflict_annotations_enabled,
                ),
            },
        ]
        create_kwargs: dict[str, Any] = {}
        if self._max_output_tokens is not None:
            create_kwargs["max_tokens"] = self._max_output_tokens
        with self._telemetry.observe(
            "generation.answer",
            as_type="chain",
            input={
                "messages": self._telemetry.content(messages),
                "question_length": len(question),
                "evidence": [
                    {
                        "source_id": source_id,
                        "chunk_id": candidate.chunk.id,
                        "document_id": candidate.chunk.document_id,
                        "score": candidate.score,
                        "text": self._telemetry.content(candidate.chunk.text),
                    }
                    for source_id, candidate in evidence_by_alias.items()
                ],
            },
            metadata={
                "evidence_count": len(evidence),
                **evidence_trace_metadata,
            },
            model=self._model,
            model_parameters={
                "temperature": self._temperature,
                "max_output_tokens": self._max_output_tokens,
                "stream": True,
            },
        ) as observation:
            langfuse_kwargs = self._telemetry.openai_call_attributes(
                "generate-answer",
                metadata={
                    "evidence_count": len(evidence),
                    "conflict_pair_count": len(conflict_alias_pairs),
                    **evidence_trace_metadata,
                },
            )
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
                temperature=self._temperature,
                stream_options={"include_usage": True},
                **langfuse_kwargs,
                **create_kwargs,
            )

            buffer = ""
            emitted: set[str] = set()
            input_tokens: int | None = None
            output_tokens: int | None = None
            first_token_seen = False
            enforced_conflict_citations = 0
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    input_tokens = usage.prompt_tokens
                    output_tokens = usage.completion_tokens
                    yield UsageInfo(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    continue

                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = choices[0].delta.content
                if not delta:
                    continue

                if not first_token_seen:
                    first_token_seen = True
                    observation.update(completion_start_time=datetime.now(UTC))
                buffer += delta
                yield TokenChunk(text=delta)

                for match in _SOURCE_REFERENCE_PATTERN.finditer(buffer):
                    source_id = match.group(1)
                    if source_id in emitted:
                        continue
                    candidate = evidence_by_alias.get(source_id)
                    if candidate is None:
                        continue
                    emitted.add(source_id)
                    yield CitationHit(
                        source_id=source_id,
                        ordinal=len(emitted),
                        candidate=candidate,
                    )

            missing_conflict_aliases = tuple(
                dict.fromkeys(
                    alias for pair in conflict_alias_pairs for alias in pair if alias not in emitted
                )
            )
            if missing_conflict_aliases:
                conflict_lines = "\n".join(
                    f"- [{left}] ↔ [{right}]" for left, right in conflict_alias_pairs
                )
                fallback = (
                    "\n\n> ⚠️ **Nguồn mâu thuẫn:** Cần đối chiếu cả hai phía; "
                    "hệ thống không tự chọn hoặc hợp nhất các phát biểu sau:\n"
                    f"{conflict_lines}"
                )
                buffer += fallback
                yield TokenChunk(text=fallback)
                for source_id in missing_conflict_aliases:
                    candidate = evidence_by_alias[source_id]
                    emitted.add(source_id)
                    enforced_conflict_citations += 1
                    yield CitationHit(
                        source_id=source_id,
                        ordinal=len(emitted),
                        candidate=candidate,
                    )

            observation.update(
                output={
                    "answer": self._telemetry.content(buffer),
                    "citation_source_ids": sorted(emitted),
                    "conflict_pair_count": len(conflict_alias_pairs),
                    "enforced_conflict_citation_count": enforced_conflict_citations,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )


_TRACEABLE_RETRIEVAL_METADATA_FIELDS = (
    "document_type",
    "category",
    "domain",
    "project_code",
    "department_code",
    "year",
    "effective_at",
    "content_kind",
    "language",
)


def _evidence_trace_metadata(
    evidence: tuple[RetrievalCandidate, ...],
) -> dict[str, object]:
    """Summarize evidence identity and canonical metadata without chunk text."""

    document_ids = sorted({candidate.chunk.document_id for candidate in evidence})
    chunk_ids = [candidate.chunk.id for candidate in evidence]
    version_ids: set[str] = set()
    observed_fields: set[str] = set()
    canonical_values: dict[str, set[str]] = {
        field_name: set() for field_name in _TRACEABLE_RETRIEVAL_METADATA_FIELDS
    }
    for candidate in evidence:
        metadata = candidate.chunk.typed_metadata
        version_id = metadata.text("document_version_id")
        if version_id:
            version_ids.add(version_id)
        nested = metadata.get("retrieval_metadata")
        retrieval_metadata = nested if isinstance(nested, Mapping) else metadata
        observed_fields.update(str(key) for key in retrieval_metadata)
        for field_name in _TRACEABLE_RETRIEVAL_METADATA_FIELDS:
            value = retrieval_metadata.get(field_name)
            if value in (None, "") or isinstance(value, dict | list):
                continue
            canonical_values[field_name].add(str(value))

    trace_metadata: dict[str, object] = {
        "evidence_document_ids": ",".join(document_ids) or "none",
        "evidence_document_version_ids": ",".join(sorted(version_ids)) or "none",
        "evidence_chunk_ids": ",".join(chunk_ids) or "none",
        "retrieval_metadata_fields": ",".join(sorted(observed_fields)) or "none",
    }
    for field_name, values in canonical_values.items():
        if values:
            trace_metadata[f"evidence_{field_name}"] = ",".join(sorted(values))
    return trace_metadata


def _build_user_prompt(
    question: str,
    evidence_by_alias: dict[str, RetrievalCandidate],
    *,
    include_conflict_notice: bool = True,
) -> str:
    blocks = [
        f"[{source_id}]\n{candidate.chunk.text}"
        for source_id, candidate in evidence_by_alias.items()
    ]
    sources = "\n\n".join(blocks) if blocks else "(không có nguồn nào)"
    conflict_notice = ""
    if include_conflict_notice:
        aliases = tuple(evidence_by_alias)
        conflicts = detect_conflicts(
            tuple(evidence_by_alias[alias].chunk.text for alias in aliases)
        )
        lines = [
            (
                f"- [{aliases[item.left_index]}] <-> "
                f"[{aliases[item.right_index]}]: "
                f"{','.join(item.analysis.reason_codes)} "
                f"(confidence={item.analysis.confidence:.2f})"
            )
            for item in conflicts
        ]
        detected_pairs = {
            tuple(sorted((aliases[item.left_index], aliases[item.right_index])))
            for item in conflicts
        }
        structured_pairs = _structured_conflict_alias_pairs(evidence_by_alias)
        lines.extend(
            f"- [{left}] <-> [{right}]: structured_claim_relation"
            for left, right in structured_pairs
            if (left, right) not in detected_pairs
        )
        signaled_pairs = detected_pairs | set(structured_pairs)
        lines.extend(
            f"- [{left}] <-> [{right}]: confirmed_document_relation"
            for left, right in _confirmed_conflict_alias_pairs(evidence_by_alias)
            if (left, right) not in signaled_pairs
        )
        if lines:
            conflict_notice = (
                "\n\nSYSTEM CONFLICT SIGNALS (do not silently reconcile):\n" + "\n".join(lines)
            )
    return f"Các nguồn:\n\n{sources}{conflict_notice}\n\nCâu hỏi: {question}"


def _conflict_alias_pairs(
    evidence_by_alias: dict[str, RetrievalCandidate],
) -> tuple[tuple[str, str], ...]:
    aliases = tuple(evidence_by_alias)
    pairs = list(_structured_conflict_alias_pairs(evidence_by_alias))
    pairs.extend(
        pair for pair in _confirmed_conflict_alias_pairs(evidence_by_alias) if pair not in pairs
    )
    seen = set(pairs)
    conflicts = detect_conflicts(tuple(evidence_by_alias[alias].chunk.text for alias in aliases))
    for item in conflicts:
        sorted_aliases = sorted((aliases[item.left_index], aliases[item.right_index]))
        pair = (sorted_aliases[0], sorted_aliases[1])
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)
    return tuple(pairs)


def _structured_conflict_alias_pairs(
    evidence_by_alias: dict[str, RetrievalCandidate],
) -> tuple[tuple[str, str], ...]:
    """Pair exact claim sources that share one unresolved conflict relation."""

    aliases_by_relation: dict[str, list[str]] = {}
    for alias, candidate in evidence_by_alias.items():
        warnings = candidate.chunk.metadata.get("structured_relation_warnings")
        if not isinstance(warnings, list | tuple):
            continue
        for warning in warnings:
            if not isinstance(warning, Mapping):
                continue
            relation_type = str(warning.get("relation_type") or "").strip().casefold()
            review_status = str(warning.get("review_status") or "").strip().casefold()
            relation_id = str(warning.get("relation_id") or "").strip()
            if (
                relation_type not in {"conflict", "conflict_candidate"}
                or review_status == "dismissed"
                or not relation_id
            ):
                continue
            relation_aliases = aliases_by_relation.setdefault(relation_id, [])
            if alias not in relation_aliases:
                relation_aliases.append(alias)

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for aliases in aliases_by_relation.values():
        for left_index, left in enumerate(aliases):
            for right in aliases[left_index + 1 :]:
                sorted_aliases = sorted((left, right))
                pair = (sorted_aliases[0], sorted_aliases[1])
                if pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)
    return tuple(pairs)


def _confirmed_conflict_alias_pairs(
    evidence_by_alias: dict[str, RetrievalCandidate],
) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    aliases_by_document: dict[str, list[str]] = {}
    for alias, candidate in evidence_by_alias.items():
        aliases_by_document.setdefault(candidate.chunk.document_id, []).append(alias)
    for alias, candidate in evidence_by_alias.items():
        raw_peers = (
            candidate.chunk.typed_metadata.text("confirmed_conflict_peer_document_ids") or ""
        )
        for peer_document_id in raw_peers.split(","):
            peer_document_id = peer_document_id.strip()
            if not peer_document_id:
                continue
            for peer_alias in aliases_by_document.get(peer_document_id, ()):
                sorted_aliases = sorted((alias, peer_alias))
                pair = (sorted_aliases[0], sorted_aliases[1])
                if pair[0] != pair[1] and pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)
    return tuple(pairs)


__all__ = ["OpenAIAnswerGenerator"]
