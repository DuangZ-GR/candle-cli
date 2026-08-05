# M4 验收：差分轨迹与首个偏差定位

## 结论

当前执行批次 M4（对应路线图中的“差分轨迹接入与根因诊断”）已经完成第一版可复现闭环：可从轻量运行时采集器或 msprobe `dump.json` 获得统一 JSONL 轨迹，通过版本化 API 映射对齐 PyTorch/MindSpore 调用，并输出第一个可观测偏差及其证据。

本阶段没有把“最终抛错位置”直接当作根因。比较器按调用顺序检查运行时错误、返回结构、dtype、shape、NaN/Inf 和数值摘要，遇到第一个差异即生成 `verified: true` 的 `diagnostic`。

## 交付内容

- `python/migration/trace_capture.py`：不强制导入框架的鸭子类型采集器，支持 Tensor、标量、布尔值、字符串、序列、字典、异常和嵌套返回值。
- `python/migration/msprobe_import.py`：将当前 msprobe API 级前向 `dump.json` 规范化为公共 JSONL；不支持的记录进入带原因的 `skipped`。
- `python/migration/trace_compare.py`：通过映射知识库和 LCS 对齐调用序列，定位首个可观测差异。
- `candle-cli migrate import-msprobe` 与 `candle-cli migrate compare`：Rust CLI 控制面负责启动 Python 执行面并对结果做强类型校验。
- `trace_comparison` 与 `msprobe_import_report`：已加入 Rust、Python 和 JSON Schema v1 公共协议。
- `benchmarks/migration/trace_cases`：固定、公开、可重复执行的合成缺陷注入产物。

## 使用方式

```bash
cargo run -- migrate import-msprobe torch_dump/dump.json torch.jsonl \
  --framework pytorch --framework-version 2.1 --run-id experiment-001

cargo run -- migrate import-msprobe ms_dump/dump.json mindspore.jsonl \
  --framework mindspore --framework-version 2.9.0 --run-id experiment-001

cargo run -- migrate compare torch.jsonl mindspore.jsonl --pretty

python -m migration.trace_benchmark --pretty
```

比较器发现 dtype 或数值差异时仍返回成功退出码，因为“差异”是有效业务结果；自动化脚本应读取 JSON 中的 `equivalent`。

## 验收数据

### 全量回归

- Rust：127/127 通过。
- Python：224/224 通过。
- Windows 中文 JSON：在显式清除 `PYTHONUTF8` 与 `PYTHONIOENCODING` 后复测通过，迁移子命令会主动把 stdout/stderr 配置为 UTF-8。

### 固定缺陷注入集

数据集版本：`trace-defects-v1`。

- 总场景：10。
- 等价场景：2，包括严格等价和容差内数值扰动。
- 缺陷场景：8，包括 dtype、shape、数值、NaN、返回结构、运行时错误、第二次调用偏差和调用缺失。
- 等价性分类准确率：10/10，100%。
- 差异类别准确率：8/8，100%。
- 首个偏差 Top-1：8/8，100%，高于本里程碑 80% 门槛。

这些数字只说明当前确定性算法能够覆盖仓库内公开的合成模式。数据集由本项目构造，规模小、没有盲测，也没有包含真实模型噪声，因此不能写成“真实迁移准确率 100%”。真实简历数据必须在后续 held-out 项目集和实际 MindSpore 环境上重新测量。

## 官方依据

- MindSpore 官方 PyTorch API 映射表用于调用对齐和版本证据：<https://www.mindspore.cn/docs/zh-CN/stable/note/api_mapping/pytorch_api_mapping.html>
- 当前 msprobe MindSpore 数据采集文档说明 `dump.json` 包含 API/Cell 名称、dtype、shape、Max、Min、Mean 等统计量：<https://gitee.com/ascend/mstt/blob/master/debug/accuracy_tools/msprobe/docs/06.data_dump_MindSpore.md>
- msprobe 跨框架比较文档给出了 `input_args`、`input_kwargs`、`output` 和 Tensor 统计字段示例：<https://gitee.com/ascend/mstt/blob/master/debug/accuracy_tools/msprobe/docs/11.accuracy_compare_MindSpore.md>
- 旧版 Troubleshooter API Dump 只支持 MindSpore PyNative，因而本阶段优先适配当前 msprobe 格式：<https://gitee.com/mindspore/toolkits/blob/master/troubleshooter/docs/api_compare.md>

## 已知限制

- msprobe 导入器当前只处理 API 级前向记录；模块级、反向、静态图 Kernel 和真实 `.npy` 张量比较留到后续阶段。
- `dump.json` 的统计字段没有提供可靠的 NaN/Inf 个数，导入记录会标注 `nan_inf_counts_available: false`；不得把缺失信息解释为数量为零。
- 轻量采集器对超过 100,000 元素的 Tensor 默认省略数值统计，避免为了调试把超大 Tensor 整块传回主机；dtype 和 shape 仍会保留。
- LCS 只能在已有映射范围内对齐；未知 API 或额外/缺失调用会降级为 `needs_manual_review`。
- 当前 Benchmark 不是权威第三方 Benchmark，也不是 held-out 测试；下一版至少需要真实网络组件、独立标注和盲测集。

## 下一阶段

进入自动修复与验证闭环：先做确定性的 import/API 名称/关键字参数修复，再做 dtype、shape 和默认值适配；所有补丁必须支持预览、原子写入、回滚和修复后重新对拍，未通过验证的补丁不能标记为成功。
