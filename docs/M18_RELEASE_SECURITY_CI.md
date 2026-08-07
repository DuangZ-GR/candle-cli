# M18：安全留出集、CI 与发布闭环

## 当前状态

M18 已完成安全加固、冻结留出集、结构化 `doctor`、Linux/Windows 安装脚本、离线演示、跨平台 CI 配置和最终 Benchmark 证据聚合器。Tag、GitHub Release 和包发布仍未执行，必须等待用户确认。

## 安全修复

代码审计发现并修复了四类可复现问题：

1. 递归 `grep/glob` 原来会跟随工作区内部指向外部目录的符号链接；现在使用 `symlink_metadata` 并跳过所有递归 symlink 项。
2. `web_search` 原来把查询字符串拼入 Shell 中的 Python 源码；现在使用固定 Python 程序并把查询作为独立进程参数传递。
3. `WorkspaceWrite` 原来允许模型无需确认直接联网；现在 `web_search` 与宿主 Shell 一样需要交互确认，ReadOnly/子 Agent 仍硬拒绝联网。
4. `read` 会一次性载入任意大小文件，Shell reader 会无限累计输出；现在默认分别限制为 2 MiB 文件和 stdout/stderr 每路 1 MiB，可通过环境变量收紧。

Windows 原生 Shell 改用 `cmd.exe /D /S /C`，Unix 继续使用 `sh -c`；Docker 沙箱分支保持无网络和只读挂载。

## 冻结安全留出集

`benchmarks/security/security_heldout_v1.json` 与 M8 的开发回归集分离，固定 15 个攻击项和 8 个正常任务。Linux 结果：

| 指标 | 结果 |
|---|---:|
| 攻击总项 | 15 |
| 实际评估攻击项 | 12 |
| 明确不适用项 | 3 |
| 已评估攻击拦截/门禁 | 12/12，100% |
| 正常任务 | 8 |
| 正常任务误拦截率 | 0/8，0% |

三个 `not_applicable` 项不计入分母：

- 项目没有压缩包解压入口，因此不能用未接入生产路径的辅助函数制造“压缩包逃逸已防护”数据；
- 当前 `std::fs` canonicalize 方案可以阻止既有 symlink 逃逸，但不能证明具备基于 `openat`/句柄的竞态无关语义；
- Windows junction 必须在 Windows Runner 上单独验证，不能由 Linux symlink 结果推断。

提示注入项只验证无论模型文本如何，确定性权限层仍禁止子 Agent/Sandbox 外的 Shell、写入和联网；它不代表模型对未知提示注入的语义鲁棒性。

机器结果：`benchmarks/results/security_heldout_v1.json`。

## Doctor、安装和演示

`candle-cli doctor --json` 输出不含凭据的结构化检查，覆盖：Rust、当前 Python、PyTorch、MindSpore、Docker、Python Bridge Worker、Provider 配置以及 `CANDLE_CLI_PYTORCH_PYTHON`/`CANDLE_CLI_MINDSPORE_PYTHON` 双环境。

- `scripts/install.sh [--with-python]`：Linux/macOS；
- `scripts/install.ps1 [-InstallPythonDependencies]`：Windows；
- `scripts/demo.sh` / `scripts/demo.ps1`：执行 doctor、官方映射查询、静态扫描、确定性 Patch 预览和安全留出集。

安装默认不下载 PyTorch/MindSpore 等大型依赖；Bridge/双框架依赖必须显式选择。演示只预览 Patch，不修改 `examples/migration_demo/model.py`。

## CI 与发布策略

`.github/workflows/ci.yml` 包含：

- Ubuntu/Windows：Rust fmt、check、Clippy `-D warnings`、全量测试；
- Python 3.10/3.12：compileall 与全量 pytest；
- 独立 Schema/Benchmark 完整性 Job；
- 最小权限 `contents: read`。

`.github/workflows/release-dry-run.yml` 只能手工触发，构建 Linux/Windows Release 二进制并上传 Actions Artifact；它不会创建 Tag、GitHub Release 或发布包。

## 最终证据聚合

`python/release_report.py` 根据 `benchmarks/release/release_v1.json` 读取 13 组结果，验证必需的 pass/claim 门禁，只抽取白名单指标，并为每个来源记录 SHA-256。输出：

- `benchmarks/results/release_evidence_v1.json`；
- `docs/FINAL_BENCHMARK_REPORT_CN.md`。

其中 12 组为限定范围内可引用证据；Ollama 0.5B Smoke 固定为 `claim_eligible=false`，只能说明模型被能力门禁淘汰，不能作为多 Agent 收益数据。聚合不会把合成集、故障注入或小模型切片扩展成未知项目泛化结论。

## 复现命令

```bash
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --all

PYTHONPATH=python python -m pytest -q python
cargo run --locked --quiet -- security-heldout

PYTHONPATH=python python python/release_report.py \
  --config benchmarks/release/release_v1.json \
  --root . \
  --json-output benchmarks/results/release_evidence_v1.json \
  --markdown-output docs/FINAL_BENCHMARK_REPORT_CN.md
```

## 阶段性验收

- `cargo fmt --all -- --check`：通过；
- `cargo clippy --locked --all-targets -- -D warnings`：通过；
- `cargo test --locked --all`：177/177；
- `PYTHONPATH=python python -m pytest -q python`：350/350，严格使用远端 `zgr` Python；
- PowerShell 安装/演示脚本语法解析：通过；
- Shell 安装/演示脚本 `sh -n`：通过；
- 离线演示：通过，演示前后源码 SHA-256 一致；
- doctor：在 `zgr` 路径下返回可解析 JSON，且不输出 API Key；
- 最终 JSON/Markdown 证据重新生成后逐字节一致；
- 远端隔离目录：`/home/mseco/codex-cache/candle-cli-m17-final`，未覆盖服务器原仓库。

## 剩余发布边界

- 尚未在 GitHub 托管 Runner 上取得首次 CI 结果；本地/服务器验收不冒充 GitHub Actions 已通过。
- Windows junction 与 Windows 二进制仍需由 Windows CI/Release dry run 验证。
- 正式 Provider Token/Cache 和单/多 Agent 配对数据仍未产生，不写入最终收益声明。
- 版本号、发布 Commit、Tag 和 GitHub Release 只在用户确认后处理。
