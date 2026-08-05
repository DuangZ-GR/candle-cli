use assert_cmd::Command;
use serde_json::Value;
use std::fs;
use tempfile::tempdir;

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
