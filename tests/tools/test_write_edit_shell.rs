use candle_cli::tools::registry::ToolRegistry;
use std::fs;

#[test]
fn shell_tool_executes_command() {
    let registry = ToolRegistry::default_workspace_write();
    let result = registry.execute("shell", r#"{"command":"pwd"}"#).unwrap();
    assert!(!result.is_empty());
}

#[test]
fn edit_tool_replaces_exactly_one_match() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello\n").unwrap();

    let registry = candle_cli::tools::registry::ToolRegistry::default_workspace_write();
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

    let registry = candle_cli::tools::registry::ToolRegistry::default_workspace_write();
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

    let registry = candle_cli::tools::registry::ToolRegistry::default_workspace_write();
    let input = serde_json::json!({
        "file_path": file_path,
        "old_string": "hello",
        "new_string": "world",
    })
    .to_string();

    let err = registry.execute("edit", &input).unwrap_err();
    assert!(err.contains("old_string matched 2 times"));
}
