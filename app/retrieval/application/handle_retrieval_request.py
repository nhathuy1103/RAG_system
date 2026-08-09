"""Top-level entry point composing SPEC steps ①-⑤ with the agentic retrieval loop (⑥-⑬)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.infrastructure.telemetry import Telemetry
from app.retrieval.application.agentic_retrieval import AgenticRetrievalUseCase
from app.retrieval.application.metadata_filter_planner import (
    DeterministicMetadataFilterPlanner,
)
from app.retrieval.domain.models import AgenticRetrievalResult, RetrievalFilters
from app.retrieval.ports.adaptive_port import AdaptiveClassifierPort
from app.retrieval.ports.contextualization_port import ContextualizerPort

_DEFAULT_CLARIFYING_QUESTION = "Bạn có thể nói rõ hơn câu hỏi của mình không?"
_DEFAULT_FIXED_ANSWER = "Mình chưa có câu trả lời soạn sẵn cho yêu cầu này."


@dataclass(frozen=True)
class ClarificationNeeded:
    """Outcome when the message is too ambiguous to retrieve — SPEC step ③."""

    clarifying_question: str
    reasoning: str | None = None


@dataclass(frozen=True)
class FixedAnswer:
    """Outcome when Adaptive (④) decides no retrieval is needed — SPEC step ⑤."""

    answer: str
    reasoning: str | None = None


@dataclass(frozen=True)
class RetrievalRequestHandler:
    """Depends only on port/use-case contracts; adapters wired at composition root."""

    contextualizer: ContextualizerPort
    adaptive_classifier: AdaptiveClassifierPort
    agentic_retrieval: AgenticRetrievalUseCase
    metadata_filter_planner: DeterministicMetadataFilterPlanner | None = None
    telemetry: Telemetry = field(default_factory=Telemetry, compare=False, repr=False)

    def handle(
        self,
        *,
        message: str,
        history: tuple[str, ...],
        filters: RetrievalFilters,
        top_k: int,
    ) -> ClarificationNeeded | FixedAnswer | AgenticRetrievalResult:
        """Run steps ①②④, then stop (③⑤) or hand off to the agentic loop (⑥-⑬)."""
        with self.telemetry.observe(
            "retrieval.request",
            as_type="retriever",
            input={
                "message": self.telemetry.content(message),
                "history": self.telemetry.content(list(history)),
                "top_k": top_k,
                "document_count": (
                    len(filters.document_ids) if filters.document_ids is not None else None
                ),
            },
        ) as root_observation:
            with self.telemetry.observe(
                "retrieval.contextualize",
                as_type="chain",
                input={
                    "message": self.telemetry.content(message),
                    "history_turns": len(history),
                },
            ) as observation:
                contextualized = self.contextualizer.contextualize(message, history)
                observation.update(
                    output={
                        "resolved_question": self.telemetry.content(
                            contextualized.resolved_question
                        ),
                        "is_ambiguous": contextualized.is_ambiguous,
                        "reasoning": self.telemetry.content(contextualized.reasoning),
                    }
                )

            if contextualized.is_ambiguous:
                clarification = ClarificationNeeded(
                    clarifying_question=(
                        contextualized.clarifying_question or _DEFAULT_CLARIFYING_QUESTION
                    ),
                    reasoning=contextualized.reasoning,
                )
                root_observation.update(output={"outcome": "clarification_needed"})
                return clarification

            with self.telemetry.observe(
                "retrieval.adaptive_decision",
                as_type="chain",
                input={"question": self.telemetry.content(contextualized.resolved_question)},
            ) as observation:
                decision = self.adaptive_classifier.classify(contextualized.resolved_question)
                observation.update(
                    output={
                        "needs_retrieval": decision.needs_retrieval,
                        "reasoning": self.telemetry.content(decision.reasoning),
                    }
                )
            if not decision.needs_retrieval:
                fixed_answer = FixedAnswer(
                    answer=decision.fixed_answer or _DEFAULT_FIXED_ANSWER,
                    reasoning=decision.reasoning,
                )
                root_observation.update(output={"outcome": "fixed_answer"})
                return fixed_answer

            planner = self.metadata_filter_planner
            with self.telemetry.observe(
                "retrieval.metadata_plan",
                as_type="chain",
                input={
                    "resolved_query": self.telemetry.content(contextualized.resolved_question),
                    "planner_enabled": planner is not None,
                    "allowed_fields": sorted(planner.allowed_fields) if planner else [],
                    "initial_metadata_filters": filters.metadata.as_dict(),
                    "owner_scope_applied": True,
                    "notebook_id": filters.notebook_id,
                    "document_ids": list(filters.document_ids or ()),
                },
            ) as observation:
                effective_filters = (
                    planner.plan(contextualized.resolved_question, filters)
                    if planner is not None
                    else filters
                )
                active_filters = effective_filters.metadata.as_dict()
                rpc_parameters = {
                    f"p_{field_name}": value
                    for field_name, value in effective_filters.metadata.active_items()
                }
                observation.update(
                    output={
                        "effective_metadata_filters": active_filters,
                        "filter_count": len(active_filters),
                        "match_policy": "exact_match_fail_closed",
                        "dense_metadata_filters": active_filters,
                        "sparse_rpc_metadata_parameters": rpc_parameters,
                    }
                )
            retrieval_result = self.agentic_retrieval.run(
                original_question=contextualized.resolved_question,
                filters=effective_filters,
                top_k=top_k,
            )
            root_observation.update(
                output={
                    "outcome": "retrieved",
                    "evidence_count": len(retrieval_result.evidence),
                    "rounds_used": retrieval_result.rounds_used,
                    "gave_up": retrieval_result.gave_up,
                    "chunk_ids": [candidate.chunk.id for candidate in retrieval_result.evidence],
                    "metadata_filters": effective_filters.metadata.as_dict(),
                }
            )
            return retrieval_result


__all__ = ["ClarificationNeeded", "FixedAnswer", "RetrievalRequestHandler"]
