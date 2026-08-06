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
