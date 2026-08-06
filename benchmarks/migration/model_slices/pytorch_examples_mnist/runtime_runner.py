"""Execute the migrated classifier-head slice and emit one canonical trace."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path


def load_slice(path: Path):
    spec = importlib.util.spec_from_file_location("mnist_executable_slice", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load model slice: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tensor_values(framework: str):
    x = [[-1.0, -0.5, 0.5, 1.0], [0.25, -0.75, 1.25, -1.5]]
    weight1 = [
        [0.10, -0.20, 0.30],
        [-0.40, 0.50, -0.60],
        [0.70, -0.80, 0.90],
        [-1.00, 1.10, -1.20],
    ]
    bias1 = [0.05, -0.10, 0.15]
    weight2 = [[0.20, -0.30], [-0.40, 0.50], [0.60, -0.70]]
    bias2 = [0.125, -0.25]
    values = (x, weight1, bias1, weight2, bias2)
    if framework == "pytorch":
        import torch

        return torch, tuple(torch.tensor(value, dtype=torch.float32) for value in values)
    import mindspore

    return mindspore, tuple(
        mindspore.Tensor(value, dtype=mindspore.float32) for value in values
    )


def to_flat_list(value):
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "asnumpy"):
        value = value.asnumpy()
    return [float(item) for row in value.tolist() for item in row]


def normalized_dtype(value) -> str:
    text = str(value.dtype).strip().lower()
    for prefix in ("torch.", "mindspore.", "mstype.", "numpy."):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def trace_payload(framework: str, version: str, output, *, dtype_fault: bool):
    values = to_flat_list(output)
    dtype = "bool" if dtype_fault else normalized_dtype(output)
    api = "torch.add" if framework == "pytorch" else "mindspore.mint.add"
    return {
        "schema_version": "1.0",
        "record_kind": "api_trace",
        "run_id": f"pytorch-examples-mnist-{framework}",
        "framework": framework,
        "framework_version": version,
        "execution_mode": "eager" if framework == "pytorch" else "py_native",
        "location": {"file": "executable_slice.py", "line": 26, "column": 11},
        "api": api,
        "call_index": 0,
        "output": {
            "kind": "tensor",
            "dtype": dtype,
            "shape": [int(item) for item in output.shape],
            "numeric": {
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
                "nan_count": sum(math.isnan(item) for item in values),
                "inf_count": sum(math.isinf(item) for item in values),
            },
            "preview": values[:8],
        },
        "metadata": {
            "model_slice": "pytorch-examples-mnist-v1",
            "semantic_role": "forward",
            "synthetic_input": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", choices=("pytorch", "mindspore"), required=True)
    parser.add_argument("--slice", default="executable_slice.py")
    parser.add_argument("--trace", required=True)
    parser.add_argument(
        "--fault", choices=("none", "runtime", "dtype"), default="none"
    )
    arguments = parser.parse_args()
    if arguments.fault == "runtime":
        raise RuntimeError("injected target runtime failure")
    framework_module, values = tensor_values(arguments.framework)
    model_slice = load_slice(Path(arguments.slice).resolve())
    output = model_slice.mnist_classifier_head(*values)
    payload = trace_payload(
        arguments.framework,
        framework_module.__version__,
        output,
        dtype_fault=arguments.fault == "dtype",
    )
    trace = Path(arguments.trace)
    trace.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
