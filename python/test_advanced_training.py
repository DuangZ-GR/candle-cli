import copy
import json
from pathlib import Path

import pytest

from migration.advanced_training import (
    DEFAULT_MANIFEST,
    RUNTIMES,
    _error_payload,
    evaluate_benchmark,
    load_manifest,
    validate_report,
)
from migration.schema import SchemaError


def test_advanced_training_manifest_is_frozen_and_covers_m16_acceptance():
    manifest = load_manifest()
    assert manifest.benchmark_version == "advanced-training-v1"
    assert len(manifest.cases) == 13
    capabilities = {
        capability for case in manifest.cases for capability in case.capabilities
    }
    assert {"pynative", "graph", "adam", "adamw", "cross-process"} <= capabilities
    assert {case.expected_category.value for case in manifest.cases if case.expected_category} == {
        "graph_compile_failure",
        "runtime_error",
        "gradient_mismatch",
        "optimizer_state_mismatch",
        "shape_mismatch",
    }


def test_advanced_training_manifest_rejects_case_drift(tmp_path):
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    payload["cases"][0]["kind"] = "training"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SchemaError, match="changed kind"):
        load_manifest(path)


def test_synthetic_advanced_training_report_meets_acceptance(tmp_path):
    _write_synthetic_captures(tmp_path)
    report = evaluate_benchmark(tmp_path)
    assert report["complete"] is True
    assert report["passed"] is True
    assert report["case_count"] == 13
    assert report["mode_component_count"] == 4
    assert report["multi_step_optimizer_case_count"] == 3
    assert report["checkpoint_case_count"] == 1
    assert report["classification_accuracy"] == 1.0
    assert report["diagnostic_top1_accuracy"] == 1.0
    assert report["mode_parity_rate"] == 1.0
    assert report["multi_step_optimizer_parity_rate"] == 0.666667
    assert report["checkpoint_restore_rate"] == 1.0
    assert set(report["first_divergence_categories"]) == {
        "graph_compile_failure",
        "runtime_error",
        "gradient_mismatch",
        "optimizer_state_mismatch",
        "shape_mismatch",
    }
    validate_report(report)


def test_advanced_training_report_marks_missing_runtime_incomplete(tmp_path):
    _write_synthetic_captures(tmp_path)
    (tmp_path / "mindspore-graph.json").unlink()
    report = evaluate_benchmark(tmp_path)
    assert report["complete"] is False
    assert report["passed"] is False
    assert all(case["status"] == "missing_capture" for case in report["cases"])


def test_advanced_training_report_rejects_invalid_rate():
    report = {
        "schema_version": "1.0",
        "record_kind": "advanced_training_report",
        "benchmark_version": "advanced-training-v1",
        "case_count": 0,
        "evaluated_case_count": 0,
        "fault_case_count": 0,
        "mode_component_count": 0,
        "multi_step_optimizer_case_count": 0,
        "checkpoint_case_count": 0,
        "classification_accuracy": 1.1,
        "diagnostic_top1_accuracy": 0.0,
        "mode_parity_rate": 0.0,
        "multi_step_optimizer_parity_rate": 0.0,
        "checkpoint_restore_rate": 0.0,
        "runtime_environments": {},
        "cases": [],
    }
    with pytest.raises(ValueError, match="rates"):
        validate_report(report)


def test_capture_error_payload_redacts_project_path():
    project_root = DEFAULT_MANIFEST.parents[2]
    payload = _error_payload(ValueError(f"failed in {project_root}/model.py"))
    assert str(project_root) not in payload["message"]
    assert "<project_root>/model.py" in payload["message"]


def _write_synthetic_captures(root: Path):
    manifest = load_manifest()
    for runtime in RUNTIMES:
        cases = []
        for case in manifest.cases:
            value = {
                "id": case.case_id,
                "split": case.split,
                "kind": case.kind,
                "capabilities": list(case.capabilities),
                "fault_injection": case.fault_injection,
                "status": "ok",
            }
            if case.kind == "forward":
                value["measurements"] = {"output": [[0.5, -0.25]]}
            elif case.kind == "training":
                value["measurements"] = {
                    "losses": [1.0, 0.8, 0.6],
                    "final_parameters": [0.2, -0.4, 0.1],
                }
            elif case.kind == "checkpoint":
                value["measurements"] = {
                    "producer_pid": 100,
                    "consumer_pid": 101,
                    "distinct_processes": True,
                    "checkpoint_bytes": 128,
                    "roundtrip_equivalent": True,
                }
            cases.append(value)
        by_id = {case["id"]: case for case in cases}
        if runtime == "mindspore-graph":
            by_id["graph-compile-failure-injected"].update(
                {
                    "status": "expected_error",
                    "phase": "compile",
                    "observed_category": "graph_compile_failure",
                    "error": {"type": "AttributeError", "message": "injected"},
                }
            )
            by_id["shape-specialization-injected"].update(
                {
                    "status": "expected_error",
                    "phase": "runtime",
                    "observed_category": "shape_mismatch",
                    "error": {"type": "ValueError", "message": "injected"},
                }
            )
            by_id["gradient-mismatch-injected"]["measurements"] = {
                "gradient_signature": [1.5, 3.0]
            }
            by_id["optimizer-state-mismatch-injected"]["measurements"] = {
                "beta2": 0.9,
                "final_parameters": [0.4],
            }
        else:
            by_id["gradient-mismatch-injected"]["measurements"] = {
                "gradient_signature": [1.0, 2.0]
            }
            by_id["optimizer-state-mismatch-injected"]["measurements"] = {
                "beta2": 0.999,
                "final_parameters": [0.2],
            }
        if runtime != "pytorch":
            by_id["mlp-adamw-schedule-5step"]["measurements"] = {
                "losses": [1.0, 0.6, 0.3],
                "final_parameters": [0.4, -0.2, 0.2],
            }
        if runtime == "mindspore-pynative":
            by_id["runtime-error-injected"].update(
                {
                    "status": "expected_error",
                    "phase": "runtime",
                    "observed_category": "runtime_error",
                    "error": {"type": "RuntimeError", "message": "injected"},
                }
            )
        payload = {
            "schema_version": "1.0",
            "record_kind": "advanced_training_capture",
            "benchmark_version": "advanced-training-v1",
            "runtime": runtime,
            "framework": "pytorch" if runtime == "pytorch" else "mindspore",
            "framework_version": "2.6.0" if runtime == "pytorch" else "2.9.0",
            "version_compatible": True,
            "execution_mode": "eager" if runtime == "pytorch" else runtime.removeprefix("mindspore-"),
            "device_target": "CPU",
            "python_version": "3.10.20",
            "platform": "test",
            "processor": "test",
            "status": "captured",
            "case_count": len(cases),
            "cases": copy.deepcopy(cases),
        }
        (root / f"{runtime}.json").write_text(json.dumps(payload), encoding="utf-8")
