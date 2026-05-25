# Runtime Introspection Commands Design

**Date:** 2026-05-21

## Goal

Add a small, demonstration-friendly runtime introspection layer to `candle-cli` so that after a turn completes, the user can inspect:

- which tools the agent knows about,
- the current session/runtime state,
- the most recent execution trace.

The feature should stay simple, terminal-native, and easy to explain. It is not a logging framework and it is not a profiling system. Its purpose is to make the project easier to debug, easier to demo, and easier to describe on a résumé.

## Problem Statement

The project already supports:

- multi-turn REPL interaction,
- session persistence,
- tool execution,
- structured tool results,
- verbose stderr traces,
- DeepSeek-backed real tool use.

However, those capabilities are still partly hidden from the user:

- there is no simple built-in way to list the registered tools;
- there is no single command to summarize the current runtime state;
- there is no user-facing way to inspect the last execution path except watching verbose output live.

That makes the system harder to demo and harder to explain.

## Scope

### In scope

Add three new REPL-only slash commands:

- `/tools`
- `/status`
- `/trace`

These commands should:

- work after the REPL starts without changing the core agent loop contract,
- show information that already exists or can be recorded cheaply,
- avoid introducing complex persistence or telemetry infrastructure.

### Out of scope

- prompt-mode introspection commands,
- persistent trace history across sessions,
- JSON or file-based trace export,
- low-level model operator tracing,
- web dashboards,
- new runtime backends,
- new tool types.

## Interaction Model

The interaction should be **post-execution inspection**, not a live streaming dashboard.

That means the expected user flow is:

```text
> 读取 README.md，总结如何运行项目
...assistant answers...
> /trace
...show last execution chain...
> /status
...show current runtime/session state...
> /tools
...show registered tools...
```

This is the right trade-off because it is:

- simpler than a live trace console,
- easier to test,
- easier for the user to understand,
- better aligned with the current REPL architecture.

The existing `CANDLE_CLI_VERBOSE=1` behavior remains useful for live low-level debugging. The new commands are complementary: they provide a user-facing snapshot after execution.

## Command Design

### `/tools`

Purpose: show which internal interfaces are currently available to the agent.

Expected output:

```text
Registered tools
- pwd
- read
- glob
- grep
- edit
- shell
```

Design notes:

- the list should come directly from the tool registry rather than being duplicated in CLI code;
- the first version should print names only;
- descriptions can be added later if needed.

### `/status`

Purpose: show the current runtime/session state in one place.

Expected output shape:

```text
Session
- session_id: session-...
- messages: 8
- workspace: /home/.../candle-cli-target
- permission: read-only
- runtime: bridge
- model: deepseek-v4-flash
- max_turns: 20
```

The exact labels can vary slightly, but the command should at minimum expose:

- session id,
- number of messages,
- workspace root,
- permission mode,
- runtime mode,
- model id,
- max turns.

Design notes:

- most of this is already available through the session, env vars, or existing configuration helpers;
- `/status` should remain stable even if no user turn has run yet.

### `/trace`

Purpose: show the last execution chain in a compact, human-readable form.

Expected output shape:

```text
Last trace
1. build_turn_request
2. runtime.generate_turn
3. parse_tool_call
4. tool: read
5. tool result: ok
6. runtime.generate_turn
7. final answer
```

If the last run failed or recovered from an error, the trace should still summarize the path:

```text
Last trace
1. build_turn_request
2. runtime.generate_turn
3. parse_tool_call
4. tool: shell
5. tool result: error
6. final answer
```

If the user has not run any model turn yet, `/trace` should print:

```text
no trace available
```

Design notes:

- first version only stores the latest trace, not a history;
- the trace should summarize steps, not dump full tool outputs;
- this command is for humans, not the model.

## Data Model

Introduce a lightweight agent trace representation, for example in `src/agent/trace.rs`.

A minimal structure is enough:

```rust
pub enum TraceEvent {
    BuildTurnRequest,
    RuntimeGenerateTurn,
    ParseToolCall,
    ToolCall { name: String },
    ToolResult { tool: String, status: String },
    FinalAnswer,
}

pub struct ExecutionTrace {
    pub steps: Vec<TraceEvent>,
}
```

Only the latest trace needs to be stored during the REPL process. It does not need to be written into the session or persisted to disk.

The REPL layer can maintain:

```rust
Option<ExecutionTrace>
```

Whenever a new turn starts, it builds a new trace and replaces the previous one when complete.

## Architecture

### `src/agent/trace.rs`

Owns the trace representation and formatting helpers.

Responsibilities:

- define `TraceEvent`,
- define `ExecutionTrace`,
- optionally define a render helper to convert the trace into user-visible lines.

### `src/agent/loop.rs`

Owns trace emission.

Responsibilities:

- append trace steps at key boundaries,
- return or expose the trace to the caller,
- avoid mixing trace state into session messages.

A simple design is to add a variant of the loop entry point that writes into a mutable trace collector. The loop should remain bounded and otherwise unchanged.

### `src/tools/registry.rs`

Should expose the registered tool names for `/tools`.

A small helper such as:

```rust
pub fn tool_names(&self) -> Vec<&'static str>
```

is sufficient.

### `src/cli/repl.rs`

Owns command presentation.

Responsibilities:

- maintain the latest `ExecutionTrace`,
- implement `/tools`, `/status`, and `/trace`,
- keep command output simple and deterministic.

## Output and UX Principles

1. **Keep it compact**
   These commands should be readable in a terminal and suitable for demos.

2. **Keep it stable**
   The same state should produce the same output shape.

3. **Do not duplicate verbose logs**
   `/trace` is a summary of the last run, not a full replay of stderr output.

4. **Do not contaminate session state**
   Introspection belongs to the user-facing REPL, not to the model conversation transcript.

## Testing Strategy

### `/tools`

Add an integration test that:

- starts the REPL,
- sends `/tools`,
- asserts success,
- checks that output contains `pwd`, `read`, `glob`, `grep`, `edit`, and `shell`.

### `/status`

Add an integration test that:

- sends one normal input,
- then sends `/status`,
- asserts output contains session id, workspace, and messages count,
- optionally checks permission/runtime/model labels if deterministic in tests.

### `/trace`

Add an integration test that:

- runs one turn that triggers a tool call,
- then sends `/trace`,
- asserts output contains a compact execution chain such as `build_turn_request`, `runtime.generate_turn`, `tool: read`, and `tool result:`.

Add another test for the empty case:

- start REPL,
- immediately send `/trace`,
- expect `no trace available`.

### Internal trace tests

If a dedicated `ExecutionTrace` type is introduced, add a small unit test to verify formatting of a trace with a few steps.

## Success Criteria

This enhancement is complete when:

- the REPL supports `/tools`, `/status`, and `/trace`;
- `/tools` lists the registered tools;
- `/status` shows the current runtime/session state;
- `/trace` shows the most recent execution chain;
- `/trace` gracefully handles the "nothing has run yet" case;
- the feature is implemented without making the core agent loop significantly more complex;
- the output is simple enough to demonstrate and explain in an interview or project walkthrough.

## Why This Is Worth Doing

This feature makes the project significantly easier to present:

- it shows the internal interfaces the agent can use,
- it exposes current runtime state without digging through code,
- it demonstrates the execution path of a real multi-step agent turn.

That gives the project a concrete, user-facing differentiator while staying lightweight and technically understandable.
