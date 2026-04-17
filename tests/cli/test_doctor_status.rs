use assert_cmd::Command;

#[test]
fn doctor_mode_reports_runtime_status() {
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.arg("doctor");
    let output = cmd.assert().success();
    let stdout = String::from_utf8_lossy(&output.get_output().stdout);
    assert!(stdout.contains("runtime"));
}
