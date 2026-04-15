from importlib import import_module


def test_package_imports():
    module = import_module("candle_cli")
    assert hasattr(module, "__version__")

