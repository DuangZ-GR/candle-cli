"""Capture and evaluate deterministic PyTorch/MindSpore runtime parity cases."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase
from migration.schema import ExecutionMode, Framework, SchemaError
from migration.trace_capture import TraceRecorder
from migration.trace_compare import compare_traces, load_trace_jsonl

DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "runtime_parity_v1.json"
)
DATASET_KIND = "deterministic_cross_framework_microcases"


@dataclass(frozen=True)
class RuntimeCase:
    case_id: str
    operations: tuple[str, ...]
    expected_equivalent: bool


@dataclass(frozen=True)
class RuntimeManifest:
    benchmark_version: str
    source_version_prefix: str
    target_version_prefix: str
    relative_tolerance: float
    absolute_tolerance: float
    cases: tuple[RuntimeCase, ...]


SOURCE_APIS = {
    "add": "torch.add",
    "sum": "torch.sum",
    "reshape": "torch.reshape",
    "unsqueeze": "torch.unsqueeze",
    "matmul": "torch.matmul",
    "mean": "torch.mean",
    "relu": "torch.nn.functional.relu",
    "cat": "torch.cat",
    "flatten": "torch.flatten",
}
TARGET_APIS = {
    "add": "mindspore.mint.add",
    "sum": "mindspore.mint.sum",
    "reshape": "mindspore.mint.reshape",
    "unsqueeze": "mindspore.mint.unsqueeze",
    "matmul": "mindspore.mint.matmul",
    "mean": "mindspore.mint.mean",
    "relu": "mindspore.mint.nn.functional.relu",
    "cat": "mindspore.mint.cat",
    "flatten": "mindspore.mint.flatten",
}
CASE_OPERATIONS = {
    "elementwise-reduction": ("add", "sum"),
    "shape-transform": ("reshape", "unsqueeze"),
    "matrix-reduction": ("matmul", "mean"),
    "activation-reduction": ("relu", "sum"),
    "concatenate-flatten": ("cat", "flatten"),
}


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> RuntimeManifest:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0":
        raise SchemaError("unsupported runtime parity schema_version")
    if document.get("dataset_kind") != DATASET_KIND:
        raise SchemaError("unsupported runtime parity dataset_kind")
    benchmark_version = _required_string(document, "benchmark_version")
    source = document.get("source_framework")
    target = document.get("target_framework")
    if not isinstance(source, dict) or source.get("name") != "pytorch":
        raise SchemaError("runtime parity source framework must be pytorch")
    if not isinstance(target, dict) or target.get("name") != "mindspore":
        raise SchemaError("runtime parity target framework must be mindspore")
    source_prefix = _required_string(source, "version_prefix")
    target_prefix = _required_string(target, "version_prefix")
    relative_tolerance = _non_negative_number(document, "relative_tolerance")
    absolute_tolerance = _non_negative_number(document, "absolute_tolerance")
    values = document.get("cases")
    if not isinstance(values, list) or not values:
        raise SchemaError("runtime parity manifest requires cases")
    cases = []
    identifiers = set()
    for value in values:
        if not isinstance(value, dict):
            raise SchemaError("runtime parity case must be an object")
        case_id = _required_string(value, "id")
        if case_id in identifiers:
            raise SchemaError("runtime parity case ids must be unique")
        operations = value.get("operations")
        if not isinstance(operations, list) or not all(
            isinstance(item, str) and item in SOURCE_APIS for item in operations
        ):
            raise SchemaError(f"runtime parity case {case_id} has invalid operations")
        expected = CASE_OPERATIONS.get(case_id)
        if expected is None or tuple(operations) != expected:
            raise SchemaError(f"runtime parity case {case_id} does not match built-in case")
        equivalent = value.get("expected_equivalent")
        if not isinstance(equivalent, bool):
            raise SchemaError(f"runtime parity case {case_id} requires expected_equivalent")
        identifiers.add(case_id)
        cases.append(RuntimeCase(case_id, tuple(operations), equivalent))
    if identifiers != set(CASE_OPERATIONS):
        raise SchemaError("runtime parity manifest must contain every built-in case once")
    return RuntimeManifest(
        benchmark_version,
        source_prefix,
        target_prefix,
        relative_tolerance,
        absolute_tolerance,
        tuple(cases),
    )


class _Backend:
    def __init__(self, framework: Framework, module: Any):
        self.framework = framework
        self.module = module
        self.apis = SOURCE_APIS if framework == Framework.PYTORCH else TARGET_APIS
        if framework == Framework.PYTORCH:
            self.functions = {
                "add": module.add,
                "sum": module.sum,
                "reshape": module.reshape,
                "unsqueeze": module.unsqueeze,
                "matmul": module.matmul,
                "mean": module.mean,
                "relu": module.nn.functional.relu,
                "cat": module.cat,
                "flatten": module.flatten,
            }
        else:
            mint = module.mint
            self.functions = {
                "add": mint.add,
                "sum": mint.sum,
                "reshape": mint.reshape,
                "unsqueeze": mint.unsqueeze,
                "matmul": mint.matmul,
                "mean": mint.mean,
                "relu": mint.nn.functional.relu,
                "cat": mint.cat,
                "flatten": mint.flatten,
            }

    def tensor(self, value: Any):
        if self.framework == Framework.PYTORCH:
            return self.module.tensor(value, dtype=self.module.float32)
        return self.module.Tensor(value, dtype=self.module.float32)

    def call(self, recorder: TraceRecorder, operation: str, *args: Any, **kwargs: Any):
        return recorder.call(
            self.apis[operation], self.functions[operation], *args, **kwargs
        )


def capture_framework(
    framework: Framework | str,
    output_dir: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    *,
    overwrite: bool = False,
    allow_version_mismatch: bool = False,
) -> dict[str, Any]:
    framework = Framework.parse(framework) if isinstance(framework, str) else framework
    if framework not in (Framework.PYTORCH, Framework.MINDSPORE):
        raise ValueError("runtime capture framework must be pytorch or mindspore")
    manifest = load_manifest(manifest_path)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    expected_prefix = (
        manifest.source_version_prefix
        if framework == Framework.PYTORCH
        else manifest.target_version_prefix
    )
    module_name = "torch" if framework == Framework.PYTORCH else "mindspore"
    try:
        module = importlib.import_module(module_name)
    except (ImportError, OSError) as error:
        return _capture_report(
            manifest,
            framework,
            "unavailable",
            None,
            expected_prefix,
            [],
            [{"id": case.case_id, "reason": type(error).__name__} for case in manifest.cases],
        )
    version = str(getattr(module, "__version__", "unknown"))
    version_compatible = _version_matches(version, expected_prefix)
    if not version_compatible and not allow_version_mismatch:
        return _capture_report(
            manifest,
            framework,
            "version_mismatch",
            version,
            expected_prefix,
            [],
            [
                {
                    "id": case.case_id,
                    "reason": f"expected version prefix {expected_prefix}",
                }
                for case in manifest.cases
            ],
        )
    paths = [output / f"{case.case_id}.jsonl" for case in manifest.cases]
    existing = [path.name for path in paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"runtime capture outputs already exist: {', '.join(existing)}")
    try:
        if framework == Framework.MINDSPORE:
            module.set_context(mode=module.PYNATIVE_MODE)
        backend = _Backend(framework, module)
    except (AttributeError, OSError, RuntimeError) as error:
        return _capture_report(
            manifest,
            framework,
            "backend_unavailable",
            version,
            expected_prefix,
            [],
            [{"id": case.case_id, "reason": type(error).__name__} for case in manifest.cases],
        )
    captured = []
    failures = []
    for case, trace_path in zip(manifest.cases, paths):
        try:
            with TraceRecorder(
                trace_path,
                framework=framework,
                framework_version=version,
                execution_mode=(
                    ExecutionMode.EAGER
                    if framework == Framework.PYTORCH
                    else ExecutionMode.PYNATIVE
                ),
                run_id=f"{manifest.benchmark_version}:{case.case_id}",
                overwrite=overwrite,
                source_root=Path(__file__).parents[2],
            ) as recorder:
                _run_case(case.case_id, backend, recorder)
            records = load_trace_jsonl(trace_path, framework)
            actual = tuple(record.api for record in records)
            expected = tuple(
                backend.apis[operation] for operation in case.operations
            )
            if actual != expected:
                raise SchemaError(f"runtime case {case.case_id} emitted unexpected APIs")
            captured.append({"id": case.case_id, "call_count": len(records)})
        except Exception as error:
            failures.append({"id": case.case_id, "reason": type(error).__name__})
    status = "captured" if not failures else "case_failure"
    return _capture_report(
        manifest,
        framework,
        status,
        version,
        expected_prefix,
        captured,
        failures,
    )


def evaluate_benchmark(
    capture_root: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    root = Path(capture_root).resolve()
    knowledge_path = Path(knowledge_base)
    knowledge = MappingKnowledgeBase.load(knowledge_path)
    results = []
    categories = Counter()
    equivalent_count = 0
    evaluated_count = 0
    source_versions = set()
    target_versions = set()
    for case in manifest.cases:
        source_path = root / Framework.PYTORCH.value / f"{case.case_id}.jsonl"
        target_path = root / Framework.MINDSPORE.value / f"{case.case_id}.jsonl"
        missing = []
        if not source_path.is_file():
            missing.append(Framework.PYTORCH.value)
        if not target_path.is_file():
            missing.append(Framework.MINDSPORE.value)
        if missing:
            if source_path.is_file():
                source_versions.update(
                    record.framework_version
                    for record in load_trace_jsonl(source_path, Framework.PYTORCH)
                )
            if target_path.is_file():
                target_versions.update(
                    record.framework_version
                    for record in load_trace_jsonl(target_path, Framework.MINDSPORE)
                )
            results.append(
                {"id": case.case_id, "status": "missing_capture", "missing": missing}
            )
            continue
        source = load_trace_jsonl(source_path, Framework.PYTORCH)
        target = load_trace_jsonl(target_path, Framework.MINDSPORE)
        source_versions.update(record.framework_version for record in source)
        target_versions.update(record.framework_version for record in target)
        comparison = compare_traces(
            source,
            target,
            knowledge,
            manifest.relative_tolerance,
            manifest.absolute_tolerance,
        )
        evaluated_count += 1
        equivalent_count += int(comparison.equivalent)
        category = (
            comparison.diagnostic.category.value
            if comparison.diagnostic is not None
            else None
        )
        if category is not None:
            categories[category] += 1
        results.append(
            {
                "id": case.case_id,
                "status": "equivalent" if comparison.equivalent else "divergent",
                "expected_equivalent": case.expected_equivalent,
                "classification_correct": comparison.equivalent
                == case.expected_equivalent,
                "first_divergence_category": category,
                "source_call_index": (
                    comparison.diagnostic.metadata.get("source_call_index")
                    if comparison.diagnostic is not None
                    else None
                ),
            }
        )
    case_count = len(manifest.cases)
    complete = evaluated_count == case_count
    classification_correct = sum(
        result.get("classification_correct", False) for result in results
    )
    parity_rate = equivalent_count / evaluated_count if evaluated_count else None
    versions_match = bool(source_versions and target_versions) and all(
        _version_matches(version, manifest.source_version_prefix)
        for version in source_versions
    ) and all(
        _version_matches(version, manifest.target_version_prefix)
        for version in target_versions
    )
    report = {
        "schema_version": "1.0",
        "benchmark_version": manifest.benchmark_version,
        "dataset_kind": DATASET_KIND,
        "knowledge": {
            "snapshot_version": knowledge.payload["snapshot_version"],
            "sha256": hashlib.sha256(knowledge_path.read_bytes()).hexdigest(),
        },
        "case_count": case_count,
        "evaluated_case_count": evaluated_count,
        "complete": complete,
        "passed": complete and classification_correct == case_count and versions_match,
        "runtime_parity_rate": parity_rate,
        "classification_accuracy": (
            classification_correct / evaluated_count if evaluated_count else None
        ),
        "source_framework_versions": sorted(source_versions),
        "target_framework_versions": sorted(target_versions),
        "version_prefixes_match": versions_match,
        "first_divergence_categories": dict(sorted(categories.items())),
        "cases": results,
        "limitations": [
            "Microcases exercise deterministic forward APIs only.",
            "A complete report requires captures from both pinned framework version families.",
            "Passing microcases does not prove whole-project migration correctness.",
        ],
    }
    return report


def _run_case(case_id: str, backend: _Backend, recorder: TraceRecorder) -> None:
    if case_id == "elementwise-reduction":
        left = backend.tensor([[1.0, -2.0], [3.5, 4.0]])
        right = backend.tensor([[0.5, 2.0], [-1.5, 1.0]])
        value = backend.call(recorder, "add", left, right)
        backend.call(recorder, "sum", value)
    elif case_id == "shape-transform":
        value = backend.tensor([1.0, 2.0, 3.0, 4.0])
        value = backend.call(recorder, "reshape", value, (2, 2))
        backend.call(recorder, "unsqueeze", value, 0)
    elif case_id == "matrix-reduction":
        left = backend.tensor([[1.0, 2.0], [3.0, 4.0]])
        right = backend.tensor([[2.0, 0.0], [1.0, 2.0]])
        value = backend.call(recorder, "matmul", left, right)
        backend.call(recorder, "mean", value)
    elif case_id == "activation-reduction":
        value = backend.tensor([[-2.0, -0.5], [1.5, 3.0]])
        value = backend.call(recorder, "relu", value)
        backend.call(recorder, "sum", value)
    elif case_id == "concatenate-flatten":
        left = backend.tensor([[1.0, 2.0]])
        right = backend.tensor([[3.0, 4.0]])
        value = backend.call(recorder, "cat", (left, right), 0)
        backend.call(recorder, "flatten", value)
    else:
        raise SchemaError(f"unknown built-in runtime case: {case_id}")


def _capture_report(
    manifest: RuntimeManifest,
    framework: Framework,
    status: str,
    version: str | None,
    expected_prefix: str,
    captured: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "benchmark_version": manifest.benchmark_version,
        "record_kind": "runtime_capture_report",
        "framework": framework.value,
        "framework_version": version,
        "expected_version_prefix": expected_prefix,
        "version_compatible": bool(version and _version_matches(version, expected_prefix)),
        "status": status,
        "python_version": platform.python_version(),
        "case_count": len(manifest.cases),
        "captured_case_count": len(captured),
        "captured": captured,
        "failures": failures,
    }


def _required_string(value: dict[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise SchemaError(f"runtime parity requires {name}")
    return item.strip()


def _non_negative_number(value: dict[str, Any], name: str) -> float:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0:
        raise SchemaError(f"runtime parity {name} must be a non-negative number")
    return float(item)


def _version_matches(version: str, expected_prefix: str) -> bool:
    release = version.split("+", 1)[0]
    return release == expected_prefix or release.startswith(f"{expected_prefix}.")


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("framework", choices=["pytorch", "mindspore"])
    capture.add_argument("output_dir")
    capture.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    capture.add_argument("--force", action="store_true")
    capture.add_argument("--allow-version-mismatch", action="store_true")
    capture.add_argument("--pretty", action="store_true")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("capture_root")
    evaluate.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    evaluate.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    evaluate.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "capture":
            result = capture_framework(
                arguments.framework,
                arguments.output_dir,
                arguments.manifest,
                overwrite=arguments.force,
                allow_version_mismatch=arguments.allow_version_mismatch,
            )
            passed = result["status"] == "captured"
        else:
            result = evaluate_benchmark(
                arguments.capture_root,
                arguments.manifest,
                arguments.knowledge_base,
            )
            passed = result["passed"]
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if arguments.pretty else None, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
