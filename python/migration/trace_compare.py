"""Normalize and compare PyTorch/MindSpore API trace JSON Lines."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase
from migration.cli_io import configure_utf8_stdio
from migration.schema import (
    SCHEMA_VERSION,
    ApiTraceRecord,
    DiagnosticCategory,
    DiagnosticEvidence,
    DiagnosticRecord,
    EvidenceKind,
    Framework,
    RecordKind,
    SchemaError,
    Severity,
    ValueSummary,
)

DEFAULT_MAX_LINE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class TraceComparison:
    source_count: int
    target_count: int
    aligned_count: int
    equivalent: bool
    diagnostic: DiagnosticRecord | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "record_kind": RecordKind.TRACE_COMPARISON.value,
            "source_count": self.source_count,
            "target_count": self.target_count,
            "aligned_count": self.aligned_count,
            "equivalent": self.equivalent,
            "diagnostic": self.diagnostic.to_dict() if self.diagnostic else None,
        }


def load_trace_jsonl(
    path: str | Path,
    expected_framework: Framework | None = None,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> list[ApiTraceRecord]:
    if max_line_bytes <= 0:
        raise ValueError("max_line_bytes must be greater than zero")
    records = []
    run_id = None
    previous_call_index = None
    with Path(path).open("r", encoding="utf-8") as trace_file:
        for line_number, line in enumerate(trace_file, start=1):
            if not line.strip():
                continue
            if len(line.encode("utf-8")) > max_line_bytes:
                raise SchemaError(f"trace line {line_number} exceeds byte limit")
            try:
                payload = json.loads(line)
                record = ApiTraceRecord.from_dict(payload)
                record.validate()
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise SchemaError(f"invalid trace line {line_number}: {error}") from error
            if expected_framework is not None and record.framework != expected_framework:
                raise SchemaError(
                    f"trace line {line_number} framework is {record.framework.value}; "
                    f"expected {expected_framework.value}"
                )
            if run_id is None:
                run_id = record.run_id
            elif record.run_id != run_id:
                raise SchemaError("all trace records must share one run_id")
            if previous_call_index is not None and record.call_index <= previous_call_index:
                raise SchemaError("trace call_index values must be strictly increasing")
            previous_call_index = record.call_index
            records.append(record)
    if not records:
        raise SchemaError("trace file must contain at least one record")
    return records


def compare_traces(
    source: list[ApiTraceRecord],
    target: list[ApiTraceRecord],
    knowledge: MappingKnowledgeBase | None = None,
    relative_tolerance: float = 1e-5,
    absolute_tolerance: float = 1e-8,
) -> TraceComparison:
    if not source or not target:
        raise SchemaError("both traces must contain at least one record")
    if relative_tolerance < 0 or absolute_tolerance < 0:
        raise ValueError("numeric tolerances must be non-negative")
    knowledge = knowledge or MappingKnowledgeBase.load()
    pairs = _align_calls(source, target, knowledge)
    source_cursor = 0
    target_cursor = 0
    for source_index, target_index in pairs:
        if source_index != source_cursor or target_index != target_cursor:
            diagnostic = _sequence_diagnostic(
                source,
                target,
                source_cursor,
                target_cursor,
                knowledge,
                relative_tolerance,
                absolute_tolerance,
            )
            return TraceComparison(
                len(source), len(target), len(pairs), False, diagnostic
            )
        difference = _compare_call(
            source[source_index],
            target[target_index],
            relative_tolerance,
            absolute_tolerance,
        )
        if difference is not None:
            return TraceComparison(len(source), len(target), len(pairs), False, difference)
        source_cursor = source_index + 1
        target_cursor = target_index + 1
    if source_cursor != len(source) or target_cursor != len(target):
        diagnostic = _sequence_diagnostic(
            source,
            target,
            source_cursor,
            target_cursor,
            knowledge,
            relative_tolerance,
            absolute_tolerance,
        )
        return TraceComparison(len(source), len(target), len(pairs), False, diagnostic)
    return TraceComparison(len(source), len(target), len(pairs), True, None)


def _align_calls(
    source: list[ApiTraceRecord],
    target: list[ApiTraceRecord],
    knowledge: MappingKnowledgeBase,
) -> list[tuple[int, int]]:
    source_keys = [
        knowledge.resolve(record.api).target_api or f"unknown:{record.api}"
        for record in source
    ]
    target_keys = [record.api for record in target]
    rows = len(source_keys) + 1
    columns = len(target_keys) + 1
    lengths = [[0] * columns for _ in range(rows)]
    for source_index in range(len(source_keys) - 1, -1, -1):
        for target_index in range(len(target_keys) - 1, -1, -1):
            if source_keys[source_index] == target_keys[target_index]:
                lengths[source_index][target_index] = (
                    lengths[source_index + 1][target_index + 1] + 1
                )
            else:
                lengths[source_index][target_index] = max(
                    lengths[source_index + 1][target_index],
                    lengths[source_index][target_index + 1],
                )
    pairs = []
    source_index = 0
    target_index = 0
    while source_index < len(source_keys) and target_index < len(target_keys):
        if source_keys[source_index] == target_keys[target_index]:
            pairs.append((source_index, target_index))
            source_index += 1
            target_index += 1
        elif lengths[source_index + 1][target_index] >= lengths[source_index][target_index + 1]:
            source_index += 1
        else:
            target_index += 1
    return pairs


def _compare_call(
    source: ApiTraceRecord,
    target: ApiTraceRecord,
    relative_tolerance: float,
    absolute_tolerance: float,
) -> DiagnosticRecord | None:
    if source.error is not None or target.error is not None:
        if (
            source.error is not None
            and target.error is not None
            and source.error.error_type == target.error.error_type
        ):
            return None
        category = DiagnosticCategory.RUNTIME_ERROR
        if (
            source.error is None
            and target.error is not None
            and target.error.error_type
            in {
                "AttributeError",
                "ImportError",
                "ModuleNotFoundError",
                "NotImplementedError",
            }
        ):
            category = DiagnosticCategory.MISSING_OPERATOR
        summary = (
            "MindSpore 目标算子不可用"
            if category == DiagnosticCategory.MISSING_OPERATOR
            else "框架运行结果不一致"
        )
        explanation = (
            "PyTorch 调用成功，但 MindSpore 目标调用报告算子或模块不可用。"
            if category == DiagnosticCategory.MISSING_OPERATOR
            else "一个框架产生运行时错误，或两端错误类型不同。"
        )
        return _diagnostic(
            source,
            target,
            category,
            Severity.HIGH,
            summary,
            explanation,
            {"source_error": _error_data(source), "target_error": _error_data(target)},
            relative_tolerance,
            absolute_tolerance,
        )
    assert source.output is not None and target.output is not None
    difference = _compare_value(
        source.output, target.output, "output", relative_tolerance, absolute_tolerance
    )
    if difference is None:
        return None
    category, severity, summary, explanation, data = difference
    semantic_roles = {
        source.metadata.get("semantic_role"),
        target.metadata.get("semantic_role"),
    }
    if "gradient" in semantic_roles:
        category = DiagnosticCategory.GRADIENT_MISMATCH
        summary = "梯度不一致"
        explanation = f"首个可观测偏差位于梯度调用的 {data.get('path', 'output')}。"
    elif "randomness" in semantic_roles:
        category = DiagnosticCategory.RANDOMNESS_MISMATCH
        summary = "随机性行为不一致"
        explanation = f"首个可观测偏差位于随机调用的 {data.get('path', 'output')}。"
    return _diagnostic(
        source,
        target,
        category,
        severity,
        summary,
        explanation,
        data,
        relative_tolerance,
        absolute_tolerance,
    )


def _compare_value(source, target, path, relative_tolerance, absolute_tolerance):
    if source.kind != target.kind or len(source.children) != len(target.children):
        return (
            DiagnosticCategory.RETURN_STRUCTURE_MISMATCH,
            Severity.HIGH,
            "返回结构不一致",
            f"首个可观测偏差位于 {path} 的结构。",
            {"path": path, "source_kind": source.kind.value, "target_kind": target.kind.value},
        )
    if source.dtype != target.dtype:
        return (
            DiagnosticCategory.DTYPE_MISMATCH,
            Severity.HIGH,
            "输出 dtype 不一致",
            f"首个可观测偏差位于 {path} 的 dtype。",
            {"path": path, "source_dtype": source.dtype, "target_dtype": target.dtype},
        )
    if source.shape != target.shape:
        return (
            DiagnosticCategory.SHAPE_MISMATCH,
            Severity.HIGH,
            "输出 shape 不一致",
            f"首个可观测偏差位于 {path} 的 shape。",
            {"path": path, "source_shape": source.shape, "target_shape": target.shape},
        )
    if source.numeric is not None or target.numeric is not None:
        if source.numeric is None or target.numeric is None:
            return _value_difference(path, "一端缺少数值摘要", {})
        if (
            source.numeric.nan_count != target.numeric.nan_count
            or source.numeric.inf_count != target.numeric.inf_count
        ):
            return _value_difference(
                path,
                "NaN/Inf 数量不一致",
                {
                    "source_nan_count": source.numeric.nan_count,
                    "target_nan_count": target.numeric.nan_count,
                    "source_inf_count": source.numeric.inf_count,
                    "target_inf_count": target.numeric.inf_count,
                },
            )
        for statistic in ("min", "max", "mean"):
            source_value = getattr(source.numeric, statistic)
            target_value = getattr(target.numeric, statistic)
            if source_value is None and target_value is None:
                continue
            if source_value is None or target_value is None or not math.isclose(
                source_value,
                target_value,
                rel_tol=relative_tolerance,
                abs_tol=absolute_tolerance,
            ):
                return _value_difference(
                    path,
                    f"数值摘要 {statistic} 超出容差",
                    {"statistic": statistic, "source": source_value, "target": target_value},
                )
    preview_difference = _compare_numeric_preview(
        source.preview, target.preview, path, relative_tolerance, absolute_tolerance
    )
    if preview_difference is not None:
        return preview_difference
    for index, (source_child, target_child) in enumerate(
        zip(source.children, target.children)
    ):
        difference = _compare_value(
            source_child,
            target_child,
            f"{path}.children[{index}]",
            relative_tolerance,
            absolute_tolerance,
        )
        if difference is not None:
            return difference
    return None


def _compare_numeric_preview(source, target, path, relative_tolerance, absolute_tolerance):
    source_values = _numeric_preview_values(source)
    target_values = _numeric_preview_values(target)
    if source_values is None or target_values is None:
        return None
    if len(source_values) != len(target_values):
        return _value_difference(
            path,
            "数值预览长度不一致",
            {"source_length": len(source_values), "target_length": len(target_values)},
        )
    for index, (source_value, target_value) in enumerate(
        zip(source_values, target_values)
    ):
        if not math.isclose(
            source_value,
            target_value,
            rel_tol=relative_tolerance,
            abs_tol=absolute_tolerance,
        ):
            return _value_difference(
                path,
                f"数值预览第 {index} 项超出容差",
                {
                    "preview_index": index,
                    "source": source_value,
                    "target": target_value,
                },
            )
    return None


def _numeric_preview_values(value):
    values = value if isinstance(value, list) else [value]
    if not values or any(
        not isinstance(item, (int, float)) or isinstance(item, bool) for item in values
    ):
        return None
    return [float(item) for item in values]


def _value_difference(path, explanation, data):
    return (
        DiagnosticCategory.VALUE_MISMATCH,
        Severity.MEDIUM,
        "输出数值不一致",
        f"首个可观测偏差位于 {path}：{explanation}。",
        {"path": path, **data},
    )


def _sequence_diagnostic(source, target, source_index, target_index, knowledge, rtol, atol):
    source_record = source[source_index] if source_index < len(source) else source[-1]
    target_record = target[target_index] if target_index < len(target) else target[-1]
    expected_target = knowledge.resolve(source_record.api).target_api
    return _diagnostic(
        source_record,
        target_record,
        DiagnosticCategory.NEEDS_MANUAL_REVIEW,
        Severity.HIGH,
        "API 调用序列无法对齐",
        "在数值比较前发现缺失、额外或未知映射的 API 调用。",
        {
            "source_index": source_index,
            "target_index": target_index,
            "source_api": source_record.api,
            "expected_target_api": expected_target,
            "actual_target_api": target_record.api,
        },
        rtol,
        atol,
    )


def _diagnostic(source, target, category, severity, summary, explanation, data, rtol, atol):
    identity = f"{source.run_id}:{source.call_index}:{target.call_index}:{category.value}"
    diagnostic = DiagnosticRecord(
        schema_version=SCHEMA_VERSION,
        record_kind=RecordKind.DIAGNOSTIC,
        diagnostic_id=hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        run_id=source.run_id,
        category=category,
        severity=severity,
        confidence=1.0,
        summary=summary,
        explanation=explanation,
        location=source.location,
        source_api=source.api,
        target_api=target.api,
        evidence=[
            DiagnosticEvidence(
                kind=EvidenceKind.DIFF_VALIDATION,
                message="PyTorch 与 MindSpore 归一化轨迹的确定性比较结果。",
                location=source.location,
                data=data,
            )
        ],
        suggested_action="检查该调用的映射差异、输入转换、dtype 和默认参数。",
        verified=True,
        metadata={
            "source_framework_version": source.framework_version,
            "target_framework_version": target.framework_version,
            "source_call_index": source.call_index,
            "target_call_index": target.call_index,
            "relative_tolerance": rtol,
            "absolute_tolerance": atol,
        },
    )
    diagnostic.validate()
    return diagnostic


def _error_data(record):
    if record.error is None:
        return None
    return {"error_type": record.error.error_type, "message": record.error.message}


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_trace")
    parser.add_argument("target_trace")
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--relative-tolerance", type=float, default=1e-5)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-8)
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        source = load_trace_jsonl(arguments.source_trace, Framework.PYTORCH)
        target = load_trace_jsonl(arguments.target_trace, Framework.MINDSPORE)
        result = compare_traces(
            source,
            target,
            MappingKnowledgeBase.load(arguments.knowledge_base),
            arguments.relative_tolerance,
            arguments.absolute_tolerance,
        )
    except (OSError, ValueError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
