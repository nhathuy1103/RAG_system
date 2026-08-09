"""A/B authoritative document scope on the live Supabase/pgvector corpus.

This runner never injects benchmark metadata into chunks. Ground truth is a
frozen list of document/chunk UUIDs that must already exist in the live store.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2 as httpx

from app.bootstrap.settings import get_settings as get_app_settings
from app.chat.application.document_scope_planner import DeterministicDocumentScopePlanner
from app.generation.adapters.openai_generator import OpenAIAnswerGenerator
from app.generation.domain import CitationHit, TokenChunk
from app.infrastructure.telemetry import Telemetry
from app.infrastructure.telemetry.openai import create_openai_client
from app.pipeline.bootstrap.composition import build_vector_index
from app.pipeline.bootstrap.settings import get_settings as get_ingestion_settings
from app.pipeline.indexing.adapters.embedding_providers import create_embedding_provider
from app.retrieval.adapters.fusion import ReciprocalRankFusion
from app.retrieval.adapters.hybrid_search import HybridRetrievalAdapter
from app.retrieval.adapters.local_adaptive import HeuristicAdaptiveClassifier
from app.retrieval.adapters.local_contextualizer import HeuristicContextualizer
from app.retrieval.adapters.local_reformulation import FallbackQueryReformulator
from app.retrieval.adapters.local_sufficiency import KeywordOverlapSufficiencyChecker
from app.retrieval.adapters.mmr_reranker import MaximalMarginalRelevanceReranker
from app.retrieval.adapters.postgrest_full_text_search import PostgrestFullTextRetrievalAdapter
from app.retrieval.adapters.qdrant_dense_search import DenseVectorRetrievalAdapter
from app.retrieval.application.agentic_retrieval import AgenticRetrievalUseCase
from app.retrieval.application.handle_retrieval_request import RetrievalRequestHandler
from app.retrieval.domain.models import AgenticRetrievalResult, RetrievalCandidate, RetrievalFilters

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TESTSET = Path(__file__).with_name("live_document_scope_testset.jsonl")
DEFAULT_OUTPUT = Path(__file__).parent / "runs" / "live-document-scope-ablation"


@dataclass(frozen=True)
class LiveDocument:
    id: UUID
    original_filename: str


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _normalize(value: str) -> str:
    from app.chat.application.document_scope_planner import normalize_document_identity

    return normalize_document_identity(value)


def _rank(candidates: tuple[RetrievalCandidate, ...], chunk_id: str) -> int | None:
    return next(
        (index for index, item in enumerate(candidates, start=1) if item.chunk.id == chunk_id),
        None,
    )


async def _generate(
    generator: OpenAIAnswerGenerator,
    query: str,
    evidence: tuple[RetrievalCandidate, ...],
) -> tuple[str, list[str]]:
    answer: list[str] = []
    citations: list[str] = []
    async for event in generator.stream(question=query, evidence=evidence):
        if isinstance(event, TokenChunk):
            answer.append(event.text)
        elif isinstance(event, CitationHit):
            citations.append(event.candidate.chunk.id)
    return "".join(answer), citations


def _fetch_live_state(
    client: httpx.Client,
    notebook_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    documents_response = client.get(
        "/documents",
        params={
            "notebook_id": f"eq.{notebook_id}",
            "status": "eq.ready",
            "is_active": "eq.true",
            "is_current": "eq.true",
            "canonical_document_id": "is.null",
            "select": "id,original_filename,status,is_active,is_current,canonical_document_id",
        },
    )
    documents_response.raise_for_status()
    chunks_response = client.get(
        "/document_chunks",
        params={
            "notebook_id": f"eq.{notebook_id}",
            "select": "id,document_id,chunk_index,content,metadata",
            "limit": "10000",
        },
    )
    chunks_response.raise_for_status()
    return documents_response.json(), chunks_response.json()


def _validate_ground_truth(
    cases: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> None:
    document_ids = {str(item["id"]) for item in documents}
    chunks_by_id = {str(item["id"]): item for item in chunks}
    for case in cases:
        expected_document_id = case["expected_document_id"]
        expected_chunk_id = case["expected_chunk_id"]
        if expected_document_id not in document_ids:
            raise ValueError(f"{case['id']}: expected document is not active/current")
        chunk = chunks_by_id.get(expected_chunk_id)
        if chunk is None or str(chunk["document_id"]) != expected_document_id:
            raise ValueError(f"{case['id']}: expected chunk/document provenance mismatch")
        normalized_content = _normalize(str(chunk["content"]))
        missing = [term for term in case["expected_terms"] if _normalize(term) not in normalized_content]
        if missing:
            raise ValueError(f"{case['id']}: expected terms absent from source chunk: {missing}")


async def run(args: argparse.Namespace) -> None:
    os.environ["LANGFUSE_ENABLED"] = "false"
    app_settings = get_app_settings()
    ingestion_settings = get_ingestion_settings()
    if app_settings.supabase_rest_url is None or app_settings.supabase_service_role_key is None:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    if not ingestion_settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    service_key = app_settings.supabase_service_role_key.get_secret_value()
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    telemetry = Telemetry()
    cases = _load_jsonl(args.testset)
    args.output.mkdir(parents=True, exist_ok=True)

    with httpx.Client(
        base_url=str(app_settings.supabase_rest_url),
        headers=headers,
        timeout=30.0,
    ) as client:
        document_rows, chunk_rows = _fetch_live_state(client, args.notebook_id)
        _validate_ground_truth(cases, document_rows, chunk_rows)
        live_documents = [
            LiveDocument(id=UUID(str(row["id"])), original_filename=str(row["original_filename"]))
            for row in document_rows
        ]
        allowed_ids = tuple(sorted((item.id for item in live_documents), key=str))
        chunks_per_document: dict[str, int] = {}
        for row in chunk_rows:
            document_id = str(row["document_id"])
            if UUID(document_id) in set(allowed_ids):
                chunks_per_document[document_id] = chunks_per_document.get(document_id, 0) + 1

        embedding_provider = create_embedding_provider(
            ingestion_settings.embedding_config,
            telemetry=telemetry,
        )
        vector_index = build_vector_index(
            ingestion_settings,
            postgrest_base_url=str(app_settings.supabase_rest_url),
            postgrest_headers=headers,
        )
        retrieval = HybridRetrievalAdapter(
            sparse=PostgrestFullTextRetrievalAdapter(client=client, telemetry=telemetry),
            dense=DenseVectorRetrievalAdapter(
                vector_index=vector_index,
                embedding_provider=embedding_provider,
                telemetry=telemetry,
            ),
            fusion=ReciprocalRankFusion(rank_constant=app_settings.retrieval_rrf_k),
            sparse_candidate_k=app_settings.retrieval_sparse_top_k,
            dense_candidate_k=app_settings.retrieval_dense_top_k,
            telemetry=telemetry,
        )
        handler = RetrievalRequestHandler(
            contextualizer=HeuristicContextualizer(),
            adaptive_classifier=HeuristicAdaptiveClassifier(),
            agentic_retrieval=AgenticRetrievalUseCase(
                retrieval_port=retrieval,
                sufficiency_checker=KeywordOverlapSufficiencyChecker(),
                reformulator=FallbackQueryReformulator(),
                reranker=MaximalMarginalRelevanceReranker(
                    lambda_param=app_settings.retrieval_mmr_lambda,
                    collapse_exact_duplicates=(app_settings.knowledge_quality_mode == "on"),
                ),
                score_threshold=app_settings.retrieval_min_dense_score,
                rerank_pool_size=max(
                    app_settings.retrieval_dense_top_k,
                    app_settings.retrieval_sparse_top_k,
                ),
                max_chunks_per_document=app_settings.retrieval_max_chunks_per_document,
                knowledge_quality_mode=app_settings.knowledge_quality_mode,
                telemetry=telemetry,
            ),
            telemetry=telemetry,
        )
        planner = DeterministicDocumentScopePlanner()
        run_rows: list[dict[str, Any]] = []
        evidence_for_generation: dict[tuple[str, str], tuple[RetrievalCandidate, ...]] = {}
        rng = random.Random(args.seed)

        for case_index, case in enumerate(cases, start=1):
            plan = planner.plan(case["query"], live_documents, allowed_ids)  # type: ignore[arg-type]
            mode_ids = {
                "baseline_all_authorized_documents": allowed_ids,
                "document_identity_scope": plan.after_document_ids,
            }
            for repeat in range(1, args.repeats + 1):
                modes = list(mode_ids)
                rng.shuffle(modes)
                for mode in modes:
                    selected_ids = mode_ids[mode]
                    started = time.perf_counter()
                    outcome = handler.handle(
                        message=case["query"],
                        history=(),
                        filters=RetrievalFilters(
                            owner_id=args.owner_id,
                            notebook_id=args.notebook_id,
                            document_ids=tuple(str(value) for value in selected_ids),
                        ),
                        top_k=args.top_k,
                    )
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    evidence = outcome.evidence if isinstance(outcome, AgenticRetrievalResult) else ()
                    evidence_for_generation.setdefault((case["id"], mode), evidence)
                    rank = _rank(evidence, case["expected_chunk_id"])
                    candidate_chunks = sum(chunks_per_document.get(str(value), 0) for value in selected_ids)
                    run_rows.append(
                        {
                            "case_id": case["id"],
                            "query": case["query"],
                            "mode": mode,
                            "repeat": repeat,
                            "planner_applied": plan.applied if mode == "document_identity_scope" else False,
                            "planner_reason": plan.reason if mode == "document_identity_scope" else "baseline",
                            "matched_titles": " | ".join(plan.matched_titles),
                            "matched_tokens": " | ".join(plan.matched_tokens),
                            "document_count": len(selected_ids),
                            "candidate_chunk_count": candidate_chunks,
                            "latency_ms": round(elapsed_ms, 3),
                            "expected_document_id": case["expected_document_id"],
                            "expected_chunk_id": case["expected_chunk_id"],
                            "retrieved_chunk_ids": " | ".join(item.chunk.id for item in evidence),
                            "retrieved_document_ids": " | ".join(item.chunk.document_id for item in evidence),
                            "rank": rank or "",
                            "recall_at_5": int(rank is not None and rank <= 5),
                            "reciprocal_rank": 0.0 if rank is None else 1.0 / rank,
                        }
                    )
            print(f"[{case_index}/{len(cases)}] {case['id']} plan={plan.reason}")

    generation_rows: list[dict[str, Any]] = []
    if not args.skip_generation:
        openai_client = create_openai_client(
            telemetry=telemetry,
            async_client=True,
            api_key=ingestion_settings.openai_api_key,
            base_url=ingestion_settings.openai_base_url,
            timeout=app_settings.llm_timeout_seconds,
            max_retries=app_settings.llm_max_retries,
        )
        generator = OpenAIAnswerGenerator(
            client=openai_client,
            model=ingestion_settings.openai_chat_model,
            temperature=0.0,
            max_output_tokens=250,
            allow_outside_knowledge=False,
            conflict_annotations_enabled=False,
            telemetry=telemetry,
        )
        try:
            for case_index, case in enumerate(cases, start=1):
                for mode in ("baseline_all_authorized_documents", "document_identity_scope"):
                    evidence = evidence_for_generation[(case["id"], mode)]
                    started = time.perf_counter()
                    answer, cited_chunks = await _generate(generator, case["query"], evidence)
                    generation_ms = (time.perf_counter() - started) * 1000
                    normalized_answer = _normalize(answer)
                    matched_terms = [
                        term for term in case["expected_terms"] if _normalize(term) in normalized_answer
                    ]
                    term_recall = len(matched_terms) / len(case["expected_terms"])
                    generation_rows.append(
                        {
                            "case_id": case["id"],
                            "mode": mode,
                            "generation_latency_ms": round(generation_ms, 3),
                            "expected_chunk_cited": int(case["expected_chunk_id"] in cited_chunks),
                            "expected_term_recall": round(term_recall, 6),
                            "grounded_answer_pass": int(
                                case["expected_chunk_id"] in cited_chunks and term_recall == 1.0
                            ),
                            "cited_chunk_ids": " | ".join(cited_chunks),
                            "matched_expected_terms": " | ".join(matched_terms),
                            "answer": answer,
                        }
                    )
                print(f"[generation {case_index}/{len(cases)}] {case['id']}")
        finally:
            await openai_client.close()

    with (args.output / "retrieval_runs.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(run_rows[0]))
        writer.writeheader()
        writer.writerows(run_rows)
    if generation_rows:
        with (args.output / "generation_quality.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(generation_rows[0]))
            writer.writeheader()
            writer.writerows(generation_rows)

    summary: dict[str, Any] = {
        "provenance": {
            "source": f"live_supabase_and_{ingestion_settings.vector_store_backend}",
            "vector_store_backend": ingestion_settings.vector_store_backend,
            "notebook_id": args.notebook_id,
            "owner_id": args.owner_id,
            "source_fields": ["documents.id", "documents.original_filename"],
            "ground_truth": str(args.testset.relative_to(ROOT)),
            "gold_metadata_injected": False,
            "active_document_count": len(allowed_ids),
            "active_chunk_count": sum(chunks_per_document.values()),
        },
        "config": {"top_k": args.top_k, "repeats": args.repeats, "seed": args.seed},
        "planner": {
            "routed_cases": len(
                {
                    row["case_id"]
                    for row in run_rows
                    if row["mode"] == "document_identity_scope" and row["planner_applied"]
                }
            ),
            "total_cases": len(cases),
        },
        "modes": {},
    }
    for mode in ("baseline_all_authorized_documents", "document_identity_scope"):
        rows = [row for row in run_rows if row["mode"] == mode]
        first_repeats = [row for row in rows if row["repeat"] == 1]
        generated = [row for row in generation_rows if row["mode"] == mode]
        summary["modes"][mode] = {
            "recall_at_5": statistics.mean(row["recall_at_5"] for row in first_repeats),
            "mrr": statistics.mean(row["reciprocal_rank"] for row in first_repeats),
            "median_latency_ms": statistics.median(row["latency_ms"] for row in rows),
            "mean_candidate_chunks": statistics.mean(
                row["candidate_chunk_count"] for row in first_repeats
            ),
            "grounded_answer_pass_rate": (
                statistics.mean(row["grounded_answer_pass"] for row in generated)
                if generated
                else None
            ),
            "expected_term_recall": (
                statistics.mean(row["expected_term_recall"] for row in generated)
                if generated
                else None
            ),
            "expected_chunk_citation_rate": (
                statistics.mean(row["expected_chunk_cited"] for row in generated)
                if generated
                else None
            ),
        }
    baseline = summary["modes"]["baseline_all_authorized_documents"]
    routed = summary["modes"]["document_identity_scope"]
    summary["delta"] = {
        "recall_at_5": routed["recall_at_5"] - baseline["recall_at_5"],
        "mrr": routed["mrr"] - baseline["mrr"],
        "median_latency_ms": routed["median_latency_ms"] - baseline["median_latency_ms"],
        "candidate_reduction_ratio": 1
        - routed["mean_candidate_chunks"] / baseline["mean_candidate_chunks"],
        "grounded_answer_pass_rate": (
            routed["grounded_answer_pass_rate"] - baseline["grounded_answer_pass_rate"]
            if generation_rows
            else None
        ),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--notebook-id", default="7769d606-146c-4a4d-8d9d-3889aa2d5d33")
    parser.add_argument("--owner-id", default="9d7fa672-ca49-47f7-a926-1bb0b2d948a4")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260806)
    parser.add_argument("--skip-generation", action="store_true")
    args = parser.parse_args()
    args.testset = args.testset.resolve()
    args.output = args.output.resolve()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
