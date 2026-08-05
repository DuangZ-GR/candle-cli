use assert_cmd::Command;
use serde_json::Value;

#[test]
fn binary_starts_and_shows_help() {
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.arg("--help");
    cmd.assert().success();
}

#[test]
fn security_harness_emits_a_passing_structured_report() {
    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .arg("security-harness")
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["attack_interception_rate"], 1.0);
    assert_eq!(report["benign_false_positive_rate"], 0.0);
    assert_eq!(report["passed"], true);
}

#[test]
fn context_harness_emits_a_passing_structured_report_without_fake_cache_metrics() {
    let output = Command::cargo_bin("candle-cli")
        .unwrap()
        .arg("context-harness")
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["integrity_passed"], true);
    assert_eq!(report["provider_cache_metrics_available"], false);
    assert!(report["provider_cache_hit_rate"].is_null());
    assert_eq!(report["passed"], true);
}
