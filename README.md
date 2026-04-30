# candle-cli

Rust-first terminal AI assistant with multi-turn conversation, session persistence, and flexible model backends.

## 快速开始

```bash
git clone https://github.com/DuangZ-GR/candle-cli.git
cd candle-cli
cargo build
```

## 推荐用法：API 模式（Ollama）

最简单的方式是通过 Ollama 运行本地模型：

```bash
# 1. 安装并启动 Ollama，下载一个小模型
ollama pull qwen2:0.5b

# 2. 配置环境变量
export CANDLE_CLI_API_BASE_URL="http://localhost:11434/v1"
export CANDLE_CLI_API_KEY="ollama"
export CANDLE_CLI_MODEL_ID="qwen2:0.5b"
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_VERBOSE="1"          # 可选：查看诊断信息

# 3. 运行
cargo run -- prompt "你好，介绍一下你自己"
cargo run --                           # 交互式 REPL
```

---

## 运行模式

### Prompt 模式（单轮）

```bash
cargo run -- prompt "你的问题"
```

单轮对话，输出回复后退出，结果保存到 session。

### REPL 模式（多轮交互）

```bash
cargo run --
```

进入交互式 REPL，支持多轮对话、slash 命令、session 管理。

### Doctor 模式（状态查看）

```bash
cargo run -- doctor
```

---

## REPL Slash 命令

| 命令 | 说明 |
|------|------|
| `/exit`, `/quit`, `/q` | 退出 REPL（自动保存 session） |
| `/help`, `/h` | 显示所有命令 |
| `/session`, `/info` | 查看当前 session 信息 |
| `/system` | 查看当前系统提示词 |
| `/clear` | 清空当前 session |
| `/list`, `/ls` | 列出所有已保存的 session |
| `/resume <id>` | 恢复指定 session |
| `/save` | 显式保存当前 session |

---

## 两种模型后端

### API 模式（推荐）

通过 OpenAI 兼容的 HTTP API 调用模型（Ollama / vLLM / OpenAI 等）。

**最小配置：**

```bash
export CANDLE_CLI_API_BASE_URL="http://localhost:11434/v1"
export CANDLE_CLI_API_KEY="ollama"
export CANDLE_CLI_MODEL_ID="qwen2:0.5b"
export CANDLE_CLI_RUNTIME="bridge"
```

**常用后端：**

| 后端 | CANDLE_CLI_API_BASE_URL | CANDLE_CLI_API_KEY | CANDLE_CLI_MODEL_ID |
|------|--------------------------|---------------------|----------------------|
| Ollama | `http://localhost:11434/v1` | `ollama` | `qwen2:0.5b` |
| vLLM | `http://localhost:8000/v1` | `not-needed` | `Qwen/Qwen2-0.5B-Instruct` |
| OpenAI | `https://api.openai.com/v1` | `sk-xxx` | `gpt-4o-mini` |

### 本地模型

直接通过 `transformers` 加载本地模型文件推理，无需网络。

```bash
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"
export CANDLE_CLI_MODEL_DEVICE="cpu"
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_LOCAL_FILES_ONLY="false"   # 首次需设置为 false 以下载模型
cargo run -- prompt "你好"
```

---

## 诊断输出

设置 `CANDLE_CLI_VERBOSE=1` 后，worker 通过 stderr 输出详细信息：

```
[candle-cli] API mode active, skipping local model load
[candle-cli]   api_base_url: http://localhost:11434/v1
[candle-cli] API call: POST http://localhost:11434/v1/chat/completions
[candle-cli]   messages: 2 (system=True)
[candle-cli]   model: qwen2:0.5b
[candle-cli]   max_tokens: 512
[candle-cli]   response in 1.4s
[candle-cli]   tokens: prompt=87 completion=66 total=153
[candle-cli]   response length: 24 chars
```

---

## 环境变量完整列表

### 模型与后端

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | 模型 ID 或本地路径 |
| `CANDLE_CLI_MODEL_DEVICE` | auto | 设备：`cpu` / `cuda` / `auto` |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | 仅本地文件，不联网下载 |
| `CANDLE_CLI_API_BASE_URL` | (空) | API 地址，设置后自动切换 API 模式 |
| `CANDLE_CLI_API_KEY` | (空) | API Key |
| `CANDLE_CLI_RUNTIME` | `mock` | runtime 类型：`mock` / `bridge` |

### 生成参数

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | 最大生成 token 数 |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | 采样温度 |
| `CANDLE_CLI_TOP_P` | `0.9` | top-p 采样 |

### 对话控制

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CANDLE_CLI_SYSTEM_PROMPT` | (内置默认) | 系统提示词 |
| `CANDLE_CLI_MAX_TURNS` | `20` | 最大保留对话轮数（超出自动裁剪旧消息） |

### 其他

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CANDLE_CLI_VERBOSE` | `false` | 开启 stderr 诊断输出 |
| `CANDLE_CLI_MODEL_CONFIG` | (空) | JSON 配置文件路径（可选） |
| `CANDLE_CLI_SESSION_DIR` | 系统临时目录 | session 持久化目录 |

---

## 当前功能

- 多轮对话 REPL + 单轮 prompt 模式
- Session 持久化：保存、恢复、列表、清空
- 上下文窗口管理：自动裁剪旧消息，保持对话在 token 预算内
- 系统提示词可配置
- 两种模型后端：本地 transformers / 远程 OpenAI 兼容 API
- 纯环境变量驱动，零配置文件
- Verbose 诊断：token 用量、API 请求详情、显存状态

## 开发

```bash
# 运行所有测试
cargo test
python3 -m pytest python/test_bridge_runtime.py -q

# 代码检查
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
```
