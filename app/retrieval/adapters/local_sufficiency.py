"""Deterministic heuristic sufficiency checker — placeholder for an LLM judge."""

from __future__ import annotations

from app.retrieval.adapters.keyword_matching import extract_keywords
from app.retrieval.domain.models import RetrievalCandidate, SufficiencyCheck


class KeywordOverlapSufficiencyChecker:
    """Sufficient once accumulated evidence covers enough of the question's keywords."""

    def __init__(self, *, min_overlap_ratio: float = 0.5) -> None:
        if not 0 < min_overlap_ratio <= 1:
            raise ValueError("min_overlap_ratio must be in (0, 1]")
        self.min_overlap_ratio = min_overlap_ratio

    def check(
        self,
        original_question: str,
        evidence: tuple[RetrievalCandidate, ...],
    ) -> SufficiencyCheck:
        question_keywords = extract_keywords(original_question)
        if not question_keywords:
            return SufficiencyCheck(
                sufficient=bool(evidence),
                reasoning="Câu hỏi không có từ khoá để so khớp; coi là đủ nếu có evidence.",
            )

        evidence_keywords: set[str] = set()
        for candidate in evidence:
            evidence_keywords |= extract_keywords(candidate.chunk.text)

        covered = question_keywords & evidence_keywords
        missing_keywords = question_keywords - evidence_keywords
        ratio = len(covered) / len(question_keywords)

        if ratio >= self.min_overlap_ratio:
            return SufficiencyCheck(
                sufficient=True,
                reasoning=f"Heuristic từ khoá: bao phủ {ratio:.0%} từ khoá câu hỏi gốc.",
            )
        return SufficiencyCheck(
            sufficient=False,
            missing=" ".join(sorted(missing_keywords)) or original_question,
            reasoning=f"Heuristic từ khoá: chỉ bao phủ {ratio:.0%} từ khoá câu hỏi gốc.",
        )


__all__ = ["KeywordOverlapSufficiencyChecker"]
