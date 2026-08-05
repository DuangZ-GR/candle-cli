# M7 双框架运行微基准

## 目标

静态扫描覆盖率和 Patch 语法有效率不能回答“迁移后的结果是否真的一致”。`runtime-parity-v1` 因此提供一个可跨环境采集的运行微基准：PyTorch 和 MindSpore 不必安装在同一台机器，只要分别生成标准 JSONL 轨迹，再将两个目录合并评估即可。

当前包含 5 个确定性前向案例、10 个 API 调用步骤，覆盖：

- 逐元素计算与归约：`add`、`sum`；
- shape 变换：`reshape`、`unsqueeze`；
- 线性代数与归约：`matmul`、`mean`；
- 激活与归约：`relu`、`sum`；
- 序列拼接与展平：`cat`、`flatten`。

每一步都通过公共 `TraceRecorder` 记录返回结构、dtype、shape、数值摘要、NaN/Inf 和耗时。评估器按版本化映射对齐调用并报告首个可观测偏差。

## 版本真实性门禁

清单固定 PyTorch `2.1.x` 和 MindSpore `2.9.x`。默认情况下，版本不匹配不会产生正式采集结果；`--allow-version-mismatch` 只用于验证采集链路，最终报告仍会把 `version_prefixes_match` 标记为 `false`，并禁止 `passed: true`。

这条门禁避免把“某个较新版本上的冒烟通过”包装成与知识库声明版本一致的运行准确率。

## 执行方式

在 PyTorch 2.1 环境：

```bash
python -m migration.runtime_parity capture pytorch ./runtime-captures/pytorch --pretty
```

在 MindSpore 2.9 环境：

```bash
python -m migration.runtime_parity capture mindspore ./runtime-captures/mindspore --pretty
```

将两个子目录放在同一个 `runtime-captures` 下后评估：

```bash
python -m migration.runtime_parity evaluate ./runtime-captures --pretty
```

采集器不会下载模型、数据集或执行第三方工程代码；只执行仓库内固定、无随机性的微型张量运算。输出文件默认不可覆盖，只有显式 `--force` 才能重跑同一目录。

## 当前机器验收结果

当前 Windows 环境只具备 PyTorch `2.13.0+cpu`，未安装 MindSpore：

| 项目 | 结果 |
|---|---:|
| Python | 3.12.13 |
| PyTorch 非正式采集 | 5/5 案例、10/10 调用成功 |
| PyTorch 版本门禁 | 不通过（要求 `2.1.x`，实际 `2.13.0+cpu`） |
| MindSpore 采集 | `unavailable` |
| 双框架已评估案例 | 0/5 |
| 正式 runtime parity | 未产生，不报告虚假百分比 |

非正式轨迹只保存在 D 盘外部缓存，没有加入仓库。正式数据需要在 Linux/ModelArts 的 MindSpore 2.9 环境补跑；完成前，简历中只能使用 M6 的静态覆盖数据，不能声称“运行一致率”。

## 验收语义

完整报告同时满足以下条件才会 `passed: true`：

1. 5/5 案例同时存在 PyTorch 与 MindSpore 轨迹；
2. 两端实际版本分别属于 `2.1.x` 与 `2.9.x`；
3. 每个案例的等价/不等价判断都符合清单标签；
4. 所有 JSONL 均通过公共迁移 Schema 校验。

即使 5/5 通过，也只代表这 10 个基础 API 链路，不代表真实项目端到端迁移正确。后续应增加梯度、随机性、数据集流水线、Cell 训练/推理模式和缺失算子的真实用例。
