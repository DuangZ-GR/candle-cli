import hashlib
import json
import shutil

import pytest

from migration.real_model_benchmark import DEFAULT_MANIFEST, load_manifest


def test_real_model_manifest_freezes_one_success_and_two_faults():
    manifest = load_manifest()

    assert manifest.path == DEFAULT_MANIFEST.resolve()
    assert manifest.benchmark_version == "real-model-dual-runtime-v1"
    assert manifest.source_version_prefix == "2.6"
    assert manifest.target_version_prefix == "2.9"
    assert [case.fault for case in manifest.cases] == ["none", "runtime", "dtype"]


def test_real_model_provenance_matches_vendored_source_and_license():
    manifest = load_manifest()
    provenance = json.loads(
        (manifest.slice_root / "PROVENANCE.json").read_text(encoding="utf-8")
    )
    source = (manifest.slice_root / "upstream_main.py").read_bytes()
    license_text = (manifest.slice_root / "UPSTREAM_LICENSE").read_bytes()

    assert len(source.decode("utf-8").splitlines()) == provenance["source_line_count"]
    assert hashlib.sha256(source).hexdigest() == provenance["source_sha256"]
    assert hashlib.sha256(license_text).hexdigest() == provenance["license_sha256"]
    assert provenance["commit"] == "acc295dc7b90714f1bf47f06004fc19a7fe235c4"


def test_real_model_manifest_rejects_missing_fault_case(tmp_path):
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    source_root = (DEFAULT_MANIFEST.parent / payload["slice"]["root"]).resolve()
    copied_root = tmp_path / "model_slice"
    shutil.copytree(source_root, copied_root)
    payload["slice"]["root"] = copied_root.name
    payload["cases"] = payload["cases"][:1]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_manifest(path)
