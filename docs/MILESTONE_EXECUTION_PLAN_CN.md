# candle-cli M0–M18 完整执行计划

更新日期：2026-08-06

## 1. 总体结论

当前版本规划到 **M18**，从 M0 开始计算，一共有 **19 个里程碑轮次**：

- 已完成：M0–M16，共 17 轮；
- 开发中：M17；
- M18：开发与服务器验收完成，待 PR、GitHub 托管 CI 和用户确认后的发布；
- 当前代码状态：M16 已通过 PR #6 合并；M17 的结构化上下文、等预算委派、硬截止时间、Ollama 原生协议和 Smoke 门禁已完成，正式 Provider 配对运行仍待合格推理环境；M18 已完成安全留出集、doctor、安装/演示脚本、跨平台 CI 配置和最终证据聚合，并通过 Rust 177/177、Python 350/350 全量回归；
- 完整路线剩余工作：创建 PR 并取得 GitHub 托管 CI 结果；正式 Provider 数据实验可在推理环境就绪后补充；
- 简历优先路线：先合并当前候选并完成 CI/Release dry run，再由用户决定是否发布版本。

这里的 M18 表示当前规划版本的工程闭环，不表示项目以后不能继续增加新能力。

## 2. 全部里程碑总表

| 里程碑 | 主题 | 当前状态 | 核心结果 |
|---|---|---|---|
| M0 | 稳定性与安全基线 | 已完成 | 修复基础缺陷，建立 Rust/Python 全量测试基线 |
| M1 | 统一迁移诊断 Schema | 已完成 | Rust、Python、JSON Schema 统一 API Trace 与诊断协议 |
| M2 | Python AST 扫描器 | 已完成 | 不执行目标代码即可识别 PyTorch API、别名和 Tensor Method |
| M3 | 版本化 API 映射知识库 | 已完成 | 引入 MindSpore 官方证据、版本和差异分类 |
| M4 | 差分轨迹与首错定位 | 已完成 | 对齐 PyTorch/MindSpore Trace，定位 dtype、shape、结构和数值首差异 |
| M5 | 确定性重写与验证 | 已完成 | Patch 预览、事务应用、程序验证、校验和回滚 |
| M6 | 真实项目静态评测 | 已完成 | PyTorch Examples、nanoGPT、DETR 与 Segment Anything 留出审计 |
| M7 | 双框架运行微基准 | 已完成 | PyTorch 2.6/MindSpore 2.9 基础前向 API 链真实对拍 |
| M8 | 安全回归基准 | 已完成 | 路径逃逸、权限门禁和正常任务误拦截评测 |
| M9 | 上下文裁切基准 | 已完成 | 测量估算 Token 减少和工具调用链完整性 |
| M10 | Provider Token/Cache 可观测性 | 已完成采集链路 | Bridge 采集真实 usage；真实 Provider 基准留到 M17 |
| M11 | 组件级双框架验证 | 已完成 | MLP、CNN、梯度、BatchNorm 和三类首错定位 |
| M12 | 训练步骤差分验证 | 已完成并合并 | 前向、MSE、梯度和 SGD 参数更新完整对拍 |
| M13 | 端到端迁移闭环 | 已完成并合并 | `migrate run` 串联扫描、改写、验证、Trace 和回滚 |
| M14 | 真实模型切片与自动双环境采集 | 已完成并合并 | 在 PyTorch Examples MNIST 分类器头上自动运行双框架、比较 Trace 并验证回滚 |
| M15 | 数据流水线与随机性诊断 | 已完成并合并 | 18/18 真实双框架案例；8/8 故障分类与首差异 Top-1 正确 |
| M16 | Graph Mode 与高级训练状态 | 已完成，PR #6 已合并 | 13/13 分类正确；4/4 模式组件；2/3 多步优化器等价并定位 AdamW 差异；3/3 跨进程恢复 |
| M17 | Agent 上下文、真实 Token/Cache 与多 Agent 消融 | 开发中 | 20/20 事实保留与任务可回答；81.76% 估算压缩；真实 Provider/多 Agent 收益待测 |
| M18 | 安全留出集、CI、发布与最终 Benchmark | 开发完成，待 PR/托管 CI/发布 | 12/12 Linux 可评估留出攻击被拦截或门禁，8/8 正常项无误拦；doctor、安装、演示、CI 与 13 组证据聚合已完成 |

## 3. 已完成阶段说明

### M0–M5：核心迁移基础

这一阶段建立了统一协议、AST 扫描、官方 API 映射、运行轨迹比较和事务式改写。完成后，项目不再只是通用 Agent CLI，而是具备明确 PyTorch→MindSpore 迁移目标的诊断工具。

对应文档：

- `docs/M0_VERIFICATION.md`
- `docs/M1_VERIFICATION.md`
- `docs/M2_VERIFICATION.md`
- `docs/M3_VERIFICATION.md`
- `docs/M4_VERIFICATION.md`
- `docs/M5_VERIFICATION.md`

### M6–M10：真实覆盖、安全和可观测性

这一阶段增加真实项目静态覆盖、双框架运行微基准、安全回归、上下文裁切和 Provider usage 采集。M10 已完成采集链路，但真实 Provider 的 Token/Cache 数据仍需在 M17 使用固定模型和请求集正式测量。

### M11–M14：组件、训练和真实模型自动闭环

这一阶段将差分验证扩展到网络组件、梯度和单步训练，形成统一的 `candle-cli migrate run` 状态机，并在 M14 由版本化清单自动启动两端运行时。M14 固定 PyTorch Examples MNIST 分类器头切片，在 PyTorch `2.6.0+cu124` 与 MindSpore `2.9.0` 环境完成 3/3 场景，包含一次等价迁移和两类字节级故障回滚。

当前完整测试基线：

- Rust：177/177；
- Python：350/350；
- M12 训练步骤：3/3 案例；
- M13 工作流：4/4 场景；
- M14 真实模型双运行时：3/3 场景，2/2 回滚。

## 4. M14：真实模型切片与自动双环境采集

状态：已完成开发与远端正式验收，待提交 PR。

原预计周期：8–12 个开发日。

### 目标

把 M13 的两算子闭环提升到一个来自外部公开项目的可执行模型切片，并让工作流自动启动 PyTorch 和 MindSpore 两套 Python 环境，不再要求用户手工准备两份 JSONL Trace。

### 开发任务

1. 从宽松许可证的公开项目中选择一个 100–500 行模型切片，固定仓库、Commit、许可证、源码路径和 SHA-256。
2. 使用合成输入替代在线数据下载，确保离线可重复运行。
3. 新增版本化工作流清单，描述：
   - PyTorch Python 路径；
   - MindSpore Python 路径；
   - 源端运行命令；
   - 目标端验证命令；
   - Trace 输出路径；
   - 超时、环境变量白名单和资源限制。
4. 为 `migrate run` 增加双环境采集编排：
   - 先运行源端并生成 PyTorch Trace；
   - 生成并应用迁移 Patch；
   - 运行目标端并生成 MindSpore Trace；
   - 自动比较 Trace；
   - 失败时自动回滚。
5. 记录剩余 unknown/difference API 和人工修改次数，不能把人工修复包装成自动修复。
6. 增加一次真实成功案例和至少两次故障注入：目标程序失败、Trace 语义偏差。
7. 输出 JSON/Markdown 报告和可复现命令。

### 必须采集的数据

- 源码文件数与代码行数；
- 扫描发现数、映射覆盖率和 unknown API 数；
- 自动 Patch 数、人工 Patch 数和 Patch 采用率；
- 源端/目标端执行结果；
- Trace 调用数、等价率和首个偏差位置；
- 自动回滚成功率；
- 总耗时及各步骤耗时；
- 框架、Python、Commit、清单和知识库版本。

### 验收标准

- 至少一个固定外部模型切片能够在 PyTorch 环境运行；
- 迁移后能够在 MindSpore 环境运行并完成 Trace 比较；
- 两端 Trace 由工作流自动生成，不手工复制；
- 至少一个成功闭环和两个回滚场景可重复执行；
- 回滚后源码字节与应用前完全一致；
- 全量 Rust/Python 测试继续通过；
- 生成 `docs/M14_*.md`、固定清单和机器结果。

### 风险和依赖

- 外部模型可能依赖自定义 CUDA 算子或在线数据，应优先选择 CPU 可运行切片；
- 当前知识库覆盖率不足时允许人工适配，但报告必须单独统计；
- 只有 M14 的单个固定项目通过时，仍不能声称真实项目总体迁移成功率。

### 验收结果

- 固定上游：PyTorch Examples `mnist/main.py`，Commit `acc295d...`，BSD-3-Clause；
- 来源文件：2 个、166 行；运行切片 25 行，1 次人工功能适配单独计数；
- 自动 Patch：6，人工 Patch：1，采用率 85.7143%；
- 运行切片映射覆盖：5/5，unknown 为 0；
- 1/1 正常迁移等价，2/2 故障注入字节级回滚，dtype 首差异分类正确；
- 远端完整验收：Python 325/325、Rust 148/148、Benchmark 3/3；
- 文档：`docs/M14_REAL_MODEL_DUAL_RUNTIME.md`；
- 机器结果：`benchmarks/results/real_model_dual_runtime_v1.json`。

## 5. M15：数据流水线与随机性诊断

优先级：P1。

预计周期：8–12 个开发日。

### 目标

覆盖实际迁移中非常常见、但单纯 API 名称替换无法定位的数据输入问题，例如 HWC/CHW、整数标签、布尔掩码、批处理尾部、Transform 默认值和随机性。

### 开发任务

1. 建立数据流水线 Schema：输入批次、布局、dtype、shape、范围和标签语义。
2. 增加 DataLoader/TensorDataset、Normalize、Resize、ToTensor、随机采样和批处理案例。
3. 增加布局、dtype、归一化范围、标签类型和 drop-last 故障分类。
4. 为随机初始化、Dropout 和采样引入统计比较，不要求逐元素相等。
5. 区分固定种子可复现问题与框架随机算法差异。
6. 将数据诊断结果接入 M13/M14 工作流报告。

### 验收标准

- 至少 12 个固定案例，其中至少 5 个为冻结后的故障案例；
- 确定性等价案例全部通过；
- 故障类别和首错 Top-1 准确率至少达到 80%；
- 所有随机案例报告样本量、统计量和阈值；
- 不把统计等价写成逐元素相同。

### 完成记录（2026-08-06）

- 冻结 18 个案例，其中 8 个故障注入、7 个确定性等价和 3 个统计等价案例；
- PyTorch 2.6.0+cu124/torchvision 0.21.0+cu124 与 MindSpore 2.9.0 真实双端采集 18/18；
- 分类准确率、首差异 Top-1、确定性等价率和统计等价率均为 100%；
- 4 个随机案例记录 128–4096 个样本、统计量、阈值和不同的序列摘要，均未使用逐元素相等；
- `migrate run --data-pipeline-report` 已接入 Rust/Python 统一报告；
- 远端完整验收：Python 331/331、Rust 150/150、`cargo fmt` 与 Clippy 通过；
- 文档：`docs/M15_DATA_PIPELINE_RANDOMNESS.md`；
- 机器结果：`benchmarks/results/data_pipeline_randomness_v1.json` 与 `data_pipeline_workflow_v1.json`。

## 6. M16：Graph Mode 与高级训练状态

优先级：P1。

预计周期：10–15 个开发日。

### 目标

将当前单步 SGD/PYNATIVE 验证扩展到 Graph Mode、Adam、Checkpoint 和短序列训练，覆盖真实训练迁移中的状态管理问题。

### 开发任务

1. 对相同 MindSpore 网络分别运行 PYNATIVE 和 GRAPH 模式。
2. 捕获编译阶段错误、动态图依赖、控制流和 shape specialization 差异。
3. 增加 Adam/AdamW 状态、学习率调度器、梯度累积和梯度裁剪。
4. 比较参数名、参数顺序、Checkpoint 保存与恢复后的输出。
5. 增加 3–10 步短训练轨迹，比较 loss 趋势和参数更新，而不是宣称完整收敛。
6. 为 Graph 编译失败和优化器状态错位建立独立诊断类别。

### 验收标准

- 至少三个网络组件同时通过 PYNATIVE/GRAPH 验证；
- 至少两个优化器案例完成多步参数更新对比；
- 至少一个 Checkpoint 跨进程恢复案例；
- 故障报告能够区分编译错误、运行错误、梯度错误和优化器状态错误；
- 明确记录 CPU/加速卡、模式和框架版本。

### 完成结果

- PyTorch Eager、MindSpore PYNATIVE/GRAPH 在 CPU 上完成 13/13 冻结案例；
- Linear、MLP、Conv2d、Tensor 控制流 4/4 三运行时等价；
- Linear Adam 与梯度累积/裁剪 2/2 多步轨迹等价，AdamW + 学习率序列发现并定位 1 个真实优化器状态差异；
- 三运行时均完成独立生产/消费进程的 Checkpoint 恢复，3/3 输出和参数结构一致；
- 编译、运行、梯度、优化器状态和 shape 五类冻结故障 Top-1 为 5/5；
- Python 338/338、Rust 152/152，`cargo fmt --all -- --check` 通过；
- 详细证据：`docs/M16_GRAPH_ADVANCED_TRAINING.md` 与 `benchmarks/results/advanced_training_v1.json`。

## 7. M17：Agent 上下文、真实 Token/Cache 与多 Agent 消融

优先级：P2；面向 Agent/大模型工程岗位时可提升到 P1。

预计周期：8–12 个开发日，另需用户提供可用 Provider 凭据并授权少量 API 调用成本。

### 目标

回答三个目前还没有真实数据的问题：上下文摘要是否保留任务事实、Provider Cache 是否真实命中、多 Agent 是否比单 Agent 更有效。

### 开发任务

1. 将上下文策略升级为“近期原文 + 结构化任务状态 + 可验证历史摘要”。
2. 建立迁移任务事实保留集，检查文件、命令、错误位置和待办事项是否在压缩后仍可恢复。
3. 固定 Provider、模型、temperature、请求集和价格日期。
4. 采集真实 input/output/cached input token、延迟、重试和成本。
5. 建立单 Agent 与主 Agent+专家子 Agent 消融：相同任务、相同总预算、相同超时。
6. 比较任务通过率、工具步数、Token、耗时、失败类型和人工介入次数。

### 验收标准

- 至少 20 个固定上下文/迁移任务；
- 报告压缩率、事实保留率和任务通过率，三者不能互相替代；
- Cache 只使用 Provider 返回字段；不支持时明确写 `unsupported/null`；
- 多 Agent 只有在任务成功率或成本/耗时上存在可重复收益时才写入简历；
- 发布原始匿名化机器结果和完整实验配置。

## 8. M18：安全留出集、CI、发布与最终 Benchmark

优先级：P0 收尾阶段。

预计周期：5–8 个开发日。

### 目标

把研究型工程整理为其他人可以安装、运行、复现和审查的正式版本，并生成最终简历证据。

### 开发任务

1. 扩展安全评测到符号链接竞态、Windows junction、压缩包逃逸、命令注入、提示注入、资源耗尽和网络外传尝试。
2. 将开发攻击集与冻结留出攻击集分开，统计拦截率和正常任务误拦截率。
3. 建立 GitHub Actions：Rust fmt/check/test、Python lint/pytest、Schema/Benchmark 防漂移检查。
4. 提供 Linux/Windows 安装脚本或发布二进制，并明确 Python Bridge 依赖。
5. 增加 `doctor` 环境检查：Rust、Python、PyTorch、MindSpore、Docker 和双环境配置。
6. 生成一个 3–5 分钟演示脚本或录屏流程。
7. 聚合所有正式 Benchmark，生成一份总 JSON、Markdown 技术报告和最终简历版本。
8. 经用户确认后创建发布分支、PR、Tag 和 Release；不自动发布。

### 验收标准

- 新环境可以依据 README 完成安装和最小迁移演示；
- CI 在干净环境通过，不依赖开发机隐式状态；
- 所有公开指标能够追溯到清单、代码、环境和机器结果；
- 安全报告同时给出攻击拦截率和正常任务误拦截率；
- README 中不存在未实现后端、虚假缓存率或泛化准确率表述；
- GitHub Release 只在用户确认后执行。

## 9. 推荐执行顺序

### 完整技术路线

```text
M14 真实模型自动闭环
  → M15 数据流水线与随机性
  → M16 Graph/高级训练
  → M17 上下文、Cache、多 Agent 消融
  → M18 CI、安全与正式发布
```

该路线技术覆盖最完整，适合把项目持续做成长期作品。

### 简历优先路线

```text
M14 真实模型自动闭环
  → M18-lite CI、演示、总报告和发布
  → 根据目标岗位选择 M15/M16 或 M17
```

推荐理由：当前项目最缺少的是“外部真实模型切片上的自动迁移闭环”。完成 M14 后，项目故事可以从“小型双框架案例”提升为“真实来源代码、自动执行、可定位、可回滚”。随后通过 M18-lite 把结果变成面试官能够直接运行和验证的交付物。

岗位方向选择：

- MindSpore/框架迁移/训练系统岗位：优先 M15、M16；
- Agent/LLM 工程岗位：优先 M17；
- 后端/基础设施岗位：优先 M18 的安全、CI、跨平台和发布部分。

## 10. 每一轮固定执行流程

后续每个 M 都按照以下顺序执行：

1. **冻结范围：** 明确本轮做什么、不做什么和可量化验收标准。
2. **检查现状：** 阅读相关代码、测试、文档和现有机器结果。
3. **先写协议与样例：** 固定 Schema、清单、案例 ID 和版本门禁。
4. **实现最小闭环：** 先让一个代表性案例完整跑通。
5. **补充故障与边界：** 增加失败、超时、回滚、版本不匹配和路径安全测试。
6. **本地自验：** 静态检查、目标测试、JSON 校验和差异检查。
7. **服务器正式验收：** 仅在隔离测试目录和指定环境运行，不修改服务器其他环境。
8. **全量回归：** Rust、Python、双框架任务全部通过。
9. **固化证据：** 更新机器结果、中文里程碑文档、README 和简历材料。
10. **用户确认：** 汇报改动和数据；得到确认后再 Commit、Push 和创建 PR。

## 11. GitHub 提交策略

- M12 与 M13 当前可以合并成一个 PR，也可以拆成两个 PR；建议拆分，便于审查训练验证与工作流控制两类改动。
- M14 及之后每个 M 独立使用功能分支和 PR。
- 每个 PR 必须包含：实现、测试、固定清单、机器结果、限制说明和复现命令。
- 不把临时服务器目录、虚拟环境、模型权重、API Key 或原始敏感日志提交到仓库。
- 未经用户明确确认，不执行 GitHub Push、PR 合并、Tag 或 Release。

## 12. 当前下一步

M17 工程链路与 M18 开发已在远端隔离目录完成，当前基线为 Rust 177/177、Python 350/350、Clippy `-D warnings` 通过；M18 Linux 安全留出集的 12 个可评估攻击项全部被拦截或门禁，8 个正常项无误拦，3 个不适用项未计入分母。下一步是由用户确认后创建 PR，在 GitHub Ubuntu/Windows Runner 上取得首次托管 CI 和 Release dry run 结果；正式 Provider Token/Cache 与多 Agent 配对实验继续等待合格推理环境，不阻塞当前发布工程闭环。
