from python.bridge_runtime import BridgeRuntime


def test_bridge_runtime_initializes_lazily():
    runtime = BridgeRuntime()
    assert runtime._initialized is False
    runtime.generate_turn({"messages_json": "[]"})
    assert runtime._initialized is True
