import json
import sys
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

    def _ensure_initialized(self):
        if not self._initialized:
            self._load_model()
            self._initialized = True

    def _load_model(self):
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            self._fallback_to_stub("transformers not installed – run: pip install transformers")
            return

        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._config.model_id,
                trust_remote_code=True,
                local_files_only=self._config.local_files_only,
            )
        except Exception as exc:
            self._fallback_to_stub(f"failed to load tokenizer: {exc}")
            return

        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token_id = self._tokenizer.eos_token_id

        resolved_device = self._resolve_device()
        try:
            self._model = AutoModelForCausalLM.from_pretrained(
                self._config.model_id,
                trust_remote_code=True,
                local_files_only=self._config.local_files_only,
            )
            if resolved_device != "cpu":
                self._model = self._model.to(resolved_device)
                self._device = resolved_device
            else:
                self._device = "cpu"
        except Exception as exc:
            self._fallback_to_stub(f"failed to load model: {exc}")
            return

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

    def health(self) -> dict:
        return {"message": "bridge worker ok"}

    def generate_turn(self, request: dict) -> dict:
        self._ensure_initialized()

        if self._model is None or self._tokenizer is None:
            user_text = extract_latest_user_text(request)
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

            inputs = self._tokenizer.apply_chat_template(
                chat_messages,
                return_tensors="pt",
                add_generation_prompt=True,
                tokenize=True,
            )
            if isinstance(inputs, list):
                inputs = torch.tensor([inputs])
            inputs = inputs.to(self._device)

            with torch.no_grad():
                outputs = self._model.generate(
                    inputs,
                    max_new_tokens=self._config.max_new_tokens,
                    temperature=self._config.temperature,
                    top_p=self._config.top_p,
                    do_sample=True,
                    pad_token_id=self._tokenizer.pad_token_id,
                )

            response_text = self._tokenizer.decode(
                outputs[0][inputs.shape[1] :],
                skip_special_tokens=True,
            )

            return {
                "result": {
                    "final_text": response_text.strip(),
                    "tool_calls": [],
                }
            }
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return {
                "result": {
                    "final_text": f"generated: {extract_latest_user_text(request)}",
                    "tool_calls": [],
                }
            }
