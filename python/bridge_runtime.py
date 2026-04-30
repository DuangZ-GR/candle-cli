import json
import sys
import time
import traceback

from bridge_prompt import build_chat_messages, extract_latest_user_text
from model_config import ModelConfig


class BridgeRuntime:
    def __init__(self, config: ModelConfig | None = None):
        self._initialized = False
        self._config = config or ModelConfig()
        self._model = None
        self._tokenizer = None
        self._device = None

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

    # ── model loading ────────────────────────────────────────────────────

    def _ensure_initialized(self):
        if not self._initialized:
            self._load_model()
            self._initialized = True

    def _load_model(self):
        self._log("=" * 60)
        self._log("bridge runtime initializing")
        self._log(f"  config: model_id={self._config.model_id}")
        self._log(f"  config: device={self._config.device}")
        self._log(f"  config: local_files_only={self._config.local_files_only}")
        self._log(f"  config: max_new_tokens={self._config.max_new_tokens}")
        self._log(f"  config: temperature={self._config.temperature}")
        self._log(f"  config: top_p={self._config.top_p}")

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

        # model info
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
            json.dumps({"ok": True, "warning": f"bridge runtime fallback: {reason}"}),
            file=sys.stderr,
            flush=True,
        )
        self._model = None
        self._tokenizer = None
        self._device = None
        self._log(f"  FALLBACK: {reason}")

    # ── health ───────────────────────────────────────────────────────────

    def health(self) -> dict:
        return {"message": "bridge worker ok"}

    # ── generation ───────────────────────────────────────────────────────

    def generate_turn(self, request: dict) -> dict:
        self._ensure_initialized()

        # fallback path
        if self._model is None or self._tokenizer is None:
            user_text = extract_latest_user_text(request)
            self._log(f"generate_turn: fallback mode, user_text_len={len(user_text)}")
            return {
                "result": {
                    "final_text": f"generated: {user_text}",
                    "tool_calls": [],
                }
            }

        messages_json = request.get("messages_json", "[]")
        chat_messages = build_chat_messages(messages_json)
        if not chat_messages:
            return {
                "result": {
                    "final_text": "",
                    "tool_calls": [],
                }
            }

        try:
            import torch

            self._log(f"generate_turn: {len(chat_messages)} chat messages")

            # tokenize
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

            # generate
            self._log(f"  generating (max_new_tokens={self._config.max_new_tokens})...")
            t0 = time.time()
            with torch.no_grad():
                outputs = self._model.generate(
                    inputs,
                    max_new_tokens=self._config.max_new_tokens,
                    temperature=self._config.temperature,
                    top_p=self._config.top_p,
                    do_sample=True,
                    pad_token_id=self._tokenizer.pad_token_id,
                )
            gen_time = time.time() - t0
            output_tokens = outputs.shape[1] - input_tokens
            self._log(f"  output tokens: {output_tokens}")
            self._log(f"  generation time: {gen_time:.2f}s ({output_tokens / gen_time:.1f} tok/s)")
            self._log(f"  {self._gpu_memory_info()}")

            # decode
            response_text = self._tokenizer.decode(
                outputs[0][input_tokens:],
                skip_special_tokens=True,
            )

            self._log(f"  response length: {len(response_text)} chars")
            return {
                "result": {
                    "final_text": response_text.strip(),
                    "tool_calls": [],
                }
            }
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self._log(f"  ERROR during generation, falling back to stub")
            return {
                "result": {
                    "final_text": f"generated: {extract_latest_user_text(request)}",
                    "tool_calls": [],
                }
            }
