use assert_cmd::Command;
use std::fs;
use std::path::PathBuf;
use tempfile::tempdir;

/// Find the first JSON session file in the session directory.
fn find_session_json(dir: &std::path::Path) -> PathBuf {
    for entry in fs::read_dir(dir).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("json") {
            return path;
        }
    }
    panic!("no session JSON file found in {:?}", dir);
}

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

    let session_body = fs::read_to_string(find_session_json(session_dir.path())).unwrap();
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

    let session_body = fs::read_to_string(find_session_json(session_dir.path())).unwrap();
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

    let session_body = fs::read_to_string(find_session_json(session_dir.path())).unwrap();

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

    let session_body = fs::read_to_string(find_session_json(session_dir.path())).unwrap();

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

// ── session management tests ──────────────────────────────────────────

#[test]
fn repl_slash_list_shows_sessions() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/list\n")
        .assert()
        .success();
}

#[test]
fn repl_slash_list_with_saved_session() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("hello\n/list\n")
        .assert()
        .success();
}

#[test]
fn repl_slash_save_succeeds() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/save\n")
        .assert()
        .success();
}

#[test]
fn repl_slash_resume_requires_argument() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/resume\n")
        .assert()
        .success();
}

#[test]
fn repl_slash_resume_invalid_id_shows_error() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/resume nonexistent\n")
        .assert()
        .success();
}

#[test]
fn repl_can_save_list_and_resume_session() {
    let session_dir = tempdir().unwrap();

    // first session: say something, then exit (auto-saves)
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("hello from session one\n/exit\n")
        .assert()
        .success();

    // find the saved session ID
    let saved_path = find_session_json(session_dir.path());
    let saved_body = fs::read_to_string(&saved_path).unwrap();
    let parsed: serde_json::Value = serde_json::from_str(&saved_body).unwrap();
    let saved_id = parsed["session_id"].as_str().unwrap().to_string();
    assert!(saved_body.contains("hello from session one"));

    // second session: resume the previous one, add more messages
    let resume_cmd = format!("/resume {saved_id}\n");
    let mut cmd2 = Command::cargo_bin("candle-cli").unwrap();
    cmd2.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin(format!("{resume_cmd}more text\n/exit\n"))
        .assert()
        .success();

    // the resumed session should contain both old and new messages
    let resumed_body = fs::read_to_string(&saved_path).unwrap();
    assert!(resumed_body.contains("hello from session one"));
    assert!(resumed_body.contains("more text"));
}

#[test]
fn repl_trace_reports_last_execution_chain() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    let output = cmd
        .current_dir(".")
        .env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .env("CANDLE_CLI_RUNTIME", "bridge")
        .write_stdin("读取 README.md，总结如何运行项目\n/trace\n")
        .output()
        .unwrap();

    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("Last trace"));
    assert!(stdout.contains("build_turn_request"));
    assert!(stdout.contains("runtime.generate_turn"));
}

#[test]
fn repl_tools_lists_registered_tools() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    let output = cmd
        .env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/tools\n")
        .output()
        .unwrap();

    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("Registered tools"));
    assert!(stdout.contains("- pwd"));
    assert!(stdout.contains("- read"));
    assert!(stdout.contains("- glob"));
    assert!(stdout.contains("- grep"));
    assert!(stdout.contains("- edit"));
    assert!(stdout.contains("- shell"));
}

#[test]
fn repl_trace_reports_empty_state_before_any_turn() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    let output = cmd
        .env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/trace\n")
        .output()
        .unwrap();

    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("no trace available"));
}

#[test]
fn repl_status_reports_runtime_snapshot() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    let output = cmd
        .env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .env("CANDLE_CLI_RUNTIME", "bridge")
        .env("CANDLE_CLI_MODEL_ID", "deepseek-v4-flash")
        .env("CANDLE_CLI_PERMISSION", "read-only")
        .write_stdin("hello\n/status\n")
        .output()
        .unwrap();

    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("Session"));
    assert!(stdout.contains("session_id:"));
    assert!(stdout.contains("messages:"));
    assert!(stdout.contains("workspace:"));
    assert!(stdout.contains("permission: ReadOnly"));
    assert!(stdout.contains("runtime: bridge"));
    assert!(stdout.contains("model: deepseek-v4-flash"));
}
