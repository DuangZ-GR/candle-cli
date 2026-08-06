import json
import sys
from pathlib import Path

import pytest

from migration.rewriter import rollback_transaction
from migration.workflow import main, render_markdown, run_migration, validate_report


def write_project(root: Path) -> Path:
    source = root / "model.py"
    source.write_text("import torch\ny = torch.add(x, 1)\n", encoding="utf-8")
    return source


def write_trace(path: Path, framework: str, api: str, dtype: str = "float32") -> None:
    payload = {
        "schema_version": "1.0",
        "record_kind": "api_trace",
        "run_id": f"workflow-{framework}",
        "framework": framework,
        "framework_version": "2.6.0" if framework == "pytorch" else "2.9.0",
        "execution_mode": "eager" if framework == "pytorch" else "py_native",
        "location": {"file": "model.py", "line": 2, "column": 4},
        "api": api,
        "call_index": 0,
        "output": {"kind": "tensor", "dtype": dtype, "shape": [2]},
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_runtime_manifest(
    root: Path,
    *,
    target_exit_code: int = 0,
    target_dtype: str = "float32",
) -> Path:
    runner = root / "runtime_runner.py"
    runner.write_text(
        """import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--framework", required=True)
parser.add_argument("--trace", required=True)
parser.add_argument("--dtype", default="float32")
parser.add_argument("--exit-code", type=int, default=0)
args = parser.parse_args()
source = Path("model.py").read_text(encoding="utf-8")
expected = "torch.add" if args.framework == "pytorch" else "mindspore.mint.add"
if expected not in source:
    raise SystemExit(8)
if args.exit_code:
    raise SystemExit(args.exit_code)
payload = {
    "schema_version": "1.0",
    "record_kind": "api_trace",
    "run_id": "automatic-runtime",
    "framework": args.framework,
    "framework_version": "2.6.0" if args.framework == "pytorch" else "2.9.0",
    "execution_mode": "eager" if args.framework == "pytorch" else "py_native",
    "location": {"file": "model.py", "line": 2, "column": 4},
    "api": "torch.add" if args.framework == "pytorch" else "mindspore.mint.add",
    "call_index": 0,
    "output": {"kind": "tensor", "dtype": args.dtype, "shape": [2]},
}
Path(args.trace).write_text(json.dumps(payload) + "\\n", encoding="utf-8")
""",
        encoding="utf-8",
    )
    payload = {
        "schema_version": "1.0",
        "workflow_version": "dual-runtime-v1",
        "manifest_id": "workflow-test-v1",
        "source_files": ["model.py"],
        "manual_patch_count": 1,
        "source": {
            "framework": "pytorch",
            "python_env": "WORKFLOW_SOURCE_PYTHON",
            "python_default": sys.executable,
            "entrypoint": runner.name,
            "args": ["--framework", "{framework}", "--trace", "{trace_path}"],
            "trace_path": ".candle-cli/traces/{run_id}-source.jsonl",
            "timeout_seconds": 10,
        },
        "target": {
            "framework": "mindspore",
            "python_env": "WORKFLOW_TARGET_PYTHON",
            "python_default": sys.executable,
            "entrypoint": runner.name,
            "args": [
                "--framework",
                "{framework}",
                "--trace",
                "{trace_path}",
                "--dtype",
                target_dtype,
                "--exit-code",
                str(target_exit_code),
            ],
            "trace_path": ".candle-cli/traces/{run_id}-target.jsonl",
            "timeout_seconds": 10,
        },
        "metadata": {"fixture": "automatic-dual-runtime"},
    }
    path = root / "runtime-manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_preview_runs_scan_and_rewrite_without_modifying_source(tmp_path):
    source = write_project(tmp_path)
    original = source.read_bytes()

    report = run_migration(tmp_path)

    validate_report(report)
    assert report["status"] == "previewed"
    assert report["verified"] is False
    assert [step["name"] for step in report["steps"]] == [
        "scan",
        "rewrite_preview",
    ]
    assert report["summary"]["finding_count"] == 1
    assert report["summary"]["files_changed"] == 1
    assert report["summary"]["edit_count"] == 2
    assert source.read_bytes() == original


def test_apply_requires_validation_command(tmp_path):
    write_project(tmp_path)

    with pytest.raises(ValueError, match="requires a non-empty validation command"):
        run_migration(tmp_path, apply=True)


def test_apply_and_successful_validation_produces_verified_run(tmp_path):
    source = write_project(tmp_path)

    report = run_migration(
        tmp_path,
        apply=True,
        validation_command=[sys.executable, "-c", "print('validated')"],
    )

    assert report["status"] == "verified"
    assert report["verified"] is True
    assert report["summary"]["validation_status"] == "passed"
    assert "mindspore.mint.add" in source.read_text(encoding="utf-8")
    manifest = report["artifacts"]["transaction_manifest"]
    assert manifest
    rollback_transaction(manifest)


def test_failed_validation_returns_report_and_restores_source(tmp_path):
    source = write_project(tmp_path)
    original = source.read_bytes()

    report = run_migration(
        tmp_path,
        apply=True,
        validation_command=[sys.executable, "-c", "raise SystemExit(7)"],
    )

    assert report["status"] == "rolled_back"
    assert report["error"]["stage"] == "validation"
    assert report["summary"]["validation_status"] == "failed"
    assert report["steps"][-1]["status"] == "rolled_back"
    assert source.read_bytes() == original


def test_trace_divergence_rolls_back_an_applied_patch(tmp_path):
    source = write_project(tmp_path)
    original = source.read_bytes()
    source_trace = tmp_path / "source.jsonl"
    target_trace = tmp_path / "target.jsonl"
    write_trace(source_trace, "pytorch", "torch.add")
    write_trace(target_trace, "mindspore", "mindspore.mint.add", dtype="bool")

    report = run_migration(
        source,
        apply=True,
        validation_command=[sys.executable, "-c", "print('validated')"],
        source_trace=source_trace,
        target_trace=target_trace,
    )

    assert report["status"] == "rolled_back"
    assert report["summary"]["trace_equivalent"] is False
    assert report["summary"]["first_divergence_category"] == "dtype_mismatch"
    assert [step["name"] for step in report["steps"]][-2:] == [
        "trace_compare",
        "rollback",
    ]
    assert source.read_bytes() == original


def test_equivalent_traces_complete_verified_apply(tmp_path):
    source = write_project(tmp_path)
    source_trace = tmp_path / "source.jsonl"
    target_trace = tmp_path / "target.jsonl"
    write_trace(source_trace, "pytorch", "torch.add")
    write_trace(target_trace, "mindspore", "mindspore.mint.add")

    report = run_migration(
        source,
        apply=True,
        validation_command=[sys.executable, "-c", "print('validated')"],
        source_trace=source_trace,
        target_trace=target_trace,
    )

    assert report["status"] == "verified"
    assert report["summary"]["trace_equivalent"] is True
    rollback_transaction(report["artifacts"]["transaction_manifest"])


def test_runtime_manifest_collects_both_traces_and_verifies_apply(tmp_path):
    source = write_project(tmp_path)
    manifest = write_runtime_manifest(tmp_path)

    report = run_migration(tmp_path, apply=True, runtime_manifest=manifest)

    assert report["status"] == "verified"
    assert report["summary"]["trace_equivalent"] is True
    runtime = report["summary"]["runtime_collection"]
    assert runtime["source_status"] == "passed"
    assert runtime["target_status"] == "passed"
    assert runtime["source_trace_calls"] == 1
    assert runtime["target_trace_calls"] == 1
    assert runtime["automatic_patch_count"] == 2
    assert runtime["manual_patch_count"] == 1
    assert runtime["patch_adoption_rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert [step["name"] for step in report["steps"]] == [
        "scan",
        "runtime_manifest",
        "rewrite_preview",
        "source_runtime",
        "target_runtime",
        "apply_and_validate",
        "trace_compare",
    ]
    markdown = render_markdown(report)
    assert "## Dual-runtime collection" in markdown
    assert "Mapping coverage: `100.00%`" in markdown
    assert "Automatic/manual patches: `2/1`" in markdown
    assert "Source/target runtime: `passed/passed`" in markdown
    assert "mindspore.mint.add" in source.read_text(encoding="utf-8")
    rollback_transaction(report["artifacts"]["transaction_manifest"])


def test_runtime_manifest_target_failure_rolls_back_bytes(tmp_path):
    source = write_project(tmp_path)
    original = source.read_bytes()
    manifest = write_runtime_manifest(tmp_path, target_exit_code=7)

    report = run_migration(tmp_path, apply=True, runtime_manifest=manifest)

    assert report["status"] == "rolled_back"
    assert report["error"]["stage"] == "validation"
    assert report["summary"]["runtime_collection"]["target_status"] == "failed"
    assert report["summary"]["runtime_collection"]["source_trace_calls"] == 1
    assert report["summary"]["runtime_collection"]["target_trace_calls"] == 0
    assert report["summary"]["runtime_collection"]["rollback_succeeded"] is True
    assert source.read_bytes() == original


def test_runtime_manifest_trace_divergence_rolls_back_bytes(tmp_path):
    source = write_project(tmp_path)
    original = source.read_bytes()
    manifest = write_runtime_manifest(tmp_path, target_dtype="bool")

    report = run_migration(tmp_path, apply=True, runtime_manifest=manifest)

    assert report["status"] == "rolled_back"
    assert report["summary"]["first_divergence_category"] == "dtype_mismatch"
    assert report["summary"]["runtime_collection"]["rollback_succeeded"] is True
    assert source.read_bytes() == original


def test_cli_preserves_failed_report_and_returns_nonzero(tmp_path, capsys):
    source = write_project(tmp_path)
    original = source.read_bytes()

    exit_code = main(
        [
            str(source),
            "--apply",
            "--validate-command",
            sys.executable,
            "-c",
            "raise SystemExit(9)",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["status"] == "rolled_back"
    assert source.read_bytes() == original


def test_markdown_report_contains_status_and_steps(tmp_path):
    write_project(tmp_path)

    markdown = render_markdown(run_migration(tmp_path))

    assert "# Torch2MindSpore Migration Run" in markdown
    assert "Status: `previewed`" in markdown
    assert "`rewrite_preview`" in markdown
