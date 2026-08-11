"""Streamlit reviewer for duplicate, near-duplicate, and conflict detection."""

from __future__ import annotations

import hashlib
import html
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.knowledge_quality.application.analysis import (  # noqa: E402
    analyze_text_relation,
    build_document_fingerprint,
    is_auto_identity_eligible,
    strict_normalize_text,
)
from app.knowledge_quality.domain.models import DETECTOR_VERSION, RelationType  # noqa: E402
from app.pipeline.documents.adapters.parsers import ParserRegistry, TxtParser  # noqa: E402
from app.pipeline.documents.domain.parsed import ParsedDocument  # noqa: E402
from app.pipeline.indexing.application.chunker import ChunkData, Chunker  # noqa: E402

FEEDBACK_PATH = ROOT / "artifacts" / "quality_review" / "duplicate_conflict_feedback.jsonl"

RELATION_LABELS = {
    RelationType.EXACT_CONTENT.value: "Exact duplicate",
    RelationType.NEAR_DUPLICATE.value: "Near duplicate",
    RelationType.VERSION_CANDIDATE.value: "Version / thêm-sửa",
    RelationType.TEMPORAL_SERIES.value: "Chuỗi dữ liệu theo thời kỳ",
    RelationType.CONFLICT_CANDIDATE.value: "Conflict",
    RelationType.TEMPLATE_VARIANT.value: "Cùng mẫu, khác phạm vi",
    RelationType.DISTINCT.value: "Distinct",
    RelationType.RELATED.value: "Related",
}

RELATION_TONES = {
    RelationType.EXACT_CONTENT.value: "#d9f99d",
    RelationType.NEAR_DUPLICATE.value: "#fde68a",
    RelationType.VERSION_CANDIDATE.value: "#bae6fd",
    RelationType.TEMPORAL_SERIES.value: "#c7d2fe",
    RelationType.CONFLICT_CANDIDATE.value: "#fecaca",
    RelationType.TEMPLATE_VARIANT.value: "#e9d5ff",
    RelationType.DISTINCT.value: "#e5e7eb",
    RelationType.RELATED.value: "#ddd6fe",
}

REASON_LABELS = {
    "strict_content_match": "trùng strict text",
    "high_semantic_lexical_overlap": "trùng/gần trùng ngữ nghĩa-từ vựng",
    "high_content_containment": "một file bao hàm phần lớn file kia",
    "number_mismatch": "lệch số",
    "date_mismatch": "lệch ngày/thời điểm",
    "unit_mismatch": "lệch đơn vị",
    "negation_mismatch": "lệch phủ định",
    "policy_modality_mismatch": "lệch tính bắt buộc/cho phép/cấm",
    "insufficient_duplicate_evidence": "chưa đủ bằng chứng trùng",
}


@dataclass(frozen=True)
class SourceBundle:
    label: str
    name: str
    text: str
    parsed: ParsedDocument | None
    chunks: tuple[ChunkData, ...]
    strict_hash: str | None
    loose_signature: str | None
    raw_sha256: str | None
    warnings: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True)
class ChunkPairEvidence:
    old_index: int
    new_index: int
    old_text: str
    new_text: str
    relation_type: str
    confidence: float
    lexical_similarity: float
    containment: float
    semantic_similarity: float | None
    reason_codes: tuple[str, ...]
    score: float


def main() -> None:
    st.set_page_config(
        page_title="Duplicate / Conflict Review",
        page_icon="🔎",
        layout="wide",
    )
    _inject_css()

    st.title("Duplicate, Near Duplicate & Conflict Lab")
    st.caption(
        "Offline harness dùng parser + chunker + fingerprint + "
        "`analyze_text_relation`. Không ghi DB và không gọi Supabase/vector search."
    )

    with st.sidebar:
        st.header("Cấu hình detector")
        chunk_size = st.number_input("Chunk size", min_value=64, max_value=1024, value=256, step=32)
        overlap = st.number_input("Chunk overlap", min_value=0, max_value=256, value=32, step=8)
        min_chunk_score = st.slider("Ngưỡng hiện chunk liên quan", 0.0, 1.0, 0.35, 0.01)
        max_pairs = st.slider("Số cặp chunk tối đa", 5, 80, 20, 1)
        use_semantic = st.checkbox("Giả lập semantic similarity", value=False)
        semantic_similarity = None
        if use_semantic:
            semantic_similarity = st.slider("semantic_similarity", 0.0, 1.0, 0.90, 0.01)
        st.divider()

    input_left, input_right = st.columns(2)
    with input_left:
        old_source = _source_input("old", "File cũ / nguồn chuẩn", chunk_size, overlap)
    with input_right:
        new_source = _source_input("new", "File mới / nguồn cần kiểm tra", chunk_size, overlap)

    _render_source_status(old_source, new_source)

    if old_source.error or new_source.error:
        st.stop()
    if not old_source.text.strip() or not new_source.text.strip():
        st.info("Upload hai file hoặc nhập text hai phía để bắt đầu đánh giá.")
        st.stop()

    result = _build_result(
        old_source,
        new_source,
        semantic_similarity=semantic_similarity,
        min_chunk_score=min_chunk_score,
        max_pairs=max_pairs,
    )
    _feedback_sidebar(old_source, new_source, result)
    _render_result(old_source, new_source, result)


def _source_input(
    key: str,
    label: str,
    chunk_size: int,
    overlap: int,
) -> SourceBundle:
    st.subheader(label)
    registry = ParserRegistry()
    mode = st.radio(
        "Nguồn dữ liệu",
        ["Upload file", "Nhập text"],
        key=f"{key}_mode",
        horizontal=True,
    )
    if mode == "Upload file":
        uploaded = st.file_uploader(
            "Chọn file",
            type=list(registry.supported_extensions),
            key=f"{key}_file",
        )
        if uploaded is None:
            return _empty_source(label)
        content = uploaded.getvalue()
        return _parse_source(
            label=label,
            name=uploaded.name,
            content=content,
            chunk_size=chunk_size,
            overlap=overlap,
        )

    text = st.text_area(
        "Dán nội dung",
        height=280,
        key=f"{key}_text",
        placeholder="Dán nguyên văn đoạn/tài liệu cần kiểm tra...",
    )
    name = st.text_input("Tên nguồn", value=f"{key}_manual.txt", key=f"{key}_name")
    return _parse_text_source(
        label=label,
        name=name or f"{key}_manual.txt",
        text=text,
        chunk_size=chunk_size,
        overlap=overlap,
    )


def _empty_source(label: str) -> SourceBundle:
    return SourceBundle(
        label=label,
        name="",
        text="",
        parsed=None,
        chunks=(),
        strict_hash=None,
        loose_signature=None,
        raw_sha256=None,
        warnings=(),
    )


def _parse_text_source(
    *,
    label: str,
    name: str,
    text: str,
    chunk_size: int,
    overlap: int,
) -> SourceBundle:
    if not text.strip():
        return _empty_source(label)
    return _parse_source(
        label=label,
        name=name,
        content=text.encode("utf-8"),
        chunk_size=chunk_size,
        overlap=overlap,
        force_text=True,
    )


def _parse_source(
    *,
    label: str,
    name: str,
    content: bytes,
    chunk_size: int,
    overlap: int,
    force_text: bool = False,
) -> SourceBundle:
    raw_sha256 = hashlib.sha256(content).hexdigest()
    try:
        parsed = (
            TxtParser().parse(content)
            if force_text
            else ParserRegistry().get_parser(name).parse(content)
        )
        text = parsed.text or ""
        fingerprint = build_document_fingerprint(text)
        chunks = tuple(
            Chunker.structure_recursive(chunk_size=chunk_size, overlap=overlap).chunk(
                document_id=_stable_document_id(name, raw_sha256),
                version=1,
                parsed=parsed,
            )
        )
        return SourceBundle(
            label=label,
            name=name,
            text=text,
            parsed=parsed,
            chunks=chunks,
            strict_hash=fingerprint.strict_hash,
            loose_signature=fingerprint.loose_signature,
            raw_sha256=raw_sha256 if not force_text else None,
            warnings=tuple(str(item) for item in parsed.warnings),
        )
    except Exception as exc:
        return SourceBundle(
            label=label,
            name=name,
            text="",
            parsed=None,
            chunks=(),
            strict_hash=None,
            loose_signature=None,
            raw_sha256=raw_sha256,
            warnings=(),
            error=f"{type(exc).__name__}: {exc}",
        )


def _stable_document_id(name: str, content_hash: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"streamlit-quality-review:{name}:{content_hash}"))


def _render_source_status(old_source: SourceBundle, new_source: SourceBundle) -> None:
    for source in (old_source, new_source):
        if source.error:
            st.error(f"{source.label}: không đọc được `{source.name}`. {source.error}")
    if old_source.text or new_source.text:
        cols = st.columns(4)
        cols[0].metric("File cũ chunks", len(old_source.chunks))
        cols[1].metric("File mới chunks", len(new_source.chunks))
        cols[2].metric("File cũ ký tự", len(old_source.text))
        cols[3].metric("File mới ký tự", len(new_source.text))
        warnings = old_source.warnings + new_source.warnings
        if warnings:
            with st.expander("Cảnh báo extraction"):
                for warning in warnings:
                    st.warning(warning)


def _build_result(
    old_source: SourceBundle,
    new_source: SourceBundle,
    *,
    semantic_similarity: float | None,
    min_chunk_score: float,
    max_pairs: int,
) -> dict[str, object]:
    full_analysis = analyze_text_relation(
        old_source.text,
        new_source.text,
        semantic_similarity=semantic_similarity,
    )
    chunk_pairs = _chunk_pair_evidence(
        old_source.chunks,
        new_source.chunks,
        semantic_similarity=semantic_similarity,
        min_chunk_score=min_chunk_score,
        max_pairs=max_pairs,
    )
    exact_file_duplicate = (
        bool(old_source.raw_sha256)
        and old_source.raw_sha256 == new_source.raw_sha256
    )
    strict_content_duplicate = (
        bool(old_source.strict_hash)
        and old_source.strict_hash == new_source.strict_hash
        and is_auto_identity_eligible(build_document_fingerprint(old_source.text))
        and is_auto_identity_eligible(build_document_fingerprint(new_source.text))
    )
    predicted_relation = (
        "technical_duplicate"
        if exact_file_duplicate
        else (
            RelationType.EXACT_CONTENT.value
            if strict_content_duplicate
            else full_analysis.relation_type.value
        )
    )
    return {
        "analysis": full_analysis,
        "predicted_relation": predicted_relation,
        "chunk_pairs": chunk_pairs,
        "exact_file_duplicate": exact_file_duplicate,
        "strict_content_duplicate": strict_content_duplicate,
        "loose_signature_equal": (
            bool(old_source.loose_signature)
            and old_source.loose_signature == new_source.loose_signature
        ),
        "detector_version": DETECTOR_VERSION,
    }


def _chunk_pair_evidence(
    old_chunks: tuple[ChunkData, ...],
    new_chunks: tuple[ChunkData, ...],
    *,
    semantic_similarity: float | None,
    min_chunk_score: float,
    max_pairs: int,
) -> tuple[ChunkPairEvidence, ...]:
    pairs: list[ChunkPairEvidence] = []
    for old_chunk in old_chunks:
        for new_chunk in new_chunks:
            analysis = analyze_text_relation(
                old_chunk.text,
                new_chunk.text,
                semantic_similarity=semantic_similarity,
            )
            score = max(
                analysis.lexical_similarity,
                analysis.containment,
                analysis.semantic_similarity or 0.0,
            )
            if analysis.relation_type == RelationType.DISTINCT and score < min_chunk_score:
                continue
            pairs.append(
                ChunkPairEvidence(
                    old_index=old_chunk.chunk_index,
                    new_index=new_chunk.chunk_index,
                    old_text=old_chunk.text,
                    new_text=new_chunk.text,
                    relation_type=analysis.relation_type.value,
                    confidence=analysis.confidence,
                    lexical_similarity=analysis.lexical_similarity,
                    containment=analysis.containment,
                    semantic_similarity=analysis.semantic_similarity,
                    reason_codes=tuple(analysis.reason_codes),
                    score=score,
                )
            )
    return tuple(
        sorted(
            pairs,
            key=lambda item: (
                _relation_priority(item.relation_type),
                item.confidence,
                item.score,
            ),
            reverse=True,
        )[:max_pairs]
    )


def _relation_priority(relation_type: str) -> int:
    if "conflict" in relation_type:
        return 6
    if relation_type in {RelationType.VERSION_CANDIDATE.value, "version"}:
        return 5
    if relation_type == RelationType.TEMPORAL_SERIES.value:
        return 4
    if relation_type == RelationType.NEAR_DUPLICATE.value:
        return 3
    if relation_type == RelationType.TEMPLATE_VARIANT.value:
        return 2
    if relation_type == RelationType.EXACT_CONTENT.value:
        return 1
    if relation_type == RelationType.RELATED.value:
        return 0
    return -1


def _feedback_sidebar(
    old_source: SourceBundle,
    new_source: SourceBundle,
    result: dict[str, object],
) -> None:
    analysis = result["analysis"]
    predicted = str(result["predicted_relation"])
    case_id = _case_id(old_source, new_source)
    with st.sidebar:
        st.header("Đánh giá thủ công")
        st.caption(f"Case ID: `{case_id}`")
        with st.form("quality_feedback_form"):
            expected_relation = st.selectbox(
                "Nhãn đúng theo người đánh giá",
                [
                    "exact",
                    "near_duplicate",
                    "version",
                    "conflict",
                    "distinct",
                    "mixed",
                    "unclear",
                ],
                index=6,
            )
            judgment = st.radio(
                "Kết luận bắt có chuẩn không?",
                [
                    "Bắt đúng",
                    "Bắt thiếu duplicate/near",
                    "Bắt thiếu conflict",
                    "Bắt lầm duplicate/near",
                    "Bắt lầm conflict",
                    "Bắt lầm version",
                    "Không chắc",
                ],
            )
            precision_score = st.slider("Độ chuẩn khi bắt", 1, 5, 3)
            recall_score = st.slider("Độ đủ khi bắt", 1, 5, 3)

            with st.expander("Nếu bắt thiếu duplicate/near"):
                missing_dup_old = st.text_area("Đoạn bị thiếu ở file cũ", height=90)
                missing_dup_new = st.text_area("Đoạn bị thiếu ở file mới", height=90)
                missing_dup_note = st.text_area("Ghi chú thiếu duplicate/near", height=80)

            with st.expander("Nếu bắt thiếu conflict"):
                missing_conflict_types = st.multiselect(
                    "Loại conflict bị thiếu",
                    [
                        "date_mismatch",
                        "number_mismatch",
                        "unit_mismatch",
                        "negation_mismatch",
                        "policy_modality_mismatch",
                        "other",
                    ],
                )
                missing_conflict_old = st.text_area("Claim/đoạn conflict ở file cũ", height=90)
                missing_conflict_new = st.text_area("Claim/đoạn conflict ở file mới", height=90)
                missing_conflict_note = st.text_area("Ghi chú thiếu conflict", height=80)

            with st.expander("Nếu bắt lầm"):
                false_positive_types = st.multiselect(
                    "Loại bắt lầm",
                    [
                        "duplicate_false_positive",
                        "near_duplicate_false_positive",
                        "version_false_positive",
                        "conflict_false_positive",
                    ],
                )
                false_positive_old = st.text_area("Đoạn file cũ bị bắt lầm", height=90)
                false_positive_new = st.text_area("Đoạn file mới bị bắt lầm", height=90)
                false_positive_note = st.text_area("Vì sao là bắt lầm?", height=90)

            evaluator = st.text_input("Người đánh giá", value="")
            notes = st.text_area("Ghi chú chung", height=90)
            store_full_text = st.checkbox("Lưu full extracted text vào JSONL", value=False)
            submitted = st.form_submit_button("Lưu đánh giá")

        if submitted:
            record = {
                "schema_version": "quality-review-feedback-v1",
                "created_at": datetime.now(UTC).isoformat(),
                "case_id": case_id,
                "evaluator": evaluator.strip() or None,
                "source_name": old_source.name,
                "target_name": new_source.name,
                "source_sha256": old_source.raw_sha256,
                "target_sha256": new_source.raw_sha256,
                "predicted_relation": predicted,
                "predicted_confidence": round(float(analysis.confidence), 6),
                "predicted_reason_codes": list(analysis.reason_codes),
                "expected_relation": expected_relation,
                "judgment": judgment,
                "precision_score": precision_score,
                "recall_score": recall_score,
                "missing_duplicate": {
                    "old_segment": missing_dup_old,
                    "new_segment": missing_dup_new,
                    "note": missing_dup_note,
                },
                "missing_conflict": {
                    "types": missing_conflict_types,
                    "old_segment": missing_conflict_old,
                    "new_segment": missing_conflict_new,
                    "note": missing_conflict_note,
                },
                "false_positive": {
                    "types": false_positive_types,
                    "old_segment": false_positive_old,
                    "new_segment": false_positive_new,
                    "note": false_positive_note,
                },
                "notes": notes,
                "detector_version": DETECTOR_VERSION,
            }
            if store_full_text:
                record["source_text"] = old_source.text
                record["target_text"] = new_source.text
            _append_feedback(record)
            st.success(f"Đã lưu vào `{FEEDBACK_PATH.relative_to(ROOT)}`")

        if FEEDBACK_PATH.exists():
            st.download_button(
                "Tải feedback JSONL",
                data=FEEDBACK_PATH.read_text(encoding="utf-8"),
                file_name="duplicate_conflict_feedback.jsonl",
                mime="application/jsonl",
            )


def _case_id(old_source: SourceBundle, new_source: SourceBundle) -> str:
    raw = "|".join(
        [
            old_source.name,
            new_source.name,
            old_source.strict_hash or hashlib.sha256(old_source.text.encode()).hexdigest(),
            new_source.strict_hash or hashlib.sha256(new_source.text.encode()).hexdigest(),
        ]
    )
    return "manual-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _append_feedback(record: dict[str, object]) -> None:
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _render_result(
    old_source: SourceBundle,
    new_source: SourceBundle,
    result: dict[str, object],
) -> None:
    analysis = result["analysis"]
    predicted = str(result["predicted_relation"])
    reason_codes = [REASON_LABELS.get(code, code) for code in analysis.reason_codes]

    st.divider()
    st.subheader("Kết quả detector")
    summary_cols = st.columns([1.2, 1, 1, 1])
    summary_cols[0].markdown(_relation_badge(predicted), unsafe_allow_html=True)
    summary_cols[1].metric("Confidence", f"{analysis.confidence:.3f}")
    summary_cols[2].metric("Lexical", f"{analysis.lexical_similarity:.3f}")
    summary_cols[3].metric("Containment", f"{analysis.containment:.3f}")

    signal_cols = st.columns(4)
    signal_cols[0].metric("Exact file", "Có" if result["exact_file_duplicate"] else "Không")
    signal_cols[1].metric(
        "Strict content",
        "Trùng" if result["strict_content_duplicate"] else "Khác",
    )
    signal_cols[2].metric(
        "Loose signature",
        "Trùng" if result["loose_signature_equal"] else "Khác",
    )
    signal_cols[3].metric("Detector", str(result["detector_version"]))

    if reason_codes:
        st.caption("Lý do: " + ", ".join(reason_codes))

    tabs = st.tabs(
        [
            "Evidence chunk",
            "Claim conflict",
            "Diff toàn văn",
            "Extraction",
            "Fingerprint",
            "Feedback đã lưu",
        ]
    )
    with tabs[0]:
        _render_chunk_evidence(result)
    with tabs[1]:
        _render_claim_conflicts(analysis)
    with tabs[2]:
        _render_text_diff(old_source.text, new_source.text)
    with tabs[3]:
        _render_extraction(old_source, new_source)
    with tabs[4]:
        _render_fingerprints(old_source, new_source)
    with tabs[5]:
        _render_saved_feedback()


def _relation_badge(relation_type: str) -> str:
    label = RELATION_LABELS.get(relation_type, relation_type)
    color = RELATION_TONES.get(relation_type, "#e5e7eb")
    if relation_type == "technical_duplicate":
        label = "Technical exact file duplicate"
        color = "#bbf7d0"
    return (
        f"<div class='relation-badge' style='background:{color};'>"
        f"<strong>{html.escape(label)}</strong></div>"
    )


def _render_chunk_evidence(result: dict[str, object]) -> None:
    pairs = result["chunk_pairs"]
    if not pairs:
        st.info("Không có cặp chunk nào vượt ngưỡng hiện tại.")
        return

    rows = [
        {
            "old_chunk": pair.old_index,
            "new_chunk": pair.new_index,
            "relation": pair.relation_type,
            "confidence": round(pair.confidence, 3),
            "lexical": round(pair.lexical_similarity, 3),
            "containment": round(pair.containment, 3),
            "score": round(pair.score, 3),
            "reason": ", ".join(pair.reason_codes),
        }
        for pair in pairs
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    selected = st.selectbox(
        "Xem chi tiết cặp chunk",
        range(len(pairs)),
        format_func=lambda idx: (
            f"#{idx + 1}: old {pairs[idx].old_index} ↔ new {pairs[idx].new_index} "
            f"({pairs[idx].relation_type}, {pairs[idx].confidence:.2f})"
        ),
    )
    pair = pairs[selected]
    cols = st.columns(2)
    cols[0].markdown("**File cũ**")
    cols[0].code(pair.old_text, language="text")
    cols[1].markdown("**File mới**")
    cols[1].code(pair.new_text, language="text")
    _render_text_diff(pair.old_text, pair.new_text, compact=True)


def _render_claim_conflicts(analysis: object) -> None:
    conflicts = list(getattr(analysis, "claim_conflicts", ()) or ())
    if not conflicts:
        st.info("Không có claim conflict chi tiết được detector trích xuất.")
        return
    for index, conflict in enumerate(conflicts, start=1):
        payload = conflict.to_signal()
        with st.expander(f"Conflict claim #{index}", expanded=index == 1):
            st.write(
                {
                    "alignment_score": payload["alignment_score"],
                    "reason_codes": payload["reason_codes"],
                }
            )
            cols = st.columns(2)
            cols[0].markdown("**File cũ**")
            cols[0].write(payload["left"]["text"])
            cols[0].json(payload["left"]["values"])
            cols[1].markdown("**File mới**")
            cols[1].write(payload["right"]["text"])
            cols[1].json(payload["right"]["values"])


def _render_text_diff(old_text: str, new_text: str, *, compact: bool = False) -> None:
    old_lines = _diff_lines(old_text, compact=compact)
    new_lines = _diff_lines(new_text, compact=compact)
    matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    parts: list[str] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            for line in old_lines[old_start:old_end]:
                parts.append(f"<div class='diff-line same'>{html.escape(line)}</div>")
        elif tag == "delete":
            for line in old_lines[old_start:old_end]:
                parts.append(f"<div class='diff-line old'>- {html.escape(line)}</div>")
        elif tag == "insert":
            for line in new_lines[new_start:new_end]:
                parts.append(f"<div class='diff-line new'>+ {html.escape(line)}</div>")
        else:
            for line in old_lines[old_start:old_end]:
                parts.append(f"<div class='diff-line old'>- {html.escape(line)}</div>")
            for line in new_lines[new_start:new_end]:
                parts.append(f"<div class='diff-line new'>+ {html.escape(line)}</div>")
    st.markdown("<div class='diff-box'>" + "".join(parts) + "</div>", unsafe_allow_html=True)


def _diff_lines(text: str, *, compact: bool) -> list[str]:
    lines = [strict_normalize_text(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if compact:
        return lines[:120]
    return lines[:800]


def _render_extraction(old_source: SourceBundle, new_source: SourceBundle) -> None:
    cols = st.columns(2)
    for col, source in zip(cols, [old_source, new_source], strict=True):
        col.markdown(f"**{source.label}**")
        col.caption(source.name)
        col.text_area(
            "Extracted text",
            value=source.text,
            height=420,
            key=f"extracted_{source.label}",
            disabled=True,
        )


def _render_fingerprints(old_source: SourceBundle, new_source: SourceBundle) -> None:
    rows = [
        {
            "side": "file_cu",
            "strict_hash": old_source.strict_hash,
            "loose_signature": old_source.loose_signature,
            "raw_sha256": old_source.raw_sha256,
        },
        {
            "side": "file_moi",
            "strict_hash": new_source.strict_hash,
            "loose_signature": new_source.loose_signature,
            "raw_sha256": new_source.raw_sha256,
        },
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_saved_feedback() -> None:
    if not FEEDBACK_PATH.exists():
        st.info("Chưa có feedback nào được lưu.")
        return
    lines = FEEDBACK_PATH.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines[-50:] if line.strip()]
    st.caption(f"Hiển thị {len(records)} feedback cuối. File: `{FEEDBACK_PATH.relative_to(ROOT)}`")
    st.dataframe(records, use_container_width=True, hide_index=True)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .relation-badge {
            border: 1px solid rgba(0,0,0,.12);
            border-radius: 8px;
            color: #111827;
            padding: .7rem .85rem;
            text-align: center;
        }
        .diff-box {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: .82rem;
            max-height: 520px;
            overflow: auto;
            padding: .5rem;
        }
        .diff-line {
            border-radius: 4px;
            margin: 1px 0;
            padding: .18rem .35rem;
            white-space: pre-wrap;
        }
        .diff-line.same { color: #374151; }
        .diff-line.old { background: #fee2e2; color: #991b1b; }
        .diff-line.new { background: #dcfce7; color: #166534; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
