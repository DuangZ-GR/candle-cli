"""Run the fixed AST scanner precision/recall benchmark."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from migration.scanner import scan_path

DEFAULT_MANIFEST = (
    Path(__file__).parents[2] / "benchmarks" / "manifests" / "scanner_v1.json"
)


def run_benchmark(manifest_path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    true_positive = 0
    false_positive = 0
    false_negative = 0
    exact_cases = 0
    failures = []

    with tempfile.TemporaryDirectory(prefix="candle-cli-scanner-bench-") as directory:
        benchmark_root = Path(directory)
        for case in manifest["cases"]:
            case_file = benchmark_root / f"{case['id']}.py"
            case_file.write_text(case["source"], encoding="utf-8")
            actual = Counter(item.api for item in scan_path(case_file).findings)
            expected = Counter(case["expected_apis"])
            matched = actual & expected
            case_true_positive = sum(matched.values())
            case_false_positive = sum((actual - expected).values())
            case_false_negative = sum((expected - actual).values())
            true_positive += case_true_positive
            false_positive += case_false_positive
            false_negative += case_false_negative
            if case_false_positive == 0 and case_false_negative == 0:
                exact_cases += 1
            else:
                failures.append(
                    {
                        "case_id": case["id"],
                        "expected": sorted(expected.elements()),
                        "actual": sorted(actual.elements()),
                    }
                )

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 1.0
    recall = true_positive / recall_denominator if recall_denominator else 1.0
    task_count = len(manifest["cases"])
    return {
        "benchmark_id": manifest["benchmark_id"],
        "task_count": task_count,
        "exact_case_count": exact_cases,
        "exact_case_rate": exact_cases / task_count if task_count else 1.0,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--min-precision", type=float, default=0.95)
    parser.add_argument("--min-recall", type=float, default=0.95)
    arguments = parser.parse_args(argv)

    result = run_benchmark(arguments.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["precision"] < arguments.min_precision:
        return 1
    if result["recall"] < arguments.min_recall:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
