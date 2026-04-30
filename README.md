# candle-cli

Rust-first terminal coding assistant designed around a candle-targeted runtime boundary.

## 快速开始

```bash
git clone https://github.com/DuangZ-GR/candle-cli.git
cd candle-cli
cargo build
```

## 两种运行模式

candle-cli 支持两种模型后端，通过环境变量切换。

---

### 模式一：本地模型（Local Model）

直接用 `transformers` 加载本地模型文件进行推理，无需网络。

**最小配置：**

```bash
# 必填：模型 ID（HuggingFace repo ID 或本地路径）
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"

# 可选：设备（默认 auto = 自动检测 CUDA）
export CANDLE_CLI_MODEL_DEVICE="cpu"

# 运行
cargo run -- prompt "你好，介绍一下你自己"
```

**完整配置选项：**

```bash
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"   # 模型 ID 或本地路径
export CANDLE_CLI_MODEL_DEVICE="auto"                    # cpu / cuda / auto
export CANDLE_CLI_LOCAL_FILES_ONLY="true"                # 仅本地文件（默认 true，false 则允许自动下载）
export CANDLE_CLI_MAX_NEW_TOKENS="512"                   # 最大生成 token 数
export CANDLE_CLI_TEMPERATURE="0.7"                      # 采样温度
export CANDLE_CLI_TOP_P="0.9"                            # top-p 采样
export CANDLE_CLI_VERBOSE="1"                            # 开启诊断输出（显存、接口、耗时等）
```

---

### 模式二：API 模式（Remote API）

通过 OpenAI 兼容的 HTTP API 调用远程模型（vLLM / Ollama / OpenAI / Anthropic / 等）。

**最小配置：**

```bash
# 必填：API 地址
export CANDLE_CLI_API_BASE_URL="http://localhost:11434/v1"

# 必填：API Key
export CANDLE_CLI_API_KEY="ollama"

# 必填：模型 ID
export CANDLE_CLI_MODEL_ID="qwen2:0.5b"
```

**常用后端示例：**

| 后端 | CANDLE_CLI_API_BASE_URL | CANDLE_CLI_API_KEY | CANDLE_CLI_MODEL_ID |
|------|--------------------------|---------------------|----------------------|
| Ollama | `http://localhost:11434/v1` | `ollama` | `qwen2:0.5b` |
| vLLM | `http://localhost:8000/v1` | `not-needed` | `Qwen/Qwen2-0.5B-Instruct` |
| OpenAI | `https://api.openai.com/v1` | `sk-xxx` | `gpt-4o-mini` |
| Anthropic (兼容) | 需配置兼容网关 | `sk-ant-xxx` | `claude-sonnet-4-5` |

**完整 API 模式配置：**

```bash
export CANDLE_CLI_API_BASE_URL="http://localhost:8000/v1"
export CANDLE_CLI_API_KEY="not-needed"
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"
export CANDLE_CLI_MAX_NEW_TOKENS="2048"
export CANDLE_CLI_TEMPERATURE="0.7"
export CANDLE_CLI_VERBOSE="1"                            # 可看到每次 API 请求/响应详情
```

---

### 诊断输出

设置 `CANDLE_CLI_VERBOSE=1` 后，worker 通过 stderr 输出：

```
[candle-cli] ============================================================
[candle-cli] bridge runtime initializing (local model mode)
[candle-cli]   model_id=Qwen/Qwen2-0.5B-Instruct
[candle-cli]   device=cuda
[candle-cli]   transformers: import ok
[candle-cli]   loading tokenizer: Qwen/Qwen2-0.5B-Instruct
[candle-cli]   tokenizer loaded in 2.3s
[candle-cli]   resolved device: cuda
[candle-cli]   GPU memory: 0.00 GiB allocated, 0.00 GiB reserved (before model load)
[candle-cli]   loading model: Qwen/Qwen2-0.5B-Instruct
[candle-cli]   model loaded in 8.5s
[candle-cli]   GPU memory: 1.02 GiB allocated, 1.15 GiB reserved (after model load)
[candle-cli]   model parameters: 0.49B
[candle-cli] bridge runtime ready
[candle-cli] generate_turn: 3 chat messages
[candle-cli]   input tokens: 128
[candle-cli]   generating (max_new_tokens=512)...
[candle-cli]   output tokens: 156
[candle-cli]   generation time: 12.30s (12.7 tok/s)
[candle-cli]   GPU memory: 1.15 GiB allocated, 1.28 GiB reserved
```

---

### REPL 模式

```bash
cargo run --
```

进入交互式 REPL，支持多轮对话、session 持久化。

### Prompt 模式

```bash
cargo run -- prompt "你的问题"
```

单轮 prompt，输出回复后退出。

### 查看状态

```bash
cargo run -- doctor
```

---

## 开发

```bash
# 运行所有测试
cargo test

# Python worker 测试
python3 -m pytest python/test_bridge_runtime.py -q

# 代码检查
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
```

## 环境变量完整列表

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | 模型 ID 或本地路径 |
| `CANDLE_CLI_MODEL_DEVICE` | auto (CUDA 优先) | 设备：`cpu` / `cuda` / `auto` |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | 仅本地文件，不联网下载 |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | 最大生成 token 数 |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | 采样温度 |
| `CANDLE_CLI_TOP_P` | `0.9` | top-p 采样 |
| `CANDLE_CLI_VERBOSE` | `false` | 开启 stderr 诊断输出 |
| `CANDLE_CLI_API_BASE_URL` | (空) | API 地址，设置后自动切换 API 模式 |
| `CANDLE_CLI_API_KEY` | (空) | API Key |
| `CANDLE_CLI_MODEL_CONFIG` | (空) | JSON 配置文件路径（可选） |
| `CANDLE_CLI_SESSION_DIR` | 系统临时目录 | session 持久化目录 |
| `CANDLE_CLI_RUNTIME` | `mock` | runtime 类型：`mock` / `bridge` |
