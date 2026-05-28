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
fn read_tool_requires_file_path() {
    let registry = ToolRegistry::default_read_only();
    let err = registry
        .execute("read", "{}")
        .expect_err("missing path should fail");
    assert_eq!(err, "missing file_path");
}

#[test]
fn read_tool_errors_on_directory() {
    let dir = tempfile::tempdir().unwrap();
    let registry = ToolRegistry::default_read_only();
    let input = serde_json::json!({ "file_path": dir.path() }).to_string();
    let err = registry
        .execute("read", &input)
        .expect_err("directory should fail");
    assert!(err.contains("not a file"));
}

#[test]
fn read_tool_errors_on_missing_file() {
    let registry = ToolRegistry::default_read_only();
    let input = serde_json::json!({ "file_path": "/definitely/nonexistent/file.txt" }).to_string();
    let err = registry
        .execute("read", &input)
        .expect_err("missing file should fail");
    assert!(err.contains("not a file") || err.contains("failed to read"));
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
fn glob_tool_requires_pattern() {
    let registry = ToolRegistry::default_read_only();
    let err = registry
        .execute("glob", "{}")
        .expect_err("missing pattern should fail");
    assert_eq!(err, "missing pattern");
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
fn grep_tool_requires_pattern() {
    let registry = ToolRegistry::default_read_only();
    let err = registry
        .execute("grep", "{}")
        .expect_err("missing pattern should fail");
    assert_eq!(err, "missing pattern");
}

#[test]
fn grep_tool_defaults_to_current_dir() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("test.rs");
    fs::write(&file_path, "line with target\n").unwrap();

    let registry = ToolRegistry::default_read_only();
    let input = serde_json::json!({
        "pattern": "target",
        "path": dir.path(),
    })
    .to_string();
    let out = registry.execute("grep", &input).unwrap();

    assert!(out.contains("target"));
}
