# Runtime Introspection Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/tools`, `/status`, and `/trace` REPL commands so users can inspect registered tools, current runtime/session state, and the last execution trace after a turn completes.

**Architecture:** Introduce a lightweight in-memory `ExecutionTrace` in the agent layer, pass it through the bounded loop during REPL turns, and expose it through new slash commands. Keep the feature REPL-only, keep trace state out of sessions, and reuse existing CLI/session/runtime information instead of building a new logging system.

**Tech Stack:** Rust 2021, current REPL command handling, existing `assert_cmd` integration tests, `serde_json` for session assertions, standard library only.

---

## File Structure Map

- `src/agent/trace.rs` — new trace event and trace container definitions plus rendering helpers.
- `src/agent/mod.rs` — export the new `trace` module.
- `src/agent/loop.rs` — append trace events during build/request/parse/tool/result/final-answer flow.
- `src/tools/registry.rs` — expose registered tool names for `/tools`.
- `src/cli/repl.rs` — store the latest trace, add `/tools`, `/status`, `/trace`, and render outputs.
- `tests/cli/test_repl_session_integration.rs` — integration tests for `/tools`, `/status`, `/trace`, and `/trace` empty state.
- `docs/superpowers/specs/2026-05-21-runtime-introspection-commands-design.md` — design doc already written.
- `docs/superpowers/plans/2026-05-21-runtime-introspection-commands.md` — this plan.

---

### Task 1: Add trace types and rendering helpers

**Files:**
- Create: `src/agent/trace.rs`
- Modify: `src/agent/mod.rs`
- Test: `tests/cli/test_repl_session_integration.rs`

- [ ] **Step 1: Create the trace module**

Create `src/agent/trace.rs` with:

```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TraceEvent {
    BuildTurnRequest,
    RuntimeGenerateTurn,
    ParseToolCall,
    ToolCall { name: String },
    ToolResult { tool: String, status: String },
    FinalAnswer,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ExecutionTrace {
    steps: Vec<TraceEvent>,
}

impl ExecutionTrace {
    pub fn new() -> Self {
        Self { steps: Vec::new() }
    }

    pub fn push(&mut self, event: TraceEvent) {
        self.steps.push(event);
    }

    pub fn is_empty(&self) -> bool {
        self.steps.is_empty()
    }

    pub fn render_lines(&self) -> Vec<String> {
        let mut lines = vec!["Last trace".to_string()];
        for (idx, step) in self.steps.iter().enumerate() {
            let line = match step {
                TraceEvent::BuildTurnRequest => format!("{}. build_turn_request", idx + 1),
                TraceEvent::RuntimeGenerateTurn => format!("{}. runtime.generate_turn", idx + 1),
                TraceEvent::ParseToolCall => format!("{}. parse_tool_call", idx + 1),
                TraceEvent::ToolCall { name } => format!("{}. tool: {name}", idx + 1),
                TraceEvent::ToolResult { tool: _, status } => {
                    format!("{}. tool result: {status}", idx + 1)
                }
                TraceEvent::FinalAnswer => format!("{}. final answer", idx + 1),
            };
            lines.push(line);
        }
        lines
    }
}
```

- [ ] **Step 2: Export the trace module**

Modify `src/agent/mod.rs` so it contains:

```rust
pub mod r#loop;
pub mod state;
pub mod tool_call;
pub mod trace;
pub mod turn;
```

- [ ] **Step 3: Add a REPL empty-trace integration test**

Append this test to `tests/cli/test_repl_session_integration.rs`:

```rust
#[test]
fn repl_trace_reports_empty_state_before_any_turn() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/trace\n")
        .assert()
        .success()
        .stdout(predicates::str::contains("no trace available"));
}
```

If `predicates::str::contains` is not already imported, add:

```rust
use predicates::str::contains;
```

and change `.stdout(predicates::str::contains(...))` to `.stdout(contains(...))`.

- [ ] **Step 4: Run the new trace test and confirm it fails**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_repl_session_integration repl_trace_reports_empty_state_before_any_turn
```

Expected: failure because `/trace` is not implemented yet.

- [ ] **Step 5: Commit the trace type scaffolding**

Do not commit yet. This task is only scaffolding; commit with Task 2 after the first working `/trace` implementation.

---

### Task 2: Wire execution trace into the agent loop and REPL `/trace`

**Files:**
- Modify: `src/agent/loop.rs`
- Modify: `src/cli/repl.rs`
- Test: `tests/cli/test_repl_session_integration.rs`

- [ ] **Step 1: Extend the agent loop with trace-aware entry points**

In `src/agent/loop.rs`, import trace types:

```rust
use crate::agent::trace::{ExecutionTrace, TraceEvent};
```

Add a new entry point that accepts a mutable trace collector:

```rust
pub fn run_single_turn_with_trace<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    policy: &PermissionPolicy,
    trace: &mut ExecutionTrace,
) -> Result<TurnResult, String> {
    run_single_turn_with_limit_and_trace(session, runtime, tools, policy, DEFAULT_MAX_TOOL_STEPS, trace)
}
```

Then introduce a trace-aware loop function:

```rust
pub fn run_single_turn_with_limit_and_trace<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    policy: &PermissionPolicy,
    max_steps: usize,
    trace: &mut ExecutionTrace,
) -> Result<TurnResult, String> {
    let verbose = verbose_enabled();

    for step in 0..max_steps {
        trace.push(TraceEvent::BuildTurnRequest);
        let request = crate::context::builder::build_turn_request(session, tools_json())?;

        trace.push(TraceEvent::RuntimeGenerateTurn);
        let result = runtime.generate_turn(request)?;

        trace.push(TraceEvent::ParseToolCall);
        match parse_tool_call(&result.final_text) {
            Ok(Some(tool_call)) => {
                trace.push(TraceEvent::ToolCall {
                    name: tool_call.name.clone(),
                });
                trace_tool_step(verbose, step + 1, max_steps, &tool_call);
                append_tool_call(session, &tool_call);
                let (output, is_error) = /* keep existing permission/tool execution logic */;
                let status = if is_error { "error" } else { "ok" };
                trace.push(TraceEvent::ToolResult {
                    tool: tool_call.name.clone(),
                    status: status.to_string(),
                });
                trace_tool_result(verbose, &output, is_error);
                append_tool_result(session, &tool_call.id, output, is_error);
            }
            Ok(None) => {
                let final_text = finish_turn(result.final_text.clone());
                trace.push(TraceEvent::FinalAnswer);
                append_assistant_text(session, final_text.clone());
                return Ok(TurnResult {
                    final_text,
                    tool_calls: Vec::new(),
                });
            }
            Err(err) => {
                trace_parse_error(verbose, &err);
                let correction = malformed_tool_call_message(&err);
                append_assistant_text(session, correction);
            }
        }
    }

    let final_text = format!("stopped after reaching maximum tool steps ({max_steps})");
    trace.push(TraceEvent::FinalAnswer);
    append_assistant_text(session, final_text.clone());
    Ok(TurnResult {
        final_text,
        tool_calls: Vec::new(),
    })
}
```

Finally, make the existing `run_single_turn` allocate a throwaway trace and delegate:

```rust
pub fn run_single_turn<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    policy: &PermissionPolicy,
) -> Result<TurnResult, String> {
    let mut trace = ExecutionTrace::new();
    run_single_turn_with_trace(session, runtime, tools, policy, &mut trace)
}
```

- [ ] **Step 2: Store last trace in REPL state**

In `src/cli/repl.rs`, import the trace type:

```rust
use crate::agent::trace::ExecutionTrace;
```

Inside `run_repl`, after creating `policy`, add:

```rust
    let mut last_trace: Option<ExecutionTrace> = None;
```

Change `handle_slash_command` signature to accept a trace reference:

```rust
fn handle_slash_command(
    input: &str,
    session: &mut Session,
    store: &SessionStore,
    last_trace: &Option<ExecutionTrace>,
) -> bool {
```

Update the call site in `run_repl`:

```rust
            let handled = handle_slash_command(&input, &mut session, &store, &last_trace);
```

When running a non-slash turn in `run_repl`, create a fresh trace before the runtime call:

```rust
        let mut current_trace = ExecutionTrace::new();
```

Then call `run_single_turn_with_trace(...)` instead of `run_single_turn(...)` in both runtime branches:

```rust
run_single_turn_with_trace(&mut session, &mut runtime, &tools, &policy, &mut current_trace)
```

After a successful turn, before `store.save(&session)?;`, add:

```rust
                last_trace = Some(current_trace);
```

- [ ] **Step 3: Implement `/trace` output**

In `handle_slash_command`, add a new branch:

```rust
        "trace" => {
            match last_trace {
                Some(trace) if !trace.is_empty() => {
                    for line in trace.render_lines() {
                        let _ = writeln!(stdout, "{line}");
                    }
                }
                _ => {
                    let _ = writeln!(stdout, "no trace available");
                }
            }
        }
```

Also update the help text at the bottom of `src/cli/repl.rs`:

```rust
  /trace           查看最近一次执行链路
```
```

- [ ] **Step 4: Run the empty-trace test again**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_repl_session_integration repl_trace_reports_empty_state_before_any_turn
```

Expected: passes.

- [ ] **Step 5: Add a filled-trace integration test**

Append this test to `tests/cli/test_repl_session_integration.rs`:

```rust
#[test]
fn repl_trace_reports_last_execution_chain() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.current_dir(".")
        .env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .env("CANDLE_CLI_RUNTIME", "bridge")
        .write_stdin("读取 README.md，总结如何运行项目\n/trace\n")
        .assert()
        .success()
        .stdout(contains("Last trace"))
        .stdout(contains("build_turn_request"))
        .stdout(contains("runtime.generate_turn"));
}
```

- [ ] **Step 6: Run REPL integration tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_repl_session_integration
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git add src/agent/trace.rs src/agent/mod.rs src/agent/loop.rs src/cli/repl.rs tests/cli/test_repl_session_integration.rs && git commit -m "feat: add runtime trace inspection command"
```

---

### Task 3: Add `/tools` using the tool registry

**Files:**
- Modify: `src/tools/registry.rs`
- Modify: `src/cli/repl.rs`
- Test: `tests/cli/test_repl_session_integration.rs`

- [ ] **Step 1: Add a tool registry listing helper**

In `src/tools/registry.rs`, add this method inside `impl ToolRegistry`:

```rust
    pub fn tool_names(&self) -> Vec<&'static str> {
        vec!["pwd", "read", "glob", "grep", "edit", "shell"]
    }
```

Do not include `write` because the current design and README emphasize the exposed interactive tools as `pwd/read/glob/grep/edit/shell`.

- [ ] **Step 2: Add `/tools` branch in REPL**

In `src/cli/repl.rs`, change `handle_slash_command` signature again so it also accepts the registry:

```rust
fn handle_slash_command(
    input: &str,
    session: &mut Session,
    store: &SessionStore,
    last_trace: &Option<ExecutionTrace>,
    tools: &ToolRegistry,
) -> bool {
```

Update the call site in `run_repl` accordingly:

```rust
            let handled = handle_slash_command(&input, &mut session, &store, &last_trace, &tools);
```

Then add this branch:

```rust
        "tools" => {
            let _ = writeln!(stdout, "Registered tools");
            for name in tools.tool_names() {
                let _ = writeln!(stdout, "- {name}");
            }
        }
```

Update help text:

```rust
  /tools           查看当前可用工具列表
```
```

- [ ] **Step 3: Add `/tools` integration test**

Append this test to `tests/cli/test_repl_session_integration.rs`:

```rust
#[test]
fn repl_tools_lists_registered_tools() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .write_stdin("/tools\n")
        .assert()
        .success()
        .stdout(contains("Registered tools"))
        .stdout(contains("- pwd"))
        .stdout(contains("- read"))
        .stdout(contains("- glob"))
        .stdout(contains("- grep"))
        .stdout(contains("- edit"))
        .stdout(contains("- shell"));
}
```

- [ ] **Step 4: Run REPL integration tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_repl_session_integration
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git add src/tools/registry.rs src/cli/repl.rs tests/cli/test_repl_session_integration.rs && git commit -m "feat: add tool registry inspection command"
```

---

### Task 4: Add `/status` runtime/session snapshot

**Files:**
- Modify: `src/cli/repl.rs`
- Test: `tests/cli/test_repl_session_integration.rs`

- [ ] **Step 1: Add a status render helper**

In `src/cli/repl.rs`, add this helper near other helper functions:

```rust
fn render_status_lines(session: &Session, permission: PermissionMode) -> Vec<String> {
    let runtime = std::env::var("CANDLE_CLI_RUNTIME").unwrap_or_else(|_| "mock".to_string());
    let model = std::env::var("CANDLE_CLI_MODEL_ID")
        .unwrap_or_else(|_| "Qwen/Qwen2-0.5B-Instruct".to_string());
    let max_turns = std::env::var("CANDLE_CLI_MAX_TURNS").unwrap_or_else(|_| "20".to_string());

    vec![
        "Session".to_string(),
        format!("- session_id: {}", session.session_id),
        format!("- messages: {}", session.messages.len()),
        format!("- workspace: {}", session.workspace_root),
        format!("- permission: {:?}", permission),
        format!("- runtime: {}", runtime),
        format!("- model: {}", model),
        format!("- max_turns: {}", max_turns),
    ]
}
```

- [ ] **Step 2: Add `/status` branch**

In `handle_slash_command`, add this branch:

```rust
        "status" => {
            let permission = resolve_permission_mode();
            for line in render_status_lines(session, permission) {
                let _ = writeln!(stdout, "{line}");
            }
        }
```

Update help text:

```rust
  /status          查看当前运行状态
```
```

- [ ] **Step 3: Add `/status` integration test**

Append this test to `tests/cli/test_repl_session_integration.rs`:

```rust
#[test]
fn repl_status_reports_runtime_snapshot() {
    let session_dir = tempdir().unwrap();
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.env("CANDLE_CLI_SESSION_DIR", session_dir.path())
        .env("CANDLE_CLI_RUNTIME", "bridge")
        .env("CANDLE_CLI_MODEL_ID", "deepseek-v4-flash")
        .env("CANDLE_CLI_PERMISSION", "read-only")
        .write_stdin("hello\n/status\n")
        .assert()
        .success()
        .stdout(contains("Session"))
        .stdout(contains("session_id:"))
        .stdout(contains("messages:"))
        .stdout(contains("workspace:"))
        .stdout(contains("permission: ReadOnly"))
        .stdout(contains("runtime: bridge"))
        .stdout(contains("model: deepseek-v4-flash"));
}
```

- [ ] **Step 4: Run REPL integration tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test --test test_repl_session_integration
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git add src/cli/repl.rs tests/cli/test_repl_session_integration.rs && git commit -m "feat: add runtime status inspection command"
```

---

### Task 5: Final verification and push

**Files:**
- No code changes required beyond the above tasks.

- [ ] **Step 1: Run Python bridge tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && python3 -m pytest python/test_bridge_runtime.py -q
```

Expected: all Python tests pass.

- [ ] **Step 2: Run full Rust tests**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && ~/.cargo/bin/cargo test
```

Expected: all Rust tests pass.

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

- [ ] **Step 5: Check worktree status**

```bash
cd /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap && git status --short --branch
```

Expected: clean branch with no unstaged changes.

- [ ] **Step 6: Push to remote main**

```bash
TOKEN=$(cat /tmp/candle_cli_push_token) && git -C /home/mseco/candle-cli-target/.worktrees/phase1-bootstrap push "https://x-access-token:${TOKEN}@github.com/DuangZ-GR/candle-cli.git" feature/phase1-bootstrap:main
```

Expected: remote `main` advances.

---

## Self-Review

- Spec coverage: `/tools` is covered in Task 3, `/status` in Task 4, `/trace` and trace model in Task 1/2, verification/push in Task 5.
- Placeholder scan: each task includes concrete code snippets and exact commands.
- Type consistency: `ExecutionTrace` / `TraceEvent` are introduced once in `src/agent/trace.rs` and reused consistently; `run_single_turn_with_trace` is the only new loop entry point; `tool_names` is scoped to `ToolRegistry`.

Plan complete and saved to `docs/superpowers/plans/2026-05-21-runtime-introspection-commands.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — run tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
