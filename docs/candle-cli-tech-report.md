# candle-cli 项目技术说明报告

## 摘要

candle-cli 是一个面向 agentic coding 的命令行工具原型，采用 Rust 核心加 Python bridge 的分层架构。项目的设计方向受到 candle-org/candle 轻量级 AI runtime 及其 Cognitive Runtime、Agentic Kernel 路线启发，目标是在 CLI 层面构建一个让大语言模型能够通过工具接口参与本地软件开发任务的执行框架。

当前阶段，系统采用 API-first 策略调用模型（优先支持 DeepSeek API，同时兼容 Ollama、vLLM 和 OpenAI），以此降低模型部署门槛，使开发资源集中于 CLI 交互、agent loop、工具系统、权限控制、session 管理和执行追踪等工程能力的建设。Rust 侧负责所有系统控制逻辑，Python bridge 负责模型后端的请求转发和响应解析。

项目已实现了有界多步 agent loop（最大 8 步），包含 read、glob、grep、edit、shell 共 6 个工具，4 种权限模式，以及 `/tools`、`/status`、`/trace` 三个可观察性接口。后续可接入 candle 本地推理后端，增强代码编辑能力，并构建 self-development workflow。

---

## 1. 项目背景与设计动机

### 1.1 candle 对本项目的启发

[candle-org/candle](https://github.com/candle-org/candle) 是一个纯 Python 深度学习框架，核心特征是轻量（安装体积约 10 MB）、多硬件后端（CPU/CUDA/Apple MPS/Ascend NPU）和 PyTorch 兼容 API。candle 在其 roadmap 中规划了从 Foundation 到 Self-Hosting 的四阶段路线，其中 Phase 2 Cognitive Runtime 和 Phase 3 Agentic Kernel 明确提出将本地模型部署与 agent 系统结合，最终实现"模型改善模型"的自我进化闭环。

candle 的重点是底层框架和推理运行时，并未提供面向终端用户的命令行工具层。candle-cli 正是受这一思路启发，在 CLI 层面探索 agentic coding 的工程实现——不是从零构建推理引擎，而是在已有模型能力之上搭建 agent 执行框架。

### 1.2 candle-cli 的目标

candle-cli 的目标是构建一个模型与本地开发环境之间的可编程接口。具体来说，它希望让模型能够读取项目文件、搜索代码、编辑文本、运行 shell 命令，并在每一步的执行结果基础上继续推理。这种"行动—反馈—再行动"的模式使模型从问答工具转变为开发任务的主动参与者。

项目当前的重点是完成 agentic CLI 的执行框架本身（agent loop、工具系统、权限控制、session 管理），而非模型的训练或本地部署。模型调用优先使用 API，降低硬件门槛，后后续再根据需要对接到 candle 等本地推理后端。

---

## 2. 项目总体定位

candle-cli 当前可以从以下几个层面理解：

**Rust-first agentic CLI。** 项目以 Rust 为主要开发语言，提供 prompt 单轮模式、REPL 交互模式和 slash 命令体系。系统启动时创建 session，在 REPL 循环中接收用户输入，通过 agent loop 调用模型、解析工具请求、执行操作并收集反馈。

**API-first 模型调用工具。** 模型推理通过 OpenAI 兼容 API 完成，支持 DeepSeek、Ollama、vLLM 和 OpenAI 四个后端。用户只需配置三个环境变量（`CANDLE_CLI_API_BASE_URL`、`CANDLE_CLI_API_KEY`、`CANDLE_CLI_MODEL_ID`）即可使用。API-first 策略省去了模型权重下载、显存管理和量化配置等工程负担。

**面向本地开发任务的 AI coding assistant 原型。** 系统已具备读代码、搜文件、编辑文件、执行命令的多步工具链能力。它不是通用的聊天界面，而是专门为软件工程场景设计的命令行代理。

**未来可扩展到 candle backend 的 agentic runtime interface。** 系统的 `CandleTargetRuntime` trait 定义了统一的模型调用抽象，目前有三个实现：`MockRuntime`（测试用）、`LocalBridgeRuntime`（通过子进程调用 Python bridge）和 `CandleRuntime`（占位，预留 candle 后端接口）。未来接入 candle 本地推理时，上层 agent loop 和工具系统无需修改。

---

## 3. 系统架构设计

### 3.1 总体架构

系统由上到下分为以下几层：

- **CLI 层**（`src/cli/`）：命令行参数解析、REPL 交互循环、slash 命令分发。
- **Agent 层**（`src/agent/`）：agent loop 核心逻辑，包括多步执行控制、tool call 解析和 observation 反馈。
- **Tool 层**（`src/tools/`）：工具注册与执行分发，包含 read、glob、grep、edit、shell 等 6 个内置工具。
- **Permission 层**（`src/permissions/`）：4 种权限模式，在工具执行前进行判断，限制高风险操作。
- **Model 层**（`src/model/`）：`CandleTargetRuntime` trait 定义统一的模型调用接口。
- **Python bridge 层**（`python/`）：通过子进程 stdin/stdout JSON 协议连接 Rust 与 Python 模型后端。
- **Session 层**（`src/session/`）：对话上下文保存为 JSON 文件，支持列表、恢复和清空。

### 3.2 执行流程

一次完整的 agentic 请求按以下步骤执行：

1. CLI 接收用户输入，判断是内部命令（以 `/` 开头）还是模型提问。内部命令直接处理并展示结果；模型提问追加到 session 后进入 agent loop。
2. Agent loop 调用 `build_turn_request` 构造 `TurnRequest`，包含系统提示词（含工具调用协议说明和工具 JSON schema）、对话历史序列化和可用工具列表。
3. Model 层通过 `CandleTargetRuntime::generate_turn` 调用模型。在 bridge 模式下，Rust 启动 Python 子进程，由 Python bridge 向 API 发送请求并返回响应。
4. Agent loop 调用 `parse_tool_call` 解析模型响应中的 `<tool_call>` JSON 块。若响应中无工具调用，视为最终回答并返回。若 JSON 格式错误，追加纠正引导消息后继续循环。
5. 解析出 `ToolCallIntent` 后，Permission 层检查该工具在当前的权限模式下是否允许执行。
6. Tool 层执行对应工具，结果以统一格式（`status: ok/error`）包装后追加到 session。
7. Agent loop 回到步骤 2，将包含工具结果的完整消息历史发送给模型，进入下一轮推理。
8. 若达到最大步数（8 步），循环终止并输出提示信息。
9. Session 保存完整的消息历史，Trace 记录每一步的执行事件。
10. 用户可通过 `/trace` 查看执行链路，通过 `/status` 查看运行时状态，通过 `/tools` 查看可用工具。

---

## 4. 核心模块说明

### 4.1 CLI 模块

CLI 模块（`src/cli/repl.rs`、`args.rs`、`commands.rs`）是系统与用户的直接交互层。它提供三种入口模式：`cargo run -- prompt "..."` 执行单轮提问后退出；`cargo run --` 进入 REPL 循环；`cargo run -- doctor` 打印配置状态。

REPL 中的 slash 命令用于系统管理而非模型对话：`/exit` 退出，`/session` 查看会话信息，`/clear` 清空上下文，`/list` 和 `/resume` 管理历史 session，`/save` 显式保存，以及 `/tools`、`/status`、`/trace` 三个可观察性接口。CLI 层的主要职责是区分"应该交给模型处理的内容"和"应该由系统响应内部命令"。

### 4.2 Agent 模块

Agent 模块（`src/agent/loop.rs`、`tool_call.rs`、`trace.rs`）实现了 candle-cli 的核心执行逻辑。

`loop.rs` 中的 `run_single_turn_with_limit_and_trace` 函数是有界多步循环的主体：每步构造 `TurnRequest`、调用模型、解析响应、检查权限、执行工具、记录结果，直到模型输出最终回答或循环次数达到上限（默认 8 步）。

`tool_call.rs` 实现了文本 JSON 工具调用协议的解析。模型在响应中发出 `<tool_call>{"id":"call-1","name":"read","input":{...}}</tool_call>` 文本块，解析器提取 JSON 并验证 `id`、`name`、`input` 三个必选字段。解析失败时返回明确的错误类型（如 MissingCloseTag、InvalidJson、MissingStringField），agent loop 据此生成纠正提示让模型重试。

`trace.rs` 记录了每一步的执行事件（BuildTurnRequest、RuntimeGenerateTurn、ParseToolCall、ToolCall、ToolResult、FinalAnswer），为 `/trace` 接口提供数据来源。

### 4.3 Tool 模块

工具系统（`src/tools/registry.rs` 和 `builtin/` 目录）为模型提供访问本地环境的能力。`ToolRegistry` 负责工具的注册、参数解析和工作目录边界检查。当前包含 6 个工具：

- `pwd`：返回当前工作目录。
- `read`：读取指定 UTF-8 文本文件，需文件在工作目录范围内。
- `glob`：按模式匹配文件路径，支持 `*.rs`、`**/*.rs` 等格式，结果排序返回。
- `grep`：递归搜索文件内容，返回 `path:line:content` 格式的匹配行。
- `edit`：在文件中精确替换一处文本。0 次匹配或多次匹配均返回错误，避免误修改。
- `shell`：通过 `sh -lc` 执行命令，支持工作目录绑定和超时（默认 30 秒）。

工具的路径安全由 `ToolRegistry` 层面的 `resolve_existing_path` 和 `resolve_writable_path` 方法统一保证，工具实现本身不感知路径边界。

### 4.4 Permission 模块

权限控制（`src/permissions/mode.rs`、`policy.rs`）定义了四种模式，通过 `CANDLE_CLI_PERMISSION` 环境变量配置（默认 `workspace-write`）。

`read-only` 仅允许 pwd、read、glob、grep，拒绝任何可能修改文件的操作。`workspace-write` 允许所有工具，适用于受信任的本地开发环境。`prompt` 对只读工具自动放行，对 edit、write、shell 等操作需要用户确认（当前确认函数返回 false，为后续交互式确认预留接口）。`danger-full-access` 无任何限制。

权限检查嵌入在 agent loop 的工具执行路径中，不在独立的拦截层，避免绕过。工具被拒绝时，系统生成格式化的拒绝信息返回给模型，使其了解限制并调整策略。

### 4.5 Model 与 Python bridge 模块

Model 层（`src/model/runtime.rs`、`types.rs`、`bridge.rs`、`mock.rs`、`candle.rs`）的核心是 `CandleTargetRuntime` trait，定义了 `generate_turn`、`healthcheck` 和 `capabilities` 三个方法。

`LocalBridgeRuntime`（`bridge.rs`）当前是主要的运行时实现：它启动 Python 子进程（`python3 python/bridge_worker.py`），通过 stdin 发送 `{"type":"generate_turn","request":{...}}` JSON 请求，从 stdout 读取一行 JSON 响应并解析为 `TurnResult`。

Python bridge（`python/bridge_runtime.py`、`bridge_worker.py`、`bridge_prompt.py`、`model_config.py`）负责接收 Rust 的请求，将 Rust session 中的消息格式转换为 API 聊天格式（处理 Text、ToolCall 和 ToolResult 三种 ContentBlock 类型），构造 OpenAI 兼容的 HTTP 请求，解析响应并返回。API 请求体中加入 `"thinking":{"type":"disabled"}` 参数以兼容 DeepSeek V4。

这种分工将系统控制逻辑（Rust）与模型后端适配（Python）解耦，更换后端不影响上层代码。

### 4.6 Session 模块

Session 系统（`src/session/model.rs`、`store.rs`、`resume.rs`）将对话上下文序列化为 JSON 文件，保存内容包括 session ID、workspace 路径和完整的消息历史。消息历史中的每条 Message 包含 role（System/User/Assistant/Tool）和 blocks（Text/ToolCall/ToolResult），完整记录了 agent 的每一次交互和工具执行。

Session 的保存和恢复支持跨多次交互的长期开发任务。用户在退出后可通过 `/resume` 恢复之前的上下文，无需重新执行已完成的工具操作。

---

## 5. 关键接口设计：/tools、/status、/trace

这三个 slash 命令是 candle-cli 可观察性设计的关键组件，分别解决"系统有什么能力""系统当前什么状态""系统刚做了什么"三个问题。

### 5.1 `/tools`

`/tools` 接口调用 `ToolRegistry::tool_names()` 列出当前注册的所有工具。它向用户展示 agent 的能力边界：在 read-only 模式下，edit 和 shell 不会被列出为可调用；在 workspace-write 模式下，全部 6 个工具可用。这个接口帮助用户在开始任务前判断系统能否胜任，也帮助在调试时确认工具配置是否正确。

### 5.2 `/status`

`/status` 接口（由 `render_status_lines` 函数实现）展示当前运行时状态，包括：session ID 和消息数、workspace 路径、runtime 类型（mock/bridge）、模型 ID、API 后端地址（脱敏）、权限模式、最大保留对话轮数和工具列表。

当使用 API 模式时，系统只能展示本地环境信息（如 Python bridge 状态、本地工作目录），不能显示远程 API 服务器的显存或设备状态。系统支持通过 `CANDLE_CLI_VERBOSE=1` 在诊断输出中显示本地 GPU 信息（若可用）。

### 5.3 `/trace`

`/trace` 接口基于 `ExecutionTrace` 结构体，展示最近一次 agent 执行的步骤序列：build_turn_request → runtime.generate_turn → parse_tool_call → tool call → tool result → final answer。每一步以序号和事件类型呈现，帮助用户理解 agent 在哪些环节调用了哪些工具、每个工具的执行结果是什么。

需要区分的是，`/trace` 展示的是系统级执行链路，即系统在何时构造请求、调用模型、解析工具、执行操作、返回结果，而不是模型的私有 chain-of-thought 或内部推理过程。

---

## 6. 技术特色总结

1. **Rust-first CLI 控制层。** 系统的核心逻辑——CLI 交互、agent loop、工具执行、权限判断、session 管理和 trace 记录——全部由 Rust 实现，提供编译期类型安全和可预测的运行时行为。

2. **API-first 模型调用策略。** 模型推理通过 OpenAI 兼容 API 完成，用户无需下载模型权重或配置 GPU 环境，只需设置三个环境变量即可使用。这使开发资源能够聚焦于 agentic CLI 框架本身。

3. **Python bridge 后端适配。** Python bridge 以子进程方式运行，将 Rust 的 `TurnRequest` 转换为 API 请求，将 API 响应解析回 `TurnResult`。bridge 与 Rust 核心通过 JSON 行协议通信，更换模型后端只需调整 Python 侧配置，不影响 Rust 逻辑。

4. **文本 JSON 工具调用协议驱动的 agent loop。** 模型通过 `<tool_call>{"id":"...","name":"...","input":{...}}</tool_call>` 文本块请求工具，解析器在模型输出中查找并验证该格式。此协议不依赖特定 API 的 function calling 特性，任何遵循文本指令的模型均可使用。

5. **Permission-aware 本地执行控制。** 四种权限模式嵌入 agent loop 的工具执行路径，每次操作前自动检查。工作目录边界检查统一在 `ToolRegistry` 层面实现，工具本身不感知路径限制。

6. **`/tools`、`/status`、`/trace` 可观察性接口。** 三个接口分别回答"系统有什么能力""系统当前什么状态""系统刚做了什么"，为 agentic 系统提供了基本的行为可见性。

7. **面向 hybrid backend 的运行时抽象。** `CandleTargetRuntime` trait 是模型调用的统一接口，其 Mock、Bridge 和 Candle 三个实现覆盖了测试、API 调用和未来本地推理三种场景。接入 candle backend 只需实现新的 `CandleRuntime`，上层代码不感知变化。

---

## 7. 未来发展方向

**接入 candle backend。** 未来可在 `CandleRuntime` 占位实现的基础上，通过 candle 框架加载本地模型完成推理，形成 API + candle 的混合后端：网络可用时走 API，离线时回退到本地模型。

**增强代码编辑能力。** 当前 `edit` 工具实现了精确单次匹配替换，后续可扩展到 patch-style edit（支持行号偏移的多行修改）和 diff 预览，让代码修改更安全可控。

**扩展 `/tools`、`/status`、`/trace`。** 三个接口当前展示基本信息，可扩展到工具 schema 详情、API 调用耗时统计、trace 步骤的时间戳和错误详情。

**增强 project memory。** 可为每个项目引入记忆机制，记录项目结构索引、用户常用命令和任务上下文，使 candle-cli 在多轮开发中积累对项目的持续理解。

**构建 self-development workflow。** 当前系统已具备"读代码→改代码→跑测试→看结果"的能力基础，可将这些能力串联为自动化闭环：修改源码 → 运行测试 → 分析失败 → 自动修复 → 总结变更。

**补充 demo 和 examples。** 增加典型 agentic 任务的示例脚本和 demo 记录，展示系统在真实开发场景中的行为。

---

## 8. 总结

candle-cli 是一个面向 agentic coding 命令行工具原型，其核心价值不在于又一个模型聊天界面，而在于它构建了一套完整的 agent 执行基础设施：有界多步循环负责控制模型调用节奏，工具系统为模型提供文件读、搜索、编辑、命令执行等本地操作接口，权限系统管理高风险操作的安全边界，session 机制支持长周期开发任务的上下文延续，`/tools`、`/status`、`/trace` 三个接口提供系统行为的可见性。

项目受到 candle-org/candle 轻量级 AI runtime 技术路线的启发，当前采用 API-first 策略以降低使用门槛，将开发重心放在 agentic CLI 框架的工程实现上。Rust 核心与 Python bridge 的分层设计使系统控制逻辑与模型后端充分解耦，`CandleTargetRuntime` trait 为后续接入 candle 本地推理预留了清晰接口。

从定位上看，candle-cli 不是 candle 的替代或分支，而是 candle 技术理念在 CLI 交互层面的一次工程化探索。candle 解决"如何以轻量方式运行模型"，candle-cli 解决"如何让模型通过命令行参与开发任务"。二者的关系是底层推理框架与上层 agent 接口的互补。
