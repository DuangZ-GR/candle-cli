# M10 Provider Token/Cache 可观测性

## 目标

上下文裁切的启发式 Token 减少率不能替代 Provider 的真实计费数据。本阶段把 OpenAI-compatible 流式响应中的 usage 信息贯通到 Rust Agent Trace，并且只有在一轮 Agent 的每次模型请求都返回相应字段时，才输出完整 Token 或缓存命中率。

## 数据链路

1. Python Bridge 默认发送 `stream_options.include_usage=true`；不兼容该选项的本地后端可设置 `CANDLE_CLI_INCLUDE_USAGE=false`。
2. 流式解析器单独处理 `choices=[]` 的最终 usage 块，不把它误当作内容块。
3. 统一采集 `prompt_tokens`、`completion_tokens` 和 `total_tokens`。
4. DeepSeek 的 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 和 OpenAI-compatible 的 `prompt_tokens_details.cached_tokens` 归一化为统一字段。
5. Rust Bridge 对字段做非负整数校验，多步 Agent Loop 与三步有界子 Agent 的调用量一并累计到 `/trace --json`。
6. M17 增加每次 Provider 请求的 `retry_count` 和端到端 `provider_latency_ms`；即使 Provider 不返回 Token usage，重试与延迟仍能保留，而 Token/Cache 继续为未知。
7. M17 增加 `ollama-native` API 风格，直接从 `/api/chat` 的 `prompt_eval_count` 和 `eval_count` 采集真实 usage；Ollama 未提供缓存拆分时继续报告未知。
8. M17 把实验绝对截止时间传递到 Python Worker、流式读取和重试退避，Provider 调用不再绕过 Agent 的墙钟预算。

Provider 给出的 `total_tokens` 必须等于 prompt 与 completion 之和；cached token 不能超过 prompt token，DeepSeek 同时提供 hit/miss 时二者之和必须等于 prompt token。主 usage 不合法时整次 usage 降级为未知；只有缓存拆分不合法时仅禁用缓存指标，不影响模型回复和主 Token 统计。

Trace 中的关键字段包括：

```json
{
  "usage": {
    "request_count": 2,
    "retry_count": 1,
    "provider_latency_ms": 1840,
    "usage_reported_request_count": 2,
    "usage_complete": true,
    "prompt_tokens": 150,
    "completion_tokens": 20,
    "total_tokens": 170,
    "cache_metrics_reported_request_count": 2,
    "cache_metrics_complete": true,
    "cached_prompt_tokens": 100,
    "provider_cache_hit_rate": 0.6666666666666666
  }
}
```

如果任一模型请求没有返回 usage，`usage_complete=false`，汇总 Token 输出为 `null`；如果任一请求缺少缓存明细，`cache_metrics_complete=false`，缓存 Token 和命中率为 `null`。已观测到的部分数据不会被错误包装成整轮完整数据。

## 当前结果边界

本阶段完成的是采集、归一化、聚合和完整性门禁，不产生虚假的 Provider 基准值。M17 已补充冻结 Provider/单多 Agent 实验协议、共享预算与重试/延迟遥测，但当前仓库仍没有提交真实 API Key，也没有完成固定账号、模型和请求集的联网评测，因此简历中仍不能写具体缓存命中率或账单节省率。

本地自动化验收：Rust 142/142、Python 287/287 全量测试通过，其中 Bridge 专项 36/36 通过。全量 Rust 首轮曾有既有的 Windows Shell 后台进程清理时序用例超过 3 秒门槛；该用例随后连续三次约 0.37、0.37、0.33 秒通过，完整套件复跑通过，未放宽门槛或隐藏该过程。

后续正式评测必须固定 Provider、模型 ID、请求集、执行时间、上下文策略和仓库提交，并同时报告：

- usage 完整请求数 / 总请求数；
- prompt、completion、cached prompt Token；
- Provider 缓存命中率；
- 请求延迟与失败/重试率；
- 按当时官方价格计算的估算成本，并注明价格日期。

对应的执行器为 `candle-cli agent-experiment`，严格拒绝 `TO_BE_SELECTED` 模板；原始记录由 `python/agent_experiment.py` 校验和聚合。完整设计与当前进度见 `docs/M17_CONTEXT_AGENT_ABLATION.md`。

## 官方协议依据

- DeepSeek Chat Completion：<https://api-docs.deepseek.com/api/create-chat-completion>
- OpenAI API Reference：<https://platform.openai.com/docs/api-reference>
