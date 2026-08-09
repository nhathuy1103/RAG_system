"""Heuristic contextualizer — placeholder for an LLM-based one."""

from __future__ import annotations

from app.retrieval.adapters.keyword_matching import extract_keywords, tokenize_all
from app.retrieval.domain.models import ContextualizedQuestion

_REFERENCE_MARKERS = frozenset(
    {
        "đó",
        "này",
        "nó",
        "ấy",
        "vậy",
        "kia",
        "họ",
        "chúng",
        "that",
        "this",
        "it",
        "they",
    }
)

_DEFAULT_CLARIFYING_QUESTION = "Bạn có thể nói rõ hơn bạn đang hỏi về nội dung/tài liệu nào không?"


class HeuristicContextualizer:
    """Flags ambiguous only when leaning entirely on a dangling reference marker."""

    def contextualize(
        self,
        message: str,
        history: tuple[str, ...],
    ) -> ContextualizedQuestion:
        has_reference_marker = bool(tokenize_all(message) & _REFERENCE_MARKERS)
        concrete_keywords = extract_keywords(message) - _REFERENCE_MARKERS

        if not has_reference_marker:
            return ContextualizedQuestion(
                resolved_question=message,
                is_ambiguous=False,
                reasoning="Không có tham chiếu mơ hồ nào cần giải quyết.",
            )

        if concrete_keywords:
            return ContextualizedQuestion(
                resolved_question=message,
                is_ambiguous=False,
                reasoning=(
                    "Có tham chiếu nhưng câu vẫn còn từ khoá cụ thể; coi là đủ rõ để tiếp tục."
                ),
            )

        if history:
            merged = f"{message} (liên quan tới lượt trước: {history[-1]})"
            return ContextualizedQuestion(
                resolved_question=merged,
                is_ambiguous=False,
                reasoning=(
                    "Heuristic ghép với lượt hội thoại gần nhất; "
                    "không đảm bảo đúng ngữ nghĩa, chỉ là best-effort."
                ),
            )

        return ContextualizedQuestion(
            resolved_question=message,
            is_ambiguous=True,
            clarifying_question=_DEFAULT_CLARIFYING_QUESTION,
            reasoning=(
                "Có tham chiếu mơ hồ, không có từ khoá cụ thể, và không có "
                "lịch sử hội thoại để giải quyết."
            ),
        )


__all__ = ["HeuristicContextualizer"]
