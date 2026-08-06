"""Capture and evaluate Graph Mode and advanced training-state parity."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.schema import DiagnosticCategory, SchemaError

DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "advanced_training_v1.json"
)
DATASET_KIND = "cross_framework_advanced_training_cases"
RUNTIMES = ("pytorch", "mindspore-pynative", "mindspore-graph")
SPLITS = {"development", "heldout"}

CASE_DEFINITIONS = {
    "linear-mode-parity": ("forward", None),
    "mlp-mode-parity": ("forward", None),
    "conv-mode-parity": ("forward", None),
    "control-flow-mode-parity": ("forward", None),
    "linear-adam-5step": ("training", None),
    "mlp-adamw-schedule-5step": (
        "training",
        DiagnosticCategory.OPTIMIZER_STATE_MISMATCH,
    ),
    "linear-accumulate-clip-3step": ("training", None),
    "checkpoint-cross-process": ("checkpoint", None),
    "graph-compile-failure-injected": (
        "diagnostic",
        DiagnosticCategory.GRAPH_COMPILE_FAILURE,
    ),
    "runtime-error-injected": ("diagnostic", DiagnosticCategory.RUNTIME_ERROR),
    "gradient-mismatch-injected": (
        "diagnostic",
        DiagnosticCategory.GRADIENT_MISMATCH,
    ),
    "optimizer-state-mismatch-injected": (
        "diagnostic",
        DiagnosticCategory.OPTIMIZER_STATE_MISMATCH,
    ),
    "shape-specialization-injected": (
        "diagnostic",
        DiagnosticCategory.SHAPE_MISMATCH,
    ),
}


@dataclass(frozen=True)
class AdvancedCase:
    case_id: str
    split: str
    kind: str
    capabilities: tuple[str, ...]
    expected_equivalent: bool
    expected_category: DiagnosticCategory | None
    fault_injection: bool


@dataclass(frozen=True)
class AdvancedManifest:
    benchmark_version: str
    source_version_prefix: str
    target_version_prefix: str
    relative_tolerance: float
    absolute_tolerance: float
    cases: tuple[AdvancedCase, ...]


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> AdvancedManifest:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0":
        raise SchemaError("unsupported advanced training schema_version")
    if document.get("benchmark_version") != "advanced-training-v1":
        raise SchemaError("unsupported advanced training benchmark_version")
    if document.get("dataset_kind") != DATASET_KIND:
        raise SchemaError("unsupported advanced training dataset_kind")
    source = document.get("source_framework")
    target = document.get("target_framework")
    if not isinstance(source, dict) or source.get("name") != "pytorch":
        raise SchemaError("advanced training source framework must be pytorch")
    if not isinstance(target, dict) or target.get("name") != "mindspore":
        raise SchemaError("advanced training target framework must be mindspore")
    values = document.get("cases")
    if not isinstance(values, list) or len(values) != len(CASE_DEFINITIONS):
        raise SchemaError("advanced training manifest has unexpected case count")
    cases: list[AdvancedCase] = []
    identifiers: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise SchemaError("advanced training case must be an object")
        case_id = _required_string(value, "id")
        if case_id in identifiers:
            raise SchemaError("advanced training case ids must be unique")
        identifiers.add(case_id)
        definition = CASE_DEFINITIONS.get(case_id)
        if definition is None:
            raise SchemaError(f"unsupported advanced training case: {case_id}")
        kind = _required_string(value, "kind")
        if kind != definition[0]:
            raise SchemaError(f"advanced training case {case_id} has changed kind")
        split = _required_string(value, "split")
        if split not in SPLITS:
            raise SchemaError(f"advanced training case {case_id} has invalid split")
        capabilities = value.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities or any(
            not isinstance(item, str) or not item.strip() for item in capabilities
        ):
            raise SchemaError(f"advanced training case {case_id} needs capabilities")
        expected_equivalent = value.get("expected_equivalent")
        fault_injection = value.get("fault_injection")
        if not isinstance(expected_equivalent, bool) or not isinstance(
            fault_injection, bool
        ):
            raise SchemaError(f"advanced training case {case_id} has invalid flags")
        raw_category = value.get("expected_category")
        category = (
            DiagnosticCategory.parse(raw_category)
            if isinstance(raw_category, str)
            else None
        )
        if category != definition[1]:
            raise SchemaError(
                f"advanced training case {case_id} has changed expected category"
            )
        if fault_injection and expected_equivalent:
            raise SchemaError(f"advanced training case {case_id} has inconsistent flags")
        cases.append(
            AdvancedCase(
                case_id,
                split,
                kind,
                tuple(capabilities),
                expected_equivalent,
                category,
                fault_injection,
            )
        )
    if set(CASE_DEFINITIONS) != identifiers:
        raise SchemaError("advanced training manifest does not match frozen cases")
    return AdvancedManifest(
        _required_string(document, "benchmark_version"),
        _required_string(source, "version_prefix"),
        _required_string(target, "version_prefix"),
        _non_negative_number(document, "relative_tolerance"),
        _non_negative_number(document, "absolute_tolerance"),
        tuple(cases),
    )


def capture_runtime(
    runtime: str,
    output_path: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    *,
    overwrite: bool = False,
    allow_version_mismatch: bool = False,
) -> dict[str, Any]:
    if runtime not in RUNTIMES:
        raise ValueError(f"runtime must be one of: {', '.join(RUNTIMES)}")
    manifest = load_manifest(manifest_path)
    output = Path(output_path).resolve()
    if output.exists() and not overwrite:
        raise FileExistsError("capture output exists; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    framework = "pytorch" if runtime == "pytorch" else "mindspore"
    module_name = "torch" if framework == "pytorch" else "mindspore"
    expected_prefix = (
        manifest.source_version_prefix
        if framework == "pytorch"
        else manifest.target_version_prefix
    )
    try:
        module = importlib.import_module(module_name)
    except (ImportError, OSError) as error:
        return _capture_report(
            manifest, runtime, "unavailable", None, expected_prefix, [], error
        )
    version = str(getattr(module, "__version__", "unknown"))
    if not _version_matches(version, expected_prefix) and not allow_version_mismatch:
        return _capture_report(
            manifest,
            runtime,
            "version_mismatch",
            version,
            expected_prefix,
            [],
            ValueError(f"expected version prefix {expected_prefix}"),
        )
    device_target = "CPU"
    if framework == "pytorch":
        module.set_num_threads(1)
        execution_mode = "eager"
    else:
        mode = module.GRAPH_MODE if runtime == "mindspore-graph" else module.PYNATIVE_MODE
        module.set_context(mode=mode, device_target=device_target)
        execution_mode = "graph" if runtime == "mindspore-graph" else "py_native"
    artifacts = output.parent / f".{output.stem}-{runtime}-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    cases = []
    unexpected_failures = []
    for case in manifest.cases:
        started = time.perf_counter()
        try:
            result = _capture_case(case, runtime, module, artifacts)
        except Exception as error:  # preserve one failed case without losing the suite
            result = {
                "status": "error",
                "phase": "capture",
                "error": _error_payload(error),
            }
        result.update(
            {
                "id": case.case_id,
                "split": case.split,
                "kind": case.kind,
                "capabilities": list(case.capabilities),
                "fault_injection": case.fault_injection,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
        if result["status"] == "error":
            unexpected_failures.append(case.case_id)
        cases.append(result)
    report = {
        "schema_version": "1.0",
        "record_kind": "advanced_training_capture",
        "benchmark_version": manifest.benchmark_version,
        "runtime": runtime,
        "framework": framework,
        "framework_version": version,
        "expected_version_prefix": expected_prefix,
        "version_compatible": _version_matches(version, expected_prefix),
        "execution_mode": execution_mode,
        "device_target": device_target,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "pid": os.getpid(),
        "status": "captured" if not unexpected_failures else "case_failure",
        "case_count": len(cases),
        "cases": cases,
        "unexpected_failures": unexpected_failures,
    }
    _atomic_write_json(output, report)
    return report


def _capture_case(case, runtime, module, artifacts):
    if case.kind == "forward":
        return {"status": "ok", "measurements": _forward_case(case.case_id, runtime, module)}
    if case.kind == "training":
        return {"status": "ok", "measurements": _training_case(case.case_id, runtime, module)}
    if case.kind == "checkpoint":
        return {
            "status": "ok",
            "measurements": _checkpoint_roundtrip(runtime, artifacts),
        }
    return _diagnostic_case(case.case_id, runtime, module)


def _forward_case(case_id, runtime, module):
    if runtime == "pytorch":
        tensor = lambda value: module.tensor(value, dtype=module.float32)
        if case_id == "linear-mode-parity":
            layer = module.nn.Linear(2, 2)
            with module.no_grad():
                layer.weight.copy_(tensor([[0.2, -0.4], [0.5, 0.3]]))
                layer.bias.copy_(tensor([0.1, -0.2]))
            value = tensor([[1.0, -2.0], [0.5, 3.0]])
            return _measurement(layer(value), layer)
        if case_id == "mlp-mode-parity":
            model = _torch_model(module, "mlp")
            value = tensor([[1.0, -2.0], [0.5, 3.0]])
            return _measurement(model(value), model)
        if case_id == "conv-mode-parity":
            layer = module.nn.Conv2d(1, 1, 2, bias=False)
            with module.no_grad():
                layer.weight.copy_(tensor([[[[0.2, -0.4], [0.5, 0.3]]]]))
            value = tensor([[[[1.0, 2.0, 3.0], [0.5, -1.0, 2.0], [3.0, 1.0, 0.0]]]])
            return _measurement(layer(value), layer)

        class ControlFlow(module.nn.Module):
            def forward(self, value):
                return value * 2.0 if value.sum() > 0 else value - 2.0

        model = ControlFlow()
        value = tensor([[1.0, -0.25], [0.5, 0.25]])
        return _measurement(model(value), model)

    tensor = lambda value: module.Tensor(value, dtype=module.float32)
    if case_id == "linear-mode-parity":
        layer = module.nn.Dense(
            2,
            2,
            weight_init=tensor([[0.2, -0.4], [0.5, 0.3]]),
            bias_init=tensor([0.1, -0.2]),
        )
        value = tensor([[1.0, -2.0], [0.5, 3.0]])
        return _measurement(layer(value), layer)
    if case_id == "mlp-mode-parity":
        model = _mindspore_model(module, "mlp")
        value = tensor([[1.0, -2.0], [0.5, 3.0]])
        return _measurement(model(value), model)
    if case_id == "conv-mode-parity":
        layer = module.nn.Conv2d(
            1,
            1,
            2,
            has_bias=False,
            pad_mode="valid",
            weight_init=tensor([[[[0.2, -0.4], [0.5, 0.3]]]]),
        )
        value = tensor([[[[1.0, 2.0, 3.0], [0.5, -1.0, 2.0], [3.0, 1.0, 0.0]]]])
        return _measurement(layer(value), layer)

    class ControlFlow(module.nn.Cell):
        def construct(self, value):
            if value.sum() > 0:
                return value * 2.0
            return value - 2.0

    model = ControlFlow()
    value = tensor([[1.0, -0.25], [0.5, 0.25]])
    return _measurement(model(value), model)


def _training_case(case_id, runtime, module):
    if case_id == "linear-accumulate-clip-3step":
        return _accumulation_training(runtime, module)
    model_kind = "linear" if case_id == "linear-adam-5step" else "mlp"
    adamw = case_id == "mlp-adamw-schedule-5step"
    learning_rates = (
        [0.02, 0.02, 0.02, 0.02, 0.02]
        if not adamw
        else [0.015, 0.013, 0.009, 0.005, 0.002]
    )
    if runtime == "pytorch":
        model = _torch_model(module, model_kind)
        inputs, targets = _torch_training_data(module)
        optimizer_type = module.optim.AdamW if adamw else module.optim.Adam
        optimizer = optimizer_type(
            model.parameters(),
            lr=learning_rates[0],
            betas=(0.9, 0.999),
            eps=1e-8,
            weight_decay=0.01 if adamw else 0.0,
        )
        losses = []
        gradient_norms = []
        for learning_rate in learning_rates:
            optimizer.param_groups[0]["lr"] = learning_rate
            optimizer.zero_grad(set_to_none=True)
            loss = module.nn.functional.mse_loss(model(inputs), targets)
            loss.backward()
            gradient_norms.append(_torch_gradient_norm(module, model.parameters()))
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))
        state_slots = sum(len(value) for value in optimizer.state.values())
        return _training_measurements(
            model, losses, gradient_norms, learning_rates, state_slots, "adamw" if adamw else "adam"
        )

    model = _mindspore_model(module, model_kind)
    inputs, targets = _mindspore_training_data(module)
    lr_tensor = module.Tensor(learning_rates, module.float32)
    if adamw:
        optimizer = module.nn.AdamWeightDecay(
            model.trainable_params(),
            learning_rate=lr_tensor,
            beta1=0.9,
            beta2=0.999,
            eps=1e-8,
            weight_decay=0.01,
        )
    else:
        optimizer = module.nn.Adam(
            model.trainable_params(),
            learning_rate=lr_tensor,
            beta1=0.9,
            beta2=0.999,
            eps=1e-8,
            weight_decay=0.0,
        )
    loss_network = module.nn.WithLossCell(model, module.nn.MSELoss())
    gradient_function = module.value_and_grad(
        loss_network, grad_position=None, weights=model.trainable_params()
    )
    losses = []
    gradient_norms = []
    for _ in learning_rates:
        loss, gradients = gradient_function(inputs, targets)
        gradient_norms.append(_mindspore_gradient_norm(gradients))
        optimizer(gradients)
        losses.append(float(loss.asnumpy().item()))
    state_slots = len(tuple(optimizer.get_parameters())) - len(model.trainable_params())
    return _training_measurements(
        model, losses, gradient_norms, learning_rates, state_slots, "adamw" if adamw else "adam"
    )


def _accumulation_training(runtime, module):
    learning_rates = [0.01, 0.01, 0.01]
    clip_norm = 0.25
    if runtime == "pytorch":
        model = _torch_model(module, "linear")
        inputs, targets = _torch_training_data(module)
        optimizer = module.optim.Adam(model.parameters(), lr=0.01, eps=1e-8)
        losses = []
        pre_clip = []
        post_clip = []
        for step in range(3):
            optimizer.zero_grad(set_to_none=True)
            micro_losses = []
            for offset in range(2):
                index = (step + offset) % 2
                batch_inputs = inputs[index * 2 : index * 2 + 2]
                batch_targets = targets[index * 2 : index * 2 + 2]
                loss = module.nn.functional.mse_loss(model(batch_inputs), batch_targets)
                (loss / 2.0).backward()
                micro_losses.append(float(loss.detach().cpu().item()))
            pre_clip.append(_torch_gradient_norm(module, model.parameters()))
            module.nn.utils.clip_grad_norm_(model.parameters(), clip_norm)
            post_clip.append(_torch_gradient_norm(module, model.parameters()))
            optimizer.step()
            losses.append(sum(micro_losses) / len(micro_losses))
        return _training_measurements(
            model,
            losses,
            post_clip,
            learning_rates,
            sum(len(value) for value in optimizer.state.values()),
            "adam-accumulate-clip",
            extra={"pre_clip_gradient_norms": pre_clip, "clip_norm": clip_norm, "accumulation_steps": 2},
        )

    model = _mindspore_model(module, "linear")
    inputs, targets = _mindspore_training_data(module)
    weights = model.trainable_params()
    optimizer = module.nn.Adam(weights, learning_rate=0.01, eps=1e-8)
    loss_function = module.nn.MSELoss()

    def forward(data, labels):
        return loss_function(model(data), labels)

    gradient_function = module.value_and_grad(forward, None, weights)
    losses = []
    pre_clip = []
    post_clip = []
    for step in range(3):
        accumulated = None
        micro_losses = []
        for offset in range(2):
            index = (step + offset) % 2
            loss, gradients = gradient_function(
                inputs[index * 2 : index * 2 + 2],
                targets[index * 2 : index * 2 + 2],
            )
            micro_losses.append(float(loss.asnumpy().item()))
            accumulated = (
                tuple(gradient / 2.0 for gradient in gradients)
                if accumulated is None
                else tuple(
                    current + gradient / 2.0
                    for current, gradient in zip(accumulated, gradients)
                )
            )
        pre_clip.append(_mindspore_gradient_norm(accumulated))
        clipped = module.ops.clip_by_global_norm(accumulated, clip_norm)
        post_clip.append(_mindspore_gradient_norm(clipped))
        optimizer(clipped)
        losses.append(sum(micro_losses) / len(micro_losses))
    return _training_measurements(
        model,
        losses,
        post_clip,
        learning_rates,
        len(tuple(optimizer.get_parameters())) - len(weights),
        "adam-accumulate-clip",
        extra={"pre_clip_gradient_norms": pre_clip, "clip_norm": clip_norm, "accumulation_steps": 2},
    )


def _diagnostic_case(case_id, runtime, module):
    if case_id == "graph-compile-failure-injected":
        if runtime != "mindspore-graph":
            return {"status": "not_applicable", "phase": "compile"}

        class InvalidGraph(module.nn.Cell):
            def construct(self, value):
                return self.operator_that_does_not_exist(value)

        try:
            InvalidGraph()(module.Tensor([1.0], module.float32))
        except Exception as error:
            return {
                "status": "expected_error",
                "phase": "compile",
                "observed_category": DiagnosticCategory.GRAPH_COMPILE_FAILURE.value,
                "error": _error_payload(error),
            }
        raise RuntimeError("frozen graph compile fault did not fail")
    if case_id == "runtime-error-injected":
        if runtime != "mindspore-pynative":
            return {"status": "not_applicable", "phase": "runtime"}
        try:
            raise RuntimeError("injected runtime failure after successful setup")
        except RuntimeError as error:
            return {
                "status": "expected_error",
                "phase": "runtime",
                "observed_category": DiagnosticCategory.RUNTIME_ERROR.value,
                "error": _error_payload(error),
            }
    if case_id == "gradient-mismatch-injected":
        signature = _gradient_signature(runtime, module)
        if runtime == "mindspore-graph":
            signature = [value * 1.5 for value in signature]
        return {
            "status": "ok",
            "phase": "gradient",
            "measurements": {"gradient_signature": signature},
        }
    if case_id == "optimizer-state-mismatch-injected":
        measurements = _optimizer_fault_trajectory(runtime, module)
        return {"status": "ok", "phase": "optimizer", "measurements": measurements}
    if runtime != "mindspore-graph":
        return {"status": "not_applicable", "phase": "runtime"}
    layer = module.nn.Dense(2, 1)
    layer(module.Tensor([[1.0, 2.0]], module.float32))
    try:
        layer(module.Tensor([[1.0, 2.0, 3.0]], module.float32))
    except Exception as error:
        return {
            "status": "expected_error",
            "phase": "runtime",
            "observed_category": DiagnosticCategory.SHAPE_MISMATCH.value,
            "error": _error_payload(error),
        }
    raise RuntimeError("frozen shape specialization fault did not fail")


def _gradient_signature(runtime, module):
    if runtime == "pytorch":
        model = _torch_model(module, "linear")
        inputs, targets = _torch_training_data(module)
        loss = module.nn.functional.mse_loss(model(inputs), targets)
        gradients = module.autograd.grad(loss, tuple(model.parameters()))
        return _flatten_tensors(gradients)
    model = _mindspore_model(module, "linear")
    inputs, targets = _mindspore_training_data(module)
    loss_function = module.nn.MSELoss()

    def forward(data, labels):
        return loss_function(model(data), labels)

    _, gradients = module.value_and_grad(
        forward, None, model.trainable_params()
    )(inputs, targets)
    return _flatten_tensors(gradients)


def _optimizer_fault_trajectory(runtime, module):
    if runtime == "pytorch":
        model = _torch_model(module, "linear")
        inputs, targets = _torch_training_data(module)
        optimizer = module.optim.Adam(model.parameters(), lr=0.02, betas=(0.9, 0.999), eps=1e-8)
        losses = []
        for _ in range(4):
            optimizer.zero_grad(set_to_none=True)
            loss = module.nn.functional.mse_loss(model(inputs), targets)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))
        return {"losses": losses, "final_parameters": _parameter_values(model), "beta2": 0.999}
    model = _mindspore_model(module, "linear")
    inputs, targets = _mindspore_training_data(module)
    beta2 = 0.9 if runtime == "mindspore-graph" else 0.999
    optimizer = module.nn.Adam(model.trainable_params(), learning_rate=0.02, beta2=beta2, eps=1e-8)
    loss_function = module.nn.MSELoss()

    def forward(data, labels):
        return loss_function(model(data), labels)

    gradient_function = module.value_and_grad(forward, None, model.trainable_params())
    losses = []
    for _ in range(4):
        loss, gradients = gradient_function(inputs, targets)
        optimizer(gradients)
        losses.append(float(loss.asnumpy().item()))
    return {"losses": losses, "final_parameters": _parameter_values(model), "beta2": beta2}


def _checkpoint_roundtrip(runtime, artifacts):
    suffix = ".pt" if runtime == "pytorch" else ".ckpt"
    checkpoint = artifacts / f"checkpoint{suffix}"
    producer = artifacts / "checkpoint-producer.json"
    consumer = artifacts / "checkpoint-consumer.json"
    command = [
        sys.executable,
        "-m",
        "migration.advanced_training",
        "_checkpoint-worker",
        runtime,
    ]
    environment = dict(os.environ)
    python_root = str(Path(__file__).parents[1])
    environment["PYTHONPATH"] = python_root + os.pathsep + environment.get("PYTHONPATH", "")
    for action, result in (("write", producer), ("read", consumer)):
        completed = subprocess.run(
            [*command, action, str(checkpoint), str(result)],
            cwd=python_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"checkpoint {action} worker failed: {completed.stderr.strip()}"
            )
    written = json.loads(producer.read_text(encoding="utf-8"))
    restored = json.loads(consumer.read_text(encoding="utf-8"))
    return {
        "producer_pid": written["pid"],
        "consumer_pid": restored["pid"],
        "distinct_processes": written["pid"] != restored["pid"],
        "checkpoint_bytes": checkpoint.stat().st_size,
        "parameter_schema_before": written["parameter_schema"],
        "parameter_schema_after": restored["parameter_schema"],
        "output_before": written["output"],
        "output_after": restored["output"],
        "roundtrip_equivalent": _allclose(
            written["output"], restored["output"], 1e-7, 1e-8
        )
        and written["parameter_schema"] == restored["parameter_schema"],
    }


def checkpoint_worker(runtime, action, checkpoint_path, output_path):
    if runtime not in RUNTIMES or action not in {"write", "read"}:
        raise ValueError("invalid checkpoint worker arguments")
    checkpoint = Path(checkpoint_path).resolve()
    output = Path(output_path).resolve()
    if runtime == "pytorch":
        module = importlib.import_module("torch")
        model = _torch_model(module, "linear", zeros=action == "read")
        if action == "write":
            module.save(model.state_dict(), checkpoint)
        else:
            model.load_state_dict(module.load(checkpoint, map_location="cpu", weights_only=True))
        value = module.tensor([[1.0, -2.0], [0.5, 3.0]], dtype=module.float32)
    else:
        module = importlib.import_module("mindspore")
        module.set_context(
            mode=module.GRAPH_MODE if runtime == "mindspore-graph" else module.PYNATIVE_MODE,
            device_target="CPU",
        )
        model = _mindspore_model(module, "linear", zeros=action == "read")
        if action == "write":
            module.save_checkpoint(model, str(checkpoint))
        else:
            parameters = module.load_checkpoint(str(checkpoint))
            not_loaded, checkpoint_not_loaded = module.load_param_into_net(model, parameters)
            if not_loaded or checkpoint_not_loaded:
                raise RuntimeError("checkpoint parameters were not fully restored")
        value = module.Tensor([[1.0, -2.0], [0.5, 3.0]], module.float32)
    payload = {
        "pid": os.getpid(),
        "output": _to_list(model(value)),
        "parameter_schema": _parameter_schema(model),
    }
    _atomic_write_json(output, payload)
    return payload


def evaluate_benchmark(
    capture_root: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    root = Path(capture_root).resolve()
    captures = {}
    for runtime in RUNTIMES:
        path = root / f"{runtime}.json"
        if path.is_file():
            captures[runtime] = json.loads(path.read_text(encoding="utf-8"))
    results = []
    categories: dict[str, int] = {}
    for case in manifest.cases:
        runtime_cases = {
            runtime: _case_by_id(capture, case.case_id)
            for runtime, capture in captures.items()
        }
        missing = [runtime for runtime in RUNTIMES if runtime not in runtime_cases]
        if missing:
            results.append(
                {"id": case.case_id, "split": case.split, "status": "missing_capture", "missing": missing}
            )
            continue
        equivalent, category, evidence = _evaluate_case(
            case,
            runtime_cases,
            manifest.relative_tolerance,
            manifest.absolute_tolerance,
        )
        classification_correct = equivalent == case.expected_equivalent
        localization_correct = (
            None
            if case.expected_category is None
            else category == case.expected_category
        )
        passed = classification_correct and localization_correct is not False
        if category is not None:
            categories[category.value] = categories.get(category.value, 0) + 1
        results.append(
            {
                "id": case.case_id,
                "split": case.split,
                "kind": case.kind,
                "capabilities": list(case.capabilities),
                "fault_injection": case.fault_injection,
                "status": "equivalent" if equivalent else "divergent",
                "expected_equivalent": case.expected_equivalent,
                "classification_correct": classification_correct,
                "expected_category": case.expected_category.value if case.expected_category else None,
                "first_divergence_category": category.value if category else None,
                "localization_correct": localization_correct,
                "passed": passed,
                "evidence": evidence,
            }
        )
    evaluated = [item for item in results if "passed" in item]
    faults = [item for item in evaluated if item["fault_injection"]]
    mode_cases = [item for item in evaluated if "mode-parity" in item["capabilities"]]
    optimizers = [item for item in evaluated if item["kind"] == "training" and not item["fault_injection"]]
    checkpoints = [item for item in evaluated if item["kind"] == "checkpoint"]
    versions_match = len(captures) == len(RUNTIMES) and all(
        capture.get("version_compatible") is True for capture in captures.values()
    )
    complete = len(evaluated) == len(manifest.cases)
    report = {
        "schema_version": "1.0",
        "record_kind": "advanced_training_report",
        "benchmark_version": manifest.benchmark_version,
        "dataset_kind": DATASET_KIND,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "case_count": len(manifest.cases),
        "evaluated_case_count": len(evaluated),
        "fault_case_count": len(faults),
        "mode_component_count": len(mode_cases),
        "multi_step_optimizer_case_count": len(optimizers),
        "checkpoint_case_count": len(checkpoints),
        "complete": complete,
        "version_prefixes_match": versions_match,
        "passed": complete and versions_match and all(item["passed"] for item in evaluated),
        "classification_accuracy": _rate(evaluated, lambda item: item["classification_correct"]),
        "diagnostic_top1_accuracy": _rate(faults, lambda item: item["localization_correct"]),
        "mode_parity_rate": _rate(mode_cases, lambda item: item["status"] == "equivalent"),
        "multi_step_optimizer_parity_rate": _rate(optimizers, lambda item: item["status"] == "equivalent"),
        "checkpoint_restore_rate": _rate(checkpoints, lambda item: item["status"] == "equivalent"),
        "first_divergence_categories": dict(sorted(categories.items())),
        "runtime_environments": {
            runtime: {
                key: capture.get(key)
                for key in (
                    "framework",
                    "framework_version",
                    "execution_mode",
                    "device_target",
                    "python_version",
                    "platform",
                    "processor",
                )
            }
            for runtime, capture in captures.items()
        },
        "splits": {split: _split_metrics(evaluated, split) for split in sorted(SPLITS)},
        "cases": results,
        "limitations": [
            "The suite compares deterministic CPU runs on tiny networks and does not prove full convergence.",
            "Training trajectories contain 3-5 optimizer updates; distributed, mixed-precision and accelerator kernels are out of scope.",
            "Held-out failures are frozen fault injections used to test phase/category localization.",
            "Checkpoint evidence proves fresh-process restoration for this benchmark, not compatibility across all framework releases.",
        ],
    }
    validate_report(report)
    return report


def validate_report(report: dict[str, Any]) -> None:
    if report.get("schema_version") != "1.0":
        raise ValueError("unsupported advanced training report schema_version")
    if report.get("record_kind") != "advanced_training_report":
        raise ValueError("record_kind must be advanced_training_report")
    if report.get("benchmark_version") != "advanced-training-v1":
        raise ValueError("unsupported advanced training benchmark_version")
    integer_fields = (
        "case_count",
        "evaluated_case_count",
        "fault_case_count",
        "mode_component_count",
        "multi_step_optimizer_case_count",
        "checkpoint_case_count",
    )
    if any(not isinstance(report.get(name), int) or report[name] < 0 for name in integer_fields):
        raise ValueError("advanced training counts must be non-negative integers")
    rate_fields = (
        "classification_accuracy",
        "diagnostic_top1_accuracy",
        "mode_parity_rate",
        "multi_step_optimizer_parity_rate",
        "checkpoint_restore_rate",
    )
    if any(
        not isinstance(report.get(name), (int, float)) or not 0 <= report[name] <= 1
        for name in rate_fields
    ):
        raise ValueError("advanced training rates must be between zero and one")
    cases = report.get("cases")
    if not isinstance(cases, list) or report["case_count"] != len(cases):
        raise ValueError("advanced training report case count is invalid")
    if report["case_count"] < 13 or report["evaluated_case_count"] > report["case_count"]:
        raise ValueError("advanced training report has invalid coverage")
    if not isinstance(report.get("complete"), bool) or not isinstance(
        report.get("passed"), bool
    ):
        raise ValueError("advanced training report needs terminal flags")
    environments = report.get("runtime_environments")
    if not isinstance(environments, dict) or not set(environments) <= set(RUNTIMES):
        raise ValueError("advanced training report has invalid runtime environments")
    if report["passed"] and not report["complete"]:
        raise ValueError("a passed advanced training report must be complete")
    if report["complete"]:
        if report["evaluated_case_count"] != report["case_count"]:
            raise ValueError("a complete advanced training report needs every case")
        if report["fault_case_count"] < 5:
            raise ValueError("advanced training report needs at least five fault cases")
        if report["mode_component_count"] < 3:
            raise ValueError("advanced training report needs at least three mode components")
        if report["multi_step_optimizer_case_count"] < 2:
            raise ValueError("advanced training report needs at least two optimizer cases")
        if report["checkpoint_case_count"] < 1:
            raise ValueError("advanced training report needs a checkpoint case")
        if not set(RUNTIMES) <= set(environments):
            raise ValueError("a complete advanced training report needs all runtimes")
    if not isinstance(report.get("first_divergence_categories"), dict):
        raise ValueError("advanced training report needs divergence categories")


def _evaluate_case(case, values, rtol, atol):
    eager = values["pytorch"]
    pynative = values["mindspore-pynative"]
    graph = values["mindspore-graph"]
    if case.kind == "forward":
        outputs = [item.get("measurements", {}).get("output") for item in (eager, pynative, graph)]
        equivalent = all(output is not None for output in outputs) and _allclose(outputs[0], outputs[1], rtol, atol) and _allclose(outputs[1], outputs[2], rtol, atol)
        return equivalent, None if equivalent else DiagnosticCategory.VALUE_MISMATCH, {"compared_runtimes": list(RUNTIMES)}
    if case.kind == "training":
        measurements = [item.get("measurements", {}) for item in (eager, pynative, graph)]
        losses = [item.get("losses") for item in measurements]
        parameters = [item.get("final_parameters") for item in measurements]
        equivalent = all(value is not None for value in losses + parameters) and _allclose(losses[0], losses[1], rtol, atol) and _allclose(losses[1], losses[2], rtol, atol) and _allclose(parameters[0], parameters[1], rtol, atol) and _allclose(parameters[1], parameters[2], rtol, atol)
        return equivalent, None if equivalent else DiagnosticCategory.OPTIMIZER_STATE_MISMATCH, {"steps": len(losses[0]) if losses[0] else 0, "loss_trend": [_trend(value) for value in losses]}
    if case.kind == "checkpoint":
        measurements = [item.get("measurements", {}) for item in (eager, pynative, graph)]
        equivalent = all(item.get("roundtrip_equivalent") and item.get("distinct_processes") and item.get("checkpoint_bytes", 0) > 0 for item in measurements)
        return equivalent, None if equivalent else DiagnosticCategory.CHECKPOINT_MISMATCH, {"producer_pids": [item.get("producer_pid") for item in measurements], "consumer_pids": [item.get("consumer_pid") for item in measurements]}
    if case.case_id in {"graph-compile-failure-injected", "runtime-error-injected", "shape-specialization-injected"}:
        selected = graph if case.case_id != "runtime-error-injected" else pynative
        raw = selected.get("observed_category")
        category = DiagnosticCategory.parse(raw) if isinstance(raw, str) else None
        return False, category, {"phase": selected.get("phase"), "error_type": selected.get("error", {}).get("type")}
    if case.case_id == "gradient-mismatch-injected":
        left = pynative.get("measurements", {}).get("gradient_signature")
        right = graph.get("measurements", {}).get("gradient_signature")
        divergent = left is not None and right is not None and not _allclose(left, right, rtol, atol)
        return not divergent, DiagnosticCategory.GRADIENT_MISMATCH if divergent else None, {"phase": "gradient"}
    left = pynative.get("measurements", {})
    right = graph.get("measurements", {})
    divergent = left.get("beta2") != right.get("beta2") or not _allclose(left.get("final_parameters"), right.get("final_parameters"), rtol, atol)
    return not divergent, DiagnosticCategory.OPTIMIZER_STATE_MISMATCH if divergent else None, {"phase": "optimizer", "pynative_beta2": left.get("beta2"), "graph_beta2": right.get("beta2")}


def _torch_model(module, kind, *, zeros=False):
    tensor = lambda value: module.tensor(value, dtype=module.float32)
    if kind == "linear":
        model = module.nn.Linear(2, 1)
        with module.no_grad():
            model.weight.copy_(tensor([[0.2, -0.4]]) if not zeros else module.zeros((1, 2)))
            model.bias.copy_(tensor([0.1]) if not zeros else module.zeros(1))
        return model
    first = module.nn.Linear(2, 3)
    second = module.nn.Linear(3, 1)
    with module.no_grad():
        first.weight.copy_(tensor([[0.2, -0.4], [0.1, 0.3], [-0.5, 0.2]]))
        first.bias.copy_(tensor([0.1, -0.2, 0.05]))
        second.weight.copy_(tensor([[0.3, -0.6, 0.2]]))
        second.bias.copy_(tensor([0.2]))
    return module.nn.Sequential(first, module.nn.ReLU(), second)


def _mindspore_model(module, kind, *, zeros=False):
    tensor = lambda value: module.Tensor(value, module.float32)
    if kind == "linear":
        return module.nn.Dense(
            2,
            1,
            weight_init="zeros" if zeros else tensor([[0.2, -0.4]]),
            bias_init="zeros" if zeros else tensor([0.1]),
        )
    return module.nn.SequentialCell(
        module.nn.Dense(2, 3, weight_init=tensor([[0.2, -0.4], [0.1, 0.3], [-0.5, 0.2]]), bias_init=tensor([0.1, -0.2, 0.05])),
        module.nn.ReLU(),
        module.nn.Dense(3, 1, weight_init=tensor([[0.3, -0.6, 0.2]]), bias_init=tensor([0.2])),
    )


def _torch_training_data(module):
    return (
        module.tensor([[1.0, -2.0], [0.5, 3.0], [-1.0, 0.25], [2.0, 1.0]], dtype=module.float32),
        module.tensor([[0.5], [-1.0], [0.25], [1.5]], dtype=module.float32),
    )


def _mindspore_training_data(module):
    return (
        module.Tensor([[1.0, -2.0], [0.5, 3.0], [-1.0, 0.25], [2.0, 1.0]], module.float32),
        module.Tensor([[0.5], [-1.0], [0.25], [1.5]], module.float32),
    )


def _training_measurements(model, losses, gradient_norms, learning_rates, state_slots, optimizer, *, extra=None):
    result = {
        "losses": losses,
        "loss_trend": _trend(losses),
        "final_parameters": _parameter_values(model),
        "parameter_schema": _parameter_schema(model),
        "gradient_norms": gradient_norms,
        "learning_rates": learning_rates,
        "optimizer": optimizer,
        "optimizer_state_slot_count": state_slots,
        "step_count": len(losses),
    }
    if extra:
        result.update(extra)
    return result


def _measurement(output, model):
    return {"output": _to_list(output), "parameter_schema": _parameter_schema(model)}


def _parameter_schema(model):
    if hasattr(model, "named_parameters"):
        values = list(model.named_parameters())
    else:
        values = list(model.parameters_and_names())
    return [
        {"index": index, "name": name, "shape": list(parameter.shape)}
        for index, (name, parameter) in enumerate(values)
    ]


def _parameter_values(model):
    if hasattr(model, "parameters"):
        parameters = list(model.parameters())
    else:
        parameters = list(model.get_parameters())
    return _flatten_tensors(parameters)


def _flatten_tensors(values):
    flattened = []
    for value in values:
        flattened.extend(_flatten_numbers(_to_list(value)))
    return flattened


def _torch_gradient_norm(module, parameters):
    total = 0.0
    for parameter in parameters:
        if parameter.grad is not None:
            total += float(module.sum(parameter.grad.detach() ** 2).cpu().item())
    return math.sqrt(total)


def _mindspore_gradient_norm(gradients):
    return math.sqrt(sum(value * value for value in _flatten_tensors(gradients)))


def _to_list(value):
    if hasattr(value, "detach"):
        return value.detach().cpu().numpy().tolist()
    if hasattr(value, "asnumpy"):
        return value.asnumpy().tolist()
    return value


def _flatten_numbers(value):
    if isinstance(value, (list, tuple)):
        return [number for item in value for number in _flatten_numbers(item)]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return []
    return [float(value)]


def _allclose(left, right, rtol, atol):
    left_values = _flatten_numbers(left)
    right_values = _flatten_numbers(right)
    return bool(left_values or right_values) and len(left_values) == len(right_values) and all(
        math.isfinite(a) and math.isfinite(b) and abs(a - b) <= atol + rtol * abs(a)
        for a, b in zip(left_values, right_values)
    )


def _trend(values):
    if not values:
        return "empty"
    if len(values) == 1:
        return "single"
    return "decreasing" if values[-1] < values[0] else "non_decreasing"


def _capture_report(manifest, runtime, status, version, expected_prefix, cases, error):
    return {
        "schema_version": "1.0",
        "record_kind": "advanced_training_capture",
        "benchmark_version": manifest.benchmark_version,
        "runtime": runtime,
        "framework_version": version,
        "expected_version_prefix": expected_prefix,
        "version_compatible": bool(version and _version_matches(version, expected_prefix)),
        "status": status,
        "case_count": len(cases),
        "cases": cases,
        "error": _error_payload(error),
    }


def _case_by_id(capture, case_id):
    for value in capture.get("cases", []):
        if value.get("id") == case_id:
            return value
    return None


def _split_metrics(results, split):
    selected = [item for item in results if item["split"] == split]
    return {
        "case_count": len(selected),
        "passed_count": sum(item["passed"] for item in selected),
        "pass_rate": _rate(selected, lambda item: item["passed"]),
    }


def _rate(values, predicate):
    return round(sum(bool(predicate(value)) for value in values) / len(values), 6) if values else 0.0


def _error_payload(error):
    message = str(error)
    replacements = (
        (str(Path(__file__).parents[2]), "<project_root>"),
        (sys.prefix, "<python_prefix>"),
        (str(Path.home()), "<home>"),
    )
    for prefix, placeholder in replacements:
        if prefix:
            message = message.replace(prefix, placeholder)
    return {"type": type(error).__name__, "message": message[:1000]}


def _required_string(value, name):
    result = value.get(name)
    if not isinstance(result, str) or not result.strip():
        raise SchemaError(f"advanced training {name} must be a non-empty string")
    return result


def _non_negative_number(value, name):
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, (int, float)) or result < 0:
        raise SchemaError(f"advanced training {name} must be non-negative")
    return float(result)


def _version_matches(version, prefix):
    return version == prefix or version.startswith(prefix + ".") or version.startswith(prefix + "+")


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("runtime", choices=RUNTIMES)
    capture.add_argument("output_path")
    capture.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    capture.add_argument("--force", action="store_true")
    capture.add_argument("--allow-version-mismatch", action="store_true")
    capture.add_argument("--pretty", action="store_true")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("capture_root")
    evaluate.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    evaluate.add_argument("--pretty", action="store_true")
    worker = subparsers.add_parser("_checkpoint-worker")
    worker.add_argument("runtime", choices=RUNTIMES)
    worker.add_argument("action", choices=("write", "read"))
    worker.add_argument("checkpoint_path")
    worker.add_argument("output_path")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "capture":
            result = capture_runtime(
                arguments.runtime,
                arguments.output_path,
                arguments.manifest,
                overwrite=arguments.force,
                allow_version_mismatch=arguments.allow_version_mismatch,
            )
            passed = result["status"] == "captured"
        elif arguments.command == "evaluate":
            result = evaluate_benchmark(arguments.capture_root, arguments.manifest)
            passed = result["passed"]
        else:
            checkpoint_worker(
                arguments.runtime,
                arguments.action,
                arguments.checkpoint_path,
                arguments.output_path,
            )
            return 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if arguments.pretty else None, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
