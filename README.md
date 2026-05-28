# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)

Rust-first terminal AI assistant for DeepSeek API, local model backends, persistent sessions, and agent-style tool use.

## Highlights

- **Terminal-native AI chat**: one-shot prompts and multi-turn REPL.
- **DeepSeek-first API mode**: works with OpenAI-compatible chat completion APIs.
- **Local fallback**: run through Ollama, vLLM, or local `transformers` models.
- **Persistent sessions**: save, list, resume, and clear conversations.
- **Agent tool loop**: read, search, edit, and shell tools with configurable permissions.
- **Rust core + Python bridge**: small CLI surface with flexible model execution.

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

cargo run -- prompt "你好，介绍一下你自己"
cargo run --
```

If DeepSeek publishes a different model ID, replace `deepseek-v4-flash` with the ID shown in the DeepSeek console or official docs.

### Local fallback: Ollama

```bash
ollama pull qwen2:0.5b

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="http://localhost:11434/v1"
export CANDLE_CLI_API_KEY="ollama"
export CANDLE_CLI_MODEL_ID="qwen2:0.5b"

cargo run -- prompt "你好，介绍一下你自己"
```

## Usage

| Command | Purpose |
|---------|---------|
| `cargo run -- prompt "your question"` | Run one prompt and exit. |
| `cargo run --` | Start the interactive REPL. |
| `cargo run -- doctor` | Print runtime and configuration status. |

### REPL commands

| Command | Purpose |
|---------|---------|
| `/help`, `/h` | Show available commands. |
| `/exit`, `/quit`, `/q` | Exit and save the session. |
| `/session`, `/info` | Show current session metadata. |
| `/system` | Show the active system prompt. |
| `/clear` | Clear the current session. |
| `/list`, `/ls` | List saved sessions. |
| `/resume <id>` | Resume a saved session. |
| `/save` | Save the current session now. |

## Model backends

`candle-cli` uses the Python bridge runtime for real model calls. Set `CANDLE_CLI_RUNTIME=bridge`, then choose either an OpenAI-compatible API or a local model path.

### OpenAI-compatible APIs

| Backend | `CANDLE_CLI_API_BASE_URL` | `CANDLE_CLI_API_KEY` | `CANDLE_CLI_MODEL_ID` |
|---------|---------------------------|----------------------|-----------------------|
| DeepSeek | `https://api.deepseek.com/v1` | `YOUR_DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| Ollama | `http://localhost:11434/v1` | `ollama` | `qwen2:0.5b` |
| vLLM | `http://localhost:8000/v1` | `not-needed` | `Qwen/Qwen2-0.5B-Instruct` |
| OpenAI | `https://api.openai.com/v1` | `sk-xxx` | `gpt-4o-mini` |

### Local `transformers` model

```bash
python3 -m pip install -r requirements.txt

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"
export CANDLE_CLI_MODEL_DEVICE="cpu"
export CANDLE_CLI_LOCAL_FILES_ONLY="false"

cargo run -- prompt "你好"
```

## Agent tools and permissions

Models can request tools by emitting text JSON tool calls:

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Available tools:

| Tool | Purpose |
|------|---------|
| `pwd` | Show the workspace directory. |
| `read` | Read UTF-8 files inside the workspace. |
| `glob` | Match files by glob pattern. |
| `grep` | Search file contents. |
| `edit` | Replace one exact text match in a file. |
| `shell` | Run a shell command from the workspace root. |

Control tool execution with `CANDLE_CLI_PERMISSION`:

| Mode | Behavior |
|------|----------|
| `read-only` | Allow only `pwd`, `read`, `glob`, and `grep`. |
| `workspace-write` | Allow all current tools without asking. |
| `prompt` | Auto-allow read tools; confirm `edit`, `write`, and `shell`. |
| `danger-full-access` | Allow all current tools without asking. |

```bash
CANDLE_CLI_PERMISSION=read-only cargo run -- prompt "读取 README.md 并总结"
CANDLE_CLI_PERMISSION=prompt cargo run -- prompt "运行 cargo test 并总结失败原因"
```

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `CANDLE_CLI_RUNTIME` | `mock` | Runtime type: `mock` or `bridge`. |
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | Model ID or local model path. |
| `CANDLE_CLI_MODEL_DEVICE` | auto | Device: `cpu`, `cuda`, or `auto`. |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | Use only local model files. |
| `CANDLE_CLI_API_BASE_URL` | empty | OpenAI-compatible API base URL. |
| `CANDLE_CLI_API_KEY` | empty | API key for remote backends. |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | Maximum generated tokens. |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | Sampling temperature. |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p sampling. |
| `CANDLE_CLI_SYSTEM_PROMPT` | built-in | Override the system prompt. |
| `CANDLE_CLI_MAX_TURNS` | `20` | Maximum retained conversation turns. |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | Tool permission mode. |
| `CANDLE_CLI_VERBOSE` | `false` | Print bridge diagnostics to stderr. |
| `CANDLE_CLI_MODEL_CONFIG` | empty | Optional JSON config file path. |
| `CANDLE_CLI_SESSION_DIR` | system temp dir | Session storage directory. |

## Examples

```bash
python3 examples/api_inference.py
python3 examples/qwen3_local_inference.py
```

- `examples/api_inference.py`: test an OpenAI-compatible API backend.
- `examples/qwen3_local_inference.py`: test a local `transformers` model.

## Development

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
python3 -m pytest python/test_bridge_runtime.py -q
```

## License

MIT
