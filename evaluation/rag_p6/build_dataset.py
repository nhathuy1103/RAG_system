"""Build deterministic, scenario-diverse P6 DEV/TEST query fixtures."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "datasets" / "rag_p6"

SCENARIOS = (
    "simple_factual",
    "historical_explicit_year",
    "current_latest",
    "temporal_comparison",
    "followup_year_override",
    "followup_qualifier_override",
    "duplicate_heavy",
    "methodology_vs_value",
    "version_comparison",
    "conflict",
    "conditional_variant",
    "uncertain_evidence",
    "table_fact",
    "prose_fact",
    "multi_document_comparison",
    "permission_sensitive",
)

DEV_SUBJECTS = (
    ("Grand Park", "price", "giá", "48 triệu đồng/m2"),
    ("Ocean Park", "price", "giá", "52 triệu đồng/m2"),
    ("Smart City", "fee", "phí dịch vụ", "18 nghìn đồng/m2"),
    ("VF8 Eco", "driving_range", "phạm vi", "450 km"),
    ("VF9 Plus", "driving_range", "phạm vi", "520 km"),
    ("VinFast", "revenue", "doanh thu", "65 nghìn tỷ đồng"),
    ("Vinhomes", "revenue", "doanh thu", "120 nghìn tỷ đồng"),
    ("Central Park", "area", "diện tích", "43 ha"),
    ("Green Bay", "quantity", "số căn", "3.000 căn"),
    ("Times City", "capacity", "công suất", "1.200 chỗ"),
)

TEST_SUBJECTS = (
    ("Royal Island", "price", "giá", "61 triệu đồng/m2"),
    ("VF7 Base", "driving_range", "phạm vi", "375 km"),
    ("Vinmec", "capacity", "công suất", "500 giường"),
    ("Vinpearl", "revenue", "doanh thu", "42 nghìn tỷ đồng"),
)


def _row(split: str, index: int, scenario: str, subject: tuple[str, ...]) -> dict[str, object]:
    entity, predicate, label, value = subject
    query = f"{label.capitalize()} {entity} năm 2025 là bao nhiêu?"
    history: list[str] = []
    if scenario == "historical_explicit_year":
        query = f"{label.capitalize()} {entity} năm 2023 là bao nhiêu?"
    elif scenario == "current_latest":
        query = f"{label.capitalize()} {entity} hiện tại là bao nhiêu?"
    elif scenario in {"temporal_comparison", "multi_document_comparison"}:
        query = f"So sánh {label} {entity} qua các năm 2023, 2025 và 2026"
    elif scenario == "followup_year_override":
        history = [f"So sánh {label} {entity} qua các năm"]
        query = "2025 thì sao?"
    elif scenario == "followup_qualifier_override":
        history = [f"{entity} WLTP đi được bao xa?"]
        query = "EPA thì sao?"
    elif scenario == "duplicate_heavy":
        query = f"{label.capitalize()} {entity} năm 2025?"
    elif scenario == "methodology_vs_value":
        query = f"{label.capitalize()} thực tế của {entity} năm 2025?"
    elif scenario == "version_comparison":
        query = f"Bản 2023 và 2026 ghi {label} {entity} thế nào?"
    elif scenario == "conflict":
        query = f"Các nguồn có mâu thuẫn về {label} {entity} năm 2025 không?"
    elif scenario == "conditional_variant":
        query = f"Phạm vi EPA của {entity} là bao nhiêu?"
    elif scenario == "uncertain_evidence":
        query = f"Có chắc {label} {entity} năm 2025 là {value} không?"
    elif scenario == "table_fact":
        query = f"Trong bảng, {label} {entity} năm 2025 là bao nhiêu?"
    elif scenario == "prose_fact":
        query = f"Đoạn mô tả nêu {label} {entity} năm 2025 thế nào?"
    elif scenario == "permission_sensitive":
        query = f"{label.capitalize()} {entity} năm 2025 theo mọi tài liệu?"
    return {
        "id": f"p6-{split}-{index:04d}",
        "scenario": scenario,
        "query": query,
        "history": history,
        "entity": entity,
        "predicate": predicate,
        "predicate_label": label,
        "value": value,
    }


def build() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for split, subjects in (("dev", DEV_SUBJECTS), ("test", TEST_SUBJECTS)):
        rows = [
            _row(split, index, scenario, subject)
            for index, (scenario, subject) in enumerate(
                ((scenario, subject) for subject in subjects for scenario in SCENARIOS),
                start=1,
            )
        ]
        path = OUTPUT / f"enterprise_p6_queries_v1_{split}.jsonl"
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        print(f"{split}: {len(rows)} -> {path}")


if __name__ == "__main__":
    build()
