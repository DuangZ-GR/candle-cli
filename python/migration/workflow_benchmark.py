"""Evaluate the end-to-end migration workflow with real runtimes and faults."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.workflow import run_migration

DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "workflow_e2e_v1.json"
)
DATASET_KIND = "deterministic_migration_workflow_cases"
CASE_KINDS = {
    "preview-safe": "preview",
    "validated-apply": "real_framework_apply",
    "validation-failure-rollback": "validation_fault",
    "dtype-divergence-rollback": "trace_fault",
}
FIXTURE_SOURCE = """import torch
x = torch.ones((2,), dtype=torch.float32)
y = torch.add(x, 1.0)
print(y)
"""


@dataclass(frozen=True)
class WorkflowCase:
    case_id: str
    kind: str
    expected_status: str
    expected_divergence: str | None


@dataclass(frozen=True)
class WorkflowManifest:
    benchmark_version: str
    source_version_prefix: str
    target_version_prefix: str
    cases: tuple[WorkflowCase, ...]


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> WorkflowManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("unsupported workflow benchmark schema_version")
    if payload.get("dataset_kind") != DATASET_KIND:
        raise ValueError("unsupported workflow benchmark dataset_kind")
    source = payload.get("source_framework")
    target = payload.get("target_framework")
    if not isinstance(source, dict) or source.get("name") != "pytorch":
        raise ValueError("workflow source framework must be pytorch")
    if not isinstance(target, dict) or target.get("name") != "mindspore":
        raise ValueError("workflow target framework must be mindspore")
    cases = []
    for value in payload.get("cases", []):
        case_id = value.get("id") if isinstance(value, dict) else None
        if case_id not in CASE_KINDS or value.get("kind") != CASE_KINDS[case_id]:
            raise ValueError("workflow benchmark contains an unknown built-in case")
        expected_status = value.get("expected_status")
        if expected_status not in {"previewed", "verified", "rolled_back"}:
            raise ValueError("workflow case has an invalid expected_status")
        cases.append(
            WorkflowCase(
                case_id,
                value["kind"],
                expected_status,
                value.get("expected_divergence"),
            )
        )
    if {case.case_id for case in cases} != set(CASE_KINDS) or len(cases) != len(
        CASE_KINDS
    ):
        raise ValueError("workflow benchmark must contain every built-in case once")
    return WorkflowManifest(
        _required_string(payload, "benchmark_version"),
        _required_string(source, "version_prefix"),
        _required_string(target, "version_prefix"),
        tuple(cases),
    )


def run_benchmark(
    source_python: str,
    target_python: str,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    source_version = _framework_version(source_python, "torch")
    target_version = _framework_version(target_python, "mindspore")
    source_compatible = source_version.startswith(manifest.source_version_prefix)
    target_compatible = target_version.startswith(manifest.target_version_prefix)
    if not source_compatible or not target_compatible:
        raise RuntimeError(
            "framework versions do not match the frozen workflow benchmark manifest"
        )

    case_reports = []
    with tempfile.TemporaryDirectory(prefix="candle-cli-workflow-") as temporary:
        root = Path(temporary)
        for case in manifest.cases:
            case_root = root / case.case_id
            case_root.mkdir()
            source_path = case_root / "model.py"
            source_path.write_text(FIXTURE_SOURCE, encoding="utf-8")
            original = source_path.read_bytes()
            source_execution = _run_program(source_python, source_path)
            arguments: dict[str, Any] = {}
            if case.kind != "preview":
                arguments.update(
                    apply=True,
                    validation_command=[target_python, str(source_path)],
                )
            if case.kind == "validation_fault":
                arguments["validation_command"] = [
                    target_python,
                    "-c",
                    "raise SystemExit(7)",
                ]
            if case.kind == "trace_fault":
                source_trace = case_root / "source.jsonl"
                target_trace = case_root / "target.jsonl"
                _write_trace(source_trace, "pytorch", "torch.add", "float32")
                _write_trace(
                    target_trace,
                    "mindspore",
                    "mindspore.mint.add",
                    "bool",
                )
                arguments.update(
                    source_trace=source_trace,
                    target_trace=target_trace,
                )
            report = run_migration(source_path, **arguments)
            restored = source_path.read_bytes() == original
            expected_restored = case.kind in {"preview", "validation_fault", "trace_fault"}
            passed = (
                source_execution["return_code"] == 0
                and report["status"] == case.expected_status
                and restored == expected_restored
                and report["summary"]["first_divergence_category"]
                == case.expected_divergence
            )
            case_reports.append(
                {
                    "id": case.case_id,
                    "kind": case.kind,
                    "passed": passed,
                    "expected_status": case.expected_status,
                    "actual_status": report["status"],
                    "source_execution": source_execution,
                    "source_bytes_restored": restored,
                    "expected_source_bytes_restored": expected_restored,
                    "first_divergence_category": report["summary"][
                        "first_divergence_category"
                    ],
                    "validation_status": report["summary"]["validation_status"],
                    "error": report["error"],
                    "steps": report["steps"],
                    "workflow_duration_ms": report["duration_ms"],
                    "step_count": len(report["steps"]),
                }
            )
    passed_count = sum(case["passed"] for case in case_reports)
    rollback_cases = [
        case
        for case in case_reports
        if case["kind"] in {"validation_fault", "trace_fault"}
    ]
    verified_cases = [
        case for case in case_reports if case["kind"] == "real_framework_apply"
    ]
    trace_fault_cases = [
        case for case in rollback_cases if case["kind"] == "trace_fault"
    ]
    return {
        "schema_version": "1.0",
        "benchmark_version": manifest.benchmark_version,
        "dataset_kind": DATASET_KIND,
        "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
        "environment": {
            "source_python": source_python,
            "target_python": target_python,
            "pytorch_version": source_version,
            "mindspore_version": target_version,
            "source_version_compatible": source_compatible,
            "target_version_compatible": target_compatible,
        },
        "summary": {
            "case_count": len(case_reports),
            "passed_case_count": passed_count,
            "workflow_pass_rate": round(passed_count / len(case_reports), 6),
            "source_execution_pass_rate": round(
                sum(case["source_execution"]["return_code"] == 0 for case in case_reports)
                / len(case_reports),
                6,
            ),
            "verified_apply_rate": round(
                sum(case["actual_status"] == "verified" for case in verified_cases)
                / len(verified_cases),
                6,
            ),
            "fault_rollback_rate": round(
                sum(
                    case["actual_status"] == "rolled_back"
                    and case["source_bytes_restored"]
                    for case in rollback_cases
                )
                / len(rollback_cases),
                6,
            ),
            "dtype_defect_top1_accuracy": round(
                sum(
                    case["first_divergence_category"] == "dtype_mismatch"
                    for case in trace_fault_cases
                )
                / len(trace_fault_cases),
                6,
            ),
        },
        "passed": passed_count == len(case_reports),
        "cases": case_reports,
        "limitations": [
            "The executable fixture is a deterministic two-operator CPU program.",
            "Fault cases are labelled injections, not unknown production defects.",
            "The benchmark measures workflow control and rollback, not project migration accuracy.",
        ],
    }


def _framework_version(python: str, module: str) -> str:
    result = subprocess.run(
        [python, "-c", f"import {module}; print({module}.__version__)"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to load {module}: {result.stderr.strip()}")
    return result.stdout.strip()


def _run_program(python: str, path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [python, str(path)],
        cwd=path.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    return {
        "return_code": result.returncode,
        "stdout": result.stdout[:4096],
        "stderr": result.stderr[:4096],
    }


def _write_trace(path: Path, framework: str, api: str, dtype: str) -> None:
    payload = {
        "schema_version": "1.0",
        "record_kind": "api_trace",
        "run_id": f"workflow-benchmark-{framework}",
        "framework": framework,
        "framework_version": "2.6.0" if framework == "pytorch" else "2.9.0",
        "execution_mode": "eager" if framework == "pytorch" else "py_native",
        "location": {"file": "model.py", "line": 3, "column": 4},
        "api": api,
        "call_index": 0,
        "output": {"kind": "tensor", "dtype": dtype, "shape": [2]},
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"workflow benchmark requires {key}")
    return value


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-python", required=True)
    parser.add_argument("--target-python", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    output = Path(arguments.output) if arguments.output else None
    if output is not None and output.exists() and not arguments.force:
        print("benchmark output already exists; pass --force", file=__import__("sys").stderr)
        return 2
    try:
        report = run_benchmark(
            arguments.source_python,
            arguments.target_python,
            arguments.manifest,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    encoded = json.dumps(
        report,
        ensure_ascii=False,
        indent=2 if arguments.pretty or output else None,
        sort_keys=True,
    ) + "\n"
    if output is None:
        print(encoded, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
