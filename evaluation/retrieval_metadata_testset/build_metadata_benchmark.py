"""Build the controlled metadata retrieval benchmark (benchmark_v2).

The three uploaded documents remain the real-data pilot.  This builder creates
a deterministic stress corpus so versioning, null results, ACLs, and multi-hop
ground truth can be evaluated without pretending those properties exist in the
pilot files.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "benchmark_v2"
CORPUS_PATH = OUTPUT_DIR / "corpus.jsonl"
TESTSET_PATH = OUTPUT_DIR / "testset.jsonl"
QUERIES_PATH = OUTPUT_DIR / "queries.csv"
SLICE_DISTRIBUTION_PATH = OUTPUT_DIR / "slice_distribution.csv"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

SCENARIO_COUNT = 30
OWNER_ID = "metadata-benchmark-user"
NOTEBOOK_ID = "metadata-benchmark"
RESTRICTED_OWNER_ID = "metadata-benchmark-admin"
RESTRICTED_NOTEBOOK_ID = "metadata-benchmark-restricted"

PRIMARY_SLICES = (
    "content_only",
    "explicit_filter",
    "implicit_filter",
    "cross_document_confusion",
    "version_conflict",
    "section_localization",
    "table_visual",
    "multi_hop",
    "null_insufficient",
    "permission_sensitive",
)

TOPICS = (
    "hỗ trợ nghiên cứu",
    "thực tập doanh nghiệp",
    "học bổng khuyến khích",
    "sử dụng phòng thí nghiệm",
    "đăng ký đề tài",
    "thanh toán công tác phí",
    "mượn thiết bị",
    "tổ chức hội thảo",
    "xét tốt nghiệp",
    "phúc khảo học phần",
)

FACULTIES = (
    "Khoa Công nghệ thông tin",
    "Khoa Kinh tế",
    "Khoa Luật",
    "Khoa Ngoại ngữ",
    "Khoa Cơ khí",
    "Khoa Điện - Điện tử",
)

SOURCES = (
    "Cổng thông tin nội bộ",
    "SharePoint học vụ",
    "Kho văn bản điện tử",
)

REFERENCE_WORDS = (
    "AURORA",
    "BOREALIS",
    "CEDAR",
    "DELTA",
    "EMBER",
    "FUSION",
    "GALAXY",
    "HORIZON",
    "IRIDIUM",
    "JASMINE",
    "KINETIC",
    "LUMEN",
    "MATRIX",
    "NEBULA",
    "ORBIT",
    "PRISM",
    "QUARTZ",
    "RADIANT",
    "SOLARIS",
    "TITANIUM",
    "UMBRA",
    "VECTOR",
    "WILLOW",
    "XENON",
    "YTTRIUM",
    "ZENITH",
    "ACACIA",
    "BERYL",
    "CITRINE",
    "DIODE",
)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _current_metadata(gold: dict[str, Any], scenario: int) -> dict[str, Any]:
    """Create realistic, deterministic extraction gaps for mode B."""

    current = dict(gold)
    if scenario % 7 == 0:
        current.pop("source", None)
    if scenario % 9 == 0:
        current.pop("faculty", None)
    if scenario % 8 == 0:
        current.pop("contextual_summary", None)
    if scenario % 10 == 0:
        current.pop("lifecycle_status", None)
        current.pop("effective_status", None)
    if scenario % 11 == 0:
        current.pop("table_header", None)
        current.pop("figure_caption", None)
    return current


def _chunk(
    *,
    chunk_id: str,
    document_id: str,
    document_title: str,
    chunk_index: int,
    page_number: int,
    text: str,
    metadata: dict[str, Any],
    scenario: int,
    owner_id: str = OWNER_ID,
    notebook_id: str = NOTEBOOK_ID,
    visibility: str = "internal",
    allowed_groups: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_title": document_title,
        "chunk_index": chunk_index,
        "page_number": page_number,
        "text": text,
        "current_metadata": _current_metadata(metadata, scenario),
        "gold_metadata": metadata,
        "gold_annotated": True,
        "security": {
            "owner_id": owner_id,
            "notebook_id": notebook_id,
            "visibility": visibility,
            "allowed_groups": allowed_groups or [],
        },
    }


def _metadata(
    *,
    title: str,
    document_type: str,
    year: int,
    faculty: str,
    source: str,
    version: int,
    status: str,
    published_at: str,
    topic: str,
    section_title: str,
    section_path: list[str],
    content_kind: str,
    contextual_summary: str,
    contextual_search_terms: list[str],
    clause_type: str,
    table_header: str | None = None,
    figure_caption: str | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "title": title,
        "document_type": document_type,
        "year": year,
        "faculty": faculty,
        "department": faculty,
        "source": source,
        "source_kind": "synthetic_fixture",
        "document_version": version,
        "effective_status": status,
        "lifecycle_status": status,
        "published_at": published_at,
        "domain": "university_operations",
        "policy_field": topic,
        "clause_type": clause_type,
        "section_title": section_title,
        "section_path": section_path,
        "content_kind": content_kind,
        "keyword_aliases": [topic, faculty],
        "contextual_summary": contextual_summary,
        "contextual_search_terms": contextual_search_terms,
    }
    if table_header:
        values["table_header"] = table_header
    if figure_caption:
        values["figure_caption"] = figure_caption
    return values


def _scenario_values(index: int) -> dict[str, Any]:
    topic = TOPICS[(index - 1) % len(TOPICS)]
    faculty = FACULTIES[(index - 1) % len(FACULTIES)]
    source = SOURCES[(index - 1) % len(SOURCES)]
    old_source = SOURCES[index % len(SOURCES)]
    deadline = 5 + ((index * 3) % 10)
    old_deadline = deadline + 5
    amount = 2_000_000 + index * 175_000
    old_amount = amount - 250_000
    completed = 70 + index * 4
    old_completed = completed - 13
    rate = 72 + (index % 19)
    old_rate = max(50, rate - 9)
    return {
        "scenario": index,
        "scenario_id": f"scenario_{index:02d}",
        "topic": topic,
        "faculty": faculty,
        "source": source,
        "old_source": old_source,
        "deadline": deadline,
        "old_deadline": old_deadline,
        "amount": amount,
        "old_amount": old_amount,
        "completed": completed,
        "old_completed": old_completed,
        "rate": rate,
        "old_rate": old_rate,
        "reference_code": f"MKB{REFERENCE_WORDS[index - 1]}NEW",
        "old_reference_code": f"MKB{REFERENCE_WORDS[index - 1]}OLD",
        "secret_code": f"CONF-{index:02d}-{9000 + index}",
    }


def _build_policy_chunks(values: dict[str, Any], *, version: int) -> list[dict[str, Any]]:
    scenario = values["scenario"]
    is_current = version == 2
    year = 2026 if is_current else 2024
    status = "current" if is_current else "superseded"
    source = values["source"] if is_current else values["old_source"]
    deadline = values["deadline"] if is_current else values["old_deadline"]
    amount = values["amount"] if is_current else values["old_amount"]
    rate = values["rate"] if is_current else values["old_rate"]
    reference_code = values["reference_code"] if is_current else values["old_reference_code"]
    prefix = f"mb:s{scenario:02d}:policy:v{version}"
    document_id = f"mb-doc-s{scenario:02d}-policy-v{version}"
    document_title = f"MB_{scenario:02d}_POLICY_V{version}.pdf"
    title = f"Quy định {values['topic']}"
    common = {
        "title": title,
        "document_type": "policy",
        "year": year,
        "faculty": values["faculty"],
        "source": source,
        "version": version,
        "status": status,
        "published_at": f"{year}-01-{(scenario % 27) + 1:02d}",
        "topic": values["topic"],
    }
    eligibility_metadata = _metadata(
        **common,
        section_title="Phạm vi và điều kiện tiếp nhận",
        section_path=[title, "Phạm vi và điều kiện tiếp nhận"],
        content_kind="paragraph",
        contextual_summary=(
            f"Điều kiện tiếp nhận hồ sơ {values['topic']} và mã tham chiếu áp dụng."
        ),
        contextual_search_terms=[reference_code, "điều kiện tiếp nhận", "biểu mẫu hợp lệ"],
        clause_type="eligibility",
    )
    procedure_metadata = _metadata(
        **common,
        section_title="Thời hạn và mức áp dụng",
        section_path=[title, "Quy trình", "Thời hạn và mức áp dụng"],
        content_kind="paragraph",
        contextual_summary=(f"Quy định thời hạn xử lý và mức hỗ trợ cho hồ sơ {values['topic']}."),
        contextual_search_terms=[f"{deadline} ngày làm việc", "mức hỗ trợ tối đa"],
        clause_type="deadline_and_amount",
    )
    chunks = [
        _chunk(
            chunk_id=f"{prefix}:eligibility",
            document_id=document_id,
            document_title=document_title,
            chunk_index=0,
            page_number=1,
            text=(
                f"Mã tham chiếu {reference_code}. Hồ sơ {values['topic']} được tiếp nhận khi "
                "có biểu mẫu hợp lệ, chữ ký của người đề nghị và đủ tài liệu chứng minh."
            ),
            metadata=eligibility_metadata,
            scenario=scenario,
        ),
        _chunk(
            chunk_id=f"{prefix}:procedure",
            document_id=document_id,
            document_title=document_title,
            chunk_index=1,
            page_number=2,
            text=(
                f"Hồ sơ {values['topic']} hợp lệ được xử lý trong {deadline} ngày làm việc. "
                f"Mức hỗ trợ tối đa là {amount:,} VND; hồ sơ thiếu chứng từ phải bổ sung."
            ),
            metadata=procedure_metadata,
            scenario=scenario,
        ),
    ]

    if scenario % 2 == 0:
        media_metadata = _metadata(
            **common,
            section_title="Bảng chỉ tiêu xử lý",
            section_path=[title, "Phụ lục", "Bảng chỉ tiêu xử lý"],
            content_kind="table",
            table_header="Hạng mục | Giá trị áp dụng",
            contextual_summary=f"Bảng chỉ tiêu định lượng cho hồ sơ {values['topic']}.",
            contextual_search_terms=["thời hạn xử lý", "mức hỗ trợ tối đa"],
            clause_type="service_level_table",
        )
        media_text = (
            "| Hạng mục | Giá trị áp dụng |\n"
            "| --- | --- |\n"
            f"| Thời hạn xử lý | {deadline} ngày làm việc |\n"
            f"| Mức hỗ trợ tối đa | {amount:,} VND |"
        )
        media_suffix = "table"
    else:
        caption = f"Biểu đồ tỷ lệ hoàn tất hồ sơ {values['topic']}"
        media_metadata = _metadata(
            **common,
            section_title="Biểu đồ tiến độ xử lý",
            section_path=[title, "Phụ lục", "Biểu đồ tiến độ xử lý"],
            content_kind="figure",
            figure_caption=caption,
            contextual_summary=f"Biểu đồ thể hiện tỷ lệ hoàn tất hồ sơ {values['topic']} theo quý.",
            contextual_search_terms=["Quý I", "Quý II", f"{rate}%"],
            clause_type="completion_chart",
        )
        media_text = (
            f"{caption}. Dữ liệu trích xuất: Quý I {max(40, rate - 8)}%; "
            f"Quý II {rate}%; Quý III {min(99, rate + 4)}%."
        )
        media_suffix = "figure"
    chunks.append(
        _chunk(
            chunk_id=f"{prefix}:{media_suffix}",
            document_id=document_id,
            document_title=document_title,
            chunk_index=2,
            page_number=3,
            text=media_text,
            metadata=media_metadata,
            scenario=scenario,
        )
    )
    return chunks


def _build_report_chunk(values: dict[str, Any], *, latest: bool) -> dict[str, Any]:
    scenario = values["scenario"]
    year = 2026 if latest else 2025
    status = "latest" if latest else "archived"
    completed = values["completed"] if latest else values["old_completed"]
    rate = values["rate"] if latest else values["old_rate"]
    suffix = "latest" if latest else "archived"
    document_id = f"mb-doc-s{scenario:02d}-report-{year}"
    document_title = f"MB_{scenario:02d}_REPORT_{year}.pdf"
    title = f"Báo cáo {values['topic']}"
    metadata = _metadata(
        title=title,
        document_type="report",
        year=year,
        faculty=values["faculty"],
        source=values["source"],
        version=2 if latest else 1,
        status=status,
        published_at=f"{year}-12-{(scenario % 27) + 1:02d}",
        topic=values["topic"],
        section_title="Kết quả thực hiện",
        section_path=[title, "Kết quả thực hiện"],
        content_kind="paragraph",
        contextual_summary=(f"Báo cáo số hồ sơ hoàn tất và tỷ lệ đúng hạn của {values['topic']}."),
        contextual_search_terms=[f"{completed} hồ sơ", f"{rate}%", "kết quả thực hiện"],
        clause_type="performance_report",
    )
    return _chunk(
        chunk_id=f"mb:s{scenario:02d}:report:{suffix}",
        document_id=document_id,
        document_title=document_title,
        chunk_index=0,
        page_number=1,
        text=(
            f"Báo cáo {values['topic']}: có {completed} hồ sơ hoàn tất, tỷ lệ đúng hạn "
            f"đạt {rate}%, và {max(1, scenario % 7)} hồ sơ cần bổ sung."
        ),
        metadata=metadata,
        scenario=scenario,
    )


def _build_restricted_chunk(values: dict[str, Any]) -> dict[str, Any]:
    scenario = values["scenario"]
    document_id = f"mb-doc-s{scenario:02d}-restricted"
    document_title = f"MB_{scenario:02d}_CONFIDENTIAL.pdf"
    metadata = _metadata(
        title=f"Dự toán mật {values['topic']}",
        document_type="confidential_memo",
        year=2026,
        faculty=values["faculty"],
        source="Kho quản trị hạn chế",
        version=1,
        status="current",
        published_at=f"2026-06-{(scenario % 27) + 1:02d}",
        topic=values["topic"],
        section_title="Dự toán nội bộ",
        section_path=["Tài liệu hạn chế", "Dự toán nội bộ"],
        content_kind="paragraph",
        contextual_summary="Thông tin dự toán chỉ dành cho nhóm quản trị được cấp quyền.",
        contextual_search_terms=[values["secret_code"], "dự toán mật"],
        clause_type="restricted_budget",
    )
    return _chunk(
        chunk_id=f"mb:s{scenario:02d}:restricted:budget",
        document_id=document_id,
        document_title=document_title,
        chunk_index=0,
        page_number=1,
        text=(
            f"Mã dự toán bảo mật {values['secret_code']}. Ngân sách dự kiến cho "
            f"{values['topic']} là {values['amount'] * 12:,} VND."
        ),
        metadata=metadata,
        scenario=scenario,
        owner_id=RESTRICTED_OWNER_ID,
        notebook_id=RESTRICTED_NOTEBOOK_ID,
        visibility="restricted",
        allowed_groups=["ban-giam-hieu"],
    )


def build_corpus() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    corpus: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    for index in range(1, SCENARIO_COUNT + 1):
        values = _scenario_values(index)
        scenarios.append(values)
        corpus.extend(_build_policy_chunks(values, version=1))
        corpus.extend(_build_policy_chunks(values, version=2))
        corpus.append(_build_report_chunk(values, latest=False))
        corpus.append(_build_report_chunk(values, latest=True))
        corpus.append(_build_restricted_chunk(values))
    return corpus, scenarios


def _condition(field: str, value: object, op: str = "eq") -> dict[str, Any]:
    return {"field": field, "op": op, "value": value}


def _test_case(
    *,
    values: dict[str, Any],
    primary_slice: str,
    query: str,
    relevant_chunk_ids: list[str] | None = None,
    relevant_chunk_groups: list[list[str]] | None = None,
    protected_chunk_ids: list[str] | None = None,
    target_type: str = "single",
    answerable: bool = True,
    difficulty: str = "medium",
    required_metadata_fields: list[str] | None = None,
    metadata_conditions: list[dict[str, Any]] | None = None,
    extra_slices: list[str] | None = None,
    must_include_terms: list[str] | None = None,
    should_include_terms: list[str] | None = None,
    forbidden_chunk_ids: list[str] | None = None,
    forbidden_document_titles: list[str] | None = None,
    query_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenario = values["scenario"]
    case_id = f"mb_{scenario:02d}_{primary_slice}"
    relevant = relevant_chunk_ids or []
    groups = relevant_chunk_groups or ([[chunk_id] for chunk_id in relevant] if relevant else [])
    slices = list(dict.fromkeys([primary_slice, *(extra_slices or [])]))
    expected_title = ""
    if relevant:
        chunk_id = relevant[0]
        if ":policy:v1:" in chunk_id:
            expected_title = f"MB_{scenario:02d}_POLICY_V1.pdf"
        elif ":policy:v2:" in chunk_id:
            expected_title = f"MB_{scenario:02d}_POLICY_V2.pdf"
        elif ":report:archived" in chunk_id:
            expected_title = f"MB_{scenario:02d}_REPORT_2025.pdf"
        elif ":report:latest" in chunk_id:
            expected_title = f"MB_{scenario:02d}_REPORT_2026.pdf"
    if protected_chunk_ids:
        expected_title = f"MB_{scenario:02d}_CONFIDENTIAL.pdf"
    return {
        "id": case_id,
        "query_id": case_id,
        "query": query,
        "query_type": primary_slice,
        "category": primary_slice,
        "primary_slice": primary_slice,
        "benchmark_slices": slices,
        "scenario_id": values["scenario_id"],
        "split": "dev" if scenario <= 6 else "test",
        "difficulty": difficulty,
        "answerable": answerable,
        "target_type": target_type,
        "source_file": expected_title or "__none__",
        "source_kind": "synthetic_fixture",
        "domain": "university_operations",
        "metadata_focus": required_metadata_fields or [],
        "required_metadata_fields": required_metadata_fields or [],
        "relevant_doc_ids": [],
        "relevant_doc_titles": [expected_title] if expected_title else [],
        "relevant_chunk_ids": relevant,
        "relevant_chunk_groups": groups,
        "protected_chunk_ids": protected_chunk_ids or [],
        "forbidden_chunk_ids": forbidden_chunk_ids or [],
        "retrieval_filters": {
            "metadata_conditions": metadata_conditions or [],
            "unsupported_field_policy": "skip",
        },
        "query_context": query_context
        or {
            "owner_id": OWNER_ID,
            "notebook_id": NOTEBOOK_ID,
            "groups": ["giang-vien", "sinh-vien"],
        },
        "expected_metadata": {
            "required_fields": required_metadata_fields or [],
            "metadata_conditions": metadata_conditions or [],
        },
        "expected": {
            "target_type": target_type,
            "document_title": expected_title,
            "page": None,
            "page_tolerance": 0,
            "must_include_terms": must_include_terms or [],
            "should_include_terms": should_include_terms or [],
            "forbidden_document_titles": forbidden_document_titles or [],
            "forbidden_chunk_ids": forbidden_chunk_ids or [],
            "protected_chunk_ids": protected_chunk_ids or [],
        },
        "notes": "Controlled synthetic metadata benchmark; not production ground truth.",
    }


def build_testset(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    for values in scenarios:
        scenario = values["scenario"]
        policy_v1 = f"mb:s{scenario:02d}:policy:v1"
        policy_v2 = f"mb:s{scenario:02d}:policy:v2"
        media_suffix = "table" if scenario % 2 == 0 else "figure"
        old_policy_title = f"MB_{scenario:02d}_POLICY_V1.pdf"
        old_report_title = f"MB_{scenario:02d}_REPORT_2025.pdf"

        tests.append(
            _test_case(
                values=values,
                primary_slice="content_only",
                query=f"Mã tham chiếu {values['reference_code']} yêu cầu hồ sơ có những gì?",
                relevant_chunk_ids=[f"{policy_v2}:eligibility"],
                difficulty="easy",
                must_include_terms=[values["reference_code"], "biểu mẫu hợp lệ"],
            )
        )
        tests.append(
            _test_case(
                values=values,
                primary_slice="explicit_filter",
                query=(
                    f"Theo văn bản năm 2026 của {values['faculty']}, loại policy, nguồn "
                    f"{values['source']}, thời hạn xử lý hồ sơ {values['topic']} là bao lâu?"
                ),
                relevant_chunk_ids=[f"{policy_v2}:procedure"],
                difficulty="hard",
                required_metadata_fields=["year", "faculty", "document_type", "source"],
                metadata_conditions=[
                    _condition("year", 2026),
                    _condition("faculty", values["faculty"]),
                    _condition("document_type", "policy"),
                    _condition("source", values["source"]),
                ],
                must_include_terms=[f"{values['deadline']} ngày làm việc"],
                forbidden_document_titles=[old_policy_title],
            )
        )
        tests.append(
            _test_case(
                values=values,
                primary_slice="implicit_filter",
                query=(
                    f"Trong báo cáo mới nhất của {values['faculty']} về {values['topic']}, "
                    "có bao nhiêu hồ sơ hoàn tất?"
                ),
                relevant_chunk_ids=[f"mb:s{scenario:02d}:report:latest"],
                difficulty="hard",
                required_metadata_fields=["faculty", "document_type", "lifecycle_status"],
                metadata_conditions=[
                    _condition("faculty", values["faculty"]),
                    _condition("document_type", "report"),
                    _condition("lifecycle_status", "latest"),
                ],
                must_include_terms=[f"{values['completed']} hồ sơ"],
                forbidden_document_titles=[old_report_title],
            )
        )
        tests.append(
            _test_case(
                values=values,
                primary_slice="cross_document_confusion",
                query=(
                    f"Quy định {values['topic']} đang áp dụng tại {values['faculty']} nêu mức "
                    "hỗ trợ tối đa bao nhiêu?"
                ),
                relevant_chunk_ids=[f"{policy_v2}:procedure"],
                difficulty="hard",
                required_metadata_fields=["faculty", "effective_status", "policy_field"],
                must_include_terms=[f"{values['amount']:,} VND"],
                forbidden_document_titles=[old_policy_title],
                forbidden_chunk_ids=[f"{policy_v1}:procedure"],
            )
        )
        tests.append(
            _test_case(
                values=values,
                primary_slice="version_conflict",
                query=(
                    f"Thời hạn xử lý {values['topic']} của {values['faculty']} thay đổi thế nào "
                    "giữa bản năm 2024 và bản năm 2026?"
                ),
                relevant_chunk_ids=[f"{policy_v1}:procedure", f"{policy_v2}:procedure"],
                relevant_chunk_groups=[
                    [f"{policy_v1}:procedure"],
                    [f"{policy_v2}:procedure"],
                ],
                target_type="multi_hop",
                difficulty="hard",
                required_metadata_fields=["year", "document_version", "effective_status"],
                extra_slices=["multi_hop"],
                must_include_terms=[
                    f"{values['old_deadline']} ngày làm việc",
                    f"{values['deadline']} ngày làm việc",
                ],
            )
        )
        tests.append(
            _test_case(
                values=values,
                primary_slice="section_localization",
                query=(
                    f"Trong mục 'Phạm vi và điều kiện tiếp nhận' của quy định {values['topic']} "
                    f"tại {values['faculty']}, hồ sơ cần điều kiện gì?"
                ),
                relevant_chunk_ids=[f"{policy_v2}:eligibility"],
                difficulty="medium",
                required_metadata_fields=["section_title", "section_path"],
                must_include_terms=["biểu mẫu hợp lệ", "chữ ký"],
                forbidden_chunk_ids=[f"{policy_v2}:procedure", f"{policy_v2}:{media_suffix}"],
            )
        )
        if scenario % 2 == 0:
            media_query = (
                f"Trong bảng chỉ tiêu của quy định {values['topic']} tại {values['faculty']}, "
                "mức hỗ trợ tối đa là bao nhiêu?"
            )
            media_terms = [f"{values['amount']:,} VND"]
            media_fields = ["content_kind", "table_header", "section_path"]
        else:
            media_query = (
                f"Biểu đồ tiến độ của quy định {values['topic']} tại {values['faculty']} cho biết "
                "tỷ lệ hoàn tất Quý II là bao nhiêu?"
            )
            media_terms = [f"Quý II {values['rate']}%"]
            media_fields = ["content_kind", "figure_caption", "section_path"]
        tests.append(
            _test_case(
                values=values,
                primary_slice="table_visual",
                query=media_query,
                relevant_chunk_ids=[f"{policy_v2}:{media_suffix}"],
                difficulty="hard",
                required_metadata_fields=media_fields,
                must_include_terms=media_terms,
                forbidden_chunk_ids=[f"{policy_v1}:{media_suffix}"],
            )
        )
        tests.append(
            _test_case(
                values=values,
                primary_slice="multi_hop",
                query=(
                    f"Kết hợp quy định hiện hành và báo cáo mới nhất của {values['faculty']} về "
                    f"{values['topic']}: thời hạn xử lý là bao lâu và có bao nhiêu hồ sơ hoàn tất?"
                ),
                relevant_chunk_ids=[f"{policy_v2}:procedure", f"mb:s{scenario:02d}:report:latest"],
                relevant_chunk_groups=[
                    [f"{policy_v2}:procedure"],
                    [f"mb:s{scenario:02d}:report:latest"],
                ],
                target_type="multi_hop",
                difficulty="hard",
                required_metadata_fields=[
                    "faculty",
                    "document_type",
                    "effective_status",
                    "lifecycle_status",
                ],
                metadata_conditions=[_condition("faculty", values["faculty"])],
                must_include_terms=[
                    f"{values['deadline']} ngày làm việc",
                    f"{values['completed']} hồ sơ",
                ],
                forbidden_document_titles=[old_policy_title, old_report_title],
            )
        )
        tests.append(
            _test_case(
                values=values,
                primary_slice="null_insufficient",
                query=(
                    f"Có báo cáo năm 2027 của {values['faculty']}, loại report, nguồn Kho lưu trữ "
                    f"ngoài trường về {values['topic']} không?"
                ),
                target_type="null",
                answerable=False,
                difficulty="hard",
                required_metadata_fields=["year", "faculty", "document_type", "source"],
                metadata_conditions=[
                    _condition("year", 2027),
                    _condition("faculty", values["faculty"]),
                    _condition("document_type", "report"),
                    _condition("source", "Kho lưu trữ ngoài trường"),
                ],
            )
        )
        protected_id = f"mb:s{scenario:02d}:restricted:budget"
        tests.append(
            _test_case(
                values=values,
                primary_slice="permission_sensitive",
                query=(
                    f"Trong tài liệu mật về {values['topic']}, mã dự toán bảo mật "
                    f"{values['secret_code']} là gì?"
                ),
                target_type="permission",
                answerable=False,
                difficulty="hard",
                protected_chunk_ids=[protected_id],
                required_metadata_fields=[
                    "owner_id",
                    "notebook_id",
                    "visibility",
                    "allowed_groups",
                ],
                query_context={
                    "owner_id": OWNER_ID,
                    "notebook_id": RESTRICTED_NOTEBOOK_ID,
                    "groups": ["sinh-vien"],
                },
            )
        )
    return tests


def _validate(corpus: list[dict[str, Any]], tests: list[dict[str, Any]]) -> None:
    chunk_ids = [row["chunk_id"] for row in corpus]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Corpus contains duplicate chunk IDs")
    test_ids = [row["id"] for row in tests]
    if len(test_ids) != len(set(test_ids)):
        raise ValueError("Testset contains duplicate query IDs")
    known = set(chunk_ids)
    referenced: set[str] = set()
    for test in tests:
        referenced.update(test["relevant_chunk_ids"])
        referenced.update(test["protected_chunk_ids"])
        referenced.update(test["forbidden_chunk_ids"])
        for group in test["relevant_chunk_groups"]:
            referenced.update(group)
    missing = sorted(referenced - known)
    if missing:
        raise ValueError(f"Ground truth references missing chunks: {missing[:5]}")
    primary_counts = Counter(row["primary_slice"] for row in tests)
    if set(primary_counts) != set(PRIMARY_SLICES):
        raise ValueError(f"Unexpected primary slices: {sorted(primary_counts)}")
    if any(primary_counts[name] < 30 for name in PRIMARY_SLICES):
        raise ValueError(f"Every primary slice must have at least 30 cases: {primary_counts}")
    if not 200 <= len(tests) <= 300:
        raise ValueError(f"Benchmark size must be 200-300, got {len(tests)}")


def build_benchmark() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    corpus, scenarios = build_corpus()
    tests = build_testset(scenarios)
    _validate(corpus, tests)
    primary_counts = Counter(row["primary_slice"] for row in tests)
    all_slice_counts = Counter(
        slice_name for row in tests for slice_name in row["benchmark_slices"]
    )
    field_counts = Counter(field for row in tests for field in row["required_metadata_fields"])
    manifest = {
        "schema_version": "2.0",
        "name": "metadata_retrieval_controlled_benchmark",
        "version": "2026-08-04.v2",
        "benchmark_kind": "controlled_synthetic",
        "language": "vi",
        "query_count": len(tests),
        "chunk_count": len(corpus),
        "scenario_count": len(scenarios),
        "primary_slice_counts": dict(sorted(primary_counts.items())),
        "all_slice_counts": dict(sorted(all_slice_counts.items())),
        "required_metadata_field_counts": dict(sorted(field_counts.items())),
        "split_counts": dict(sorted(Counter(row["split"] for row in tests).items())),
        "ground_truth": {
            "single_chunk": "relevant_chunk_ids",
            "multi_hop": "relevant_chunk_groups; all groups are required",
            "null": "no matching chunk; success requires an empty retrieval result",
            "permission": "protected_chunk_ids must never be returned",
        },
        "filter_evaluation": {
            "policy": "Apply only query filters supported by fields present in each mode.",
            "purpose": "Isolate index metadata quality from natural-language filter parsing.",
        },
        "recommended_metrics": {
            "answerable_recall_at_5_min": 0.85,
            "multi_hop_all_groups_at_10_min": 0.80,
            "null_rejection_at_10_min": 0.95,
            "permission_leak_at_10_max": 0.0,
        },
        "limitations": [
            "Synthetic stress data validates metadata behavior, not production-domain accuracy.",
            "Table/visual cases evaluate retrieval after text/caption extraction, not OCR quality.",
            (
                "Use the uploaded-document pilot and later 200-300 real queries before "
                "production sign-off."
            ),
        ],
        "outputs": {
            "corpus": CORPUS_PATH.name,
            "testset": TESTSET_PATH.name,
            "queries": QUERIES_PATH.name,
            "slice_distribution": SLICE_DISTRIBUTION_PATH.name,
        },
    }
    return corpus, tests, manifest


def main() -> None:
    corpus, tests, manifest = build_benchmark()
    _write_jsonl(CORPUS_PATH, corpus)
    _write_jsonl(TESTSET_PATH, tests)
    query_rows = [
        {
            "query_id": row["id"],
            "scenario_id": row["scenario_id"],
            "split": row["split"],
            "primary_slice": row["primary_slice"],
            "benchmark_slices": " | ".join(row["benchmark_slices"]),
            "query": row["query"],
            "answerable": row["answerable"],
            "target_type": row["target_type"],
            "required_metadata_fields": " | ".join(row["required_metadata_fields"]),
            "relevant_chunk_ids": " | ".join(row["relevant_chunk_ids"]),
            "protected_chunk_ids": " | ".join(row["protected_chunk_ids"]),
            "metadata_conditions": json.dumps(
                row["retrieval_filters"]["metadata_conditions"], ensure_ascii=False
            ),
        }
        for row in tests
    ]
    _write_csv(QUERIES_PATH, query_rows)
    primary_counts = Counter(row["primary_slice"] for row in tests)
    all_counts = Counter(name for row in tests for name in row["benchmark_slices"])
    _write_csv(
        SLICE_DISTRIBUTION_PATH,
        [
            {
                "slice": name,
                "primary_query_count": primary_counts[name],
                "all_tagged_query_count": all_counts[name],
                "minimum_required": 30,
                "passes_minimum": all_counts[name] >= 30,
            }
            for name in PRIMARY_SLICES
        ],
    )
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(corpus)} chunks to {CORPUS_PATH}")
    print(f"Wrote {len(tests)} queries to {TESTSET_PATH}")
    print(f"Wrote query review CSV to {QUERIES_PATH}")
    print(f"Wrote benchmark manifest to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
