# M0 稳定性基线验收记录

验收日期：2026-08-04

## 验收结论

M0 稳定性与安全基线已通过本地验收，可以在此基础上继续开发 PyTorch 到 MindSpore 迁移诊断能力。

本阶段只在本地分支 `feat/torch2mindspore-agent` 上开发，尚未上传 GitHub。

## 环境

- Windows 11
- Rust 1.97.1，GNU target，使用 Rust 自带 LLD 完成自包含链接
- Python 3.12.13
- Rust 编译产物与 Python 测试依赖放置在 D 盘临时目录，C 盘仅保留源码和必要工具链

## 自动化验收

| 检查项 | 结果 |
| --- | --- |
| `cargo fmt --all -- --check` | 通过 |
| `cargo check --all-targets` | 通过 |
| `cargo test --all-targets -- --test-threads=1` | 99 项通过，0 失败 |
| `python -m pytest python -q` | 31 项通过，0 失败 |
| `python -m compileall -q python` | 通过 |
| Bridge 4xx/5xx/网络错误重试语义专项检查 | 通过 |
| 工具清单一致性检查 | 通过，9 个工具 |
| `git diff --check` | 通过 |

## 已覆盖的关键风险

- Bridge Worker 在多轮对话中复用，不再每轮重复启动 Python 进程。
- Bridge 的 API、网络和本地模型错误默认显式返回，不再伪造成功结果。
- Windows 下的 UTF-8 中文 JSON Lines 协议可稳定往返。
- 未知运行时会明确失败，并向 CLI 返回非零退出状态。
- 上下文裁切以完整对话轮次为边界，不留下孤立的工具调用或工具结果。
- RAG 注入不再污染持久会话，也不会在多轮构建时递归膨胀。
- 工作目录边界、符号链接逃逸和会话 ID 路径穿越均有防护与测试。
- Shell 同时读取标准输出和错误输出，避免大输出死锁；超时或主进程退出时会清理进程树及后台任务。
- 工具输出按 UTF-8 字符边界截断，避免超长输出挤占上下文窗口。
- 工具注册、提示词、解析器回退列表和文档统一为 9 个工具。

## 下一阶段入口

M1 将建立统一、可版本化的迁移诊断 Schema，作为 AST 扫描、API 映射、双框架对拍、根因定位、自动修复和 Benchmark 统计的共同数据协议。
