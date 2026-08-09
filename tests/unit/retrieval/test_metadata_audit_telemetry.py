from __future__ import annotations

from contextlib import contextmanager

from app.retrieval.adapters.hybrid_search import HybridRetrievalAdapter
from app.retrieval.application.handle_retrieval_request import RetrievalRequestHandler
from app.retrieval.application.metadata_filter_planner import (
    DeterministicMetadataFilterPlanner,
    ProjectAliasRegistry,
    ProjectIdentity,
)
from app.retrieval.domain.models import (
    AdaptiveDecision,
    AgenticRetrievalResult,
    ContextualizedQuestion,
    EvidenceChunk,
    RetrievalCandidate,
    RetrievalFilters,
    StructuredMetadataFilters,
)


class _RecordingObservation:
    def __init__(self, record: dict[str, object]) -> None:
        self.record = record

    def update(self, **values: object) -> None:
        self.record.update(values)


class _RecordingTelemetry:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def content(self, value: object) -> object:
        return value

    @contextmanager
    def observe(self, name: str, **values: object):
        record = {"name": name, **values}
        self.records.append(record)
        yield _RecordingObservation(record)

    def named(self, name: str) -> dict[str, object]:
        return next(record for record in self.records if record["name"] == name)


class _Contextualizer:
    def contextualize(self, message: str, history: tuple[str, ...]) -> ContextualizedQuestion:
        del history
        return ContextualizedQuestion(resolved_question=message, is_ambiguous=False)


class _AdaptiveClassifier:
    def classify(self, question: str) -> AdaptiveDecision:
        del question
        return AdaptiveDecision(needs_retrieval=True)


class _RecordingAgenticRetrieval:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.filters: RetrievalFilters | None = None

    def run(
        self,
        *,
        original_question: str,
        filters: RetrievalFilters,
        top_k: int,
    ) -> AgenticRetrievalResult:
        del original_question, top_k
        self.events.append("retrieval.run")
        self.filters = filters
        return AgenticRetrievalResult(evidence=(), rounds_used=1, gave_up=False, trace=())


def test_metadata_plan_is_recorded_before_retrieval_runs() -> None:
    events: list[str] = []
    telemetry = _RecordingTelemetry()
    agentic = _RecordingAgenticRetrieval(events)
    planner = DeterministicMetadataFilterPlanner(
        project_registry=ProjectAliasRegistry(
            (
                ProjectIdentity(
                    project_id=None,
                    project_code="P16",
                    project_name="Vinhomes Smart City",
                ),
            )
        ),
        allowed_fields=frozenset({"project_code"}),
    )
    handler = RetrievalRequestHandler(
        contextualizer=_Contextualizer(),
        adaptive_classifier=_AdaptiveClassifier(),
        agentic_retrieval=agentic,  # type: ignore[arg-type]
        metadata_filter_planner=planner,
        telemetry=telemetry,  # type: ignore[arg-type]
    )

    handler.handle(
        message="Thông tin Vinhomes Smart City",
        history=(),
        filters=RetrievalFilters(
            owner_id="owner-1",
            notebook_id="notebook-1",
            document_ids=("document-1",),
        ),
        top_k=5,
    )

    plan = telemetry.named("retrieval.metadata_plan")
    assert plan["output"] == {
        "effective_metadata_filters": {"project_code": "P16"},
        "filter_count": 1,
        "match_policy": "exact_match_fail_closed",
        "dense_metadata_filters": {"project_code": "P16"},
        "sparse_rpc_metadata_parameters": {"p_project_code": "P16"},
    }
    assert agentic.filters is not None
    assert agentic.filters.metadata.as_dict() == {"project_code": "P16"}
    assert telemetry.records.index(plan) < len(telemetry.records)
    assert events == ["retrieval.run"]


class _FakeRetriever:
    def __init__(self, result: RetrievalCandidate) -> None:
        self.result = result

    def index(self, chunk: EvidenceChunk) -> None:
        del chunk

    def search(
        self,
        query: str,
        filters: RetrievalFilters,
        *,
        top_k: int,
    ) -> tuple[RetrievalCandidate, ...]:
        del query, filters, top_k
        return (self.result,)


def test_hybrid_trace_contains_returned_retrieval_metadata_and_filter_match() -> None:
    telemetry = _RecordingTelemetry()
    candidate = RetrievalCandidate(
        chunk=EvidenceChunk(
            id="chunk-1",
            document_id="document-1",
            text="Nội dung không được sao chép vào audit.",
            metadata={
                "retrieval_metadata": {
                    "title": "Danh mục tiện ích",
                    "project_code": "P16",
                }
            },
        ),
        score=0.9,
        rank=1,
        source="test",
    )
    adapter = HybridRetrievalAdapter(
        sparse=_FakeRetriever(candidate),  # type: ignore[arg-type]
        dense=_FakeRetriever(candidate),  # type: ignore[arg-type]
        telemetry=telemetry,  # type: ignore[arg-type]
    )
    filters = RetrievalFilters(
        owner_id="owner-1",
        metadata=StructuredMetadataFilters(project_code="P16"),
    )

    adapter.search("Vinhomes Smart City", filters, top_k=1)

    sparse = telemetry.named("retrieval.sparse_search")
    output = sparse["output"]
    assert isinstance(output, dict)
    records = output["candidate_metadata_audit"]
    assert isinstance(records, list)
    assert records[0]["retrieval_metadata"] == {
        "title": "Danh mục tiện ích",
        "project_code": "P16",
    }
    assert records[0]["matches_metadata_filters"] is True
    assert "text" not in records[0]
