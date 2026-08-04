# M1 统一迁移诊断 Schema 验收记录

验收日期：2026-08-04

## 验收结论

Rust 控制面与 Python 执行面已经能够通过统一、版本化的 JSON 协议交换 API 轨迹和诊断结果。M1 通过本地验收，可以作为 AST 扫描、映射知识库、双框架对拍、自动修复和 Benchmark 的公共数据基础。

## 交付内容

- Rust 协议实现：`src/migration/schema.rs`
- Python 协议实现：`python/migration/schema.py`
- Draft 2020-12 机器可读 Schema：`schemas/migration-v1.schema.json`
- Rust/Python 共用固定样例：`tests/fixtures/migration`
- 中文协议说明：`docs/MIGRATION_SCHEMA.md`

## 协议保证

- 固定 `1.0` 版本，拒绝不兼容主版本，接受同主版本的新次版本。
- 未知枚举值安全降级为 `unknown`。
- 源码行号从 1 开始、列号从 0 开始，结束坐标必须成对且顺序合法。
- 动态 shape 使用 `null`，负数维度被拒绝。
- API 轨迹必须且只能包含 `output` 或 `error` 之一。
- 诊断必须包含证据，置信度必须位于 `[0, 1]`。
- `verified: true` 必须包含 `diff_validation` 证据。
- 默认记录摘要而非完整张量，避免测试产物无界增长或泄漏模型数据。

## 自动化验收

| 检查项 | 结果 |
| --- | --- |
| Rust Schema 专项测试 | 12 项通过，0 失败 |
| Python Schema 专项测试 | 15 项通过，0 失败 |
| `cargo fmt --all -- --check` | 通过 |
| `cargo check --all-targets` | 通过 |
| `cargo test --all-targets -- --test-threads=1` | 111 项通过，0 失败 |
| `python -m pytest python -q` | 46 项通过，0 失败 |
| `python -m compileall -q python` | 通过 |
| Schema、固定样例与中文文档 UTF-8 读取 | 通过 |

## 下一阶段入口

M2 将实现不依赖 PyTorch 安装的 Python AST 扫描器，解析 import 别名、API 调用、源码范围和参数表达式，并输出稳定的扫描报告。
