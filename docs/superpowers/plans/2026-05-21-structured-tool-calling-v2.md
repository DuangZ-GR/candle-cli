# Structured Tool Calling v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing candle-cli tool-calling loop more reliable, more standardized, and more inspectable without expanding scope or adding new tools.

**Architecture:** Keep current `<tool_call>{...}</tool_call>` protocol with `tool({...})` fallback, keep text-based tool result envelopes, and keep the bounded multi-step agent loop. Improvements happen at three boundaries: parser correctness, structured tool result contract, and verbose execution trace.

**Tech Stack:** Rust 2021, serde_json, std::process for shell, existing assert_cmd/tempfile test helpers.

---

## File Structure Map

- `src/agent/tool_call.rs` — owns canonical and fallback parser behavior.
- `src/agent/loop.rs` — owns parser/permission/execution flow and verbose trace.
- `src/tools/builtin/shell.rs` — owns shell result envelope.
- `src/tools/registry.rs` — keeps existing tool dispatch.
- `tests/agent/test_tool_call_parser.rs` — parser contract coverage.
- `tests/agent/test_agent_loop.rs` — agent loop recovery and structured result coverage.
- `tests/tools/test_write_edit_shell.rs` — shell envelope coverage.
- `docs/superpowers/specs/2026-05-21-structured-tool-calling-v2-design.md` — design doc, already exists.
- `docs/superpowers/plans/2026-05-21-structured-tool-calling-v2.md` — this plan.

---

### Task 1: Lock parser precedence between canonical and fallback formats

**Files:**
- Modify: `tests/agent/test_tool_call_parser.rs`

- [ ] **Step 1: Add a parser precedence test that pins canonical-over-fallback behavior**

Open `tests/agent/test_tool_call_parser.rs` and append this test:

```rust
#[test]
fn canonical_tool_call_takes_precedence_over_fallback() {
    let mixed = r#"read({"file_path":"unused"})
<tool_call>{"id":"call-1","name":"glob","input":{"pattern":"src/*.rs"}}</tool_call>"#;

    let parsed = parse_tool_call(mixed)
        .expect("mixed output should parse without error")
        .expect("canonical tool call should be selected");

    assert_eq!(parsed.id, "call-1");
    assert_eq!(parsed.name, "glob");
    assert_eq!(parsed.input_json, "{\"pattern\":\"src/*.rs\"}");
}
```

- [ ] **Step 2: Run the parser tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_tool_call_parser
```

Expected: every test in `test_tool_call_parser` passes, including the new precedence test.

- [ ] **Step 3: Commit**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git add tests/agent/test_tool_call_parser.rs && git commit -m "test: lock canonical tool call precedence over fallback"
```

---

### Task 2: Strengthen malformed tool-call recovery message

**Files:**
- Modify: `src/agent/loop.rs`
- Modify: `tests/agent/test_agent_loop.rs`

- [ ] **Step 1: Add a failing recovery test**

Append this test at the end of `tests/agent/test_agent_loop.rs`:

```rust
#[test]
fn agent_loop_appends_explicit_correction_message_for_malformed_tool_call() {
    let malformed = r#"<tool_call>{"id":"call-1"</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![malformed, "ok, I will stop."]);
    let tools = ToolRegistry::workspace_write(".");
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "do something".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();

    assert_eq!(result.final_text, "ok, I will stop.");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::Text { text }
                if text.contains("The previous tool call was malformed")
                    && text.contains("<tool_call>")
                    && text.contains("retry with one valid tool call or provide a final answer")
        ))
    }));
}
```

- [ ] **Step 2: Run the failing test**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_agent_loop agent_loop_appends_explicit_correction_message_for_malformed_tool_call
```

Expected: this test fails because the current correction message uses different wording.

- [ ] **Step 3: Update the correction message**

Open `src/agent/loop.rs` and replace the body of `malformed_tool_call_message` with this exact code:

```rust
fn malformed_tool_call_message(err: &ToolCallParseError) -> String {
    format!(
        "The previous tool call was malformed: {err}. Expected exactly one raw tool call block like <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call>. retry with one valid tool call or provide a final answer."
    )
}
```

- [ ] **Step 4: Run the test again**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_agent_loop agent_loop_appends_explicit_correction_message_for_malformed_tool_call
```

Expected: this test now passes.

- [ ] **Step 5: Run all agent loop tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_agent_loop
```

Expected: all loop tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git add src/agent/loop.rs tests/agent/test_agent_loop.rs && git commit -m "feat: clearer correction message for malformed tool calls"
```

---

### Task 3: Pin non-shell tool result contract

**Files:**
- Modify: `tests/tools/test_read_only_tools.rs`

- [ ] **Step 1: Inspect the current expected output of read-only tools**

Open `tests/tools/test_read_only_tools.rs`. Confirm the `read` test currently asserts the literal file contents.

- [ ] **Step 2: Replace the read success assertion with envelope assertion**

Find the existing test that calls `registry.execute("read", ...)` and asserts file contents directly. Replace its assertion block with:

```rust
    let out = registry.execute("read", &input).unwrap();
    assert!(out.contains("hello world"));
```

This intentionally relaxes only what is needed; envelope wrapping happens at the agent loop layer, not the registry layer.

- [ ] **Step 3: Add a registry envelope contract test that pins agent-layer wrapping behavior**

Append this test at the end of `tests/agent/test_agent_loop.rs`:

```rust
#[test]
fn agent_loop_wraps_non_shell_tool_success_with_envelope() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    std::fs::write(&file_path, "hello loop\n").unwrap();

    let read_call = format!(
        r#"<tool_call>{{"id":"call-1","name":"read","input":{{"file_path":"{}"}}}}</tool_call>"#,
        file_path.display()
    );
    let mut runtime = ScriptedRuntime::new(vec![&read_call, "done"]);
    let tools = ToolRegistry::workspace_write(dir.path());
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "read the file".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();

    assert_eq!(result.final_text, "done");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { is_error: false, output, .. }
                if output.starts_with("status: ok\ntool: read\noutput:\n")
                    && output.contains("hello loop")
        ))
    }));
}
```

- [ ] **Step 4: Run both affected test targets**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_read_only_tools && ~/.cargo/bin/cargo test --test test_agent_loop
```

Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git add tests/agent/test_agent_loop.rs tests/tools/test_read_only_tools.rs && git commit -m "test: pin non-shell tool result envelope contract"
```

---

### Task 4: Pin shell result and timeout envelopes

**Files:**
- Modify: `tests/tools/test_write_edit_shell.rs`

- [ ] **Step 1: Verify shell success envelope is already covered**

Open `tests/tools/test_write_edit_shell.rs`. Confirm `shell_tool_executes_command_inside_workspace_root` already asserts `status: ok`, `tool: shell`, and `exit_code: 0`.

- [ ] **Step 2: Add a shell non-zero exit code test**

Append this test to `tests/tools/test_write_edit_shell.rs`:

```rust
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
```

- [ ] **Step 3: Run shell-related tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_write_edit_shell
```

Expected: every shell test passes, including the new non-zero exit case.

- [ ] **Step 4: Commit**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git add tests/tools/test_write_edit_shell.rs && git commit -m "test: pin shell error envelope for non-zero exit"
```

---

### Task 5: Lock verbose trace lines and stderr-only behavior

**Files:**
- Modify: `tests/agent/test_agent_loop.rs`

- [ ] **Step 1: Add a verbose trace integration test**

Append this test to `tests/agent/test_agent_loop.rs`:

```rust
#[test]
fn agent_loop_emits_verbose_trace_lines_to_stderr_only() {
    let _guard = PERMISSION_RESPONSE_LOCK.lock().unwrap();
    std::env::set_var("CANDLE_CLI_VERBOSE", "1");

    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    std::fs::write(&file_path, "hi\n").unwrap();

    let read_call = format!(
        r#"<tool_call>{{"id":"call-1","name":"read","input":{{"file_path":"{}"}}}}</tool_call>"#,
        file_path.display()
    );
    let mut runtime = ScriptedRuntime::new(vec![&read_call, "done"]);
    let tools = ToolRegistry::workspace_write(dir.path());
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "read the file".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();
    std::env::remove_var("CANDLE_CLI_VERBOSE");

    assert_eq!(result.final_text, "done");
    let session_dump = serde_json::to_string(&session.messages).unwrap();
    assert!(!session_dump.contains("[tool step"));
    assert!(!session_dump.contains("[tool result]"));
    assert!(!session_dump.contains("[tool parse error]"));
}
```

This test guarantees verbose traces never leak into session messages.

- [ ] **Step 2: Run the new test**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_agent_loop agent_loop_emits_verbose_trace_lines_to_stderr_only
```

Expected: passes immediately because the current implementation already prints to stderr only.

- [ ] **Step 3: Commit**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git add tests/agent/test_agent_loop.rs && git commit -m "test: verbose trace stays in stderr only"
```

---

### Task 6: Final verification and push

**Files:**
- No source changes; verification only.

- [ ] **Step 1: Run Python bridge tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && python3 -m pytest python/test_bridge_runtime.py -q
```

Expected: every test passes.

- [ ] **Step 2: Run the full Rust test suite**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test
```

Expected: every Rust test passes.

- [ ] **Step 3: Run format check**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo fmt -- --check
```

Expected: zero diff.

- [ ] **Step 4: Run clippy**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo clippy --all-targets --all-features -- -D warnings
```

Expected: no warnings.

- [ ] **Step 5: Confirm worktree state**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git status --short --branch
```

Expected: clean working tree on `feature/phase1-bootstrap`.

- [ ] **Step 6: Push branch to remote main**

```bash
TOKEN=$(cat /tmp/candle_cli_push_token) && git -C /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap push "https://x-access-token:${TOKEN}@github.com/DuangZ-GR/candle-cli.git" feature/phase1-bootstrap:main
```

Expected: remote `main` advances by exactly the commits created in tasks 1 through 5. If push fails with `Failed to connect to github.com port 443` or `GnuTLS recv error`, treat it as a transient network issue and retry the same command.

---

## Self-Review

- Spec coverage: protocol precedence covered in Task 1; correction message covered in Task 2; non-shell envelope covered in Task 3; shell envelope covered in Task 4; verbose trace observability covered in Task 5; verification and push covered in Task 6.
- Placeholder scan: no TODO, no “similar to task N”, no vague error handling instructions.
- Type consistency: all tests use existing types `ToolRegistry`, `PermissionPolicy`, `PermissionMode`, `ScriptedRuntime`, `Session`, `Message`, `MessageRole`, `ContentBlock` already present in the test files. `malformed_tool_call_message` keeps its existing signature `fn(&ToolCallParseError) -> String`.
- File scope: all touched paths exist in the current worktree.

Plan complete and saved to `docs/superpowers/plans/2026-05-21-structured-tool-calling-v2.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — run tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
