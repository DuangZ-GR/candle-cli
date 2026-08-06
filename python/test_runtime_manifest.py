from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from migration.runtime_manifest import (
    RuntimeExecutionError,
    RuntimeManifestError,
    execute_runtime,
    load_runtime_manifest,
)


RUNNER = """import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--framework", required=True)
parser.add_argument("--trace", required=True)
parser.add_argument("--exit-code", type=int, default=0)
args = parser.parse_args()
if args.exit_code:
    raise SystemExit(args.exit_code)
payload = {
    "schema_version": "1.0",
    "record_kind": "api_trace",
    "run_id": "runtime-test",
    "framework": args.framework,
    "framework_version": "test",
    "captured_at": "2026-01-01T00:00:00+00:00",
    "call_index": 0,
    "api": "torch.add" if args.framework == "pytorch" else "mindspore.mint.add",
    "inputs": [],
    "output": {"kind": "tensor", "dtype": "float32", "shape": [1], "values": [2.0]},
}
Path(args.trace).write_text(json.dumps(payload) + "\\n", encoding="utf-8")
print(os.environ.get("RUNTIME_TEST_VALUE", "missing"))
"""


def write_manifest(
    root: Path,
    *,
    source_entrypoint: str = "runner.py",
    source_exit_code: int = 0,
) -> Path:
    (root / "runner.py").write_text(RUNNER, encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "workflow_version": "dual-runtime-v1",
        "manifest_id": "runtime-test-v1",
        "source_files": ["runner.py"],
        "manual_patch_count": 0,
        "source": {
            "framework": "pytorch",
            "python_env": "TEST_PYTORCH_PYTHON",
            "entrypoint": source_entrypoint,
            "args": [
                "--framework",
                "{framework}",
                "--trace",
                "{trace_path}",
                "--exit-code",
                str(source_exit_code),
            ],
            "trace_path": ".candle-cli/traces/{run_id}-source.jsonl",
            "timeout_seconds": 10,
            "environment": {
                "inherit": ["PATH", "RUNTIME_TEST_VALUE"],
                "set": {"PYTHONHASHSEED": "0"},
            },
            "resource_limits": {"cpu_seconds": 5, "memory_mb": 512},
        },
        "target": {
            "framework": "mindspore",
            "python_env": "TEST_MINDSPORE_PYTHON",
            "python_default": sys.executable,
            "entrypoint": "runner.py",
            "args": ["--framework", "{framework}", "--trace", "{trace_path}"],
            "trace_path": ".candle-cli/traces/{run_id}-target.jsonl",
            "timeout_seconds": 10,
        },
        "metadata": {"fixture": True},
    }
    path = root / "runtime.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def runtime_environment() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "TEST_PYTORCH_PYTHON": sys.executable,
        "TEST_MINDSPORE_PYTHON": sys.executable,
        "RUNTIME_TEST_VALUE": "allowed",
        "RUNTIME_SECRET": "must-not-leak",
    }


def test_manifest_executes_both_runtimes_and_creates_fresh_traces(tmp_path):
    manifest = load_runtime_manifest(write_manifest(tmp_path), tmp_path)
    stale = tmp_path / ".candle-cli" / "traces" / "case-source.jsonl"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    source = execute_runtime(
        manifest, "source", "case", environment=runtime_environment()
    )
    target = execute_runtime(
        manifest, "target", "case", environment=runtime_environment()
    )

    assert source["status"] == "passed"
    assert target["status"] == "passed"
    assert source["framework"] == "pytorch"
    assert target["framework"] == "mindspore"
    assert source["stdout"].strip() == "allowed"
    assert "RUNTIME_SECRET" not in source["command"]
    assert json.loads(stale.read_text(encoding="utf-8"))["framework"] == "pytorch"


def test_manifest_rejects_entrypoint_escape(tmp_path):
    outside = tmp_path.parent / "outside-runtime.py"
    outside.write_text("pass\n", encoding="utf-8")
    path = write_manifest(tmp_path, source_entrypoint="../outside-runtime.py")

    with pytest.raises(RuntimeManifestError, match="escapes project root"):
        load_runtime_manifest(path, tmp_path)


def test_runtime_failure_preserves_structured_evidence(tmp_path):
    manifest = load_runtime_manifest(
        write_manifest(tmp_path, source_exit_code=7), tmp_path
    )

    with pytest.raises(RuntimeExecutionError) as captured:
        execute_runtime(
            manifest, "source", "failed", environment=runtime_environment()
        )

    assert captured.value.result["status"] == "failed"
    assert captured.value.result["return_code"] == 7
    assert captured.value.result["trace_bytes"] == 0


def test_manifest_requires_explicit_python_resolution(tmp_path):
    path = write_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source"].pop("python_default", None)
    path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = load_runtime_manifest(path, tmp_path)

    with pytest.raises(RuntimeManifestError, match="TEST_PYTORCH_PYTHON"):
        execute_runtime(manifest, "source", "missing", environment={"PATH": ""})
