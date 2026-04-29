import json
import os
import tempfile
from unittest import mock

import pytest

from python.bridge_prompt import build_chat_messages, extract_latest_user_text
from python.bridge_runtime import BridgeRuntime
from python.model_config import ModelConfig


# ── ModelConfig tests ─────────────────────────────────────────────────────────


def test_model_config_defaults():
    config = ModelConfig()
    assert config.max_new_tokens == 512
    assert config.temperature == 0.7
    assert config.top_p == 0.9
    assert config.device in ("cpu", "cuda")


def test_model_config_from_file():
    data = {
        "model": {"model_id": "test-model", "device": "cpu"},
        "generation": {"max_new_tokens": 256, "temperature": 0.5, "top_p": 0.8},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        json.dump(data, fh)
        path = fh.name
    try:
        os.environ["CANDLE_CLI_MODEL_CONFIG"] = path
        config = ModelConfig(config_path=path)
        assert config.model_id == "test-model"
        assert config.device == "cpu"
        assert config.max_new_tokens == 256
        assert config.temperature == 0.5
        assert config.top_p == 0.8
    finally:
        os.unlink(path)
        os.environ.pop("CANDLE_CLI_MODEL_CONFIG", None)


def test_model_config_env_override():
    os.environ["CANDLE_CLI_MODEL_ID"] = "env-model"
    os.environ["CANDLE_CLI_MODEL_DEVICE"] = "cpu"
    try:
        config = ModelConfig()
        assert config.model_id == "env-model"
        assert config.device == "cpu"
    finally:
        os.environ.pop("CANDLE_CLI_MODEL_ID", None)
        os.environ.pop("CANDLE_CLI_MODEL_DEVICE", None)


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
            {
                "role": "Assistant",
                "blocks": [{"Text": {"text": "hi there"}}],
            },
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
                    [
                        {
                            "role": "User",
                            "blocks": [{"Text": {"text": "hello"}}],
                        }
                    ]
                )
            }
        )

    assert result["result"]["final_text"] == "mock response"
    assert result["result"]["tool_calls"] == []
