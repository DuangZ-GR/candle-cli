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
