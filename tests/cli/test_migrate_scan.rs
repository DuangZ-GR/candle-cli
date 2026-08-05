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
    assert!(result["evidence_urls"].as_array().unwrap().len() > 0);
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
