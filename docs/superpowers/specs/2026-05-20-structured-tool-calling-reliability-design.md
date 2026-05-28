# Structured Tool Calling Reliability Design

**Date:** 2026-05-20

## Goal

Improve the existing `candle-cli` tool-calling loop from a minimal working MVP into a more reliable, diagnosable, and demonstration-ready agent workflow.

This enhancement focuses on the current text-based `<tool_call>...</tool_call>` protocol and existing tools. It does not introduce a new agent framework, native OpenAI tool schemas, streaming, parallel tool calls, or new model backends.

The target outcome is simple:

- model tool-call formatting mistakes are easier to recover from;
- tool execution results are easier for both the model and user to understand;
- verbose mode makes the agent loop observable without changing normal output.

## Current Context

The project already has the core agent path:

1. user input is stored in the session;
2. `build_turn_request` creates a runtime request with tool protocol guidance;
3. the runtime generates either final text or a `<tool_call>...</tool_call>` block;
4. `parse_tool_call` converts model output into `ToolCallIntent`;
5. `ToolRegistry` executes the requested tool;
6. tool results are appended to the session;
7. the loop continues until the runtime returns a final answer or reaches the step limit.

Relevant current modules:

- `src/agent/tool_call.rs`
- `src/agent/loop.rs`
- `src/context/builder.rs`
- `src/tools/registry.rs`
- `src/tools/builtin/*.rs`
- `src/ui/*`
- `tests/agent/*`
- `tests/tools/*`

## Scope

### In scope

This work is split into three incremental stages.

#### Stage 1: Tool-call parsing reliability

- Keep `<tool_call>{...}</tool_call>` as the primary model protocol.
- Keep the existing fallback parser for known function-style calls such as `read({"file_path":"README.md"})` and `pwd({})`.
- Make parser behavior explicit for malformed tool calls, missing fields, non-object input, and mixed surrounding text.
- Improve correction messages sent back to the model after parser errors.
- Strengthen prompt guidance so real models are less likely to emit Markdown fences, pseudo function calls, or empty final answers.
- Add parser and agent-loop tests for common real-model mistakes.

#### Stage 2: Structured tool results

- Keep the session schema unchanged by continuing to store tool output as text.
- Format tool outputs with a lightweight text envelope.
- Represent tool errors consistently with `status: error` text and `is_error: true` in the session.
- Improve shell output so stdout, stderr, exit code, and timeout are visible.
- Keep tool execution failures inside the agent loop so the model can recover or explain the failure.

#### Stage 3: Agent-loop observability

- Add verbose-only trace output for each tool step.
- Show the step number, maximum step count, tool name, compact input JSON, and result status.
- Keep normal non-verbose output concise and unchanged.
- Do not write trace lines into the session; they are UI diagnostics only.

### Out of scope

- Native OpenAI-compatible tool schemas.
- Parallel tool calls.
- Streaming tool-call parsing.
- Web UI traces or JSON log files.
- New tools beyond the current `pwd`, `read`, `glob`, `grep`, `edit`, and `shell` set.
- Full sandboxing redesign.
- Candle-native inference changes.
- Session schema migration.

## Architecture

The existing data flow remains unchanged:

```text
User input
  -> Session
  -> build_turn_request(session, tools_json)
  -> runtime.generate_turn(request)
  -> parse_tool_call(model_output)
  -> ToolRegistry.execute(...)
  -> append ToolResult
  -> runtime.generate_turn(...)
  -> final answer
```

The enhancement adds reliability at three existing boundaries:

1. **model output to `ToolCallIntent`** through stricter parser behavior and better correction prompts;
2. **tool execution to session result** through a consistent text result envelope;
3. **agent loop to terminal UI** through verbose trace lines.

No new high-level loop abstraction is required. The current bounded loop in `src/agent/loop.rs` should remain the coordinator.

## Stage 1 Design: Parser Reliability

`src/agent/tool_call.rs` remains responsible for parsing runtime output into `ToolCallIntent`.

The parser should make these outcomes explicit:

- no tool call present: `Ok(None)`;
- one valid wrapped tool call: `Ok(Some(ToolCallIntent))`;
- wrapped tool call with malformed JSON: `Err(ToolCallParseError::InvalidJson(_))`;
- wrapped tool call with missing `id` or `name`: `Err(ToolCallParseError::MissingStringField(_))`;
- wrapped tool call with missing or non-object `input`: `Err(ToolCallParseError::InputMustBeObject)`;
- wrapped tool call with non-object outer JSON: `Err(ToolCallParseError::OuterMustBeObject)`;
- known fallback function-style call with object JSON: `Ok(Some(ToolCallIntent))`;
- unknown function-style output: `Ok(None)`.

Mixed surrounding text should keep the current behavior: if a valid `<tool_call>...</tool_call>` block exists, parse the first block. This preserves compatibility with real models that add short prose despite the prompt. Prompt guidance should still tell the model not to do this.

Malformed wrapped tool calls should produce a clearer correction message in the agent loop. The message should include:

- the parse failure reason;
- the expected exact protocol;
- one concrete example;
- the instruction to retry with one valid tool call or provide a final answer.

The correction message can continue to be appended as assistant text. A new session block type is unnecessary for this iteration.

## Stage 2 Design: Structured Tool Results

Tool results should remain text so existing session persistence continues to work.

Use this envelope for successful non-shell tools:

```text
status: ok
tool: read
output:
<tool output>
```

Use this envelope for failed non-shell tools:

```text
status: error
tool: read
message: <error message>
```

Shell should expose process details:

```text
status: ok
tool: shell
exit_code: 0
stdout:
<stdout>

stderr:
<stderr>
```

For non-zero exit codes:

```text
status: error
tool: shell
exit_code: 101
stdout:
<stdout>

stderr:
<stderr>
```

For timeouts:

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

The loop should preserve the distinction between runtime errors and tool errors:

- runtime errors return `Err` because the model did not produce usable output;
- parser errors are fed back to the model as correction context;
- permission errors become tool results with `is_error: true`;
- tool execution errors become tool results with `is_error: true`.

This keeps the agent capable of recovering from file errors, permission denials, edit mismatches, command failures, and timeouts.

## Stage 3 Design: Verbose Trace

Verbose trace is terminal UI only. It should not be appended to the session.

In verbose mode, each tool step should print a compact trace similar to:

```text
[tool step 1/8] read {"file_path":"README.md"}
[tool result] ok
[tool step 2/8] shell {"command":"cargo test"}
[tool result] error: exit_code 101
```

For permission denials:

```text
[tool result] denied: tool not allowed in read-only mode: shell
```

For parser errors:

```text
[tool parse error] tool call JSON is invalid: ...
```

The first version should not print full tool output in the trace. Full output is already stored in the session and can be summarized by the final answer. Keeping traces compact avoids noisy terminals.

## Error Handling

### Parser errors

Parser errors should not terminate the loop. They should append a correction message and continue until the model retries successfully, provides a final answer, or reaches the maximum step limit.

### Permission errors

Permission errors should append a tool result with `is_error: true`. The model can then explain the limitation or choose a read-only alternative.

### Tool execution errors

Tool execution errors should append a structured error result with `is_error: true`. They should not become Rust-level loop errors unless the loop itself cannot continue.

### Runtime errors

Runtime errors should still return `Err` from the loop because there is no model output to recover from.

### Step limit

If the loop reaches the maximum step count, it should append and return a clear final message such as:

```text
stopped after reaching maximum tool steps (8)
```

## Testing Strategy

### Parser tests

Add or preserve tests for:

- valid wrapped tool call;
- valid wrapped tool call with surrounding text;
- fallback function-style calls for known tools;
- unknown fallback function names returning `None`;
- malformed JSON inside `<tool_call>` returning an error;
- missing close tag;
- missing `id`;
- missing `name`;
- missing `input`;
- non-object `input`;
- non-object outer JSON;
- multiple wrapped tool calls with fixed first-block behavior.

### Tool result tests

Add or preserve tests for:

- read success includes `status: ok`;
- read failure includes `status: error`;
- edit success includes `status: ok` or an equivalent normalized success message;
- edit failure includes `status: error`;
- shell success includes `exit_code`, `stdout`, and `stderr`;
- shell non-zero exit code produces an error result;
- shell timeout produces a timeout error result.

### Agent loop tests

Add or preserve tests for:

- parser error followed by valid retry;
- tool execution error followed by final answer;
- permission denial recorded with `is_error: true`;
- maximum step count termination;
- verbose trace does not alter session content.

## Success Criteria

The enhancement is complete when:

- existing prompt and REPL workflows still work;
- malformed model tool calls produce actionable correction context instead of ending the run;
- tool failures are visible to the model as structured `status: error` results;
- shell results clearly show stdout, stderr, exit code, and timeout state;
- verbose mode shows each tool step without changing normal output;
- tests cover parser, tool-result, and agent-loop reliability paths.

## Implementation Order

1. Strengthen parser tests and correction messages.
2. Normalize non-shell tool result text.
3. Normalize shell result text and timeout behavior.
4. Add verbose trace hooks around parse, permission, execution, and result handling.
5. Run Rust formatting, clippy, and test suite.

This order keeps each change independently verifiable and avoids a large one-shot rewrite.
