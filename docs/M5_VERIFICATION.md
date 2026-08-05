# M5 确定性重写与验证闭环验收记录

## 结论

当前执行批次 M5（对应路线图中的“自动修复与验证闭环”第一阶段）已形成可复现的安全闭环：默认只生成最小 Patch 预览；显式应用时校验源码哈希并保存事务备份；可运行无 shell 验证命令；验证失败、超时或启动异常时自动恢复源码；成功应用仍可通过事务清单回滚。

本阶段只把具有官方证据、能够确定性表达的规则放入自动重写路径。未知映射保持不变；带差异映射默认跳过，必须通过 `--include-differences` 显式选择。

## 交付内容

- `python/migration/rewriter.py`：基于 AST 坐标、import 别名和作用域解析生成最小文本编辑，不格式化整个文件。
- `knowledge/rewrites/mindspore-2.9.0-pytorch-2.1.json`：版本化 dtype 常量规则及官方证据链接。
- `candle-cli migrate rewrite <path>`：默认预览；`--apply` 后才写入源码。
- `candle-cli migrate rollback <manifest>`：校验备份和当前 Patch 哈希后恢复事务文件。
- `rewrite_plan`、`rewrite_apply_report`、`rewrite_rollback_report`：Rust 强类型、Python 枚举和 JSON Schema 的统一记录类型。
- `benchmarks/migration/rewrite_cases`：固定、公开、可重复执行的合成重写开发集。

## 安全与验证语义

1. 只处理已被版本化映射知识库接受的函数调用；Tensor Method、动态调用和未知 API 不自动修改。
2. `difference` 映射默认不修改。当前 `torch.arange` 和 `torch.nn.Linear` 只有在显式开启后才进入 Patch。
3. dtype 常量只在其外层调用也被接受时修改，例如 `torch.zeros(..., dtype=torch.float32)`；不会全局替换独立的 `torch.float32`。
4. 即使官方映射标记为一致，只要调用显式携带 `out`、`device`、`requires_grad` 等 MindSpore 通用不支持参数，当前版本会整次跳过，等待参数适配规则或人工处理。
5. 写入前重新计算源文件 SHA-256，防止预览后文件发生变化仍被覆盖。
6. 备份、临时文件和目标文件位于同一项目/文件系统，单文件通过 `fsync + os.replace` 替换；多文件失败时按相反顺序恢复。
7. 验证命令使用参数数组和 `shell=False`，标准输入关闭，默认超时 300 秒，stdout/stderr 各最多记录 16,384 个字符。
8. 只有验证命令返回 0 才输出 `verified: true`。未运行验证时明确输出 `verified: false`；失败、超时或进程启动异常会回滚且事务标记为 `aborted`。
9. 常规回滚会拒绝覆盖应用后又被用户修改的文件；只有显式 `--force` 才跳过 Patch 哈希检查。

## 使用方式

```bash
# 只预览，不修改源码
cargo run -- migrate rewrite ./project --pretty

# 应用精确映射并执行验证
cargo run -- migrate rewrite ./project --apply \
  --validate-program python --validate-arg=-m --validate-arg=pytest

# 显式允许带差异映射
cargo run -- migrate rewrite ./project --include-differences --pretty

# 回滚一次已应用事务
cargo run -- migrate rollback \
  ./project/.candle-cli/backups/<transaction-id>/manifest.json --pretty
```

## 固定开发集结果

`rewrite-cases-v1` 当前包含 14 个合成案例，其中 4 个是预期安全跳过案例。固定执行结果：

| 指标 | 结果 |
|---|---:|
| 精确 Patch 匹配 | 14/14，100% |
| 安全跳过准确率 | 4/4，100% |
| Patch 后语法有效率 | 14/14，100% |

这些数字只证明当前实现覆盖了仓库内公开的开发模式，不是 held-out 测试，也不代表真实 PyTorch 项目上的自动迁移成功率。简历中的真实指标需要在 M6 的独立项目集和实际 MindSpore 运行环境中重新测量。

## 本地回归结果

| 检查 | 结果 |
|---|---:|
| `cargo fmt --all -- --check` | 通过 |
| Rust `cargo test --all-targets` | 132/132 通过 |
| Python `pytest python -q` | 252/252 通过 |
| 重写器定向测试 | 28/28 通过 |
| Rust 迁移 CLI 端到端测试 | 14/14 通过 |
| JSON 协议与规则文档 UTF-8 解析 | 通过 |

当前本机工具链未安装 Clippy 组件；为遵守“C 盘只放必要文件”约定，本阶段没有额外下载该组件。编译、格式检查和全量测试均已完成。

## 官方证据

- PyTorch→MindSpore 官方 API 映射表：<https://www.mindspore.cn/docs/zh-CN/stable/note/api_mapping/pytorch_api_mapping.html>
- MindSpore 2.9 dtype 定义：<https://www.mindspore.cn/docs/en/stable/api_python/mindspore/mindspore.dtype.html>
- `mindspore.mint.ones` 的 dtype 参数：<https://www.mindspore.cn/docs/zh-CN/stable/api_python/mint/mindspore.mint.ones.html>
- `mindspore.mint.zeros` 的 dtype 参数：<https://www.mindspore.cn/docs/zh-CN/stable/api_python/mint/mindspore.mint.zeros.html>

## 已知边界与下一阶段

- 当前没有为 `torch.tensor` 建立官方映射，因此不会自动改写该构造调用。
- Level 2 目前只覆盖显式 dtype 常量；shape 重排、默认值补偿和复杂关键字改名仍需逐条证据规则与真实运行验证。
- 当前验证器可以运行项目自己的测试命令，但仓库尚未提供真实 PyTorch/MindSpore 双环境的自动编排。
- 固定重写集是合成开发集，尚未覆盖真实模型、第三方依赖、动态图控制流和 Graph Mode。
- 下一批工作应冻结独立测试集，接入至少一个真实网络组件，在实际 MindSpore 环境中统计 Patch 采用率、验证通过率、回滚率与首个偏差定位效果。
