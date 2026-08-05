# M2 Python AST 扫描器验收记录

验收日期：2026-08-04

## 验收结论

已实现不依赖 PyTorch 或 MindSpore 安装、不会执行目标工程代码的确定性 AST 扫描器，并通过 Rust CLI 提供 JSON 与 Markdown 报告。扫描结果已纳入 v1 共享协议并由 Rust 强类型二次校验。

## 交付内容

- Python AST 扫描器：`python/migration/scanner.py`
- Rust CLI：`candle-cli migrate scan <path>`
- JSON/Markdown 报告与安全覆盖策略
- `scan_report` Rust 类型和机器可读 JSON Schema
- 固定评测清单：`benchmarks/manifests/scanner_v1.json`
- 可复现评测入口：`python -m migration.scanner_benchmark`

## 已覆盖能力

- `import torch`、模块别名、`from import` 和 API 别名解析。
- 作用域、函数参数、赋值和二次 import 导致的别名遮蔽。
- 由构造调用、函数式 API、类型注解和链式调用推断的常见 Tensor Method。
- 字面量和动态 `getattr` 调用，其中动态名称标记为高风险、低置信度。
- PEP 263 源码编码、语法错误、读取错误、文件大小限制和常见目录忽略。
- 稳定排序、稳定 finding ID、相对路径、源码位置、参数数量与关键字名称。
- 报告文件默认拒绝覆盖，显式 `--force` 才允许替换。

## 当前评测数据

`torch2ms-scanner-v1` 是随仓库公开的第一版语法覆盖开发集：

| 指标 | 结果 |
| --- | ---: |
| 任务数 | 50 |
| 标注 API 调用数 | 49 |
| 完全匹配任务 | 50/50 |
| True Positive | 49 |
| False Positive | 0 |
| False Negative | 0 |
| Precision | 100% |
| Recall | 100% |

这些数据仅说明当前实现覆盖了该固定清单中的语法模式，不代表未知真实项目上的总体效果，也不作为最终简历指标。M6 需要补充冻结后的独立测试集和真实迁移项目样本。

## 自动化验收

| 检查项 | 结果 |
| --- | --- |
| AST 扫描专项测试 | 113 项通过，0 失败 |
| `cargo fmt --all -- --check` | 通过 |
| `cargo check --all-targets` | 通过 |
| `cargo test --all-targets -- --test-threads=1` | 116 项通过，0 失败 |
| `python -m pytest python -q` | 159 项通过，0 失败 |
| `python -m compileall -q python` | 通过 |
| 固定 Benchmark 独立执行 | 通过 |
| Schema、Benchmark 清单和文档 UTF-8 读取 | 通过 |

## 下一阶段入口

M3 将引入带框架版本、官方来源和差异说明的 MindSpore API 映射知识库，把扫描结果从 `unclassified` 转换为直接映射、存在差异、不支持或未知，并生成候选转换建议。
