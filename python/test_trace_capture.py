import json
import math

import pytest

from migration.schema import ExecutionMode, Framework, ValueKind
from migration.trace_capture import TraceRecorder, summarize_value
from migration.trace_compare import load_trace_jsonl


class FakeTensor:
    def __init__(self, values, shape=(2, 2), dtype="torch.float32"):
        self.values = values
        self.shape = shape
        self.dtype = dtype
        self.converted = False

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        self.converted = True
        return self.values


def test_bool_is_not_summarized_as_integer():
    summary = summarize_value(True)
    assert summary.kind == ValueKind.BOOLEAN
    assert summary.dtype == "bool"
    assert summary.numeric is None


def test_scalar_nan_is_json_safe_and_counted():
    summary = summarize_value(float("nan"))
    assert summary.preview == "nan"
    assert summary.numeric.nan_count == 1
    assert summary.numeric.min is None


def test_sequence_children_are_bounded():
    summary = summarize_value([1, 2, 3], max_children=2)
    assert summary.kind == ValueKind.SEQUENCE
    assert len(summary.children) == 2
    assert summary.preview["truncated"] is True


def test_recursive_mapping_is_safe():
    value = {}
    value["self"] = value
    summary = summarize_value(value)
    assert summary.children[0].preview == {"recursive": True}


def test_tensor_dtype_shape_and_statistics_are_normalized():
    tensor = FakeTensor([[1.0, 2.0], [3.0, 4.0]])
    summary = summarize_value(tensor)
    assert summary.kind == ValueKind.TENSOR
    assert summary.dtype == "float32"
    assert summary.shape == [2, 2]
    assert summary.numeric.mean == 2.5
    assert tensor.converted is True


def test_large_tensor_is_not_copied_to_host():
    tensor = FakeTensor([], shape=(1_000_000,), dtype="mindspore.float16")
    summary = summarize_value(tensor, max_tensor_elements=100)
    assert summary.numeric is None
    assert summary.preview["statistics_omitted"] is True
    assert tensor.converted is False


def test_unknown_tensor_dimension_omits_statistics():
    tensor = FakeTensor([], shape=(None, 4), dtype="Float32")
    summary = summarize_value(tensor)
    assert summary.shape == [None, 4]
    assert summary.numeric is None


def test_invalid_capture_limits_are_rejected():
    with pytest.raises(ValueError):
        summarize_value([], max_children=0)
    with pytest.raises(ValueError):
        summarize_value([], max_depth=-1)
    with pytest.raises(ValueError):
        summarize_value([], max_tensor_elements=0)


def test_trace_recorder_writes_valid_output_and_arguments(tmp_path):
    path = tmp_path / "trace.jsonl"
    with TraceRecorder(
        path,
        framework=Framework.PYTORCH,
        framework_version="2.1.0",
        execution_mode=ExecutionMode.EAGER,
        run_id="run-1",
    ) as recorder:
        result = recorder.call("torch.add", lambda left, right=0: left + right, 2, right=3)
    assert result == 5
    record = load_trace_jsonl(path, Framework.PYTORCH)[0]
    assert record.api == "torch.add"
    assert record.arguments[1].name == "right"
    assert record.output.preview == 5
    assert record.metadata["duration_ms"] >= 0


def test_trace_recorder_preserves_exception_and_redacts_secret(tmp_path):
    path = tmp_path / "trace.jsonl"
    with TraceRecorder(
        path,
        framework=Framework.MINDSPORE,
        framework_version="2.9.0",
        execution_mode=ExecutionMode.PYNATIVE,
    ) as recorder:
        with pytest.raises(RuntimeError, match="api_key"):
            recorder.call(
                "mindspore.ops.add",
                lambda: (_ for _ in ()).throw(RuntimeError("api_key=top-secret failed")),
            )
    record = load_trace_jsonl(path, Framework.MINDSPORE)[0]
    assert record.error.message == "api_key=[REDACTED] failed"


def test_trace_location_does_not_leak_absolute_host_path(tmp_path):
    path = tmp_path / "trace.jsonl"
    with TraceRecorder(
        path,
        framework=Framework.PYTORCH,
        framework_version="2.1.0",
        execution_mode=ExecutionMode.EAGER,
        source_root=tmp_path,
    ) as recorder:
        recorder.call("torch.add", lambda: 1)
    record = load_trace_jsonl(path)[0]
    assert not record.location.file.startswith(str(tmp_path))


def test_trace_indices_are_monotonic(tmp_path):
    path = tmp_path / "trace.jsonl"
    with TraceRecorder(
        path,
        framework=Framework.PYTORCH,
        framework_version="2.1.0",
        execution_mode=ExecutionMode.EAGER,
    ) as recorder:
        recorder.call("torch.add", lambda: 1)
        recorder.call("torch.add", lambda: 2)
    assert [record.call_index for record in load_trace_jsonl(path)] == [0, 1]


def test_trace_recorder_refuses_overwrite_by_default(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        TraceRecorder(
            path,
            framework=Framework.PYTORCH,
            framework_version="2.1.0",
            execution_mode=ExecutionMode.EAGER,
        )


def test_complex_scalar_has_explicit_preview():
    summary = summarize_value(complex(2, -3))
    assert summary.dtype == "complex"
    assert summary.preview == {"real": 2.0, "imag": -3.0}


def test_unbounded_python_numbers_stay_valid_for_cross_language_json():
    huge = 2**4096
    integer = summarize_value(huge)
    non_finite_complex = summarize_value(complex(math.inf, math.nan))

    assert integer.numeric is None
    assert integer.preview == str(huge)
    assert non_finite_complex.preview == {"real": "inf", "imag": "nan"}


def test_recorder_validates_tensor_limit_before_creating_file(tmp_path):
    path = tmp_path / "trace.jsonl"
    with pytest.raises(ValueError, match="max_tensor_elements"):
        TraceRecorder(
            path,
            framework=Framework.PYTORCH,
            framework_version="2.1.0",
            execution_mode=ExecutionMode.EAGER,
            max_tensor_elements=0,
        )
    assert not path.exists()


def test_numeric_summary_ignores_boolean_tensor_values():
    summary = summarize_value(FakeTensor([[True, False]], shape=(1, 2), dtype="torch.bool"))
    assert summary.dtype == "bool"
    assert summary.numeric is None


def test_non_finite_tensor_values_are_counted():
    summary = summarize_value(
        FakeTensor([[1.0, math.inf], [math.nan, -1.0]])
    )
    assert summary.numeric.nan_count == 1
    assert summary.numeric.inf_count == 1
    assert summary.numeric.min == -1.0
