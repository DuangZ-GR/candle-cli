"""Measure mapping coverage against a fixed scanner API manifest."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase
from migration.cli_io import configure_utf8_stdio

DEFAULT_MANIFEST = (
    Path(__file__).parents[2] / "benchmarks" / "manifests" / "scanner_v1.json"
)


def run_benchmark(
    manifest_path: str | Path = DEFAULT_MANIFEST,
    knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE,
) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    unique_apis = sorted(
        {api for case in manifest["cases"] for api in case["expected_apis"]}
    )
    knowledge = MappingKnowledgeBase.load(knowledge_base)
    resolutions = [knowledge.resolve(api) for api in unique_apis]
    status_counts = Counter(result.status for result in resolutions)
    known_count = len(unique_apis) - status_counts["unknown"]
    return {
        "benchmark_id": "torch2ms-mapping-coverage-v1",
        "scanner_manifest": manifest["benchmark_id"],
        "knowledge_version": knowledge.payload["snapshot_version"],
        "unique_api_count": len(unique_apis),
        "known_api_count": known_count,
        "coverage": known_count / len(unique_apis) if unique_apis else 1.0,
        "status_counts": dict(sorted(status_counts.items())),
        "unknown_apis": sorted(
            result.source_api for result in resolutions if result.status == "unknown"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--min-coverage", type=float, default=0.70)
    arguments = parser.parse_args(argv)
    result = run_benchmark(arguments.manifest, arguments.knowledge_base)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["coverage"] >= arguments.min_coverage else 1


if __name__ == "__main__":
    raise SystemExit(main())
