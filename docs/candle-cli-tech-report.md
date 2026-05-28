# candle-cli 项目结构与技术特色说明文档

## 摘要

candle-cli 是一个面向 agentic coding 的命令行工具原型，采用 Rust 核心加 Python bridge 的架构设计。项目受到 candle-org/candle 轻量级、多后端、agentic AI ready 技术路线的启发，致力于在 candle 所勾勒的 Cognitive Runtime 和 Agentic Kernel 理念基础上，探索面向终端用户的 agentic CLI 交互框架。

candle-cli 当前阶段的模型调用主要通过 OpenAI 兼容 API 完成，优先支持 DeepSeek API，同时兼容 Ollama、vLLM、OpenAI 等后端。采用 API-first 策略的目的是降低本地模型部署的硬件门槛和工程复杂度，使项目能优先聚焦于 CLI 交互、agent loop、工具系统、权限控制、session 管理、执行追踪和运行状态展示等工程能力的建设。

系统在架构上分为 CLI 层、Agent 层、Tool 层、Permission 层、Model 层、Python Bridge 层、Session 层、Runtime Status 层和 Trace 层。用户通过命令行输入后，系统将输入传入 agent loop，agent 构造上下文、调用模型、解析 tool call、执行权限检查、调用工具系统、收集执行结果并反馈给模型，形成多步推理闭环。`/tools`、`/status`、`/trace` 三个透明化接口使系统具备良好的可观察性和可调试性。

后续可以继续扩展为更完整的 Claude-Code-like agentic CLI，包括接入 candle 本地推理后端、增强代码编辑能力、引入 project memory 和 self-development workflow 等方向。

---

## 1. 项目背景

### 1.1 大语言模型与 Agentic CLI

传统的大语言模型主要通过文本生成完成问答任务：用户输入问题，模型返回回答，一次交互即结束。这类模式适用于信息查询、文本润色和知识问答，但无法深入参与软件开发的核心流程。

Agentic CLI 则进一步赋予模型访问本地环境的能力。模型不再仅仅"回答"，而是可以"行动"：读取项目源代码、搜索函数定义、执行 shell 命令、编辑文件内容，并根据每一步的执行结果决定下一步应该做什么。这种"感知—行动—反馈—再行动"的循环，使模型从被动回答者转变为主动参与者，能够帮助开发者在真实项目环境中完成理解代码、修改代码、运行测试、分析错误的完整开发闭环。

构建一个 agentic CLI 系统需要在传统对话模型之上额外实现以下关键能力：

- **Tool Calling**：定义和注册模型可调用的工具，使模型能够通过结构化输出请求执行本地操作。
- **Permission Control**：对高风险操作（如文件写入、shell 执行）进行权限检查，防止未授权的修改。
- **Session Management**：保存和恢复对话上下文，支持跨多次交互的长期开发任务。
- **Execution Trace**：记录模型调用链路、工具调用和结果，提供执行过程的可见性。
- **Runtime Status Monitoring**：展示当前系统配置、模型状态、权限模式和工具可用性。

这些能力共同构成了 agentic CLI 的基础设施，使其区别于普通的模型聊天工具。

### 1.2 candle 项目的技术背景

[candle-org/candle](https://github.com/candle-org/candle) 是一个纯 Python 深度学习框架，其核心定位是轻量级、PyTorch 兼容、多硬件后端支持。candle 项目不追求成为另一个庞大的训练框架，而是关注以下特性：

- **纯 Python 实现**：无 C++ 扩展，安装体积约 10 MB（PyTorch 约 2 GB），可在边缘设备上部署。
- **多后端支持**：CPU（NumPy）、CUDA（NVIDIA GPU）、Apple MPS（Metal Shaders）和 Ascend NPU（ACLNN 原生内核）。
- **PyTorch 兼容 API**：通过 `import torch` 零修改 drop-in 机制，使现有 PyTorch 代码可直接在 candle 上运行。
- **Agentic AI Ready**：轻量到可嵌入 AI agent 运行时，为 agent 系统提供本地推理能力。

candle 的 roadmap 中明确提出了从 Foundation 到 Self-Hosting 的四个阶段愿景：

1. **Phase 1 — Foundation**：完成核心张量操作、自动微分、神经网络模块和多后端适配。
2. **Phase 2 — Cognitive Runtime**：将本地模型部署作为一等公民，支持模型加载、量化、角色路由和多模型推理策略。
3. **Phase 3 — Agentic Kernel**：框架获得自我观察、诊断和行动的能力，通过 Dev Layer（调试模型）、Bootstrap Layer（生成模型）和 ModelOps Layer（评估模型）形成自我进化循环。
4. **Phase 4 — Self-Hosting**：本地模型不再仅是被管理的资产，而是成为 Agentic Kernel 本身的执行引擎，实现"模型改善模型"的连续自我改进闭环。

这些设计理念说明，轻量级模型运行框架可以进一步向 agentic execution、self-debugging 和 self-improving system 方向发展。

### 1.3 candle-cli 的开发动机

candle-cli 的开发动机直接来源于 candle 项目的技术路线启发。candle 在框架层面勾勒了从轻量深度学习框架到 Agentic Kernel 和 Self-Hosting 的演进路径，但 candle 本身定位于底层框架，并未提供面向终端用户的命令行交互层、agent loop 以及面向软件工程任务的工具系统。

candle-cli 正是为了填补这一空白而诞生的工程尝试。它的核心目标包括：

- 在 candle 技术路线基础上，开发一个面向 agentic coding 的实际可用命令行工具。
- 该工具不仅是模型问答界面，更希望成为模型与本地开发环境之间的执行接口和"操作系统"。
- 当前阶段优先使用 API 调用模型（而非本地加载模型权重），是为了降低模型部署复杂度，使项目重点集中在 agentic CLI 框架本身的工程设计上，包括 CLI 交互、agent loop、tools、permissions、session、trace 和 status 等核心模块。
- 后续可以根据需要接入 candle 或其他本地推理后端，从 API-first 演进为 API + local hybrid backend。

---

## 2. 项目总体定位

### 2.1 candle-cli 是什么

candle-cli 当前可以被理解为以下几个层次的叠加：

- 一个 **Rust-first terminal AI assistant**：以 Rust 为主要开发语言，通过命令行提供 prompt 单轮问答和 REPL 交互式多轮对话能力。
- 一个 **支持 API 模型调用的命令行大模型工具**：通过 OpenAI 兼容 API 连接到 DeepSeek、Ollama、vLLM 和 OpenAI 等模型后端，用户只需配置环境变量即可开始使用。
- 一个 **具有 tool calling 和 agent loop 的 agentic CLI 原型**：模型能够通过文本 JSON 格式（`<tool_call>` 标签）主动请求执行文件读取、代码搜索、文本编辑和 shell 命令，系统以有界多步循环的方式执行这些请求。
- 一个 **可以继续扩展为 AI coding assistant 的工程基础**：模块化架构允许后续增加更多工具、接入本地推理后端、增强权限控制和完善交互体验。

### 2.2 与 candle 的关系

candle 和 candle-cli 处于技术栈的不同层次：

- **candle** 是底层 AI runtime / framework 方向的参考基础。它解决的是"如何在多种硬件上以最小体积运行深度学习模型"的问题。
- **candle-cli** 是面向用户交互和 agentic workflow 的 CLI 层探索。它解决的是"如何让模型通过命令行工具参与真实软件开发流程"的问题。

candle-cli 当前不一定直接依赖 candle 完成本地推理——它的模型调用通过 API 完成。但 candle-cli 的设计目标与 candle 的 agentic AI ready、Cognitive Runtime 和 Agentic Kernel 思路高度一致：

1. 两者都关注 agentic execution —— candle 从框架底层为 agent 系统提供运行时支持，candle-cli 从 CLI 层面为 agent 行为提供工程实现。
2. 两者都遵循模块化、轻量化的设计原则 —— candle 追求纯 Python、小体积、多后端，candle-cli 追求 Rust 核心明确、Python bridge 解耦、工具系统可扩展。
3. 未来可以将 candle 作为 candle-cli 的本地模型推理后端之一，实现从 API-first 到 local-first 或 hybrid backend 的完整演进。

### 2.3 当前模型调用策略

candle-cli 当前优先使用 API 调用模型，这是经过权衡的工程决策：

1. **部署简单**：用户无需拥有高端 GPU 或下载数十 GB 的模型权重，只需一个 API 密钥即可开始使用。
2. **降低硬件门槛**：不需要关心 CUDA 版本、显存大小和模型量化方案。API 提供商已解决这些问题。
3. **便于快速验证 agentic CLI 框架**：项目可以优先开发 agent loop、tools、permissions、session、trace 和 status 等系统能力，这些才是 candle-cli 区别于普通聊天工具的核心价值。
4. **后端灵活切换**：由于使用 OpenAI 兼容 API 协议，可以在 DeepSeek、Ollama、vLLM 和 OpenAI 之间自由切换，无需修改代码。
5. **为本地模型预留空间**：后续可以结合 candle 或其他本地推理后端，实现 API fallback + local candle backend 的 hybrid model backend，同时兼顾使用便利性和本地部署能力。

---

## 3. 项目目录结构

| 路径 | 作用 | 在系统中的位置 |
|------|------|--------------|
| `README.md` | 英文版项目说明文档，包含快速开始、用法、配置和开发指南 | 项目入口文档 |
| `README_CN.md` | 中文版项目说明文档，与英文版内容镜像 | 中文入口文档 |
| `Cargo.toml` | Rust 项目配置文件，定义依赖（clap、serde、serde_json）、二进制目标和测试目标 | Rust 构建系统入口 |
| `Cargo.lock` | 依赖版本锁定文件 | 构建可复现性保障 |
| `model_config.json` | 模型默认配置文件（备选配置源，优先级低于环境变量） | 模型配置层 |
| `requirements.txt` | Python 依赖声明（pytest、transformers、torch） | Python 环境配置 |
| `src/main.rs` | 程序入口，解析 CLI 参数并根据子命令分发到 prompt 模式、REPL 模式或 doctor 模式 | CLI 入口层 |
| `src/lib.rs` | 库根文件，导出 `agent`、`cli`、`context`、`model`、`permissions`、`session`、`tools`、`ui` 八个顶层模块 | 模块组织入口 |
| `src/cli/` | CLI 层：命令行参数解析（`args.rs`）、slash 命令解析（`commands.rs`）和 REPL 主循环（`repl.rs`） | CLI 交互层 |
| `src/agent/` | Agent 层：agent loop（`loop.rs`）、tool call 解析器（`tool_call.rs`）、执行追踪（`trace.rs`）、turn 处理（`turn.rs`）和 agent 状态（`state.rs`） | Agent 执行核心 |
| `src/tools/` | 工具系统：类型定义（`types.rs`）、工具注册与分发（`registry.rs`）和内置工具实现（`builtin/` 目录） | 工具执行层 |
| `src/permissions/` | 权限系统：权限模式定义（`mode.rs`）、权限策略判断（`policy.rs`）和危险操作确认（`prompt.rs`） | 安全控制层 |
| `src/model/` | 模型调用层：运行时 trait 定义（`runtime.rs`）、请求/响应类型（`types.rs`）、mock 运行时（`mock.rs`）、Python bridge 运行时（`bridge.rs`）和 candle 运行时占位（`candle.rs`） | 模型抽象层 |
| `src/context/` | 上下文组装：context builder（`builder.rs`）、token 预算估算（`budget.rs`）和对话裁剪（`compact.rs`） | 上下文管理层 |
| `src/session/` | 会话管理：session 数据模型（`model.rs`）、文件存储（`store.rs`）和最新会话查找（`resume.rs`） | 会话持久化层 |
| `src/ui/` | 终端输出：文本渲染（`render.rs`）、状态格式化（`format.rs`）和 spinner（`spinner.rs`） | UI 输出层 |
| `python/` | Python bridge 代码：worker 入口（`bridge_worker.py`）、运行时核心（`bridge_runtime.py`）、JSON 协议编解码（`bridge_protocol.py`）、消息格式转换（`bridge_prompt.py`）、模型配置管理（`model_config.py`） | Python 桥接层 |
| `tests/` | Rust 测试目录，按模块分为 `cli/`、`agent/`、`tools/`、`permissions/`、`session/`、`model/` 子目录 | 测试系统 |
| `docs/` | 项目设计文档，包含 `specs/`（设计规格）和 `plans/`（实施计划） | 设计文档 |
| `examples/` | Python 独立示例脚本：API 推理示例和本地 transformers 推理示例 | 示例代码 |

---

## 4. 系统总体架构

### 4.1 架构概览

candle-cli 的系统架构可以分为以下层次：

1. **CLI Layer**（`src/cli/`）：负责命令行输入解析、REPL 交互循环、用户命令和内部 slash 命令分发。是用户与系统之间的入口。
2. **Agent Layer**（`src/agent/`）：负责 agent loop 核心逻辑，包括多轮执行控制、tool call 解析、工具执行结果接收和模型反馈循环。是系统的大脑。
3. **Tool Layer**（`src/tools/`）：负责文件读取、文件搜索、文件编辑、shell 执行等本地操作能力。是模型接触本地环境的"手"。
4. **Permission Layer**（`src/permissions/`）：负责判断工具调用是否允许执行，包括四种权限模式和对高风险操作的确认机制。是系统的安全守门人。
5. **Model Layer**（`src/model/`）：负责模型调用抽象，定义了 `CandleTargetRuntime` trait，提供 `MockRuntime`、`LocalBridgeRuntime` 和 `CandleRuntime`（占位）三种实现。是系统的"引擎"接口。
6. **Python Bridge Layer**（`python/`）：负责将 Rust 的模型调用请求转换为 Python 逻辑，通过子进程 stdio JSON 协议连接实际的模型推理（API 调用或本地 transformers 模型加载）。是 Rust 与 Python/API 之间的桥梁。
7. **Session Layer**（`src/session/`）：负责将对话上下文（消息历史、workspace 信息）序列化为 JSON 文件，支持保存、加载、列表和恢复操作。是系统的"记忆"。
8. **Runtime Status Layer**（`src/cli/repl.rs` 中的 `/status` 命令处理）：负责展示运行时状态，包括模型配置、API backend 状态、权限模式、session 和 workspace 信息。是系统的"仪表盘"。
9. **Trace Layer**（`src/agent/trace.rs`）：负责记录和展示最近一次 agent 执行链路，包括 build_turn_request、runtime.generate_turn、parse_tool_call、tool call、tool result 和 final answer 等步骤。是系统的"黑匣子"。

### 4.2 系统数据流

一次完整的 agentic 交互流程包含以下步骤：

1. 用户输入 prompt（如 `"Read README.md and summarize"`）或 REPL 中的消息。
2. CLI（`src/cli/repl.rs` 中的 `run_repl` 或 `run_prompt`）接收输入，判断是否为以 `/` 开头的内部命令。若是内部命令，执行对应逻辑（如 `/status`、`/trace`、`/tools`）；否则将输入作为用户消息追加到 session。
3. CLI 调用 agent loop 入口 `run_single_turn` 或 `run_single_turn_with_trace`（`src/agent/loop.rs`）。
4. Agent 通过 `build_turn_request`（`src/context/builder.rs`）构造 `TurnRequest`，其中包括系统提示词（含工具调用协议指导）、对话历史 JSON 和可用工具 JSON。
5. Model layer 通过 `CandleTargetRuntime` trait 的 `generate_turn` 方法调用模型。若配置为 bridge 模式，则通过 `LocalBridgeRuntime`（`src/model/bridge.rs`）启动 Python 子进程，由 Python bridge 向 API 发送请求。
6. 模型返回文本响应。若响应中包含 `<tool_call>{"id":"...","name":"...","input":{...}}</tool_call>` 文本块，agent 通过 `parse_tool_call`（`src/agent/tool_call.rs`）解析出 `ToolCallIntent`。
7. Permission system（`src/permissions/policy.rs` 中的 `PermissionPolicy`）检查该工具调用是否在当前权限模式下被允许执行，并对高风险操作执行确认判断。
8. Tool system（`src/tools/registry.rs` 中的 `ToolRegistry`）根据工具名称和输入参数执行对应工具（`read`、`glob`、`grep`、`edit`、`shell` 等），返回执行结果或错误信息。
9. 工具执行结果作为 observation 以 `ContentBlock::ToolResult` 形式追加到 session 消息历史中。
10. Agent loop 继续执行下一轮迭代：再次构造 `TurnRequest`，将包含工具结果的完整消息历史发送给模型。
11. 模型可能继续请求工具，或给出最终回答。若模型输出不包含有效的 `<tool_call>` 块，agent loop 终止。
12. 若达到最大步数（`DEFAULT_MAX_TOOL_STEPS = 8`），agent loop 结束并输出步数超限提示。
13. Trace layer（`src/agent/trace.rs` 中的 `ExecutionTrace`）记录每一步的执行事件，包括 BuildTurnRequest、RuntimeGenerateTurn、ParseToolCall、ToolCall、ToolResult 和 FinalAnswer。
14. Session system 将完整的消息历史保存到 JSON 文件。
15. 用户可以通过 `/trace` 查看最近一次执行链路，通过 `/status` 查看运行时状态，通过 `/tools` 查看可用工具列表。

---

## 5. Rust 核心模块说明

### 5.1 `src/main.rs`

`main.rs` 是程序的唯一入口点。它使用 `clap` 库的 derive 模式解析命令行参数，根据用户输入的子命令分发到三种模式：

- `prompt "..."` 模式：调用 `run_prompt`（`src/cli/repl.rs`），执行一次模型调用并输出结果，然后退出。
- `doctor` 模式：输出当前 runtime 类型和 session 存储目录。
- 无参数模式：调用 `run_repl`（`src/cli/repl.rs`），进入交互式 REPL 循环。

此外，`main.rs` 还通过 `session_dir()` 函数解析 session 文件的存储路径，优先使用 `CANDLE_CLI_SESSION_DIR` 环境变量，否则使用系统临时目录下的 `candle-cli-sessions` 子目录。

### 5.2 `src/cli/`

CLI 模块是用户与 agent 系统之间的直接交互界面，由三个文件组成：

- **`args.rs`**：使用 `clap::Parser` 和 `clap::Subcommand` derive 宏定义命令行参数结构。`Cli` 结构体包含 `--resume` 标志和 `CommandMode` 子命令枚举。`CommandMode` 当前支持 `Prompt { input }` 和 `Doctor` 两种子命令。
- **`commands.rs`**：提供一个简单的 `parse_slash_command` 函数，将以 `/` 开头的用户输入解析为命令名称。
- **`repl.rs`**：CLI 模块的核心文件，包含以下关键功能：
  - `run_repl`：REPL 主循环，读取用户输入、分发 slash 命令、创建工具注册表（`ToolRegistry::workspace_write`）、调用 agent loop、保存 session 和输出结果。
  - `run_prompt`：单轮 prompt 模式，逻辑与 REPL 类似但只执行一次。
  - `handle_slash_command`：处理 `/exit`、`/help`、`/tools`、`/status`、`/trace`、`/system`、`/clear`、`/session`、`/list`、`/resume`、`/save` 等内部命令。还包括 `resolve_permission_mode` 函数从环境变量解析权限模式。
  - `render_status_lines`：为 `/status` 命令生成运行时状态信息行，包括 session ID、消息数量、workspace、运行时、模型、后端、权限模式、对话轮数和工具列表。

CLI 层的核心职责是区分"应该发送给模型的用户输入"和"应该由系统本身处理的内部命令"，前者交给 agent loop 处理，后者直接执行并展示结果。

### 5.3 `src/agent/`

Agent 模块是 candle-cli 的执行核心，负责将模型调用、工具执行和结果反馈编织成有界多步循环。模块由以下文件组成：

- **`loop.rs`**：实现了完整的 agent loop。核心函数为 `run_single_turn_with_limit_and_trace`，其执行流程为：
  1. 对每一步（最大 `DEFAULT_MAX_TOOL_STEPS = 8` 步），调用 `build_turn_request` 构造 `TurnRequest`。
  2. 调用 `runtime.generate_turn` 获取模型响应。
  3. 调用 `parse_tool_call` 解析响应中的工具调用。
  4. 若解析出有效工具调用，通过 `PermissionPolicy` 检查权限，执行工具，将结果格式化为 `"status: ok"` 或 `"status: error"` 格式并追加到 session。
  5. 若解析失败（格式错误），追加包含重试引导的纠正消息。
  6. 若无工具调用，将模型响应作为最终回答返回。
  7. 若达到最大步数，输出步数超限提示。

  模块还提供 `tools_json()` 函数，返回当前所有可用工具的 JSON schema 描述，用于在系统提示词中告知模型可用的工具集合。

- **`tool_call.rs`**：实现了文本 JSON 工具调用协议的解析器。`parse_tool_call` 函数在模型输出中查找 `<tool_call>` 和 `</tool_call>` 标签对，将其中的内容作为 JSON 解析，提取 `id`、`name` 和 `input` 字段。解析器定义了 `ToolCallParseError` 枚举，包含 MissingCloseTag、InvalidJson、MissingStringField、InputMustBeObject 和 OuterMustBeObject 五种错误类型，每种错误都有对应的引导性错误消息，帮助模型在下一次尝试中修正格式。

- **`trace.rs`**：定义了 `ExecutionTrace` 结构体和 `TraceEvent` 枚举。TraceEvent 包含 BuildTurnRequest、RuntimeGenerateTurn、ParseToolCall、ToolCall、ToolResult 和 FinalAnswer 六种事件类型。ExecutionTrace 提供 `push`、`is_empty` 和 `render_lines` 方法，支持在 REPL 中通过 `/trace` 命令展示最近一次执行链路。

- **`turn.rs`**：提供 `finish_turn` 函数，当前为恒等函数，在 agent loop 结束时对最终文本进行后处理。

- **`state.rs`**：定义了 `AgentState` 空结构体，为后续的 agent 状态管理预留空间。

### 5.4 `src/tools/`

工具系统是模型接触本地环境的接口。模块由类型定义、注册表和内置工具实现三部分组成：

- **`types.rs`**：定义了 `ToolResult = Result<String, String>` 类型别名。
- **`registry.rs`**：`ToolRegistry` 结构体是工具系统的核心。它持有 `allow_mutation` 布尔标志和 `workspace_root` 路径，提供以下关键能力：
  - `execute(&self, name: &str, input_json: &str) -> ToolResult`：根据工具名称和执行 JSON 输入分发到具体工具实现。对于 mutation 工具（`edit`、`write`、`shell`），在 `allow_mutation = false` 时返回明确的拒绝消息。
  - `resolve_existing_path` 和 `resolve_writable_path`：对文件路径进行规范化和工作目录边界检查，确保 `read`、`edit`、`write` 等操作不会超出 workspace 范围。
  - `shell_timeout`：从环境变量 `CANDLE_CLI_SHELL_TIMEOUT_SECS` 读取超时配置（默认 30 秒），传递给 shell 工具。
  - `tool_names`：返回所有已注册工具的名称列表，供 `/tools` 命令使用。
- **`builtin/`**：包含六个内置工具的实现文件：
  - `pwd.rs`：返回当前工作目录路径。
  - `read.rs`：读取 UTF-8 编码的文本文件，要求路径为文件（非目录），支持工作目录边界检查。
  - `glob.rs`：根据 glob 模式查找匹配文件，支持 `*.rs`、`**/*.rs` 和 `*suffix` 等模式，结果按字母序排列。
  - `grep.rs`：递归搜索目录中的文件内容，返回 `path:line_number:content` 格式的匹配行。
  - `edit.rs`：在文件中精确替换一处文本匹配。若 `old_string` 未匹配到（0 次）或匹配到多次（>1 次），返回错误而非执行替换。
  - `shell.rs`：通过 `sh -lc` 执行 shell 命令，支持工作目录设定和超时保护。

### 5.5 `src/permissions/`

权限控制系统确保 agent 的高风险操作在可管理的安全边界内执行。模块由三个文件组成：

- **`mode.rs`**：定义了 `PermissionMode` 枚举，包含四种模式：
  - `ReadOnly`：仅允许只读操作。
  - `WorkspaceWrite`：允许所有工具执行，不需要用户确认。
  - `DangerFullAccess`：允许所有工具执行，不需要用户确认。
  - `Prompt`：只读工具自动允许，修改工具需要用户确认。
- **`policy.rs`**：`PermissionPolicy` 结构体提供 `allows` 和 `requires_prompt` 两个判断方法。`allows` 根据当前权限模式决定某个工具是否可用；`requires_prompt` 判断是否需要用户交互确认。
- **`prompt.rs`**：提供 `confirm_dangerous_action(tool_name, input_json) -> bool` 函数，用于在执行高风险操作前请求用户确认。当前返回 `false`（拒绝），为后续的交互式确认机制预留接口。

权限控制被嵌入到 agent loop 中（`src/agent/loop.rs` 的 `run_single_turn_with_limit_and_trace` 函数），在每次工具执行前检查权限。若工具不被允许执行，系统会生成格式化的错误信息返回给模型，告知权限拒绝原因。

### 5.6 `src/model/`

模型调用层定义了统一的运行时抽象，使 CLI 和 agent 层不依赖于具体的模型实现细节。

- **`runtime.rs`**：定义了 `CandleTargetRuntime` trait，包含三个核心方法：
  - `generate_turn(&mut self, request: TurnRequest) -> Result<TurnResult, String>`：执行一次模型调用。
  - `healthcheck(&self) -> RuntimeHealth`：检查运行时健康状态。
  - `capabilities(&self) -> RuntimeCapabilities`：报告运行时能力（是否支持工具、是否支持流式输出）。
- **`types.rs`**：定义了模型交互的数据类型，包括 `TurnRequest`（系统提示词 + 消息 JSON + 工具 JSON）、`TurnResult`（最终文本 + 工具调用列表）、`ToolCallIntent`（工具 ID + 名称 + 输入 JSON）、`RuntimeEvent`、`RuntimeCapabilities` 和 `RuntimeHealth`。
- **`mock.rs`**：`MockRuntime` 实现，返回固定的 `"mock response"` 文本，用于在没有配置真实模型后端时进行开发测试。
- **`bridge.rs`**：`LocalBridgeRuntime` 实现，通过启动 Python 子进程、使用 stdin/stdout JSON 行协议与 `python/bridge_worker.py` 通信。每次 `generate_turn` 调用发送 `{"type": "generate_turn", "request": {...}}` 请求，读取一行 JSON 响应并解析为 `TurnResult`。
- **`candle.rs`**：`CandleRuntime` 占位实现，所有方法返回 `"not implemented"`。为后续直接接入 candle 推理引擎预留接口。

当前阶段的模型调用优先采用 API 方式（通过 `LocalBridgeRuntime` 调用 Python bridge，Python bridge 再通过 `urllib.request` 调用 OpenAI 兼容 API）。这种方式的优势在于：
- 无需本地加载模型权重，降低了硬件需求和部署复杂度。
- 可通过环境变量灵活切换不同的 API 后端（DeepSeek、Ollama、vLLM、OpenAI）。
- 使系统更容易运行和测试，开发者可以将精力集中在 agentic CLI 框架本身。

后续可以扩展为 API、本地模型、candle backend 或混合后端，在 `CandleTargetRuntime` trait 的统一抽象下无缝切换。

### 5.7 `src/session/`

会话管理模块负责对话上下文的持久化存储和恢复。

- **`model.rs`**：定义了核心数据结构：
  - `Session`：包含 `session_id`（基于 Unix 时间戳生成）、`workspace_root`（项目根目录路径）和 `messages`（Message 列表）。
  - `Message`：包含 `role`（System/User/Assistant/Tool）和 `blocks`（ContentBlock 列表）。
  - `ContentBlock`：支持三种类型——`Text`（纯文本）、`ToolCall`（工具调用记录，含 id、name 和 input）、`ToolResult`（工具执行结果，含 tool_call_id、output 和 is_error 标志）。
- **`store.rs`**：`SessionStore` 将 Session 序列化为 JSON 文件（`{session_id}.json`），提供 `save`、`load` 和 `list` 三个方法。
- **`resume.rs`**：`latest_session_id` 函数通过文件修改时间查找最近的 session，支持 `--resume` 模式下自动恢复上一次对话。

Session 系统使 candle-cli 能够支持跨多次交互的长期开发任务。用户在退出 REPL 后可以恢复之前的对话上下文，继续未完成的 agentic 任务。

---

## 6. Python bridge 与 API 模型调用说明

### 6.1 Python bridge 的作用

Python bridge 是连接 Rust 核心与模型推理后端的桥梁。它存在的根本原因是：Rust 生态中目前缺少与 HuggingFace `transformers` 库同等成熟度的模型加载和推理工具链。通过在 Python 侧调用 `transformers` 或 `urllib.request`，candle-cli 可以无缝利用 Python 生态中丰富的模型资源。

Python bridge 由五个文件组成：

- **`bridge_worker.py`**：worker 入口，从 stdin 读取 JSON 行，根据请求类型（`healthcheck`、`generate_turn`、`shutdown`）分发给 `BridgeRuntime`。
- **`bridge_runtime.py`**：核心运行时，包含 `BridgeRuntime` 类，负责模型的懒加载（`_ensure_initialized`）、API 模式生成（`_generate_via_api`）、本地模型生成（`_generate_local`）和 fallback 处理。
- **`bridge_protocol.py`**：JSON 协议编解码，提供 `encode_ok(payload)`、`encode_error(message)` 和 `decode_request(line)` 函数。
- **`bridge_prompt.py`**：消息格式转换，将 Rust session 中序列化的 `Message` 结构（含 Text、ToolCall、ToolResult 等 ContentBlock 类型）转换为 API 所需的聊天消息格式。
- **`model_config.py`**：配置管理，支持 JSON 文件 + 环境变量两级覆盖，管理模型 ID、设备、生成长度、温度、API 地址等参数。

### 6.2 当前 API-first 模型调用策略

candle-cli 当前优先通过 OpenAI 兼容 API 进行模型调用。这一策略具有以下优势：

1. **使用方便**：用户只需配置三个环境变量（`CANDLE_CLI_API_BASE_URL`、`CANDLE_CLI_API_KEY`、`CANDLE_CLI_MODEL_ID`）即可开始使用。
2. **不依赖本地大模型权重**：无需下载数十 GB 的模型文件，无需配置 CUDA 或 NPU 环境。
3. **降低显存压力**：模型推理在远端服务器完成，本地机器只需运行轻量的 CLI 程序。
4. **便于快速测试 agentic CLI 框架**：开发者可以专注验证 agent loop、tool system 和 permission control 的正确性，而不被模型部署问题分散精力。
5. **后端灵活切换**：通过修改环境变量即可在 DeepSeek、Ollama、vLLM 和 OpenAI 之间切换，无需修改任何代码。

### 6.3 Rust 与 Python/API 的分工

系统的职责分离清晰：

- **Rust 侧负责**：CLI 交互、agent loop 控制、tool call 解析、工具执行、权限检查、session 管理、trace 记录和 status 展示。这些是决定系统行为和可靠性的核心控制逻辑。
- **Python bridge / API backend 负责**：接收 Rust 发送的 `TurnRequest`，构造 API 请求体，发送 HTTP 请求，解析 API 响应，将结果返回给 Rust。Python bridge 不参与 agent loop 的控制逻辑。

这种设计使系统控制层和模型调用层充分解耦。更换模型后端（如从 DeepSeek API 切换到本地 Ollama）不影响 Rust 核心的任何逻辑。

### 6.4 未来与 candle backend 的关系

当前 API-first 是工程上更直接的路线，但 candle-cli 的架构设计已为后续接入 candle 本地推理后端做好了准备：

- `CandleTargetRuntime` trait 是一种统一抽象，`MockRuntime`、`LocalBridgeRuntime` 和 `CandleRuntime`（占位）都实现了该 trait。接入 candle backend 只需实现一个新的 `CandleRuntime`。
- `CandleRuntime` 占位文件（`src/model/candle.rs`）已存在于项目中，为后续实现预留了接口。
- 未来可以形成 API fallback + local candle backend 的 hybrid model backend：当网络可用时优先使用 API，网络不可用时回退到本地 candle 推理；或者读操作使用本地模型以降低延迟和成本，复杂推理使用云端 API。
- 这种 hybrid 架构可以同时兼顾使用便利性和本地部署能力，也与 candle 项目 roadmap 中的 Cognitive Runtime 和 Agentic Kernel 方向一致。

---

## 7. Agent loop 机制说明

### 7.1 Agent loop 的基本思想

普通聊天模型调用是一次性的：用户输入 → 模型输出 → 结束。这种模式无法让模型在"行动后根据反馈调整策略"。

Agent loop 的核心思想是赋予模型"行动—感知—再行动"的能力。模型不仅输出文本，还可以在文本中嵌入工具调用请求。系统解析这些请求、执行对应操作、将结果反馈给模型，模型再根据结果决定下一步——继续请求工具，还是给出最终回答。这个循环使得模型能够执行多步推理和操作序列。

### 7.2 当前流程

candle-cli 的 agent loop 实现在 `src/agent/loop.rs` 的 `run_single_turn_with_limit_and_trace` 函数中，流程如下：

```
for step in 0..DEFAULT_MAX_TOOL_STEPS (8):
    1. build_turn_request(session, tools_json) → TurnRequest
    2. runtime.generate_turn(request) → TurnResult (模型响应文本)
    3. parse_tool_call(result.final_text) → 解析结果:
       a. Ok(Some(tool_call)) → 权限检查 → 执行工具 → 记录 ToolResult → 继续循环
       b. Ok(None) → 作为最终回答 → 追加 Assistant 文本消息 → 返回
       c. Err(parse_error) → 追加纠正引导消息 → 继续循环
4. 达到最大步数: 返回步数超限提示
```

关键设计特点：

- **有界循环**：最大步数默认 8，防止无限循环消耗 API 额度。
- **格式错误可恢复**：当模型输出的工具调用格式不正确时（如 JSON 解析失败、缺少必需字段），系统不直接失败，而是追加一条引导消息告知模型正确格式，然后继续循环让模型重试。
- **工具结果格式化**：工具执行结果被格式化为 `"status: ok\ntool: {name}\noutput:\n{output}"` 或 `"status: error\ntool: {name}\nmessage: {error}"` 的统一格式，帮助模型理解执行状态。
- **权限拒绝反馈**：当工具因权限不足被拒绝执行时，系统生成明确的拒绝信息返回给模型，让模型理解为什么操作未能执行。

### 7.3 Agentic 能力体现

candle-cli 当前体现的 agentic 能力包括：

- 读取项目文件（`read`）：模型可以主动读取 README.md、源代码、配置文件等，而非只能依赖训练时的记忆。
- 搜索代码和文件（`grep`、`glob`）：模型可以搜索函数定义、变量引用和文件路径。
- 编辑文件（`edit`）：模型可以对项目文件进行精确单次匹配替换。
- 执行 shell 命令（`shell`）：模型可以运行 `cargo test`、`git status`、`cat` 等命令。
- 多步推理链：模型可以执行 read → edit → shell → final answer 的完整工具链，每一步基于前一步的结果决定下一步。
- 错误恢复：工具执行失败或格式错误时，模型可以重试或更换策略。
- 会话持久化：执行过程被完整记录到 session 中，可以恢复继续。

---

## 8. Tool system 说明

### 8.1 工具系统总体设计

工具系统（`src/tools/`）是模型接触本地环境的唯一接口。在设计理念上：

- 每个工具封装了一个具体的本地操作能力（读文件、搜索代码、执行命令等）。
- 所有工具共享统一的调用接口：`execute(name: &str, input_json: &str) -> Result<String, String>`。
- 输入通过 JSON 字符串传递，解析由 `ToolRegistry` 统一处理，确保输入验证的一致性。
- 输出统一为文本字符串，便于追加到对话上下文和返回给模型。
- 工作目录边界检查（`resolve_existing_path`、`resolve_writable_path`）确保读/写/编辑操作不会超出 workspace 范围。

### 8.2 已有工具说明

| 工具 | 功能 | 是否修改文件 | 风险等级 | 在 agentic coding 中的作用 |
|------|------|------------|---------|--------------------------|
| `pwd` | 显示当前工作目录路径 | 否 | 低 | 帮助模型确认当前所在目录，为后续文件操作提供路径参考 |
| `read` | 读取 UTF-8 文本文件内容 | 否 | 低 | 让模型获取项目文件内容，是代码理解和分析的基础能力 |
| `glob` | 按 glob 模式查找匹配文件（支持 `*.rs`、`**/*.rs`） | 否 | 低 | 帮助模型了解项目文件结构，定位目标文件 |
| `grep` | 递归搜索文件内容中的匹配行 | 否 | 中（可能读取大量文件） | 帮助模型查找函数定义、变量引用、配置项等 |
| `edit` | 在文件中精确替换一处文本匹配 | **是** | 高（修改文件内容） | 让模型能够实施代码修改，是 agentic coding 的关键能力 |
| `shell` | 通过 shell 执行命令 | **可能**（取决于命令） | 高（可执行任意命令） | 让模型能够运行测试、编译代码、检查环境状态 |

### 8.3 `/tools` 接口说明

`/tools` 接口（在 `src/cli/repl.rs` 的 `handle_slash_command` 函数中实现）是系统透明性的重要组成部分。当用户在 REPL 中输入 `/tools` 时，系统调用 `ToolRegistry::tool_names()` 获取已注册工具列表，展示给用户。

`/tools` 的核心价值在于：

- **展示系统能力边界**：用户可以清楚地知道 agent 当前拥有哪些工具，从而判断任务是否在系统能力范围内。
- **辅助调试**：当 agent 执行与预期不符时，用户可以通过 `/tools` 查看可用工具集合，判断是否缺少所需工具。
- **提高透明度**：避免用户对"模型能做什么"产生误解或盲目信任。
- **为后续扩展提供基础**：未来可以展示每个工具的详细 schema、参数格式、权限要求和风险等级，进一步提升系统的可解释性。

---

## 9. Permission system 说明

### 9.1 权限系统的必要性

agentic CLI 赋予模型修改文件内容和执行系统命令的能力，这带来了显著的安全风险。如果没有权限控制，模型可能在用户不知情的情况下删除文件、执行危险命令或访问敏感路径。权限系统存在的根本目的不是阻止用户使用这些能力，而是确保模型对高风险操作的调用处于用户可控的安全边界内。

### 9.2 当前权限模式

权限模式通过 `CANDLE_CLI_PERMISSION` 环境变量配置（默认为 `workspace-write`）：

| 模式 | 含义 | 适用场景 |
|------|------|---------|
| `read-only` | 仅允许 `pwd`、`read`、`glob`、`grep` 四个只读工具 | 代码审阅、项目理解、安全敏感环境 |
| `workspace-write` | 允许所有工具执行，无需用户确认 | 受信任的开发环境中的日常 agentic coding |
| `prompt` | 只读工具自动允许；`edit`、`write`、`shell` 需要用户确认 | 希望保留控制权但允许 agent 执行操作的场景 |
| `danger-full-access` | 允许所有工具，无需确认 | 隔离的测试环境中需要完全自动化执行时 |

### 9.3 权限系统的特色

candle-cli 的权限系统具有以下特色：

- **嵌入 agent loop**：权限检查不是独立于 agent 执行的，而是在 agent loop 内部（`run_single_turn_with_limit_and_trace`）每次工具执行前自动触发，确保不被绕过。
- **拒绝透明**：当工具被拒绝执行时，系统生成格式化的错误信息（如 `"status: error\ntool: shell\nmessage: tool not allowed in read-only mode: shell"`）返回给模型，让模型了解执行被拒绝的原因并调整策略。
- **Human-in-the-loop 接口预留**：`confirm_dangerous_action` 函数为后续的交互式确认机制预留了接口。当权限模式为 `prompt` 且操作需要确认时，该函数会被调用以请求用户批准。
- **环境变量驱动**：权限模式通过环境变量配置，不依赖配置文件，既便于快速切换，也降低了配置文件被意外修改的风险。

---

## 10. Status system 说明

### 10.1 `/status` 接口的作用

`/status` 接口（在 `src/cli/repl.rs` 中的 `handle_slash_command` 和 `render_status_lines` 函数中实现）用于展示当前 CLI 的运行状态。当用户在 REPL 中输入 `/status` 时，系统输出以下信息：

- Session 信息：session ID、消息数量、workspace 路径。
- 运行时信息：当前 runtime 类型（mock/bridge）、模型 ID、API 后端地址（安全脱敏）。
- 权限信息：当前权限模式（read-only/workspace-write/prompt/danger-full-access）。
- 配置信息：最大对话轮数。
- 工具信息：已注册的工具名称列表。

`/status` 的核心价值在于让用户在任何时候都能了解"系统当前处于什么运行环境中"——使用的是什么模型、具备哪些权限、是否有工具可用。这种透明性对于 agentic 系统的可信使用至关重要。

### 10.2 显存和设备状态展示

显存状态展示功能主要体现在 Python bridge 的 verbose 诊断输出中（`bridge_runtime.py` 的 `_gpu_memory_info` 方法）。当用户设置 `CANDLE_CLI_VERBOSE=1` 时，bridge 会尝试检测本地 GPU 显存状态（通过 `torch.cuda.memory_allocated` 和 `torch.cuda.memory_reserved`）并输出到 stderr。

需要明确的是：当使用 API 模式调用远程模型时，系统只能显示本地设备的显存状态，不能显示远程 API 服务器的显存状态。显存展示功能主要为以下场景设计：

- 对本地模型或未来 candle backend 的显存使用监控。
- 帮助用户判断当前环境是否适合加载本地模型。
- 帮助诊断 GPU/NPU 是否被系统正确识别。
- 为后续 local-first agentic runtime 的资源配置和管理做准备。

---

## 11. Trace system 说明

### 11.1 `/trace` 接口的作用

`/trace` 接口（基于 `src/agent/trace.rs` 中的 `ExecutionTrace` 结构体，在 `src/cli/repl.rs` 中通过 `last_trace` 变量保存并展示）用于展示最近一次 agent 执行的完整链路。当用户在 REPL 中输入 `/trace` 时，系统输出类似如下的执行步骤：

```
Last trace
1. build_turn_request
2. runtime.generate_turn
3. parse_tool_call
4. tool: read
5. tool result: ok
6. build_turn_request
7. runtime.generate_turn
8. parse_tool_call
9. tool: edit
10. tool result: ok
11. build_turn_request
12. runtime.generate_turn
13. parse_tool_call
14. final answer
```

需要明确的是：`/trace` 展示的是**系统级执行链路**——即系统在哪些步骤做了什么事情（构造请求、调用模型、解析工具、执行工具、返回结果），而不是模型的私有 chain-of-thought 或内部推理过程。trace 记录的是系统行为，不是模型思想。

### 11.2 Trace 对 agentic CLI 的意义

Agentic 系统天然具有不透明性：用户看到的是输入 prompt 和最终回答，中间的模型调用轮次、工具执行、权限检查和错误恢复对用户来说是一个黑箱。Trace 系统就是为了打开这个黑箱而设计的：

- **可观察性**：用户可以追溯 agent 为什么调用了某个工具，以及每一步的执行结果是什么。
- **可调试性**：当 agent 行为不符合预期时（如调用了错误的工具、重复请求同一操作、提前终止），用户可以通过 trace 定位问题发生在哪一步。
- **可信性**：展示执行链路有助于建立用户对 agent 行为的信任——用户可以看到系统确实执行了声称的操作。
- **报告和分析基础**：Trace 记录是后续撰写技术报告、制作 demo 和分析系统行为的结构化数据基础。

---

## 12. Session system 说明

### 12.1 Session 的作用

Session 系统（`src/session/`）负责保存和恢复对话上下文。其核心机制为：

- 将 `Session` 结构体（包含 session_id、workspace_root 和 messages 列表）序列化为 JSON 文件。
- 文件保存在 `CANDLE_CLI_SESSION_DIR` 指定的目录中（默认为系统临时目录下的 `candle-cli-sessions`）。
- 提供 `save`（保存）、`load`（按 ID 加载）、`list`（列出所有已保存 session）操作。
- 支持 `--resume` 标志自动恢复最近一次 session。

Session 的 messages 列表中，每条 Message 包含 role 和 blocks。blocks 支持三种 ContentBlock 类型：`Text`（普通文本）、`ToolCall`（工具调用记录，含工具 ID、名称和输入参数）、`ToolResult`（工具执行结果，含错误标志）。这种设计使得 session 不仅保存了对话文本，也保存了完整的 agent 执行链路信息。

### 12.2 在 agentic coding 中的意义

对于 agentic coding 场景，session 系统的价值体现在：

- **长期开发任务**：一个复杂的 agentic 任务（如重构一个模块）可能需要多轮交互才能完成。Session 允许用户在退出后恢复之前的对话状态，继续未完成的工作。
- **任务上下文保持**：模型在之前的轮次中已读取过的文件内容、已执行过的命令结果都保存在 session 中，恢复后无需重新执行。
- **审计和回溯**：Session 文件完整记录了 agent 的每一次操作（读了什么文件、编辑了什么内容、执行了什么命令），可以作为开发记录进行回溯。
- **跨会话协作**：不同的 session 对应不同的开发任务，用户可以在不同任务间切换而不丢失上下文。

---

## 13. CLI 交互能力说明

candle-cli 当前支持的 CLI 交互方式包括：

| 命令/模式 | 类型 | 说明 |
|-----------|------|------|
| `cargo run -- prompt "..."` | 子命令 | 单次 prompt 模式：执行一次模型调用，输出结果后退出 |
| `cargo run --` | 默认模式 | 进入 REPL 交互模式：支持多轮对话、slash 命令和 session 管理 |
| `cargo run -- doctor` | 子命令 | 打印运行时类型和 session 存储路径 |
| `/help` (`/h`) | Slash 命令 | 显示所有可用命令及其说明 |
| `/tools` | Slash 命令 | 展示当前已注册的工具名称列表 |
| `/status` | Slash 命令 | 展示运行时状态：session 信息、模型配置、权限模式、工具列表 |
| `/trace` | Slash 命令 | 展示最近一次 agent 执行的完整链路 |
| `/system` | Slash 命令 | 展示当前生效的系统提示词 |
| `/session` (`/info`) | Slash 命令 | 展示当前 session 的 ID 和消息数量 |
| `/clear` | Slash 命令 | 清空当前 session（保留 session ID） |
| `/list` (`/ls`) | Slash 命令 | 列出所有已保存的 session 及其消息数量 |
| `/resume <id>` | Slash 命令 | 恢复指定 ID 的 session |
| `/save` | Slash 命令 | 显式保存当前 session |
| `/exit` (`/quit`, `/q`) | Slash 命令 | 退出 REPL 并自动保存 session |

需要特别强调 `/tools`、`/status` 和 `/trace` 三个接口在系统中的独特地位：

- **`/tools`** 负责展示可调用工具集合，让用户知道 agent 的能力边界。
- **`/status`** 负责展示运行状态、模型配置、权限模式和工具状态，让用户了解系统当前处于什么环境中。
- **`/trace`** 负责展示最近一次 agent 执行链路，让用户追溯每一步的系统行为。

这三个接口共同构成了系统的"可观察性基础设施"，是 candle-cli 区别于普通聊天 CLI 的重要特色——它不仅让模型"做事"，也让用户"看见模型做了什么"。

---

## 14. 测试系统说明

### 14.1 Rust 测试

candle-cli 的 Rust 测试覆盖了项目的核心模块（共计 82 个测试，全部通过），按测试目标组织在 `tests/` 目录下的各子目录中：

- **CLI 测试**（`tests/cli/`）：覆盖二进制启动（`test_bootstrap.rs`）、命令行参数解析（`test_args.rs`）、slash 命令解析（`test_commands.rs`）、doctor 模式（`test_doctor_status.rs`）和完整的 REPL session 集成测试（`test_repl_session_integration.rs`，含 22 个测试），覆盖 prompt 模式、多轮对话、slash 命令、session 保存/恢复/列表等场景。
- **Agent 测试**（`tests/agent/`）：覆盖 agent loop 的多步工具执行（`test_agent_loop.rs`，含 8 个测试，包括 read→edit→shell→answer 完整链路、工具错误恢复、最大步数停止、格式错误恢复）、context builder（`test_context_builder.rs`）和 tool call 解析器（`test_tool_call_parser.rs`，含 7 个测试）。
- **Tools 测试**（`tests/tools/`）：覆盖只读工具（`test_read_only_tools.rs`，含 7 个测试，包括 pwd、read、glob、grep 的真实功能和错误处理）和写/编辑/shell 工具（`test_write_edit_shell.rs`，含 7 个测试，包括编辑精确匹配、0 次匹配、多次匹配和权限拒绝）。
- **Permissions 测试**（`tests/permissions/`）：覆盖权限策略的基本判断逻辑（`test_policy.rs`）。
- **Session 测试**（`tests/session/`）：覆盖 session 数据模型和文件存储的保存/加载（`test_model.rs`、`test_store.rs`）。
- **Model 测试**（`tests/model/`）：覆盖 runtime 类型定义（`test_runtime_contract.rs`）、mock runtime（`test_mock_runtime.rs`）和 bridge runtime 的端到端行为（`test_bridge_runtime.rs`，含 6 个测试）。

### 14.2 Python 测试

Python bridge 的测试（`python/test_bridge_runtime.py`，27 个测试，全部通过）覆盖以下方面：

- `ModelConfig` 的默认值和文件加载行为（2 个测试）。
- 环境变量对 `ModelConfig` 的覆盖行为（9 个测试，逐个测试每个环境变量）。
- `bridge_prompt` 的消息解析和格式转换（3 个测试）。
- `BridgeRuntime` 的懒加载、健康检查、verbose 配置和 fallback 行为（4 个测试）。
- 本地模型 mock 测试（2 个测试，模拟 transformers 加载和生成流程）。
- API 模式测试（5 个测试，覆盖 API 调用、系统提示词注入、空消息处理和 HTTP 错误 fallback）。

### 14.3 测试系统的价值

测试系统为 candle-cli 的持续开发和维护提供了关键保障：

- **回归保护**：完整的测试套件确保后续的功能扩展不会破坏现有 agentic 行为。
- **行为文档**：测试用例本身就是对系统期望行为的精确描述——例如 `test_agent_loop_runs_read_edit_shell_then_final_answer` 测试通过脚本化 runtime 验证了完整的 read→edit→shell→answer 链路。
- **CI 就绪**：所有测试可通过 `cargo test` 和 `python3 -m pytest` 一键运行，为后续接入 GitHub Actions CI 做好准备。

---

## 15. 项目技术特色

### 15.1 受到 candle 技术路线启发的 agentic CLI

candle-cli 的设计动机直接来源于 candle-org/candle 的轻量级、多后端和 agentic AI ready 路线。candle 在其 roadmap 中规划了从 Foundation 到 Cognitive Runtime、Agentic Kernel 再到 Self-Hosting 的四阶段演进路径，candle-cli 则可以理解为其在 CLI 交互层面的工程化探索——将"agentic"从框架概念落地为可交互的命令行工具。

### 15.2 Rust-first CLI 架构

以 Rust 为主要开发语言的架构选择带来了显著的工程优势：编译时类型安全、零成本抽象、内存安全和强大的并发支持。Rust 负责系统的所有控制逻辑（CLI、agent loop、tools、permissions、session、trace），确保核心行为的可靠性和可预测性。

### 15.3 API-first 模型调用策略

通过优先采用 API 调用模型，candle-cli 显著降低了使用门槛。用户无需 GPU 或模型下载，只需配置环境变量即可开始使用。这一策略使项目能够将开发资源集中在 agentic CLI 框架的核心能力（tools、permissions、session、trace、status）上，而非模型部署工程。

### 15.4 Python bridge 的模型生态兼容性

Python bridge（`python/bridge_worker.py` + `bridge_runtime.py`）通过子进程 stdio JSON 协议连接 Rust 核心与 Python 模型生态。这一设计既保留了 Rust 在系统控制层面的优势，又充分利用了 Python 在模型推理（transformers、torch）和 HTTP 调用方面的成熟工具链。同时，bridge 的抽象接口为后续接入不同的模型后端（candle、本地量化模型、自定义服务）提供了灵活空间。

### 15.5 Agent loop 设计

candle-cli 的 agent loop 不是一次性问答，而是支持 tool call、observation 和多轮执行的有界循环。默认最大步数为 8，格式错误可恢复（通过纠正引导消息让模型重试），权限拒绝有明确反馈。这种设计使系统具备了真正的 agentic 行为，而非仅仅在聊天中嵌入工具描述。

### 15.6 Tool system 模块化

read、glob、grep、edit、shell 等工具被封装为独立的模块，每个工具具有清晰的接口（`fn run(...) -> Result<String, String>`）。工作目录边界检查（`resolve_existing_path`、`resolve_writable_path`）被统一实现在 `ToolRegistry` 层面，工具本身不需要关心路径安全。新增工具只需在 `builtin/` 目录中添加实现文件并在 `registry.rs` 中注册即可。

### 15.7 Permission-aware 设计

权限检查被嵌入到 agent loop 的核心执行路径中（`run_single_turn_with_limit_and_trace`），确保每次工具执行前都经过权限验证。四种权限模式（read-only、workspace-write、prompt、danger-full-access）覆盖了从安全审阅到完全自动化的不同使用场景。权限拒绝信息以统一格式返回给模型，使模型能够理解限制并调整行为。

### 15.8 `/tools`、`/status`、`/trace` 的透明化接口设计

这三个接口是 candle-cli 区别于普通聊天 CLI 的独特特色：

- `/tools` 让用户知道 agent 的能力边界。
- `/status` 让用户了解系统当前运行环境。
- `/trace` 让用户追溯 agent 的执行链路。

三者共同提供了 agentic 系统必需的可观察性，使系统行为从"黑箱"变为"可审计的过程"。

### 15.9 Session persistence

完整的 session 持久化（基于 JSON 文件）支持长期开发任务。Session 中不仅保存了对话文本，也保存了 tool call 和 tool result 记录，使恢复后的 session 包含完整的 agent 执行历史。对话裁剪机制（`compact_session`，按最大轮数裁剪旧消息）帮助控制上下文长度。

### 15.10 面向 self-development workflow 的可扩展基础

candle-cli 的模块化架构和完整的 agent 基础设施为未来的 self-development workflow 提供了工程基础。后续可以让 candle-cli 在自己的仓库中完成读代码、改代码、跑测试、分析错误、继续修复的完整闭环——这正是 candle 项目 Self-Hosting 愿景在 CLI 层面的具体实践。

---

## 16. 典型使用场景

candle-cli 当前可以支持以下典型使用场景：

1. **项目代码理解**：用户可以让 agent 读取项目的 README.md、Cargo.toml 和核心模块代码，然后向 agent 提问关于项目架构、依赖关系或设计模式的问题。Agent 通过 read、glob 和 grep 工具获取所需信息。

2. **本地代码辅助开发**：用户可以在 REPL 中描述修改需求，agent 通过 read 读取目标文件、edit 执行精确替换、shell 运行测试验证修改正确性，形成 read → edit → test 的辅助开发闭环。

3. **自动化调试辅助**：用户可以要求 agent 运行 `cargo test` 获取失败信息，通过 grep 搜索相关代码，通过 read 检查可疑函数，然后在分析基础上输出诊断建议。

4. **工具调用演示**：用户可以通过 `/tools` 查看可用工具，通过 `/status` 检查配置状态，通过 `/trace` 查看完整的执行链路。这三个接口为开发者理解 agentic 系统的行为模式提供了直观的入口。

5. **运行状态监控**：在 REPL 会话中，用户可以随时使用 `/status` 查看当前模型配置、权限模式和 session 状态，确保 agent 运行在预期的配置环境下。

6. **技术报告生成**：Trace 和 session 记录可以作为实验数据来源，支撑后续的技术报告、课程项目和学术论文中的案例分析。

7. **后续 agentic coding workflow**：随着项目的持续发展，candle-cli 可以支持更复杂的 agentic 任务链，包括跨文件重构、自动化代码审查和多步骤的 CI/CD 辅助操作。

---

## 17. 未来修改建议

### 17.1 增强代码编辑能力

当前 `edit` 工具实现了精确单次匹配替换。未来可以引入更丰富的编辑能力，如 patch-style 编辑（支持上下文行号的 diff 格式）、多行替换和结构化 diff 展示，使代码修改过程对用户更加透明和可控。

### 17.2 增强 `/tools` 接口

当前 `/tools` 展示工具名称列表。未来可以扩展为展示每个工具的详细信息，包括工具 schema（输入参数类型和格式）、参数示例、权限要求、风险等级和典型使用场景。这可以让用户更清楚地了解 agent 的能力范围和使用方式。

### 17.3 增强 `/status` 接口

当前 `/status` 展示基本的运行时信息。未来可以扩展为展示更丰富的状态信息，包括 API backend 名称和健康状态、模型名称和 token 用量统计、当前权限模式的详细说明、session 的完整元数据、工作目录的文件统计、本地 GPU/NPU 设备信息和显存状态（当使用本地模型时）、Python bridge 的版本和健康状态等。

### 17.4 增强 `/trace` 接口

当前 `/trace` 展示最近一次执行的事件序列。未来可以扩展为在每个 trace 步骤中包含更详细的信息，如工具调用的输入参数、执行结果摘要、权限决策原因、错误具体信息和每步的耗时统计。同时保持"不展示模型私有 chain-of-thought"的原则。

### 17.5 增强 session 和 project memory

未来可以引入项目级别的 memory，记录常用命令、用户偏好、项目关键文件索引和长期任务状态。这将使 candle-cli 从"单次交互的工具"发展为"理解项目的长期协作伙伴"。项目级 memory 可以存储在 workspace 根目录下的配置文件中，随项目代码一起管理。

### 17.6 增强模型后端配置

当前通过环境变量配置模型后端。未来可以提供 `/model` 命令支持在 REPL 中动态切换模型后端，支持为不同任务类型配置不同的模型（如日常对话用 flash 模型，复杂推理用 pro 模型），以及更便捷的后端 profile 管理。

### 17.7 增强上下文管理

未来可以引入项目文件索引（自动识别项目中的重要文件）、智能上下文压缩（基于语义而非简单截断）和相关文件自动检索（当模型需要了解某个模块时，主动推送相关文件内容）。这些能力将帮助模型在大型项目中更高效地导航和理解代码。

### 17.8 接入 candle backend

未来可以将 candle 作为本地模型运行后端之一，实现 `CandleRuntime` 的完整实现。这将形成 API-first 到 hybrid backend 的演进路线：当网络可用时使用 API，网络不可用时回退到本地 candle 推理；或读操作使用本地模型以降低延迟，复杂推理使用 API。这与 candle 项目 roadmap 中的 Cognitive Runtime 方向直接对应。

### 17.9 增强 self-development workflow

candle-cli 当前已经具备了 self-development workflow 的基础能力（读代码、改代码、跑测试、查看结果）。未来可以进一步将这些能力串联成自动化工作流：agent 在自己的仓库中根据用户需求修改代码 → 运行测试套件 → 分析失败原因 → 自动修复 → 再次测试 → 总结修改内容。这种闭环正是 candle 项目 Self-Hosting 和 Agentic Kernel 理念在实践层面的具体体现。

### 17.10 增强文档和示例

未来可以提供更多的 examples 脚本、tutorials 文档、demo workflow 和真实开发案例记录，帮助新用户快速了解 candle-cli 的使用方式和最佳实践。

---

## 18. 可用于报告的项目创新点总结

以下创新点可以写入课程项目报告、科研项目报告或工程报告中。每个创新点均基于项目当前实际实现或明确的未来设计方向，不涉及夸大或编造。

1. **基于 candle 技术路线启发的 agentic CLI 设计**：项目从 candle-org/candle 的轻量级、多后端和 agentic AI ready 路线出发，在 CLI 层面对 Cognitive Runtime 和 Agentic Kernel 理念进行了工程化探索，形成了从底层框架到终端工具的完整技术视野。

2. **Rust 系统控制层与 Python/API 模型调用层的混合架构**：Rust 负责 CLI、agent loop、tools、permissions、session 和 trace 等系统控制逻辑，Python bridge 负责模型推理和 API 调用适配，两层通过定义清晰的 JSON 协议解耦。这种架构既保证了核心行为的类型安全和可靠性，又充分利用了 Python 生态的模型工具链。

3. **API-first 的低门槛模型调用策略**：优先通过 OpenAI 兼容 API 调用模型，使用户无需 GPU 或模型下载即可使用 agentic CLI。这一策略降低了部署门槛，使开发资源能集中在 agentic CLI 框架的核心工程能力上，同时保留了后续接入本地推理后端的架构灵活性。

4. **文本 JSON 工具调用协议驱动的 agent loop**：设计了 `<tool_call>{"id":"...","name":"...","input":{...}}</tool_call>` 文本协议，使模型能够通过自然语言生成的 JSON 块发起工具调用请求。该协议不依赖特定 API 的 function calling 能力，兼容任何能遵循文本格式指令的模型后端。Agent loop 支持格式错误恢复、权限拒绝反馈和有界步数保护。

5. **Permission-aware 的本地执行安全控制**：四种权限模式（read-only、workspace-write、prompt、danger-full-access）被嵌入到 agent loop 的核心执行路径中，工作目录边界检查被统一实现在工具注册表层。权限拒绝信息以结构化格式返回给模型，使 agent 能够理解权限限制并调整行为。

6. **`/tools`、`/status`、`/trace` 构成的透明化可观察性接口体系**：这三个接口共同为 agentic 系统提供了必需的可观察性——让用户知道系统有什么能力（/tools）、当前处于什么状态（/status）以及执行了什么操作（/trace）。这种透明化设计是 agentic CLI 区别于普通聊天工具的重要特色。

7. **Session persistence 支持长期 agentic 任务**：Session 不仅保存对话文本，还保存完整的 tool call 和 tool result 记录，支持跨会话的 agentic 任务延续。这与软件工程中长期开发任务的自然节律（code → test → debug → repeat）相契合。

8. **面向 Hybrid Backend 和 Self-Development Workflow 的可扩展架构**：`CandleTargetRuntime` trait 的统一抽象为后续接入 candle 本地推理后端预留了清晰接口。项目当前的 read → edit → shell → test Agentic 工具链已具备支持 self-development workflow 的基础能力，未来可以发展为 candle 项目 Self-Hosting 理念在 CLI 层面的完整实践。

---

## 19. 总结

candle-cli 是一个面向 agentic coding 的命令行工具原型，其核心目标是构建一个让大语言模型能够通过工具系统参与真实软件开发流程的 CLI 交互框架。项目受到 candle-org/candle 轻量级、多后端和 agentic AI ready 技术路线的直接启发，在 candle 所勾勒的 Cognitive Runtime 和 Agentic Kernel 理念基础上，进行了面向终端用户的工程化探索。

在架构上，candle-cli 采用 Rust 核心加 Python bridge 的分层设计。Rust 负责 CLI 交互、agent loop 控制、工具系统管理、权限检查、session 持久化、执行追踪和运行状态展示等系统控制逻辑；Python bridge 负责连接模型推理后端（主要为 OpenAI 兼容 API）。当前阶段优先采用 API-first 的模型调用策略，使项目能够聚焦于 agentic CLI 框架的核心工程能力建设。

`/tools`、`/status` 和 `/trace` 三个透明化接口是蜡烛 CLI 区别于普通聊天工具的重要特色：它们分别为用户提供了系统能力清单、运行时状态快照和执行链路追溯，使 agent 的行为从黑箱变为可审计的过程。

后续可以在此基础上继续扩展，包括增强代码编辑能力、完善透明化接口、引入项目级 memory、接入 candle 本地推理后端、构建 self-development workflow 以及向更完整的 AI coding assistant 方向演进。这些方向既是对 candle-cli 自身工程质量的持续提升，也是对 candle 项目 Agentic Kernel 和 Self-Hosting 理念在实践层面的不断深化。
