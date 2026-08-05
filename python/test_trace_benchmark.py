import json

import pytest

from migration.schema import SchemaError
from migration.trace_benchmark import DEFAULT_MANIFEST, run_benchmark


def test_fixed_trace_defect_benchmark_meets_milestone_threshold():
    report = run_benchmark()

    assert report["dataset_kind"] == "synthetic_defect_injection"
    assert report["case_count"] == 10
    assert report["defect_case_count"] == 8
    assert report["classification_accuracy"] == 1.0
    assert report["category_accuracy"] == 1.0
    assert report["top1_accuracy"] == 1.0
    assert report["passed"] is True


def test_benchmark_rejects_artifact_path_escape(tmp_path):
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["cases"][0]["source"] = "../outside.jsonl"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SchemaError, match="must stay inside"):
        run_benchmark(path)


def test_benchmark_threshold_must_be_a_probability():
    with pytest.raises(ValueError, match="between zero and one"):
        run_benchmark(minimum_top1=1.1)
