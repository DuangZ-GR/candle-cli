# 迁移诊断协议 v1

`candle-cli` 使用版本化 JSON 记录连接 Rust 控制面、Python 分析器、框架执行器、Benchmark 和报告生成器。机器可读定义位于 `schemas/migration-v1.schema.json`。

## 兼容性规则

- 当前版本为 `1.0`。
- 主版本变化表示不兼容；读取器必须拒绝不支持的主版本。
- 同一主版本内可以增加可选字段；读取器应忽略不认识的字段。
- 未知枚举值降级为 `unknown`，但原始值可保存在 `metadata` 中供排查。
- JSON 文件使用 UTF-8；流式轨迹使用一行一条记录的 JSON Lines。

Rust 实现在 `src/migration/schema.rs`，Python 实现在 `python/migration/schema.py`。两端共同读取 `tests/fixtures/migration` 中的固定样例，防止字段名或枚举编码发生漂移。

## 坐标约定

- `file` 是相对于待迁移项目根目录的路径，不记录宿主机绝对路径。
- `line` 和 `end_line` 从 1 开始。
- `column` 和 `end_column` 从 0 开始，与 Python AST 一致。
- 结束行和结束列必须同时出现。

## API 轨迹

`api_trace` 表示一次确定的框架 API 调用，必须包含：

- 运行 ID、框架及版本、执行模式；
- 源码坐标、规范化 API 名称和本次运行中的调用序号；
- 参数的类型、dtype、shape 和可选数值摘要；
- `output` 或 `error`，且二者只能存在一个。

动态或无法确定的 shape 维度使用 `null`，不能使用 `-1`，从而避免把真实的负值与未知值混淆。`preview` 只保存经过长度限制和脱敏的样例，不用于完整张量传输。

## 诊断记录

`diagnostic` 表示一条可解释的迁移结论。分类包括：

- `missing_operator`、`unmapped_api`；
- `parameter_mismatch`、`default_value_mismatch`；
- `dtype_mismatch`、`shape_mismatch`、`return_structure_mismatch`；
- `value_mismatch`、`gradient_mismatch`、`randomness_mismatch`；
- `graph_compile_failure`、`device_unsupported`、`runtime_error`；
- `needs_manual_review`。

每条诊断必须包含至少一条证据，置信度必须位于 `[0, 1]`。只有包含 `diff_validation` 证据的诊断才能设置 `verified: true`，确保“已验证”代表实际执行对拍结果，而不是模型判断。

## 数据最小化

- 默认只记录 dtype、shape、统计量和截断预览，不保存完整输入、输出或模型权重。
- traceback 和预览在写入报告前需要执行路径与密钥脱敏。
- `metadata` 用于可选实验信息，不应存放令牌、认证头或用户隐私数据。
