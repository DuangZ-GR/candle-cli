# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)

[English](README.md) | [中文](README_CN.md)

Rust-first terminal AI assistant with agentic coding — read, search, edit, run commands through a multi-step tool loop.

## Highlights

- **Agentic tool loop** — read → edit → shell → answer, bounded by max step count
- **DeepSeek-first** — optimized for DeepSeek API; compatible with any OpenAI-compatible endpoint
- **Persistent sessions** — save, list, resume, and clear conversations
- **Configurable permissions** — `read-only`, `workspace-write`, `prompt`, `danger-full-access`
- **REPL + Prompt** — interactive multi-turn REPL and one-shot prompt mode
- **Rust core + Python bridge** — Rust owns CLI, session, tools, agent loop; Python handles model inference

## Quickstart

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

# One-shot prompt
cargo run -- prompt "Read README.md and summarize this project"

# Interactive REPL
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
| `cargo run -- prompt "..."` | Run one prompt and exit |
| `cargo run --` | Start interactive REPL |
| `cargo run -- doctor` | Print runtime and configuration status |

### REPL commands

| Command | Alias | Purpose |
|---------|-------|---------|
| `/help` | `/h` | Show available commands |
| `/exit` | `/quit`, `/q` | Exit and save session |
| `/session` | `/info` | Show current session metadata |
| `/status` | | Show runtime, model, and permission status |
| `/tools` | | List registered tools |
| `/trace` | | Show last turn's execution trace |
| `/system` | | Show active system prompt |
| `/clear` | | Clear current session |
| `/list` | `/ls` | List saved sessions |
| `/resume <id>` | | Resume a saved session |
| `/save` | | Save current session |

## Agentic tool loop

Models can request tools by emitting text JSON tool calls:

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Rust parses the block, executes the tool, records the result in the session, and calls the model again. The loop repeats until the model produces a final answer without a tool call, or reaches the maximum step count (8).

### Available tools

| Tool | Input | Purpose | Mutates |
|------|-------|---------|---------|
| `pwd` | `{}` | Show workspace directory | No |
| `read` | `{"file_path":"README.md"}` | Read a UTF-8 file | No |
| `glob` | `{"pattern":"src/**/*.rs"}` | Find files by pattern | No |
| `grep` | `{"pattern":"fn main","path":"src"}` | Search file contents | No |
| `edit` | `{"file_path":"Cargo.toml","old_string":"0.1.0","new_string":"0.3.0"}` | Replace exactly one text occurrence | **Yes** |
| `shell` | `{"command":"cargo test"}` | Run a shell command | **Possible** |

### Permission modes

Control via `CANDLE_CLI_PERMISSION`:

| Mode | Behavior |
|------|----------|
| `read-only` | Allow `pwd`, `read`, `glob`, `grep` only |
| `workspace-write` (default) | Allow all tools without confirmation |
| `prompt` | Auto-allow read tools; confirm `edit`, `write`, `shell` |
| `danger-full-access` | Allow all tools without confirmation |

## Model backends

Set `CANDLE_CLI_RUNTIME=bridge` to enable real model calls (default is `mock` for testing).

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

Set `CANDLE_CLI_VERBOSE=1` to see API details, token usage, and timing on stderr:

```text
[candle-cli] API call: POST https://api.deepseek.com/v1/chat/completions
[candle-cli]   messages: 4 (system=True)
[candle-cli]   model: deepseek-v4-pro
[candle-cli]   max_tokens: 2048
[candle-cli]   response in 1.5s
[candle-cli]   tokens: prompt=599 completion=35 total=634
```

## Configuration

All configuration via environment variables.

| Variable | Default | Purpose |
|----------|---------|---------|
| `CANDLE_CLI_RUNTIME` | `mock` | `mock` or `bridge` |
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | Model ID or local path |
| `CANDLE_CLI_MODEL_DEVICE` | auto | `cpu`, `cuda`, or `auto` |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | Use only local model files |
| `CANDLE_CLI_API_BASE_URL` | (empty) | OpenAI-compatible API base URL |
| `CANDLE_CLI_API_KEY` | (empty) | API key |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | Max generated tokens per turn |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | Sampling temperature |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p sampling |
| `CANDLE_CLI_SYSTEM_PROMPT` | built-in | Override system prompt |
| `CANDLE_CLI_MAX_TURNS` | `20` | Max retained conversation turns |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | Tool permission mode |
| `CANDLE_CLI_SHELL_TIMEOUT_SECS` | `30` | Shell command timeout (seconds) |
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

cargo run -- prompt "\
1. Read src/tools/registry.rs
2. Add a new tool called 'echo' that repeats its input
3. Run cargo test to verify nothing broke
4. Summarize what you changed"
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
