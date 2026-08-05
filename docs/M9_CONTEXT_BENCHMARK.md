# M9 上下文裁切基准

## 结果

`context-compaction-v1` 对固定的英文长对话、中文长对话、工具密集对话和未超限对话执行当前“按完整用户轮次保留最近 N 轮”的策略：

| 场景 | 轮次 → 保留 | 估算 Token 前 → 后 | 减少率 |
|---|---:|---:|---:|
| 英文长对话 | 20 → 5 | 1,329 → 355 | 73.29% |
| 中文长对话 | 16 → 4 | 1,308 → 350 | 73.24% |
| 工具密集对话 | 12 → 3 | 1,509 → 402 | 73.36% |
| 未超限 | 4 → 4 | 288 → 288 | 0% |
| 合计 | — | 4,434 → 1,395 | 68.54% |

共减少 3,039 个**估算 Token**。四个场景均保留所有系统消息，工具密集场景没有留下孤立的 ToolCall 或 ToolResult；未超限场景不发生无意义裁切。

运行方式：

```bash
cargo run -- context-harness
```

机器可读结果位于 `benchmarks/results/context_compaction_v1.json`，单元测试会重算并核对结果文件，避免指标漂移。

## Token 与 Cache 必须区分

当前估算器按“中文字符约 1 Token、拉丁字符约 4 字符/Token”计算序列化消息长度。它适合做同一实现的确定性前后对比，但不是任一模型 Provider 的真实计费 tokenizer。

`context-compaction-v1` 本身不调用 Provider，也没有实现本地 prompt KV cache。因此这份确定性报告明确记录：

- `provider_cache_metrics_available: false`
- `provider_cache_hit_rate: null`

不能把 68.54% 的上下文裁切率写成 68.54% 的缓存命中率。M10 已让 Bridge 采集 Provider 返回的 input/output/cached input tokens，并在字段完整时计算整轮命中率；但只有固定 Provider、模型、请求集和计费口径并实际运行后，才能对外报告真实 cache hit rate 与成本节省，详见 `docs/M10_PROVIDER_USAGE.md`。

## 能力边界

当前策略是丢弃最旧完整轮次，不是语义总结：

- 优点是确定性强，不会拆散工具调用链，也不会产生总结幻觉；
- 缺点是旧事实会直接消失，长任务可能丢失关键约束；
- 评测没有衡量裁切前后的任务成功率，不能仅根据 Token 减少率判断效果更好。

下一阶段应引入“近期原文 + 结构化长期状态 + 可验证摘要”的分层上下文，并在同一任务集上同时报告 Token、成功率和事实保留率。
