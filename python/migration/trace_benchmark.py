"""Run the fixed synthetic trace defect-injection benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase
from migration.cli_io import configure_utf8_stdio
from migration.schema import Framework, SchemaError
from migration.trace_compare import compare_traces, load_trace_jsonl

DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "trace_cases"
    / "manifest.json"
)


def run_benchmark(
    manifest_path: str | Path = DEFAULT_MANIFEST,
    knowledge_base_path: str | Path = DEFAULT_KNOWLEDGE_BASE,
    minimum_top1: float = 0.8,
) -> dict[str, Any]:
    if not 0 <= minimum_top1 <= 1:
        raise ValueError("minimum_top1 must be between zero and one")
    manifest_path = Path(manifest_path).resolve()
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SchemaError("benchmark manifest must contain a non-empty cases array")
    knowledge = MappingKnowledgeBase.load(knowledge_base_path)
    results = []
    classification_correct = 0
    category_correct = 0
    top1_correct = 0
    defect_count = 0
    for case in cases:
        source_path = _artifact_path(root, case.get("source"))
        target_path = _artifact_path(root, case.get("target"))
        source = load_trace_jsonl(source_path, Framework.PYTORCH)
        target = load_trace_jsonl(target_path, Framework.MINDSPORE)
        comparison = compare_traces(source, target, knowledge)
        expected_equivalent = case.get("equivalent")
        if not isinstance(expected_equivalent, bool):
            raise SchemaError(f"case {case.get('id')} has no boolean equivalent label")
        classification_match = comparison.equivalent == expected_equivalent
        classification_correct += int(classification_match)
        category_match = None
        top1_match = None
        actual_category = None
        actual_source_call_index = None
        if not expected_equivalent:
            defect_count += 1
            if comparison.diagnostic is not None:
                actual_category = comparison.diagnostic.category.value
                actual_source_call_index = comparison.diagnostic.metadata.get(
                    "source_call_index"
                )
            category_match = actual_category == case.get("category")
            top1_match = actual_source_call_index == case.get("source_call_index")
            category_correct += int(category_match)
            top1_correct += int(top1_match)
        results.append(
            {
                "id": case.get("id"),
                "classification_correct": classification_match,
                "category_correct": category_match,
                "top1_correct": top1_match,
                "actual_category": actual_category,
                "actual_source_call_index": actual_source_call_index,
            }
        )
    top1_accuracy = top1_correct / defect_count if defect_count else 0.0
    category_accuracy = category_correct / defect_count if defect_count else 0.0
    return {
        "benchmark_version": manifest.get("benchmark_version", "unknown"),
        "dataset_kind": "synthetic_defect_injection",
        "source_framework_version": knowledge.payload["source_framework"]["version"],
        "target_framework_version": knowledge.payload["target_framework"]["version"],
        "case_count": len(cases),
        "defect_case_count": defect_count,
        "classification_accuracy": classification_correct / len(cases),
        "category_accuracy": category_accuracy,
        "top1_accuracy": top1_accuracy,
        "minimum_top1": minimum_top1,
        "passed": top1_accuracy >= minimum_top1,
        "cases": results,
    }


def _artifact_path(root: Path, relative_path: Any) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise SchemaError("benchmark artifact path must be a non-empty string")
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise SchemaError("benchmark artifact must stay inside the manifest directory")
    return path


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--minimum-top1", type=float, default=0.8)
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = run_benchmark(
            arguments.manifest,
            arguments.knowledge_base,
            arguments.minimum_top1,
        )
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
