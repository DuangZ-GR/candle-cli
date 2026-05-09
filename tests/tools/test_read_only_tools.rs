use candle_cli::tools::registry::ToolRegistry;
use std::fs;

#[test]
fn pwd_tool_runs() {
    let registry = ToolRegistry::default_read_only();
    let out = registry.execute("pwd", "{}").unwrap();
    assert!(!out.is_empty());
}

#[test]
fn read_tool_returns_file_contents() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello\nworld\n").unwrap();

    let registry = ToolRegistry::default_read_only();
    let input = serde_json::json!({ "file_path": file_path }).to_string();
    let out = registry.execute("read", &input).unwrap();

    assert_eq!(out, "hello\nworld\n");
}

#[test]
fn glob_tool_returns_sorted_matches() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("b.rs"), "fn b() {}\n").unwrap();
    fs::write(dir.path().join("a.rs"), "fn a() {}\n").unwrap();
    fs::write(dir.path().join("note.txt"), "ignore\n").unwrap();

    let registry = ToolRegistry::default_read_only();
    let pattern = format!("{}/*.rs", dir.path().display());
    let input = serde_json::json!({ "pattern": pattern }).to_string();
    let out = registry.execute("glob", &input).unwrap();

    let lines: Vec<&str> = out.lines().collect();
    assert_eq!(lines.len(), 2);
    assert!(lines[0].ends_with("a.rs"));
    assert!(lines[1].ends_with("b.rs"));
}

#[test]
fn grep_tool_returns_path_line_and_text() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("main.rs");
    fs::write(&file_path, "alpha\nneedle here\nomega\n").unwrap();

    let registry = ToolRegistry::default_read_only();
    let input = serde_json::json!({
        "pattern": "needle",
        "path": dir.path(),
    })
    .to_string();
    let out = registry.execute("grep", &input).unwrap();

    assert!(out.contains("main.rs:2:needle here"));
}

#[test]
fn read_tool_requires_file_path() {
    let registry = ToolRegistry::default_read_only();
    let err = registry.execute("read", "{}").expect_err("missing path should fail");
    assert_eq!(err, "missing file_path");
}
