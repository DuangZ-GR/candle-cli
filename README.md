# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)

[English](README.md) | [中文](README_CN.md)

Rust-first agentic CLI with multi-agent coordination, layered memory, sandboxed execution, and observability. Inspired by candle's lightweight AI runtime philosophy.

## Highlights

- **Agentic tool loop** — bounded multi-step execution with sub-agent task delegation
- **Streaming output** — real-time token-by-token display as the model generates
- **Layered memory** — session memory + project-level persistent memory
- **Sandboxed shell** — optional Docker container isolation with network cutoff
- **Multi-model** — DeepSeek, Ollama, vLLM, OpenAI via persistent Python bridge
- **Permission control** — four modes with path boundary enforcement and interactive confirmation
- **Observability** — `/tools`, `/status` (with token estimation), `/trace` (with millisecond timing and JSON export)
- **Fault tolerance** — API retry with exponential backoff (4xx not retried), shell timeout with kill
- **Rust core + Python bridge** — Rust owns CLI, agent loop, tools, permissions; Python bridges model backends with persistent worker

## Quickstart

Requirements: Rust stable and Python 3.10 or newer. Install Python bridge
dependencies with `python -m pip install -r requirements.txt` when using the
bridge runtime.

```bash
git clone https://github.com/DuangZ-GR/candle-cli.git
cd candle-cli
cargo build
```

### Recommended: DeepSeek API

```bash
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_DEEPSEEK_API_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

cargo run -- prompt "Read README.md and summarize this project"
cargo run --
```

### Local fallback: Ollama

```bash
ollama pull qwen2:0.5b

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="http://localhost:11434/v1"
export CANDLE_CLI_API_KEY="ollama"
export CANDLE_CLI_MODEL_ID="qwen2:0.5b"

cargo run -- prompt "Hello, introduce yourself"
```

> Small models (0.5B–3B) may not reliably follow the tool-call protocol. Use 7B+ or API models for agentic tasks.

## Usage

| Command | Purpose |
|---------|---------|
| `cargo run -- prompt "..."` | One-shot prompt and exit |
| `cargo run --` | Interactive REPL with readline editing |
| `cargo run -- harness` | Run automated scenario benchmark |
| `cargo run -- doctor` | Print runtime status |

### REPL commands

| Command | Alias | Purpose |
|---------|-------|---------|
| `/help` | `/h` | Show available commands |
| `/exit` | `/quit`, `/q` | Exit and save session |
| `/session` | `/info` | Show session metadata |
| `/status` | | Show runtime, model, permission status |
| `/tools` | | List registered tools |
| `/trace` | | Show execution trace with timing; `--json` for structured export |
| `/system` | | Show active system prompt |
| `/name <label>` | | Name current session |
| `/memory` | | Manage project memory (file/cmd/note subcommands) |
| `/clear` | | Clear current session |
| `/list` | `/ls` | List saved sessions |
| `/resume <id>` | | Resume a saved session |
| `/save` | | Save current session |

## Agentic system

### Tool call protocol

Models request tools via text JSON blocks:

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Rust parses the block, executes the tool, records the result in session, and feeds it back to the model. The loop continues until the model produces a final answer or reaches the maximum step count (8). A fallback parser also accepts function-style calls: `read({"file_path":"README.md"})`.

### Available tools

| Tool | Input | Purpose | Mutates |
|------|-------|---------|---------|
| `pwd` | `{}` | Show workspace directory | No |
| `read` | `{"file_path":"README.md"}` | Read a UTF-8 file (path boundary enforced) | No |
| `glob` | `{"pattern":"src/**/*.rs"}` | Find files by pattern | No |
| `grep` | `{"pattern":"fn main","path":"src"}` | Search file contents recursively | No |
| `web_search` | `{"query":"today weather"}` | Web search via DuckDuckGo/Sogou fallback | No |
| `task` | `{"description":"analyze this code"}` | Delegate to read-only sub-agent (3-step loop) | No |
| `write` | `{"file_path":"report.txt","content":"..."}` | Write a UTF-8 file inside the workspace | **Yes** |
| `edit` | `{"file_path":"Cargo.toml","old_string":"0.1.0","new_string":"0.3.0"}` | Replace exactly one text occurrence | **Yes** |
| `shell` | `{"command":"cargo test"}` | Run shell command with timeout | **Possible** |

### Permission modes

| Mode | Behavior |
|------|----------|
| `read-only` | Allow `pwd`, `read`, `glob`, `grep` only |
| `workspace-write` (default) | Allow workspace file edits; require confirmation for host shell commands |
| `prompt` | Auto-allow read tools; confirm `edit`, `write`, `shell` interactively |
| `danger-full-access` | Allow all tools, including host shell commands, without confirmation |

### Multi-agent coordination

The `task` tool spawns a sub-agent with read-only permission and a 3-step bounded loop. The main agent can delegate code analysis, research, or verification subtasks to isolated sub-agents and receive structured results.

### Layered memory

- **Session memory**: dialogue history persisted as JSON, supports list/resume/clear
- **Project memory**: `.candle-cli/memory.json` stores key files, common commands, and free-form notes; automatically injected into system prompt

```bash
/memory file src/main.rs
/memory cmd cargo test
/memory note build=takes ~5s on 4090
```

### Sandboxed execution

Set `CANDLE_CLI_SANDBOX=docker` to run shell commands in an isolated Alpine container with read-only workspace mount and network disabled.

### Fault tolerance

- API retry with exponential backoff (3 attempts, 1s/2s/4s, 4xx not retried)
- Shell timeout with SIGKILL (configurable via `CANDLE_CLI_SHELL_TIMEOUT_SECS`)

### RAG pre-search

Before each turn, the context builder extracts keywords from the user message, runs grep against `src/`, and injects matching code snippets into the prompt. Greetings and chat messages are automatically detected and skipped.

### Observability

- `/tools` — system capability boundary
- `/status` — runtime snapshot (session, model, permission, configuration)
- `/trace` — execution chain with per-step millisecond timing; `--json` for structured analysis

### Harness

```bash
cargo run -- harness
```

Runs four predefined scenarios (read, glob, grep, shell) and produces a pass/fail report with timing, tool step counts, and a `harness_report.json` output.

## Model backends

Set `CANDLE_CLI_RUNTIME=bridge` for real model calls (default `mock` for testing).

| Backend | `CANDLE_CLI_API_BASE_URL` | `CANDLE_CLI_API_KEY` | `CANDLE_CLI_MODEL_ID` |
|---------|---------------------------|----------------------|-----------------------|
| DeepSeek | `https://api.deepseek.com/v1` | `YOUR_DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| Ollama | `http://localhost:11434/v1` | `ollama` | `qwen2:0.5b` |
| vLLM | `http://localhost:8000/v1` | `not-needed` | `Qwen/Qwen2-0.5B-Instruct` |
| OpenAI | `https://api.openai.com/v1` | `sk-xxx` | `gpt-4o-mini` |

### Local transformers model

```bash
python3 -m pip install -r requirements.txt

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"
export CANDLE_CLI_MODEL_DEVICE="cpu"
export CANDLE_CLI_LOCAL_FILES_ONLY="false"

cargo run -- prompt "Hello"
```

### Verbose diagnostics

Set `CANDLE_CLI_VERBOSE=1` for API request details, token usage, timing, and GPU memory diagnostics on stderr.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `CANDLE_CLI_RUNTIME` | `mock` | `mock` or `bridge` |
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | Model ID or local path |
| `CANDLE_CLI_MODEL_DEVICE` | auto | `cpu`, `cuda`, or `auto` |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | Use only local files (no download) |
| `CANDLE_CLI_API_BASE_URL` | (empty) | OpenAI-compatible API base URL |
| `CANDLE_CLI_API_KEY` | (empty) | API key |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | Max generated tokens per turn |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | Sampling temperature |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p sampling |
| `CANDLE_CLI_SYSTEM_PROMPT` | built-in | Override system prompt |
| `CANDLE_CLI_MAX_TURNS` | `20` | Max retained conversation turns |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | Permission mode |
| `CANDLE_CLI_PERMISSION_RESPONSE` | (empty) | Pre-set prompt responses (`y`/`allow`/`deny`) |
| `CANDLE_CLI_SHELL_TIMEOUT_SECS` | `30` | Shell command timeout (seconds) |
| `CANDLE_CLI_MAX_TOOL_OUTPUT_CHARS` | `65536` | Maximum tool-result characters retained in model/session context |
| `CANDLE_CLI_ALLOW_STUB_FALLBACK` | `false` | Enable echo-only bridge stub for demos/tests; never enable for real agent tasks |
| `CANDLE_CLI_SANDBOX` | (empty) | Set to `docker` for container isolation |
| `CANDLE_CLI_VERBOSE` | `false` | Print diagnostics to stderr |
| `CANDLE_CLI_MODEL_CONFIG` | (empty) | Optional JSON config file path |
| `CANDLE_CLI_SESSION_DIR` | system temp dir | Session storage directory |

## Examples

```bash
# Standalone inference tests
python3 examples/api_inference.py
python3 examples/qwen3_local_inference.py

# Multi-step agentic task
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

cargo run -- prompt "Read src/tools/registry.rs and summarize the tool dispatch logic"

# Harness benchmark
cargo run -- harness
```

## Development

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
python3 -m pytest python/test_bridge_runtime.py -q
```

## License

MIT
