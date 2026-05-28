use candle_cli::tools::registry::ToolRegistry;
use std::fs;

#[test]
fn shell_tool_executes_command() {
    let registry = ToolRegistry::default_workspace_write();
    let result = registry.execute("shell", r#"{"command":"pwd"}"#).unwrap();
    assert!(!result.is_empty());
}

#[test]
fn shell_tool_rejected_in_read_only() {
    let registry = ToolRegistry::default_read_only();
    let err = registry
        .execute("shell", r#"{"command":"pwd"}"#)
        .expect_err("shell should be rejected in read-only mode");
    assert!(err.contains("read-only"));
}

#[test]
fn edit_tool_replaces_exactly_one_match() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello\n").unwrap();

    let registry = ToolRegistry::default_workspace_write();
    let input = serde_json::json!({
        "file_path": file_path,
        "old_string": "hello",
        "new_string": "world",
    })
    .to_string();

    let out = registry.execute("edit", &input).unwrap();
    assert_eq!(out, "edited");
    assert_eq!(fs::read_to_string(&file_path).unwrap(), "world\n");
}

#[test]
fn edit_tool_fails_when_old_string_is_absent() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello\n").unwrap();

    let registry = ToolRegistry::default_workspace_write();
    let input = serde_json::json!({
        "file_path": file_path,
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

    let registry = ToolRegistry::default_workspace_write();
    let input = serde_json::json!({
        "file_path": file_path,
        "old_string": "hello",
        "new_string": "world",
    })
    .to_string();

    let err = registry.execute("edit", &input).unwrap_err();
    assert!(err.contains("matched 2 times"));
}

#[test]
fn edit_tool_rejected_in_read_only() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello\n").unwrap();

    let registry = ToolRegistry::default_read_only();
    let input = serde_json::json!({
        "file_path": file_path,
        "old_string": "hello",
        "new_string": "world",
    })
    .to_string();

    let err = registry
        .execute("edit", &input)
        .expect_err("edit should be rejected");
    assert!(err.contains("read-only"));
}

#[test]
fn write_tool_rejected_in_read_only() {
    let registry = ToolRegistry::default_read_only();
    let err = registry
        .execute("write", r#"{"file_path":"/tmp/test.txt","content":"data"}"#)
        .expect_err("write should be rejected");
    assert!(err.contains("read-only"));
}
