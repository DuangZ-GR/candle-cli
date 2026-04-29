import json
import os

DEFAULT_MODEL_ID = "Qwen/Qwen2-0.5B-Instruct"
DEFAULT_MAX_NEW_TOKENS = 512
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9


class ModelConfig:
    def __init__(self, config_path: str | None = None):
        self.model_id: str = DEFAULT_MODEL_ID
        self.device: str = "cuda" if _cuda_available() else "cpu"
        self.local_files_only: bool = True
        self.max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
        self.temperature: float = DEFAULT_TEMPERATURE
        self.top_p: float = DEFAULT_TOP_P

        if config_path:
            self._load_from_file(config_path)
        elif os.environ.get("CANDLE_CLI_MODEL_CONFIG"):
            self._load_from_file(os.environ["CANDLE_CLI_MODEL_CONFIG"])

        self._apply_env_overrides()

    def _load_from_file(self, path: str):
        with open(path) as fh:
            data = json.load(fh)
        model = data.get("model", {})
        generation = data.get("generation", {})
        if "model_id" in model:
            self.model_id = model["model_id"]
        if "device" in model:
            self.device = model["device"]
        if "local_files_only" in model:
            self.local_files_only = model["local_files_only"]
        if "max_new_tokens" in generation:
            self.max_new_tokens = generation["max_new_tokens"]
        if "temperature" in generation:
            self.temperature = generation["temperature"]
        if "top_p" in generation:
            self.top_p = generation["top_p"]

    def _apply_env_overrides(self):
        if os.environ.get("CANDLE_CLI_MODEL_ID"):
            self.model_id = os.environ["CANDLE_CLI_MODEL_ID"]
        if os.environ.get("CANDLE_CLI_MODEL_DEVICE"):
            self.device = os.environ["CANDLE_CLI_MODEL_DEVICE"]


def _cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False

