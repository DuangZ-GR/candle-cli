"""Capture and diagnose PyTorch/MindSpore data-pipeline and randomness parity."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.schema import DiagnosticCategory, Framework, SchemaError

SCHEMA_VERSION = "1.0"
BENCHMARK_VERSION = "data-pipeline-randomness-v1"
DATASET_KIND = "cross_framework_data_pipeline_cases"
CASE_SPLITS = {"development", "heldout"}
COMPARISON_KINDS = {"deterministic", "fixed_seed", "statistical"}
DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "data_pipeline_randomness_v1.json"
)


@dataclass(frozen=True)
class PipelineCase:
    case_id: str
    split: str
    capabilities: tuple[str, ...]
    comparison_kind: str
    expected_equivalent: bool
    expected_category: DiagnosticCategory | None
    fault_injection: bool
    thresholds: dict[str, float | int | bool]


@dataclass(frozen=True)
class PipelineManifest:
    benchmark_version: str
    source_version_prefix: str
    target_version_prefix: str
    cases: tuple[PipelineCase, ...]


# Ordered comparison rules are deliberately code-owned so changing a frozen case
# requires a reviewed code and manifest change instead of arbitrary execution data.
CASE_DEFINITIONS: dict[str, tuple[str, bool, str | None]] = {
    "tensor-dataset-order": ("deterministic", False, None),
    "dataloader-tail-batch": ("deterministic", False, None),
    "normalize-float-range": ("deterministic", False, None),
    "resize-layout-preserved": ("deterministic", False, None),
    "to-tensor-scale-layout": ("deterministic", False, None),
    "classification-label-semantics": ("deterministic", False, None),
    "boolean-mask-semantics": ("deterministic", False, None),
    "layout-hwc-injected": ("deterministic", True, "layout_mismatch"),
    "tensor-bool-injected": ("deterministic", True, "dtype_mismatch"),
    "normalization-scale-injected": (
        "deterministic",
        True,
        "normalization_mismatch",
    ),
    "label-float-injected": ("deterministic", True, "label_dtype_mismatch"),
    "mask-int-injected": ("deterministic", True, "mask_dtype_mismatch"),
    "drop-last-injected": ("deterministic", True, "batching_mismatch"),
    "resize-default-injected": ("deterministic", True, "transform_mismatch"),
    "fixed-seed-reset-injected": (
        "fixed_seed",
        True,
        "reproducibility_mismatch",
    ),
    "dropout-statistical": ("statistical", False, None),
    "uniform-sampler-statistical": ("statistical", False, None),
    "normal-initializer-statistical": ("statistical", False, None),
}


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> PipelineManifest:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("unsupported data-pipeline schema_version")
    if document.get("benchmark_version") != BENCHMARK_VERSION:
        raise SchemaError("unsupported data-pipeline benchmark_version")
    if document.get("dataset_kind") != DATASET_KIND:
        raise SchemaError("unsupported data-pipeline dataset_kind")
    source = document.get("source_framework")
    target = document.get("target_framework")
    if not isinstance(source, dict) or source.get("name") != "pytorch":
        raise SchemaError("data-pipeline source framework must be pytorch")
    if not isinstance(target, dict) or target.get("name") != "mindspore":
        raise SchemaError("data-pipeline target framework must be mindspore")
    source_prefix = _required_string(source, "version_prefix")
    target_prefix = _required_string(target, "version_prefix")
    values = document.get("cases")
    if not isinstance(values, list) or not values:
        raise SchemaError("data-pipeline manifest requires cases")

    cases: list[PipelineCase] = []
    identifiers: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise SchemaError("data-pipeline case must be an object")
        case_id = _required_string(value, "id")
        if case_id in identifiers:
            raise SchemaError("data-pipeline case ids must be unique")
        definition = CASE_DEFINITIONS.get(case_id)
        if definition is None:
            raise SchemaError(f"unknown built-in data-pipeline case: {case_id}")
        split = _required_string(value, "split")
        if split not in CASE_SPLITS:
            raise SchemaError(f"data-pipeline case {case_id} has invalid split")
        capabilities = value.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities or any(
            not isinstance(item, str) or not item.strip() for item in capabilities
        ):
            raise SchemaError(f"data-pipeline case {case_id} requires capabilities")
        comparison_kind = _required_string(value, "comparison_kind")
        if comparison_kind not in COMPARISON_KINDS:
            raise SchemaError(f"data-pipeline case {case_id} has invalid comparison_kind")
        expected_equivalent = value.get("expected_equivalent")
        fault_injection = value.get("fault_injection", False)
        if not isinstance(expected_equivalent, bool) or not isinstance(
            fault_injection, bool
        ):
            raise SchemaError(f"data-pipeline case {case_id} has invalid expectations")
        category_value = value.get("expected_category")
        category = (
            DiagnosticCategory.parse(category_value)
            if isinstance(category_value, str)
            else None
        )
        expected_kind, expected_fault, expected_category = definition
        normalized_category = category.value if category is not None else None
        if (
            comparison_kind,
            fault_injection,
            normalized_category,
        ) != (expected_kind, expected_fault, expected_category):
            raise SchemaError(f"data-pipeline case {case_id} does not match built-in case")
        if expected_equivalent == fault_injection:
            raise SchemaError(f"data-pipeline case {case_id} has inconsistent equivalence")
        thresholds = value.get("thresholds", {})
        if not isinstance(thresholds, dict):
            raise SchemaError(f"data-pipeline case {case_id} thresholds must be an object")
        normalized_thresholds: dict[str, float | int | bool] = {}
        for name, threshold in thresholds.items():
            if not isinstance(name, str) or not isinstance(
                threshold, (int, float, bool)
            ):
                raise SchemaError(f"data-pipeline case {case_id} has invalid threshold")
            if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
                if not math.isfinite(float(threshold)) or float(threshold) < 0:
                    raise SchemaError(
                        f"data-pipeline case {case_id} threshold must be non-negative"
                    )
            normalized_thresholds[name] = threshold
        if comparison_kind in {"fixed_seed", "statistical"} and not thresholds:
            raise SchemaError(f"random case {case_id} requires thresholds")
        identifiers.add(case_id)
        cases.append(
            PipelineCase(
                case_id=case_id,
                split=split,
                capabilities=tuple(item.strip() for item in capabilities),
                comparison_kind=comparison_kind,
                expected_equivalent=expected_equivalent,
                expected_category=category,
                fault_injection=fault_injection,
                thresholds=normalized_thresholds,
            )
        )
    if identifiers != set(CASE_DEFINITIONS):
        raise SchemaError("data-pipeline manifest must contain every built-in case once")
    return PipelineManifest(
        BENCHMARK_VERSION, source_prefix, target_prefix, tuple(cases)
    )


def capture_framework(
    framework: Framework | str,
    output: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    *,
    overwrite: bool = False,
    allow_version_mismatch: bool = False,
) -> dict[str, Any]:
    framework = Framework.parse(framework) if isinstance(framework, str) else framework
    if framework not in {Framework.PYTORCH, Framework.MINDSPORE}:
        raise ValueError("data-pipeline framework must be pytorch or mindspore")
    manifest = load_manifest(manifest_path)
    module_name = "torch" if framework == Framework.PYTORCH else "mindspore"
    module = importlib.import_module(module_name)
    np = importlib.import_module("numpy")
    framework_version = str(module.__version__)
    expected_prefix = (
        manifest.source_version_prefix
        if framework == Framework.PYTORCH
        else manifest.target_version_prefix
    )
    if not allow_version_mismatch and not framework_version.startswith(expected_prefix):
        raise RuntimeError(
            f"{framework.value} version {framework_version} does not match "
            f"required prefix {expected_prefix}"
        )
    observations = [
        _capture_case(case, framework, module, np) for case in manifest.cases
    ]
    document = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "data_pipeline_capture",
        "benchmark_version": manifest.benchmark_version,
        "framework": framework.value,
        "framework_version": framework_version,
        "case_count": len(observations),
        "observations": observations,
    }
    destination = Path(output).resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"capture already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "captured",
        "framework": framework.value,
        "framework_version": framework_version,
        "captured_case_count": len(observations),
        "output": str(destination),
    }


def evaluate_benchmark(
    source_capture: str | Path,
    target_capture: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    source = _load_capture(source_capture, Framework.PYTORCH, manifest)
    target = _load_capture(target_capture, Framework.MINDSPORE, manifest)
    source_by_id = {item["case_id"]: item for item in source["observations"]}
    target_by_id = {item["case_id"]: item for item in target["observations"]}
    results = []
    classification_correct = 0
    fault_top1_correct = 0
    deterministic_equivalent_passes = 0
    deterministic_equivalent_total = 0
    statistical_passes = 0
    statistical_total = 0
    stochastic_sample_sizes = []
    categories: Counter[str] = Counter()
    split_counts: dict[str, Counter[str]] = {
        split: Counter(total=0, passed=0) for split in CASE_SPLITS
    }

    for case in manifest.cases:
        source_observation = source_by_id.get(case.case_id)
        target_observation = target_by_id.get(case.case_id)
        if source_observation is None or target_observation is None:
            result = {
                "case_id": case.case_id,
                "split": case.split,
                "comparison_kind": case.comparison_kind,
                "status": "missing_capture",
                "passed": False,
                "expected_equivalent": case.expected_equivalent,
                "observed_equivalent": None,
                "expected_category": _category_value(case.expected_category),
                "observed_category": None,
                "sample_size": None,
                "statistics": None,
                "thresholds": case.thresholds,
                "elementwise_compared": False,
            }
        else:
            comparison = _compare_case(case, source_observation, target_observation)
            observed_equivalent = comparison["equivalent"]
            observed_category = comparison["category"]
            passed = observed_equivalent == case.expected_equivalent and (
                observed_category == _category_value(case.expected_category)
            )
            classification_correct += int(passed)
            if case.fault_injection:
                fault_top1_correct += int(
                    observed_category == _category_value(case.expected_category)
                )
                if observed_category:
                    categories[observed_category] += 1
            if case.comparison_kind == "deterministic" and case.expected_equivalent:
                deterministic_equivalent_total += 1
                deterministic_equivalent_passes += int(observed_equivalent)
            if case.comparison_kind == "statistical":
                statistical_total += 1
                statistical_passes += int(observed_equivalent)
            if case.comparison_kind in {"fixed_seed", "statistical"}:
                stochastic_sample_sizes.append(comparison["sample_size"])
            result = {
                "case_id": case.case_id,
                "split": case.split,
                "comparison_kind": case.comparison_kind,
                "status": "evaluated",
                "passed": passed,
                "expected_equivalent": case.expected_equivalent,
                "observed_equivalent": observed_equivalent,
                "expected_category": _category_value(case.expected_category),
                "observed_category": observed_category,
                "first_difference": comparison["first_difference"],
                "sample_size": comparison["sample_size"],
                "statistics": comparison["statistics"],
                "thresholds": case.thresholds,
                "elementwise_compared": False,
            }
        split_counts[case.split]["total"] += 1
        split_counts[case.split]["passed"] += int(result["passed"])
        results.append(result)

    total = len(manifest.cases)
    fault_total = sum(case.fault_injection for case in manifest.cases)
    complete = all(result["status"] == "evaluated" for result in results)
    classification_accuracy = _rate(classification_correct, total)
    fault_accuracy = _rate(fault_top1_correct, fault_total)
    report = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "data_pipeline_diagnostic_report",
        "benchmark_version": manifest.benchmark_version,
        "dataset_kind": DATASET_KIND,
        "complete": complete,
        "passed": complete
        and classification_accuracy >= 0.8
        and fault_accuracy >= 0.8
        and deterministic_equivalent_passes == deterministic_equivalent_total
        and statistical_passes == statistical_total,
        "case_count": total,
        "evaluated_case_count": sum(result["status"] == "evaluated" for result in results),
        "fault_case_count": fault_total,
        "stochastic_case_count": len(stochastic_sample_sizes),
        "minimum_stochastic_sample_size": min(stochastic_sample_sizes)
        if stochastic_sample_sizes
        else None,
        "classification_accuracy": classification_accuracy,
        "first_divergence_top1_accuracy": fault_accuracy,
        "deterministic_equivalence_rate": _rate(
            deterministic_equivalent_passes, deterministic_equivalent_total
        ),
        "statistical_equivalence_rate": _rate(statistical_passes, statistical_total),
        "first_divergence_categories": dict(sorted(categories.items())),
        "source_framework_version": source["framework_version"],
        "target_framework_version": target["framework_version"],
        "splits": {
            split: {
                "case_count": counts["total"],
                "passed_case_rate": _rate(counts["passed"], counts["total"]),
            }
            for split, counts in sorted(split_counts.items())
        },
        "cases": results,
    }
    validate_report(report)
    return report


def validate_report(report: dict[str, Any]) -> None:
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported data-pipeline report schema_version")
    if report.get("record_kind") != "data_pipeline_diagnostic_report":
        raise ValueError("invalid data-pipeline report record_kind")
    if report.get("benchmark_version") != BENCHMARK_VERSION:
        raise ValueError("invalid data-pipeline report benchmark_version")
    case_count = report.get("case_count")
    cases = report.get("cases")
    if not isinstance(case_count, int) or not isinstance(cases, list):
        raise ValueError("data-pipeline report requires cases")
    if case_count != len(cases) or case_count < 12:
        raise ValueError("data-pipeline report case count is invalid")
    if report.get("fault_case_count", 0) < 5:
        raise ValueError("data-pipeline report requires at least five fault cases")
    for name in (
        "classification_accuracy",
        "first_divergence_top1_accuracy",
        "deterministic_equivalence_rate",
        "statistical_equivalence_rate",
    ):
        value = report.get(name)
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"data-pipeline report {name} must be between zero and one")
    for case in cases:
        if case.get("comparison_kind") in {"fixed_seed", "statistical"}:
            if not isinstance(case.get("sample_size"), int) or case["sample_size"] <= 0:
                raise ValueError("random data-pipeline case requires sample_size")
            if not isinstance(case.get("statistics"), dict) or not isinstance(
                case.get("thresholds"), dict
            ):
                raise ValueError("random data-pipeline case requires statistics and thresholds")
            if case.get("elementwise_compared") is not False:
                raise ValueError("random data-pipeline cases must not use elementwise equality")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Data Pipeline and Randomness Diagnostics",
        "",
        f"- Benchmark: `{report['benchmark_version']}`",
        f"- Complete/passed: `{report['complete']}/{report['passed']}`",
        f"- Frameworks: `{report['source_framework_version']}` / `{report['target_framework_version']}`",
        f"- Cases/faults/stochastic: `{report['case_count']}/{report['fault_case_count']}/{report['stochastic_case_count']}`",
        f"- Classification accuracy: `{report['classification_accuracy']:.2%}`",
        f"- First-divergence Top-1: `{report['first_divergence_top1_accuracy']:.2%}`",
        f"- Deterministic equivalence: `{report['deterministic_equivalence_rate']:.2%}`",
        f"- Statistical equivalence: `{report['statistical_equivalence_rate']:.2%}`",
        f"- Minimum stochastic sample size: `{report['minimum_stochastic_sample_size']}`",
        "",
        "| Case | Kind | Expected | Observed | Category | Passed |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            f"| `{case['case_id']}` | `{case['comparison_kind']}` | "
            f"`{case['expected_equivalent']}` | `{case['observed_equivalent']}` | "
            f"`{case['observed_category'] or 'none'}` | `{case['passed']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def _capture_case(
    case: PipelineCase, framework: Framework, module: Any, np: Any
) -> dict[str, Any]:
    observation = _empty_observation(case, framework)
    case_id = case.case_id
    if case_id in {
        "tensor-dataset-order",
        "dataloader-tail-batch",
        "classification-label-semantics",
        "label-float-injected",
        "drop-last-injected",
    }:
        target_fault = framework == Framework.MINDSPORE and case.fault_injection
        labels_float = case_id == "label-float-injected" and target_fault
        drop_last = case_id == "drop-last-injected" and target_fault
        batches = _capture_batches(framework, module, np, drop_last, labels_float)
        observation.update(batches)
        if case_id == "tensor-dataset-order":
            observation["tensor"] = batches["first_tensor"]
        return observation
    if case_id in {"boolean-mask-semantics", "mask-int-injected"}:
        values = np.asarray([[True, False], [False, True]])
        if framework == Framework.MINDSPORE and case_id == "mask-int-injected":
            values = values.astype(np.int32)
        tensor = _framework_tensor(framework, module, values)
        observation["mask"] = {
            "dtype": _normalized_dtype(_to_numpy(tensor)),
            "semantics": "boolean_selector",
        }
        observation["tensor"] = _tensor_summary(_to_numpy(tensor), "HW")
        return observation
    if case_id in {"layout-hwc-injected", "tensor-bool-injected"}:
        image = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
        layout = "HWC"
        values = image
        if framework == Framework.PYTORCH or case_id == "tensor-bool-injected":
            values = image.transpose(2, 0, 1)
            layout = "CHW"
        if framework == Framework.MINDSPORE and case_id == "tensor-bool-injected":
            values = values.astype(np.bool_)
        tensor = _framework_tensor(framework, module, values)
        observation["tensor"] = _tensor_summary(_to_numpy(tensor), layout)
        return observation
    if case_id in {
        "to-tensor-scale-layout",
        "normalization-scale-injected",
    }:
        image = np.asarray(
            [[[0], [64]], [[128], [255]]], dtype=np.uint8
        )
        if framework == Framework.PYTORCH:
            transforms = importlib.import_module("torchvision.transforms")
            output = transforms.ToTensor()(image)
        else:
            vision = importlib.import_module("mindspore.dataset.vision")
            if case_id == "normalization-scale-injected":
                output = image.transpose(2, 0, 1).astype(np.float32)
            else:
                output = vision.ToTensor()(image)
        observation["tensor"] = _tensor_summary(_to_numpy(output), "CHW")
        observation["transform"] = {
            "name": "ToTensor",
            "parameters": {"scale": case_id != "normalization-scale-injected" or framework == Framework.PYTORCH},
        }
        return observation
    if case_id == "normalize-float-range":
        values = np.asarray([[[0.0, 0.25], [0.5, 1.0]]], dtype=np.float32)
        if framework == Framework.PYTORCH:
            transforms = importlib.import_module("torchvision.transforms")
            output = transforms.Normalize([0.5], [0.25])(
                module.tensor(values, dtype=module.float32)
            )
        else:
            vision = importlib.import_module("mindspore.dataset.vision")
            output = vision.Normalize([0.5], [0.25], is_hwc=False)(values)
        observation["tensor"] = _tensor_summary(_to_numpy(output), "CHW")
        observation["transform"] = {
            "name": "Normalize",
            "parameters": {"mean": [0.5], "std": [0.25]},
        }
        return observation
    if case_id in {"resize-layout-preserved", "resize-default-injected"}:
        image = np.arange(16, dtype=np.uint8).reshape(4, 4, 1)
        target_fault = framework == Framework.MINDSPORE and case_id == "resize-default-injected"
        interpolation = "nearest" if target_fault else "bilinear"
        if framework == Framework.PYTORCH:
            transforms = importlib.import_module("torchvision.transforms")
            interpolation_mode = importlib.import_module(
                "torchvision.transforms.functional"
            ).InterpolationMode
            tensor = transforms.ToTensor()(image)
            output = transforms.Resize(
                (2, 2),
                interpolation=interpolation_mode.BILINEAR,
                antialias=True,
            )(tensor)
        else:
            vision = importlib.import_module("mindspore.dataset.vision")
            interpolation_mode = importlib.import_module(
                "mindspore.dataset.vision.utils"
            ).Inter
            mode = interpolation_mode.NEAREST if target_fault else interpolation_mode.LINEAR
            output = vision.Resize((2, 2), interpolation=mode)(image)
            output = np.asarray(output).transpose(2, 0, 1).astype(np.float32) / 255.0
        observation["tensor"] = _tensor_summary(_to_numpy(output), "CHW")
        observation["transform"] = {
            "name": "Resize",
            "parameters": {"size": [2, 2], "interpolation": interpolation},
        }
        return observation
    if case_id == "fixed-seed-reset-injected":
        seed = 20250315
        first = _random_uniform(framework, module, seed, 128, reset=True)
        reset_second = not (framework == Framework.MINDSPORE and case.fault_injection)
        second = _random_uniform(framework, module, seed, 128, reset=reset_second)
        observation["randomness"] = _random_summary(
            np, first, seed, _arrays_equal(np, first, second)
        )
        return observation
    if case_id == "dropout-statistical":
        seed = 20250316
        values = _dropout_values(framework, module, seed, 4096)
        observation["randomness"] = _random_summary(np, values, seed, True)
        return observation
    if case_id == "uniform-sampler-statistical":
        seed = 20250317
        values = _random_integers(framework, module, seed, 4096, 4)
        summary = _random_summary(np, values, seed, True)
        array = np.asarray(values).reshape(-1)
        summary["statistics"].update(
            {
                f"frequency_{index}": float((array == index).mean())
                for index in range(4)
            }
        )
        observation["randomness"] = summary
        return observation
    if case_id == "normal-initializer-statistical":
        seed = 20250318
        values = _random_normal(framework, module, seed, 4096)
        observation["randomness"] = _random_summary(np, values, seed, True)
        return observation
    raise AssertionError(f"unimplemented data-pipeline case: {case_id}")


def _capture_batches(
    framework: Framework, module: Any, np: Any, drop_last: bool, labels_float: bool
) -> dict[str, Any]:
    features = np.arange(10, dtype=np.float32).reshape(5, 2)
    labels = np.asarray([0, 1, 2, 1, 0], dtype=np.float32 if labels_float else np.int64)
    batch_sizes: list[int] = []
    first_features = None
    first_labels = None
    if framework == Framework.PYTORCH:
        data = importlib.import_module("torch.utils.data")
        dataset = data.TensorDataset(module.tensor(features), module.tensor(labels))
        loader = data.DataLoader(dataset, batch_size=2, shuffle=False, drop_last=drop_last)
        for batch_features, batch_labels in loader:
            feature_array = _to_numpy(batch_features)
            label_array = _to_numpy(batch_labels)
            batch_sizes.append(int(feature_array.shape[0]))
            if first_features is None:
                first_features, first_labels = feature_array, label_array
    else:
        dataset_module = importlib.import_module("mindspore.dataset")
        dataset = dataset_module.NumpySlicesDataset(
            (features, labels), column_names=["features", "labels"], shuffle=False
        ).batch(2, drop_remainder=drop_last)
        for row in dataset.create_dict_iterator(output_numpy=True):
            feature_array, label_array = row["features"], row["labels"]
            batch_sizes.append(int(feature_array.shape[0]))
            if first_features is None:
                first_features, first_labels = feature_array, label_array
    assert first_features is not None and first_labels is not None
    return {
        "sample_count": int(sum(batch_sizes)),
        "batch_count": len(batch_sizes),
        "batch_sizes": batch_sizes,
        "first_tensor": _tensor_summary(first_features, "NC"),
        "labels": {
            "dtype": _normalized_dtype(first_labels),
            "semantics": "classification_index",
        },
    }


def _compare_case(
    case: PipelineCase, source: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any]:
    if case.comparison_kind == "statistical":
        return _compare_statistical(case, source, target)
    random_source = source.get("randomness") or {}
    random_target = target.get("randomness") or {}
    if case.comparison_kind == "fixed_seed":
        sample_size = min(
            int(random_source.get("sample_size", 0)),
            int(random_target.get("sample_size", 0)),
        )
        required = bool(case.thresholds.get("reproducible_required", True))
        source_reproducible = bool(random_source.get("reproducible"))
        target_reproducible = bool(random_target.get("reproducible"))
        equivalent = source_reproducible == target_reproducible == required
        return {
            "equivalent": equivalent,
            "category": None if equivalent else "reproducibility_mismatch",
            "first_difference": None if equivalent else "randomness.reproducible",
            "sample_size": sample_size,
            "statistics": {
                "source": random_source.get("statistics", {}),
                "target": random_target.get("statistics", {}),
                "source_reproducible": source_reproducible,
                "target_reproducible": target_reproducible,
            },
        }
    rules: list[tuple[str, str]] = [("tensor.layout", "layout_mismatch")]
    if case.case_id in {"boolean-mask-semantics", "mask-int-injected"}:
        rules.extend(
            [
                ("mask.dtype", "mask_dtype_mismatch"),
                ("mask.semantics", "label_semantics_mismatch"),
                ("tensor.shape", "shape_mismatch"),
            ]
        )
    else:
        rules.extend(
            [
                ("tensor.dtype", "dtype_mismatch"),
                ("tensor.shape", "shape_mismatch"),
            ]
        )
    if case.case_id in {
        "normalize-float-range",
        "to-tensor-scale-layout",
        "normalization-scale-injected",
    }:
        rules.extend(
            [
                ("tensor.min", "normalization_mismatch"),
                ("tensor.max", "normalization_mismatch"),
            ]
        )
    rules.extend(
        [
        ("labels.dtype", "label_dtype_mismatch"),
        ("labels.semantics", "label_semantics_mismatch"),
        ("batch_sizes", "batching_mismatch"),
        ("transform.name", "transform_mismatch"),
        ("transform.parameters", "transform_mismatch"),
        ]
    )
    for path, category in rules:
        source_value = _nested(source, path)
        target_value = _nested(target, path)
        if source_value is None and target_value is None:
            continue
        if isinstance(source_value, float) and isinstance(target_value, float):
            equal = math.isclose(
                source_value,
                target_value,
                abs_tol=float(case.thresholds.get("absolute_tolerance", 1e-5)),
                rel_tol=0.0,
            )
        else:
            equal = source_value == target_value
        if not equal:
            return {
                "equivalent": False,
                "category": category,
                "first_difference": path,
                "sample_size": None,
                "statistics": None,
            }
    return {
        "equivalent": True,
        "category": None,
        "first_difference": None,
        "sample_size": None,
        "statistics": None,
    }


def _compare_statistical(
    case: PipelineCase, source: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any]:
    source_random = source.get("randomness") or {}
    target_random = target.get("randomness") or {}
    source_stats = source_random.get("statistics") or {}
    target_stats = target_random.get("statistics") or {}
    sample_size = min(
        int(source_random.get("sample_size", 0)),
        int(target_random.get("sample_size", 0)),
    )
    minimum = int(case.thresholds.get("minimum_sample_size", 1))
    differences: dict[str, float] = {}
    failures = []
    for name in sorted(set(source_stats) & set(target_stats)):
        source_value = source_stats[name]
        target_value = target_stats[name]
        if not isinstance(source_value, (int, float)) or not isinstance(
            target_value, (int, float)
        ):
            continue
        difference = abs(float(source_value) - float(target_value))
        differences[name] = round(difference, 8)
        if name.startswith("frequency_") or name == "zero_fraction":
            threshold = float(case.thresholds.get("max_probability_delta", 0.05))
        elif name == "stddev":
            threshold = float(case.thresholds.get("max_stddev_delta", 0.08))
        else:
            threshold = float(case.thresholds.get("max_mean_delta", 0.08))
        if difference > threshold:
            failures.append(name)
    if sample_size < minimum:
        failures.insert(0, "sample_size")
    equivalent = not failures
    return {
        "equivalent": equivalent,
        "category": None if equivalent else "random_distribution_mismatch",
        "first_difference": None if equivalent else f"randomness.{failures[0]}",
        "sample_size": sample_size,
        "statistics": {
            "source": source_stats,
            "target": target_stats,
            "absolute_differences": differences,
            "source_sequence_digest": source_random.get("sequence_digest"),
            "target_sequence_digest": target_random.get("sequence_digest"),
            "sequence_equal": source_random.get("sequence_digest")
            == target_random.get("sequence_digest"),
        },
    }


def _load_capture(
    path: str | Path, framework: Framework, manifest: PipelineManifest
) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported data-pipeline capture schema_version")
    if document.get("record_kind") != "data_pipeline_capture":
        raise ValueError("invalid data-pipeline capture record_kind")
    if document.get("benchmark_version") != manifest.benchmark_version:
        raise ValueError("data-pipeline capture benchmark mismatch")
    if document.get("framework") != framework.value:
        raise ValueError("data-pipeline capture framework mismatch")
    observations = document.get("observations")
    if not isinstance(observations, list):
        raise ValueError("data-pipeline capture requires observations")
    identifiers = [item.get("case_id") for item in observations if isinstance(item, dict)]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("data-pipeline observation ids must be unique")
    return document


def _empty_observation(case: PipelineCase, framework: Framework) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "framework": framework.value,
        "comparison_kind": case.comparison_kind,
        "sample_count": None,
        "batch_count": None,
        "batch_sizes": None,
        "tensor": None,
        "labels": None,
        "mask": None,
        "transform": None,
        "randomness": None,
    }


def _framework_tensor(framework: Framework, module: Any, values: Any) -> Any:
    if framework == Framework.PYTORCH:
        return module.from_numpy(values)
    return module.Tensor(values)


def _to_numpy(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    if hasattr(value, "asnumpy"):
        return value.asnumpy()
    return value


def _tensor_summary(values: Any, layout: str) -> dict[str, Any]:
    array = values if hasattr(values, "shape") else importlib.import_module("numpy").asarray(values)
    flattened = array.reshape(-1)
    return {
        "layout": layout,
        "dtype": _normalized_dtype(array),
        "shape": [int(item) for item in array.shape],
        "min": round(float(flattened.min()), 8) if flattened.size else None,
        "max": round(float(flattened.max()), 8) if flattened.size else None,
        "mean": round(float(flattened.mean()), 8) if flattened.size else None,
        "stddev": round(float(flattened.std()), 8) if flattened.size else None,
    }


def _normalized_dtype(values: Any) -> str:
    dtype = str(getattr(values, "dtype", "unknown")).lower()
    for name in ("bool", "uint8", "int32", "int64", "float16", "float32", "float64"):
        if name in dtype:
            return name
    return dtype


def _set_seed(framework: Framework, module: Any, seed: int) -> None:
    if framework == Framework.PYTORCH:
        module.manual_seed(seed)
    else:
        module.set_seed(seed)


def _random_uniform(
    framework: Framework, module: Any, seed: int, size: int, *, reset: bool
) -> Any:
    if reset:
        _set_seed(framework, module, seed)
    if framework == Framework.PYTORCH:
        return _to_numpy(module.rand(size))
    return _to_numpy(importlib.import_module("mindspore.ops").rand((size,)))


def _dropout_values(framework: Framework, module: Any, seed: int, size: int) -> Any:
    _set_seed(framework, module, seed)
    if framework == Framework.PYTORCH:
        functional = importlib.import_module("torch.nn.functional")
        return _to_numpy(
            functional.dropout(module.ones(size), p=0.25, training=True)
        )
    ops = importlib.import_module("mindspore.ops")
    return _to_numpy(ops.dropout(module.ops.ones((size,), module.float32), p=0.25))


def _random_integers(
    framework: Framework, module: Any, seed: int, size: int, high: int
) -> Any:
    _set_seed(framework, module, seed)
    if framework == Framework.PYTORCH:
        return _to_numpy(module.randint(0, high, (size,)))
    ops = importlib.import_module("mindspore.ops")
    return _to_numpy(ops.randint(0, high, (size,), dtype=module.int32))


def _random_normal(framework: Framework, module: Any, seed: int, size: int) -> Any:
    _set_seed(framework, module, seed)
    if framework == Framework.PYTORCH:
        return _to_numpy(module.randn(size))
    ops = importlib.import_module("mindspore.ops")
    return _to_numpy(ops.standard_normal((size,)))


def _random_summary(np: Any, values: Any, seed: int, reproducible: bool) -> dict[str, Any]:
    array = np.asarray(values).astype(np.float64, copy=False).reshape(-1)
    return {
        "seed": seed,
        "reproducible": reproducible,
        "sample_size": int(array.size),
        "statistics": {
            "mean": round(float(array.mean()), 8),
            "stddev": round(float(array.std()), 8),
            "zero_fraction": round(float((array == 0).mean()), 8),
        },
        "sequence_digest": hashlib.sha256(array.tobytes()).hexdigest(),
    }


def _arrays_equal(np: Any, first: Any, second: Any) -> bool:
    return bool(np.array_equal(np.asarray(first), np.asarray(second)))


def _nested(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _required_string(value: dict[str, Any], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result.strip():
        raise SchemaError(f"data-pipeline {name} must be a non-empty string")
    return result.strip()


def _category_value(category: DiagnosticCategory | None) -> str | None:
    return category.value if category is not None else None


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("framework", choices=("pytorch", "mindspore"))
    capture.add_argument("output")
    capture.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    capture.add_argument("--force", action="store_true")
    capture.add_argument("--allow-version-mismatch", action="store_true")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("source_capture")
    evaluate.add_argument("target_capture")
    evaluate.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    evaluate.add_argument("--output")
    evaluate.add_argument("--format", choices=("json", "markdown"), default="json")
    evaluate.add_argument("--force", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "capture":
            result = capture_framework(
                arguments.framework,
                arguments.output,
                arguments.manifest,
                overwrite=arguments.force,
                allow_version_mismatch=arguments.allow_version_mismatch,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        report = evaluate_benchmark(
            arguments.source_capture,
            arguments.target_capture,
            arguments.manifest,
        )
        rendered = (
            render_markdown(report)
            if arguments.format == "markdown"
            else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        if arguments.output:
            destination = Path(arguments.output).resolve()
            if destination.exists() and not arguments.force:
                raise FileExistsError(f"output already exists: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if report["passed"] else 1
    except (ImportError, OSError, RuntimeError, SchemaError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BENCHMARK_VERSION",
    "CASE_DEFINITIONS",
    "DEFAULT_MANIFEST",
    "PipelineCase",
    "PipelineManifest",
    "capture_framework",
    "evaluate_benchmark",
    "load_manifest",
    "render_markdown",
    "validate_report",
]
