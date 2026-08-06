# M15：数据流水线与随机性诊断

## 目标与结论

M15 将迁移诊断从算子和训练步骤扩展到模型输入侧，覆盖仅替换 API 名称无法可靠发现的布局、dtype、数值范围、标签、布尔掩码、尾批次、Transform 参数和随机性问题。

在隔离的远程 `zgr` 环境中，使用 PyTorch `2.6.0+cu124`、torchvision `0.21.0+cu124` 和 MindSpore `2.9.0` 对 18 个冻结案例完成真实双框架采集：

- 18/18 案例完成，8/8 故障分类正确；
- 故障类别与首个差异 Top-1 准确率均为 100%；
- 7/7 确定性等价案例通过；
- 3/3 统计等价案例通过；
- 4 个随机案例全部报告样本量、统计量和阈值，且明确记录 `elementwise_compared=false`；
- 真实结果已接入 `candle-cli migrate run --data-pipeline-report`，工作流步骤状态为 `passed`。

该结果证明固定案例上的诊断能力，不代表未知项目的数据流水线迁移准确率。

## 架构

`python/migration/data_pipeline.py` 分为三层：

1. **冻结清单层：** `data_pipeline_randomness_v1.json` 固定案例、开发/留出划分、预期类别和统计阈值，加载时拒绝案例漂移、重复 ID 和非法阈值。
2. **真实采集层：** 分别导入 PyTorch/torchvision 与 MindSpore Dataset/Vision/ops，执行 DataLoader、TensorDataset、Normalize、Resize、ToTensor、随机数、Dropout、采样和初始化。
3. **诊断层：** 确定性案例按有序语义字段定位首差异；随机案例比较均值、标准差、零值比例和类别频率，不比较随机张量逐元素值。

Rust 侧新增可选 `DataPipelineSummary`，CLI 可将机器报告附加到统一迁移报告：

```bash
candle-cli migrate run <project> \
  --data-pipeline-report benchmarks/results/data_pipeline_randomness_v1.json \
  --pretty
```

该参数可以与 M14 的双运行时报告并存；非法或损坏的报告会在 `data_pipeline_diagnostics` 阶段失败，不会被静默接受。

## 冻结案例

| 类型 | 案例 | 预期 |
|---|---|---|
| 确定性等价 | TensorDataset 顺序、DataLoader 尾批次、Normalize、Resize、ToTensor、分类标签、布尔掩码 | 7/7 等价 |
| 故障注入 | HWC/CHW、float→bool、0–1→0–255、标签 float、掩码 int、drop-last、Resize 插值默认值、固定种子未重置 | 8 类首差异 |
| 统计等价 | Dropout、均匀采样、正态初始化 | 分布指标在阈值内；不要求序列相同 |

开发集包含 10 个案例，留出集包含 8 个案例。规则和预期在执行前已经固定；评测器要求清单恰好包含全部内建案例。

## 随机性口径

固定种子案例使用 128 个样本，分别记录两次执行是否可复现。故障端故意不重置种子，正确归类为 `reproducibility_mismatch`。

三个统计案例各使用 4096 个样本：

| 案例 | 主要绝对差异 | 阈值 | 结果 |
|---|---:|---:|---|
| Dropout | mean 0.0143；std 0.0083；零值比例 0.0107 | 0.08 / 0.08 / 0.05 | 通过 |
| 均匀采样 | mean 0.0513；std 0.0046；最大类别频率差 0.0164 | 0.08 / 0.08 / 0.04 | 通过 |
| 正态初始化 | mean 0.0121；std 0.0065 | 0.08 / 0.08 | 通过 |

三组 PyTorch/MindSpore 随机序列的 SHA-256 均不同，报告中的 `sequence_equal=false`；这不会被错误判定为迁移失败。当前阈值是冻结回归阈值，不是通用统计显著性结论。

## 验收记录

执行环境：

- 服务器：`mseco-4090`；
- Python：`/home/mseco/miniconda3/envs/zgr/bin/python`，版本 3.10.20；
- PyTorch：2.6.0+cu124；
- torchvision：0.21.0+cu124；
- MindSpore：2.9.0；
- Rust：cargo 1.94.1。

验收结果：

- Python 全量测试：331/331；
- Rust 全量测试：150/150；
- `cargo fmt --check`：通过；
- `cargo clippy --all-targets --locked`：通过，保留 6 类既有非阻断告警；
- 真实双框架 Benchmark：18/18；
- 分类准确率：100%；
- 首差异 Top-1：100%；
- Rust CLI + Python 报告集成：通过。

所有 Python 依赖调用均显式使用 `zgr` 解释器，没有修改服务器 `base` Conda 环境。远程测试在独立目录 `/home/mseco/candle-cli-m15-test-v2-20260806` 中完成，没有覆盖服务器原有仓库改动。

## 可审计文件

- 冻结清单：`benchmarks/migration/data_pipeline_randomness_v1.json`；
- 真实机器结果：`benchmarks/results/data_pipeline_randomness_v1.json`；
- 工作流集成结果：`benchmarks/results/data_pipeline_workflow_v1.json`；
- 诊断实现：`python/migration/data_pipeline.py`；
- Python 测试：`python/test_data_pipeline.py`；
- Rust Schema/CLI：`src/migration/schema.rs`、`src/cli/args.rs`、`src/cli/migrate.rs`。

## 限制与下一步

- 数据为固定的小型离线数组，没有覆盖真实图片目录、损坏样本、文本序列或可变长度音频。
- 尚未覆盖多进程 DataLoader worker、prefetch、pinned memory、分布式 sampler 和设备间传输。
- Resize 只验证输出形状、布局和显式插值语义，没有宣称两个图像处理内核逐像素一致。
- 4096 个样本足以形成稳定回归，但不能替代面向任意分布的正式统计检验和多次重复实验。
- M16 将继续覆盖 PYNATIVE/GRAPH、Adam/AdamW、多步轨迹和 Checkpoint 状态。
