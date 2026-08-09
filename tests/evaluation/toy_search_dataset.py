"""Dữ liệu GIẢ (fictional) để kiểm tra harness đo — KHÔNG phải ground truth
thật của dự án. Khi có tài liệu/câu hỏi thật, thay corpus và
``GROUND_TRUTH`` bằng dữ liệu thật, giữ nguyên harness.

Cố tình có "chunk gây nhiễu" (cùng chủ đề, khác nội dung — vd doanh thu quý
2/3/4) để Recall@k có ý nghĩa: nếu corpus không có gì để nhầm lẫn, mọi mode
đều đạt 100% một cách vô nghĩa. Câu hỏi cũng cố tình trộn loại: khớp từ khoá
chính xác VS diễn đạt khác chữ (paraphrase) — xem cột ``category``.
"""

from __future__ import annotations

from app.retrieval.domain.models import EvidenceChunk, RetrievalFilters
from tests.evaluation.search_method_evaluation import GroundTruthExample

OWNER_ID = "eval-user"

CORPUS: tuple[EvidenceChunk, ...] = (
    EvidenceChunk(
        id="c1",
        document_id="doc-1",
        text="Doanh thu quý 3 của công ty đạt 5 tỷ đồng, tăng 20% so với quý 2.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c2",
        document_id="doc-1",
        text="Doanh thu quý 2 của công ty đạt 4.2 tỷ đồng.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c3",
        document_id="doc-1",
        text="Doanh thu quý 4 dự kiến đạt 6 tỷ đồng theo kế hoạch.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c4",
        document_id="doc-1",
        text="Trưởng phòng kinh doanh là bà Nguyễn Thị B, phụ trách từ năm 2022.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c5",
        document_id="doc-1",
        text="Trưởng phòng kỹ thuật là ông Trần Văn C, phụ trách từ năm 2020.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c6",
        document_id="doc-1",
        text="Chi phí vận hành quý 3 là 2 tỷ đồng, chủ yếu cho nhân sự và marketing.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c7",
        document_id="doc-1",
        text="Chi phí vận hành quý 2 là 1.8 tỷ đồng.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c8",
        document_id="doc-1",
        text="Lợi nhuận ròng quý 3 đạt 1.5 tỷ đồng sau khi trừ các khoản chi phí.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c9",
        document_id="doc-1",
        text="Công ty có tổng cộng 150 nhân viên tính đến cuối quý 3.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c10",
        document_id="doc-1",
        text="Văn phòng chính đặt tại quận 1, thành phố Hồ Chí Minh.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c11",
        document_id="doc-1",
        text="Sản phẩm chủ lực của công ty là phần mềm quản lý bán hàng.",
        metadata={"owner_id": OWNER_ID},
    ),
    EvidenceChunk(
        id="c12",
        document_id="doc-1",
        text="Đối thủ cạnh tranh chính trong ngành là công ty XYZ.",
        metadata={"owner_id": OWNER_ID},
    ),
)

# (question, expected_chunk_id, category)
_ROWS: tuple[tuple[str, str, str], ...] = (
    ("Doanh thu quý 3 là bao nhiêu?", "c1", "exact_keyword_with_distractor"),
    ("Ai là trưởng phòng kinh doanh?", "c4", "exact_keyword_with_distractor"),
    ("Chi phí vận hành quý 3 là bao nhiêu?", "c6", "exact_keyword_with_distractor"),
    ("Lợi nhuận quý 3 của công ty là bao nhiêu?", "c8", "partial_paraphrase"),
    ("Công ty có bao nhiêu nhân viên?", "c9", "exact_keyword"),
    ("Trụ sở công ty ở đâu?", "c10", "paraphrase"),
    ("Sản phẩm chính của công ty là gì?", "c11", "paraphrase"),
    ("Ai đứng đầu bộ phận kỹ thuật?", "c5", "paraphrase"),
    ("Doanh thu quý 4 dự kiến bao nhiêu?", "c3", "exact_keyword_with_distractor"),
    ("Ai là đối thủ cạnh tranh của công ty?", "c12", "exact_keyword"),
)

GROUND_TRUTH: tuple[GroundTruthExample, ...] = tuple(
    GroundTruthExample(question=question, expected_chunk_id=expected_id, category=category)
    for question, expected_id, category in _ROWS
)

FILTERS = RetrievalFilters(owner_id=OWNER_ID)

__all__ = ["CORPUS", "FILTERS", "GROUND_TRUTH", "OWNER_ID"]
