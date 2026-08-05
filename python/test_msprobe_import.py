import json

import pytest

from migration.msprobe_import import import_msprobe_dump
from migration.schema import Framework, ValueKind
from migration.trace_compare import load_trace_jsonl


def tensor_stat(dtype="Float32", shape=None, mean=1.5):
    return {
        "type": "mindspore.Tensor",
        "dtype": dtype,
        "shape": [2] if shape is None else shape,
        "Max": 2.0,
        "Min": 1.0,
        "Mean": mean,
        "Norm": 2.23,
        "md5": "1234abcd",
    }


def write_dump(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_imports_mindspore_mint_forward_record(tmp_path):
    dump = tmp_path / "dump.json"
    output = tmp_path / "trace.jsonl"
    write_dump(
        dump,
        {
            "Mint.add.0.forward": {
                "input_args": [tensor_stat()],
                "input_kwargs": {"alpha": 1},
                "output": [tensor_stat()],
            }
        },
    )

    report = import_msprobe_dump(
        dump,
        output,
        framework=Framework.MINDSPORE,
        framework_version="2.9.0",
        run_id="msprobe-1",
    )

    record = load_trace_jsonl(output, Framework.MINDSPORE)[0]
    assert report["records_imported"] == 1
    assert record.api == "mindspore.mint.add"
    assert record.output.dtype == "float32"
    assert record.output.numeric.mean == 1.5
    assert record.arguments[1].name == "alpha"
    assert record.metadata["nan_inf_counts_available"] is False


def test_imports_pytorch_torch_and_functional_names(tmp_path):
    dump = tmp_path / "dump.json"
    output = tmp_path / "trace.jsonl"
    stat = tensor_stat(dtype="torch.float32")
    stat["type"] = "torch.Tensor"
    write_dump(
        dump,
        {
            "Torch.add.0.forward": {"output": [stat]},
            "Functional.relu.0.forward": {"output": [stat]},
        },
    )

    import_msprobe_dump(
        dump,
        output,
        framework=Framework.PYTORCH,
        framework_version="2.1.0",
    )

    records = load_trace_jsonl(output, Framework.PYTORCH)
    assert [record.api for record in records] == [
        "torch.add",
        "torch.nn.functional.relu",
    ]


def test_nested_multi_output_preserves_return_structure(tmp_path):
    dump = tmp_path / "dump.json"
    output = tmp_path / "trace.jsonl"
    write_dump(
        dump,
        {"Functional.split.0.forward": {"output": [tensor_stat(), tensor_stat()]}},
    )

    import_msprobe_dump(
        dump,
        output,
        framework=Framework.MINDSPORE,
        framework_version="2.9.0",
    )

    record = load_trace_jsonl(output)[0]
    assert record.output.kind == ValueKind.SEQUENCE
    assert len(record.output.children) == 2


def test_backward_modules_and_missing_outputs_are_reported_as_skipped(tmp_path):
    dump = tmp_path / "dump.json"
    output = tmp_path / "trace.jsonl"
    write_dump(
        dump,
        {
            "Mint.add.0.forward": {"output": [tensor_stat()]},
            "Mint.add.0.backward": {"output": [tensor_stat()]},
            "Cell.net.Dense.forward.0": {"output": [tensor_stat()]},
            "Mint.relu.0.forward": {"input_args": []},
        },
    )

    report = import_msprobe_dump(
        dump,
        output,
        framework=Framework.MINDSPORE,
        framework_version="2.9.0",
    )

    assert report["records_imported"] == 1
    assert report["records_skipped"] == 3


def test_import_refuses_to_overwrite_trace(tmp_path):
    dump = tmp_path / "dump.json"
    output = tmp_path / "trace.jsonl"
    write_dump(dump, {"Torch.add.0.forward": {"output": [tensor_stat()]}})
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        import_msprobe_dump(
            dump,
            output,
            framework=Framework.PYTORCH,
            framework_version="2.1.0",
        )


def test_import_rejects_dump_without_supported_records(tmp_path):
    dump = tmp_path / "dump.json"
    write_dump(dump, {"Cell.net.Dense.forward.0": {"output": [tensor_stat()]}})

    with pytest.raises(ValueError, match="no supported forward API"):
        import_msprobe_dump(
            dump,
            tmp_path / "trace.jsonl",
            framework=Framework.MINDSPORE,
            framework_version="2.9.0",
        )
