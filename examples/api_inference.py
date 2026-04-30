"""
candle-cli API 模式推理示例

通过 OpenAI 兼容的 HTTP API 调用模型。

用法:
    # Ollama 本地 API
    CANDLE_CLI_API_BASE_URL="http://localhost:11434/v1" \\
    CANDLE_CLI_API_KEY="ollama" \\
    CANDLE_CLI_MODEL_ID="qwen2:0.5b" \\
    python3 examples/api_inference.py

    # vLLM
    CANDLE_CLI_API_BASE_URL="http://localhost:8000/v1" \\
    CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct" \\
    python3 examples/api_inference.py

    # 开启诊断输出
    CANDLE_CLI_VERBOSE=1 python3 examples/api_inference.py
"""

import json
import os
import sys
import time
import urllib.request


def main():
    base_url = os.environ.get("CANDLE_CLI_API_BASE_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("CANDLE_CLI_API_KEY", "ollama")
    model_id = os.environ.get("CANDLE_CLI_MODEL_ID", "qwen2:0.5b")
    verbose = os.environ.get("CANDLE_CLI_VERBOSE", "0") in ("1", "true")
    max_tokens = int(os.environ.get("CANDLE_CLI_MAX_NEW_TOKENS", "512"))
    temperature = float(os.environ.get("CANDLE_CLI_TEMPERATURE", "0.7"))

    url = base_url.rstrip("/") + "/chat/completions"

    messages = [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "请用一句话介绍你自己。"},
    ]

    body = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if verbose:
        print(f"[example] POST {url}")
        print(f"[example] model: {model_id}")
        print(f"[example] messages: {len(messages)}")
        print(f"[example] body: {json.dumps(body, ensure_ascii=False)[:300]}")

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")

    if verbose:
        print(f"[example] response in {time.time() - t0:.1f}s")

    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]

    print()
    print("模型回复:")
    print(content)


if __name__ == "__main__":
    main()
