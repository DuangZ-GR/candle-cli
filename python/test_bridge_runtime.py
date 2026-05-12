import json
import os
import tempfile
from unittest import mock
from urllib.error import HTTPError

import pytest

from python.bridge_prompt import build_chat_messages, extract_latest_user_text
from python.bridge_runtime import BridgeRuntime
from python.model_config import (
    ENV_API_BASE_URL,
    ENV_API_KEY,
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
        ENV_API_BASE_URL,
        ENV_API_KEY,
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
    assert config.api_base_url == ""
    assert config.api_key == ""
    assert config.use_api is False


def test_model_config_from_file_with_api():
    data = {
        "model": {"model_id": "api-model", "device": "cpu"},
        "generation": {"max_new_tokens": 256},
        "api": {"base_url": "http://localhost:8080/v1", "key": "sk-test"},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        json.dump(data, fh)
        path = fh.name
    try:
        config = ModelConfig(config_path=path)
        assert config.api_base_url == "http://localhost:8080/v1"
        assert config.api_key == "sk-test"
        assert config.use_api is True
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


def test_env_api_base_url():
    os.environ[ENV_API_BASE_URL] = "http://localhost:11434/v1"
    config = ModelConfig()
    assert config.api_base_url == "http://localhost:11434/v1"
    assert config.use_api is True


def test_env_api_key():
    os.environ[ENV_API_KEY] = "sk-my-key"
    config = ModelConfig()
    assert config.api_key == "sk-my-key"


def test_env_all_together():
    """All params set purely via env vars, no config file."""
    os.environ[ENV_MODEL_ID] = "env-only-model"
    os.environ[ENV_MODEL_DEVICE] = "cpu"
    os.environ[ENV_LOCAL_FILES_ONLY] = "false"
    os.environ[ENV_MAX_NEW_TOKENS] = "256"
    os.environ[ENV_TEMPERATURE] = "0.5"
    os.environ[ENV_TOP_P] = "0.8"
    os.environ[ENV_VERBOSE] = "1"
    os.environ[ENV_API_BASE_URL] = "http://localhost:8080/v1"
    os.environ[ENV_API_KEY] = "sk-env-key"

    config = ModelConfig()
    assert config.model_id == "env-only-model"
    assert config.device == "cpu"
    assert config.local_files_only is False
    assert config.max_new_tokens == 256
    assert config.temperature == 0.5
    assert config.top_p == 0.8
    assert config.verbose is True
    assert config.api_base_url == "http://localhost:8080/v1"
    assert config.api_key == "sk-env-key"
    assert config.use_api is True


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


def test_build_chat_messages_serializes_tool_blocks_as_text():
    messages_json = json.dumps(
        [
            {"role": "Assistant", "blocks": [{"ToolCall": {"id": "call-1", "name": "read", "input": "{\"file_path\":\"README.md\"}"}}]},
            {"role": "Tool", "blocks": [{"ToolResult": {"tool_call_id": "call-1", "output": "README contents", "is_error": False}}]},
        ]
    )

    chat = build_chat_messages(messages_json)

    assert chat == [
        {
            "role": "assistant",
            "content": '<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>',
        },
        {
            "role": "user",
            "content": "Tool result for call-1:\nREADME contents",
        },
    ]


# ── BridgeRuntime tests (local fallback) ─────────────────────────────────────


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


# ── API mode tests ───────────────────────────────────────────────────────────


def _mock_api_response(content: str) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode("utf-8")
    resp.__enter__.return_value = resp
    return resp


def test_generate_turn_via_api():
    config = ModelConfig()
    config.api_base_url = "http://localhost:8080/v1"
    config.api_key = "sk-test"
    config.model_id = "test-model"
    runtime = BridgeRuntime(config=config)

    with mock.patch(
        "urllib.request.urlopen", return_value=_mock_api_response("API response")
    ) as mock_urlopen:
        result = runtime.generate_turn(
            {
                "messages_json": json.dumps(
                    [{"role": "User", "blocks": [{"Text": {"text": "hello"}}]}]
                )
            }
        )

    assert result["result"]["final_text"] == "API response"
    assert result["result"]["tool_calls"] == []

    # verify the request body
    mock_urlopen.assert_called_once()
    call_args = mock_urlopen.call_args
    req = call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "test-model"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "hello"
    assert body["max_tokens"] == 512


def test_generate_turn_via_api_with_system_prompt():
    config = ModelConfig()
    config.api_base_url = "http://localhost:8080/v1"
    config.api_key = "sk-test"
    config.model_id = "test-model"
    runtime = BridgeRuntime(config=config)

    with mock.patch(
        "urllib.request.urlopen", return_value=_mock_api_response("ok")
    ):
        result = runtime.generate_turn(
            {
                "system_prompt": "You are helpful.",
                "messages_json": json.dumps(
                    [{"role": "User", "blocks": [{"Text": {"text": "hi"}}]}]
                ),
            }
        )

    assert result["result"]["final_text"] == "ok"


def test_generate_turn_via_api_http_error_falls_back():
    config = ModelConfig()
    config.api_base_url = "http://localhost:8080/v1"
    config.api_key = "sk-test"
    runtime = BridgeRuntime(config=config)

    with mock.patch(
        "urllib.request.urlopen",
        side_effect=HTTPError(
            url="http://localhost:8080/v1/chat/completions",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        ),
    ):
        result = runtime.generate_turn(
            {
                "messages_json": json.dumps(
                    [{"role": "User", "blocks": [{"Text": {"text": "hello"}}]}]
                )
            }
        )

    # falls back to stub
    assert result["result"]["final_text"] == "generated: hello"


def test_generate_turn_via_api_empty_messages():
    config = ModelConfig()
    config.api_base_url = "http://localhost:8080/v1"
    config.api_key = "sk-test"
    runtime = BridgeRuntime(config=config)

    result = runtime.generate_turn({"messages_json": "[]"})
    assert result["result"]["final_text"] == ""
    assert result["result"]["tool_calls"] == []
