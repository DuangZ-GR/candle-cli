# M12 真实训练步骤差分验证

## 目标

M11 已经验证了组件前向、单个梯度和推理/训练状态差异，但还没有证明迁移后的
网络能够完成一次参数更新。`runtime-training-v1` 把双框架比较扩展为一个完整且
可观测的最小训练步骤：

```text
前向输出 → MSE 损失 → 参数梯度 → SGD 一步更新后的参数
```

该评测的目标是定位训练过程中第一个语义偏差，不是比较训练性能，也不代表模型
收敛质量。

## 固定协议

清单位于 `benchmarks/migration/runtime_training_v1.json`，固定 PyTorch `2.6.x`、
MindSpore `2.9.x`、数值容差和三个案例。

| 划分 | 案例 | 预期 |
|---|---|---|
| development | Linear + MSE + SGD 一步更新 | 四阶段等价 |
| development | 两层 MLP + ReLU + MSE + SGD 一步更新 | 四阶段等价 |
| heldout | 目标端学习率从 `0.1` 注入为 `0.2` | 第 3 号调用 `value_mismatch` |

留出案例的前向、损失和梯度保持一致，只有优化器更新使用错误学习率。因此只有
比较更新后的参数，而不是只比较 loss，才能把首个偏差定位到优化器阶段。该案例
是明确标注的故障注入，不应描述为未知缺陷泛化结果。

## 采集与指标

每个案例使用相同的固定输入、标签、权重和偏置，并分别在两个框架进程中执行。
轨迹记录以下语义角色：

1. `forward`：模型输出；
2. `loss`：均方误差；
3. `gradient`：按模型参数顺序排列的梯度；
4. `parameter_update`：执行一次 SGD 后按相同顺序排列的参数快照。

实现依据 MindSpore 2.9 官方的
[`value_and_grad`](https://www.mindspore.cn/tutorials/en/r2.9.0/beginner/autograd.html)、
[`nn.SGD`](https://www.mindspore.cn/docs/en/r2.9.0/api_python/nn/mindspore.nn.SGD.html)
和 [`ops.mse_loss`](https://www.mindspore.cn/docs/en/r2.9.0/api_python/ops/mindspore.ops.mse_loss.html)
接口；清单同时固定版本前缀，避免未来 API 变化静默污染结果。

机器报告新增两个训练指标：

- `training_step_parity_rate`：预期等价训练案例完整四阶段通过率；
- `optimizer_defect_top1_accuracy`：优化器缺陷类别和首个调用位置同时正确的比例。

## 复现命令

PyTorch 2.6 环境：

```bash
PYTHONPATH=python python -m migration.training_parity capture pytorch \
  ./runtime-training-v1/pytorch --pretty
```

MindSpore 2.9 环境：

```bash
PYTHONPATH=python python -m migration.training_parity capture mindspore \
  ./runtime-training-v1/mindspore --pretty
```

合并评估：

```bash
PYTHONPATH=python python -m migration.training_parity evaluate \
  ./runtime-training-v1 --pretty
```

默认拒绝覆盖已有轨迹，只有显式传入 `--force` 才会重新采集。版本不符合清单时
默认失败；`--allow-version-mismatch` 只能用于兼容性调试，不能生成正式结果。

## 当前验收状态

- 清单冻结、合成诊断、报告指标和 CLI wrapper 测试：9/9 通过；
- 本机 PyTorch 1.8 兼容性调试：3/3 案例、12/12 调用采集成功；
- 正式 PyTorch 2.6.0+cu124 / MindSpore 2.9.0 数据：两端均完成 3/3 案例和 12/12 调用采集；
- 合并评估：3/3 案例通过，2/2 等价训练步骤完整通过，1/1 学习率注入缺陷在优化器更新阶段 Top-1 定位正确；
- 机器可读结果：`benchmarks/results/runtime_training_v1.json`。

## 边界

- 每个案例只执行一个确定性 CPU 优化器步骤；
- 仅覆盖 SGD，不覆盖 Adam、优化器状态恢复或学习率调度器；
- 不覆盖混合精度、梯度缩放、梯度累积、分布式训练或多步收敛；
- 小张量能够记录完整数值预览，大张量仍受轨迹截断限制；
- 三个固定案例不能外推为真实项目端到端迁移准确率。
