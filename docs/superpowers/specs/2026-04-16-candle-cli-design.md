# Candle CLI Design Spec

**Date:** 2026-04-16

## 1. Project

### Goal
Build a terminal-only agentic CLI assistant in `DuangZ-GR/candle-cli` with:
- multi-turn conversation
- session persistence and resume
- context assembly
- basic coding tools
- a bounded single-agent loop
- a model/runtime boundary designed around candle

### Constraints
- core architecture must be candle-native
- must not become a generic provider-first CLI with candle added later as a backend
- Phase 1 does not modify the `candle` repository
- Rust is the main implementation language
- Phase 1 may use a local-first bridge runtime
- target repository starts effectively empty

## 2. Repository Analysis Summary

### candle
Role in this project:
- long-term model/runtime target
- execution substrate and future local reasoning core
- source of architectural direction for local-first runtime ownership

What it provides now:
- tensor/autograd/backend framework
- roadmap toward cognitive runtime and self-hosted tool-use runtime

What it does not currently provide as an off-the-shelf solution for this project:
- full terminal agent CLI
- session/tool/permission architecture
- mature local chat runtime surface for this product
- finalized tokenizer/chat-template/generation/tool-call stack for this use case

Conclusion:
- use candle as the target runtime center
- do not block Phase 1 on fully completed candle-native inference stack

### claw-code
Useful areas:
- CLI structure
- input handling
- terminal rendering
- session structure
- runtime layering
- permission policy design

Not adopted as core:
- provider-centric runtime assumptions
- broad surface area for plugins/MCP/hooks in Phase 1

Conclusion:
- borrow product/runtime design patterns
- rewrite implementation for candle-target architecture

### claude-code-from-scratch
Useful areas:
- minimal agent loop abstraction
- minimal coding tool surface
- session persistence shape
- phased expansion model

Not adopted as core:
- provider-shaped internal protocol
- direct reuse of Anthropic/OpenAI message assumptions

Conclusion:
- use as abstraction reference for Phase 1 and Phase 2 decomposition

### mindnlp
Useful areas:
- generation and model-wrapper reference
- tokenizer/from_pretrained/pipeline design ideas

Not adopted as core:
- not part of MVP main stack
- not the long-term backend for this project

Conclusion:
- optional reference only

## 3. Chosen Architecture

### Direction
Use **Candle Target Runtime**.

### Core idea
- Rust owns the terminal product shell
- Rust owns session, tools, permissions, and agent loop
- model/runtime interaction is defined by `CandleTargetRuntime`
- Phase 1 provides `MockRuntime` and `LocalBridgeRuntime`
- Phase 2 evolves toward direct `CandleRuntime`

### Rejected alternatives
#### Provider-first runtime
Rejected because it would make candle just another backend and let provider schemas define the system center.

#### Build full candle inference/runtime first
Rejected for Phase 1 because it would turn the project into a local runtime effort before delivering a usable CLI assistant.

## 4. Module Architecture

### CLI / REPL
Responsibility:
- startup
- REPL input loop
- one-shot prompt mode
- slash command dispatch
- output entrypoint

Planned files:
- `src/main.rs`
- `src/cli/args.rs`
- `src/cli/repl.rs`
- `src/cli/commands.rs`

### UI
Responsibility:
- text rendering
- spinner
- tool call/result formatting
- diff-style output
- status and error presentation

Planned files:
- `src/ui/render.rs`
- `src/ui/spinner.rs`
- `src/ui/format.rs`

### Session
Responsibility:
- session model
- save/load/list/latest
- workspace root binding
- prompt history
- runtime metadata

Planned files:
- `src/session/model.rs`
- `src/session/store.rs`
- `src/session/resume.rs`

### Context
Responsibility:
- build turn request from session state
- budget handling
- simple truncation/compaction placeholder
- inject system prompt and tool context

Planned files:
- `src/context/builder.rs`
- `src/context/budget.rs`
- `src/context/compact.rs`

### Tools
Responsibility:
- tool abstraction
- registry
- input validation
- normalized result shape
- built-in coding tools

Phase 1 tools:
- `pwd`
- `glob`
- `grep`
- `read`
- `write`
- `edit`
- `shell`

Planned files:
- `src/tools/types.rs`
- `src/tools/registry.rs`
- `src/tools/builtin/pwd.rs`
- `src/tools/builtin/glob.rs`
- `src/tools/builtin/grep.rs`
- `src/tools/builtin/read.rs`
- `src/tools/builtin/write.rs`
- `src/tools/builtin/edit.rs`
- `src/tools/builtin/shell.rs`

### Permissions
Responsibility:
- permission mode definition
- allow/deny/prompt policy
- dangerous shell gating
- write/edit confirmation path

Planned files:
- `src/permissions/mode.rs`
- `src/permissions/policy.rs`
- `src/permissions/prompt.rs`

### Agent
Responsibility:
- single-agent turn loop
- consume runtime events
- call tools
- inject tool results
- stop on bounded conditions

Planned files:
- `src/agent/loop.rs`
- `src/agent/turn.rs`
- `src/agent/state.rs`

### Model Runtime
Responsibility:
- define `CandleTargetRuntime`
- define request/event/result types
- provide mock runtime
- provide bridge runtime
- reserve future direct candle runtime

Planned files:
- `src/model/types.rs`
- `src/model/runtime.rs`
- `src/model/mock.rs`
- `src/model/bridge.rs`
- `src/model/candle.rs`

## 5. Dependency Direction

```text
CLI / REPL
  -> AgentLoop
     -> SessionStore
     -> ContextBuilder
     -> ToolRegistry + PermissionPolicy
     -> CandleTargetRuntime
         -> MockRuntime
         -> LocalBridgeRuntime
         -> CandleRuntime
```

Rules:
- CLI does not depend on concrete model implementations
- AgentLoop does not depend on provider schema
- SessionStore does not depend on runtime internals
- ToolRegistry does not depend on model source
- `CandleTargetRuntime` is the only model-facing entry for upper layers

## 6. Data Model

### Session
Fields:
- `session_id`
- `workspace_root`
- `created_at`
- `updated_at`
- `messages`
- `prompt_history`
- `active_runtime`
- `active_model`
- optional compaction metadata

### Message roles
- `system`
- `user`
- `assistant`
- `tool`

### Content blocks
Internal canonical blocks:
- `Text`
- `ToolCall`
- `ToolResult`

### Runtime-facing types
Core planned types:
- `TurnRequest`
- `RuntimeEvent`
- `ToolCallIntent`
- `TurnResult`
- `RuntimeCapabilities`
- `RuntimeHealth`

## 7. CLI Surface

### Entry forms
- `candle-cli`
- `candle-cli prompt "..."`
- `candle-cli --resume`
- `candle-cli doctor`

### Initial slash commands
- `/help`
- `/status`
- `/session`
- `/resume`
- `/model`
- `/tools`
- `/permissions`
- `/doctor`
- `/clear`
- `/exit`

### Excluded from Phase 1
- `/plan`
- `/agents`
- `/memory`
- `/skills`
- `/mcp`

## 8. Phase Scope

### Phase 1
Includes:
- Rust CLI and REPL
- session persistence and resume
- context builder
- tools and permissions
- bounded single-agent loop
- `MockRuntime`
- `LocalBridgeRuntime`
- basic rendering
- status/doctor support

Excludes:
- MCP
- memory
- skills
- multi-agent
- plan mode
- hooks/plugin system
- advanced compaction
- direct `CandleRuntime`
- changes to `candle` repository

### Phase 2
Planned direction:
- direct `CandleRuntime`
- tokenizer/chat-template ownership
- generation and sampling
- richer streaming
- structured tool-call decode
- stronger compaction
- memory, skills, plan mode, subagent, MCP

## 9. MVP Definition

MVP must provide:
- usable terminal interaction
- multi-turn conversation
- session save/load/resume
- workspace read/search/write/edit/shell tooling
- active permissions
- bounded single-agent loop
- runtime boundary centered on `CandleTargetRuntime`

MVP does not require:
- direct candle-native inference in Phase 1
- full Claude Code surface area
- MCP/memory/skills/multi-agent

## 10. Execution Stages

### Stage 0: Project bootstrap
Deliverables:
- Rust project initialization
- baseline directory structure
- test/fmt/lint setup

### Stage 1: CLI + Session
Deliverables:
- REPL
- one-shot prompt mode
- session model/store/resume

### Stage 2: Read-only tools + permissions
Deliverables:
- tool abstractions
- registry
- read-only tools
- permission mode/policy

### Stage 3: Runtime contract + MockRuntime
Deliverables:
- `CandleTargetRuntime`
- runtime event/request/result types
- mock runtime

### Stage 4: AgentLoop + ContextBuilder
Deliverables:
- turn loop
- runtime event consumption
- tool result injection
- context assembly

### Stage 5: Write/edit/shell tools
Deliverables:
- mutation-capable tools
- dangerous action gating
- read-before-edit/write policy

### Stage 6: LocalBridgeRuntime
Deliverables:
- real local runtime bridge under `CandleTargetRuntime`
- no changes to `candle` repository in this phase

### Stage 7: MVP polish
Deliverables:
- improved rendering
- spinner
- better status/doctor commands
- basic diagnostics and error presentation

## 11. Bridge Decision

### Current design decision
For design work, keep the bridge transport uncommitted until runtime contract is finalized.

### Current implementation preference
When Phase 1 implementation reaches the bridge stage, prefer:
- local-first bridge
- child-process bridge
- structured messages over stdio

Reason:
- simpler MVP shape
- keeps candle-cli self-contained
- avoids introducing a full local serving system too early

## 12. Directory Structure

```text
candle-cli/
├── Cargo.toml
├── src/
│   ├── main.rs
│   ├── cli/
│   │   ├── mod.rs
│   │   ├── args.rs
│   │   ├── repl.rs
│   │   └── commands.rs
│   ├── ui/
│   │   ├── mod.rs
│   │   ├── render.rs
│   │   ├── spinner.rs
│   │   └── format.rs
│   ├── session/
│   │   ├── mod.rs
│   │   ├── model.rs
│   │   ├── store.rs
│   │   └── resume.rs
│   ├── context/
│   │   ├── mod.rs
│   │   ├── builder.rs
│   │   ├── budget.rs
│   │   └── compact.rs
│   ├── tools/
│   │   ├── mod.rs
│   │   ├── types.rs
│   │   ├── registry.rs
│   │   └── builtin/
│   │       ├── pwd.rs
│   │       ├── glob.rs
│   │       ├── grep.rs
│   │       ├── read.rs
│   │       ├── write.rs
│   │       ├── edit.rs
│   │       └── shell.rs
│   ├── permissions/
│   │   ├── mod.rs
│   │   ├── mode.rs
│   │   ├── policy.rs
│   │   └── prompt.rs
│   ├── agent/
│   │   ├── mod.rs
│   │   ├── loop.rs
│   │   ├── turn.rs
│   │   └── state.rs
│   └── model/
│       ├── mod.rs
│       ├── types.rs
│       ├── runtime.rs
│       ├── mock.rs
│       ├── bridge.rs
│       └── candle.rs
└── tests/
    ├── cli/
    ├── session/
    ├── tools/
    ├── permissions/
    ├── model/
    └── agent/
```

## 13. Decisions Frozen by This Spec

- main language is Rust
- architecture is Candle Target Runtime
- Phase 1 does not modify candle repository
- Phase 1 is product-shell-first, not provider-first
- `LocalBridgeRuntime` is transitional, not the long-term center
- direct `CandleRuntime` is a Phase 2 direction
- Phase 1 scope excludes MCP/memory/skills/multi-agent/plan mode
