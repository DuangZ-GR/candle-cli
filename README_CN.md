# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)

[English](README.md) | [中文](README_CN.md)

基于 Rust 的 Agentic CLI 工具，具备多 Agent 协同、分层记忆、沙盒执行和可观测性能力。设计方向受 candle 轻量级 AI runtime 理念启发。

## 核心特性

- **Agentic 工具循环** — 有界多步执行，支持子 Agent 任务委派
- **分层记忆** — 会话记忆 + 项目级持久化记忆
- **沙盒执行** — 可选 Docker 容器隔离，网络切断
- **多模型后端** — DeepSeek、Ollama、vLLM、OpenAI，通过 Python bridge 统一接入
- **权限控制** — 四种模式，路径边界检查
- **可观测性** — `/tools`、`/status`、`/trace` 含毫秒计时和 JSON 导出
- **容错机制** — API 指数退避重试，shell 超时强制终止
- **Rust 核心 + Python 桥接** — Rust 负责 CLI、agent loop、工具、权限；Python 桥接模型后端

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

cargo run -- prompt "读取 README.md 并总结这个项目的功能"
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

> 小模型（0.5B–3B）可能无法可靠遵循工具调用协议。建议使用 7B+ 或 API 模型执行 agentic 任务。

## 用法

| 命令 | 用途 |
|------|------|
| `cargo run -- prompt "..."` | 单轮提问后退出 |
| `cargo run --` | 交互式 REPL（含 readline 编辑） |
| `cargo run -- harness` | 运行自动化场景评测 |
| `cargo run -- doctor` | 打印运行时状态 |

### REPL 命令

| 命令 | 别名 | 用途 |
|------|------|------|
| `/help` | `/h` | 显示可用命令 |
| `/exit` | `/quit`, `/q` | 退出并保存会话 |
| `/session` | `/info` | 查看会话信息 |
| `/status` | | 查看运行时、模型、权限状态 |
| `/tools` | | 列出已注册工具 |
| `/trace` | | 查看执行链路及耗时；`--json` 导出结构化数据 |
| `/system` | | 查看当前系统提示词 |
| `/name <label>` | | 为当前会话命名 |
| `/memory` | | 管理项目记忆（file/cmd/note 子命令） |
| `/clear` | | 清空当前会话 |
| `/list` | `/ls` | 列出已保存会话 |
| `/resume <id>` | | 恢复指定会话 |
| `/save` | | 保存当前会话 |

## Agentic 系统

### 工具调用协议

模型通过文本 JSON 块请求工具：

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Rust 解析该块，执行工具，将结果记录到会话并反馈给模型。循环持续到模型输出最终回答或达到最大步数（8）。同时支持函数式调用解析：`read({"file_path":"README.md"})`。

### 可用工具

| 工具 | 输入 | 用途 | 修改文件 |
|------|------|------|---------|
| `pwd` | `{}` | 显示工作目录 | 否 |
| `read` | `{"file_path":"README.md"}` | 读取 UTF-8 文件（路径边界检查） | 否 |
| `glob` | `{"pattern":"src/**/*.rs"}` | 按模式查找文件 | 否 |
| `grep` | `{"pattern":"fn main","path":"src"}` | 递归搜索文件内容 | 否 |
| `web_search` | `{"query":"今天天气"}` | 网络搜索（DuckDuckGo/Sogou 双后端） | 否 |
| `task` | `{"description":"分析这段代码"}` | 委派只读子 Agent（3 步循环） | 否 |
| `edit` | `{"file_path":"Cargo.toml","old_string":"0.1.0","new_string":"0.3.0"}` | 精确替换一处文本 | **是** |
| `shell` | `{"command":"cargo test"}` | 运行 shell 命令（含超时） | **可能** |

### 权限模式

| 模式 | 行为 |
|------|------|
| `read-only` | 仅允许 `pwd`、`read`、`glob`、`grep` |
| `workspace-write`（默认） | 允许所有工具，无需确认 |
| `prompt` | 只读工具自动允许；`edit`、`write`、`shell` 需交互确认 |
| `danger-full-access` | 允许所有工具，无需确认 |

### 多 Agent 协同

`task` 工具以只读权限和 3 步有界循环创建子 Agent，主 Agent 可将代码分析、调研或验证等子任务委派给独立子 Agent 并获得结构化结果。

### 分层记忆

- **会话记忆**：对话历史以 JSON 持久化，支持列表、恢复和清空
- **项目记忆**：`.candle-cli/memory.json` 存储关键文件、常用命令和自由笔记，自动注入系统提示词

```bash
/memory file src/main.rs
/memory cmd cargo test
/memory note build=4090 上约 5 秒
```

### 沙盒执行

设置 `CANDLE_CLI_SANDBOX=docker` 在隔离的 Alpine 容器中运行 shell 命令，工作目录只读挂载，网络断开。

### 容错机制

- API 调用指数退避重试（最多 3 次，1s/2s/4s，4xx 不重试）
- Shell 超时 SIGKILL 强制终止（通过 `CANDLE_CLI_SHELL_TIMEOUT_SECS` 配置）

### RAG 预检索

每轮调用前，上下文构建器从用户消息中提取关键词，对 `src/` 执行 grep，将匹配的代码片段注入提示词。问候语和聊天消息自动检测并跳过。

### 可观测性

- `/tools` — 系统能力边界展示
- `/status` — 运行时快照（会话、模型、权限、配置）
- `/trace` — 执行链路含每步毫秒计时；`--json` 支持结构化导出

### Harness 评测

```bash
cargo run -- harness
```

运行四个预设场景（read、glob、grep、shell），生成通过/失败报告，含计时、工具步数统计和 `harness_report.json` 输出。

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

设置 `CANDLE_CLI_VERBOSE=1` 在 stderr 上查看 API 请求详情、token 用量、耗时和 GPU 显存诊断信息。

## 配置

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `CANDLE_CLI_RUNTIME` | `mock` | `mock` 或 `bridge` |
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | 模型 ID 或本地路径 |
| `CANDLE_CLI_MODEL_DEVICE` | auto | `cpu`、`cuda` 或 `auto` |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | 仅使用本地文件 |
| `CANDLE_CLI_API_BASE_URL` | 空 | OpenAI 兼容 API 基础地址 |
| `CANDLE_CLI_API_KEY` | 空 | API 密钥 |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | 每轮最大生成 token 数 |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | 采样温度 |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p 采样 |
| `CANDLE_CLI_SYSTEM_PROMPT` | 内置 | 覆盖系统提示词 |
| `CANDLE_CLI_MAX_TURNS` | `20` | 最大保留对话轮数 |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | 权限模式 |
| `CANDLE_CLI_PERMISSION_RESPONSE` | 空 | 预设交互确认响应 |
| `CANDLE_CLI_SHELL_TIMEOUT_SECS` | `30` | Shell 超时（秒） |
| `CANDLE_CLI_SANDBOX` | 空 | 设为 `docker` 启用容器隔离 |
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

cargo run -- prompt "读取 src/tools/registry.rs 并总结工具分发逻辑"

# Harness 评测
cargo run -- harness
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
