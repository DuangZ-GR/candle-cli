# M16：Graph Mode 与高级训练状态

## 目标与结论

M16 将 M12 的单步 SGD/PYNATIVE 验证扩展到 PyTorch Eager、MindSpore PYNATIVE、MindSpore GRAPH 三运行时，覆盖图编译、Tensor 控制流、Adam/AdamW、多步 loss 轨迹、学习率序列、梯度累积与裁剪、优化器状态和跨进程 Checkpoint 恢复。

在远程隔离的 `zgr` 环境中，使用 PyTorch `2.6.0+cu124` 和 MindSpore `2.9.0` 完成 13 个冻结案例的真实 CPU 采集：

- 13/13 案例分类正确，整体 Benchmark 通过；
- 4/4 网络组件在 PyTorch Eager、MindSpore PYNATIVE/GRAPH 中输出一致；
- 3 个多步优化器案例均完成 3–5 步轨迹比较，其中 Adam 与“梯度累积 + 裁剪”2/2 等价；
- AdamW + 学习率序列发现 1 个真实跨框架优化器状态差异，未通过放宽容差隐藏；
- PyTorch、MindSpore PYNATIVE、MindSpore GRAPH 三次跨进程 Checkpoint 均恢复成功，生产/消费进程 PID 不同；
- 5/5 冻结故障被正确区分为图编译、运行时、梯度、优化器状态和 shape 差异，诊断 Top-1 为 100%；
- PYNATIVE 与 GRAPH 的四个组件和三个训练案例结果一致。

这些结果证明固定小网络和短轨迹上的诊断能力，不等同于完整模型收敛、长训练稳定性或加速卡内核一致性。

## 架构

`python/migration/advanced_training.py` 将 M16 分成四层：

1. **冻结清单：** `advanced_training_v1.json` 固定 13 个案例、开发/留出划分、预期等价性和诊断类别；加载器拒绝案例缺失、重复 ID、类型或预期类别漂移。
2. **三运行时采集：** 同一组权重和输入分别在 PyTorch Eager、MindSpore PYNATIVE、MindSpore GRAPH 的 CPU 环境执行，并记录框架版本、Python、平台、设备、模式和耗时。
3. **状态比较：** 对前向输出、loss 轨迹、最终参数、梯度范数、学习率序列、参数名称/顺序、优化器状态槽和 Checkpoint 恢复输出进行结构化比较。
4. **阶段诊断：** 把首个失败阶段独立归类为 `graph_compile_failure`、`runtime_error`、`gradient_mismatch`、`optimizer_state_mismatch`、`checkpoint_mismatch` 或既有 shape/value 类别。

Rust 侧新增 `AdvancedTrainingSummary`，统一工作流可以附加并校验 M16 报告：

```bash
candle-cli migrate run <project> \
  --advanced-training-report benchmarks/results/advanced_training_v1.json \
  --format markdown
```

无效报告会在 `advanced_training_diagnostics` 阶段显式失败，不会被静默纳入结果。

## 冻结案例

| 类型 | 案例 | 结果 |
|---|---|---|
| 模式/组件 | Linear、MLP、Conv2d、Tensor 控制流 | 4/4 三运行时输出等价 |
| 多步 Adam | Linear，5 步 | 三运行时 loss 与最终参数等价 |
| AdamW + 调度 | MLP，5 个学习率 | MindSpore 两模式一致；与 PyTorch 轨迹发生真实差异并正确分类 |
| 累积与裁剪 | Linear，2 个 micro-batch 累积、global-norm 0.25、3 步 | 三运行时等价；裁剪后范数约 0.25 |
| Checkpoint | Linear，独立写/读子进程 | 三运行时 3/3 恢复输出、名称和顺序一致 |
| 留出诊断 | 编译、运行、梯度、优化器状态、shape specialization | 5/5 类别 Top-1 正确 |

开发集 8 个案例，留出集 5 个案例。留出案例是执行前固定的故障注入；AdamW 差异不是故障注入，而是实际 API 组合在相同超参数下产生的轨迹差异。

## 多步轨迹证据

| 案例 | PyTorch 首/末 loss | MindSpore PYNATIVE 首/末 loss | MindSpore GRAPH 首/末 loss | 结论 |
|---|---:|---:|---:|---|
| Linear Adam，5 步 | 0.630625 / 0.461846 | 0.630625 / 0.461846 | 0.630625 / 0.461846 | 等价 |
| MLP AdamW + 调度，5 步 | 0.699300 / 0.573255 | 0.699300 / 0.268301 | 0.699300 / 0.268301 | 跨框架差异；两种 MindSpore 模式一致 |
| Linear 累积 + 裁剪，3 步 | 0.630625 / 0.577131 | 0.630625 / 0.577132 | 0.630625 / 0.577132 | 等价 |

AdamW 案例的最终参数最大绝对差为 `0.142400`。当前证据足以定位到优化器状态更新阶段，但不足以仅凭数值结果断言某一框架实现错误；迁移时应把 AdamW 实现、偏置修正、权重衰减和学习率调度组合视为需要显式验证的语义差异。

## Checkpoint 证据

每个运行时都通过两个由当前 `zgr` Python 启动的独立子进程完成：生产进程构造固定模型并保存状态，消费进程从零初始化模型、加载状态并重新前向。报告要求：

- 生产与消费 PID 不同；
- Checkpoint 文件非空；
- 恢复前后参数名称、顺序和 shape 相同；
- 恢复前后输出在严格容差内一致。

实测 PyTorch Checkpoint 为 1514 字节，MindSpore 两种模式均为 62 字节；三组恢复输出均为 `[[1.100000], [-1.000000]]`。

## 验收记录

执行环境：

- 服务器：`mseco-4090`；
- Python：`/home/mseco/miniconda3/envs/zgr/bin/python`，3.10.20；
- PyTorch：2.6.0+cu124；
- MindSpore：2.9.0；
- 设备：CPU；
- 模式：PyTorch Eager、MindSpore PYNATIVE、MindSpore GRAPH；
- Rust：cargo 1.94.1。

验收结果：

- Python 全量测试：338/338；
- Rust 全量测试：152/152；
- `cargo fmt --all -- --check`：通过；
- 真实三运行时 Benchmark：13/13 分类正确；
- 冻结诊断 Top-1：5/5；
- 模式组件等价率：4/4；
- 多步优化器等价率：2/3，另 1 个真实 AdamW 差异正确识别；
- 跨进程 Checkpoint 恢复率：3/3；
- Rust CLI + Python 报告集成：通过。

所有 Python 命令均显式使用 `zgr` 解释器，没有修改 `base` Conda 环境。测试在独立目录 `/home/mseco/candle-cli-m16-test-20260806` 中执行，没有覆盖服务器原有仓库改动。

## 可审计文件

- 冻结清单：`benchmarks/migration/advanced_training_v1.json`；
- 汇总报告：`benchmarks/results/advanced_training_v1.json`；
- 原始三运行时采集：`benchmarks/results/advanced_training_captures/`；
- 实现：`python/migration/advanced_training.py`；
- Python 测试：`python/test_advanced_training.py`；
- 工作流接入：`python/migration/workflow.py`；
- Rust Schema/CLI：`src/migration/schema.rs`、`src/cli/args.rs`、`src/cli/migrate.rs`。

## 限制与下一步

- 当前仅运行 CPU，没有覆盖 GPU、Ascend 或设备间内核差异。
- 网络规模很小，3–5 步 loss 下降不能作为收敛、精度或吞吐结论。
- 未覆盖混合精度、loss scaling、分布式优化器、梯度同步、断点续训数据游标和 RNG 状态。
- Checkpoint 只验证相同框架版本下的独立进程恢复，不代表跨版本或跨框架格式兼容。
- AdamW 的根因需要结合框架实现/官方语义继续拆分验证；当前结论仅为可复现的状态更新差异。
- M17 将转向 Agent 上下文事实保留、真实 Provider Token/Cache 和单/多 Agent 消融；M18 完成 CI、发布和复现实验闭环。
