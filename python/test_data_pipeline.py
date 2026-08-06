import json

import pytest

from migration.data_pipeline import (
    CASE_DEFINITIONS,
    DEFAULT_MANIFEST,
    evaluate_benchmark,
    load_manifest,
    validate_report,
)
from migration.schema import SchemaError


def _observation(case, framework):
    observation = {
        "case_id": case.case_id,
        "framework": framework,
        "comparison_kind": case.comparison_kind,
        "sample_count": 5,
        "batch_count": 3,
        "batch_sizes": [2, 2, 1],
        "tensor": {
            "layout": "CHW",
            "dtype": "float32",
            "shape": [1, 2, 2],
            "min": 0.0,
            "max": 1.0,
            "mean": 0.5,
            "stddev": 0.25,
        },
        "labels": {"dtype": "int64", "semantics": "classification_index"},
        "mask": {"dtype": "bool", "semantics": "boolean_selector"},
        "transform": {
            "name": "Resize",
            "parameters": {"size": [2, 2], "interpolation": "bilinear"},
        },
        "randomness": None,
    }
    if case.comparison_kind in {"fixed_seed", "statistical"}:
        sample_size = int(case.thresholds["minimum_sample_size"])
        observation["randomness"] = {
            "seed": 20250315,
            "reproducible": True,
            "sample_size": sample_size,
            "statistics": {
                "mean": 0.0,
                "stddev": 1.0,
                "zero_fraction": 0.25,
            },
            "sequence_digest": f"{framework}-{case.case_id}",
        }
    return observation


def _write_captures(tmp_path):
    manifest = load_manifest()
    source_observations = []
    target_observations = []
    for case in manifest.cases:
        source = _observation(case, "pytorch")
        target = _observation(case, "mindspore")
        if case.case_id == "layout-hwc-injected":
            target["tensor"]["layout"] = "HWC"
        elif case.case_id == "tensor-bool-injected":
            target["tensor"]["dtype"] = "bool"
        elif case.case_id == "normalization-scale-injected":
            target["tensor"]["max"] = 255.0
        elif case.case_id == "label-float-injected":
            target["labels"]["dtype"] = "float32"
        elif case.case_id == "mask-int-injected":
            target["mask"]["dtype"] = "int32"
        elif case.case_id == "drop-last-injected":
            target["batch_sizes"] = [2, 2]
        elif case.case_id == "resize-default-injected":
            target["transform"]["parameters"]["interpolation"] = "nearest"
        elif case.case_id == "fixed-seed-reset-injected":
            target["randomness"]["reproducible"] = False
        source_observations.append(source)
        target_observations.append(target)

    def document(framework, version, observations):
        return {
            "schema_version": "1.0",
            "record_kind": "data_pipeline_capture",
            "benchmark_version": "data-pipeline-randomness-v1",
            "framework": framework,
            "framework_version": version,
            "case_count": len(observations),
            "observations": observations,
        }

    source_path = tmp_path / "pytorch.json"
    target_path = tmp_path / "mindspore.json"
    source_path.write_text(
        json.dumps(document("pytorch", "2.6.0+cu124", source_observations)),
        encoding="utf-8",
    )
    target_path.write_text(
        json.dumps(document("mindspore", "2.9.0", target_observations)),
        encoding="utf-8",
    )
    return source_path, target_path


def test_manifest_is_frozen_and_meets_m15_case_floor():
    manifest = load_manifest()

    assert {case.case_id for case in manifest.cases} == set(CASE_DEFINITIONS)
    assert len(manifest.cases) == 18
    assert sum(case.fault_injection for case in manifest.cases) == 8
    assert sum(case.comparison_kind != "deterministic" for case in manifest.cases) == 4
    assert {case.split for case in manifest.cases} == {"development", "heldout"}


def test_manifest_rejects_frozen_case_drift(tmp_path):
    document = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    document["cases"][0]["comparison_kind"] = "statistical"
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SchemaError, match="does not match built-in case"):
        load_manifest(changed)


def test_synthetic_report_localizes_all_frozen_faults(tmp_path):
    source, target = _write_captures(tmp_path)

    report = evaluate_benchmark(source, target)

    assert report["complete"] is True
    assert report["passed"] is True
    assert report["case_count"] == 18
    assert report["fault_case_count"] == 8
    assert report["classification_accuracy"] == 1.0
    assert report["first_divergence_top1_accuracy"] == 1.0
    assert report["deterministic_equivalence_rate"] == 1.0
    assert report["statistical_equivalence_rate"] == 1.0
    assert report["minimum_stochastic_sample_size"] == 128
    assert report["first_divergence_categories"] == {
        "batching_mismatch": 1,
        "dtype_mismatch": 1,
        "label_dtype_mismatch": 1,
        "layout_mismatch": 1,
        "mask_dtype_mismatch": 1,
        "normalization_mismatch": 1,
        "reproducibility_mismatch": 1,
        "transform_mismatch": 1,
    }
    random_cases = [
        case
        for case in report["cases"]
        if case["comparison_kind"] in {"fixed_seed", "statistical"}
    ]
    assert all(case["sample_size"] for case in random_cases)
    assert all(case["statistics"] for case in random_cases)
    assert all(case["thresholds"] for case in random_cases)
    assert all(case["elementwise_compared"] is False for case in random_cases)
    statistical = [
        case for case in random_cases if case["comparison_kind"] == "statistical"
    ]
    assert all(case["statistics"]["sequence_equal"] is False for case in statistical)


def test_statistical_case_uses_thresholds_not_elementwise_equality(tmp_path):
    source, target = _write_captures(tmp_path)
    target_document = json.loads(target.read_text(encoding="utf-8"))
    dropout = next(
        item
        for item in target_document["observations"]
        if item["case_id"] == "dropout-statistical"
    )
    dropout["randomness"]["statistics"]["mean"] = 0.5
    target.write_text(json.dumps(target_document), encoding="utf-8")

    report = evaluate_benchmark(source, target)
    result = next(
        item for item in report["cases"] if item["case_id"] == "dropout-statistical"
    )

    assert report["passed"] is False
    assert result["observed_category"] == "random_distribution_mismatch"
    assert result["first_difference"] == "randomness.mean"
    assert result["elementwise_compared"] is False


def test_report_validation_rejects_elementwise_random_claim(tmp_path):
    source, target = _write_captures(tmp_path)
    report = evaluate_benchmark(source, target)
    random_case = next(
        item for item in report["cases"] if item["comparison_kind"] == "statistical"
    )
    random_case["elementwise_compared"] = True

    with pytest.raises(ValueError, match="must not use elementwise equality"):
        validate_report(report)
