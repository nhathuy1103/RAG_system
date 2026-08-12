import json
from pathlib import Path


def test_final_dev_report_meets_p1_acceptance_and_preserves_safety() -> None:
    report = json.loads(
        Path("reports/evaluation/p1_candidate_generation_dev.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["split"] == "dev"
    assert report["frozen_gold_unchanged"] is True
    assert report["candidate_generation"]["recall@50"] >= 0.95
    assert report["safety"]["false_auto_reuse_count"] == 0
    assert report["stress"]["long_document"]["eligible_probe_coverage"] == 1.0
    assert report["stress"]["simhash_counterexample"]["recovered_by_selected_binary"]
    assert {"channel_k_15", "channel_k_30", "channel_k_50"} <= set(
        report["parameter_sweeps"]
    )
