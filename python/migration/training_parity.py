"""Capture and evaluate deterministic PyTorch/MindSpore training-step parity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.component_parity import (
    DEFAULT_TRAINING_MANIFEST,
    capture_framework as capture_component_framework,
    evaluate_benchmark as evaluate_component_benchmark,
)


def capture_framework(
    framework: str,
    output_dir: str | Path,
    manifest_path: str | Path = DEFAULT_TRAINING_MANIFEST,
    *,
    overwrite: bool = False,
    allow_version_mismatch: bool = False,
) -> dict[str, Any]:
    return capture_component_framework(
        framework,
        output_dir,
        manifest_path,
        overwrite=overwrite,
        allow_version_mismatch=allow_version_mismatch,
    )


def evaluate_benchmark(
    capture_root: str | Path,
    manifest_path: str | Path = DEFAULT_TRAINING_MANIFEST,
) -> dict[str, Any]:
    return evaluate_component_benchmark(capture_root, manifest_path)


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("framework", choices=["pytorch", "mindspore"])
    capture.add_argument("output_dir")
    capture.add_argument("--manifest", default=str(DEFAULT_TRAINING_MANIFEST))
    capture.add_argument("--force", action="store_true")
    capture.add_argument("--allow-version-mismatch", action="store_true")
    capture.add_argument("--pretty", action="store_true")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("capture_root")
    evaluate.add_argument("--manifest", default=str(DEFAULT_TRAINING_MANIFEST))
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
