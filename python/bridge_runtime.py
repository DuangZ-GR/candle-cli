import json
import sys
import time
import traceback
import urllib.error
import urllib.request

from bridge_prompt import build_chat_messages, extract_latest_user_text
from model_config import ModelConfig


class BridgeRuntime:
    def __init__(self, config: ModelConfig | None = None):
        self._initialized = False
        self._config = config or ModelConfig()
        self._model = None
        self._tokenizer = None
        self._device = None
        self._fallback_reason = None

    # ── verbose logging ──────────────────────────────────────────────────

    @property
    def _verbose(self) -> bool:
        return self._config.verbose

    def _log(self, msg: str):
        """Output diagnostic info to stderr (does not touch stdout JSON protocol)."""
        if self._verbose:
            print(f"[candle-cli] {msg}", file=sys.stderr, flush=True)

    def _gpu_memory_info(self) -> str:
        try:
            import torch
            if torch.cuda.is_available():
                allocated = torch.cuda.memory_allocated() / (1024**3)
                reserved = torch.cuda.memory_reserved() / (1024**3)
                return f"GPU memory: {allocated:.2f} GiB allocated, {reserved:.2f} GiB reserved"
            return "GPU memory: CUDA not available"
        except Exception:
            return "GPU memory: unknown"

    # ── initialization ───────────────────────────────────────────────────

    def _ensure_initialized(self):
        if not self._initialized:
            if self._config.use_api:
                self._log("API mode active, skipping local model load")
                self._log(f"  api_base_url: {self._config.api_base_url}")
            else:
                self._load_model()
            self._initialized = True

    # ── local model loading ──────────────────────────────────────────────

    def _load_model(self):
        self._log("=" * 60)
        self._log("bridge runtime initializing (local model mode)")
        self._log(f"  model_id={self._config.model_id}")
        self._log(f"  device={self._config.device}")
        self._log(f"  local_files_only={self._config.local_files_only}")
        self._log(f"  max_new_tokens={self._config.max_new_tokens}")
        self._log(f"  temperature={self._config.temperature}")
        self._log(f"  top_p={self._config.top_p}")

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self._log("  transformers: import ok")
        except ImportError:
            self._fallback_to_stub("transformers not installed – run: pip install transformers")
            return

        # load tokenizer
        self._log(f"  loading tokenizer: {self._config.model_id}")
        t0 = time.time()
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._config.model_id,
                trust_remote_code=True,
                local_files_only=self._config.local_files_only,
            )
        except Exception as exc:
            self._fallback_to_stub(f"failed to load tokenizer: {exc}")
            return
        self._log(f"  tokenizer loaded in {time.time() - t0:.1f}s")

        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token_id = self._tokenizer.eos_token_id
            self._log(f"  pad_token_id set to eos_token_id={self._tokenizer.eos_token_id}")

        # resolve device
        resolved_device = self._resolve_device()
        self._log(f"  resolved device: {resolved_device}")
        self._log(f"  {self._gpu_memory_info()} (before model load)")

        # load model
        self._log(f"  loading model: {self._config.model_id}")
        t0 = time.time()
        try:
            self._model = AutoModelForCausalLM.from_pretrained(
                self._config.model_id,
                trust_remote_code=True,
                local_files_only=self._config.local_files_only,
            )
        except Exception as exc:
            self._fallback_to_stub(f"failed to load model: {exc}")
            return

        if resolved_device != "cpu":
            self._model = self._model.to(resolved_device)
            self._device = resolved_device
            self._log(f"  model moved to {resolved_device}")
        else:
            self._device = "cpu"

        self._log(f"  model loaded in {time.time() - t0:.1f}s")
        self._log(f"  {self._gpu_memory_info()} (after model load)")

        try:
            param_count = sum(p.numel() for p in self._model.parameters())
            self._log(f"  model parameters: {param_count / 1e9:.2f}B")
        except Exception:
            pass

        self._log("bridge runtime ready")
        self._log("=" * 60)

    def _resolve_device(self) -> str:
        device = self._config.device
        if device == "auto":
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                return "cpu"
        return device

    def _fallback_to_stub(self, reason: str):
        print(
            json.dumps({"ok": False, "warning": f"bridge runtime unavailable: {reason}"}),
            file=sys.stderr,
            flush=True,
        )
        self._model = None
        self._tokenizer = None
        self._device = None
        self._fallback_reason = reason
        self._log(f"  UNAVAILABLE: {reason}")

    def _stub_or_raise(self, request: dict, reason: str) -> dict:
        if not self._config.allow_stub_fallback:
            raise RuntimeError(
                f"local model runtime unavailable: {reason}. "
                "Configure an API backend, install/load the local model, or set "
                "CANDLE_CLI_ALLOW_STUB_FALLBACK=1 only for demos and tests"
            )

        user_text = extract_latest_user_text(request)
        self._log(f"generate_turn: explicit stub mode, user_text_len={len(user_text)}")
        return {
            "result": {
                "final_text": f"generated: {user_text}",
                "tool_calls": [],
            }
        }

    # ── health ───────────────────────────────────────────────────────────

    def health(self) -> dict:
        return {"message": "bridge worker ok"}

    # ── API-based generation ─────────────────────────────────────────────

    @staticmethod
    def _normalize_usage(usage: object) -> dict | None:
        if not isinstance(usage, dict):
            return None

        def non_negative_int(value: object) -> int | None:
            return (
                value
                if isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
                else None
            )

        prompt_tokens = non_negative_int(usage.get("prompt_tokens"))
        completion_tokens = non_negative_int(usage.get("completion_tokens"))
        total_tokens = non_negative_int(usage.get("total_tokens"))
        if prompt_tokens is None or completion_tokens is None or total_tokens is None:
            return None
        if total_tokens != prompt_tokens + completion_tokens:
            return None

        cached_prompt_tokens = non_negative_int(usage.get("prompt_cache_hit_tokens"))
        cache_miss_prompt_tokens = non_negative_int(
            usage.get("prompt_cache_miss_tokens")
        )
        prompt_details = usage.get("prompt_tokens_details")
        if cached_prompt_tokens is None and isinstance(prompt_details, dict):
            cached_prompt_tokens = non_negative_int(prompt_details.get("cached_tokens"))
        if cached_prompt_tokens is not None and cached_prompt_tokens > prompt_tokens:
            cached_prompt_tokens = None
            cache_miss_prompt_tokens = None
        if (
            cached_prompt_tokens is not None
            and cache_miss_prompt_tokens is not None
            and cached_prompt_tokens + cache_miss_prompt_tokens != prompt_tokens
        ):
            cached_prompt_tokens = None
            cache_miss_prompt_tokens = None

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cached_prompt_tokens": cached_prompt_tokens,
            "cache_miss_prompt_tokens": cache_miss_prompt_tokens,
        }

    @staticmethod
    def _result(final_text: str, usage: dict | None = None) -> dict:
        return {
            "result": {
                "final_text": final_text.strip(),
                "tool_calls": [],
                "usage": usage,
            }
        }

    def _generate_via_api(self, request: dict) -> dict:
        messages_json = request.get("messages_json", "[]")
        chat_messages = build_chat_messages(messages_json)
        if not chat_messages:
            return self._result("")

        # add system prompt if present
        api_messages: list[dict] = []
        system_prompt = request.get("system_prompt", "")
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(chat_messages)

        body = {
            "model": self._config.model_id,
            "messages": api_messages,
            "max_tokens": self._config.max_new_tokens,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "thinking": {"type": "disabled"},
            "stream": True,
        }
        if self._config.include_usage:
            body["stream_options"] = {"include_usage": True}

        url = self._config.api_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._config.api_key}",
        }

        self._log(f"API call: POST {url}")
        self._log(f"  messages: {len(api_messages)} (system={bool(system_prompt)})")
        self._log(f"  model: {self._config.model_id}")
        self._log(f"  max_tokens: {self._config.max_new_tokens}")

        max_retries = 3
        raw = None
        response_usage = None
        for attempt in range(1, max_retries + 1):
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(body).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    content_chunks: list[str] = []
                    for line_bytes in resp:
                        line = line_bytes.decode("utf-8", errors="ignore").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            normalized_usage = self._normalize_usage(chunk.get("usage"))
                            if normalized_usage is not None:
                                response_usage = normalized_usage
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                content_chunks.append(token)
                                print(token, end="", file=sys.stderr, flush=True)
                        except json.JSONDecodeError:
                            continue
                    raw = None
                    self._log(f"  response in {time.time() - t0:.1f}s")
                    print(file=sys.stderr, flush=True)
                break
            except urllib.error.HTTPError as exc:
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    err_body = "(unable to read error body)"
                self._log(f"  HTTP {exc.code}: {err_body}")
                if exc.code and 400 <= exc.code < 500:
                    # Client errors are deterministic and should be reported
                    # immediately rather than retried or disguised as output.
                    raise RuntimeError(
                        f"API request failed with HTTP {exc.code}: {err_body}"
                    ) from exc
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    self._log(f"  retrying in {wait}s (attempt {attempt}/{max_retries})")
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"API request failed after {max_retries} attempts "
                        f"with HTTP {exc.code}: {err_body}"
                    ) from exc
            except RuntimeError:
                raise
            except Exception as exc:
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    self._log(f"  network error, retrying in {wait}s (attempt {attempt}/{max_retries})")
                    time.sleep(wait)
                else:
                    self._log("  API request failed after all retries")
                    raise RuntimeError(
                        f"API request failed after {max_retries} attempts: {exc}"
                    ) from exc

        try:
            if content_chunks:
                content = "".join(content_chunks)
                self._log(f"  response length: {len(content)} chars")
                return self._result(content, response_usage)
            data = json.loads(raw or "{}")
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                raise KeyError("content missing")
            response_usage = self._normalize_usage(data.get("usage"))
            if response_usage:
                self._log(
                    f"  tokens: prompt={response_usage['prompt_tokens']} completion={response_usage['completion_tokens']} total={response_usage['total_tokens']}"
                )
            self._log(f"  response length: {len(content)} chars")
            return self._result(content, response_usage)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            self._log(f"  failed to parse API response: {exc}")
            raise RuntimeError(f"failed to parse API response: {exc}") from exc

    # ── local model generation ───────────────────────────────────────────

    def _generate_local(self, request: dict) -> dict:
        messages_json = request.get("messages_json", "[]")
        chat_messages = build_chat_messages(messages_json)
        if not chat_messages:
            return {"result": {"final_text": "", "tool_calls": []}}

        try:
            import torch

            self._log(f"generate_turn: {len(chat_messages)} chat messages")

            t0 = time.time()
            inputs = self._tokenizer.apply_chat_template(
                chat_messages,
                return_tensors="pt",
                add_generation_prompt=True,
                tokenize=True,
            )
            if isinstance(inputs, list):
                inputs = torch.tensor([inputs])
            inputs = inputs.to(self._device)
            input_tokens = inputs.shape[1]
            self._log(f"  input tokens: {input_tokens}")
            self._log(f"  tokenization time: {time.time() - t0:.2f}s")

            self._log(f"  generating (max_new_tokens={self._config.max_new_tokens})...")
            t0 = time.perf_counter()
            with torch.no_grad():
                outputs = self._model.generate(
                    inputs,
                    max_new_tokens=self._config.max_new_tokens,
                    temperature=self._config.temperature,
                    top_p=self._config.top_p,
                    do_sample=True,
                    pad_token_id=self._tokenizer.pad_token_id,
                )
            gen_time = max(time.perf_counter() - t0, 1e-9)
            output_tokens = outputs.shape[1] - input_tokens
            self._log(f"  output tokens: {output_tokens}")
            self._log(f"  generation time: {gen_time:.2f}s ({output_tokens / gen_time:.1f} tok/s)")
            self._log(f"  {self._gpu_memory_info()}")

            response_text = self._tokenizer.decode(
                outputs[0][input_tokens:],
                skip_special_tokens=True,
            )

            self._log(f"  response length: {len(response_text)} chars")
            usage = {
                "prompt_tokens": int(input_tokens),
                "completion_tokens": int(output_tokens),
                "total_tokens": int(input_tokens + output_tokens),
                "cached_prompt_tokens": None,
                "cache_miss_prompt_tokens": None,
            }
            return self._result(response_text, usage)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self._log("  ERROR during local generation")
            return self._stub_or_raise(request, f"local generation failed: {exc}")

    # ── main entry ───────────────────────────────────────────────────────

    def generate_turn(self, request: dict) -> dict:
        self._ensure_initialized()

        # API mode
        if self._config.use_api:
            return self._generate_via_api(request)

        # A missing local backend is an error by default. An echo stub remains
        # available only when explicitly enabled for demos and protocol tests.
        if self._model is None or self._tokenizer is None:
            return self._stub_or_raise(
                request, self._fallback_reason or "model or tokenizer was not loaded"
            )

        return self._generate_local(request)
