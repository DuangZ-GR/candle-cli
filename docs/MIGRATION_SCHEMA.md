# 迁移诊断协议 v1

`candle-cli` 使用版本化 JSON 记录连接 Rust 控制面、Python 分析器、框架执行器、Benchmark 和报告生成器。机器可读定义位于 `schemas/migration-v1.schema.json`。

## 兼容性规则

- 当前版本为 `1.0`。
- 主版本变化表示不兼容；读取器必须拒绝不支持的主版本。
- 同一主版本内可以增加可选字段；读取器应忽略不认识的字段。
- 未知枚举值降级为 `unknown`，但原始值可保存在 `metadata` 中供排查。
- JSON 文件使用 UTF-8；流式轨迹使用一行一条记录的 JSON Lines。

Rust 实现在 `src/migration/schema.rs`，Python 实现在 `python/migration/schema.py`。两端共同读取 `tests/fixtures/migration` 中的固定样例，防止字段名或枚举编码发生漂移。协议当前包含 `api_trace`、`diagnostic`、`scan_report`、`trace_comparison`、`msprobe_import_report`、`rewrite_plan`、`rewrite_apply_report` 和 `rewrite_rollback_report` 八种记录。

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

## 轨迹比较结果

`trace_comparison` 汇总源轨迹数、目标轨迹数、对齐数和等价性。等价结果不能包含诊断；非等价结果必须包含一条经过 `diff_validation` 验证的诊断。由此保证正常的“发现差异”仍是一次成功执行，调用方应读取 `equivalent`，而不是把进程退出码当成模型等价性。

## msprobe 导入报告

`msprobe_import_report` 记录框架版本、运行 ID、输入输出产物、成功导入数和跳过原因。导入器只处理 API 级前向记录，并把官方 `dump.json` 中的 dtype、shape、Max、Min、Mean 统计量转换为标准轨迹；模块、反向和无法识别的记录不会静默丢弃，而是进入 `skipped`。

## 扫描报告

`scan_report` 汇总静态发现的 PyTorch API、源码范围、调用形式、置信度、初步风险和扫描问题。报告中的汇总计数必须与 findings/issues 明细严格一致，Rust CLI 在输出或写文件前会再次执行强类型校验。

## 确定性重写记录

`rewrite_plan` 是只读预览，包含每个文件应用前后的 SHA-256、字符坐标编辑、统一 diff、映射状态和未处理问题。路径始终相对于迁移根目录；出现语法错误、越界符号链接或超限文件时，默认禁止部分应用。

`rewrite_apply_report` 表示事务已经完整写入。`verified` 只有在调用方提供的无 shell 验证命令以退出码 0 完成时才为 `true`；未执行验证时必须为 `false` 且 `validation.status` 为 `not_run`。验证失败或超时不会产生成功报告，已修改源码会自动恢复，事务清单保留为 `aborted` 以供审计。

`rewrite_rollback_report` 只表示事务中的文件已恢复。回滚前会同时校验备份哈希和当前 Patch 哈希，防止静默覆盖应用后的用户修改。`--force` 是显式的覆盖选择，不是默认行为。

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
- 轨迹源码位置相对于项目根目录保存；项目外文件只保留文件名。
- `metadata` 用于可选实验信息，不应存放令牌、认证头或用户隐私数据。
