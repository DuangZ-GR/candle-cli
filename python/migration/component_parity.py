"""Capture and evaluate PyTorch/MindSpore component and training parity cases."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.schema import DiagnosticCategory, ExecutionMode, Framework, SchemaError
from migration.trace_capture import TraceRecorder
from migration.trace_compare import compare_traces, load_trace_jsonl

DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "runtime_components_v1.json"
)
DEFAULT_TRAINING_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "runtime_training_v1.json"
)
COMPONENT_DATASET_KIND = "cross_framework_component_cases"
TRAINING_DATASET_KIND = "cross_framework_training_cases"
CASE_SPLITS = {"development", "heldout"}


@dataclass(frozen=True)
class ComponentOperation:
    name: str
    source_api: str
    target_api: str
    semantic_role: str


@dataclass(frozen=True)
class ComponentCase:
    case_id: str
    split: str
    capabilities: tuple[str, ...]
    operations: tuple[ComponentOperation, ...]
    expected_equivalent: bool
    expected_category: DiagnosticCategory | None
    expected_call_index: int | None
    fault_injection: bool


@dataclass(frozen=True)
class ComponentManifest:
    benchmark_version: str
    dataset_kind: str
    source_version_prefix: str
    target_version_prefix: str
    relative_tolerance: float
    absolute_tolerance: float
    cases: tuple[ComponentCase, ...]


CASE_DEFINITIONS = {
    "mlp-forward": (
        ("dense-1", "torch.nn.Linear", "mindspore.nn.Dense", "forward"),
        ("relu", "torch.nn.functional.relu", "mindspore.ops.relu", "forward"),
        ("dense-2", "torch.nn.Linear", "mindspore.nn.Dense", "forward"),
    ),
    "cnn-forward": (
        ("conv2d", "torch.nn.Conv2d", "mindspore.nn.Conv2d", "forward"),
        ("relu", "torch.nn.functional.relu", "mindspore.ops.relu", "forward"),
        ("flatten", "torch.flatten", "mindspore.ops.flatten", "forward"),
    ),
    "input-weight-gradients": (
        ("loss", "torch.sum", "mindspore.ops.sum", "forward"),
        ("gradients", "torch.autograd.grad", "mindspore.grad", "gradient"),
    ),
    "batchnorm-eval": (
        ("batchnorm", "torch.nn.BatchNorm2d", "mindspore.nn.BatchNorm2d", "inference"),
    ),
    "dtype-bool-regression": (
        ("add", "torch.add", "mindspore.ops.add", "forward"),
    ),
    "batchnorm-default-mode": (
        ("batchnorm", "torch.nn.BatchNorm2d", "mindspore.nn.BatchNorm2d", "training"),
    ),
    "missing-operator-injected": (
        ("sigmoid", "torch.sigmoid", "mindspore.ops.sigmoid", "forward"),
    ),
}

TRAINING_CASE_DEFINITIONS = {
    "linear-sgd-step": (
        ("forward", "torch.nn.Linear", "mindspore.nn.Dense", "forward"),
        ("loss", "torch.nn.functional.mse_loss", "mindspore.ops.mse_loss", "loss"),
        ("gradients", "torch.autograd.grad", "mindspore.value_and_grad", "gradient"),
        (
            "optimizer-step",
            "torch.optim.SGD.step",
            "mindspore.nn.SGD",
            "parameter_update",
        ),
    ),
    "mlp-sgd-step": (
        ("forward", "torch.nn.Sequential", "mindspore.nn.SequentialCell", "forward"),
        ("loss", "torch.nn.functional.mse_loss", "mindspore.ops.mse_loss", "loss"),
        ("gradients", "torch.autograd.grad", "mindspore.value_and_grad", "gradient"),
        (
            "optimizer-step",
            "torch.optim.SGD.step",
            "mindspore.nn.SGD",
            "parameter_update",
        ),
    ),
    "learning-rate-mismatch": (
        ("forward", "torch.nn.Linear", "mindspore.nn.Dense", "forward"),
        ("loss", "torch.nn.functional.mse_loss", "mindspore.ops.mse_loss", "loss"),
        ("gradients", "torch.autograd.grad", "mindspore.value_and_grad", "gradient"),
        (
            "optimizer-step",
            "torch.optim.SGD.step",
            "mindspore.nn.SGD",
            "parameter_update",
        ),
    ),
}

BENCHMARK_CASES = {
    "runtime-components-v1": (COMPONENT_DATASET_KIND, CASE_DEFINITIONS),
    "runtime-training-v1": (TRAINING_DATASET_KIND, TRAINING_CASE_DEFINITIONS),
}


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> ComponentManifest:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0":
        raise SchemaError("unsupported component parity schema_version")
    benchmark_version = _required_string(document, "benchmark_version")
    benchmark_definition = BENCHMARK_CASES.get(benchmark_version)
    if benchmark_definition is None:
        raise SchemaError("unsupported component parity benchmark_version")
    expected_dataset_kind, case_definitions = benchmark_definition
    if document.get("dataset_kind") != expected_dataset_kind:
        raise SchemaError("unsupported component parity dataset_kind")
    source = document.get("source_framework")
    target = document.get("target_framework")
    if not isinstance(source, dict) or source.get("name") != "pytorch":
        raise SchemaError("component parity source framework must be pytorch")
    if not isinstance(target, dict) or target.get("name") != "mindspore":
        raise SchemaError("component parity target framework must be mindspore")
    source_prefix = _required_string(source, "version_prefix")
    target_prefix = _required_string(target, "version_prefix")
    relative_tolerance = _non_negative_number(document, "relative_tolerance")
    absolute_tolerance = _non_negative_number(document, "absolute_tolerance")
    values = document.get("cases")
    if not isinstance(values, list) or not values:
        raise SchemaError("component parity manifest requires cases")
    cases = []
    identifiers = set()
    api_pairs: dict[str, str] = {}
    for value in values:
        if not isinstance(value, dict):
            raise SchemaError("component parity case must be an object")
        case_id = _required_string(value, "id")
        if case_id in identifiers:
            raise SchemaError("component parity case ids must be unique")
        split = _required_string(value, "split")
        if split not in CASE_SPLITS:
            raise SchemaError(f"component parity case {case_id} has invalid split")
        capabilities = value.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities or any(
            not isinstance(item, str) or not item.strip() for item in capabilities
        ):
            raise SchemaError(f"component parity case {case_id} requires capabilities")
        operations = _load_operations(case_id, value.get("operations"), case_definitions)
        for operation in operations:
            previous = api_pairs.setdefault(operation.source_api, operation.target_api)
            if previous != operation.target_api:
                raise SchemaError(
                    f"component parity source API {operation.source_api} maps inconsistently"
                )
        expected_equivalent = value.get("expected_equivalent")
        if not isinstance(expected_equivalent, bool):
            raise SchemaError(
                f"component parity case {case_id} requires expected_equivalent"
            )
        category_value = value.get("expected_category")
        call_index = value.get("expected_call_index")
        if expected_equivalent:
            if category_value is not None or call_index is not None:
                raise SchemaError(
                    f"equivalent component case {case_id} cannot expect a divergence"
                )
            category = None
        else:
            if not isinstance(category_value, str):
                raise SchemaError(
                    f"divergent component case {case_id} requires expected_category"
                )
            category = DiagnosticCategory.parse(category_value)
            if category in (DiagnosticCategory.UNKNOWN,):
                raise SchemaError(
                    f"component parity case {case_id} has invalid expected_category"
                )
            if not isinstance(call_index, int) or isinstance(call_index, bool):
                raise SchemaError(
                    f"divergent component case {case_id} requires expected_call_index"
                )
            if call_index < 0 or call_index >= len(operations):
                raise SchemaError(
                    f"component parity case {case_id} has invalid expected_call_index"
                )
        fault_injection = value.get("fault_injection", False)
        if not isinstance(fault_injection, bool):
            raise SchemaError(
                f"component parity case {case_id} has invalid fault_injection"
            )
        identifiers.add(case_id)
        cases.append(
            ComponentCase(
                case_id,
                split,
                tuple(item.strip() for item in capabilities),
                operations,
                expected_equivalent,
                category,
                call_index,
                fault_injection,
            )
        )
    if identifiers != set(case_definitions):
        raise SchemaError("component parity manifest must contain every built-in case once")
    return ComponentManifest(
        benchmark_version,
        expected_dataset_kind,
        source_prefix,
        target_prefix,
        relative_tolerance,
        absolute_tolerance,
        tuple(cases),
    )


def _load_operations(
    case_id: str,
    values: Any,
    case_definitions: dict[str, tuple[tuple[str, str, str, str], ...]],
) -> tuple[ComponentOperation, ...]:
    expected = case_definitions.get(case_id)
    if expected is None:
        raise SchemaError(f"unknown built-in component case: {case_id}")
    if not isinstance(values, list):
        raise SchemaError(f"component parity case {case_id} requires operations")
    normalized = []
    for value in values:
        if not isinstance(value, dict):
            raise SchemaError(f"component parity case {case_id} has invalid operation")
        normalized.append(
            (
                _required_string(value, "name"),
                _required_string(value, "source_api"),
                _required_string(value, "target_api"),
                _required_string(value, "semantic_role"),
            )
        )
    if tuple(normalized) != expected:
        raise SchemaError(f"component parity case {case_id} does not match built-in case")
    return tuple(ComponentOperation(*operation) for operation in normalized)


class _ComponentBackend:
    def __init__(self, framework: Framework, module: Any):
        self.framework = framework
        self.module = module

    def tensor(self, value: Any, *, requires_grad: bool = False):
        if self.framework == Framework.PYTORCH:
            return self.module.tensor(
                value, dtype=self.module.float32, requires_grad=requires_grad
            )
        return self.module.Tensor(value, dtype=self.module.float32)

    def record(
        self,
        recorder: TraceRecorder,
        case: ComponentCase,
        operation_index: int,
        function,
        *args,
        **kwargs,
    ):
        operation = case.operations[operation_index]
        api = (
            operation.source_api
            if self.framework == Framework.PYTORCH
            else operation.target_api
        )
        return recorder.call(
            api,
            function,
            *args,
            trace_metadata={
                "semantic_role": operation.semantic_role,
                "case_split": case.split,
                "fault_injection": case.fault_injection,
            },
            **kwargs,
        )


def capture_framework(
    framework: Framework | str,
    output_dir: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    *,
    overwrite: bool = False,
    allow_version_mismatch: bool = False,
) -> dict[str, Any]:
    framework = Framework.parse(framework) if isinstance(framework, str) else framework
    if framework not in (Framework.PYTORCH, Framework.MINDSPORE):
        raise ValueError("component capture framework must be pytorch or mindspore")
    manifest = load_manifest(manifest_path)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    expected_prefix = (
        manifest.source_version_prefix
        if framework == Framework.PYTORCH
        else manifest.target_version_prefix
    )
    module_name = "torch" if framework == Framework.PYTORCH else "mindspore"
    try:
        module = importlib.import_module(module_name)
    except (ImportError, OSError) as error:
        return _capture_report(
            manifest,
            framework,
            "unavailable",
            None,
            expected_prefix,
            [],
            [{"id": case.case_id, "reason": type(error).__name__} for case in manifest.cases],
        )
    version = str(getattr(module, "__version__", "unknown"))
    version_compatible = _version_matches(version, expected_prefix)
    if not version_compatible and not allow_version_mismatch:
        return _capture_report(
            manifest,
            framework,
            "version_mismatch",
            version,
            expected_prefix,
            [],
            [
                {"id": case.case_id, "reason": f"expected version prefix {expected_prefix}"}
                for case in manifest.cases
            ],
        )
    paths = [output / f"{case.case_id}.jsonl" for case in manifest.cases]
    existing = [path.name for path in paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"component capture outputs already exist: {', '.join(existing)}"
        )
    try:
        if framework == Framework.MINDSPORE:
            module.set_context(mode=module.PYNATIVE_MODE)
        backend = _ComponentBackend(framework, module)
    except (AttributeError, OSError, RuntimeError) as error:
        return _capture_report(
            manifest,
            framework,
            "backend_unavailable",
            version,
            expected_prefix,
            [],
            [{"id": case.case_id, "reason": type(error).__name__} for case in manifest.cases],
        )
    captured = []
    failures = []
    for case, trace_path in zip(manifest.cases, paths):
        case_error = None
        try:
            with TraceRecorder(
                trace_path,
                framework=framework,
                framework_version=version,
                execution_mode=(
                    ExecutionMode.EAGER
                    if framework == Framework.PYTORCH
                    else ExecutionMode.PYNATIVE
                ),
                run_id=f"{manifest.benchmark_version}:{case.case_id}",
                overwrite=overwrite,
                source_root=Path(__file__).parents[2],
            ) as recorder:
                _run_case(case, backend, recorder)
        except Exception as error:  # the trace preserves the framework exception
            case_error = error
        expected_error = (
            framework == Framework.MINDSPORE
            and case.expected_category == DiagnosticCategory.MISSING_OPERATOR
        )
        try:
            records = load_trace_jsonl(trace_path, framework)
            actual = tuple(record.api for record in records)
            expected = tuple(
                operation.source_api
                if framework == Framework.PYTORCH
                else operation.target_api
                for operation in case.operations
            )
            if actual != expected:
                raise SchemaError(f"component case {case.case_id} emitted unexpected APIs")
            if case_error is not None and not expected_error:
                raise case_error
            if expected_error and (
                case_error is None
                or records[-1].error is None
                or records[-1].error.error_type != "NotImplementedError"
            ):
                raise SchemaError(
                    f"component case {case.case_id} did not emit its expected error"
                )
            captured.append(
                {
                    "id": case.case_id,
                    "split": case.split,
                    "call_count": len(records),
                    "expected_error": expected_error,
                }
            )
        except Exception as error:
            failures.append({"id": case.case_id, "reason": type(error).__name__})
    status = "captured" if not failures else "case_failure"
    return _capture_report(
        manifest,
        framework,
        status,
        version,
        expected_prefix,
        captured,
        failures,
    )


class _ManifestMappings:
    def __init__(self, manifest: ComponentManifest):
        self._pairs = {
            operation.source_api: operation.target_api
            for case in manifest.cases
            for operation in case.operations
        }

    def resolve(self, source_api: str):
        return SimpleNamespace(target_api=self._pairs.get(source_api))


def evaluate_benchmark(
    capture_root: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    root = Path(capture_root).resolve()
    mappings = _ManifestMappings(manifest)
    results = []
    categories = Counter()
    source_versions = set()
    target_versions = set()
    for case in manifest.cases:
        source_path = root / Framework.PYTORCH.value / f"{case.case_id}.jsonl"
        target_path = root / Framework.MINDSPORE.value / f"{case.case_id}.jsonl"
        missing = []
        if not source_path.is_file():
            missing.append(Framework.PYTORCH.value)
        if not target_path.is_file():
            missing.append(Framework.MINDSPORE.value)
        if missing:
            results.append(
                {
                    "id": case.case_id,
                    "split": case.split,
                    "status": "missing_capture",
                    "missing": missing,
                }
            )
            continue
        source = load_trace_jsonl(source_path, Framework.PYTORCH)
        target = load_trace_jsonl(target_path, Framework.MINDSPORE)
        source_versions.update(record.framework_version for record in source)
        target_versions.update(record.framework_version for record in target)
        comparison = compare_traces(
            source,
            target,
            mappings,
            manifest.relative_tolerance,
            manifest.absolute_tolerance,
        )
        category = (
            comparison.diagnostic.category
            if comparison.diagnostic is not None
            else None
        )
        source_call_index = (
            comparison.diagnostic.metadata.get("source_call_index")
            if comparison.diagnostic is not None
            else None
        )
        classification_correct = comparison.equivalent == case.expected_equivalent
        localization_correct = None
        if not case.expected_equivalent:
            localization_correct = (
                category == case.expected_category
                and source_call_index == case.expected_call_index
            )
        case_passed = classification_correct and localization_correct is not False
        if category is not None:
            categories[category.value] += 1
        results.append(
            {
                "id": case.case_id,
                "split": case.split,
                "capabilities": list(case.capabilities),
                "fault_injection": case.fault_injection,
                "status": "equivalent" if comparison.equivalent else "divergent",
                "expected_equivalent": case.expected_equivalent,
                "classification_correct": classification_correct,
                "expected_category": (
                    case.expected_category.value if case.expected_category else None
                ),
                "first_divergence_category": category.value if category else None,
                "expected_call_index": case.expected_call_index,
                "source_call_index": source_call_index,
                "localization_correct": localization_correct,
                "passed": case_passed,
                "source_duration_ms": _duration_total(source),
                "target_duration_ms": _duration_total(target),
            }
        )
    evaluated = [result for result in results if "classification_correct" in result]
    divergent = [
        result for result in evaluated if result["expected_equivalent"] is False
    ]
    equivalent_expected = [
        result for result in evaluated if result["expected_equivalent"] is True
    ]
    gradient = [
        result for result in evaluated if "gradient" in result["capabilities"]
    ]
    training_steps = [
        result
        for result in equivalent_expected
        if "training-step" in result["capabilities"]
    ]
    optimizer_defects = [
        result
        for result in divergent
        if "optimizer" in result["capabilities"]
    ]
    versions_match = bool(source_versions and target_versions) and all(
        _version_matches(version, manifest.source_version_prefix)
        for version in source_versions
    ) and all(
        _version_matches(version, manifest.target_version_prefix)
        for version in target_versions
    )
    complete = len(evaluated) == len(manifest.cases)
    report = {
        "schema_version": "1.0",
        "benchmark_version": manifest.benchmark_version,
        "dataset_kind": manifest.dataset_kind,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "case_count": len(manifest.cases),
        "evaluated_case_count": len(evaluated),
        "complete": complete,
        "passed": complete
        and versions_match
        and all(result["passed"] for result in evaluated),
        "classification_accuracy": _rate(
            evaluated, lambda result: result["classification_correct"]
        ),
        "first_divergence_top1_accuracy": _rate(
            divergent, lambda result: result["localization_correct"]
        ),
        "equivalent_component_parity_rate": _rate(
            equivalent_expected, lambda result: result["status"] == "equivalent"
        ),
        "gradient_parity_rate": _rate(
            gradient, lambda result: result["status"] == "equivalent"
        ),
        "training_step_parity_rate": _rate(
            training_steps, lambda result: result["status"] == "equivalent"
        ),
        "optimizer_defect_top1_accuracy": _rate(
            optimizer_defects, lambda result: result["localization_correct"]
        ),
        "splits": {
            split: _split_metrics(evaluated, split) for split in sorted(CASE_SPLITS)
        },
        "source_framework_versions": sorted(source_versions),
        "target_framework_versions": sorted(target_versions),
        "version_prefixes_match": versions_match,
        "first_divergence_categories": dict(sorted(categories.items())),
        "cases": results,
        "limitations": _limitations(manifest.dataset_kind),
    }
    return report


def _run_case(
    case: ComponentCase, backend: _ComponentBackend, recorder: TraceRecorder
) -> None:
    runners = {
        "mlp-forward": _run_mlp_forward,
        "cnn-forward": _run_cnn_forward,
        "input-weight-gradients": _run_gradients,
        "batchnorm-eval": _run_batchnorm_eval,
        "dtype-bool-regression": _run_dtype_regression,
        "batchnorm-default-mode": _run_batchnorm_default_mode,
        "missing-operator-injected": _run_missing_operator,
        "linear-sgd-step": _run_linear_sgd_step,
        "mlp-sgd-step": _run_mlp_sgd_step,
        "learning-rate-mismatch": _run_learning_rate_mismatch,
    }
    runners[case.case_id](case, backend, recorder)


def _run_mlp_forward(case, backend, recorder):
    first_weight = [[0.2, -0.1, 0.3, 0.5], [-0.4, 0.6, 0.1, -0.2], [0.7, 0.2, -0.5, 0.4]]
    first_bias = [0.1, -0.2, 0.05]
    second_weight = [[0.3, -0.6, 0.2], [-0.1, 0.4, 0.5]]
    second_bias = [0.2, -0.3]
    value = backend.tensor([[1.0, -2.0, 0.5, 3.0], [-1.0, 0.0, 2.0, 1.5]])
    if backend.framework == Framework.PYTORCH:
        first = backend.module.nn.Linear(4, 3, bias=True)
        second = backend.module.nn.Linear(3, 2, bias=True)
        with backend.module.no_grad():
            first.weight.copy_(backend.tensor(first_weight))
            first.bias.copy_(backend.tensor(first_bias))
            second.weight.copy_(backend.tensor(second_weight))
            second.bias.copy_(backend.tensor(second_bias))
        relu = backend.module.nn.functional.relu
    else:
        first = backend.module.nn.Dense(
            4,
            3,
            weight_init=backend.tensor(first_weight),
            bias_init=backend.tensor(first_bias),
            has_bias=True,
        )
        second = backend.module.nn.Dense(
            3,
            2,
            weight_init=backend.tensor(second_weight),
            bias_init=backend.tensor(second_bias),
            has_bias=True,
        )
        relu = backend.module.ops.relu
    value = backend.record(recorder, case, 0, first, value)
    value = backend.record(recorder, case, 1, relu, value)
    backend.record(recorder, case, 2, second, value)


def _run_cnn_forward(case, backend, recorder):
    weight = [
        [[[1.0, 0.0], [0.0, -1.0]]],
        [[[0.5, 0.5], [-0.5, -0.5]]],
    ]
    value = backend.tensor([[[[1.0, 2.0, 3.0], [0.0, 1.0, 2.0], [-1.0, 0.0, 1.0]]]])
    if backend.framework == Framework.PYTORCH:
        convolution = backend.module.nn.Conv2d(1, 2, 2, bias=False)
        with backend.module.no_grad():
            convolution.weight.copy_(backend.tensor(weight))
        relu = backend.module.nn.functional.relu
        flatten = backend.module.flatten
    else:
        convolution = backend.module.nn.Conv2d(
            1,
            2,
            2,
            pad_mode="valid",
            has_bias=False,
            weight_init=backend.tensor(weight),
        )
        relu = backend.module.ops.relu
        flatten = backend.module.ops.flatten
    value = backend.record(recorder, case, 0, convolution, value)
    value = backend.record(recorder, case, 1, relu, value)
    # PyTorch starts at dimension 0 while MindSpore keeps the batch dimension by
    # default, so an equivalent migration must make start_dim explicit.
    backend.record(recorder, case, 2, flatten, value, start_dim=0)


def _run_gradients(case, backend, recorder):
    value = [[1.0, -2.0], [0.5, 3.0]]
    weight = [[0.2, -0.4], [0.7, 0.3]]
    if backend.framework == Framework.PYTORCH:
        x = backend.tensor(value, requires_grad=True)
        w = backend.tensor(weight, requires_grad=True)

        def loss_function(left, right):
            return backend.module.sum(backend.module.relu(backend.module.matmul(left, right)))

        loss = backend.record(recorder, case, 0, loss_function, x, w)
        backend.record(
            recorder,
            case,
            1,
            lambda: backend.module.autograd.grad(loss, (x, w)),
        )
    else:
        x = backend.tensor(value)
        w = backend.tensor(weight)

        def loss_function(left, right):
            return backend.module.ops.sum(
                backend.module.ops.relu(backend.module.ops.matmul(left, right))
            )

        backend.record(recorder, case, 0, loss_function, x, w)
        gradient_function = backend.module.grad(loss_function, grad_position=(0, 1))
        backend.record(recorder, case, 1, gradient_function, x, w)


def _batchnorm(backend, *, evaluation: bool, affine: bool = True):
    if backend.framework == Framework.PYTORCH:
        layer = backend.module.nn.BatchNorm2d(
            2, eps=1e-5, momentum=0.1, affine=affine, track_running_stats=True
        )
        if affine:
            with backend.module.no_grad():
                layer.weight.copy_(backend.tensor([1.5, 0.5]))
                layer.bias.copy_(backend.tensor([0.2, -0.1]))
                layer.running_mean.copy_(backend.tensor([1.0, 2.0]))
                layer.running_var.copy_(backend.tensor([4.0, 9.0]))
        if evaluation:
            layer.eval()
        return layer
    options = {
        "eps": 1e-5,
        "momentum": 0.9,
        "affine": affine,
        "use_batch_statistics": None,
    }
    if affine:
        options.update(
            gamma_init=backend.tensor([1.5, 0.5]),
            beta_init=backend.tensor([0.2, -0.1]),
            moving_mean_init=backend.tensor([1.0, 2.0]),
            moving_var_init=backend.tensor([4.0, 9.0]),
        )
    layer = backend.module.nn.BatchNorm2d(2, **options)
    if evaluation:
        layer.set_train(False)
    return layer


def _run_batchnorm_eval(case, backend, recorder):
    value = backend.tensor([[[[1.0, 3.0], [5.0, 7.0]], [[2.0, 5.0], [8.0, 11.0]]]])
    backend.record(recorder, case, 0, _batchnorm(backend, evaluation=True), value)


def _run_dtype_regression(case, backend, recorder):
    left = backend.tensor([[1.0, -2.0], [0.0, 3.0]])
    right = backend.tensor([[0.5, 1.0], [2.0, -1.0]])
    if backend.framework == Framework.PYTORCH:
        function = backend.module.add
    else:
        function = lambda a, b: backend.module.ops.cast(
            backend.module.ops.add(a, b), backend.module.bool_
        )
    backend.record(recorder, case, 0, function, left, right)


def _run_batchnorm_default_mode(case, backend, recorder):
    value = backend.tensor(
        [
            [[[1.0, 2.0], [3.0, 4.0]], [[2.0, 4.0], [6.0, 8.0]]],
            [[[2.0, 3.0], [4.0, 5.0]], [[1.0, 3.0], [5.0, 7.0]]],
        ]
    )
    layer = _batchnorm(backend, evaluation=False, affine=False)
    backend.record(recorder, case, 0, layer, value)


def _run_missing_operator(case, backend, recorder):
    value = backend.tensor([-1.0, 0.0, 1.0])
    if backend.framework == Framework.PYTORCH:
        function = backend.module.sigmoid
    else:
        def function(_value):
            raise NotImplementedError("injected missing MindSpore operator")
    backend.record(recorder, case, 0, function, value)


def _run_linear_sgd_step(case, backend, recorder):
    _run_sgd_training_step(
        case, backend, recorder, model_kind="linear", learning_rate=0.1
    )


def _run_mlp_sgd_step(case, backend, recorder):
    _run_sgd_training_step(
        case, backend, recorder, model_kind="mlp", learning_rate=0.05
    )


def _run_learning_rate_mismatch(case, backend, recorder):
    learning_rate = 0.1 if backend.framework == Framework.PYTORCH else 0.2
    _run_sgd_training_step(
        case,
        backend,
        recorder,
        model_kind="linear",
        learning_rate=learning_rate,
    )


def _run_sgd_training_step(
    case,
    backend,
    recorder,
    *,
    model_kind: str,
    learning_rate: float,
):
    inputs = backend.tensor([[1.0, -2.0], [0.5, 3.0]])
    targets = backend.tensor([[0.5], [-1.0]])
    model = _training_model(backend, model_kind)

    if backend.framework == Framework.PYTORCH:
        loss_function = backend.module.nn.functional.mse_loss
        optimizer = backend.module.optim.SGD(model.parameters(), lr=learning_rate)
        predictions = backend.record(recorder, case, 0, model, inputs)
        loss = backend.record(recorder, case, 1, loss_function, predictions, targets)

        def compute_gradients():
            return backend.module.autograd.grad(loss, tuple(model.parameters()))

        gradients = backend.record(recorder, case, 2, compute_gradients)

        def optimizer_step():
            for parameter, gradient in zip(model.parameters(), gradients):
                parameter.grad = gradient.detach().clone()
            optimizer.step()
            return tuple(parameter.detach().clone() for parameter in model.parameters())

        backend.record(recorder, case, 3, optimizer_step)
        return

    loss_function = backend.module.ops.mse_loss
    weights = model.trainable_params()
    optimizer = backend.module.nn.SGD(weights, learning_rate=learning_rate)
    predictions = backend.record(recorder, case, 0, model, inputs)
    backend.record(recorder, case, 1, loss_function, predictions, targets)

    def training_loss(data, labels):
        return loss_function(model(data), labels)

    gradient_function = backend.module.value_and_grad(
        training_loss,
        grad_position=None,
        weights=weights,
    )

    def compute_gradients():
        _, gradients = gradient_function(inputs, targets)
        return gradients

    gradients = backend.record(recorder, case, 2, compute_gradients)

    def optimizer_step():
        optimizer(gradients)
        return tuple(weights)

    backend.record(recorder, case, 3, optimizer_step)


def _training_model(backend, model_kind):
    if model_kind == "linear":
        weight = [[0.2, -0.4]]
        bias = [0.1]
        if backend.framework == Framework.PYTORCH:
            layer = backend.module.nn.Linear(2, 1, bias=True)
            with backend.module.no_grad():
                layer.weight.copy_(backend.tensor(weight))
                layer.bias.copy_(backend.tensor(bias))
            return layer
        return backend.module.nn.Dense(
            2,
            1,
            weight_init=backend.tensor(weight),
            bias_init=backend.tensor(bias),
            has_bias=True,
        )
    if model_kind != "mlp":
        raise ValueError(f"unsupported training model: {model_kind}")
    first_weight = [[0.2, -0.4], [0.1, 0.3], [-0.5, 0.2]]
    first_bias = [0.1, -0.2, 0.05]
    second_weight = [[0.3, -0.6, 0.2]]
    second_bias = [0.2]
    if backend.framework == Framework.PYTORCH:
        first = backend.module.nn.Linear(2, 3, bias=True)
        second = backend.module.nn.Linear(3, 1, bias=True)
        with backend.module.no_grad():
            first.weight.copy_(backend.tensor(first_weight))
            first.bias.copy_(backend.tensor(first_bias))
            second.weight.copy_(backend.tensor(second_weight))
            second.bias.copy_(backend.tensor(second_bias))
        return backend.module.nn.Sequential(first, backend.module.nn.ReLU(), second)
    return backend.module.nn.SequentialCell(
        backend.module.nn.Dense(
            2,
            3,
            weight_init=backend.tensor(first_weight),
            bias_init=backend.tensor(first_bias),
            has_bias=True,
        ),
        backend.module.nn.ReLU(),
        backend.module.nn.Dense(
            3,
            1,
            weight_init=backend.tensor(second_weight),
            bias_init=backend.tensor(second_bias),
            has_bias=True,
        ),
    )


def _capture_report(
    manifest,
    framework,
    status,
    version,
    expected_prefix,
    captured,
    failures,
):
    return {
        "schema_version": "1.0",
        "benchmark_version": manifest.benchmark_version,
        "record_kind": (
            "training_capture_report"
            if manifest.dataset_kind == TRAINING_DATASET_KIND
            else "component_capture_report"
        ),
        "framework": framework.value,
        "framework_version": version,
        "expected_version_prefix": expected_prefix,
        "version_compatible": bool(version and _version_matches(version, expected_prefix)),
        "status": status,
        "python_version": platform.python_version(),
        "case_count": len(manifest.cases),
        "captured_case_count": len(captured),
        "captured": captured,
        "failures": failures,
    }


def _limitations(dataset_kind):
    shared = [
        "Tensor previews are exact only for the captured prefix; "
        "large tensors also use summaries.",
        "Passing cases does not prove end-to-end migration correctness.",
    ]
    if dataset_kind == TRAINING_DATASET_KIND:
        return [
            "The suite executes one deterministic CPU optimizer step on small models.",
            "The held-out optimizer defect is a frozen learning-rate fault injection.",
            "It does not cover optimizer state restoration, mixed precision, "
            "distributed training, or convergence.",
            *shared,
        ]
    return [
        "The suite uses small deterministic components rather than full migrated projects.",
        "Held-out defects are frozen fault injections and default-mode mismatches.",
        *shared,
    ]


def _split_metrics(results, split):
    selected = [result for result in results if result["split"] == split]
    divergent = [result for result in selected if not result["expected_equivalent"]]
    return {
        "case_count": len(selected),
        "classification_accuracy": _rate(
            selected, lambda result: result["classification_correct"]
        ),
        "first_divergence_top1_accuracy": _rate(
            divergent, lambda result: result["localization_correct"]
        ),
        "passed_case_rate": _rate(selected, lambda result: result["passed"]),
    }


def _rate(values, predicate):
    return sum(bool(predicate(value)) for value in values) / len(values) if values else None


def _duration_total(records):
    return round(
        sum(float(record.metadata.get("duration_ms", 0.0)) for record in records), 6
    )


def _required_string(value: dict[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise SchemaError(f"component parity requires {name}")
    return item.strip()


def _non_negative_number(value: dict[str, Any], name: str) -> float:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0:
        raise SchemaError(f"component parity {name} must be a non-negative number")
    return float(item)


def _version_matches(version: str, expected_prefix: str) -> bool:
    release = version.split("+", 1)[0]
    return release == expected_prefix or release.startswith(f"{expected_prefix}.")


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("framework", choices=["pytorch", "mindspore"])
    capture.add_argument("output_dir")
    capture.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    capture.add_argument("--force", action="store_true")
    capture.add_argument("--allow-version-mismatch", action="store_true")
    capture.add_argument("--pretty", action="store_true")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("capture_root")
    evaluate.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    evaluate.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "capture":
            result = capture_framework(
                arguments.framework,
                arguments.output_dir,
                arguments.manifest,
                overwrite=arguments.force,
                allow_version_mismatch=arguments.allow_version_mismatch,
            )
            passed = result["status"] == "captured"
        else:
            result = evaluate_benchmark(arguments.capture_root, arguments.manifest)
            passed = result["passed"]
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
