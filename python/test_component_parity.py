import json
from types import SimpleNamespace

import pytest

from migration.component_parity import (
    CASE_DEFINITIONS,
    capture_framework,
    evaluate_benchmark,
    load_manifest,
)
from migration.schema import ExecutionMode, Framework, SchemaError
from migration.trace_capture import TraceRecorder


class FakeTensor:
    def __init__(self, value, dtype="float32"):
        self.value = value
        self.dtype = dtype
        self.shape = self._shape(value)

    @classmethod
    def _shape(cls, value):
        if not isinstance(value, list):
            return ()
        return (len(value), *cls._shape(value[0])) if value else (0,)

    def tolist(self):
        return self.value


def fake_module(version, *, mindspore=False):
    module = SimpleNamespace(
        __version__=version,
        float32="float32",
        tensor=lambda value, dtype=None, requires_grad=False: FakeTensor(value),
        Tensor=lambda value, dtype=None: FakeTensor(value),
    )
    if mindspore:
        module.PYNATIVE_MODE = 1
        module.set_context = lambda **kwargs: None
    return module


def write_case(root, framework, case):
    path = root / framework.value / f"{case.case_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    version = "2.6.0+cu124" if framework == Framework.PYTORCH else "2.9.0"
    mode = ExecutionMode.EAGER if framework == Framework.PYTORCH else ExecutionMode.PYNATIVE
    with TraceRecorder(
        path,
        framework=framework,
        framework_version=version,
        execution_mode=mode,
        run_id=f"runtime-components-v1:{case.case_id}",
    ) as recorder:
        for index, operation in enumerate(case.operations):
            api = operation.source_api if framework == Framework.PYTORCH else operation.target_api
            metadata = {
                "semantic_role": operation.semantic_role,
                "case_split": case.split,
                "fault_injection": case.fault_injection,
            }
            if (
                case.case_id == "missing-operator-injected"
                and framework == Framework.MINDSPORE
            ):
                with pytest.raises(NotImplementedError):
                    recorder.call(
                        api,
                        lambda: (_ for _ in ()).throw(NotImplementedError("missing")),
                        trace_metadata=metadata,
                    )
                break
            if case.case_id == "dtype-bool-regression" and framework == Framework.MINDSPORE:
                output = FakeTensor([True, False], "bool")
            elif (
                case.case_id == "batchnorm-default-mode"
                and framework == Framework.MINDSPORE
            ):
                output = FakeTensor([2.0, 4.0])
            else:
                output = FakeTensor([1.0, 3.0])
            recorder.call(api, lambda result=output: result, trace_metadata=metadata)


def test_default_component_manifest_is_frozen_and_split():
    manifest = load_manifest()

    assert manifest.benchmark_version == "runtime-components-v1"
    assert {case.case_id for case in manifest.cases} == set(CASE_DEFINITIONS)
    assert sum(case.split == "development" for case in manifest.cases) == 4
    assert sum(case.split == "heldout" for case in manifest.cases) == 3
    assert sum(not case.expected_equivalent for case in manifest.cases) == 3


def test_component_manifest_rejects_operation_drift(tmp_path):
    path = __import__(
        "migration.component_parity", fromlist=["DEFAULT_MANIFEST"]
    ).DEFAULT_MANIFEST
    document = json.loads(path.read_text(encoding="utf-8"))
    document["cases"][0]["operations"][0]["target_api"] = "mindspore.ops.matmul"
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SchemaError, match="does not match built-in case"):
        load_manifest(changed)


def test_synthetic_component_report_validates_parity_and_top1_localization(tmp_path):
    manifest = load_manifest()
    for case in manifest.cases:
        write_case(tmp_path, Framework.PYTORCH, case)
        write_case(tmp_path, Framework.MINDSPORE, case)

    report = evaluate_benchmark(tmp_path)

    assert report["complete"] is True
    assert report["passed"] is True
    assert report["classification_accuracy"] == 1.0
    assert report["first_divergence_top1_accuracy"] == 1.0
    assert report["equivalent_component_parity_rate"] == 1.0
    assert report["gradient_parity_rate"] == 1.0
    assert report["splits"]["development"]["passed_case_rate"] == 1.0
    assert report["splits"]["heldout"]["passed_case_rate"] == 1.0
    assert report["first_divergence_categories"] == {
        "dtype_mismatch": 1,
        "missing_operator": 1,
        "value_mismatch": 1,
    }


def test_component_capture_accepts_frozen_expected_target_error(tmp_path, monkeypatch):
    modules = {
        "torch": fake_module("2.6.0+cu124"),
        "mindspore": fake_module("2.9.0", mindspore=True),
    }
    monkeypatch.setattr(
        "migration.component_parity.importlib.import_module", lambda name: modules[name]
    )

    def fake_run(case, backend, recorder):
        for operation_index in range(len(case.operations)):
            if (
                case.case_id == "missing-operator-injected"
                and backend.framework == Framework.MINDSPORE
            ):
                backend.record(
                    recorder,
                    case,
                    operation_index,
                    lambda: (_ for _ in ()).throw(NotImplementedError("missing")),
                )
            backend.record(
                recorder,
                case,
                operation_index,
                lambda: FakeTensor([1.0, 3.0]),
            )

    monkeypatch.setattr("migration.component_parity._run_case", fake_run)

    source = capture_framework("pytorch", tmp_path / "pytorch")
    target = capture_framework("mindspore", tmp_path / "mindspore")

    assert source["status"] == target["status"] == "captured"
    assert source["captured_case_count"] == target["captured_case_count"] == 7
    expected_error = next(
        item for item in target["captured"] if item["id"] == "missing-operator-injected"
    )
    assert expected_error["expected_error"] is True


def test_component_evaluation_marks_missing_capture_incomplete(tmp_path):
    manifest = load_manifest()
    for case in manifest.cases:
        write_case(tmp_path, Framework.PYTORCH, case)

    report = evaluate_benchmark(tmp_path)

    assert report["complete"] is False
    assert report["passed"] is False
    assert report["evaluated_case_count"] == 0
    assert report["target_framework_versions"] == []
