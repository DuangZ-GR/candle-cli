# Minimal Agentic Coding Loop Design

**Date:** 2026-05-09

## Goal

Implement the first complete coding-agent loop for `candle-cli`: user asks for a task, the model can request tools, Rust executes those tools, tool results are added back to the session, and the model continues until it produces a final answer.

The v0.3.0 target is the smallest useful loop that can support:

1. read/search project files,
2. edit existing files,
3. run tests or shell commands,
4. summarize what happened.

This moves the project from a chat CLI with session persistence into a minimal coding-agent MVP.

## Confirmed Scope

### In scope

- Text-based JSON tool-call protocol.
- Multi-step agent loop with a fixed maximum step count.
- First-class execution for these tools:
  - `pwd`
  - `read`
  - `glob`
  - `grep`
  - `edit`
  - `shell`
- Session recording for assistant tool calls and tool results.
- Prompt-mode and REPL-mode integration.
- Mock-runtime tests that prove the loop works end-to-end.
- Bridge/model prompt guidance so real models know how to emit tool calls.

### Out of scope

- Native OpenAI-compatible `tools` schema.
- Streaming.
- Parallel tool calls.
- Interactive permission prompts.
- Full sandboxing.
- New `write` behavior.
- Candle-native inference.
- Long-lived Python bridge worker.
- GitHub Actions CI.

## Recommended Approach

Use a text JSON protocol embedded in model output:

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Rust parses this block into a `ToolCallIntent`, executes it through `ToolRegistry`, records the result in the session, then calls the runtime again.

This approach is preferred over native API tool calling because it works with mock runtimes, Ollama, vLLM, OpenAI-compatible APIs, and local transformers without requiring backend-specific tool support.

## Runtime Contract

The runtime can return either:

1. final assistant text, or
2. a single tool call encoded as a `<tool_call>...</tool_call>` block.

For v0.3.0, only one tool call per model turn is supported. If multiple tool-call blocks are present, the loop handles the first valid block and treats the rest as ignored text. This keeps the implementation small and deterministic.

A final answer is any runtime output that does not contain a valid tool-call block.

## Agent Loop

The current `run_single_turn` flow is single-shot. It should become a bounded multi-step loop:

```text
for step in 0..max_steps:
    build TurnRequest from session and tools_json
    call runtime.generate_turn(request)

    if response contains a valid tool call:
        append assistant ToolCall message
        execute tool through ToolRegistry
        append ToolResult message
        continue

    append assistant final text
    return

append assistant error/final text explaining max steps were reached
```

Default `max_steps` should be 8. This avoids infinite tool loops while allowing enough turns for read → edit → shell → final answer.

## Tool Protocol

### Tool call format

```json
{
  "id": "call-1",
  "name": "read",
  "input": {
    "file_path": "README.md"
  }
}
```

### Rust representation

```rust
ToolCallIntent {
    id: "call-1".to_string(),
    name: "read".to_string(),
    input_json: "{\"file_path\":\"README.md\"}".to_string(),
}
```

The parser should reject malformed JSON, missing `id`, missing `name`, non-object `input`, and unknown outer structure. Tool existence is checked by `ToolRegistry` during execution.

## Tool Implementations

### `pwd`

Already implemented. Returns the current working directory.

### `read`

Implement real file reading. Input:

```json
{"file_path":"README.md"}
```

Returns file contents as UTF-8 text. Errors if the path is missing, unreadable, not a file, or not valid UTF-8.

### `glob`

Implement file matching. Input:

```json
{"pattern":"src/**/*.rs"}
```

Returns newline-separated matching paths. Keep results deterministic by sorting paths.

### `grep`

Implement text search. Input:

```json
{"pattern":"run_single_turn","path":"src"}
```

Returns matching lines with path and line number. The first version may use simple substring matching rather than full regex if that keeps the implementation dependency-free. If regex support is already available or cheap through existing dependencies, use regex.

### `edit`

Keep the existing string-replacement model but make the registry input path explicit. Input:

```json
{
  "file_path":"README.md",
  "old_string":"old text",
  "new_string":"new text"
}
```

For v0.3.0, edit should fail if `old_string` is missing from the file. A stricter single-match requirement is preferred if practical, because replacing every occurrence silently can corrupt files.

### `shell`

Keep existing shell execution for workspace-write mode. Input:

```json
{"command":"cargo test"}
```

For v0.3.0, shell remains unsandboxed. Safety work is deferred, but command output should be captured and returned as the tool result.

## Permissions

v0.3.0 uses fixed `workspace-write` behavior in prompt and REPL mode. This allows `read/glob/grep/edit/shell` so the closed loop can run.

Interactive confirmation and richer permission modes are intentionally deferred. The design should keep `PermissionPolicy` compatible with future work, but not block v0.3.0 on it.

## Session Data Flow

When the model requests a tool, append an assistant message containing a `ContentBlock::ToolCall`:

```rust
Message {
    role: MessageRole::Assistant,
    blocks: vec![ContentBlock::ToolCall { id, name, input }],
}
```

After execution, append a tool message containing a `ContentBlock::ToolResult`:

```rust
Message {
    role: MessageRole::Tool,
    blocks: vec![ContentBlock::ToolResult {
        tool_call_id,
        output,
        is_error,
    }],
}
```

The next `TurnRequest` includes these session messages so the runtime can see tool output before deciding the next action.

## Prompt Guidance

The system prompt should tell the model:

- use tools when it needs to inspect files, edit files, or run commands;
- emit exactly one `<tool_call>...</tool_call>` block when requesting a tool;
- do not mix final answer text with a tool call;
- after receiving tool results, either request another tool or provide the final answer;
- use final text when no tool is needed.

The first version can add this guidance directly to the built-in system prompt or append it in the context builder when tools are available.

## Error Handling

### Malformed tool call

If model output contains a `<tool_call>` block but the block is malformed, append an assistant message that explains the parser error and instructs the model to retry with exactly one valid `<tool_call>{...}</tool_call>` block or provide a final answer. Then continue the loop. This keeps malformed model output recoverable without inventing a fake tool result ID.

### Tool execution error

If a tool returns `Err`, append a `ToolResult` with `is_error: true` and the error text. Continue the loop so the model can decide whether to recover or explain the failure.

### Step limit reached

If `max_steps` is reached, append a final assistant message explaining that the tool loop stopped after the maximum number of steps and include the latest state briefly.

## Testing Strategy

### Unit tests

- Parse a valid `<tool_call>` block.
- Reject malformed JSON.
- Reject missing `id`, `name`, or invalid `input`.
- Real `read` returns file contents.
- Real `glob` returns deterministic matches.
- Real `grep` returns path and line numbers.
- `edit` changes an existing file and fails when the old string is absent.

### End-to-end Rust tests with mock runtime

Add a scripted mock runtime that returns a sequence of responses:

1. request `read`,
2. inspect tool result and request `edit`,
3. request `shell`,
4. final answer.

The test should verify:

- file content changed,
- shell command ran,
- session contains user, assistant tool call, tool result, and final assistant messages,
- loop stops on final answer,
- max-step guard prevents infinite loops.

### Existing verification commands

Before merging v0.3.0 work, run:

```bash
python3 -m pytest python/test_bridge_runtime.py -q
~/.cargo/bin/cargo test
~/.cargo/bin/cargo fmt --check
~/.cargo/bin/cargo clippy --all-targets --all-features -- -D warnings
```

## Acceptance Criteria

v0.3.0 is complete when:

- `read`, `glob`, and `grep` are real tools, not stubs.
- The agent loop can execute at least one tool call and continue generation.
- The agent loop can complete a read → edit → shell → final-answer sequence in tests.
- Tool calls and tool results are persisted in session messages.
- Prompt mode and REPL mode use the multi-step loop.
- Existing tests still pass.
- New tests cover parser, tools, loop success, tool error, and max-step behavior.

## Deferred Follow-up Work

After v0.3.0, likely next steps are:

- interactive permission confirmation,
- workspace path guards,
- shell timeout and safer command policy,
- OpenAI-compatible native tool schema,
- streaming output,
- long-lived Python bridge worker,
- better edit semantics and diff display,
- GitHub Actions CI when a token with `workflow` scope is available.
