from __future__ import annotations

from app.retrieval.adapters.local_reformulation import FallbackQueryReformulator
from app.retrieval.adapters.local_sufficiency import KeywordOverlapSufficiencyChecker
from app.retrieval.application.agentic_retrieval import AgenticRetrievalUseCase
from app.retrieval.application.handle_retrieval_request import (
    ClarificationNeeded,
    FixedAnswer,
    RetrievalRequestHandler,
)
from app.retrieval.domain.models import (
    AdaptiveDecision,
    AgenticRetrievalResult,
    ContextualizedQuestion,
    RetrievalFilters,
)

FILTERS = RetrievalFilters(owner_id="user-1")


class FakeContextualizer:
    def __init__(self, result: ContextualizedQuestion) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def contextualize(self, message, history):
        self.calls.append((message, history))
        return self.result


class FakeAdaptiveClassifier:
    def __init__(self, decision: AdaptiveDecision) -> None:
        self.decision = decision
        self.calls: list[str] = []

    def classify(self, question):
        self.calls.append(question)
        return self.decision


class NeverCalledRetrievalPort:
    def search(self, query, filters, *, top_k):
        raise AssertionError("retrieval must not run when ambiguous or fixed-answer")


def _handler(
    *, contextualizer, adaptive_classifier, retrieval_port=None
) -> RetrievalRequestHandler:
    agentic_retrieval = AgenticRetrievalUseCase(
        retrieval_port=retrieval_port or NeverCalledRetrievalPort(),
        sufficiency_checker=KeywordOverlapSufficiencyChecker(),
        reformulator=FallbackQueryReformulator(),
    )
    return RetrievalRequestHandler(
        contextualizer=contextualizer,
        adaptive_classifier=adaptive_classifier,
        agentic_retrieval=agentic_retrieval,
    )


def test_ambiguous_question_stops_before_adaptive_and_retrieval() -> None:
    contextualizer = FakeContextualizer(
        ContextualizedQuestion(
            resolved_question="cái đó giá bao nhiêu?",
            is_ambiguous=True,
            clarifying_question="Bạn đang hỏi về sản phẩm nào?",
        )
    )
    adaptive_classifier = FakeAdaptiveClassifier(AdaptiveDecision(needs_retrieval=True))
    handler = _handler(contextualizer=contextualizer, adaptive_classifier=adaptive_classifier)

    result = handler.handle(message="cái đó giá bao nhiêu?", history=(), filters=FILTERS, top_k=5)

    assert isinstance(result, ClarificationNeeded)
    assert result.clarifying_question == "Bạn đang hỏi về sản phẩm nào?"
    assert adaptive_classifier.calls == []


def test_fixed_answer_short_circuits_before_retrieval() -> None:
    contextualizer = FakeContextualizer(
        ContextualizedQuestion(resolved_question="Chào bạn", is_ambiguous=False)
    )
    adaptive_classifier = FakeAdaptiveClassifier(
        AdaptiveDecision(needs_retrieval=False, fixed_answer="Xin chào!")
    )
    handler = _handler(contextualizer=contextualizer, adaptive_classifier=adaptive_classifier)

    result = handler.handle(message="Chào bạn", history=(), filters=FILTERS, top_k=5)

    assert isinstance(result, FixedAnswer)
    assert result.answer == "Xin chào!"


def test_document_question_is_handed_off_to_agentic_retrieval() -> None:
    contextualizer = FakeContextualizer(
        ContextualizedQuestion(
            resolved_question="doanh thu quý 3 là bao nhiêu?", is_ambiguous=False
        )
    )
    adaptive_classifier = FakeAdaptiveClassifier(AdaptiveDecision(needs_retrieval=True))

    class EmptyRetrievalPort:
        def search(self, query, filters, *, top_k):
            return ()

    handler = _handler(
        contextualizer=contextualizer,
        adaptive_classifier=adaptive_classifier,
        retrieval_port=EmptyRetrievalPort(),
    )

    result = handler.handle(
        message="doanh thu quý 3 là bao nhiêu?", history=(), filters=FILTERS, top_k=5
    )

    assert isinstance(result, AgenticRetrievalResult)
