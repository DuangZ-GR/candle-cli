# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)

[English](README.md) | [中文](README_CN.md)

`candle-cli` 是面向 PyTorch→MindSpore 工程迁移的 Rust-first 智能诊断 CLI：当前提供确定性 AST 扫描与安全 Agent 基础设施，目标是结合双框架运行证据定位首个语义偏差，并生成经过验证的修复。

## 核心特性

- **Agentic 工具循环** — 有界多步执行，支持子 Agent 任务委派
- **流式输出** — token 级实时打印，边生成边显示
- **分层记忆** — 会话记忆 + 项目级持久化记忆
- **沙盒执行** — 可选 Docker 容器隔离，网络切断
- **多模型后端** — DeepSeek、Ollama、vLLM、OpenAI，通过持久化 Python bridge 统一接入
- **权限控制** — 四种模式，路径边界检查，交互式确认
- **可观测性** — `/tools`、`/status`（含 token 估算）、`/trace`（含毫秒计时和 JSON 导出）
- **容错机制** — API 指数退避重试（4xx 不重试），shell 超时强制终止
- **Rust 核心 + Python 桥接** — Rust 负责 CLI、agent loop、工具、权限；Python 桥接模型后端，子进程跨轮复用
- **迁移静态扫描** — 无需安装 PyTorch/MindSpore，解析 import 别名、Tensor Method、源码位置和参数信息

## 快速开始

环境要求：Rust stable 与 Python 3.10 或更高版本。使用 Bridge 运行时时，
通过 `python -m pip install -r requirements.txt` 安装 Python 依赖。

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
| `cargo run --` | 交互式 REPL（含 readline 编辑、流式输出） |
| `cargo run -- harness` | 运行自动化场景评测 |
| `cargo run -- doctor` | 打印运行时状态 |
| `cargo run -- migrate scan <path>` | 扫描 PyTorch API 并输出版本化 JSON 报告 |

### PyTorch→MindSpore 迁移扫描

```bash
# 输出 JSON 到终端
cargo run -- migrate scan ./project --pretty

# 生成 Markdown 报告；已存在的文件默认不会被覆盖
cargo run -- migrate scan ./project --format markdown --output scan-report.md

# 确认替换已有报告
cargo run -- migrate scan ./project --format markdown --output scan-report.md --force
```

扫描器只使用 Python 标准库 AST，不导入也不执行待扫描工程。它支持 `import torch as t`、`from torch.nn.functional import relu` 等别名形式，并对可静态确认的 Tensor Method 和动态 `getattr` 调用分级标记。单文件默认限制为 2 MiB，可通过 `--max-file-bytes` 调整。

固定的 `torch2ms-scanner-v1` 语法覆盖集包含 50 个任务。当前版本在该公开、随仓库发布的开发评测集上为 50/50 精确匹配、precision 100%、recall 100%。该结果仅说明这些已收录语法模式通过，不能代表未知真实项目的总体准确率；后续将另建独立真实项目测试集。

### REPL 命令

| 命令 | 别名 | 用途 |
|------|------|------|
| `/help` | `/h` | 显示可用命令 |
| `/exit` | `/quit`, `/q` | 退出并保存会话 |
| `/session` | `/info` | 查看会话信息 |
| `/status` | | 查看运行时、模型、权限状态（含 token 估算） |
| `/tools` | | 列出已注册工具 |
| `/trace` | | 查看执行链路及耗时；`--json` 导出结构化数据 |
| `/system` | | 查看当前系统提示词 |
| `/name <label>` | | 为当前会话命名 |
| `/model [id]` | | 查看或切换模型 |
| `/memory` | | 管理项目记忆（file/cmd/note 子命令） |
| `/clear` | | 清空当前会话 |
| `/list` | `/ls` | 列出已保存会话 |
| `/resume <id>` | | 恢复指定会话 |
| `/save` | | 保存当前会话 |

## Agentic 系统

### 工具调用协议

模型通过文本 JSON 块请求工具，系统解析并执行后反馈结果，循环至模型输出最终回答或达到最大步数。同时支持 `<tool_call>` 标签和函数式调用两种格式。

### 可用工具

| 工具 | 输入 | 用途 | 修改文件 |
|------|------|------|---------|
| `pwd` | `{}` | 显示工作目录 | 否 |
| `read` | `{"file_path":"README.md"}` | 读取 UTF-8 文件（路径边界检查） | 否 |
| `glob` | `{"pattern":"src/**/*.rs"}` | 按模式查找文件 | 否 |
| `grep` | `{"pattern":"fn main","path":"src"}` | 递归搜索文件内容 | 否 |
| `web_search` | `{"query":"今天天气"}` | 网络搜索（DuckDuckGo/Sogou 双后端） | 否 |
| `task` | `{"description":"分析这段代码"}` | 委派只读子 Agent（3 步循环） | 否 |
| `write` | `{"file_path":"report.txt","content":"..."}` | 在工作区内写入 UTF-8 文件 | **是** |
| `edit` | `{"file_path":"Cargo.toml","old_string":"0.1.0","new_string":"0.3.0"}` | 精确替换一处文本 | **是** |
| `shell` | `{"command":"cargo test"}` | 运行 shell 命令（含超时和沙盒） | **可能** |

### 权限模式

| 模式 | 行为 |
|------|------|
| `read-only` | 仅允许 `pwd`、`read`、`glob`、`grep` |
| `workspace-write`（默认） | 工作区文件修改无需确认；宿主机 Shell 命令必须确认 |
| `prompt` | 只读工具自动允许；修改工具交互式确认 |
| `danger-full-access` | 所有工具（包括宿主机 Shell）均无需确认 |

### 多 Agent 协同

`task` 工具以只读权限和 3 步有界循环创建子 Agent，主 Agent 将子任务委派给独立子 Agent 并获得结构化结果。

### 分层记忆

- **会话记忆**：对话历史 JSON 持久化，支持列表、恢复和清空
- **项目记忆**：`.candle-cli/memory.json` 存储关键文件、常用命令和自由笔记，自动注入系统提示词

### 沙盒执行

`CANDLE_CLI_SANDBOX=docker` 在隔离 Alpine 容器中运行 shell 命令，工作目录只读挂载，网络断开。

### 容错机制

API 调用指数退避重试（最多 3 次，4xx 不重试），shell 超时 SIGKILL。

### RAG 预检索

每轮调用前自动从用户消息提取关键词，对 `src/` 目录 grep，结果注入上下文减少 API 轮次。

### 可观测性

- `/tools` — 系统能力边界展示
- `/status` — 运行时快照（会话、模型、权限、token 估算）
- `/trace` — 执行链路含每步毫秒计时；支持 `--json` 导出

### Harness 评测

```bash
cargo run -- harness
```

运行预设场景并生成通过/失败报告，输出 `harness_report.json`。

## 模型后端

| 后端 | `CANDLE_CLI_API_BASE_URL` | `CANDLE_CLI_API_KEY` | `CANDLE_CLI_MODEL_ID` |
|------|---------------------------|----------------------|-----------------------|
| DeepSeek | `https://api.deepseek.com/v1` | `YOUR_DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| Ollama | `http://localhost:11434/v1` | `ollama` | `qwen2:0.5b` |
| vLLM | `http://localhost:8000/v1` | `not-needed` | `Qwen/Qwen2-0.5B-Instruct` |
| OpenAI | `https://api.openai.com/v1` | `sk-xxx` | `gpt-4o-mini` |

### 诊断输出

`CANDLE_CLI_VERBOSE=1` 在 stderr 查看 API 详情、token 用量和耗时。

## 配置

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `CANDLE_CLI_RUNTIME` | `mock` | `mock` 或 `bridge` |
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | 模型 ID 或本地路径 |
| `CANDLE_CLI_MODEL_DEVICE` | auto | `cpu`、`cuda` 或 `auto` |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | 仅使用本地文件 |
| `CANDLE_CLI_API_BASE_URL` | 空 | API 基础地址 |
| `CANDLE_CLI_API_KEY` | 空 | API 密钥 |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | 每轮最大生成 token 数 |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | 采样温度 |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p 采样 |
| `CANDLE_CLI_SYSTEM_PROMPT` | 内置 | 覆盖系统提示词 |
| `CANDLE_CLI_MAX_TURNS` | `20` | 最大保留对话轮数 |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | 权限模式 |
| `CANDLE_CLI_PERMISSION_RESPONSE` | 空 | 预设交互确认响应 |
| `CANDLE_CLI_SHELL_TIMEOUT_SECS` | `30` | Shell 超时（秒） |
| `CANDLE_CLI_MAX_TOOL_OUTPUT_CHARS` | `65536` | 模型和会话上下文中保留的工具结果最大字符数 |
| `CANDLE_CLI_ALLOW_STUB_FALLBACK` | `false` | 仅为演示/测试启用回显桩；真实 Agent 任务禁止开启 |
| `CANDLE_CLI_SANDBOX` | 空 | `docker` 启用容器隔离 |
| `CANDLE_CLI_VERBOSE` | `false` | 诊断信息输出到 stderr |
| `CANDLE_CLI_MODEL_CONFIG` | 空 | 可选 JSON 配置文件 |
| `CANDLE_CLI_SESSION_DIR` | 系统临时目录 | 会话存储目录 |

## 示例

```bash
python3 examples/api_inference.py
python3 examples/qwen3_local_inference.py

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

cargo run -- prompt "读取 src/tools/registry.rs 并总结工具分发逻辑"
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
