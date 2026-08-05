import json

import pytest

from migration.schema import (
    ApiTraceRecord,
    DiagnosticCategory,
    Framework,
    SchemaError,
)
from migration.trace_compare import compare_traces, load_trace_jsonl


def trace_record(
    framework,
    api,
    call_index=0,
    *,
    dtype="float32",
    shape=None,
    kind="tensor",
    numeric=None,
    children=None,
    error=None,
):
    output = None
    if error is None:
        output = {
            "kind": kind,
            "dtype": dtype,
            "shape": [2] if shape is None else shape,
            "children": children or [],
        }
        if numeric is not None:
            output["numeric"] = numeric
    payload = {
        "schema_version": "1.0",
        "record_kind": "api_trace",
        "run_id": "run-compare-001",
        "framework": framework,
        "framework_version": "2.1" if framework == "pytorch" else "2.9.0",
        "execution_mode": "eager" if framework == "pytorch" else "py_native",
        "location": {"file": "model.py", "line": call_index + 1, "column": 0},
        "api": api,
        "call_index": call_index,
    }
    if output is not None:
        payload["output"] = output
    else:
        payload["error"] = {"error_type": error, "message": "failed"}
    record = ApiTraceRecord.from_dict(payload)
    record.validate()
    return record


def compare_one(source_api="torch.sum", target_api="mindspore.mint.sum", **kwargs):
    source_kwargs = kwargs.pop("source", {})
    target_kwargs = kwargs.pop("target", {})
    assert not kwargs
    return compare_traces(
        [trace_record("pytorch", source_api, **source_kwargs)],
        [trace_record("mindspore", target_api, **target_kwargs)],
    )


def test_equivalent_trace_has_no_diagnostic():
    result = compare_one()

    assert result.equivalent
    assert result.aligned_count == 1
    assert result.diagnostic is None


def test_dtype_mismatch_is_the_first_divergence():
    result = compare_one(target={"dtype": "bool"})

    assert not result.equivalent
    assert result.diagnostic.category == DiagnosticCategory.DTYPE_MISMATCH
    assert result.diagnostic.verified
    assert result.diagnostic.evidence[0].data["target_dtype"] == "bool"


def test_shape_mismatch_is_classified():
    result = compare_one(target={"shape": [1, 2]})
    assert result.diagnostic.category == DiagnosticCategory.SHAPE_MISMATCH


def test_return_kind_mismatch_is_classified_before_dtype():
    result = compare_one(target={"kind": "sequence", "dtype": "bool"})
    assert result.diagnostic.category == DiagnosticCategory.RETURN_STRUCTURE_MISMATCH


def test_child_count_mismatch_is_return_structure_mismatch():
    child = {"kind": "tensor", "dtype": "float32", "shape": [1]}
    result = compare_one(source={"children": [child]}, target={"children": []})
    assert result.diagnostic.category == DiagnosticCategory.RETURN_STRUCTURE_MISMATCH


def test_nan_count_mismatch_is_value_mismatch():
    source_numeric = {"nan_count": 0, "inf_count": 0, "mean": 1.0}
    target_numeric = {"nan_count": 1, "inf_count": 0, "mean": 1.0}
    result = compare_one(
        source={"numeric": source_numeric}, target={"numeric": target_numeric}
    )
    assert result.diagnostic.category == DiagnosticCategory.VALUE_MISMATCH
    assert "NaN/Inf" in result.diagnostic.explanation


def test_numeric_difference_inside_tolerance_is_equivalent():
    result = compare_one(
        source={"numeric": {"mean": 1.0}},
        target={"numeric": {"mean": 1.000001}},
    )
    assert result.equivalent


def test_numeric_difference_outside_tolerance_is_value_mismatch():
    result = compare_one(
        source={"numeric": {"mean": 1.0}},
        target={"numeric": {"mean": 1.1}},
    )
    assert result.diagnostic.category == DiagnosticCategory.VALUE_MISMATCH
    assert result.diagnostic.evidence[0].data["statistic"] == "mean"


def test_runtime_error_on_one_side_is_classified():
    result = compare_one(target={"error": "TypeError"})
    assert result.diagnostic.category == DiagnosticCategory.RUNTIME_ERROR


def test_same_error_type_on_both_sides_is_equivalent():
    result = compare_one(source={"error": "ValueError"}, target={"error": "ValueError"})
    assert result.equivalent


def test_extra_target_call_is_a_sequence_divergence():
    source = [trace_record("pytorch", "torch.sum", 0)]
    target = [
        trace_record("mindspore", "mindspore.mint.mean", 0),
        trace_record("mindspore", "mindspore.mint.sum", 1),
    ]

    result = compare_traces(source, target)

    assert result.diagnostic.category == DiagnosticCategory.NEEDS_MANUAL_REVIEW
    assert result.diagnostic.evidence[0].data["actual_target_api"] == "mindspore.mint.mean"


def test_unknown_source_mapping_is_not_force_aligned():
    result = compare_one("torch.future_operator", "mindspore.ops.future_operator")
    assert result.diagnostic.category == DiagnosticCategory.NEEDS_MANUAL_REVIEW


def test_first_value_divergence_is_reported_after_an_equivalent_call():
    source = [
        trace_record("pytorch", "torch.sum", 0),
        trace_record("pytorch", "torch.mean", 1),
    ]
    target = [
        trace_record("mindspore", "mindspore.mint.sum", 0),
        trace_record("mindspore", "mindspore.mint.mean", 1, dtype="bool"),
    ]

    result = compare_traces(source, target)

    assert result.diagnostic.source_api == "torch.mean"
    assert result.diagnostic.metadata["source_call_index"] == 1


def test_negative_tolerance_is_rejected():
    source = [trace_record("pytorch", "torch.sum")]
    target = [trace_record("mindspore", "mindspore.mint.sum")]
    with pytest.raises(ValueError, match="non-negative"):
        compare_traces(source, target, relative_tolerance=-1)


def test_jsonl_loader_validates_framework_and_order(tmp_path):
    first = trace_record("pytorch", "torch.sum", 0).to_dict()
    second = trace_record("pytorch", "torch.mean", 1).to_dict()
    path = tmp_path / "trace.jsonl"
    path.write_text(
        "\n".join([json.dumps(first), json.dumps(second)]) + "\n",
        encoding="utf-8",
    )

    records = load_trace_jsonl(path, Framework.PYTORCH)

    assert [record.api for record in records] == ["torch.sum", "torch.mean"]


def test_jsonl_loader_rejects_wrong_framework(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(
        json.dumps(trace_record("mindspore", "mindspore.mint.sum").to_dict()),
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="expected pytorch"):
        load_trace_jsonl(path, Framework.PYTORCH)


def test_jsonl_loader_rejects_non_increasing_call_index(tmp_path):
    record = trace_record("pytorch", "torch.sum", 0).to_dict()
    path = tmp_path / "trace.jsonl"
    path.write_text(
        "\n".join([json.dumps(record), json.dumps(record)]), encoding="utf-8"
    )
    with pytest.raises(SchemaError, match="strictly increasing"):
        load_trace_jsonl(path)


def test_jsonl_loader_rejects_empty_trace(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="at least one"):
        load_trace_jsonl(path)
