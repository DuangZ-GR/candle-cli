# M7 双框架运行微基准

## 目标

静态扫描覆盖率和 Patch 语法有效率不能回答“迁移后的结果是否真的一致”。运行微基准因此提供一个可跨环境采集的验证链路：PyTorch 和 MindSpore 不必安装在同一个 Python 环境，只要分别生成标准 JSONL 轨迹，再将两个目录合并评估即可。

当前包含 5 个确定性前向案例、10 个 API 调用步骤，覆盖：

- 逐元素计算与归约：`add`、`sum`；
- shape 变换：`reshape`、`unsqueeze`；
- 线性代数与归约：`matmul`、`mean`；
- 激活与归约：`relu`、`sum`；
- 序列拼接与展平：`cat`、`flatten`。

每一步都通过公共 `TraceRecorder` 记录返回结构、dtype、shape、数值摘要、NaN/Inf 和耗时。评估器按版本化映射对齐调用并报告首个可观测偏差。

## 版本真实性门禁

每个清单独立固定版本族：`runtime-parity-v1` 对应 PyTorch `2.1.x`/MindSpore `2.9.x`，`runtime-parity-v2` 对应 PyTorch `2.6.x`/MindSpore `2.9.x`。默认情况下，版本不匹配不会产生正式采集结果；`--allow-version-mismatch` 只用于验证采集链路，最终报告仍会把 `version_prefixes_match` 标记为 `false`，并禁止 `passed: true`。

这条门禁避免把“某个较新版本上的冒烟通过”包装成与知识库声明版本一致的运行准确率。

## 执行方式

以下命令以已经完成真实验收的 `runtime-parity-v2` 为例。在 PyTorch 2.6 环境：

```bash
python -m migration.runtime_parity capture pytorch ./runtime-captures/pytorch \
  --manifest benchmarks/migration/runtime_parity_v2.json --pretty
```

在 MindSpore 2.9 环境：

```bash
python -m migration.runtime_parity capture mindspore ./runtime-captures/mindspore \
  --manifest benchmarks/migration/runtime_parity_v2.json --pretty
```

将两个子目录放在同一个 `runtime-captures` 下后评估：

```bash
python -m migration.runtime_parity evaluate ./runtime-captures \
  --manifest benchmarks/migration/runtime_parity_v2.json --pretty
```

采集器不会下载模型、数据集或执行第三方工程代码；只执行仓库内固定、无随机性的微型张量运算。输出文件默认不可覆盖，只有显式 `--force` 才能重跑同一目录。

## Linux 真实验收结果

2026-08-05 在隔离的 Linux 测试目录完成 `runtime-parity-v2` 双端采集。源端使用 `zgr` Conda 环境，目标端使用由同一 Python 3.10 创建的独立 MindSpore 虚拟环境；没有降级或改写 `zgr` 中的 PyTorch。MindSpore 官方 `run_check()` 确认 CPU 平台安装成功，微基准两端均显式使用默认 CPU 张量执行。

| 项目 | 结果 |
|---|---:|
| Linux | Ubuntu 24.04.3 LTS，x86_64 |
| Python | 3.10.20 |
| PyTorch 源端 | `2.6.0+cu124`，5/5 案例、10/10 调用成功 |
| MindSpore 目标端 | `2.9.0`，5/5 案例、10/10 调用成功 |
| 版本门禁 | 两端均通过 |
| 已评估案例 | 5/5 |
| runtime parity | 100%（5/5 等价） |
| 分类准确率 | 100%（5/5 标签判断正确） |
| 首个偏差 | 无 |
| 机器可读证据 | `benchmarks/results/runtime_parity_v2.json` |

原始 JSONL 轨迹保存在服务器专用缓存，仓库提交固定清单和评估器输出。简历可以准确表述为“5 个确定性基础 API 链运行一致率 100%”，但不能省略微基准范围，也不能表述成“真实项目迁移准确率 100%”。

## 验收语义

完整报告同时满足以下条件才会 `passed: true`：

1. 5/5 案例同时存在 PyTorch 与 MindSpore 轨迹；
2. 两端实际版本分别属于所选清单固定的版本族；
3. 每个案例的等价/不等价判断都符合清单标签；
4. 所有 JSONL 均通过公共迁移 Schema 校验。

即使 5/5 通过，也只代表这 10 个基础 API 链路，不代表真实项目端到端迁移正确。后续应增加梯度、随机性、数据集流水线、Cell 训练/推理模式和缺失算子的真实用例。
