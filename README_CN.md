# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)

[English](README.md) | [中文](README_CN.md)

基于 Rust 的终端 AI 编程助手，具备 agentic coding 能力——通过多步工具循环读取代码、搜索文件、编辑内容、执行命令。

## 核心特性

- **Agent 工具循环** — read → edit → shell → answer，多步执行，有界步数限制
- **DeepSeek 优先** — 针对 DeepSeek API 优化，兼容所有 OpenAI 兼容端点
- **会话持久化** — 保存、列表、恢复、清空对话
- **可配置权限** — `read-only`、`workspace-write`、`prompt`、`danger-full-access`
- **REPL + Prompt** — 交互式多轮对话和单轮提问两种模式
- **Rust 核心 + Python 桥接** — Rust 负责 CLI、会话、工具、agent 循环；Python 负责模型推理

## 快速开始

```bash
git clone https://github.com/DuangZ-GR/candle-cli.git
cd candle-cli
cargo build
```

### 推荐方式：DeepSeek API

```bash
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_DEEPSEEK_API_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

# 单轮提问
cargo run -- prompt "读取 README.md 并总结这个项目的功能"

# 交互式 REPL
cargo run --
```

### 本地后备：Ollama

```bash
ollama pull qwen2:0.5b

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="http://localhost:11434/v1"
export CANDLE_CLI_API_KEY="ollama"
export CANDLE_CLI_MODEL_ID="qwen2:0.5b"

cargo run -- prompt "你好，介绍一下你自己"
```

> 小模型（0.5B–3B）可能无法可靠遵循工具调用协议，建议使用 7B+ 或 API 模型执行 agentic 任务。

## 用法

| 命令 | 用途 |
|------|------|
| `cargo run -- prompt "..."` | 单轮提问后退出 |
| `cargo run --` | 启动交互式 REPL |
| `cargo run -- doctor` | 打印运行时和配置状态 |

### REPL 命令

| 命令 | 别名 | 用途 |
|------|------|------|
| `/help` | `/h` | 显示可用命令 |
| `/exit` | `/quit`, `/q` | 退出并保存会话 |
| `/session` | `/info` | 查看当前会话信息 |
| `/status` | | 查看运行时、模型和权限状态 |
| `/tools` | | 列出已注册工具 |
| `/trace` | | 显示上一轮执行追踪 |
| `/system` | | 查看当前系统提示词 |
| `/clear` | | 清空当前会话 |
| `/list` | `/ls` | 列出已保存会话 |
| `/resume <id>` | | 恢复指定会话 |
| `/save` | | 显式保存当前会话 |

## Agent 工具循环

模型通过发出文本 JSON 格式的工具调用来请求工具：

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Rust 解析该块，执行工具，将会结果记录到会话中，然后再次调用模型。循环重复，直到模型输出不含工具调用的最终回答，或达到最大步数（8 步）。

### 可用工具

| 工具 | 输入 | 用途 | 修改文件 |
|------|------|------|---------|
| `pwd` | `{}` | 显示工作目录 | 否 |
| `read` | `{"file_path":"README.md"}` | 读取 UTF-8 文件 | 否 |
| `glob` | `{"pattern":"src/**/*.rs"}` | 按模式查找文件 | 否 |
| `grep` | `{"pattern":"fn main","path":"src"}` | 搜索文件内容 | 否 |
| `edit` | `{"file_path":"Cargo.toml","old_string":"0.1.0","new_string":"0.3.0"}` | 精确替换一处文本 | **是** |
| `shell` | `{"command":"cargo test"}` | 运行 shell 命令 | **可能** |

### 权限模式

通过 `CANDLE_CLI_PERMISSION` 控制：

| 模式 | 行为 |
|------|------|
| `read-only` | 仅允许 `pwd`、`read`、`glob`、`grep` |
| `workspace-write`（默认） | 允许所有工具，无需确认 |
| `prompt` | 自动允许只读工具；`edit`、`write`、`shell` 需确认 |
| `danger-full-access` | 允许所有工具，无需确认 |

## 模型后端

设置 `CANDLE_CLI_RUNTIME=bridge` 启用真实模型调用（默认 `mock` 用于测试）。

| 后端 | `CANDLE_CLI_API_BASE_URL` | `CANDLE_CLI_API_KEY` | `CANDLE_CLI_MODEL_ID` |
|------|---------------------------|----------------------|-----------------------|
| DeepSeek | `https://api.deepseek.com/v1` | `YOUR_DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| Ollama | `http://localhost:11434/v1` | `ollama` | `qwen2:0.5b` |
| vLLM | `http://localhost:8000/v1` | `not-needed` | `Qwen/Qwen2-0.5B-Instruct` |
| OpenAI | `https://api.openai.com/v1` | `sk-xxx` | `gpt-4o-mini` |

### 本地 transformers 模型

```bash
python3 -m pip install -r requirements.txt

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"
export CANDLE_CLI_MODEL_DEVICE="cpu"
export CANDLE_CLI_LOCAL_FILES_ONLY="false"

cargo run -- prompt "你好"
```

### 诊断输出

设置 `CANDLE_CLI_VERBOSE=1` 在 stderr 上查看 API 详情、token 用量和计时：

```text
[candle-cli] API call: POST https://api.deepseek.com/v1/chat/completions
[candle-cli]   messages: 4 (system=True)
[candle-cli]   model: deepseek-v4-pro
[candle-cli]   max_tokens: 2048
[candle-cli]   response in 1.5s
[candle-cli]   tokens: prompt=599 completion=35 total=634
```

## 配置

所有配置通过环境变量设置。

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `CANDLE_CLI_RUNTIME` | `mock` | `mock` 或 `bridge` |
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | 模型 ID 或本地路径 |
| `CANDLE_CLI_MODEL_DEVICE` | auto | `cpu`、`cuda` 或 `auto` |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | 仅使用本地模型文件 |
| `CANDLE_CLI_API_BASE_URL` | 空 | OpenAI 兼容 API 基础地址 |
| `CANDLE_CLI_API_KEY` | 空 | API 密钥 |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | 每轮最大生成 token 数 |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | 采样温度 |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p 采样 |
| `CANDLE_CLI_SYSTEM_PROMPT` | 内置 | 覆盖系统提示词 |
| `CANDLE_CLI_MAX_TURNS` | `20` | 最大保留对话轮数 |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | 工具权限模式 |
| `CANDLE_CLI_SHELL_TIMEOUT_SECS` | `30` | Shell 命令超时（秒） |
| `CANDLE_CLI_VERBOSE` | `false` | 输出诊断信息到 stderr |
| `CANDLE_CLI_MODEL_CONFIG` | 空 | 可选 JSON 配置文件路径 |
| `CANDLE_CLI_SESSION_DIR` | 系统临时目录 | 会话存储目录 |

## 示例

```bash
# 独立推理测试
python3 examples/api_inference.py
python3 examples/qwen3_local_inference.py

# 多步 agentic 任务
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

cargo run -- prompt "\
1. 读取 src/tools/registry.rs
2. 添加一个名为 'echo' 的新工具，重复其输入
3. 运行 cargo test 验证没有破坏
4. 总结你所做的更改"
```

## 开发

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
python3 -m pytest python/test_bridge_runtime.py -q
```

## 许可证

MIT
