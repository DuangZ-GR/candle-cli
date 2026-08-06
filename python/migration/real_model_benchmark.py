"""Run the frozen external-model dual-runtime migration benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.workflow import run_migration

DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "real_model_dual_runtime_v1.json"
)
DATASET_KIND = "pinned_external_model_slice_dual_runtime_cases"


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    fault: str
    expected_status: str
    expected_divergence: str | None


@dataclass(frozen=True)
class BenchmarkManifest:
    path: Path
    benchmark_version: str
    slice_root: Path
    migration_path: str
    runtime_manifest: str
    source_version_prefix: str
    target_version_prefix: str
    cases: tuple[BenchmarkCase, ...]


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> BenchmarkManifest:
    manifest_path = Path(path).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("unsupported real-model benchmark schema_version")
    if payload.get("dataset_kind") != DATASET_KIND:
        raise ValueError("unsupported real-model benchmark dataset_kind")
    slice_data = payload.get("slice")
    frameworks = payload.get("frameworks")
    if not isinstance(slice_data, dict) or not isinstance(frameworks, dict):
        raise ValueError("real-model benchmark requires slice and frameworks")
    root = (manifest_path.parent / _required_text(slice_data, "root")).resolve()
    if not root.is_relative_to(manifest_path.parent) or not root.is_dir():
        raise ValueError("real-model slice root escapes the benchmark directory")
    migration_path = _required_text(slice_data, "migration_path")
    runtime_manifest = _required_text(slice_data, "runtime_manifest")
    for relative in (migration_path, runtime_manifest):
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError(f"real-model slice file is missing: {relative}")
    source = frameworks.get("source")
    target = frameworks.get("target")
    if not isinstance(source, dict) or source.get("name") != "pytorch":
        raise ValueError("real-model source framework must be pytorch")
    if not isinstance(target, dict) or target.get("name") != "mindspore":
        raise ValueError("real-model target framework must be mindspore")
    cases = []
    for item in payload.get("cases", []):
        if not isinstance(item, dict):
            raise ValueError("real-model benchmark case must be an object")
        case = BenchmarkCase(
            case_id=_required_text(item, "id"),
            fault=_required_text(item, "fault"),
            expected_status=_required_text(item, "expected_status"),
            expected_divergence=item.get("expected_divergence"),
        )
        if case.fault not in {"none", "runtime", "dtype"}:
            raise ValueError(f"unsupported real-model fault: {case.fault}")
        cases.append(case)
    if {case.fault for case in cases} != {"none", "runtime", "dtype"}:
        raise ValueError("real-model benchmark requires success, runtime, and dtype cases")
    return BenchmarkManifest(
        path=manifest_path,
        benchmark_version=_required_text(payload, "benchmark_version"),
        slice_root=root,
        migration_path=migration_path,
        runtime_manifest=runtime_manifest,
        source_version_prefix=_required_text(source, "version_prefix"),
        target_version_prefix=_required_text(target, "version_prefix"),
        cases=tuple(cases),
    )


def run_benchmark(
    manifest: BenchmarkManifest,
    *,
    pytorch_python: str | Path,
    mindspore_python: str | Path,
) -> dict[str, Any]:
    source_version = _framework_version(pytorch_python, "torch")
    target_version = _framework_version(mindspore_python, "mindspore")
    if not source_version.startswith(manifest.source_version_prefix):
        raise ValueError(
            f"PyTorch version {source_version} does not match {manifest.source_version_prefix}"
        )
    if not target_version.startswith(manifest.target_version_prefix):
        raise ValueError(
            f"MindSpore version {target_version} does not match {manifest.target_version_prefix}"
        )
    case_reports = []
    previous_source = os.environ.get("CANDLE_CLI_PYTORCH_PYTHON")
    previous_target = os.environ.get("CANDLE_CLI_MINDSPORE_PYTHON")
    os.environ["CANDLE_CLI_PYTORCH_PYTHON"] = str(Path(pytorch_python).resolve())
    os.environ["CANDLE_CLI_MINDSPORE_PYTHON"] = str(
        Path(mindspore_python).resolve()
    )
    try:
        with tempfile.TemporaryDirectory(prefix="candle-cli-real-model-") as temporary:
            temporary_root = Path(temporary)
            for case in manifest.cases:
                case_root = temporary_root / case.case_id
                shutil.copytree(manifest.slice_root, case_root)
                migration_path = case_root / manifest.migration_path
                runtime_path = case_root / manifest.runtime_manifest
                original = migration_path.read_bytes()
                _set_target_fault(runtime_path, case.fault)
                report = run_migration(
                    migration_path,
                    apply=True,
                    runtime_manifest=runtime_path,
                )
                restored = migration_path.read_bytes() == original
                passed = report["status"] == case.expected_status
                if case.expected_divergence is not None:
                    passed = passed and report["summary"][
                        "first_divergence_category"
                    ] == case.expected_divergence
                if case.expected_status == "rolled_back":
                    passed = passed and restored
                case_reports.append(
                    {
                        "case_id": case.case_id,
                        "fault": case.fault,
                        "expected_status": case.expected_status,
                        "passed": passed,
                        "source_restored": restored,
                        "original_sha256": hashlib.sha256(original).hexdigest(),
                        "final_sha256": hashlib.sha256(
                            migration_path.read_bytes()
                        ).hexdigest(),
                        "workflow": report,
                    }
                )
    finally:
        _restore_environment("CANDLE_CLI_PYTORCH_PYTHON", previous_source)
        _restore_environment("CANDLE_CLI_MINDSPORE_PYTHON", previous_target)
    passed_count = sum(case["passed"] for case in case_reports)
    rollback_cases = [
        case for case in case_reports if case["expected_status"] == "rolled_back"
    ]
    return {
        "schema_version": "1.0",
        "record_kind": "real_model_dual_runtime_benchmark",
        "benchmark_version": manifest.benchmark_version,
        "dataset_kind": DATASET_KIND,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "pytorch_python": str(Path(pytorch_python).resolve()),
            "mindspore_python": str(Path(mindspore_python).resolve()),
            "pytorch_version": source_version,
            "mindspore_version": target_version,
        },
        "summary": {
            "case_count": len(case_reports),
            "passed_count": passed_count,
            "pass_rate": round(passed_count / len(case_reports), 6),
            "rollback_case_count": len(rollback_cases),
            "rollback_success_count": sum(case["source_restored"] for case in rollback_cases),
            "rollback_success_rate": round(
                sum(case["source_restored"] for case in rollback_cases)
                / len(rollback_cases),
                6,
            ),
        },
        "cases": case_reports,
        "limitations": [
            "The runtime scope is the MNIST classifier head, not the dataset pipeline or full training loop.",
            "One manual functional adaptation is reported separately from automatic API edits.",
            "A single pinned slice does not estimate whole-project migration accuracy.",
        ],
    }


def _framework_version(python: str | Path, module: str) -> str:
    completed = subprocess.run(
        [str(python), "-c", f"import {module}; print({module}.__version__)"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"failed to query {module} version: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _set_target_fault(path: Path, fault: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    args = payload["target"]["args"]
    index = args.index("--fault") + 1
    args[index] = fault
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _restore_environment(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"real-model benchmark requires {key}")
    return value


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--pytorch-python", required=True)
    parser.add_argument("--mindspore-python", required=True)
    parser.add_argument("--output")
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        result = run_benchmark(
            load_manifest(arguments.manifest),
            pytorch_python=arguments.pytorch_python,
            mindspore_python=arguments.mindspore_python,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        indent=2 if arguments.pretty else None,
        sort_keys=True,
    ) + "\n"
    if arguments.output:
        Path(arguments.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["summary"]["pass_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
