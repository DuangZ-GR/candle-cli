"""
candle-cli 本地模型推理示例

用法:
    # 默认模型 (Qwen/Qwen2-0.5B-Instruct)
    python3 examples/qwen3_local_inference.py

    # 指定模型
    CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct" python3 examples/qwen3_local_inference.py

    # 开启诊断输出
    CANDLE_CLI_VERBOSE=1 python3 examples/qwen3_local_inference.py

    # 使用 GPU
    CANDLE_CLI_MODEL_DEVICE="cuda" python3 examples/qwen3_local_inference.py
"""

import os
import sys
import time


def main():
    # 模型配置（全部可通过环境变量覆盖）
    model_id = os.environ.get("CANDLE_CLI_MODEL_ID", "Qwen/Qwen2-0.5B-Instruct")
    device = os.environ.get("CANDLE_CLI_MODEL_DEVICE", "cuda" if _cuda_ok() else "cpu")
    verbose = os.environ.get("CANDLE_CLI_VERBOSE", "0") in ("1", "true")
    max_new_tokens = int(os.environ.get("CANDLE_CLI_MAX_NEW_TOKENS", "512"))
    temperature = float(os.environ.get("CANDLE_CLI_TEMPERATURE", "0.7"))

    if verbose:
        print(f"[example] model_id={model_id}")
        print(f"[example] device={device}")
        print(f"[example] max_new_tokens={max_new_tokens}")
        print(f"[example] temperature={temperature}")

    from transformers import AutoModelForCausalLM, AutoTokenizer

    # 1) 加载 tokenizer
    if verbose:
        print("[example] loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id

    # 2) 加载模型
    if verbose:
        print("[example] loading model...")
        t0 = time.time()

    model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)
    if device != "cpu":
        model = model.to(device)

    if verbose:
        elapsed = time.time() - t0
        params = sum(p.numel() for p in model.parameters())
        print(f"[example] model loaded in {elapsed:.1f}s, {params / 1e9:.2f}B params")
        _print_gpu_memory()

    # 3) 对话
    messages = [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "请用一句话介绍你自己。"},
    ]

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    if verbose:
        print(f"[example] prompt: {text[:200]}...")

    inputs = tokenizer(text, return_tensors="pt").to(device)

    if verbose:
        print(f"[example] input tokens: {inputs['input_ids'].shape[1]}")
        print(f"[example] generating (max_new_tokens={max_new_tokens})...")
        t0 = time.time()

    import torch

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=True,
            pad_token_id=tokenizer.pad_token_id,
        )

    response = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1] :],
        skip_special_tokens=True,
    )

    if verbose:
        gen_time = time.time() - t0
        out_tokens = outputs.shape[1] - inputs["input_ids"].shape[1]
        print(f"[example] output tokens: {out_tokens}")
        print(f"[example] generation time: {gen_time:.1f}s ({out_tokens / gen_time:.1f} tok/s)")
        _print_gpu_memory()

    print()
    print("模型回复:")
    print(response)


def _cuda_ok() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _print_gpu_memory():
    import torch
    if torch.cuda.is_available():
        a = torch.cuda.memory_allocated() / (1024**3)
        r = torch.cuda.memory_reserved() / (1024**3)
        print(f"[example] GPU memory: {a:.2f} GiB allocated, {r:.2f} GiB reserved")


if __name__ == "__main__":
    main()
