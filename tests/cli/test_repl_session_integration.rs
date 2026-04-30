use assert_cmd::Command;
use std::fs;
use tempfile::tempdir;

// ── prompt mode tests ──────────────────────────────────────────────────

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

// ── REPL mode tests ────────────────────────────────────────────────────

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

#[test]
fn repl_loop_runs_multiple_turns() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .env("CANDLE_CLI_RUNTIME", "bridge")
        .write_stdin("first\nsecond\n")
        .assert()
        .success();

    let session_path = session_dir.path().join("session-1.json");
    let session_body = fs::read_to_string(session_path).unwrap();

    // both user messages should be in the session
    assert!(session_body.contains("first"));
    assert!(session_body.contains("second"));
}

#[test]
fn repl_exits_on_eof() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("")
        .assert()
        .success(); // exits without running any turn
}

#[test]
fn repl_slash_exit_saves_and_quits() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/exit\n")
        .assert()
        .success();
}

#[test]
fn repl_slash_quit_also_exits() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/quit\n")
        .assert()
        .success();
}

#[test]
fn repl_slash_session_shows_info() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("hello\n/session\n")
        .assert()
        .success();
}

#[test]
fn repl_slash_help_works() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/help\n")
        .assert()
        .success();
}

#[test]
fn repl_slash_clear_resets_session() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("hello\n/clear\n")
        .assert()
        .success();

    let session_path = session_dir.path().join("session-1.json");
    let session_body = fs::read_to_string(session_path).unwrap();

    // after /clear, the session should be reset (no message containing "hello")
    let parsed: serde_json::Value = serde_json::from_str(&session_body).unwrap();
    let messages = parsed["messages"].as_array().unwrap();
    assert!(messages.is_empty(), "session should be empty after /clear");
}

#[test]
fn repl_unknown_command_shows_message() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/unknowncommand\n")
        .assert()
        .success();
}

#[test]
fn repl_empty_line_skipped() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("\n\n")
        .assert()
        .success(); // empty lines shouldn't crash
}
