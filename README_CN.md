# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)
[![CI](https://github.com/DuangZ-GR/candle-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/DuangZ-GR/candle-cli/actions/workflows/ci.yml)

[English](README.md) | [中文](README_CN.md)

`candle-cli` 是面向 PyTorch→MindSpore 工程迁移的 Rust-first 智能诊断 CLI：通过确定性 AST 扫描、官方映射、双框架运行证据和事务式 Patch，定位首个语义偏差并生成可验证、可回滚的迁移结果。

项目的一句话定位、可复现指标、推荐简历表述与能力边界见 [`docs/RESUME_PROJECT_SUMMARY_CN.md`](docs/RESUME_PROJECT_SUMMARY_CN.md)。

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
- **组件级差分验证** — 分离采集 PyTorch/MindSpore 前向与梯度轨迹，评估等价性、缺陷分类和首错 Top-1
- **可验证迁移重写** — 最小化预览 API/dtype 修改，事务式应用，显式执行验证命令，并支持校验和保护的回滚
- **端到端迁移闭环** — 单个命令串联扫描、预览、应用、程序验证、Trace 比较和失败回滚，输出统一 JSON/Markdown 报告

## 快速开始

环境要求：Rust stable 与 Python 3.10 或更高版本。使用 Bridge 运行时时，
通过 `python -m pip install -r requirements.txt` 安装 Python 依赖。

```bash
git clone https://github.com/DuangZ-GR/candle-cli.git
cd candle-cli
cargo build
```

仓库安装脚本默认只安装 Rust CLI，不强制下载框架依赖：

```bash
sh scripts/install.sh                # Linux/macOS
.\scripts\install.ps1               # Windows PowerShell
```

仅在需要 Bridge/双框架能力时，Linux 增加 `--with-python`，Windows 增加 `-InstallPythonDependencies`。`sh scripts/demo.sh` 与 `scripts/demo.ps1` 提供离线 doctor、映射查询、扫描、Patch 预览和冻结安全留出集演示，不修改示例源码。

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
export CANDLE_CLI_API_STYLE="ollama-native"
export CANDLE_CLI_API_BASE_URL="http://localhost:11434"
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
| `cargo run -- security-harness` | 运行确定性的路径/权限安全回归基准 |
| `cargo run -- security-heldout` | 运行与 M8 开发集分离的 M18 冻结安全留出集 |
| `cargo run -- context-harness` | 测量确定性轮次裁切的 Token 减少与完整性 |
| `cargo run -- doctor [--json]` | 检查 Rust、Python、双框架、Docker、Bridge、Provider 与双环境配置 |
| `cargo run -- migrate scan <path>` | 扫描 PyTorch API 并输出版本化 JSON 报告 |
| `cargo run -- migrate run <path>` | 执行扫描、改写、验证、Trace 对比和回滚闭环 |
| `cargo run -- migrate map <api>` | 查询带框架版本与官方证据的 MindSpore 映射 |
| `cargo run -- migrate import-msprobe ...` | 将 msprobe `dump.json` 归一化为标准 JSONL |
| `cargo run -- migrate compare <pt.jsonl> <ms.jsonl>` | 对齐双框架轨迹并定位首个可观测偏差 |
| `cargo run -- migrate rewrite <path>` | 只预览确定性 API/dtype 重写，不修改源码 |
| `cargo run -- migrate rollback <manifest>` | 从重写事务中恢复源码 |

### PyTorch→MindSpore 迁移扫描

```bash
# 输出 JSON 到终端
cargo run -- migrate scan ./project --pretty

# 生成 Markdown 报告；已存在的文件默认不会被覆盖
cargo run -- migrate scan ./project --format markdown --output scan-report.md

# 确认替换已有报告
cargo run -- migrate scan ./project --format markdown --output scan-report.md --force

# 单独查询一个 API
cargo run -- migrate map torch.arange --pretty

# 只生成最小 Patch 预览，不修改源码
cargo run -- migrate rewrite ./project --pretty

# 统一预览工作流并生成 Markdown 报告
cargo run -- migrate run ./project \
  --format markdown --output migration-report.md

# 应用补丁并强制在 MindSpore 环境执行验证
cargo run -- migrate run ./project --apply \
  --validate-program /path/to/mindspore/python \
  --validate-arg=-m --validate-arg=pytest

# 由版本化清单自动采集 PyTorch/MindSpore Trace、比较并按需回滚
export CANDLE_CLI_PYTORCH_PYTHON=/path/to/pytorch/python
export CANDLE_CLI_MINDSPORE_PYTHON=/path/to/mindspore/python
cargo run -- migrate run ./project/model.py --apply \
  --runtime-manifest ./project/runtime_manifest.json

# 应用精确映射并直接执行验证程序（不经过 shell）
cargo run -- migrate rewrite ./project --apply \
  --validate-program python --validate-arg=-m --validate-arg=pytest

# 根据事务清单回滚
cargo run -- migrate rollback \
  ./project/.candle-cli/backups/<transaction-id>/manifest.json --pretty
```

扫描器只使用 Python 标准库 AST，不导入也不执行待扫描工程。它支持 `import torch as t`、`from torch.nn.functional import relu` 等别名形式，并对可静态确认的 Tensor Method 和动态 `getattr` 调用分级标记。每条 finding 自动附带目标 API、PyTorch/MindSpore 版本、映射快照版本、差异类型和官方证据。单文件默认限制为 2 MiB，可通过 `--max-file-bytes` 调整。

当前映射快照基于 PyTorch 2.1 与 MindSpore 2.9.0 官方映射表，收录 53 条经过证据校验的记录。在固定扫描集的 36 个唯一 API 上覆盖 27 个（75%）：25 个一致映射、2 个差异映射、9 个保持 unknown。未收录只表示当前快照未知，不代表 MindSpore 不支持。

固定的 `torch2ms-scanner-v1` 语法覆盖集包含 50 个任务。当前版本在该公开、随仓库发布的开发评测集上为 50/50 精确匹配、precision 100%、recall 100%。该结果仅说明这些已收录语法模式通过，不能代表未知真实项目的总体准确率；后续将另建独立真实项目测试集。

确定性重写默认只预览。它解析 import 别名，只修改已接受映射的调用名称及其内部受支持的 `dtype=` 常量，不重排周边代码或注释；标记为 `difference` 的映射必须显式传入 `--include-differences`。应用前会校验预览时的源码哈希，随后在同一项目的 `.candle-cli/backups` 中保存备份和事务清单。验证命令失败或超时时会自动恢复全部源码；未提供 `--validate-program` 的应用结果会明确标记为 `verified: false`。固定的 `rewrite-cases-v1` 合成开发集包含 15 个案例，当前精确 Patch、安全跳过和语法有效率均为 100%；其中专门包含混合迁移文件，确保仍有 PyTorch 引用时不会误删 import。这不是 held-out 或真实项目评测结果。

固定的 `real-projects-v1` 增加了真实项目覆盖审计，包含 PyTorch Examples、nanoGPT、DETR 的 25 个文件与 4,436 行代码。在知识库快照 `ms2.9.0-pt2.1-2026-08-05.1` 下，25/25 文件扫描无问题，但当前只映射 132/545 个调用发现（24.22%）和 21/162 个唯一 API（12.96%）。exact-only 策略在 18 个文件中产生 71 个调用改写，18/18 个预览保持语法有效。这些是静态覆盖与语法指标，不是运行时迁移准确率，详见 `docs/M6_REAL_PROJECT_BASELINE.md`。

基于官方证据扩充到快照 `.3` 后，调用映射覆盖达到 244/545（44.77%），exact-only 改写机会从 71 增至 115，18/18 个预览文件仍保持语法有效。规则冻结后才选取 Segment Anything 做留出审计：17/17 个文件扫描成功，映射 89/212 个调用（41.98%），9/9 个生成预览文件语法有效。详见 `docs/M6_REAL_PROJECT_RESULTS.md`；这些仍是静态指标，不等同于 MindSpore 运行时准确率。

带版本门禁的运行微基准可分别在 PyTorch 与 MindSpore 环境采集 5 条确定性 API 链，再通过公共轨迹比较器核对返回结构、dtype、shape、NaN/Inf 和数值摘要。`runtime-parity-v2` 已在 Linux 的 PyTorch 2.6.0+cu124 与 MindSpore 2.9.0 环境完成真实双端采集：两端均为 5/5 案例、10/10 调用成功，5/5 案例等价，运行一致率与分类准确率均为 100%，版本门禁通过。该数据只代表基础前向 API 微基准，不代表真实项目端到端迁移准确率，详见 `docs/M7_RUNTIME_PARITY.md`。

`runtime-components-v1` 进一步覆盖 MLP、CNN、输入/权重梯度、BatchNorm 推理，以及 dtype 误转、默认训练模式和缺失算子三类固定偏差。Linux 真实双端采集完成 7/7 案例和每端 12/12 调用记录；4/4 等价组件通过，3/3 留出偏差的类别与首错 Top-1 正确，梯度案例 1/1 一致。该集合仍是小型确定性组件与故障注入，不是完整项目迁移准确率，详见 `docs/M11_COMPONENT_PARITY.md`。

`runtime-training-v1` 将验证扩展到最小训练步骤：前向输出、MSE loss、参数梯度和 SGD 一步更新后的参数快照。Linux 真实双端采集使用 PyTorch 2.6.0+cu124 与 MindSpore 2.9.0，两端均完成 3/3 案例和 12/12 调用记录；2/2 等价训练步骤通过，1/1 学习率注入缺陷在优化器更新阶段首错 Top-1 定位正确。该数据仍是小型确定性训练步基准，不覆盖多步收敛、Adam、混合精度、分布式训练或真实项目端到端准确率，详见 `docs/M12_TRAINING_PARITY.md`。

`workflow-e2e-v1` 通过统一的 `migrate run` 状态机验证扫描、改写、程序执行、Trace 比较和回滚：在 PyTorch 2.6.0+cu124 与 MindSpore 2.9.0 环境中，4/4 固定场景符合预期，1/1 真实双框架应用验证通过，2/2 故障注入完整恢复源码，1/1 dtype 偏差首错 Top-1 正确并触发回滚。该集合只包含一个两算子可执行样例和两个已标注故障，证明闭环控制与恢复能力，不代表真实项目迁移准确率，详见 `docs/M13_END_TO_END_WORKFLOW.md`。

`real-model-dual-runtime-v1` 固定 PyTorch Examples MNIST 的 141 行上游源码，并对其中分类器头构造 25 行离线可执行切片。工作流自动启动 PyTorch 2.6.0+cu124 与 MindSpore 2.9.0、生成 Trace、应用 6 个自动 Patch，并将 1 次人工功能适配单独计数：3/3 场景通过，1/1 正常迁移等价，2/2 故障注入按字节回滚，自动 Patch 采用率为 6/7（85.7143%）。运行切片的 5/5 调用映射覆盖率为 100%，但该数字不代表完整上游程序或未知项目的迁移准确率，详见 `docs/M14_REAL_MODEL_DUAL_RUNTIME.md`。

`data-pipeline-randomness-v1` 使用 PyTorch 2.6.0+cu124/torchvision 0.21.0+cu124 与 MindSpore 2.9.0 真实运行 18 个冻结的数据输入案例，覆盖 TensorDataset/DataLoader、Normalize、Resize、ToTensor、布局、dtype、标签、掩码、尾批次、固定种子、Dropout、采样和初始化。7/7 个确定性等价案例与 3/3 个统计等价案例通过，8/8 个故障注入的类别和首差异 Top-1 全部正确。4 个随机案例均报告样本量、统计量和阈值，并明确禁止逐元素相等判定。该结果只适用于固定的小型数组和已标注故障，不代表未知项目准确率，也不表示两个框架使用相同随机算法，详见 `docs/M15_DATA_PIPELINE_RANDOMNESS.md`。

`advanced-training-v1` 在 CPU 上通过 PyTorch Eager、MindSpore PYNATIVE/GRAPH 真实运行 13 个冻结案例。4/4 前向组件在三运行时一致；三个 3–5 步优化器案例中 2/3 等价，AdamW + 学习率序列暴露出可复现的跨框架优化器状态差异，没有通过放宽容差隐藏；三个独立进程 Checkpoint 恢复均成功，5/5 个编译/运行/梯度/优化器/shape 故障均正确完成 Top-1 分类。该结果来自固定小网络和短轨迹，不代表完整收敛、加速卡、混合精度或分布式训练结论，详见 `docs/M16_GRAPH_ADVANCED_TRAINING.md`。

随仓库固定的 `security-regression-v1` 在不执行危险 Shell 的情况下测试 12 个本地路径/权限攻击样例和 10 个正常样例：12/12 被介入（10 个硬拦截、2 个确认门禁），10/10 正常样例放行。该数据只适用于当前确定性回归集，不能外推到未知攻击、容器逃逸、提示注入或网络外传，详见 `docs/M8_SECURITY_BENCHMARK.md`。

M18 新增独立冻结的 `security-heldout-v1`。Linux 上 15 个攻击项中有 12 个可实际评估，12/12 被硬拦截或进入确认门禁；8/8 正常任务被放行或按预期确认，误拦截率为 0%。压缩包逃逸（项目无解压入口）、真正的 symlink 竞态安全和 Windows junction 三项明确标为 `not_applicable`，不计入拦截率。实现同时修复递归搜索跟随外部符号链接、web_search 查询拼接执行、联网无需确认，以及大文件/Shell 输出无内存上限等问题。详见 `docs/M18_RELEASE_SECURITY_CI.md` 与 `docs/FINAL_BENCHMARK_REPORT_CN.md`。

`context-fact-retention-v2` 在 20 个冻结迁移会话中采用“近期原文 + 结构化任务状态 + 可校验来源摘要”，将估算 Token 从 23,146 降至 4,221，减少 81.76%；文件、命令、错误、待办和决策事实保留 20/20，历史事实任务可回答 20/20，来源摘要校验 20/20。该结果仍是确定性启发式估算，不是 Provider 计费 Token。Bridge 已能采集 Provider 返回的 Token/Cache usage；Agent 消融提供不可用于正式结论的 `--smoke` 能力门禁，现有 `qwen2:0.5b` 未通过工具调用冒烟，因此正式 Provider 消融尚未运行、缓存命中率继续为 `null`，详见 `docs/M17_CONTEXT_AGENT_ABLATION.md`。

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
| `read-only-with-task` | 在只读工具之外允许 `task` 委派，不开放 Shell/写入 |
| `workspace-write`（默认） | 工作区文件修改无需确认；宿主机 Shell 命令必须确认 |
| `prompt` | 只读工具自动允许；修改工具交互式确认 |
| `danger-full-access` | 所有工具（包括宿主机 Shell）均无需确认 |

### 多 Agent 协同

`task` 工具以只读权限和 3 步有界循环创建子 Agent，主 Agent 将子任务委派给独立子 Agent 并获得结构化结果。主/子 Agent 共享模型请求数与工具步数预算，子 Agent 继承父工作目录，避免消融时获得额外预算或读取错误目录。

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
| Ollama 原生 | `http://localhost:11434` | `ollama` | `qwen2:0.5b` |
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
| `CANDLE_CLI_API_STYLE` | `openai` | `openai` 或 `ollama-native`；原生模式支持 Ollama `think=false` |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | 每轮最大生成 token 数 |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | 采样温度 |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p 采样 |
| `CANDLE_CLI_SYSTEM_PROMPT` | 内置 | 覆盖系统提示词 |
| `CANDLE_CLI_MAX_TURNS` | `20` | 最大保留对话轮数 |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | 权限模式 |
| `CANDLE_CLI_PERMISSION_RESPONSE` | 空 | 预设交互确认响应 |
| `CANDLE_CLI_SHELL_TIMEOUT_SECS` | `30` | Shell 超时（秒） |
| `CANDLE_CLI_MAX_SHELL_OUTPUT_BYTES` | `1048576` | Shell stdout/stderr 各自最多保留的字节数 |
| `CANDLE_CLI_MAX_READ_BYTES` | `2097152` | read 工具允许读取的 UTF-8 文件大小上限 |
| `CANDLE_CLI_MAX_TOOL_OUTPUT_CHARS` | `65536` | 模型和会话上下文中保留的工具结果最大字符数 |
| `CANDLE_CLI_ALLOW_STUB_FALLBACK` | `false` | 仅为演示/测试启用回显桩；真实 Agent 任务禁止开启 |
| `CANDLE_CLI_INCLUDE_USAGE` | `true` | 请求流式 API 返回 usage；不兼容的本地后端可关闭 |
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
PYTHONPATH=python python3 -m pytest python -q
```

## 许可证

MIT
