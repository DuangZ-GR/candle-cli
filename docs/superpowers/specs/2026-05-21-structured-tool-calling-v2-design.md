# Structured Tool Calling v2 Design

**Date:** 2026-05-21

## Goal

Refine the current tool-calling agent loop so it is easier to reason about, easier to demonstrate, and more reliable with real models such as DeepSeek. The focus is not on adding new tools or new backends, but on making the existing structured tool-calling flow more stable, more explicit, and more inspectable.

The end state should still feel like a small project, not a framework. The system should remain easy to understand end-to-end.

## Current State

The project already supports:

- multi-turn REPL sessions,
- prompt mode,
- session persistence,
- a bounded multi-step tool loop,
- DeepSeek-backed real tool execution,
- fallback parsing for weak models,
- workspace boundaries and permission modes,
- structured text envelopes for tool results,
- basic verbose trace output.

That is enough for a minimal MVP. What is missing now is consistency and clarity across the protocol boundary.

## Problem Statement

The current implementation works, but several aspects are still “good enough” instead of explicit:

1. the relationship between the canonical `<tool_call>...</tool_call>` format and fallback forms like `read({...})` is implemented but not fully framed as a protocol contract;
2. tool result output is now more structured, but not yet formally treated as a stable interface for the model;
3. verbose tracing exists, but it should become a more intentional part of agent observability;
4. parser errors, permission denials, and execution failures should feel like well-defined states rather than just text that happened to work.

This version is about stabilizing those boundaries without making the project heavy.

## Scope

### In scope

This design covers three related enhancements.

#### 1. Protocol stability

- Keep `<tool_call>{...}</tool_call>` as the primary protocol.
- Keep `tool({...})` fallback syntax for weak models.
- Make the precedence and error behavior of both formats explicit.
- Make malformed tool-call recovery messages more precise.

#### 2. Structured tool result contract

- Treat text envelopes as the official result surface for now.
- Keep the session schema unchanged.
- Standardize success and error output for all tools.
- Keep shell output richer than other tools but in the same general envelope pattern.

#### 3. Observability

- Make verbose tracing more intentional and more consistent.
- Separate parser, permission, and tool execution trace events conceptually.
- Keep trace output in stderr only and out of the session.

### Out of scope

- Native OpenAI tool-call schemas.
- Parallel tool calls.
- Multi-tool batch planning in one model turn.
- New tools beyond the current set.
- Streaming.
- A new session block type.
- Candle-native inference changes.

## Design Principles

1. **Small-surface correctness over abstraction**
   Keep the protocol easy to explain and easy to test.

2. **One canonical protocol, one fallback**
   Avoid adding many alternate accepted forms. The more variants we accept, the harder the system becomes to reason about.

3. **Text-first compatibility**
   For this stage, tool results remain text envelopes because they are already compatible with the current session model and real-model prompting.

4. **Errors should remain in-band when possible**
   Parser errors, permission denials, and tool failures should be visible to the model as part of the conversation so it can recover or explain.

5. **Verbose mode is for humans, not the model**
   Trace output should help debugging and demos without contaminating session state.

## Enhancement 1: Protocol Stability

### Canonical protocol

The official tool-call format remains:

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

This stays the preferred model output and the primary format shown in prompts, docs, and examples.

### Fallback protocol

A single fallback form remains supported:

```text
read({"file_path":"README.md"})
```

The same applies to other built-in tools such as `pwd({})`, `glob({...})`, `grep({...})`, `edit({...})`, and `shell({...})`.

This fallback should only be interpreted when no canonical `<tool_call>` block is present.

### Expected behavior

The parser should make these states explicit:

- no tool call present → treat as final answer;
- canonical tool call present and valid → execute it;
- fallback tool call present and valid → execute it;
- canonical tool call malformed → correction path;
- fallback tool call malformed → correction path;
- unknown function-style text → final answer, not a tool call.

### Recovery behavior

If the model outputs malformed tool syntax, the agent loop should continue to append a correction message and retry, instead of failing the whole turn.

That correction message should include:

- the exact parse error,
- the canonical expected format,
- the instruction to either retry with one valid tool call or provide a final answer.

## Enhancement 2: Structured Tool Results

### Contract shape

Tool results remain session text, but should behave like a stable interface.

#### Success contract

For non-shell tools:

```text
status: ok
tool: read
output:
<tool output>
```

#### Error contract

For non-shell tools:

```text
status: error
tool: read
message: <error message>
```

### Shell contract

Shell remains richer because its output naturally has multiple channels.

#### Shell success

```text
status: ok
tool: shell
exit_code: 0
stdout:
<stdout>

stderr:
<stderr>
```

#### Shell non-zero exit

```text
status: error
tool: shell
exit_code: 101
stdout:
<stdout>

stderr:
<stderr>
```

#### Shell timeout

```text
status: error
tool: shell
timeout: true
message: command timed out after 1s
stdout:
<stdout if available>

stderr:
<stderr if available>
```

### Why text envelopes remain correct for now

This project still wants to stay understandable and compact. Structured text is currently the best trade-off:

- the model can read it,
- the session model does not need to change,
- tests remain straightforward,
- the format is easy to demonstrate.

## Enhancement 3: Observability

Verbose mode should expose the three main boundaries of the loop.

### Parser trace

```text
[tool parse error] tool call JSON is invalid: ...
```

### Step trace

```text
[tool step 1/8] read {"file_path":"README.md"}
```

### Result trace

Examples:

```text
[tool result] ok
[tool result] error: message: tool execution denied by user
[tool result] error: exit_code: 101
```

These traces should remain concise and should never be added to the session. They are terminal diagnostics only.

## File Responsibilities

### `src/agent/tool_call.rs`

Own the parsing rules and the precedence between canonical and fallback syntax.

### `src/agent/loop.rs`

Own the behavioral states:

- parse success,
- parse failure,
- permission denial,
- tool success,
- tool failure,
- verbose trace.

### `src/tools/builtin/shell.rs`

Own rich shell output formatting.

### `tests/agent/test_tool_call_parser.rs`

Own parser contract coverage.

### `tests/agent/test_agent_loop.rs`

Own recovery and in-band error behavior.

### `tests/tools/test_write_edit_shell.rs`

Own shell envelope behavior and shell timeout expectations.

## Testing Strategy

### Parser tests

Keep or add tests for:

- canonical wrapped tool calls,
- canonical tool calls with surrounding text,
- fallback function-style calls,
- malformed fallback JSON,
- unknown fallback tool names,
- no tool call output.

### Tool-result tests

Keep or add tests for:

- shell success envelope,
- shell timeout envelope,
- non-shell structured success and error envelopes where relevant.

### Loop tests

Keep or add tests for:

- parser fallback call accepted,
- permission denial recovery,
- shell success path,
- final-answer return after structured tool results.

## Success Criteria

This enhancement is complete when:

- the canonical and fallback tool-call behavior are easy to explain and stable in tests;
- tool results have a consistent contract across success and error paths;
- shell results carry enough structured detail for debugging and model reasoning;
- verbose mode shows useful execution trace without affecting session state;
- the project remains small and understandable.

## Why This Is Worth Doing

This work gives the project one of the most valuable “small but real” differentiators for a résumé-worthy project:

- the system is not just a CLI wrapper around an API,
- it has a real tool-calling protocol,
- it can recover from malformed model output,
- it exposes execution details clearly enough to reason about.

That makes the project easier to demo, easier to explain, and easier to defend technically in an interview or project discussion.
