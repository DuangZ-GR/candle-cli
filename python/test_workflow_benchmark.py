import json

import pytest

from migration.workflow_benchmark import load_manifest


def test_workflow_manifest_loads_every_frozen_case():
    manifest = load_manifest()

    assert manifest.benchmark_version == "workflow-e2e-v1"
    assert [case.case_id for case in manifest.cases] == [
        "preview-safe",
        "validated-apply",
        "validation-failure-rollback",
        "dtype-divergence-rollback",
    ]


def test_workflow_manifest_rejects_missing_case(tmp_path):
    payload = json.loads(
        __import__("pathlib").Path(
            "benchmarks/migration/workflow_e2e_v1.json"
        ).read_text(encoding="utf-8")
    )
    payload["cases"].pop()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="every built-in case"):
        load_manifest(path)
