from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.pipeline.documents.extraction.evaluation.benchmark_governance import (
    check_frozen_benchmark,
    freeze_benchmark_v1,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze or verify an extraction benchmark.")
    parser.add_argument("benchmark_dir", type=Path)
    parser.add_argument("--check", action="store_true", help="verify freeze checksums")
    parser.add_argument(
        "--apply-readonly",
        action="store_true",
        help="mark protected benchmark files read-only after writing freeze metadata",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = (
        check_frozen_benchmark(args.benchmark_dir)
        if args.check
        else freeze_benchmark_v1(args.benchmark_dir, apply_readonly=args.apply_readonly)
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if payload.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
