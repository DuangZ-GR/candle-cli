import json
from types import SimpleNamespace

import pytest

from migration.runtime_parity import (
    CASE_OPERATIONS,
    capture_framework,
    evaluate_benchmark,
    load_manifest,
)
from migration.schema import SchemaError


class FakeTensor:
    dtype = "float32"

    def __init__(self, value):
        self.value = value
        self.shape = self._shape(value)

    @classmethod
    def _shape(cls, value):
        if not isinstance(value, list):
            return ()
        return (len(value), *cls._shape(value[0])) if value else (0,)

    def tolist(self):
        return self.value


def flatten_values(value):
    if isinstance(value, list):
        return [item for child in value for item in flatten_values(child)]
    return [value]


def fake_functions():
    def add(left, right):
        def combine(a, b):
            return [combine(x, y) for x, y in zip(a, b)] if isinstance(a, list) else a + b

        return FakeTensor(combine(left.value, right.value))

    def total(value):
        return FakeTensor(sum(flatten_values(value.value)))

    def reshape(value, shape):
        flat = flatten_values(value.value)
        if len(shape) == 2:
            width = shape[1]
            return FakeTensor([flat[index : index + width] for index in range(0, len(flat), width)])
        raise ValueError("unsupported fake shape")

    def unsqueeze(value, dimension):
        if dimension != 0:
            raise ValueError("unsupported fake dimension")
        return FakeTensor([value.value])

    def matmul(left, right):
        columns = list(zip(*right.value))
        return FakeTensor(
            [[sum(a * b for a, b in zip(row, column)) for column in columns] for row in left.value]
        )

    def mean(value):
        flat = flatten_values(value.value)
        return FakeTensor(sum(flat) / len(flat))

    def relu(value):
        def activate(item):
            return [activate(child) for child in item] if isinstance(item, list) else max(0, item)

        return FakeTensor(activate(value.value))

    def cat(values, dimension):
        if dimension != 0:
            raise ValueError("unsupported fake dimension")
        return FakeTensor([row for value in values for row in value.value])

    def flatten(value):
        return FakeTensor(flatten_values(value.value))

    return {
        "add": add,
        "sum": total,
        "reshape": reshape,
        "unsqueeze": unsqueeze,
        "matmul": matmul,
        "mean": mean,
        "relu": relu,
        "cat": cat,
        "flatten": flatten,
    }


def fake_module(version, mindspore=False):
    functions = fake_functions()
    functional = SimpleNamespace(relu=functions["relu"])
    nn = SimpleNamespace(functional=functional)
    module = SimpleNamespace(
        __version__=version,
        float32="float32",
        tensor=lambda value, dtype=None: FakeTensor(value),
        Tensor=lambda value, dtype=None: FakeTensor(value),
        nn=nn,
        **functions,
    )
    if mindspore:
        module.mint = SimpleNamespace(nn=nn, **functions)
        module.PYNATIVE_MODE = 1
        module.set_context = lambda **kwargs: None
    return module


def test_default_runtime_manifest_is_complete_and_versioned():
    manifest = load_manifest()

    assert manifest.benchmark_version == "runtime-parity-v1"
    assert {case.case_id for case in manifest.cases} == set(CASE_OPERATIONS)
    assert manifest.source_version_prefix == "2.1"
    assert manifest.target_version_prefix == "2.9"


def test_manifest_rejects_case_drift(tmp_path):
    document = json.loads(
        __import__("migration.runtime_parity", fromlist=["DEFAULT_MANIFEST"])
        .DEFAULT_MANIFEST.read_text(encoding="utf-8")
    )
    document["cases"][0]["operations"] = ["sum", "add"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SchemaError, match="does not match built-in case"):
        load_manifest(path)


def test_capture_reports_unavailable_dependency_without_writing_traces(tmp_path, monkeypatch):
    def unavailable(_name):
        raise ImportError("not installed")

    monkeypatch.setattr("migration.runtime_parity.importlib.import_module", unavailable)

    report = capture_framework("mindspore", tmp_path)

    assert report["status"] == "unavailable"
    assert report["captured_case_count"] == 0
    assert len(report["failures"]) == len(CASE_OPERATIONS)
    assert not list(tmp_path.glob("*.jsonl"))


def test_version_prefix_does_not_confuse_2_13_with_2_1(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "migration.runtime_parity.importlib.import_module",
        lambda _name: fake_module("2.13.0+cpu"),
    )

    report = capture_framework("pytorch", tmp_path)

    assert report["status"] == "version_mismatch"
    assert report["version_compatible"] is False
    assert not list(tmp_path.glob("*.jsonl"))


def test_fake_cross_framework_captures_evaluate_as_complete_parity(tmp_path, monkeypatch):
    modules = {
        "torch": fake_module("2.1.2+cpu"),
        "mindspore": fake_module("2.9.0", mindspore=True),
    }
    monkeypatch.setattr(
        "migration.runtime_parity.importlib.import_module", lambda name: modules[name]
    )

    source = capture_framework("pytorch", tmp_path / "pytorch")
    target = capture_framework("mindspore", tmp_path / "mindspore")
    report = evaluate_benchmark(tmp_path)

    assert source["status"] == target["status"] == "captured"
    assert report["complete"] is True
    assert report["passed"] is True
    assert report["runtime_parity_rate"] == 1.0
    assert report["classification_accuracy"] == 1.0
    assert report["version_prefixes_match"] is True


def test_evaluation_marks_missing_target_capture_as_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "migration.runtime_parity.importlib.import_module",
        lambda _name: fake_module("2.1.0"),
    )
    capture_framework("pytorch", tmp_path / "pytorch")

    report = evaluate_benchmark(tmp_path)

    assert report["complete"] is False
    assert report["passed"] is False
    assert report["evaluated_case_count"] == 0
    assert report["runtime_parity_rate"] is None
    assert report["source_framework_versions"] == ["2.1.0"]
    assert report["target_framework_versions"] == []


def test_evaluation_never_passes_incompatible_framework_versions(tmp_path, monkeypatch):
    modules = {
        "torch": fake_module("2.13.0+cpu"),
        "mindspore": fake_module("3.0.0", mindspore=True),
    }
    monkeypatch.setattr(
        "migration.runtime_parity.importlib.import_module", lambda name: modules[name]
    )
    capture_framework(
        "pytorch", tmp_path / "pytorch", allow_version_mismatch=True
    )
    capture_framework(
        "mindspore", tmp_path / "mindspore", allow_version_mismatch=True
    )

    report = evaluate_benchmark(tmp_path)

    assert report["complete"] is True
    assert report["runtime_parity_rate"] == 1.0
    assert report["classification_accuracy"] == 1.0
    assert report["version_prefixes_match"] is False
    assert report["passed"] is False
