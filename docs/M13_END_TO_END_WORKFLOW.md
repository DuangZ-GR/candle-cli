# M13 端到端迁移闭环

## 目标

M13 将此前独立的扫描、确定性改写、程序验证、双框架 Trace 对比和事务回滚串成一个可重复执行的状态机。统一入口是：

```text
candle-cli migrate run <path>
```

默认模式只执行扫描和 Patch 预览，不修改源码；`--apply` 模式强制要求验证程序。若验证失败、超时或后续 Trace 比较发现首个语义偏差，工作流会恢复事务中的全部文件，并保留 JSON/Markdown 报告和备份清单。

## 执行状态

```text
scan → rewrite_preview → apply_and_validate → trace_compare → rollback（按需）
```

终态包括：

- `previewed`：完成扫描和预览，未修改源码；
- `verified`：补丁已应用且验证命令通过；若提供 Trace，两端还必须等价；
- `divergent`：预览模式下给定的 Trace 不等价；
- `rolled_back`：应用后验证失败或 Trace 不等价，源码已恢复；
- `failed`：输入、执行或回滚本身失败。

机器报告记录每一步状态和毫秒级耗时，并汇总扫描文件数、发现数、映射分布、改写文件数、Edit 数、验证状态、Trace 等价性和首个偏差类别。Rust 侧会再次反序列化并校验 `migration_run_report`，避免 Python 子进程返回不完整或自相矛盾的成功结果。

## 安全约束

- `migrate run --apply` 必须提供 `--validate-program`，不允许产生“已应用但未验证”的闭环结果；
- 验证程序使用参数数组直接启动，不经过 Shell 字符串解释；
- 应用前重新校验预览源码哈希，并在同文件系统写入原子备份；
- 验证失败由重写事务立即恢复；Trace 偏差由工作流调用校验和保护的回滚；
- 只有在静态确认原 PyTorch import 的全部绑定均已无剩余引用时，才会替换该 import；混合迁移文件保留 PyTorch import。

## 使用方式

只生成 JSON 预览：

```bash
cargo run -- migrate run ./project --pretty
```

生成 Markdown 报告：

```bash
cargo run -- migrate run ./project \
  --format markdown --output migration-report.md
```

应用补丁并在 MindSpore 环境运行验证：

```bash
cargo run -- migrate run ./project --apply \
  --validate-program /path/to/mindspore/python \
  --validate-arg=-m --validate-arg=pytest
```

在验证后继续比较已有的双框架轨迹：

```bash
cargo run -- migrate run ./project --apply \
  --validate-program /path/to/mindspore/python \
  --validate-arg=validate_migration.py \
  --source-trace torch.jsonl --target-trace mindspore.jsonl \
  --format markdown --output migration-report.md
```

## 固定评测

`workflow-e2e-v1` 冻结了四个确定性场景：

| 场景 | 证据 | 预期终态 |
|---|---|---|
| 安全预览 | 源码字节保持不变 | `previewed` |
| 真实双框架应用 | PyTorch 原程序成功；改写后由 MindSpore 解释器成功执行 | `verified` |
| 验证失败注入 | 验证进程返回 7；源码字节恢复 | `rolled_back` |
| dtype Trace 偏差注入 | 首错分类为 `dtype_mismatch`；源码字节恢复 | `rolled_back` |

Linux 正式运行环境为 PyTorch `2.6.0+cu124` 与 MindSpore `2.9.0`，结果如下：

- 4/4 场景符合冻结预期，工作流通过率 100%；
- 4/4 迁移前 PyTorch 程序执行成功；
- 1/1 真实 MindSpore 应用通过验证；
- 2/2 故障场景完整回滚，源码字节恢复率 100%；
- 1/1 dtype 注入缺陷首错 Top-1 分类正确并触发回滚。

机器可读结果位于 `benchmarks/results/workflow_e2e_v1.json`，清单位于 `benchmarks/migration/workflow_e2e_v1.json`。

## 边界

- 可执行样例只有两个基础算子，证明控制流和回滚机制，不代表真实项目迁移准确率；
- 两个失败案例是明确标注的故障注入，不代表未知缺陷泛化能力；
- 工作流接受已有 Trace，尚未自动启动两个框架的采集命令；
- 尚未覆盖数据流水线、Graph Mode、混合精度、分布式训练和真实模型端到端迁移；
- `--include-differences` 仍需用户显式选择，默认只应用 exact 映射。
