use assert_cmd::Command;
use std::fs;
use tempfile::tempdir;

#[test]
fn prompt_mode_saves_session_file() {
    let session_dir = tempdir().unwrap();

    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .args(["prompt", "hello"])
        .assert()
        .success();

    let entries = fs::read_dir(session_dir.path()).unwrap().count();
    assert!(entries > 0);
}

#[test]
fn prompt_mode_can_run_through_bridge_runtime() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .env("CANDLE_CLI_RUNTIME", "bridge")
        .args(["prompt", "hello"])
        .assert()
        .success();

    let session_path = session_dir.path().join("session-1.json");
    let session_body = fs::read_to_string(session_path).unwrap();
    assert!(session_body.contains("generated: hello"));
}

#[test]
fn repl_mode_can_run_through_bridge_runtime() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .env("CANDLE_CLI_RUNTIME", "bridge")
        .write_stdin("hello\n")
        .assert()
        .success();

    let session_path = session_dir.path().join("session-1.json");
    let session_body = fs::read_to_string(session_path).unwrap();
    assert!(session_body.contains("generated: hello"));
}
