# Real Inference and API Mode Design

**Date:** 2026-04-29

## Goal

Move `LocalBridgeRuntime` beyond stub responses by letting the Python bridge perform real generation through either local transformers models or an OpenAI-compatible API.

## Runtime Boundary

Rust continues to own CLI, session, tools, permissions, context building, and agent orchestration. Python owns transitional model execution behind the existing stdio JSON bridge. The upper Rust layers continue to depend only on `CandleTargetRuntime`.

## Python Bridge Modes

### Local transformers mode

The bridge loads `AutoTokenizer` and `AutoModelForCausalLM`, formats chat messages with the tokenizer chat template, and calls `model.generate`. Model ID, device, local-files-only behavior, max tokens, temperature, top-p, and verbosity are controlled by environment variables.

### API mode

When `CANDLE_CLI_API_BASE_URL` is set, the bridge skips local model loading and sends OpenAI-compatible `/chat/completions` requests. This supports Ollama, vLLM, and OpenAI-style endpoints.

## Fallback Behavior

If local model loading or generation fails, the bridge returns a deterministic stub-style response so CLI and Rust integration tests remain runnable in lightweight environments.

## Diagnostics

When `CANDLE_CLI_VERBOSE=1`, diagnostics go to stderr so stdout remains reserved for JSON protocol responses. Diagnostics include model loading, API calls, token usage, latency, and GPU memory where available.

## Deferred Work

- Streaming output.
- Structured tool calling.
- Direct candle-native inference.
