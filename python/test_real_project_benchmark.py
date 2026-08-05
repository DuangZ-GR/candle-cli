import hashlib
import json
import zipfile

import pytest

from migration.real_corpus import load_manifest, prepare_corpus
from migration.real_project_benchmark import run_benchmark


def write_manifest(tmp_path, project, paths=None):
    manifest = {
        "schema_version": "1.0",
        "benchmark_version": "test-real-v1",
        "dataset_kind": "pinned_real_project_static_corpus",
        "projects": [
            {
                "id": "fixture",
                "repository": "https://github.com/example/fixture.git",
                "commit": "0" * 40,
                "checkout_dir": "fixture",
                "license": "MIT",
                "license_file": "LICENSE",
                "paths": paths or ["*.py"],
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    checkout = tmp_path / "fixture"
    checkout.mkdir()
    (checkout / "LICENSE").write_text("MIT", encoding="utf-8")
    (checkout / "model.py").write_text(
        "import torch\na = torch.add(x, 1)\nb = torch.future_api(x)\n",
        encoding="utf-8",
    )
    return path


def test_real_project_benchmark_measures_scan_and_preview_without_execution(tmp_path):
    manifest = write_manifest(tmp_path, "fixture")

    report = run_benchmark(tmp_path, manifest, verify_commits=False)

    summary = report["summary"]
    assert report["project_count"] == 1
    assert summary["files"] == 1
    assert summary["findings"] == 2
    assert summary["mapping_counts"] == {
        "exact": 1,
        "difference": 0,
        "unsupported": 0,
        "unknown": 1,
    }
    assert summary["mapped_finding_coverage"] == 0.5
    assert summary["rewrite"]["call_rewrites"] == 1
    assert summary["rewrite"]["syntax_valid_rate"] == 1.0
    assert summary["top_unknown_apis"] == [{"api": "torch.future_api", "count": 1}]


def test_manifest_rejects_path_escape(tmp_path):
    manifest = write_manifest(tmp_path, "fixture", paths=["../outside.py"])

    with pytest.raises(ValueError, match="safe relative"):
        load_manifest(manifest)


def test_manifest_rejects_moving_or_abbreviated_commit(tmp_path):
    manifest = write_manifest(tmp_path, "fixture")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["projects"][0]["commit"] = "main"
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="40-character SHA"):
        load_manifest(manifest)


def write_archive_manifest(tmp_path):
    prefix = "fixture-" + "1" * 40
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"{prefix}/LICENSE", "MIT")
        bundle.writestr(f"{prefix}/model.py", "import torch\nx = torch.add(a, b)\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    document = {
        "schema_version": "1.0",
        "benchmark_version": "archive-v1",
        "dataset_kind": "pinned_real_project_static_corpus",
        "projects": [
            {
                "id": "archive-fixture",
                "repository": "https://github.com/example/fixture.git",
                "commit": "1" * 40,
                "checkout_dir": "fixture",
                "license": "MIT",
                "license_file": "LICENSE",
                "archive_file": "fixture.zip",
                "archive_sha256": digest,
                "archive_prefix": prefix,
                "paths": ["*.py"],
            }
        ],
    }
    manifest = tmp_path / "archive-manifest.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    return manifest


def test_archive_corpus_is_hash_checked_extracted_and_content_verified(tmp_path):
    manifest = write_archive_manifest(tmp_path)

    prepared = prepare_corpus(tmp_path, manifest)
    report = run_benchmark(tmp_path, manifest)

    assert prepared["projects"][0]["status"] == "ready"
    assert report["summary"]["findings"] == 1
    assert report["summary"]["rewrite"]["syntax_valid_rate"] == 1.0

    (tmp_path / "fixture" / "model.py").write_text("import torch\n", encoding="utf-8")
    with pytest.raises(ValueError, match="archive content mismatch"):
        run_benchmark(tmp_path, manifest)


def test_manifest_rejects_partial_or_invalid_archive_metadata(tmp_path):
    manifest = write_archive_manifest(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    del document["projects"][0]["archive_prefix"]
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="provided together"):
        load_manifest(manifest)
