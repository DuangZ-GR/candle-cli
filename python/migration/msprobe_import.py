"""Import msprobe dump.json statistics into canonical migration JSON Lines."""

from __future__ import annotations

import argparse
import json
import math
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from migration.schema import (
    SCHEMA_VERSION,
    ApiArgument,
    ApiTraceRecord,
    ExecutionMode,
    Framework,
    NumericSummary,
    RecordKind,
    SchemaError,
    SourceLocation,
    ValueKind,
    ValueSummary,
)
from migration.trace_capture import summarize_value
from migration.cli_io import configure_utf8_stdio

DEFAULT_MAX_DUMP_BYTES = 256 * 1024 * 1024


def import_msprobe_dump(
    dump_path: str | Path,
    output_path: str | Path,
    *,
    framework: Framework,
    framework_version: str,
    run_id: str | None = None,
    overwrite: bool = False,
    max_dump_bytes: int = DEFAULT_MAX_DUMP_BYTES,
) -> dict[str, Any]:
    """Normalize forward API records from an msprobe ``dump.json`` file."""

    if framework not in (Framework.PYTORCH, Framework.MINDSPORE):
        raise ValueError("framework must be pytorch or mindspore")
    if not framework_version.strip():
        raise ValueError("framework_version must not be empty")
    if max_dump_bytes <= 0:
        raise ValueError("max_dump_bytes must be greater than zero")
    dump_path = Path(dump_path).resolve()
    if dump_path.stat().st_size > max_dump_bytes:
        raise SchemaError("msprobe dump exceeds configured byte limit")
    try:
        payload = json.loads(dump_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SchemaError(f"invalid msprobe dump JSON: {error}") from error
    if not isinstance(payload, dict):
        raise SchemaError("msprobe dump root must be an object")

    resolved_run_id = run_id or uuid.uuid4().hex
    execution_mode = (
        ExecutionMode.EAGER if framework == Framework.PYTORCH else ExecutionMode.PYNATIVE
    )
    records = []
    skipped = []
    for dump_key, entry in payload.items():
        api = _api_from_dump_key(dump_key, framework)
        if api is None:
            skipped.append({"key": dump_key, "reason": "not a supported forward API record"})
            continue
        if not isinstance(entry, dict) or "output" not in entry:
            skipped.append({"key": dump_key, "reason": "record has no output"})
            continue
        output = _output_summary(entry["output"])
        arguments = _arguments(entry)
        record = ApiTraceRecord(
            schema_version=SCHEMA_VERSION,
            record_kind=RecordKind.API_TRACE,
            run_id=resolved_run_id,
            framework=framework,
            framework_version=framework_version,
            execution_mode=execution_mode,
            location=SourceLocation(file=dump_path.name, line=1, column=0),
            api=api,
            call_index=len(records),
            arguments=arguments,
            output=output,
            metadata={
                "source_format": "msprobe_dump_json",
                "dump_key": dump_key,
                "nan_inf_counts_available": False,
            },
        )
        record.validate()
        records.append(record)
    if not records:
        raise SchemaError("msprobe dump contains no supported forward API records")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w" if overwrite else "x", encoding="utf-8") as output_file:
        for record in records:
            output_file.write(
                json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
            )
            output_file.write("\n")
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": RecordKind.MSPROBE_IMPORT_REPORT.value,
        "framework": framework.value,
        "framework_version": framework_version,
        "run_id": resolved_run_id,
        "input": str(dump_path),
        "output": str(output_path.resolve()),
        "records_imported": len(records),
        "records_skipped": len(skipped),
        "skipped": skipped,
    }


def _api_from_dump_key(key: Any, framework: Framework) -> str | None:
    if not isinstance(key, str):
        return None
    parts = key.split(".")
    if len(parts) < 4 or parts[-1] != "forward" or not parts[-2].isdigit():
        return None
    prefix = parts[0]
    names = parts[1:-2]
    if not names:
        return None
    if framework == Framework.PYTORCH:
        roots = {
            "Torch": "torch",
            "Functional": "torch.nn.functional",
            "Tensor": "torch.Tensor",
        }
    else:
        roots = {
            "Mint": "mindspore.mint",
            "MintFunctional": "mindspore.mint.nn.functional",
            "MintDistributed": "mindspore.mint.distributed",
            "Functional": "mindspore.ops",
            "Tensor": "mindspore.Tensor",
            "Distributed": "mindspore.communication.comm_func",
        }
    root = roots.get(prefix)
    if root is None:
        if framework == Framework.MINDSPORE and prefix == "Primitive":
            return f"mindspore.ops.{names[0]}"
        return None
    return ".".join([root, names[-1]])


def _arguments(entry: dict[str, Any]) -> list[ApiArgument]:
    arguments = []
    input_args = entry.get("input_args", [])
    if isinstance(input_args, list):
        arguments.extend(
            ApiArgument(position=index, value=_summary_from_dump(value))
            for index, value in enumerate(input_args)
        )
    input_kwargs = entry.get("input_kwargs", {})
    if isinstance(input_kwargs, Mapping):
        arguments.extend(
            ApiArgument(
                name=str(name),
                position=len(arguments) + index,
                value=_summary_from_dump(value),
            )
            for index, (name, value) in enumerate(input_kwargs.items())
        )
    return arguments


def _output_summary(output: Any) -> ValueSummary:
    if isinstance(output, list) and len(output) == 1:
        return _summary_from_dump(output[0])
    return _summary_from_dump(output)


def _summary_from_dump(value: Any) -> ValueSummary:
    if isinstance(value, Mapping) and _is_tensor_stat(value):
        return ValueSummary(
            kind=ValueKind.TENSOR,
            dtype=_normalize_dtype(value.get("dtype")),
            shape=_normalize_shape(value.get("shape", [])),
            numeric=_numeric_from_dump(value),
            preview={"md5": value.get("md5")} if value.get("md5") else None,
        )
    if isinstance(value, Mapping):
        return ValueSummary(
            kind=ValueKind.MAPPING,
            preview={"keys": [str(key) for key in value], "length": len(value)},
            children=[_summary_from_dump(child) for child in value.values()],
        )
    if isinstance(value, list):
        return ValueSummary(
            kind=ValueKind.SEQUENCE,
            preview={"length": len(value)},
            children=[_summary_from_dump(child) for child in value],
        )
    return summarize_value(value)


def _is_tensor_stat(value: Mapping) -> bool:
    value_type = str(value.get("type", "")).lower()
    return "tensor" in value_type and "dtype" in value and "shape" in value


def _normalize_dtype(value: Any) -> str:
    text = str(value).strip().lower()
    for prefix in ("torch.", "mindspore."):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text or "unknown"


def _normalize_shape(value: Any) -> list[int | None]:
    if not isinstance(value, list):
        return []
    result = []
    for dimension in value:
        if dimension is None:
            result.append(None)
        elif isinstance(dimension, int) and dimension >= 0:
            result.append(dimension)
        else:
            result.append(None)
    return result


def _numeric_from_dump(value: Mapping) -> NumericSummary | None:
    minimum = _finite_number(value.get("Min"))
    maximum = _finite_number(value.get("Max"))
    mean = _finite_number(value.get("Mean"))
    if minimum is None and maximum is None and mean is None:
        return None
    return NumericSummary(min=minimum, max=maximum, mean=mean)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        return converted if math.isfinite(converted) else None
    return None


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump_path")
    parser.add_argument("output_path")
    parser.add_argument("--framework", choices=["pytorch", "mindspore"], required=True)
    parser.add_argument("--framework-version", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = import_msprobe_dump(
            arguments.dump_path,
            arguments.output_path,
            framework=Framework.parse(arguments.framework),
            framework_version=arguments.framework_version,
            run_id=arguments.run_id,
            overwrite=arguments.force,
        )
    except (OSError, ValueError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
