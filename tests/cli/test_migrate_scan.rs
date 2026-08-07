use assert_cmd::Command;
use serde_json::Value;
use std::fs;
use tempfile::tempdir;

fn trace_record(framework: &str, api: &str, dtype: &str) -> String {
    serde_json::json!({
        "schema_version": "1.0",
        "record_kind": "api_trace",
        "run_id": "run-cli-compare",
        "framework": framework,
        "framework_version": if framework == "pytorch" { "2.1" } else { "2.9.0" },
        "execution_mode": if framework == "pytorch" { "eager" } else { "py_native" },
        "location": { "file": "model.py", "line": 1, "column": 0 },
        "api": api,
        "call_index": 0,
        "output": { "kind": "tensor", "dtype": dtype, "shape": [2] }
    })
    .to_string()
}

fn test_python() -> String {
    std::env::var("CANDLE_CLI_TEST_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    })
}

#[test]
fn migrate_scan_emits_a_json_report() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("model.py"),
        "import torch\nvalue = torch.sum(x, dim=1)\n",
    )
    .unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "scan"])
        .arg(project.path())
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["record_kind"], "scan_report");
    assert_eq!(report["summary"]["finding_count"], 1);
    assert_eq!(report["findings"][0]["api"], "torch.sum");
    assert_eq!(report["findings"][0]["location"]["file"], "model.py");
}

#[test]
fn migrate_run_previews_the_complete_workflow() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("model.py"),
        "import torch\nvalue = torch.add(x, 1)\n",
    )
    .unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "run"])
        .arg(project.path())
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["record_kind"], "migration_run_report");
    assert_eq!(report["status"], "previewed");
    assert_eq!(report["steps"][0]["name"], "scan");
    assert_eq!(report["steps"][1]["name"], "rewrite_preview");
    assert_eq!(report["summary"]["finding_count"], 1);
    assert_eq!(report["summary"]["files_changed"], 1);
}

#[test]
fn migrate_run_renders_attached_data_pipeline_report() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("model.py"),
        "import torch\nvalue = torch.add(x, 1)\n",
    )
    .unwrap();
    let mut cases: Vec<Value> = (0..11)
        .map(|index| {
            serde_json::json!({
                "case_id": format!("deterministic-{index}"),
                "comparison_kind": "deterministic",
                "elementwise_compared": false
            })
        })
        .collect();
    cases.push(serde_json::json!({
        "case_id": "random-statistical",
        "comparison_kind": "statistical",
        "sample_size": 128,
        "statistics": {"source": {"mean": 0.0}, "target": {"mean": 0.0}},
        "thresholds": {"max_mean_delta": 0.1},
        "elementwise_compared": false
    }));
    let pipeline_path = project.path().join("pipeline.json");
    fs::write(
        &pipeline_path,
        serde_json::json!({
            "schema_version": "1.0",
            "record_kind": "data_pipeline_diagnostic_report",
            "benchmark_version": "data-pipeline-randomness-v1",
            "dataset_kind": "cross_framework_data_pipeline_cases",
            "complete": true,
            "passed": true,
            "case_count": 12,
            "evaluated_case_count": 12,
            "fault_case_count": 5,
            "stochastic_case_count": 1,
            "minimum_stochastic_sample_size": 128,
            "classification_accuracy": 1.0,
            "first_divergence_top1_accuracy": 1.0,
            "deterministic_equivalence_rate": 1.0,
            "statistical_equivalence_rate": 1.0,
            "first_divergence_categories": {"layout_mismatch": 1},
            "source_framework_version": "2.6.0+cu124",
            "target_framework_version": "2.9.0",
            "splits": {},
            "cases": cases
        })
        .to_string(),
    )
    .unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "run"])
        .arg(project.path())
        .args(["--data-pipeline-report"])
        .arg(pipeline_path)
        .args(["--format", "markdown"])
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let markdown = String::from_utf8(output.stdout).unwrap();
    assert!(markdown.contains("## Data pipeline and randomness"));
    assert!(markdown.contains("First-divergence Top-1: `100.00%`"));
}

#[test]
fn migrate_run_renders_attached_advanced_training_report() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("model.py"),
        "import torch\nvalue = torch.add(x, 1)\n",
    )
    .unwrap();
    let training_path = project.path().join("advanced-training.json");
    let cases: Vec<Value> = (0..13)
        .map(|index| serde_json::json!({"id": format!("case-{index}")}))
        .collect();
    fs::write(
        &training_path,
        serde_json::json!({
            "schema_version": "1.0",
            "record_kind": "advanced_training_report",
            "benchmark_version": "advanced-training-v1",
            "complete": true,
            "passed": true,
            "case_count": 13,
            "evaluated_case_count": 13,
            "fault_case_count": 5,
            "mode_component_count": 4,
            "multi_step_optimizer_case_count": 3,
            "checkpoint_case_count": 1,
            "classification_accuracy": 1.0,
            "diagnostic_top1_accuracy": 1.0,
            "mode_parity_rate": 1.0,
            "multi_step_optimizer_parity_rate": 0.666667,
            "checkpoint_restore_rate": 1.0,
            "first_divergence_categories": {"optimizer_state_mismatch": 2},
            "runtime_environments": {
                "pytorch": {"device_target": "CPU"},
                "mindspore-pynative": {"device_target": "CPU"},
                "mindspore-graph": {"device_target": "CPU"}
            },
            "cases": cases
        })
        .to_string(),
    )
    .unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "run"])
        .arg(project.path())
        .arg("--advanced-training-report")
        .arg(training_path)
        .args(["--format", "markdown"])
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let markdown = String::from_utf8(output.stdout).unwrap();
    assert!(markdown.contains("## Graph mode and advanced training"));
    assert!(markdown.contains("Mode/optimizer/checkpoint parity: `100.00%/66.67%/100.00%`"));
}

#[test]
fn migrate_run_validation_failure_restores_source_and_writes_report() {
    let project = tempdir().unwrap();
    let source = project.path().join("model.py");
    let original = "import torch\nvalue = torch.add(x, 1)\n";
    fs::write(&source, original).unwrap();
    let report_path = project.path().join("migration-report.json");
    let python = test_python();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", &python)
        .args(["migrate", "run"])
        .arg(project.path())
        .args([
            "--apply",
            "--validate-program",
            &python,
            "--validate-arg=-c",
            "--validate-arg=raise SystemExit(7)",
            "--output",
        ])
        .arg(&report_path)
        .output()
        .unwrap();

    assert!(!output.status.success());
    assert_eq!(fs::read_to_string(source).unwrap(), original);
    let report: Value = serde_json::from_slice(&fs::read(report_path).unwrap()).unwrap();
    assert_eq!(report["status"], "rolled_back");
    assert_eq!(report["error"]["stage"], "validation");
    assert_eq!(report["summary"]["validation_status"], "failed");
}

#[test]
fn migrate_scan_refuses_to_overwrite_output_without_force() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("model.py"),
        "import torch\ntorch.sum(x)\n",
    )
    .unwrap();
    let output_file = project.path().join("report.json");
    fs::write(&output_file, "keep me").unwrap();

    Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "scan"])
        .arg(project.path())
        .arg("--output")
        .arg(&output_file)
        .assert()
        .failure();

    assert_eq!(fs::read_to_string(output_file).unwrap(), "keep me");
}

#[test]
fn migrate_scan_preserves_partial_report_when_a_file_has_a_syntax_error() {
    let project = tempdir().unwrap();
    fs::write(project.path().join("bad.py"), "def broken(:\n").unwrap();
    fs::write(
        project.path().join("good.py"),
        "import torch\ntorch.sum(x)\n",
    )
    .unwrap();
    let output_file = project.path().join("report.json");

    Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "scan"])
        .arg(project.path())
        .arg("--output")
        .arg(&output_file)
        .assert()
        .failure();

    let report: Value = serde_json::from_slice(&fs::read(output_file).unwrap()).unwrap();
    assert_eq!(report["summary"]["finding_count"], 1);
    assert_eq!(report["summary"]["issue_count"], 1);
    assert_eq!(report["issues"][0]["kind"], "syntax_error");
}

#[test]
fn migrate_scan_can_write_a_markdown_report() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("model.py"),
        "import torch\ntorch.sum(x, dim=1)\n",
    )
    .unwrap();
    let output_file = project.path().join("report.md");

    Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "scan"])
        .arg(project.path())
        .args(["--format", "markdown", "--output"])
        .arg(&output_file)
        .assert()
        .success();

    let markdown = fs::read_to_string(output_file).unwrap();
    assert!(markdown.contains("# Torch2MindSpore Scan Report"));
    assert!(markdown.contains("`torch.sum`"));
    assert!(markdown.contains("`model.py:2:0`"));
}

#[test]
fn migrate_map_returns_an_evidence_backed_exact_mapping() {
    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "map", "torch.sum"])
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["status"], "exact");
    assert_eq!(result["target_api"], "mindspore.mint.sum");
    assert_eq!(result["target_framework_version"], "2.9.0");
    assert!(!result["evidence_urls"].as_array().unwrap().is_empty());
}

#[test]
fn migrate_map_returns_unknown_without_claiming_unsupported() {
    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "map", "torch.future_operator"])
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["status"], "unknown");
    assert!(result["target_api"].is_null());
    assert!(result["notes"].as_str().unwrap().contains("不能据此判断"));
}

#[test]
fn migrate_scan_includes_mapping_and_updates_risk() {
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("model.py"),
        "import torch\na = torch.sum(x)\nb = torch.arange(10)\n",
    )
    .unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "scan"])
        .arg(project.path())
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    let findings = report["findings"].as_array().unwrap();
    assert_eq!(findings[0]["mapping"]["status"], "exact");
    assert_eq!(findings[0]["risk_level"], "low");
    assert_eq!(findings[1]["mapping"]["status"], "difference");
    assert_eq!(findings[1]["risk_level"], "medium");
}

#[test]
fn migrate_compare_reports_equivalent_traces() {
    let directory = tempdir().unwrap();
    let source = directory.path().join("torch.jsonl");
    let target = directory.path().join("mindspore.jsonl");
    fs::write(&source, trace_record("pytorch", "torch.sum", "float32")).unwrap();
    fs::write(
        &target,
        trace_record("mindspore", "mindspore.mint.sum", "float32"),
    )
    .unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "compare"])
        .arg(source)
        .arg(target)
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["equivalent"], true);
    assert!(result["diagnostic"].is_null());
}

#[test]
fn migrate_compare_reports_a_verified_dtype_divergence() {
    let directory = tempdir().unwrap();
    let source = directory.path().join("torch.jsonl");
    let target = directory.path().join("mindspore.jsonl");
    fs::write(&source, trace_record("pytorch", "torch.sum", "float32")).unwrap();
    fs::write(
        &target,
        trace_record("mindspore", "mindspore.mint.sum", "bool"),
    )
    .unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "compare"])
        .arg(source)
        .arg(target)
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["equivalent"], false);
    assert_eq!(result["diagnostic"]["category"], "dtype_mismatch");
    assert_eq!(result["diagnostic"]["verified"], true);
}

#[test]
fn migrate_import_msprobe_writes_a_valid_canonical_trace() {
    let directory = tempdir().unwrap();
    let dump_path = directory.path().join("dump.json");
    let trace_path = directory.path().join("trace.jsonl");
    fs::write(
        &dump_path,
        serde_json::json!({
            "Mint.add.0.forward": {
                "input_args": [],
                "input_kwargs": {},
                "output": [{
                    "type": "mindspore.Tensor",
                    "dtype": "Float32",
                    "shape": [2],
                    "Max": 2.0,
                    "Min": 1.0,
                    "Mean": 1.5
                }]
            }
        })
        .to_string(),
    )
    .unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "import-msprobe"])
        .arg(&dump_path)
        .arg(&trace_path)
        .args([
            "--framework",
            "mindspore",
            "--framework-version",
            "2.9.0",
            "--run-id",
            "run-msprobe-cli",
        ])
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["record_kind"], "msprobe_import_report");
    assert_eq!(report["records_imported"], 1);
    let trace = fs::read_to_string(trace_path).unwrap();
    let record: Value = serde_json::from_str(trace.trim()).unwrap();
    assert_eq!(record["api"], "mindspore.mint.add");
    assert_eq!(record["output"]["dtype"], "float32");
}

#[test]
fn migrate_rewrite_previews_without_modifying_source() {
    let directory = tempdir().unwrap();
    let source_path = directory.path().join("model.py");
    fs::write(&source_path, "import torch\ny = torch.add(x, 1)\n").unwrap();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "rewrite"])
        .arg(&source_path)
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["record_kind"], "rewrite_plan");
    assert_eq!(report["files_changed"], 1);
    assert!(report["files"][0]["diff"]
        .as_str()
        .unwrap()
        .contains("mindspore.mint.add"));
    assert!(fs::read_to_string(source_path)
        .unwrap()
        .contains("torch.add"));
}

#[test]
fn migrate_rewrite_apply_and_rollback_restore_source() {
    let directory = tempdir().unwrap();
    let source_path = directory.path().join("model.py");
    let original = "import torch\ny = torch.add(x, 1)\n";
    fs::write(&source_path, original).unwrap();

    let apply_output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "rewrite"])
        .arg(&source_path)
        .arg("--apply")
        .output()
        .unwrap();
    assert!(
        apply_output.status.success(),
        "{}",
        String::from_utf8_lossy(&apply_output.stderr)
    );
    let apply_report: Value = serde_json::from_slice(&apply_output.stdout).unwrap();
    assert_eq!(apply_report["record_kind"], "rewrite_apply_report");
    assert!(fs::read_to_string(&source_path)
        .unwrap()
        .contains("mindspore.mint.add"));

    let rollback_output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", test_python())
        .args(["migrate", "rollback"])
        .arg(apply_report["manifest"].as_str().unwrap())
        .output()
        .unwrap();
    assert!(
        rollback_output.status.success(),
        "{}",
        String::from_utf8_lossy(&rollback_output.stderr)
    );
    let rollback_report: Value = serde_json::from_slice(&rollback_output.stdout).unwrap();
    assert_eq!(rollback_report["record_kind"], "rewrite_rollback_report");
    assert_eq!(fs::read_to_string(source_path).unwrap(), original);
}

#[test]
fn migrate_rewrite_only_marks_successful_validation_as_verified() {
    let directory = tempdir().unwrap();
    let source_path = directory.path().join("model.py");
    fs::write(&source_path, "import torch\ny = torch.add(x, 1)\n").unwrap();
    let python = test_python();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", &python)
        .args(["migrate", "rewrite"])
        .arg(&source_path)
        .args([
            "--apply",
            "--validate-program",
            &python,
            "--validate-arg=-c",
            "--validate-arg=print('ok')",
        ])
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["verified"], true);
    assert_eq!(report["validation"]["status"], "passed");
    assert_eq!(report["validation"]["return_code"], 0);
}

#[test]
fn migrate_rewrite_validation_failure_restores_source() {
    let directory = tempdir().unwrap();
    let source_path = directory.path().join("model.py");
    let original = "import torch\ny = torch.add(x, 1)\n";
    fs::write(&source_path, original).unwrap();
    let python = test_python();

    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .env("CANDLE_CLI_PYTHON", &python)
        .args(["migrate", "rewrite"])
        .arg(&source_path)
        .args([
            "--apply",
            "--validate-program",
            &python,
            "--validate-arg=-c",
            "--validate-arg=raise SystemExit(7)",
        ])
        .output()
        .unwrap();

    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("rolled back"));
    assert_eq!(fs::read_to_string(source_path).unwrap(), original);
}
