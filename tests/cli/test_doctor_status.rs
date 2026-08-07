use assert_cmd::Command;
use serde_json::Value;

#[test]
fn doctor_mode_reports_runtime_status() {
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.arg("doctor");
    let output = cmd.assert().success();
    let stdout = String::from_utf8_lossy(&output.get_output().stdout);
    assert!(stdout.contains("runtime"));
    assert!(stdout.contains("ready_for_bridge"));
}

#[test]
fn doctor_json_reports_all_dependency_classes_without_exposing_secrets() {
    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .args(["doctor", "--json"])
        .env("CANDLE_CLI_API_KEY", "doctor-test-secret")
        .output()
        .unwrap();

    assert!(output.status.success());
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    let names: Vec<_> = report["checks"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|check| check["name"].as_str())
        .collect();
    for expected in [
        "rust",
        "python",
        "pytorch",
        "mindspore",
        "docker",
        "python-bridge-worker",
        "pytorch-python-env",
        "mindspore-python-env",
        "provider-config",
    ] {
        assert!(names.contains(&expected));
    }
    assert!(!String::from_utf8_lossy(&output.stdout).contains("doctor-test-secret"));
}
