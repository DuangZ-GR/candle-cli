# M14 真实模型切片与自动双运行时采集

## 目标

M14 将 M13 依赖用户预先准备 Trace 的工作流扩展为自动双运行时闭环：读取版本化清单，启动 PyTorch 源端、事务式应用确定性 Patch、启动 MindSpore 目标端、比较规范化 Trace，并在目标执行失败或语义不一致时恢复原始字节。

统一入口为：

```text
candle-cli migrate run <path> --apply --runtime-manifest <manifest.json>
```

## 外部源码与范围

固定来源为 PyTorch Examples 的 MNIST 示例：

- 仓库：`https://github.com/pytorch/examples.git`
- Commit：`acc295dc7b90714f1bf47f06004fc19a7fe235c4`
- 上游路径：`mnist/main.py`
- 许可证：BSD-3-Clause
- 上游源码：141 行
- 上游源码 SHA-256：`30a3359d1911d2d859dd090ce20be7ed132a33f508dc389f40366010b3e9ecc8`

`upstream_main.py` 和 `UPSTREAM_LICENSE` 保留上游原始内容。可执行评测不会宣称迁移完整 MNIST：它从 `Net.forward` 中提取分类器头，使用固定的四维合成特征替代卷积、数据下载与训练流程。该功能适配单独记录为 1 次人工 Patch；工作流只自动改写 `executable_slice.py`。

清单统计 2 个来源文件、166 行代码，其中实际运行切片为 25 行。100% 映射覆盖率只适用于运行切片中的 5 个调用发现，不能外推到完整 141 行上游程序。

来源、哈希和限制固定在：

- `benchmarks/migration/model_slices/pytorch_examples_mnist/PROVENANCE.json`
- `benchmarks/migration/model_slices/pytorch_examples_mnist/runtime_manifest.json`
- `benchmarks/migration/real_model_dual_runtime_v1.json`

## 双运行时协议

`dual-runtime-v1` 清单分别描述 PyTorch 与 MindSpore 的 Python 环境变量、参数数组、工作目录和 Trace 路径。执行器具有以下约束：

- 命令以参数数组启动，`shell=false`，stdin 关闭；
- Python、入口文件、源码和 Trace 路径必须位于允许的项目边界；
- 路径解析后再次检查，阻止 `..` 与符号链接逃逸；
- 只继承显式环境变量白名单，并注入清单中的固定变量；
- 每个进程限制 120 秒、8 GiB 地址空间和 60 秒 CPU 时间；
- stdout/stderr 有界收集，Trace 限制为 1 字节到 32 MiB；
- 运行前删除同名旧 Trace，只接受本次产生的新文件；
- 目标验证位于重写事务内部，失败后立即恢复源码；Trace 比较失败时再次执行校验和保护的回滚。

Rust 控制面反序列化并校验 `runtime_collection`，报告源文件/行数、映射覆盖、unknown API、自动/人工 Patch、采用率、两端状态、Trace 数、等价率和回滚结果。JSON 与 Markdown 使用同一份汇总数据。

## 固定场景

| 场景 | 故障 | 预期终态 | 验收证据 |
|---|---|---|---|
| `verified-apply` | 无 | `verified` | PyTorch/MindSpore Trace 等价，Patch 保留 |
| `target-runtime-rollback` | 目标进程失败 | `rolled_back` | 源端已采集，目标端失败，源码字节恢复 |
| `target-dtype-rollback` | 目标输出改为 bool | `rolled_back` | 首差异为 `dtype_mismatch`，源码字节恢复 |

## 正式结果

正式环境：Linux x86_64、Python `3.10.20`、PyTorch `2.6.0+cu124`、MindSpore `2.9.0`。MindSpore 在 CPU 后端通过官方 `run_check`。

| 指标 | 结果 |
|---|---:|
| 固定场景通过率 | 3/3，100% |
| 成功闭环 | 1/1 |
| 故障回滚 | 2/2，100% |
| 运行切片映射覆盖 | 5/5，100% |
| unknown API | 0 |
| 自动/人工 Patch | 6/1 |
| 自动 Patch 采用率 | 6/7，85.7143% |
| 成功场景源端/目标端 Trace | 1/1 |
| 运行时失败场景源端/目标端 Trace | 1/0 |
| dtype 场景源端/目标端 Trace | 1/1 |
| dtype 首错分类 | `dtype_mismatch` |

单场景工作流耗时：

- 成功闭环：`27,064.597 ms`
- 目标运行失败并回滚：`13,968.802 ms`
- dtype 差异定位并回滚：`27,267.117 ms`

机器可读结果位于 `benchmarks/results/real_model_dual_runtime_v1.json`，其中保留每一步的毫秒级耗时、命令、版本、资源限制、Trace 大小、事务清单和诊断证据。

## 测试验收

- 本地 M14 定向 Python：51/51 通过；
- 远端 `zgr` 完整 Python：325/325 通过；
- 远端 Rust `cargo test --all-targets --locked`：148/148 通过；
- 真实双运行时 Benchmark：3/3 通过；
- JSON 通过 UTF-8 解析，下载前后 SHA-256 一致。

## 复现

```bash
export PYTHONPATH="$PWD/python"
export CANDLE_CLI_PYTORCH_PYTHON=/path/to/pytorch/python
export CANDLE_CLI_MINDSPORE_PYTHON=/path/to/mindspore/python

python -m migration.real_model_benchmark \
  --pytorch-python "$CANDLE_CLI_PYTORCH_PYTHON" \
  --mindspore-python "$CANDLE_CLI_MINDSPORE_PYTHON" \
  --output benchmarks/results/real_model_dual_runtime_v1.json \
  --pretty
```

也可以直接运行单个工作流：

```bash
cargo run -- migrate run \
  benchmarks/migration/model_slices/pytorch_examples_mnist/executable_slice.py \
  --apply \
  --runtime-manifest \
  benchmarks/migration/model_slices/pytorch_examples_mnist/runtime_manifest.json \
  --format markdown \
  --output migration-report.md
```

## 限制

- 评测执行的是来自真实项目的分类器头切片，不是完整 MNIST 数据、卷积网络或训练收敛；
- 1 次人工功能适配被显式统计，不能表述为全自动迁移；
- 两个失败案例是已知故障注入，只证明控制流、诊断和恢复能力；
- 单一固定切片的 100% 场景通过率不是未知项目迁移成功率；
- 尚未覆盖数据流水线、随机性、Graph Mode、混合精度、分布式训练和自定义算子，这些分别属于 M15/M16。
