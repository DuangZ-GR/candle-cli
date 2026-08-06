# M17：上下文事实保留、Provider Usage 与多 Agent 消融

## 当前状态

M17 已完成上下文事实保留层、等预算主/子 Agent 执行机制、共享硬截止时间和 Provider Usage/Cache 消融评估协议；真实 Provider 重复实验尚未执行，因此本里程碑仍为“开发中”，不发布缓存命中率或多 Agent 收益结论。

已完成的确定性结果：

- 20 个冻结迁移会话全部通过；
- 20/20 个目标事实在压缩后可恢复，事实保留率 100%；
- 20/20 个历史事实查询仍可回答，任务可回答率 100%；
- 20/20 个事实来源摘要校验通过；
- 启发式估算 Token 从 23,146 降至 4,221，减少 18,925，压缩率 81.76%；
- Provider Cache 未在离线基准中伪造，继续报告 `unsupported/null`；
- 主 Agent 与子 Agent 现在共享模型请求和工具步数预算，子 Agent 继承父工作目录并保持只读。
- 实验超时使用贯穿 Rust Agent、子 Agent、Python Worker、Provider 请求和重试退避的绝对截止时间，不再只在运行结束后判定超时。

这些数据只证明冻结会话上的确定性事实保留，不是 Provider 计费 Token、真实模型任务成功率或未知对话泛化率。

## 上下文架构

旧实现只保留最近 N 个完整用户轮次，虽然不会留下孤立工具结果，但被裁掉的文件、命令、错误位置和待办会永久消失。M17 改为三层上下文：

1. **近期原文：** 最近 N 个用户轮次及其完整 assistant/tool 消息保持原样；
2. **结构化任务状态：** 从被裁掉的文本和工具调用中提取 `objective`、`file`、`command`、`error`、`pending`、`decision` 六类事实；
3. **可校验历史证据：** 会话文件保存每条事实的来源角色、受限原文摘要和 FNV-1a 摘要，Provider 请求只注入事实和值及摘要 ID，不重复发送来源原文。

FNV-1a 只用于检测意外损坏和结果漂移，不是安全签名。模型仍被要求在不可逆操作前通过文件或命令重新验证事实。

事实值和来源摘要在持久化前会脱敏常见的 API Key、Bearer Token、password、secret 和 access/refresh token 形式，避免上下文压缩层把误贴凭据长期写入会话文件。

`Session.task_state` 使用 `serde(default)` 和空值跳过序列化，旧会话可以继续加载。压缩只吸收完整移除的历史轮次，系统消息和近期工具调用/结果配对保持不变。

## 冻结事实保留集

`context-fact-retention-v2` 固定 20 个迁移会话，每类 4 个：

| 类别 | 数量 | 示例 |
|---|---:|---|
| 文件 | 4 | `src/model.py`、配置、测试和 Trace 路径 |
| 命令 | 4 | pytest、cargo test、Graph 迁移命令 |
| 错误 | 4 | bool dtype、缺失算子、shape、Checkpoint 状态 |
| 待办 | 4 | API 语义、Checkpoint、GRAPH_MODE、fallback |
| 决策 | 4 | 执行模式、AdamW 差异、容差、回滚清单 |

报告分别统计压缩率、事实保留率和任务可回答率，不用其中一个指标替代另一个。机器结果位于 `benchmarks/results/context_fact_retention_v2.json`。

## 等预算多 Agent

原 `task` 工具给子 Agent 独立三步循环，消融时会让多 Agent 额外获得模型请求和工具步数。M17 引入 `AgentRunBudget`：

- 主/子 Agent 共用 `max_model_requests` 和 `max_tool_steps`；
- `task` 调用和子 Agent 内部工具都计入同一工具预算；
- 子 Agent 模型调用计入同一请求预算和最终 Provider Usage；
- 子 Agent 工作目录来自父 `ToolRegistry`，不再隐式使用进程 `.`；
- `read-only-with-task` 只开放 `pwd/read/glob/grep/task`，不开放 Shell、编辑或写入；
- 仍限制每次子 Agent 调用最多三步，并阻止子 Agent 递归委派。
- `timeout_ms` 同时生成绝对 `deadline_unix_ms`，Python Worker 启动耗时、流式读取和重试等待都计入同一墙钟预算。

冻结清单 `benchmarks/agent/agent_ablation_v1.json` 包含 10 个复杂迁移任务、单 Agent/委派 Agent 两个实验臂、每任务三次重复以及相同的 8 次模型请求、8 个工具步骤和 120 秒上限。

## Provider Usage/Cache 评估协议

`python/agent_experiment.py` 对原始运行记录执行严格检查：

- Provider、模型、temperature 和价格日期必须与冻结配置一致；
- 每个任务、实验臂和重复编号必须一一配对，不允许缺失或重复；
- 任一请求数、工具步数或超时越界都会使 `budget_comparable=false`；
- input/output/total token 只有在所有请求均返回 usage 时才聚合；
- Cache 只读取 Provider 返回的 `cached_prompt_tokens`；全部不支持时为 `unsupported/null`，部分返回时视为无效实验；
- 输出通过率、工具步数、模型请求数、端到端耗时、Provider 延迟、重试次数、失败类型、人工介入、Token 和按冻结价格计算的 Provider 成本；
- 只有至少三次重复且成功率或等成功率下的成本/耗时出现可重复收益时，`comparison.claim_supported` 才能为 `true`。

当前冻结配置中的 Provider、模型和价格仍为 `TO_BE_SELECTED/TO_BE_RECORDED`，明确阻止把模板误当成真实结果。选择 Provider 并完成 10×2×3 次真实运行前，简历中不得写 Cache 命中率或多 Agent 提升百分比。

配置完成后，执行器会再次校验 `CANDLE_CLI_EXPERIMENT_PROVIDER`、`CANDLE_CLI_MODEL_ID`、`CANDLE_CLI_TEMPERATURE` 和 usage 开关，按场景/重复次数交替两个实验臂的先后顺序，并只保存答案摘要与缺失证据，不把完整模型输出或凭据写入公开结果：

```bash
candle-cli agent-experiment \
  --config benchmarks/agent/agent_ablation_v1.json \
  --output benchmarks/results/agent_ablation_raw_v1.json

/home/mseco/miniconda3/envs/zgr/bin/python python/agent_experiment.py \
  --config benchmarks/agent/agent_ablation_v1.json \
  --runs benchmarks/results/agent_ablation_raw_v1.json \
  --output benchmarks/results/agent_ablation_v1.json
```

### Provider 能力冒烟门禁

正式执行 60 次配对运行前，可以增加 `--smoke`，只运行第一个场景、一次重复和两个实验臂：

```bash
candle-cli agent-experiment \
  --config benchmarks/agent/agent_ablation_ollama_smoke_v1.json \
  --output benchmarks/results/agent_ablation_ollama_smoke_v1.json \
  --smoke
```

Smoke 报告固定写入 `run_mode="smoke"` 和 `claim_eligible=false`。Python 正式评测器会主动拒绝该报告，即使 Provider、模型和任务元数据全部匹配，也不能把两次冒烟包装成正式消融结论。

2026-08-06 在远端 Ollama `0.13.5`、`qwen2:0.5b` 上完成真实冒烟：两个实验臂均返回完整 Token usage，重试均为 0，Cache 字段均为不支持；但两臂任务均失败，工具步骤均为 0，要求的两项代码证据全部缺失。因此该模型被能力门禁淘汰，没有继续运行 60 次实验。这个结果只说明当前 0.5B 模型不满足本任务的工具调用要求，不代表 Ollama 或 Qwen 系列其他模型的能力。

可复现配置和匿名化机器结果分别位于 `benchmarks/agent/agent_ablation_ollama_smoke_v1.json` 与 `benchmarks/results/agent_ablation_ollama_smoke_v1.json`；结果只保存答案摘要，不保存完整模型输出或凭据。

### Ollama 原生协议与硬超时验证

Bridge 新增 `CANDLE_CLI_API_STYLE=ollama-native`，直接调用 Ollama `/api/chat`，显式设置 `think=false`，解析 NDJSON 流中的 `prompt_eval_count` 与 `eval_count`。这避免了当前 Ollama OpenAI-compatible 端点在 Qwen3 推理模式下可能只返回 `reasoning`、而 `content` 为空的问题；默认 `openai` 模式保持兼容现有 DeepSeek、vLLM 和 OpenAI-compatible 服务。Cache 不由 Ollama 原生响应提供，因此继续诚实报告 `unsupported/null`。

在同一服务器下载并验证了 `qwen3:8b`：CPU-only Ollama 能通过 `/api/chat` 返回正文与真实 usage，但服务器现有 CUDA Runner 在加载模型时超时，无法形成可接受的正式实验吞吐。没有把 CPU 冒烟或失败的 GPU 加载写成正式消融数据，也没有启动 60 次配对运行。

为防止慢模型无限占用实验进程，使用临时 CPU-only Ollama 对 15 秒预算做真实验证：两个实验臂都在约 `15,020 ms` 结束并归类为 `failure_type="timeout"`。该结果只验证端到端硬截止时间，不评价模型能力。

## 阶段性验收

- Rust M17 定向测试：共享预算、Smoke 门禁、绝对截止时间及 Bridge 协议全部通过；
- Python Bridge 定向测试：40/40；
- Python Agent 实验评测器：6/6；
- `cargo check`：通过；
- `cargo test --all`：169/169；
- `PYTHONPATH=python python -m pytest -q python`：348/348，严格在 `zgr` 环境执行；
- `cargo fmt --all -- --check`：通过；
- 20 个事实保留案例：20/20；
- 上下文报告与冻结结果 SHA-256 一致：`2f1f2a78eae54b2112bb78fc31303ef37643824c038245d7dbea1c75a5770204`；
- 未配置 Provider 的模板拒绝执行且不生成伪结果；
- Smoke 报告被正式评测器拒绝，且不会生成汇总结果；
- Ollama 原生协议返回正文与真实 usage；15 秒绝对截止时间实测生效；
- 远端目录：`/home/mseco/codex-cache/candle-cli-m17-final`，未覆盖服务器原仓库。

以上验收已覆盖 Provider 重试/延迟遥测、Ollama 原生协议、真实实验执行器、证据锚点校验、持久化事实脱敏、共享预算和端到端硬截止时间。真实 Provider 重复实验和最终 M17 PR 尚未执行。

## 下一步

1. 修复服务器 Ollama CUDA Runner，或选择一个能通过工具调用 Smoke 且返回 usage 的 API Provider/模型，冻结 temperature、价格日期和请求集；
2. 实现/运行两个实验臂的原始记录器，完成 60 次配对运行；
3. 依据真实字段生成匿名化原始记录和汇总报告；
4. 只有报告支持时才更新简历中的 Cache 或多 Agent 收益；
5. 真实实验完成后重新执行全量回归并提交独立 M17 PR。
