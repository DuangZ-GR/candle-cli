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
