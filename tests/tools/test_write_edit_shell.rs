use candle_cli::tools::registry::ToolRegistry;
use std::fs;

#[test]
fn shell_tool_executes_command_inside_workspace_root() {
    let dir = tempfile::tempdir().unwrap();
    let registry = ToolRegistry::workspace_write(dir.path());
    let result = registry.execute("shell", r#"{"command":"pwd"}"#).unwrap();
    assert!(result.contains("status: ok"));
    assert!(result.contains("tool: shell"));
    assert!(result.contains("exit_code: 0"));
    assert!(result.contains(&dir.path().display().to_string()));
}

#[test]
fn shell_tool_times_out() {
    let dir = tempfile::tempdir().unwrap();
    let registry = ToolRegistry::workspace_write(dir.path());
    std::env::set_var("CANDLE_CLI_SHELL_TIMEOUT_SECS", "1");
    let err = registry
        .execute("shell", r#"{"command":"sleep 2"}"#)
        .unwrap_err();
    std::env::remove_var("CANDLE_CLI_SHELL_TIMEOUT_SECS");

    assert!(err.contains("status: error"));
    assert!(err.contains("tool: shell"));
    assert!(err.contains("timeout: true"));
    assert!(err.contains("command timed out after 1s"));
}

#[test]
fn edit_tool_replaces_exactly_one_match() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello\n").unwrap();

    let registry = ToolRegistry::workspace_write(dir.path());
    let input = serde_json::json!({
        "file_path": "note.txt",
        "old_string": "hello",
        "new_string": "world",
    })
    .to_string();

    let out = registry.execute("edit", &input).unwrap();
    assert_eq!(out, "edited");
    assert_eq!(fs::read_to_string(&file_path).unwrap(), "world\n");
}

#[test]
fn edit_tool_rejects_path_escape() {
    let dir = tempfile::tempdir().unwrap();
    let outside = tempfile::NamedTempFile::new().unwrap();
    fs::write(outside.path(), "hello\n").unwrap();

    let registry = ToolRegistry::workspace_write(dir.path());
    let input = serde_json::json!({
        "file_path": outside.path(),
        "old_string": "hello",
        "new_string": "world",
    })
    .to_string();

    let err = registry.execute("edit", &input).unwrap_err();
    assert!(err.contains("path escapes workspace"));
}

#[test]
fn edit_tool_fails_when_old_string_is_absent() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello\n").unwrap();

    let registry = ToolRegistry::workspace_write(dir.path());
    let input = serde_json::json!({
        "file_path": "note.txt",
        "old_string": "missing",
        "new_string": "world",
    })
    .to_string();

    let err = registry.execute("edit", &input).unwrap_err();
    assert!(err.contains("old_string not found"));
}

#[test]
fn edit_tool_fails_when_old_string_matches_multiple_times() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello hello\n").unwrap();

    let registry = ToolRegistry::workspace_write(dir.path());
    let input = serde_json::json!({
        "file_path": "note.txt",
        "old_string": "hello",
        "new_string": "world",
    })
    .to_string();

    let err = registry.execute("edit", &input).unwrap_err();
    assert!(err.contains("old_string matched 2 times"));
}

#[test]
fn shell_tool_returns_error_envelope_for_non_zero_exit() {
    let dir = tempfile::tempdir().unwrap();
    let registry = ToolRegistry::workspace_write(dir.path());
    let err = registry
        .execute("shell", r#"{"command":"sh -lc 'exit 7'"}"#)
        .unwrap_err();

    assert!(err.contains("status: error"));
    assert!(err.contains("tool: shell"));
    assert!(err.contains("exit_code: 7"));
}
