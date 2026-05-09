# Minimal Agentic Coding Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v0.3.0 minimal coding-agent loop: read/search files, edit existing files, run shell commands, feed tool results back into the model, and stop on a final answer.

**Architecture:** Add a text `<tool_call>{...}</tool_call>` parser, make read/glob/grep real tools, and upgrade the agent loop from single-shot generation to a bounded multi-step loop. Prompt and REPL modes will use `workspace-write` tools so the closed loop can run end-to-end before richer permission prompts are added later.

**Tech Stack:** Rust 2021, serde/serde_json, tempfile/assert_cmd test utilities, Python bridge tests for regression verification.

---

## File Structure Map

- `src/agent/tool_call.rs` — new parser for `<tool_call>{...}</tool_call>` blocks.
- `src/agent/loop.rs` — upgrade `run_single_turn` to bounded multi-step tool loop.
- `src/agent/mod.rs` — export the new `tool_call` module.
- `src/tools/registry.rs` — parse JSON input for `read`, `glob`, and `grep`; keep mutation tools behind `workspace-write`.
- `src/tools/builtin/read.rs` — implement real UTF-8 file reads.
- `src/tools/builtin/glob.rs` — implement deterministic file matching.
- `src/tools/builtin/grep.rs` — implement deterministic text search with path and line numbers.
- `src/tools/builtin/edit.rs` — make edit fail unless `old_string` appears exactly once.
- `src/context/builder.rs` — expose tool-use prompt guidance and include it in the system prompt.
- `src/cli/repl.rs` — use `ToolRegistry::default_workspace_write()` in prompt and REPL mode.
- `tests/agent/test_tool_call_parser.rs` — parser unit tests.
- `tests/tools/test_read_only_tools.rs` — expand tests for read/glob/grep.
- `tests/tools/test_write_edit_shell.rs` — expand edit tests for exact replacement behavior.
- `tests/agent/test_agent_loop.rs` — add scripted runtime end-to-end tests for read → edit → shell → final answer, tool errors, and max steps.
- `README.md` — document minimal agentic loop protocol and example usage.
- `docs/superpowers/specs/2026-05-09-minimal-agentic-loop-design.md` — already created design spec; stage with implementation.

---

### Task 1: Add Tool Call Parser

**Files:**
- Create: `src/agent/tool_call.rs`
- Modify: `src/agent/mod.rs`
- Create: `tests/agent/test_tool_call_parser.rs`
- Modify: `Cargo.toml`

- [ ] **Step 1: Add parser test target to Cargo.toml**

Open `Cargo.toml` and add this test target near the other `[[test]]` entries:

```toml
[[test]]
name = "test_tool_call_parser"
path = "tests/agent/test_tool_call_parser.rs"
```

- [ ] **Step 2: Write failing parser tests**

Create `tests/agent/test_tool_call_parser.rs`:

```rust
use candle_cli::agent::tool_call::{parse_tool_call, ToolCallParseError};

#[test]
fn parses_valid_tool_call_block() {
    let parsed = parse_tool_call(
        r#"<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>"#,
    )
    .expect("valid tool call should parse")
    .expect("tool call block should be present");

    assert_eq!(parsed.id, "call-1");
    assert_eq!(parsed.name, "read");
    assert_eq!(parsed.input_json, r#"{"file_path":"README.md"}"#);
}

#[test]
fn returns_none_when_no_tool_call_block_exists() {
    let parsed = parse_tool_call("final answer only").expect("plain text should not error");
    assert!(parsed.is_none());
}

#[test]
fn rejects_malformed_json_inside_tool_call() {
    let err = parse_tool_call(r#"<tool_call>{"id":"call-1"</tool_call>"#)
        .expect_err("malformed JSON should fail");

    assert!(matches!(err, ToolCallParseError::InvalidJson(_)));
}

#[test]
fn rejects_missing_name() {
    let err = parse_tool_call(r#"<tool_call>{"id":"call-1","input":{}}</tool_call>"#)
        .expect_err("missing name should fail");

    assert_eq!(err.to_string(), "tool call is missing string field: name");
}

#[test]
fn rejects_non_object_input() {
    let err = parse_tool_call(
        r#"<tool_call>{"id":"call-1","name":"read","input":"README.md"}</tool_call>"#,
    )
    .expect_err("input must be an object");

    assert_eq!(err.to_string(), "tool call field 'input' must be an object");
}
```

- [ ] **Step 3: Run parser tests and confirm failure**

Run:

```bash
~/.cargo/bin/cargo test --test test_tool_call_parser
```

Expected: compile failure because `candle_cli::agent::tool_call` does not exist.

- [ ] **Step 4: Implement parser module**

Create `src/agent/tool_call.rs`:

```rust
use crate::model::types::ToolCallIntent;
use serde_json::Value;
use std::fmt;

const OPEN_TAG: &str = "<tool_call>";
const CLOSE_TAG: &str = "</tool_call>";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolCallParseError {
    MissingCloseTag,
    InvalidJson(String),
    MissingStringField(&'static str),
    InputMustBeObject,
    OuterMustBeObject,
}

impl fmt::Display for ToolCallParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingCloseTag => write!(f, "tool call block is missing </tool_call>"),
            Self::InvalidJson(msg) => write!(f, "tool call JSON is invalid: {msg}"),
            Self::MissingStringField(field) => {
                write!(f, "tool call is missing string field: {field}")
            }
            Self::InputMustBeObject => write!(f, "tool call field 'input' must be an object"),
            Self::OuterMustBeObject => write!(f, "tool call JSON must be an object"),
        }
    }
}

impl std::error::Error for ToolCallParseError {}

pub fn parse_tool_call(text: &str) -> Result<Option<ToolCallIntent>, ToolCallParseError> {
    let Some(start) = text.find(OPEN_TAG) else {
        return Ok(None);
    };

    let json_start = start + OPEN_TAG.len();
    let Some(relative_end) = text[json_start..].find(CLOSE_TAG) else {
        return Err(ToolCallParseError::MissingCloseTag);
    };
    let json_end = json_start + relative_end;
    let raw_json = text[json_start..json_end].trim();

    let value: Value = serde_json::from_str(raw_json)
        .map_err(|err| ToolCallParseError::InvalidJson(err.to_string()))?;
    let object = value
        .as_object()
        .ok_or(ToolCallParseError::OuterMustBeObject)?;

    let id = object
        .get("id")
        .and_then(Value::as_str)
        .ok_or(ToolCallParseError::MissingStringField("id"))?
        .to_string();
    let name = object
        .get("name")
        .and_then(Value::as_str)
        .ok_or(ToolCallParseError::MissingStringField("name"))?
        .to_string();
    let input = object
        .get("input")
        .ok_or(ToolCallParseError::InputMustBeObject)?;

    if !input.is_object() {
        return Err(ToolCallParseError::InputMustBeObject);
    }

    Ok(Some(ToolCallIntent {
        id,
        name,
        input_json: input.to_string(),
    }))
}
```

- [ ] **Step 5: Export parser module**

Modify `src/agent/mod.rs` so it contains:

```rust
pub mod r#loop;
pub mod state;
pub mod tool_call;
pub mod turn;
```

- [ ] **Step 6: Run parser tests and confirm pass**

Run:

```bash
~/.cargo/bin/cargo test --test test_tool_call_parser
```

Expected: all parser tests pass.

- [ ] **Step 7: Commit parser task**

Run:

```bash
git add Cargo.toml src/agent/mod.rs src/agent/tool_call.rs tests/agent/test_tool_call_parser.rs
git commit -m "feat: parse text tool call blocks"
```

---

### Task 2: Implement Read, Glob, and Grep Tools

**Files:**
- Modify: `src/tools/builtin/read.rs`
- Modify: `src/tools/builtin/glob.rs`
- Modify: `src/tools/builtin/grep.rs`
- Modify: `src/tools/registry.rs`
- Modify: `tests/tools/test_read_only_tools.rs`

- [ ] **Step 1: Replace read-only tool tests with failing coverage**

Replace `tests/tools/test_read_only_tools.rs` with:

```rust
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
```

- [ ] **Step 2: Run read-only tool tests and confirm failure**

Run:

```bash
~/.cargo/bin/cargo test --test test_read_only_tools
```

Expected: read/glob/grep tests fail because the tools are stubs or registry ignores JSON input.

- [ ] **Step 3: Implement `read` tool**

Replace `src/tools/builtin/read.rs` with:

```rust
use std::fs;
use std::path::Path;

pub fn run(file_path: &str) -> Result<String, String> {
    let path = Path::new(file_path);
    if !path.is_file() {
        return Err(format!("not a file: {file_path}"));
    }

    fs::read_to_string(path).map_err(|err| format!("failed to read {file_path}: {err}"))
}
```

- [ ] **Step 4: Implement `glob` tool**

Replace `src/tools/builtin/glob.rs` with:

```rust
use std::fs;
use std::path::{Path, PathBuf};

pub fn run(pattern: &str, _root: Option<&str>) -> Result<String, String> {
    let mut matches = Vec::new();
    collect_matches(pattern, &mut matches)?;
    matches.sort();
    Ok(matches.join("\n"))
}

fn collect_matches(pattern: &str, matches: &mut Vec<String>) -> Result<(), String> {
    if let Some(prefix) = pattern.strip_suffix("/**/*.rs") {
        collect_by_extension(Path::new(prefix), "rs", matches)?;
        return Ok(());
    }

    if let Some(prefix) = pattern.strip_suffix("/*.rs") {
        collect_direct_by_extension(Path::new(prefix), "rs", matches)?;
        return Ok(());
    }

    if let Some((dir, suffix)) = pattern.rsplit_once("/*") {
        collect_direct_by_suffix(Path::new(dir), suffix, matches)?;
        return Ok(());
    }

    let path = Path::new(pattern);
    if path.exists() {
        matches.push(path.display().to_string());
    }
    Ok(())
}

fn collect_by_extension(dir: &Path, extension: &str, matches: &mut Vec<String>) -> Result<(), String> {
    if !dir.exists() {
        return Ok(());
    }

    for entry in fs::read_dir(dir).map_err(|err| format!("failed to read dir {}: {err}", dir.display()))? {
        let entry = entry.map_err(|err| err.to_string())?;
        let path = entry.path();
        if path.is_dir() {
            collect_by_extension(&path, extension, matches)?;
        } else if has_extension(&path, extension) {
            matches.push(path.display().to_string());
        }
    }
    Ok(())
}

fn collect_direct_by_extension(dir: &Path, extension: &str, matches: &mut Vec<String>) -> Result<(), String> {
    if !dir.exists() {
        return Ok(());
    }

    for entry in fs::read_dir(dir).map_err(|err| format!("failed to read dir {}: {err}", dir.display()))? {
        let entry = entry.map_err(|err| err.to_string())?;
        let path = entry.path();
        if path.is_file() && has_extension(&path, extension) {
            matches.push(path.display().to_string());
        }
    }
    Ok(())
}

fn collect_direct_by_suffix(dir: &Path, suffix: &str, matches: &mut Vec<String>) -> Result<(), String> {
    if !dir.exists() {
        return Ok(());
    }

    for entry in fs::read_dir(dir).map_err(|err| format!("failed to read dir {}: {err}", dir.display()))? {
        let entry = entry.map_err(|err| err.to_string())?;
        let path = entry.path();
        if path.is_file() && path.to_string_lossy().ends_with(suffix) {
            matches.push(path.display().to_string());
        }
    }
    Ok(())
}

fn has_extension(path: &PathBuf, extension: &str) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value == extension)
}
```

- [ ] **Step 5: Implement `grep` tool**

Replace `src/tools/builtin/grep.rs` with:

```rust
use std::fs;
use std::path::{Path, PathBuf};

pub fn run(pattern: &str, path: Option<&str>) -> Result<String, String> {
    let root = path.unwrap_or(".");
    let mut files = Vec::new();
    collect_files(Path::new(root), &mut files)?;
    files.sort();

    let mut lines = Vec::new();
    for file in files {
        let Ok(contents) = fs::read_to_string(&file) else {
            continue;
        };
        for (idx, line) in contents.lines().enumerate() {
            if line.contains(pattern) {
                lines.push(format!("{}:{}:{}", file.display(), idx + 1, line));
            }
        }
    }

    Ok(lines.join("\n"))
}

fn collect_files(path: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    if path.is_file() {
        files.push(path.to_path_buf());
        return Ok(());
    }

    if !path.exists() {
        return Err(format!("path does not exist: {}", path.display()));
    }

    for entry in fs::read_dir(path).map_err(|err| format!("failed to read dir {}: {err}", path.display()))? {
        let entry = entry.map_err(|err| err.to_string())?;
        let child = entry.path();
        if child.is_dir() {
            collect_files(&child, files)?;
        } else if child.is_file() {
            files.push(child);
        }
    }
    Ok(())
}
```

- [ ] **Step 6: Wire JSON inputs in ToolRegistry**

Modify `src/tools/registry.rs` so `execute` handles read/glob/grep like this:

```rust
            "glob" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let pattern = value
                    .get("pattern")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing pattern".to_string())?;
                let root = value.get("root").and_then(|v| v.as_str());
                glob::run(pattern, root)
            }
            "grep" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let pattern = value
                    .get("pattern")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing pattern".to_string())?;
                let path = value.get("path").and_then(|v| v.as_str());
                grep::run(pattern, path)
            }
            "read" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let file_path = value
                    .get("file_path")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing file_path".to_string())?;
                read::run(file_path)
            }
```

The beginning of the match should now be:

```rust
        match name {
            "pwd" => Ok(pwd::run()),
            "glob" => { /* block above */ }
            "grep" => { /* block above */ }
            "read" => { /* block above */ }
```

- [ ] **Step 7: Run read-only tool tests and confirm pass**

Run:

```bash
~/.cargo/bin/cargo test --test test_read_only_tools
```

Expected: all read-only tool tests pass.

- [ ] **Step 8: Commit tool implementation task**

Run:

```bash
git add src/tools/builtin/read.rs src/tools/builtin/glob.rs src/tools/builtin/grep.rs src/tools/registry.rs tests/tools/test_read_only_tools.rs
git commit -m "feat: implement read glob grep tools"
```

---

### Task 3: Tighten Edit Tool Semantics

**Files:**
- Modify: `src/tools/builtin/edit.rs`
- Modify: `tests/tools/test_write_edit_shell.rs`

- [ ] **Step 1: Add failing edit tests**

Append these tests to `tests/tools/test_write_edit_shell.rs`:

```rust
use std::fs;

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
```

If `tests/tools/test_write_edit_shell.rs` already imports `std::fs`, do not duplicate that import; merge imports manually.

- [ ] **Step 2: Run write/edit/shell tests and confirm failure**

Run:

```bash
~/.cargo/bin/cargo test --test test_write_edit_shell
```

Expected: multiple-match test fails because current edit replaces all matches.

- [ ] **Step 3: Implement exact-once edit behavior**

Replace `src/tools/builtin/edit.rs` with:

```rust
use std::fs;

pub fn run(file_path: &str, old_string: &str, new_string: &str) -> Result<String, String> {
    let contents = fs::read_to_string(file_path)
        .map_err(|err| format!("failed to read {file_path}: {err}"))?;

    let matches = contents.matches(old_string).count();
    if matches == 0 {
        return Err(format!("old_string not found in {file_path}"));
    }
    if matches > 1 {
        return Err(format!("old_string matched {matches} times in {file_path}"));
    }

    let updated = contents.replacen(old_string, new_string, 1);
    fs::write(file_path, updated).map_err(|err| format!("failed to write {file_path}: {err}"))?;
    Ok("edited".to_string())
}
```

- [ ] **Step 4: Run write/edit/shell tests and confirm pass**

Run:

```bash
~/.cargo/bin/cargo test --test test_write_edit_shell
```

Expected: all write/edit/shell tests pass.

- [ ] **Step 5: Commit edit semantics task**

Run:

```bash
git add src/tools/builtin/edit.rs tests/tools/test_write_edit_shell.rs
git commit -m "fix: require exact edit match"
```

---

### Task 4: Upgrade Agent Loop to Execute Tools

**Files:**
- Modify: `src/agent/loop.rs`
- Modify: `tests/agent/test_agent_loop.rs`

- [ ] **Step 1: Replace agent loop tests with scripted runtime coverage**

Replace `tests/agent/test_agent_loop.rs` with:

```rust
use candle_cli::agent::r#loop::run_single_turn;
use candle_cli::model::runtime::CandleTargetRuntime;
use candle_cli::model::types::{RuntimeCapabilities, RuntimeHealth, TurnRequest, TurnResult};
use candle_cli::session::model::{ContentBlock, Message, MessageRole, Session};
use candle_cli::tools::registry::ToolRegistry;
use std::fs;

struct ScriptedRuntime {
    responses: Vec<String>,
    requests: Vec<TurnRequest>,
}

impl ScriptedRuntime {
    fn new(responses: Vec<&str>) -> Self {
        Self {
            responses: responses.into_iter().map(str::to_string).rev().collect(),
            requests: Vec::new(),
        }
    }
}

impl CandleTargetRuntime for ScriptedRuntime {
    fn generate_turn(&mut self, request: TurnRequest) -> Result<TurnResult, String> {
        self.requests.push(request);
        let final_text = self
            .responses
            .pop()
            .ok_or_else(|| "script exhausted".to_string())?;
        Ok(TurnResult {
            final_text,
            tool_calls: Vec::new(),
        })
    }

    fn healthcheck(&mut self) -> Result<RuntimeHealth, String> {
        Ok(RuntimeHealth {
            ok: true,
            message: "ok".to_string(),
        })
    }

    fn capabilities(&self) -> RuntimeCapabilities {
        RuntimeCapabilities {
            supports_tools: true,
            supports_streaming: false,
        }
    }
}

#[test]
fn agent_loop_runs_read_edit_shell_then_final_answer() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "old text\n").unwrap();

    let read_call = format!(
        r#"<tool_call>{{"id":"call-read","name":"read","input":{{"file_path":"{}"}}}}</tool_call>"#,
        file_path.display()
    );
    let edit_call = format!(
        r#"<tool_call>{{"id":"call-edit","name":"edit","input":{{"file_path":"{}","old_string":"old text","new_string":"new text"}}}}</tool_call>"#,
        file_path.display()
    );
    let shell_call = r#"<tool_call>{"id":"call-shell","name":"shell","input":{"command":"printf checked"}}</tool_call>"#;

    let mut runtime = ScriptedRuntime::new(vec![&read_call, &edit_call, shell_call, "done"]);
    let tools = ToolRegistry::default_workspace_write();
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "update the file and check it".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools).unwrap();

    assert_eq!(result.final_text, "done");
    assert_eq!(fs::read_to_string(&file_path).unwrap(), "new text\n");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { output, is_error: false, .. } if output.contains("checked")
        ))
    }));
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolCall { name, .. } if name == "read"
        ))
    }));
}

#[test]
fn agent_loop_records_tool_errors_and_allows_recovery() {
    let missing_read = r#"<tool_call>{"id":"call-read","name":"read","input":{"file_path":"/definitely/missing/file.txt"}}</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![missing_read, "I could not read that file."]);
    let tools = ToolRegistry::default_workspace_write();
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "read missing file".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools).unwrap();

    assert_eq!(result.final_text, "I could not read that file.");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { is_error: true, output, .. } if output.contains("not a file")
        ))
    }));
}

#[test]
fn agent_loop_stops_after_max_steps() {
    let repeated = r#"<tool_call>{"id":"call-pwd","name":"pwd","input":{}}</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![
        repeated, repeated, repeated, repeated, repeated, repeated, repeated, repeated,
    ]);
    let tools = ToolRegistry::default_workspace_write();
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "loop forever".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools).unwrap();

    assert!(result.final_text.contains("maximum tool steps"));
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::Text { text } if text.contains("maximum tool steps")
        ))
    }));
}
```

- [ ] **Step 2: Run agent loop tests and confirm failure**

Run:

```bash
~/.cargo/bin/cargo test --test test_agent_loop
```

Expected: tests fail because `run_single_turn` does not parse or execute tools.

- [ ] **Step 3: Implement bounded tool loop**

Replace `src/agent/loop.rs` with:

```rust
use crate::agent::tool_call::{parse_tool_call, ToolCallParseError};
use crate::agent::turn::finish_turn;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{ToolCallIntent, TurnResult};
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;

const DEFAULT_MAX_TOOL_STEPS: usize = 8;

pub fn run_single_turn<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
) -> Result<TurnResult, String> {
    run_single_turn_with_limit(session, runtime, tools, DEFAULT_MAX_TOOL_STEPS)
}

pub fn run_single_turn_with_limit<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    max_steps: usize,
) -> Result<TurnResult, String> {
    for _ in 0..max_steps {
        let request = crate::context::builder::build_turn_request(session, tools_json())?;
        let result = runtime.generate_turn(request)?;

        match parse_tool_call(&result.final_text) {
            Ok(Some(tool_call)) => {
                append_tool_call(session, &tool_call);
                let (output, is_error) = match tools.execute(&tool_call.name, &tool_call.input_json) {
                    Ok(output) => (output, false),
                    Err(err) => (err, true),
                };
                append_tool_result(session, &tool_call.id, output, is_error);
            }
            Ok(None) => {
                let final_text = finish_turn(result.final_text.clone());
                append_assistant_text(session, final_text.clone());
                return Ok(TurnResult {
                    final_text,
                    tool_calls: Vec::new(),
                });
            }
            Err(err) => {
                let correction = malformed_tool_call_message(&err);
                append_assistant_text(session, correction);
            }
        }
    }

    let final_text = format!("stopped after reaching maximum tool steps ({max_steps})");
    append_assistant_text(session, final_text.clone());
    Ok(TurnResult {
        final_text,
        tool_calls: Vec::new(),
    })
}

fn append_tool_call(session: &mut Session, tool_call: &ToolCallIntent) {
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::ToolCall {
            id: tool_call.id.clone(),
            name: tool_call.name.clone(),
            input: tool_call.input_json.clone(),
        }],
    });
}

fn append_tool_result(session: &mut Session, tool_call_id: &str, output: String, is_error: bool) {
    session.messages.push(Message {
        role: MessageRole::Tool,
        blocks: vec![ContentBlock::ToolResult {
            tool_call_id: tool_call_id.to_string(),
            output,
            is_error,
        }],
    });
}

fn append_assistant_text(session: &mut Session, text: String) {
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::Text { text }],
    });
}

fn malformed_tool_call_message(err: &ToolCallParseError) -> String {
    format!(
        "The previous tool call was malformed: {err}. Retry with exactly one <tool_call>{{...}}</tool_call> block or provide a final answer."
    )
}

fn tools_json() -> &'static str {
    r#"[
  {"name":"pwd","description":"Return the current working directory","input_schema":{"type":"object","properties":{}}},
  {"name":"read","description":"Read a UTF-8 file","input_schema":{"type":"object","properties":{"file_path":{"type":"string"}},"required":["file_path"]}},
  {"name":"glob","description":"Find files matching a simple glob pattern","input_schema":{"type":"object","properties":{"pattern":{"type":"string"}},"required":["pattern"]}},
  {"name":"grep","description":"Search files for a substring","input_schema":{"type":"object","properties":{"pattern":{"type":"string"},"path":{"type":"string"}},"required":["pattern"]}},
  {"name":"edit","description":"Replace exactly one string occurrence in an existing file","input_schema":{"type":"object","properties":{"file_path":{"type":"string"},"old_string":{"type":"string"},"new_string":{"type":"string"}},"required":["file_path","old_string","new_string"]}},
  {"name":"shell","description":"Run a shell command and return its output","input_schema":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}
]"#
}
```

- [ ] **Step 4: Run agent loop tests and confirm pass**

Run:

```bash
~/.cargo/bin/cargo test --test test_agent_loop
```

Expected: all agent loop tests pass.

- [ ] **Step 5: Commit loop task**

Run:

```bash
git add src/agent/loop.rs tests/agent/test_agent_loop.rs
git commit -m "feat: execute tool calls in agent loop"
```

---

### Task 5: Add Tool Prompt Guidance and Workspace-Write Integration

**Files:**
- Modify: `src/context/builder.rs`
- Modify: `src/cli/repl.rs`
- Modify: `tests/agent/test_context_builder.rs`
- Modify: `tests/cli/test_repl_session_integration.rs`

- [ ] **Step 1: Add failing context builder test for tool guidance**

Replace `tests/agent/test_context_builder.rs` with:

```rust
use candle_cli::context::builder::build_turn_request;
use candle_cli::session::model::{ContentBlock, Message, MessageRole, Session};

#[test]
fn build_turn_request_includes_messages() {
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "hello".to_string(),
        }],
    });

    let request = build_turn_request(&session, "[]").unwrap();

    assert!(request.system_prompt.contains("You are candle-cli"));
    assert!(request.messages_json.contains("hello"));
}

#[test]
fn build_turn_request_adds_tool_call_protocol_guidance_when_tools_are_available() {
    let session = Session::new(".".to_string());
    let request = build_turn_request(&session, "[{\"name\":\"read\"}]").unwrap();

    assert!(request.system_prompt.contains("<tool_call>"));
    assert!(request.system_prompt.contains("exactly one"));
    assert!(request.system_prompt.contains("read"));
}
```

- [ ] **Step 2: Run context builder test and confirm failure**

Run:

```bash
~/.cargo/bin/cargo test --test test_context_builder
```

Expected: second test fails because prompt guidance is not included yet.

- [ ] **Step 3: Add tool guidance to context builder**

Modify `src/context/builder.rs`. Ensure it contains these functions:

```rust
pub fn build_turn_request(session: &Session, tools_json: &str) -> Result<TurnRequest, String> {
    let compacted = compact_session(session, resolve_max_turns());
    let messages_json = serde_json::to_string(&compacted.messages).map_err(|e| e.to_string())?;
    Ok(TurnRequest {
        system_prompt: resolve_system_prompt_with_tools(tools_json),
        messages_json,
        tools_json: tools_json.to_string(),
    })
}

pub fn resolve_system_prompt() -> String {
    std::env::var("CANDLE_CLI_SYSTEM_PROMPT").unwrap_or_else(|_| {
        "You are candle-cli, a local terminal AI assistant. Be concise and helpful.".to_string()
    })
}

fn resolve_system_prompt_with_tools(tools_json: &str) -> String {
    let base = resolve_system_prompt();
    if tools_json.trim().is_empty() || tools_json.trim() == "[]" {
        return base;
    }

    format!(
        "{base}\n\nTool protocol:\n- Use tools when you need to inspect files, edit files, or run commands.\n- To call a tool, output exactly one <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call> block.\n- Do not mix final answer text with a tool call.\n- After receiving tool results, either request another tool or provide the final answer.\n- Available tools JSON: {tools_json}"
    )
}
```

Keep existing imports and `resolve_max_turns` behavior intact. If the current file has additional tests or helpers, preserve them.

- [ ] **Step 4: Switch prompt and REPL tools to workspace-write**

Modify `src/cli/repl.rs`:

Change this in `run_repl`:

```rust
    let tools = ToolRegistry::default_read_only();
```

to:

```rust
    let tools = ToolRegistry::default_workspace_write();
```

Change the same line in `run_prompt` from read-only to workspace-write.

- [ ] **Step 5: Run context and REPL tests**

Run:

```bash
~/.cargo/bin/cargo test --test test_context_builder
~/.cargo/bin/cargo test --test test_repl_session_integration
```

Expected: both test targets pass.

- [ ] **Step 6: Commit prompt/integration task**

Run:

```bash
git add src/context/builder.rs src/cli/repl.rs tests/agent/test_context_builder.rs tests/cli/test_repl_session_integration.rs
git commit -m "feat: enable tool guidance in cli modes"
```

---

### Task 6: Document Minimal Agentic Loop

**Files:**
- Modify: `README.md`
- Add/Stage: `docs/superpowers/specs/2026-05-09-minimal-agentic-loop-design.md`
- Create: `docs/superpowers/plans/2026-05-09-minimal-agentic-loop.md`

- [ ] **Step 1: Add README section for the tool loop**

Edit `README.md` and insert this section before `## 开发`:

```markdown
## 最小 Agent 闭环（v0.3.0）

`candle-cli` 支持一个文本 JSON 工具调用协议。模型需要读取文件、搜索代码、编辑文件或运行命令时，可以输出：

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Rust 侧会解析该工具调用，执行工具，把结果写回 session，然后继续调用模型，直到模型输出最终回答。

首批闭环工具：

- `pwd`：返回当前工作目录。
- `read`：读取 UTF-8 文件。
- `glob`：按简单 glob pattern 查找文件。
- `grep`：搜索文件内容。
- `edit`：替换已有文件中的唯一匹配文本。
- `shell`：运行 shell 命令并返回输出。

示例任务：

```bash
CANDLE_CLI_RUNTIME=bridge cargo run -- prompt "读取 README.md，总结如何运行项目"
```

当前版本先固定使用 workspace-write 工具集合。交互式权限确认、sandbox、streaming 和原生 OpenAI tools schema 会在后续版本加入。
```

- [ ] **Step 2: Run README grep check**

Run:

```bash
grep -n "最小 Agent 闭环" README.md
grep -n "<tool_call>" README.md
```

Expected: both commands print matching lines.

- [ ] **Step 3: Stage spec and plan docs**

Run:

```bash
git add README.md docs/superpowers/specs/2026-05-09-minimal-agentic-loop-design.md docs/superpowers/plans/2026-05-09-minimal-agentic-loop.md
```

- [ ] **Step 4: Commit docs task**

Run:

```bash
git commit -m "docs: describe minimal agentic loop"
```

---

### Task 7: Full Verification and Push

**Files:**
- Verification only.

- [ ] **Step 1: Run Python bridge tests**

Run:

```bash
python3 -m pytest python/test_bridge_runtime.py -q
```

Expected: `27 passed` or all Python bridge tests pass with zero failures.

- [ ] **Step 2: Run Rust tests**

Run:

```bash
~/.cargo/bin/cargo test
```

Expected: all Rust tests pass with zero failures.

- [ ] **Step 3: Run format check**

Run:

```bash
~/.cargo/bin/cargo fmt --check
```

Expected: exit 0 with no diff output.

- [ ] **Step 4: Run clippy**

Run:

```bash
~/.cargo/bin/cargo clippy --all-targets --all-features -- -D warnings
```

Expected: exit 0 with no warnings.

- [ ] **Step 5: Confirm worktree state**

Run:

```bash
git -C "/home/mseco/candle-cli-target/.worktrees/phase1-bootstrap" status --short
```

Expected: no uncommitted files in the worktree used for pushing. If implementation happened in `/home/mseco/candle-cli`, either push from that checkout only with explicit approval or transfer commits into `/home/mseco/candle-cli-target/.worktrees/phase1-bootstrap` before pushing.

- [ ] **Step 6: Push from the approved worktree**

Run from `/home/mseco/candle-cli-target/.worktrees/phase1-bootstrap` after the commits are present there:

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap
TOKEN=$(cat /tmp/candle_cli_push_token)
git push "https://x-access-token:${TOKEN}@github.com/DuangZ-GR/candle-cli.git" feature/phase1-bootstrap:main
```

Expected: remote `main` advances. If the push fails with `Failed to connect to github.com port 443` or `GnuTLS recv error`, treat it as a likely transient network/TLS issue and retry after confirming local verification still passed.

---

## Plan Self-Review

- Spec coverage: parser, real tools, multi-step loop, workspace-write integration, session persistence, prompt guidance, tests, docs, verification, and push are covered.
- Placeholder scan: no TODO/TBD placeholders remain; all code steps include concrete code.
- Type consistency: all new tests and code use existing `TurnResult`, `ToolCallIntent`, `Message`, `ContentBlock`, `ToolRegistry`, and `CandleTargetRuntime` names.
- Scope check: OpenAI native tools, streaming, prompt permissions, sandboxing, write tool, candle runtime, long-lived worker, and CI are explicitly deferred.
