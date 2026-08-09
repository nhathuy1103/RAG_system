"""Heuristic Adaptive classifier — placeholder for an LLM/intent-model one."""

from __future__ import annotations

import re

from app.retrieval.domain.models import AdaptiveDecision

_CHITCHAT_MARKERS = (
    "chào",
    "hello",
    "hi",
    "hey",
    "cảm ơn",
    "cám ơn",
    "thank",
    "tạm biệt",
    "bye",
)
_SYSTEM_HELP_MARKERS = (
    "hướng dẫn",
    "làm sao để",
    "làm thế nào để",
    "cách dùng",
    "cách sử dụng",
    "how do i",
    "how to use",
)

_CHITCHAT_ANSWER = "Xin chào. Tôi có thể trả lời câu hỏi dựa trên tài liệu bạn đã tải lên."
_SYSTEM_HELP_ANSWER = "Bạn có thể tải tài liệu lên rồi đặt câu hỏi dựa trên nội dung đó."


class HeuristicAdaptiveClassifier:
    """Matches a small set of fixed surface patterns; everything else needs
    retrieval by default (fail toward retrieving, not toward answering
    ungrounded)."""

    def classify(self, question: str) -> AdaptiveDecision:
        normalized = question.strip().lower()

        if any(_contains_marker(normalized, marker) for marker in _CHITCHAT_MARKERS):
            return AdaptiveDecision(
                needs_retrieval=False,
                fixed_answer=_CHITCHAT_ANSWER,
                reasoning="Khớp mẫu xã giao (heuristic).",
            )

        if any(_contains_marker(normalized, marker) for marker in _SYSTEM_HELP_MARKERS):
            return AdaptiveDecision(
                needs_retrieval=False,
                fixed_answer=_SYSTEM_HELP_ANSWER,
                reasoning="Khớp mẫu hỏi về cách dùng hệ thống (heuristic).",
            )

        return AdaptiveDecision(
            needs_retrieval=True,
            reasoning="Không khớp mẫu xã giao/hệ thống nào; mặc định retrieve.",
        )


def _contains_marker(text: str, marker: str) -> bool:
    phrase = marker.strip()
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


__all__ = ["HeuristicAdaptiveClassifier"]
