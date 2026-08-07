import json
from pathlib import Path

import pytest

from release_report import build_release_report, render_markdown


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "benchmarks" / "release" / "release_v1.json"


def test_release_report_aggregates_only_traceable_metrics():
    report = build_release_report(CONFIG, ROOT)

    assert report["evidence_count"] == 13
    assert report["claim_eligible_evidence_count"] == 12
    assert report["non_claim_evidence_count"] == 1
    smoke = next(item for item in report["evidence"] if item["id"] == "agent-ollama-smoke")
    assert smoke["claim_eligible"] is False
    assert smoke["metrics"]["claim_eligible"] is False
    assert all(len(item["source_sha256"]) == 64 for item in report["evidence"])
    assert "不可用于收益声明" in render_markdown(report)
    checked_in = json.loads(
        (ROOT / "benchmarks" / "results" / "release_evidence_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert report == checked_in


def test_release_report_rejects_paths_outside_repository(tmp_path):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["entries"] = [
        {
            "id": "escape",
            "path": "../outside.json",
            "claim_eligible": True,
            "metrics": [],
        }
    ]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes repository"):
        build_release_report(path, ROOT)
