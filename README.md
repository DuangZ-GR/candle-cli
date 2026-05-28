# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)

Rust-first terminal AI assistant with agentic coding capabilities — read, search, edit, and run commands through a multi-step tool loop. / 基于 Rust 的终端 AI 编程助手，具备 agentic coding 能力 — 多步工具循环：读取代码、搜索文件、编辑内容、执行命令。

---

## Table of Contents / 目录

- [Highlights / 核心特性](#highlights--核心特性)
- [Quickstart / 快速开始](#quickstart--快速开始)
- [Usage / 用法](#usage--用法)
- [REPL Commands / REPL 命令](#repl-commands--repl-命令)
- [Agentic Tool Loop / Agent 工具循环](#agentic-tool-loop--agent-工具循环)
- [Model Backends / 模型后端](#model-backends--模型后端)
- [Configuration / 配置](#configuration--配置)
- [Examples / 示例](#examples--示例)
- [Development / 开发](#development--开发)
- [License / 许可证](#license--许可证)

---

## Highlights / 核心特性

| Feature / 特性 | Description / 说明 |
|---------------|-------------------|
| **Agentic Tool Loop** / Agent 工具循环 | Multi-step read → edit → shell → answer. Bounded by max step count (8). / 多步工具循环，最大步数限制（8 步） |
| **REPL + Prompt** / 交互与单轮 | Interactive multi-turn REPL and one-shot prompt mode. / 交互式多轮对话 REPL 和单轮 prompt 模式 |
| **Persistent Sessions** / 会话持久化 | Save, list, resume, and clear conversation sessions. / 保存、列表、恢复、清空会话 |
| **DeepSeek-First** / 深度求索优先 | Optimized for DeepSeek API; compatible with any OpenAI-compatible endpoint. / 针对 DeepSeek API 优化；兼容所有 OpenAI 兼容端点 |
| **Local Fallback** / 本地后备 | Ollama, vLLM, or local `transformers` model inference. / 支持 Ollama、vLLM 或本地 transformers 模型推理 |
| **Configurable Permissions** / 可配置权限 | `read-only`, `workspace-write`, `prompt`, `danger-full-access`. / 四种权限模式 |
| **Rust Core + Python Bridge** / Rust 核心 + Python 桥接 | Clean separation: Rust owns CLI, session, tools, agent loop; Python handles model inference. / 清晰的职责分离：Rust 负责 CLI、会话、工具、agent 循环；Python 负责模型推理 |

---

## Quickstart / 快速开始

### Prerequisites / 前置条件

```bash
git clone https://github.com/DuangZ-GR/candle-cli.git
cd candle-cli
cargo build
python3 -m pip install -r requirements.txt  # for bridge runtime / 用于 bridge 运行时
```

### Recommended: DeepSeek API / 推荐方式：DeepSeek API

```bash
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_DEEPSEEK_API_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

# One-shot prompt / 单轮提问
cargo run -- prompt "请读取 README.md 并总结项目功能"

# Interactive REPL / 交互式 REPL
cargo run --
```

> If DeepSeek updates model IDs, replace `deepseek-v4-flash` with the ID shown in the DeepSeek console or official docs.
> / 如果 DeepSeek 更新模型 ID，请替换为 DeepSeek 控制台或官方文档中的实际 ID。

### Local Fallback: Ollama / 本地后备：Ollama

```bash
ollama pull qwen2:0.5b

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="http://localhost:11434/v1"
export CANDLE_CLI_API_KEY="ollama"
export CANDLE_CLI_MODEL_ID="qwen2:0.5b"

cargo run -- prompt "你好，介绍一下你自己"
```

> **Note / 注意**: Small models (0.5B–3B) may not reliably follow the tool-call protocol. Use 7B+ or API models for agentic tasks.
> / 小模型（0.5B–3B）可能无法可靠遵循工具调用协议。建议使用 7B+ 或 API 模型执行 agentic 任务。

---

## Usage / 用法

| Command / 命令 | Purpose / 用途 |
|---------------|---------------|
| `cargo run -- prompt "your question"` | Run one prompt and exit. / 单轮提问后退出 |
| `cargo run --` | Start the interactive REPL. / 启动交互式 REPL |
| `cargo run -- doctor` | Print runtime and configuration status. / 打印运行时和配置状态 |

---

## REPL Commands / REPL 命令

| Command / 命令 | Alias / 别名 | Purpose / 用途 |
|---------------|-------------|---------------|
| `/help` | `/h` | Show available commands. / 显示可用命令 |
| `/exit` | `/quit`, `/q` | Exit and save the session. / 退出并保存会话 |
| `/session` | `/info` | Show current session metadata. / 查看当前会话信息 |
| `/status` | | Show runtime, model, and permission status. / 查看运行时、模型和权限状态 |
| `/tools` | | List registered tools. / 列出已注册工具 |
| `/trace` | | Show the last turn's execution trace. / 显示上一轮的执行追踪 |
| `/system` | | Show the active system prompt. / 查看当前系统提示词 |
| `/clear` | | Clear the current session. / 清空当前会话 |
| `/list` | `/ls` | List saved sessions. / 列出已保存会话 |
| `/resume <id>` | | Resume a saved session. / 恢复指定会话 |
| `/save` | | Save the current session now. / 显式保存当前会话 |

---

## Agentic Tool Loop / Agent 工具循环

candle-cli v0.3.0 supports a bounded multi-step tool loop. / candle-cli v0.3.0 支持有界多步工具循环。

### How It Works / 工作原理

```
User / 用户: "Read README.md, edit the title, then run cargo test"
           │
           ▼
┌─────────────────────────────────────────────┐
│ 1. Model emits <tool_call>{"id":"c1","name":"read",...}</tool_call>  │
│ 2. Rust parses, executes `read`, records result in session           │
│ 3. Model emits <tool_call>{"id":"c2","name":"edit",...}</tool_call>  │
│ 4. Rust parses, executes `edit` (exact-once match), records result   │
│ 5. Model emits <tool_call>{"id":"c3","name":"shell",...}</tool_call> │
│ 6. Rust parses, executes `shell`, records result                    │
│ 7. Model emits final answer: "Done. Title updated, tests pass."     │
│ 8. Loop stops (no tool call found).                                 │
└─────────────────────────────────────────────┘
```

Max steps: **8** (configurable via `run_single_turn_with_limit`). / 最大步数：**8**（可通过 `run_single_turn_with_limit` 配置）。

### Available Tools / 可用工具

| Tool / 工具 | Input / 输入 | Purpose / 用途 | Mutates / 修改文件 |
|------------|-------------|---------------|-------------------|
| `pwd` | `{}` | Show workspace directory. / 显示工作目录 | No / 否 |
| `read` | `{"file_path":"README.md"}` | Read a UTF-8 file inside workspace. / 读取工作目录中的文件 | No / 否 |
| `glob` | `{"pattern":"src/**/*.rs"}` | Find files by pattern. / 按模式查找文件 | No / 否 |
| `grep` | `{"pattern":"fn main","path":"src"}` | Search file contents. / 搜索文件内容 | No / 否 |
| `edit` | `{"file_path":"Cargo.toml","old_string":"0.1.0","new_string":"0.3.0"}` | Replace exactly one text occurrence. / 精确替换一处文本 | **Yes / 是** |
| `shell` | `{"command":"cargo test"}` | Run a shell command. / 运行 shell 命令 | **Possible / 可能** |

### Tool Call Protocol / 工具调用协议

Models must emit tool calls in this exact format / 模型必须按以下精确格式发出工具调用：

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Rules / 规则:
1. Content between `<tool_call>` and `</tool_call>` must be valid JSON. / 标签内容必须为有效 JSON
2. JSON must have exactly 3 fields: `id`, `name`, `input` (object). / JSON 必须恰好包含 3 个字段
3. Do NOT mix tool calls with final answer text in the same message. / 工具调用和最终回答不能混在同一消息中
4. After receiving tool results, either request another tool or give the final answer. / 收到工具结果后，要么继续请求工具，要么给出最终回答

### Permission Modes / 权限模式

Control via `CANDLE_CLI_PERMISSION` / 通过 `CANDLE_CLI_PERMISSION` 控制：

| Mode / 模式 | Behavior / 行为 |
|------------|-----------------|
| `read-only` | Allow `pwd`, `read`, `glob`, `grep`. Deny `edit`, `write`, `shell`. / 仅允许只读工具 |
| `workspace-write` (default / 默认) | Allow all tools without confirmation. / 允许所有工具，无需确认 |
| `prompt` | Auto-allow read tools; confirm mutation tools. / 只读工具自动允许；修改工具需确认 |
| `danger-full-access` | Allow all tools without confirmation. / 允许所有工具，无需确认 |

### Example Agentic Task / Agentic 任务示例

```bash
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_DEEPSEEK_API_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

# Multi-step agentic task / 多步 agentic 任务
cargo run -- prompt "\
1. Read src/tools/registry.rs
2. Add a new tool called 'echo' that repeats its input
3. Run cargo test to verify nothing broke
4. Summarize what you changed"
```

---

## Model Backends / 模型后端

Set `CANDLE_CLI_RUNTIME=bridge` to enable real model calls. Default is `mock` (returns stub responses for testing). / 设置 `CANDLE_CLI_RUNTIME=bridge` 启用真实模型调用。默认值为 `mock`（返回存根响应用于测试）。

### OpenAI-Compatible APIs / OpenAI 兼容 API

| Backend / 后端 | `CANDLE_CLI_API_BASE_URL` | `CANDLE_CLI_API_KEY` | `CANDLE_CLI_MODEL_ID` |
|---------------|---------------------------|----------------------|-----------------------|
| DeepSeek / 深度求索 | `https://api.deepseek.com/v1` | `YOUR_DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| Ollama | `http://localhost:11434/v1` | `ollama` | `qwen2:0.5b` |
| vLLM | `http://localhost:8000/v1` | `not-needed` | `Qwen/Qwen2-0.5B-Instruct` |
| OpenAI | `https://api.openai.com/v1` | `sk-xxx` | `gpt-4o-mini` |

### Local Transformers Model / 本地 Transformers 模型

```bash
python3 -m pip install -r requirements.txt

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"
export CANDLE_CLI_MODEL_DEVICE="cpu"
export CANDLE_CLI_LOCAL_FILES_ONLY="false"

cargo run -- prompt "你好"
```

> **Note / 注意**: The bridge spawns a new Python process for each turn. Local model loading can be slow without model caching. Long-lived worker connections are planned for v0.4.0.
> / Bridge 每次对话都启动新的 Python 子进程。本地模型加载可能较慢。长连接 worker 计划在 v0.4.0 实现。

### Verbose Diagnostics / 诊断输出

Set `CANDLE_CLI_VERBOSE=1` to see API request details, token usage, and timing on stderr:

```text
[candle-cli] API mode active, skipping local model load
[candle-cli]   api_base_url: https://api.deepseek.com/v1
[candle-cli] API call: POST https://api.deepseek.com/v1/chat/completions
[candle-cli]   messages: 4 (system=True)
[candle-cli]   model: deepseek-v4-pro
[candle-cli]   max_tokens: 2048
[candle-cli]   response in 1.5s
[candle-cli]   tokens: prompt=599 completion=35 total=634
```

---

## Configuration / 配置

All configuration is driven by environment variables. No config file required. / 所有配置通过环境变量驱动，无需配置文件。

| Variable / 变量 | Default / 默认值 | Purpose / 用途 |
|----------------|-----------------|---------------|
| `CANDLE_CLI_RUNTIME` | `mock` | Runtime type: `mock` or `bridge`. / 运行时类型 |
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | Model ID or local path. / 模型 ID 或本地路径 |
| `CANDLE_CLI_MODEL_DEVICE` | auto | Device: `cpu`, `cuda`, or `auto`. / 推理设备 |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | Use only local model files. / 仅使用本地模型文件 |
| `CANDLE_CLI_API_BASE_URL` | (empty) | OpenAI-compatible API base URL. / API 基础地址 |
| `CANDLE_CLI_API_KEY` | (empty) | API key for remote backends. / API 密钥 |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | Maximum generated tokens per turn. / 每轮最大生成 token 数 |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | Sampling temperature. / 采样温度 |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p sampling. / Top-p 采样 |
| `CANDLE_CLI_SYSTEM_PROMPT` | built-in | Override the system prompt. / 覆盖系统提示词 |
| `CANDLE_CLI_MAX_TURNS` | `20` | Maximum retained conversation turns. / 最大保留对话轮数 |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | Tool permission mode. / 工具权限模式 |
| `CANDLE_CLI_SHELL_TIMEOUT_SECS` | `30` | Shell command timeout in seconds. / Shell 命令超时（秒） |
| `CANDLE_CLI_VERBOSE` | `false` | Print bridge diagnostics to stderr. / 输出诊断信息到 stderr |
| `CANDLE_CLI_MODEL_CONFIG` | (empty) | Optional JSON config file path. / 可选 JSON 配置文件路径 |
| `CANDLE_CLI_SESSION_DIR` | system temp dir | Session storage directory. / 会话存储目录 |

---

## Examples / 示例

### API Inference / API 推理

```bash
CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1" \
CANDLE_CLI_API_KEY="YOUR_KEY" \
CANDLE_CLI_MODEL_ID="deepseek-v4-flash" \
python3 examples/api_inference.py
```

### Local Model Inference / 本地模型推理

```bash
python3 examples/qwen3_local_inference.py
```

### Full Agentic Workflow (REPL) / 完整 Agent 工作流 (REPL)

```bash
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

cargo run --
> 帮我检查 src/tools/registry.rs 是否有重复的 match arm
> /trace
> /exit
```

---

## Development / 开发

```bash
# Format / 格式化
cargo fmt --check

# Lint / 代码检查
cargo clippy --all-targets --all-features -- -D warnings

# Rust tests / Rust 测试
cargo test

# Python bridge tests / Python bridge 测试
python3 -m pytest python/test_bridge_runtime.py -q
```

---

## License / 许可证

MIT
