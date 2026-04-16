# Candle CLI Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable Phase 1 version of `candle-cli`: a Rust terminal coding assistant with REPL, session persistence, basic coding tools, permissions, a bounded single-agent loop, and a candle-targeted runtime boundary backed first by `MockRuntime` and then `LocalBridgeRuntime`.

**Architecture:** The project is split into `cli`, `session`, `context`, `tools`, `permissions`, `agent`, `model`, and `ui` modules. Upper layers depend only on the internal `CandleTargetRuntime` contract, never on provider-shaped schemas. Phase 1 reaches real end-to-end usability through a local-first bridge runtime without modifying the `candle` repository.

**Tech Stack:** Rust stable, Cargo, `serde`, `serde_json`, `clap`, `rustyline`, `globwalk`, `grep`/`ignore`-style file search crates or equivalent, `tokio` only if bridge/runtime transport needs async, `tempfile`, `assert_cmd`, `insta` or standard snapshot/assert testing.

---

## File Structure Map

### Core crate layout
- `src/main.rs` — binary entrypoint
- `src/cli/args.rs` — CLI argument parsing
- `src/cli/repl.rs` — REPL input loop
- `src/cli/commands.rs` — slash command parsing and dispatch
- `src/session/model.rs` — session/message/content types
- `src/session/store.rs` — session persistence
- `src/session/resume.rs` — latest/list/load helpers
- `src/context/builder.rs` — build `TurnRequest` from session state
- `src/context/budget.rs` — token/context budget placeholder policy
- `src/context/compact.rs` — simple truncation/compaction placeholder
- `src/tools/types.rs` — tool traits/types
- `src/tools/registry.rs` — registry and dispatch
- `src/tools/builtin/*.rs` — built-in tool implementations
- `src/permissions/mode.rs` — permission mode enum
- `src/permissions/policy.rs` — allow/deny/prompt logic
- `src/permissions/prompt.rs` — terminal confirmation handling
- `src/model/types.rs` — runtime request/event/result types
- `src/model/runtime.rs` — `CandleTargetRuntime` trait
- `src/model/mock.rs` — mock runtime implementation
- `src/model/bridge.rs` — local-first bridge runtime
- `src/model/candle.rs` — future direct candle runtime placeholder
- `src/agent/loop.rs` — bounded agent loop
- `src/agent/turn.rs` — one-turn orchestration helpers
- `src/agent/state.rs` — agent turn state
- `src/ui/render.rs` — output rendering helpers
- `src/ui/spinner.rs` — spinner
- `src/ui/format.rs` — tool/result formatting helpers

### Test layout
- `tests/cli/*.rs`
- `tests/session/*.rs`
- `tests/tools/*.rs`
- `tests/permissions/*.rs`
- `tests/model/*.rs`
- `tests/agent/*.rs`

---

### Task 1: Bootstrap the Rust crate and binary entrypoint

**Files:**
- Create: `Cargo.toml`
- Create: `src/main.rs`
- Create: `src/lib.rs`
- Create: `src/cli/mod.rs`
- Create: `tests/cli/test_bootstrap.rs`
- Modify: `README.md`

- [ ] **Step 1: Write the failing bootstrap test**

```rust
use assert_cmd::Command;

#[test]
fn binary_starts_and_shows_help() {
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.arg("--help");
    cmd.assert().success();
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_bootstrap`
Expected: FAIL because the crate and binary do not exist yet.

- [ ] **Step 3: Write minimal crate scaffolding**

Create `Cargo.toml`:

```toml
[package]
name = "candle-cli"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "candle-cli"
path = "src/main.rs"

[dependencies]
clap = { version = "4", features = ["derive"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"

[dev-dependencies]
assert_cmd = "2"
```

Create `src/lib.rs`:

```rust
pub mod cli;
```

Create `src/cli/mod.rs`:

```rust
pub mod args;
```

Create `src/main.rs`:

```rust
use clap::Parser;

#[derive(Parser, Debug)]
#[command(name = "candle-cli")]
struct Args {}

fn main() {
    let _ = Args::parse();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_bootstrap`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Cargo.toml README.md src/main.rs src/lib.rs src/cli/mod.rs tests/cli/test_bootstrap.rs
git commit -m "build: bootstrap candle-cli Rust crate"
```

---

### Task 2: Add CLI argument parsing and command modes

**Files:**
- Create: `src/cli/args.rs`
- Create: `tests/cli/test_args.rs`
- Modify: `src/main.rs`

- [ ] **Step 1: Write the failing argument parser tests**

```rust
use candle_cli::cli::args::{Cli, CommandMode};
use clap::Parser;

#[test]
fn parses_prompt_mode() {
    let cli = Cli::parse_from(["candle-cli", "prompt", "hello"]);
    assert!(matches!(cli.command, Some(CommandMode::Prompt { .. })));
}

#[test]
fn parses_resume_flag() {
    let cli = Cli::parse_from(["candle-cli", "--resume"]);
    assert!(cli.resume);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_args`
Expected: FAIL because `args.rs` types do not exist.

- [ ] **Step 3: Implement minimal CLI model**

Create `src/cli/args.rs`:

```rust
use clap::{Parser, Subcommand};

#[derive(Parser, Debug)]
#[command(name = "candle-cli")]
pub struct Cli {
    #[arg(long)]
    pub resume: bool,
    #[command(subcommand)]
    pub command: Option<CommandMode>,
}

#[derive(Subcommand, Debug)]
pub enum CommandMode {
    Prompt { input: String },
    Doctor,
}
```

Update `src/cli/mod.rs`:

```rust
pub mod args;
```

Update `src/main.rs`:

```rust
use candle_cli::cli::args::Cli;
use clap::Parser;

fn main() {
    let _cli = Cli::parse();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_args`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cli/args.rs src/cli/mod.rs src/main.rs tests/cli/test_args.rs
git commit -m "feat: add candle-cli command modes"
```

---

### Task 3: Define session, message, and content block models

**Files:**
- Create: `src/session/mod.rs`
- Create: `src/session/model.rs`
- Create: `tests/session/test_model.rs`
- Modify: `src/lib.rs`

- [ ] **Step 1: Write the failing session model test**

```rust
use candle_cli::session::model::{ContentBlock, Message, MessageRole, Session};

#[test]
fn session_holds_user_message() {
    let msg = Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text { text: "hello".into() }],
    };
    let session = Session::new("workspace".into());
    assert_eq!(msg.role, MessageRole::User);
    assert_eq!(session.workspace_root, "workspace");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_model`
Expected: FAIL because session types do not exist.

- [ ] **Step 3: Implement session model**

Create `src/session/model.rs`:

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum MessageRole {
    System,
    User,
    Assistant,
    Tool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ContentBlock {
    Text { text: String },
    ToolCall { id: String, name: String, input: String },
    ToolResult { tool_call_id: String, output: String, is_error: bool },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Message {
    pub role: MessageRole,
    pub blocks: Vec<ContentBlock>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Session {
    pub session_id: String,
    pub workspace_root: String,
    pub messages: Vec<Message>,
}

impl Session {
    pub fn new(workspace_root: String) -> Self {
        Self {
            session_id: "session-1".into(),
            workspace_root,
            messages: Vec::new(),
        }
    }
}
```

Create `src/session/mod.rs`:

```rust
pub mod model;
pub mod resume;
pub mod store;
```

Update `src/lib.rs`:

```rust
pub mod cli;
pub mod session;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_model`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib.rs src/session/mod.rs src/session/model.rs tests/session/test_model.rs
git commit -m "feat: define session and message model"
```

---

### Task 4: Add session persistence and resume helpers

**Files:**
- Create: `src/session/store.rs`
- Create: `src/session/resume.rs`
- Create: `tests/session/test_store.rs`

- [ ] **Step 1: Write the failing session round-trip test**

```rust
use candle_cli::session::model::Session;
use candle_cli::session::store::SessionStore;
use tempfile::tempdir;

#[test]
fn saves_and_loads_session() {
    let dir = tempdir().unwrap();
    let store = SessionStore::new(dir.path().into());
    let session = Session::new("/tmp/workspace".into());
    store.save(&session).unwrap();
    let loaded = store.load(&session.session_id).unwrap();
    assert_eq!(loaded.workspace_root, "/tmp/workspace");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_store`
Expected: FAIL because `SessionStore` does not exist.

- [ ] **Step 3: Implement persistence and latest lookup**

Create `src/session/store.rs` with JSON persistence helpers for `save`, `load`, and `list`.

Create `src/session/resume.rs` with a `latest_session_id()` helper that sorts saved sessions by modified time.

Minimal signatures:

```rust
pub struct SessionStore { /* ... */ }
impl SessionStore {
    pub fn new(root: std::path::PathBuf) -> Self;
    pub fn save(&self, session: &Session) -> std::io::Result<()>;
    pub fn load(&self, id: &str) -> std::io::Result<Session>;
    pub fn list(&self) -> std::io::Result<Vec<String>>;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_store`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/session/store.rs src/session/resume.rs tests/session/test_store.rs
git commit -m "feat: add session persistence and resume helpers"
```

---

### Task 5: Implement REPL and top-level command dispatch

**Files:**
- Create: `src/cli/repl.rs`
- Create: `src/cli/commands.rs`
- Create: `tests/cli/test_commands.rs`
- Modify: `src/main.rs`
- Modify: `src/cli/mod.rs`

- [ ] **Step 1: Write the failing slash command test**

```rust
use candle_cli::cli::commands::parse_slash_command;

#[test]
fn parses_help_command() {
    let parsed = parse_slash_command("/help");
    assert_eq!(parsed.as_deref(), Some("help"));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_commands`
Expected: FAIL because REPL command parser does not exist.

- [ ] **Step 3: Implement minimal REPL and command parsing**

Create `src/cli/commands.rs`:

```rust
pub fn parse_slash_command(input: &str) -> Option<String> {
    input.strip_prefix('/').map(|value| value.trim().to_string())
}
```

Create `src/cli/repl.rs` with a minimal stdin loop that reads one line and returns it.

Update `src/cli/mod.rs`:

```rust
pub mod args;
pub mod commands;
pub mod repl;
```

Update `src/main.rs` to branch between prompt mode, doctor mode, and REPL mode.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_commands`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cli/commands.rs src/cli/repl.rs src/cli/mod.rs src/main.rs tests/cli/test_commands.rs
git commit -m "feat: add repl and slash command parsing"
```

---

### Task 6: Add permission modes and permission policy

**Files:**
- Create: `src/permissions/mod.rs`
- Create: `src/permissions/mode.rs`
- Create: `src/permissions/policy.rs`
- Create: `tests/permissions/test_policy.rs`
- Modify: `src/lib.rs`

- [ ] **Step 1: Write the failing permission policy test**

```rust
use candle_cli::permissions::mode::PermissionMode;
use candle_cli::permissions::policy::PermissionPolicy;

#[test]
fn read_tool_allowed_in_read_only() {
    let policy = PermissionPolicy::new(PermissionMode::ReadOnly);
    assert!(policy.allows("read"));
    assert!(!policy.allows("shell"));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_policy`
Expected: FAIL because permission types do not exist.

- [ ] **Step 3: Implement permission mode and policy**

Create `src/permissions/mode.rs`:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PermissionMode {
    ReadOnly,
    WorkspaceWrite,
    DangerFullAccess,
    Prompt,
}
```

Create `src/permissions/policy.rs` with `allows(tool_name: &str) -> bool` and `requires_prompt(tool_name: &str) -> bool`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_policy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib.rs src/permissions/mod.rs src/permissions/mode.rs src/permissions/policy.rs tests/permissions/test_policy.rs
git commit -m "feat: add permission modes and policy"
```

---

### Task 7: Add tool types, registry, and read-only tools

**Files:**
- Create: `src/tools/mod.rs`
- Create: `src/tools/types.rs`
- Create: `src/tools/registry.rs`
- Create: `src/tools/builtin/pwd.rs`
- Create: `src/tools/builtin/glob.rs`
- Create: `src/tools/builtin/grep.rs`
- Create: `src/tools/builtin/read.rs`
- Create: `tests/tools/test_read_only_tools.rs`
- Modify: `src/lib.rs`

- [ ] **Step 1: Write the failing registry execution test**

```rust
use candle_cli::tools::registry::ToolRegistry;

#[test]
fn pwd_tool_runs() {
    let registry = ToolRegistry::default_read_only();
    let result = registry.execute("pwd", "{}").unwrap();
    assert!(!result.is_empty());
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_read_only_tools`
Expected: FAIL because tool registry does not exist.

- [ ] **Step 3: Implement tool registry and read-only tools**

Create a minimal `ToolRegistry` that stores closures or concrete tool handlers and supports:
- `pwd`
- `glob`
- `grep`
- `read`

Minimal interface:

```rust
pub struct ToolRegistry { /* ... */ }
impl ToolRegistry {
    pub fn default_read_only() -> Self;
    pub fn execute(&self, name: &str, input_json: &str) -> Result<String, String>;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_read_only_tools`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib.rs src/tools/mod.rs src/tools/types.rs src/tools/registry.rs src/tools/builtin/pwd.rs src/tools/builtin/glob.rs src/tools/builtin/grep.rs src/tools/builtin/read.rs tests/tools/test_read_only_tools.rs
git commit -m "feat: add read-only tools and registry"
```

---

### Task 8: Define runtime types and `CandleTargetRuntime`

**Files:**
- Create: `src/model/mod.rs`
- Create: `src/model/types.rs`
- Create: `src/model/runtime.rs`
- Create: `tests/model/test_runtime_contract.rs`
- Modify: `src/lib.rs`

- [ ] **Step 1: Write the failing runtime contract test**

```rust
use candle_cli::model::types::{RuntimeEvent, TurnRequest};
use candle_cli::model::runtime::CandleTargetRuntime;

#[test]
fn turn_request_exists() {
    let req = TurnRequest {
        system_prompt: "sys".into(),
        messages_json: "[]".into(),
        tools_json: "[]".into(),
    };
    assert_eq!(req.system_prompt, "sys");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_runtime_contract`
Expected: FAIL because runtime types do not exist.

- [ ] **Step 3: Implement runtime contract**

Create `src/model/types.rs` with:
- `TurnRequest`
- `ToolCallIntent`
- `RuntimeEvent`
- `TurnResult`
- `RuntimeCapabilities`
- `RuntimeHealth`

Create `src/model/runtime.rs` with:

```rust
use crate::model::types::{RuntimeCapabilities, RuntimeHealth, TurnRequest, TurnResult};

pub trait CandleTargetRuntime {
    fn generate_turn(&mut self, request: TurnRequest) -> Result<TurnResult, String>;
    fn healthcheck(&self) -> RuntimeHealth;
    fn capabilities(&self) -> RuntimeCapabilities;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_runtime_contract`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib.rs src/model/mod.rs src/model/types.rs src/model/runtime.rs tests/model/test_runtime_contract.rs
git commit -m "feat: define candle target runtime contract"
```

---

### Task 9: Implement `MockRuntime`

**Files:**
- Create: `src/model/mock.rs`
- Create: `tests/model/test_mock_runtime.rs`
- Modify: `src/model/mod.rs`

- [ ] **Step 1: Write the failing mock runtime test**

```rust
use candle_cli::model::mock::MockRuntime;
use candle_cli::model::runtime::CandleTargetRuntime;
use candle_cli::model::types::TurnRequest;

#[test]
fn mock_runtime_returns_text() {
    let mut runtime = MockRuntime::default();
    let result = runtime.generate_turn(TurnRequest {
        system_prompt: "sys".into(),
        messages_json: "[]".into(),
        tools_json: "[]".into(),
    }).unwrap();
    assert!(!result.final_text.is_empty());
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_mock_runtime`
Expected: FAIL because `MockRuntime` does not exist.

- [ ] **Step 3: Implement mock runtime**

Create `src/model/mock.rs` with a default runtime that returns a small text answer and no tool calls.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_mock_runtime`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/model/mod.rs src/model/mock.rs tests/model/test_mock_runtime.rs
git commit -m "feat: add mock runtime"
```

---

### Task 10: Implement context builder

**Files:**
- Create: `src/context/mod.rs`
- Create: `src/context/builder.rs`
- Create: `src/context/budget.rs`
- Create: `src/context/compact.rs`
- Create: `tests/agent/test_context_builder.rs`
- Modify: `src/lib.rs`

- [ ] **Step 1: Write the failing context builder test**

```rust
use candle_cli::context::builder::build_turn_request;
use candle_cli::session::model::Session;

#[test]
fn builds_turn_request_from_session() {
    let session = Session::new("/tmp/workspace".into());
    let req = build_turn_request(&session, "sys", "[]").unwrap();
    assert_eq!(req.system_prompt, "sys");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_context_builder`
Expected: FAIL because context builder does not exist.

- [ ] **Step 3: Implement context builder**

Create `build_turn_request(session, system_prompt, tools_json)` returning `TurnRequest` with serialized session messages.

Use simple placeholder budget/compact functions in `budget.rs` and `compact.rs` without advanced logic.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_context_builder`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib.rs src/context/mod.rs src/context/builder.rs src/context/budget.rs src/context/compact.rs tests/agent/test_context_builder.rs
git commit -m "feat: add context builder"
```

---

### Task 11: Implement bounded agent loop with tool execution

**Files:**
- Create: `src/agent/mod.rs`
- Create: `src/agent/loop.rs`
- Create: `src/agent/turn.rs`
- Create: `src/agent/state.rs`
- Create: `tests/agent/test_agent_loop.rs`
- Modify: `src/lib.rs`

- [ ] **Step 1: Write the failing agent loop test**

```rust
use candle_cli::agent::loop::run_single_turn;
use candle_cli::model::mock::MockRuntime;
use candle_cli::session::model::Session;
use candle_cli::tools::registry::ToolRegistry;

#[test]
fn agent_loop_returns_final_text() {
    let mut session = Session::new("/tmp/workspace".into());
    let mut runtime = MockRuntime::default();
    let tools = ToolRegistry::default_read_only();
    let result = run_single_turn(&mut session, &mut runtime, &tools, "sys").unwrap();
    assert!(!result.final_text.is_empty());
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_agent_loop`
Expected: FAIL because the agent loop does not exist.

- [ ] **Step 3: Implement the minimal loop**

Add `run_single_turn` that:
- builds a turn request
- calls runtime
- appends assistant output to session
- returns final text

Keep the first version bounded to a single model turn with no recursive tool loop yet.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_agent_loop`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib.rs src/agent/mod.rs src/agent/loop.rs src/agent/turn.rs src/agent/state.rs tests/agent/test_agent_loop.rs
git commit -m "feat: add minimal bounded agent loop"
```

---

### Task 12: Add write, edit, and shell tools with permission enforcement

**Files:**
- Create: `src/tools/builtin/write.rs`
- Create: `src/tools/builtin/edit.rs`
- Create: `src/tools/builtin/shell.rs`
- Create: `src/permissions/prompt.rs`
- Create: `tests/tools/test_write_edit_shell.rs`
- Modify: `src/tools/registry.rs`
- Modify: `src/permissions/policy.rs`

- [ ] **Step 1: Write the failing shell permission test**

```rust
use candle_cli::permissions::mode::PermissionMode;
use candle_cli::permissions::policy::PermissionPolicy;

#[test]
fn shell_denied_in_read_only() {
    let policy = PermissionPolicy::new(PermissionMode::ReadOnly);
    assert!(!policy.allows("shell"));
}
```

- [ ] **Step 2: Run test to verify it fails if policy is incomplete**

Run: `cargo test --test test_write_edit_shell`
Expected: FAIL because write/edit/shell tools and prompt handling are missing.

- [ ] **Step 3: Implement mutation-capable tools**

Add:
- `write` for overwriting file contents
- `edit` for exact string replacement
- `shell` for running a command with captured output

Update registry to register these tools only in modes that allow them.

Add prompt helper in `src/permissions/prompt.rs` for interactive confirmation of dangerous actions.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_write_edit_shell`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tools/builtin/write.rs src/tools/builtin/edit.rs src/tools/builtin/shell.rs src/tools/registry.rs src/permissions/policy.rs src/permissions/prompt.rs tests/tools/test_write_edit_shell.rs
git commit -m "feat: add mutation tools and shell permissions"
```

---

### Task 13: Integrate REPL with sessions, runtime, and agent loop

**Files:**
- Modify: `src/cli/repl.rs`
- Modify: `src/main.rs`
- Create: `tests/cli/test_repl_session_integration.rs`

- [ ] **Step 1: Write the failing integration smoke test**

```rust
use assert_cmd::Command;

#[test]
fn doctor_command_still_runs() {
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.arg("doctor");
    cmd.assert().success();
}
```

- [ ] **Step 2: Run test to verify it fails if integration is incomplete**

Run: `cargo test --test test_repl_session_integration`
Expected: FAIL or incomplete behavior because top-level integration is missing.

- [ ] **Step 3: Wire the application together**

Update `src/main.rs` and `src/cli/repl.rs` to:
- create/load session store
- start REPL
- pass user input into agent loop
- save session after each turn

Use `MockRuntime` as the initial default runtime for this integration step.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_repl_session_integration`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.rs src/cli/repl.rs tests/cli/test_repl_session_integration.rs
git commit -m "feat: wire repl, sessions, and agent loop together"
```

---

### Task 14: Add basic rendering, spinner, and doctor/status output

**Files:**
- Create: `src/ui/mod.rs`
- Create: `src/ui/render.rs`
- Create: `src/ui/spinner.rs`
- Create: `src/ui/format.rs`
- Create: `tests/cli/test_doctor_status.rs`
- Modify: `src/lib.rs`
- Modify: `src/main.rs`

- [ ] **Step 1: Write the failing doctor/status output test**

```rust
use assert_cmd::Command;

#[test]
fn doctor_mode_exits_successfully() {
    let mut cmd = Command::cargo_bin("candle-cli").unwrap();
    cmd.arg("doctor");
    cmd.assert().success();
}
```

- [ ] **Step 2: Run test to verify it fails if output plumbing is absent**

Run: `cargo test --test test_doctor_status`
Expected: FAIL or incomplete behavior because UI/doctor/status are not implemented.

- [ ] **Step 3: Implement basic UI helpers**

Add simple text render helpers and spinner utilities. Add top-level `doctor` and `/status` output that reports:
- current workspace
- session storage location
- configured runtime name

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_doctor_status`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib.rs src/ui/mod.rs src/ui/render.rs src/ui/spinner.rs src/ui/format.rs src/main.rs tests/cli/test_doctor_status.rs
git commit -m "feat: add basic UI rendering and doctor output"
```

---

### Task 15: Add `LocalBridgeRuntime` placeholder and bridge health path

**Files:**
- Create: `src/model/bridge.rs`
- Create: `src/model/candle.rs`
- Create: `tests/model/test_bridge_runtime.rs`
- Modify: `src/model/mod.rs`

- [ ] **Step 1: Write the failing bridge runtime test**

```rust
use candle_cli::model::bridge::LocalBridgeRuntime;
use candle_cli::model::runtime::CandleTargetRuntime;

#[test]
fn bridge_runtime_reports_health() {
    let runtime = LocalBridgeRuntime::new("python3".into());
    assert!(runtime.healthcheck().ok);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --test test_bridge_runtime`
Expected: FAIL because bridge runtime does not exist.

- [ ] **Step 3: Implement bridge placeholder and future candle placeholder**

Create `src/model/bridge.rs` with a minimal constructor and healthcheck/capabilities implementation.

Create `src/model/candle.rs` with a placeholder `CandleRuntime` struct returning `not_implemented` style health/capabilities.

Do not implement full child-process transport yet; just lock the type boundary and health path.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --test test_bridge_runtime`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/model/mod.rs src/model/bridge.rs src/model/candle.rs tests/model/test_bridge_runtime.rs
git commit -m "feat: add bridge runtime and candle runtime placeholders"
```

---

### Task 16: Run full verification for Phase 1 foundation

**Files:**
- Test only: existing files from Tasks 1-15

- [ ] **Step 1: Run full test suite**

Run: `cargo test`
Expected: PASS for all tests.

- [ ] **Step 2: Run formatting check**

Run: `cargo fmt --check`
Expected: PASS with no formatting changes needed.

- [ ] **Step 3: Run lints**

Run: `cargo clippy --all-targets --all-features -- -D warnings`
Expected: PASS with no warnings.

- [ ] **Step 4: Record remaining gaps for next plan**

Verify these are still intentionally deferred and not accidental omissions:
- real child-process bridge transport
- advanced compaction
- direct candle runtime implementation
- memory/skills/MCP/multi-agent

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "test: verify Phase 1 foundation for candle-cli"
```
```
