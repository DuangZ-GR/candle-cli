import json
import os
import tempfile
from unittest import mock

import pytest

from python.bridge_prompt import build_chat_messages, extract_latest_user_text
from python.bridge_runtime import BridgeRuntime
from python.model_config import (
    ENV_LOCAL_FILES_ONLY,
    ENV_MAX_NEW_TOKENS,
    ENV_MODEL_DEVICE,
    ENV_MODEL_ID,
    ENV_TEMPERATURE,
    ENV_TOP_P,
    ENV_VERBOSE,
    ModelConfig,
)


def _clear_env():
    for key in (
        ENV_MODEL_ID,
        ENV_MODEL_DEVICE,
        ENV_LOCAL_FILES_ONLY,
        ENV_MAX_NEW_TOKENS,
        ENV_TEMPERATURE,
        ENV_TOP_P,
        ENV_VERBOSE,
        "CANDLE_CLI_MODEL_CONFIG",
    ):
        os.environ.pop(key, None)


@pytest.fixture(autouse=True)
def clean_env():
    _clear_env()
    yield
    _clear_env()


# ── ModelConfig tests ─────────────────────────────────────────────────────────


def test_model_config_defaults():
    config = ModelConfig()
    assert config.model_id == "Qwen/Qwen2-0.5B-Instruct"
    assert config.device in ("cpu", "cuda")
    assert config.local_files_only is True
    assert config.max_new_tokens == 512
    assert config.temperature == 0.7
    assert config.top_p == 0.9
    assert config.verbose is False


def test_model_config_from_file():
    data = {
        "model": {
            "model_id": "test-model",
            "device": "cpu",
            "local_files_only": False,
            "verbose": True,
        },
        "generation": {"max_new_tokens": 256, "temperature": 0.5, "top_p": 0.8},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        json.dump(data, fh)
        path = fh.name
    try:
        config = ModelConfig(config_path=path)
        assert config.model_id == "test-model"
        assert config.device == "cpu"
        assert config.local_files_only is False
        assert config.verbose is True
        assert config.max_new_tokens == 256
        assert config.temperature == 0.5
        assert config.top_p == 0.8
    finally:
        os.unlink(path)


# ── env var override tests ────────────────────────────────────────────────────


def test_env_model_id():
    os.environ[ENV_MODEL_ID] = "my-custom-model"
    config = ModelConfig()
    assert config.model_id == "my-custom-model"


def test_env_device():
    os.environ[ENV_MODEL_DEVICE] = "cpu"
    config = ModelConfig()
    assert config.device == "cpu"


def test_env_local_files_only():
    os.environ[ENV_LOCAL_FILES_ONLY] = "false"
    config = ModelConfig()
    assert config.local_files_only is False

    os.environ[ENV_LOCAL_FILES_ONLY] = "0"
    config2 = ModelConfig()
    assert config2.local_files_only is False

    os.environ[ENV_LOCAL_FILES_ONLY] = "true"
    config3 = ModelConfig()
    assert config3.local_files_only is True


def test_env_max_new_tokens():
    os.environ[ENV_MAX_NEW_TOKENS] = "1024"
    config = ModelConfig()
    assert config.max_new_tokens == 1024


def test_env_temperature():
    os.environ[ENV_TEMPERATURE] = "0.3"
    config = ModelConfig()
    assert config.temperature == 0.3


def test_env_top_p():
    os.environ[ENV_TOP_P] = "0.5"
    config = ModelConfig()
    assert config.top_p == 0.5


def test_env_verbose():
    os.environ[ENV_VERBOSE] = "1"
    config = ModelConfig()
    assert config.verbose is True

    os.environ[ENV_VERBOSE] = "true"
    config2 = ModelConfig()
    assert config2.verbose is True


def test_env_all_together():
    """All params set purely via env vars, no config file."""
    os.environ[ENV_MODEL_ID] = "env-only-model"
    os.environ[ENV_MODEL_DEVICE] = "cpu"
    os.environ[ENV_LOCAL_FILES_ONLY] = "false"
    os.environ[ENV_MAX_NEW_TOKENS] = "256"
    os.environ[ENV_TEMPERATURE] = "0.5"
    os.environ[ENV_TOP_P] = "0.8"
    os.environ[ENV_VERBOSE] = "1"

    config = ModelConfig()
    assert config.model_id == "env-only-model"
    assert config.device == "cpu"
    assert config.local_files_only is False
    assert config.max_new_tokens == 256
    assert config.temperature == 0.5
    assert config.top_p == 0.8
    assert config.verbose is True


def test_env_overrides_file():
    """Env vars take priority over config file values."""
    data = {
        "model": {"model_id": "file-model", "device": "cuda"},
        "generation": {"max_new_tokens": 100, "temperature": 1.0},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        json.dump(data, fh)
        path = fh.name
    try:
        os.environ[ENV_MODEL_ID] = "env-model"
        os.environ[ENV_MODEL_DEVICE] = "cpu"
        config = ModelConfig(config_path=path)
        # env var wins over file
        assert config.model_id == "env-model"
        assert config.device == "cpu"
        # file value kept when no env var set
        assert config.max_new_tokens == 100
        assert config.temperature == 1.0
    finally:
        os.unlink(path)


# ── bridge_prompt tests ──────────────────────────────────────────────────────


def test_extract_latest_user_text_empty():
    assert extract_latest_user_text({"messages_json": "[]"}) == ""


def test_extract_latest_user_text_single():
    request = {
        "messages_json": json.dumps(
            [{"role": "User", "blocks": [{"Text": {"text": "hello"}}]}]
        )
    }
    assert extract_latest_user_text(request) == "hello"


def test_build_chat_messages():
    messages_json = json.dumps(
        [
            {"role": "User", "blocks": [{"Text": {"text": "hello"}}]},
            {"role": "Assistant", "blocks": [{"Text": {"text": "hi there"}}]},
            {"role": "User", "blocks": [{"Text": {"text": "how are you"}}]},
        ]
    )
    chat = build_chat_messages(messages_json)
    assert chat == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
        {"role": "user", "content": "how are you"},
    ]


def test_build_chat_messages_includes_system():
    messages_json = json.dumps(
        [
            {"role": "System", "blocks": []},
            {"role": "User", "blocks": [{"Text": {"text": "ok"}}]},
        ]
    )
    chat = build_chat_messages(messages_json)
    assert chat == [
        {"role": "system", "content": ""},
        {"role": "user", "content": "ok"},
    ]


def test_build_chat_messages_skips_tool_calls():
    messages_json = json.dumps(
        [
            {
                "role": "Assistant",
                "blocks": [
                    {"Text": {"text": "let me check"}},
                    {
                        "ToolCall": {
                            "id": "t1",
                            "name": "read",
                            "input": "{}",
                        }
                    },
                ],
            },
            {
                "role": "Tool",
                "blocks": [
                    {
                        "ToolResult": {
                            "tool_call_id": "t1",
                            "output": "data",
                            "is_error": False,
                        }
                    }
                ],
            },
        ]
    )
    chat = build_chat_messages(messages_json)
    assert chat == [
        {"role": "assistant", "content": "let me check"},
        {"role": "tool", "content": ""},
    ]


# ── BridgeRuntime tests ──────────────────────────────────────────────────────


def test_bridge_runtime_initializes_lazily():
    runtime = BridgeRuntime()
    assert runtime._initialized is False


def test_health():
    runtime = BridgeRuntime()
    assert runtime.health()["message"] == "bridge worker ok"


def test_verbose_config_propagates():
    config = ModelConfig()
    config.verbose = True
    runtime = BridgeRuntime(config=config)
    assert runtime._verbose is True


def test_generate_turn_falls_back_when_no_model():
    config = ModelConfig()
    config.device = "cpu"
    runtime = BridgeRuntime(config=config)

    with mock.patch(
        "transformers.AutoTokenizer.from_pretrained",
        side_effect=OSError("model not found"),
    ):
        result = runtime.generate_turn(
            {
                "messages_json": json.dumps(
                    [{"role": "User", "blocks": [{"Text": {"text": "hello world"}}]}]
                )
            }
        )

    assert result["result"]["final_text"] == "generated: hello world"
    assert result["result"]["tool_calls"] == []


def test_generate_turn_empty_messages():
    config = ModelConfig()
    config.device = "cpu"
    runtime = BridgeRuntime(config=config)

    with mock.patch(
        "transformers.AutoTokenizer.from_pretrained",
        side_effect=OSError("model not found"),
    ):
        result = runtime.generate_turn({"messages_json": "[]"})

    assert "result" in result
    assert result["result"]["final_text"] == "generated: "


def test_fallback_to_stub_clears_model():
    config = ModelConfig()
    config.device = "cpu"
    runtime = BridgeRuntime(config=config)

    with mock.patch(
        "transformers.AutoTokenizer.from_pretrained",
        side_effect=OSError("model not found"),
    ):
        runtime.generate_turn({"messages_json": "[]"})

    assert runtime._model is None
    assert runtime._tokenizer is None


# ── mock model helpers ───────────────────────────────────────────────────────


class _MockTokenizer:
    def __init__(self):
        self.pad_token_id = 0
        self.eos_token_id = 0

    def apply_chat_template(self, messages, **kwargs):
        return [1, 2, 3]

    def decode(self, token_ids, **kwargs):
        return "mock response"


class _MockModel:
    def generate(self, inputs, **kwargs):
        import torch
        return torch.tensor([[1, 2, 3, 4, 5, 6]])

    def to(self, device):
        return self

    def parameters(self):
        return []


def _mock_from_pretrained(*args, **kwargs):
    return _MockModel()


def _mock_tokenizer_from_pretrained(*args, **kwargs):
    return _MockTokenizer()


def test_generate_turn_with_mocked_model():
    config = ModelConfig()
    config.model_id = "mock/model"
    config.device = "cpu"
    runtime = BridgeRuntime(config=config)

    with mock.patch(
        "transformers.AutoModelForCausalLM.from_pretrained",
        side_effect=_mock_from_pretrained,
    ), mock.patch(
        "transformers.AutoTokenizer.from_pretrained",
        side_effect=_mock_tokenizer_from_pretrained,
    ):
        result = runtime.generate_turn(
            {
                "messages_json": json.dumps(
                    [{"role": "User", "blocks": [{"Text": {"text": "hello"}}]}]
                )
            }
        )

    assert result["result"]["final_text"] == "mock response"
    assert result["result"]["tool_calls"] == []
