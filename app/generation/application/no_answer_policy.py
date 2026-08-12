"""Versioned, security-safe user wording for deterministic P5 abstention."""

from __future__ import annotations

from app.generation.domain.evidence import NoAnswerReason

NO_ANSWER_POLICY_VERSION = "p5-no-answer-v1"

_MESSAGES = {
    NoAnswerReason.NO_RELEVANT_EVIDENCE: (
        "Chưa có đủ thông tin trong các tài liệu bạn được phép truy cập để trả lời câu hỏi này."
    ),
    NoAnswerReason.INSUFFICIENT_SCOPE: (
        "Bằng chứng hiện có chưa xác định phạm vi hoặc tiêu chuẩn đủ rõ để trả lời an toàn."
    ),
    NoAnswerReason.CONFLICT_UNRESOLVED: (
        "Các nguồn hiện có chưa thống nhất, nên chưa thể đưa ra một kết luận duy nhất."
    ),
    NoAnswerReason.CURRENT_VERSION_UNKNOWN: (
        "Các tài liệu có nhiều phiên bản, nhưng chưa đủ bằng chứng để xác định phiên bản nào "
        "đang có hiệu lực."
    ),
    NoAnswerReason.TEMPORAL_EVIDENCE_MISSING: (
        "Chưa có đủ bằng chứng cho khoảng thời gian được hỏi để thực hiện so sánh an toàn."
    ),
    NoAnswerReason.PERMISSION_FILTERED: (
        "Chưa có đủ thông tin trong các tài liệu bạn được phép truy cập để trả lời câu hỏi này."
    ),
    NoAnswerReason.LOW_CONFIDENCE_EVIDENCE: (
        "Bằng chứng hiện có chưa đủ chắc chắn để xác nhận câu trả lời."
    ),
}


def no_answer_message(reason: NoAnswerReason, *, follow_up: str | None = None) -> str:
    message = _MESSAGES[reason]
    return f"{message}\n\n{follow_up}" if follow_up else message


__all__ = ["NO_ANSWER_POLICY_VERSION", "no_answer_message"]
