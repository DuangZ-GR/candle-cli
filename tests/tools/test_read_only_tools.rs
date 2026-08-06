use candle_cli::tools::registry::ToolRegistry;
use std::fs;

#[cfg(unix)]
use std::os::unix::fs::symlink;

#[test]
fn pwd_tool_runs() {
    let dir = tempfile::tempdir().unwrap();
    let registry = ToolRegistry::read_only(dir.path());
    let out = registry.execute("pwd", "{}").unwrap();
    assert!(!out.is_empty());
}

#[test]
fn read_tool_returns_file_contents() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello\nworld\n").unwrap();

    let registry = ToolRegistry::read_only(dir.path());
    let input = serde_json::json!({ "file_path": "note.txt" }).to_string();
    let out = registry.execute("read", &input).unwrap();

    assert_eq!(out, "hello\nworld\n");
}

#[test]
fn read_tool_rejects_files_above_the_configured_limit() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("large.txt");
    fs::write(&path, "0123456789").unwrap();
    let error = candle_cli::tools::builtin::read::run(path.to_str().unwrap(), 5).unwrap_err();

    assert!(error.contains("file exceeds read limit"));
}

#[test]
fn glob_tool_returns_sorted_matches() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("b.rs"), "fn b() {}\n").unwrap();
    fs::write(dir.path().join("a.rs"), "fn a() {}\n").unwrap();
    fs::write(dir.path().join("note.txt"), "ignore\n").unwrap();

    let registry = ToolRegistry::read_only(dir.path());
    let input = serde_json::json!({ "pattern": "*.rs" }).to_string();
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

    let registry = ToolRegistry::read_only(dir.path());
    let input = serde_json::json!({
        "pattern": "needle",
        "path": ".",
    })
    .to_string();
    let out = registry.execute("grep", &input).unwrap();

    assert!(out.contains("main.rs:2:needle here"));
}

#[test]
fn read_tool_rejects_path_escape() {
    let dir = tempfile::tempdir().unwrap();
    let outside = tempfile::NamedTempFile::new().unwrap();
    fs::write(outside.path(), "secret\n").unwrap();

    let registry = ToolRegistry::read_only(dir.path());
    let input = serde_json::json!({ "file_path": outside.path() }).to_string();
    let err = registry.execute("read", &input).unwrap_err();

    assert!(err.contains("path escapes workspace"));
}

#[test]
fn grep_tool_rejects_search_root_outside_workspace() {
    let dir = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    fs::write(outside.path().join("main.rs"), "needle\n").unwrap();

    let registry = ToolRegistry::read_only(dir.path());
    let input = serde_json::json!({
        "pattern": "needle",
        "path": outside.path(),
    })
    .to_string();
    let err = registry.execute("grep", &input).unwrap_err();

    assert!(err.contains("path escapes workspace"));
}

#[cfg(unix)]
#[test]
fn read_tool_rejects_symlink_escape() {
    let dir = tempfile::tempdir().unwrap();
    let outside = tempfile::NamedTempFile::new().unwrap();
    fs::write(outside.path(), "secret\n").unwrap();
    let link_path = dir.path().join("escape.txt");
    symlink(outside.path(), &link_path).unwrap();

    let registry = ToolRegistry::read_only(dir.path());
    let input = serde_json::json!({ "file_path": "escape.txt" }).to_string();
    let err = registry.execute("read", &input).unwrap_err();

    assert!(err.contains("path escapes workspace"));
}

#[cfg(unix)]
#[test]
fn recursive_search_tools_do_not_follow_internal_symlinks() {
    let workspace = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    fs::write(outside.path().join("secret.rs"), "exfiltration_marker\n").unwrap();
    symlink(outside.path(), workspace.path().join("linked-outside")).unwrap();

    let registry = ToolRegistry::read_only(workspace.path());
    let grep = registry
        .execute("grep", r#"{"pattern":"exfiltration_marker","path":"."}"#)
        .unwrap();
    let glob = registry
        .execute("glob", r#"{"pattern":"**/*.rs"}"#)
        .unwrap();

    assert!(grep.is_empty());
    assert!(glob.is_empty());
}
