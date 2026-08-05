# M11 组件级双框架差分验证

## 目标

`runtime-parity-v2` 证明了 5 条基础前向 API 链可以在 PyTorch 2.6 与
MindSpore 2.9 中分别采集并对齐，但它没有覆盖真实网络组件、梯度、训练/推理
状态或预期不等价案例。`runtime-components-v1` 将评测提升到组件级，并把
“是否发现偏差”与“是否定位到正确类别和首个调用”分开计量。

## 固定协议

清单位于 `benchmarks/migration/runtime_components_v1.json`，包含 7 个确定性
案例、12 个调用记录，并固定 PyTorch `2.6.x` 与 MindSpore `2.9.x` 版本门禁。

| 划分 | 案例 | 预期 |
|---|---|---|
| development | 两层 MLP 前向 | 等价 |
| development | Conv2d + ReLU + Flatten | 等价 |
| development | 输入与权重梯度 | 等价 |
| development | BatchNorm2d 推理状态 | 等价 |
| heldout | 浮点结果误转布尔值 | `dtype_mismatch`，首错 0 |
| heldout | PyTorch/MindSpore 默认训练状态差异 | `value_mismatch`，首错 0 |
| heldout | MindSpore 目标算子缺失注入 | `missing_operator`，首错 0 |

两个 `fault_injection: true` 案例用于验证诊断器，不代表 MindSpore 2.9 真实缺失
对应算子。BatchNorm 默认模式案例来自框架真实默认行为差异。留出子集在协议固化后
不参与等价组件的参数修正，但它仍是仓库内的小型固定集合，不应表述成行业基准。

## 比较器增强

公共 `TraceRecorder` 现在为每个调用记录 `semantic_role`、数据划分和故障注入
标记。比较器新增三项能力：

1. 对小张量的数值预览逐项比较，避免元素重排后 min/max/mean 不变而误判等价；
2. 将梯度调用的数值偏差归类为 `gradient_mismatch`；
3. 将目标端的 `AttributeError`、`ImportError`、`ModuleNotFoundError` 或
   `NotImplementedError` 归类为 `missing_operator`。

组件清单显式提供 PyTorch/MindSpore API 对，不把仅用于运行评测的旧接口名称
写入官方映射知识库。

## 真实执行中发现的参数差异

第一次真实运行把 CNN 的首个偏差定位到第三步 `flatten`：PyTorch 默认从第 0
维展开，而 MindSpore `ops.flatten` 默认保留 batch 维，分别得到 `[8]` 与
`[1, 8]`。随后将迁移调用固定为关键字 `start_dim=0`。MindSpore 该参数是
keyword-only，因此位置参数会产生 `TypeError`；最终实现同时适配两端正确签名。

这个过程展示了组件差分验证的作用：API 名称看似可替换时，仍能用 shape 轨迹定位
默认参数和调用签名差异。

## 复现命令

PyTorch 2.6 环境：

```bash
PYTHONPATH=python python -m migration.component_parity capture pytorch \
  ./runtime-components-v1/pytorch --pretty
```

MindSpore 2.9 环境：

```bash
PYTHONPATH=python python -m migration.component_parity capture mindspore \
  ./runtime-components-v1/mindspore --pretty
```

合并评估：

```bash
PYTHONPATH=python python -m migration.component_parity evaluate \
  ./runtime-components-v1 --pretty
```

默认不覆盖已有轨迹；只有显式传入 `--force` 才会重跑同一目录。

## 2026-08-05 Linux 验收

源端使用 `zgr` Conda 环境中的 PyTorch，目标端使用独立 MindSpore 虚拟环境，
没有降级或修改 `zgr`。

| 指标 | 结果 |
|---|---:|
| Python | 3.10.20 |
| PyTorch | `2.6.0+cu124` |
| MindSpore | `2.9.0` |
| 双端采集 | 7/7 案例，12/12 调用记录 |
| 等价组件通过率 | 4/4（100%） |
| 梯度一致率 | 1/1（100%） |
| 等价/不等价分类准确率 | 7/7（100%） |
| 留出偏差首错 Top-1 | 3/3（100%） |
| 版本门禁 | 两端通过 |
| Python 全量回归 | 297/297 |
| Rust 全量回归 | 143/143 |

机器可读结果位于 `benchmarks/results/runtime_components_v1.json`。调用耗时包含
首次框架编译、初始化和冷启动成本，只用于轨迹观察，不能解释为框架性能对比。
远端隔离 Rust 工具链未安装 `rustfmt` 组件，因此本轮没有在服务器重复执行
`cargo fmt --check`；本轮未修改任何 Rust 源码，`cargo test --locked` 已全量通过。

## 边界

- 这是 7 个小型确定性组件，不是真实项目端到端迁移准确率。
- 两个故障注入案例只证明固定缺陷能被识别，不能代表未知错误泛化能力。
- 梯度案例覆盖一个确定性函数及输入/权重梯度，不代表完整训练任务。
- 尚未覆盖随机性统计检验、数据流水线、优化器状态、Graph Mode 或真实模型训练。
- 大张量仍以有限预览和数值摘要比较；不能声称进行了全元素证明。

因此简历可准确表述为“在 4 个确定性组件和 3 个固定迁移缺陷案例中完成真实
PyTorch/MindSpore 双端验证”，不能写成“真实项目迁移准确率 100%”。
