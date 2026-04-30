import json
import os


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes")


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


# ── env var keys ─────────────────────────────────────────────────────────────

ENV_MODEL_ID = "CANDLE_CLI_MODEL_ID"
ENV_MODEL_DEVICE = "CANDLE_CLI_MODEL_DEVICE"
ENV_LOCAL_FILES_ONLY = "CANDLE_CLI_LOCAL_FILES_ONLY"
ENV_MAX_NEW_TOKENS = "CANDLE_CLI_MAX_NEW_TOKENS"
ENV_TEMPERATURE = "CANDLE_CLI_TEMPERATURE"
ENV_TOP_P = "CANDLE_CLI_TOP_P"
ENV_VERBOSE = "CANDLE_CLI_VERBOSE"
ENV_MODEL_CONFIG = "CANDLE_CLI_MODEL_CONFIG"

# ── defaults ──────────────────────────────────────────────────────────────────

DEFAULT_MODEL_ID = "Qwen/Qwen2-0.5B-Instruct"
DEFAULT_LOCAL_FILES_ONLY = True
DEFAULT_MAX_NEW_TOKENS = 512
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9


class ModelConfig:
    def __init__(self, config_path: str | None = None):
        # load from JSON file first (lowest priority)
        self.model_id: str = DEFAULT_MODEL_ID
        self.device: str = "cuda" if _cuda_available() else "cpu"
        self.local_files_only: bool = DEFAULT_LOCAL_FILES_ONLY
        self.max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
        self.temperature: float = DEFAULT_TEMPERATURE
        self.top_p: float = DEFAULT_TOP_P
        self.verbose: bool = False

        if config_path:
            self._load_from_file(config_path)
        elif os.environ.get(ENV_MODEL_CONFIG):
            self._load_from_file(os.environ[ENV_MODEL_CONFIG])

        # env vars override file values
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
        if "verbose" in model:
            self.verbose = model["verbose"]
        if "max_new_tokens" in generation:
            self.max_new_tokens = generation["max_new_tokens"]
        if "temperature" in generation:
            self.temperature = generation["temperature"]
        if "top_p" in generation:
            self.top_p = generation["top_p"]

    def _apply_env_overrides(self):
        self.model_id = _env_str(ENV_MODEL_ID, self.model_id)
        self.device = _env_str(ENV_MODEL_DEVICE, self.device)
        self.local_files_only = _env_bool(ENV_LOCAL_FILES_ONLY, self.local_files_only)
        self.max_new_tokens = _env_int(ENV_MAX_NEW_TOKENS, self.max_new_tokens)
        self.temperature = _env_float(ENV_TEMPERATURE, self.temperature)
        self.top_p = _env_float(ENV_TOP_P, self.top_p)
        self.verbose = _env_bool(ENV_VERBOSE, self.verbose)


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False
