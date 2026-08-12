from uuid import NAMESPACE_URL, UUID, uuid5

from app.pipeline.documents.domain.parsed import ParsedTable
from app.pipeline.indexing.domain.embedded_chunk import EmbeddedChunk
from app.structured_facts.application.claim_extraction import extract_structured_claims
from app.structured_facts.application.comparison import (
    build_structured_relation_payloads,
    build_unified_claim_relation_payloads,
)
from app.structured_facts.application.persistence import (
    build_structured_fact_persistence_batch,
)
from app.structured_facts.application.table_analyzer import TableAnalysis, analyze_table
from app.structured_facts.ports.repositories import StructuredClaimCandidate

OLD_DOC_ID = UUID("10000000-0000-0000-0000-000000000001")
NEW_DOC_ID = UUID("20000000-0000-0000-0000-000000000002")
OLD_SNAPSHOT_ID = UUID("30000000-0000-0000-0000-000000000003")
SECOND_OLD_DOC_ID = UUID("40000000-0000-0000-0000-000000000004")
SECOND_OLD_SNAPSHOT_ID = UUID("50000000-0000-0000-0000-000000000005")

HEADER = [
    "Project",
    "Building",
    "Unit",
    "Effective Date",
    "Price Type",
    "Price Basis",
    "VAT",
    "Payment Plan",
    "Sale Price",
]


def test_builds_pending_conflict_for_comparable_overlapping_price_change() -> None:
    old_analysis, old_table = _analysis(
        OLD_DOC_ID,
        [
            [
                "Ocean Park",
                "S1",
                "A101",
                "03/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.5 ty",
            ]
        ],
    )
    new_analysis, new_table = _analysis(
        NEW_DOC_ID,
        [
            [
                "Ocean Park",
                "S1",
                "A101",
                "03/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.8 ty",
            ]
        ],
    )
    old_batch = build_structured_fact_persistence_batch(
        analyses=(old_analysis,),
        tables=(old_table,),
        embedded_chunks=(),
    )
    new_batch = build_structured_fact_persistence_batch(
        analyses=(new_analysis,),
        tables=(new_table,),
        embedded_chunks=(),
    )

    relations = build_structured_relation_payloads(
        analyses=(new_analysis,),
        table_snapshots=new_batch.table_snapshots,
        candidates=_candidates(old_analysis, old_batch),
    )

    assert len(relations) == 1
    assert relations[0]["relation_type"] == "conflict_candidate"
    assert relations[0]["review_status"] == "pending"
    assert relations[0]["source_claim_key"]
    assert relations[0]["target_claim_key"]
    assert relations[0]["target_snapshot_id"] == str(OLD_SNAPSHOT_ID)
    assert relations[0]["evidence"]["reason_codes"] == ["overlapping_effective_value_mismatch"]


def test_different_buildings_are_source_and_target_only_not_conflicts() -> None:
    old_analysis, old_table = _analysis(
        OLD_DOC_ID,
        [
            [
                "Ocean Park",
                "S1",
                "A101",
                "03/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.5 ty",
            ]
        ],
    )
    new_analysis, new_table = _analysis(
        NEW_DOC_ID,
        [
            [
                "Ocean Park",
                "S2",
                "A101",
                "03/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.8 ty",
            ]
        ],
    )
    old_batch = build_structured_fact_persistence_batch(
        analyses=(old_analysis,),
        tables=(old_table,),
        embedded_chunks=(),
    )
    new_batch = build_structured_fact_persistence_batch(
        analyses=(new_analysis,),
        tables=(new_table,),
        embedded_chunks=(),
    )

    relations = build_structured_relation_payloads(
        analyses=(new_analysis,),
        table_snapshots=new_batch.table_snapshots,
        candidates=_candidates(old_analysis, old_batch),
    )

    assert {relation["relation_type"] for relation in relations} == {
        "source_only",
        "target_only",
    }
    assert {relation["review_status"] for relation in relations} == {"auto_confirmed"}


def test_sequential_effective_months_are_updates_not_conflicts() -> None:
    old_analysis, old_table = _analysis(
        OLD_DOC_ID,
        [
            [
                "Ocean Park",
                "S1",
                "A101",
                "03/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.5 ty",
            ]
        ],
    )
    new_analysis, new_table = _analysis(
        NEW_DOC_ID,
        [
            [
                "Ocean Park",
                "S1",
                "A101",
                "04/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.8 ty",
            ]
        ],
    )
    old_batch = build_structured_fact_persistence_batch(
        analyses=(old_analysis,),
        tables=(old_table,),
        embedded_chunks=(),
    )
    new_batch = build_structured_fact_persistence_batch(
        analyses=(new_analysis,),
        tables=(new_table,),
        embedded_chunks=(),
    )

    relations = build_structured_relation_payloads(
        analyses=(new_analysis,),
        table_snapshots=new_batch.table_snapshots,
        candidates=_candidates(old_analysis, old_batch),
    )

    assert [relation["relation_type"] for relation in relations] == ["updated"]
    assert relations[0]["review_status"] == "auto_confirmed"
    assert relations[0]["evidence"]["reason_codes"] == ["non_overlapping_effective_intervals"]


def test_compares_one_current_table_with_each_independent_prior_document() -> None:
    first_old, first_table = _analysis(
        OLD_DOC_ID,
        [
            [
                "Ocean Park",
                "S1",
                "A101",
                "03/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.5 ty",
            ]
        ],
    )
    second_old, second_table = _analysis(
        SECOND_OLD_DOC_ID,
        [
            [
                "Ocean Park",
                "S1",
                "A101",
                "03/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.6 ty",
            ]
        ],
    )
    current, current_table = _analysis(
        NEW_DOC_ID,
        [
            [
                "Ocean Park",
                "S1",
                "A101",
                "03/2025",
                "List",
                "Total unit",
                "Included",
                "Standard",
                "4.8 ty",
            ]
        ],
    )
    first_batch = build_structured_fact_persistence_batch(
        analyses=(first_old,), tables=(first_table,), embedded_chunks=()
    )
    second_batch = build_structured_fact_persistence_batch(
        analyses=(second_old,), tables=(second_table,), embedded_chunks=()
    )
    current_batch = build_structured_fact_persistence_batch(
        analyses=(current,), tables=(current_table,), embedded_chunks=()
    )

    relations = build_structured_relation_payloads(
        analyses=(current,),
        table_snapshots=current_batch.table_snapshots,
        candidates=(
            *_candidates(first_old, first_batch),
            *_candidates(
                second_old,
                second_batch,
                snapshot_id=SECOND_OLD_SNAPSHOT_ID,
            ),
        ),
    )

    assert len(relations) == 2
    assert {relation["relation_type"] for relation in relations} == {"conflict_candidate"}
    assert {relation["target_snapshot_id"] for relation in relations} == {
        str(OLD_SNAPSHOT_ID),
        str(SECOND_OLD_SNAPSHOT_ID),
    }


def test_unified_relation_compares_current_prose_with_prior_table() -> None:
    prior_analysis, prior_table = _bridge_analysis(OLD_DOC_ID, "8,2 tỷ VND")
    prior_batch = build_structured_fact_persistence_batch(
        analyses=(prior_analysis,),
        tables=(prior_table,),
        embedded_chunks=(),
    )
    current_batch = _prose_batch(
        NEW_DOC_ID,
        "Giá căn 2PN tại Vinhomes Project Alpha năm 2023 là 8200 triệu VND/căn.",
    )

    relations = build_unified_claim_relation_payloads(
        current_claims=current_batch.claims,
        table_snapshots=current_batch.table_snapshots,
        candidates=_batch_candidates(prior_batch, OLD_DOC_ID),
    )

    assert len(relations) == 1
    assert relations[0]["relation_type"] == "unchanged"
    assert relations[0]["evidence"]["source_form"] == "prose"
    assert relations[0]["evidence"]["target_form"] == "table"
    assert relations[0]["evidence"]["p2_gate"] == ("exact_value_free_candidate_identity_overlap")


def test_unified_relation_compares_current_table_with_prior_prose() -> None:
    current_analysis, current_table = _bridge_analysis(NEW_DOC_ID, "8,5 tỷ VND")
    current_batch = build_structured_fact_persistence_batch(
        analyses=(current_analysis,),
        tables=(current_table,),
        embedded_chunks=(),
    )
    prior_batch = _prose_batch(
        OLD_DOC_ID,
        "Giá căn 2PN tại Vinhomes Project Alpha năm 2023 là 8,2 tỷ VND/căn.",
    )

    relations = build_unified_claim_relation_payloads(
        current_claims=current_batch.claims,
        table_snapshots=current_batch.table_snapshots,
        candidates=_batch_candidates(prior_batch, OLD_DOC_ID),
    )

    assert len(relations) == 1
    assert relations[0]["relation_type"] == "conflict_candidate"
    assert relations[0]["review_status"] == "pending"
    assert relations[0]["evidence"]["source_form"] == "table"
    assert relations[0]["evidence"]["target_form"] == "prose"


def _analysis(
    document_id: UUID,
    rows: list[list[str]],
) -> tuple[TableAnalysis, ParsedTable]:
    table = ParsedTable(
        table_id="table-1",
        location="sheet:pricing",
        rows=[HEADER, *rows],
        columns=len(HEADER),
        header=HEADER,
    )
    return analyze_table(document_id=str(document_id), table=table), table


def _bridge_analysis(document_id: UUID, price: str) -> tuple[TableAnalysis, ParsedTable]:
    header = ["Dự án", "Loại căn", "Ngày hiệu lực", "Giá bán"]
    table = ParsedTable(
        table_id="bridge-table",
        location="sheet:bridge",
        rows=[header, ["Vinhomes Project Alpha", "2PN", "2023-01-01", price]],
        columns=len(header),
        header=header,
    )
    return analyze_table(document_id=str(document_id), table=table), table


def _prose_batch(document_id: UUID, text: str):  # type: ignore[no-untyped-def]
    chunk = EmbeddedChunk(
        id=f"prose-{document_id}",
        document_id=str(document_id),
        document_version=1,
        owner_id=str(UUID(int=91)),
        tenant_id=str(UUID(int=92)),
        chunk_index=0,
        page_number=1,
        section_title="Pricing",
        checksum="checksum",
        text=text,
        canonical_text=text,
        token_count=len(text.split()),
        embedding=(0.1, 0.2),
        embedding_model="test",
        metadata={},
    )
    claims = extract_structured_claims(
        text,
        document_id=str(document_id),
        chunk_id=chunk.id,
        page_number=1,
    ).claims
    return build_structured_fact_persistence_batch(
        analyses=(),
        tables=(),
        embedded_chunks=(chunk,),
        prose_claims=claims,
    )


def _batch_candidates(batch, document_id: UUID):  # type: ignore[no-untyped-def]
    snapshot = batch.table_snapshots[0]
    return tuple(
        StructuredClaimCandidate(
            claim_id=uuid5(NAMESPACE_URL, f"candidate:{claim['claim_key']}"),
            snapshot_id=OLD_SNAPSHOT_ID,
            document_id=document_id,
            document_version=1,
            snapshot_key=str(snapshot["snapshot_key"]),
            schema_fingerprint=str(snapshot["schema_fingerprint"]),
            template_fingerprint=None,
            normalized_schema=snapshot["normalized_schema"],
            candidate_identity_hash=str(claim["candidate_identity_hash"]),
            claim=claim,
        )
        for claim in batch.claims
    )


def _candidates(
    analysis: TableAnalysis,
    batch,
    *,
    snapshot_id: UUID = OLD_SNAPSHOT_ID,
) -> tuple[StructuredClaimCandidate, ...]:
    snapshot = batch.table_snapshots[0]
    return tuple(
        StructuredClaimCandidate(
            claim_id=uuid5(NAMESPACE_URL, f"claim:{claim.claim_identity_hash}"),
            snapshot_id=snapshot_id,
            document_id=UUID(analysis.document_id),
            document_version=1,
            snapshot_key=str(snapshot["snapshot_key"]),
            schema_fingerprint=str(snapshot["schema_fingerprint"]),
            template_fingerprint=None,
            normalized_schema=snapshot["normalized_schema"],
            candidate_identity_hash=claim.candidate_identity_hash,
            claim=claim.to_payload(),
        )
        for claim in analysis.claims
    )
