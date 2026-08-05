# M3 版本化 API 映射知识库验收记录

验收日期：2026-08-05

## 验收结论

已建立第一版带框架版本、差异类型和官方证据的 PyTorch→MindSpore 映射知识库。映射查询已接入 Rust CLI 和静态扫描报告，未知条目不会被误报为 MindSpore 不支持。

## 数据基线

- 源框架：PyTorch 2.1
- 目标框架：MindSpore 2.9.0
- 快照版本：`ms2.9.0-pt2.1-2026-08-05.1`
- 官方来源：MindSpore PyTorch API 映射表
- 已验证记录：37 条
- 通用差异参数：10 个

知识库只收录已经取得官方证据的映射。缺失条目返回 `unknown`；只有官方明确说明不支持时才允许写入 `unsupported`。

## 交付内容

- 映射快照：`knowledge/mappings/mindspore-2.9.0-pytorch-2.1.json`
- Python 校验与查询器：`python/migration/mapping.py`
- 覆盖率评测：`python/migration/mapping_benchmark.py`
- CLI 查询：`candle-cli migrate map <api>`
- 扫描报告自动富化：target API、status、differences、notes、evidence、版本
- Rust 强类型校验：映射状态、风险、目标 API 与证据一致性

## 风险分级

| 映射状态 | 扫描风险 |
| --- | --- |
| `exact` | `low` |
| `difference` | `medium` |
| `unsupported` | `high` |
| `unknown` | `high` |

风险等级表示迁移时需要的审查强度，不表示运行时一定失败。

## 当前覆盖率

在 `torch2ms-scanner-v1` 固定开发集的 36 个唯一 API 上：

| 指标 | 结果 |
| --- | ---: |
| 已知映射 | 27 |
| Exact | 25 |
| Difference | 2 |
| Unknown | 9 |
| 映射覆盖率 | 75% |

该覆盖率是固定开发集的知识库收录率，不是转换正确率。后续需要扩展到至少 100 条规则，并在独立测试集上测量映射准确率。

## 自动化验收

| 检查项 | 结果 |
| --- | --- |
| 映射知识库专项测试 | 20 项通过，0 失败 |
| `cargo fmt --all -- --check` | 通过 |
| `cargo check --all-targets` | 通过 |
| `cargo test --all-targets -- --test-threads=1` | 120 项通过，0 失败 |
| `python -m pytest python -q` | 179 项通过，0 失败 |
| Scanner Benchmark | 50/50 精确匹配 |
| Mapping Benchmark | 27/36，覆盖率 75% |
| Python compileall | 通过 |
| JSON 与 UTF-8 产物检查 | 通过 |

全量 Rust 首次运行时，已有的 Shell 后台任务清理测试因系统时序抖动超过 3 秒阈值；该用例随后连续三次分别约 0.33、0.35、0.33 秒通过，完整测试套件复跑 120/120 通过。该过程保留在验收记录中，不隐藏偶发失败。

## 下一阶段入口

M4 将建立 PyTorch/MindSpore 运行时轨迹采集、归一化和序列对齐，以 dtype、shape、返回结构、NaN/Inf 和数值误差定位第一个可观测偏差。
