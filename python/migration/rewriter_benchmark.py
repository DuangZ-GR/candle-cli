"""Run the fixed deterministic rewrite development benchmark."""

from __future__ import annotations

import argparse
import ast
import json
import tempfile
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.rewriter import plan_rewrite

DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "rewrite_cases"
    / "manifest.json"
)


def run_benchmark(manifest_path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("rewrite benchmark manifest must contain cases")
    results = []
    correct = 0
    skip_count = 0
    safe_skip_correct = 0
    syntax_valid = 0
    with tempfile.TemporaryDirectory(prefix="candle-rewrite-benchmark-") as directory:
        root = Path(directory)
        for index, case in enumerate(cases):
            source_path = root / f"case_{index}.py"
            source_path.write_text(case["source"], encoding="utf-8", newline="")
            plan = plan_rewrite(
                source_path,
                include_differences=bool(case.get("include_differences", False)),
            )
            actual = plan.files[0].patched_source if plan.files else None
            expected = case.get("expected")
            matches = actual == expected
            correct += int(matches)
            syntax_ok = actual is None
            if actual is not None:
                try:
                    ast.parse(actual)
                    syntax_ok = True
                except SyntaxError:
                    syntax_ok = False
            syntax_valid += int(syntax_ok)
            if expected is None:
                skip_count += 1
                safe_skip_correct += int(actual is None)
            results.append(
                {
                    "id": case.get("id"),
                    "correct": matches,
                    "syntax_valid": syntax_ok,
                    "expected_skip": expected is None,
                }
            )
    case_count = len(cases)
    return {
        "benchmark_version": manifest.get("benchmark_version", "unknown"),
        "dataset_kind": "synthetic_rewrite_development_set",
        "case_count": case_count,
        "expected_skip_count": skip_count,
        "exact_patch_accuracy": correct / case_count,
        "safe_skip_accuracy": safe_skip_correct / skip_count if skip_count else 0.0,
        "syntax_valid_rate": syntax_valid / case_count,
        "passed": correct == case_count and syntax_valid == case_count,
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = run_benchmark(arguments.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
