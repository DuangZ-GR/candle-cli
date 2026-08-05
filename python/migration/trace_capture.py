"""Framework-neutral runtime capture for PyTorch/MindSpore migration traces."""

from __future__ import annotations

import inspect
import json
import math
import re
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

from migration.schema import (
    SCHEMA_VERSION,
    ApiArgument,
    ApiTraceRecord,
    ExecutionMode,
    Framework,
    NumericSummary,
    RecordKind,
    RuntimeErrorRecord,
    SourceLocation,
    ValueKind,
    ValueSummary,
)

T = TypeVar("T")
DEFAULT_MAX_CHILDREN = 16
DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_TENSOR_ELEMENTS = 100_000
DEFAULT_PREVIEW_ELEMENTS = 8
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|password|secret|token)(\s*[:=]\s*)([^\s,;]+)"
)


def summarize_value(
    value: Any,
    *,
    max_children: int = DEFAULT_MAX_CHILDREN,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_tensor_elements: int = DEFAULT_MAX_TENSOR_ELEMENTS,
) -> ValueSummary:
    """Convert a runtime value into a bounded, JSON-safe summary.

    Tensor values are detected by their ``shape`` and ``dtype`` attributes, so
    importing PyTorch or MindSpore is not required. Numeric statistics are exact
    only when the tensor is within ``max_tensor_elements``; larger tensors retain
    dtype, shape and a truncation marker without pretending a sample is exact.
    """

    if max_children <= 0:
        raise ValueError("max_children must be greater than zero")
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative")
    if max_tensor_elements <= 0:
        raise ValueError("max_tensor_elements must be greater than zero")
    return _summarize(
        value,
        depth=0,
        seen=set(),
        max_children=max_children,
        max_depth=max_depth,
        max_tensor_elements=max_tensor_elements,
    )


def _summarize(value, *, depth, seen, max_children, max_depth, max_tensor_elements):
    if value is None:
        return ValueSummary(kind=ValueKind.NONE, preview=None)
    if isinstance(value, bool):
        return ValueSummary(kind=ValueKind.BOOLEAN, dtype="bool", preview=value)
    if isinstance(value, (int, float)):
        return ValueSummary(
            kind=ValueKind.SCALAR,
            dtype=type(value).__name__,
            numeric=_numeric_summary([value]),
            preview=_json_number(value),
        )
    if isinstance(value, complex):
        return ValueSummary(
            kind=ValueKind.SCALAR,
            dtype="complex",
            preview={
                "real": _json_number(value.real),
                "imag": _json_number(value.imag),
            },
        )
    if isinstance(value, str):
        preview = value if len(value) <= 256 else f"{value[:256]}…"
        return ValueSummary(kind=ValueKind.STRING, preview=preview)
    if _looks_like_tensor(value):
        return _summarize_tensor(value, max_tensor_elements)

    identity = id(value)
    if isinstance(value, Mapping):
        if identity in seen:
            return ValueSummary(kind=ValueKind.MAPPING, preview={"recursive": True})
        items = list(value.items())
        preview = {
            "keys": [str(key)[:128] for key, _ in items[:max_children]],
            "length": len(items),
            "truncated": len(items) > max_children or depth >= max_depth,
        }
        if depth >= max_depth:
            return ValueSummary(kind=ValueKind.MAPPING, preview=preview)
        seen.add(identity)
        try:
            children = [
                _summarize(
                    item,
                    depth=depth + 1,
                    seen=seen,
                    max_children=max_children,
                    max_depth=max_depth,
                    max_tensor_elements=max_tensor_elements,
                )
                for _, item in items[:max_children]
            ]
        finally:
            seen.remove(identity)
        return ValueSummary(kind=ValueKind.MAPPING, preview=preview, children=children)

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        if identity in seen:
            return ValueSummary(kind=ValueKind.SEQUENCE, preview={"recursive": True})
        preview = {
            "length": len(value),
            "truncated": len(value) > max_children or depth >= max_depth,
        }
        if depth >= max_depth:
            return ValueSummary(kind=ValueKind.SEQUENCE, preview=preview)
        seen.add(identity)
        try:
            children = [
                _summarize(
                    item,
                    depth=depth + 1,
                    seen=seen,
                    max_children=max_children,
                    max_depth=max_depth,
                    max_tensor_elements=max_tensor_elements,
                )
                for item in value[:max_children]
            ]
        finally:
            seen.remove(identity)
        return ValueSummary(kind=ValueKind.SEQUENCE, preview=preview, children=children)

    return ValueSummary(
        kind=ValueKind.UNKNOWN,
        preview={"python_type": f"{type(value).__module__}.{type(value).__qualname__}"},
    )


def _looks_like_tensor(value: Any) -> bool:
    return hasattr(value, "shape") and hasattr(value, "dtype")


def _summarize_tensor(value: Any, max_tensor_elements: int) -> ValueSummary:
    shape = _normalize_shape(value.shape)
    dtype = _normalize_dtype(value.dtype)
    element_count = _element_count(shape)
    if element_count is None or element_count > max_tensor_elements:
        return ValueSummary(
            kind=ValueKind.TENSOR,
            dtype=dtype,
            shape=shape,
            preview={
                "element_count": element_count,
                "statistics_omitted": True,
                "reason": "tensor exceeds capture limit"
                if element_count is not None
                else "tensor has an unknown dimension",
            },
        )
    try:
        serializable = _tensor_to_list(value)
        flattened = list(_flatten(serializable))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return ValueSummary(
            kind=ValueKind.TENSOR,
            dtype=dtype,
            shape=shape,
            preview={"statistics_omitted": True, "reason": "tensor conversion failed"},
        )
    return ValueSummary(
        kind=ValueKind.TENSOR,
        dtype=dtype,
        shape=shape,
        numeric=_numeric_summary(flattened),
        preview=[_json_scalar(item) for item in flattened[:DEFAULT_PREVIEW_ELEMENTS]],
    )


def _normalize_shape(shape: Any) -> list[int | None]:
    try:
        dimensions = list(shape)
    except TypeError:
        return []
    normalized = []
    for dimension in dimensions:
        if dimension is None:
            normalized.append(None)
        else:
            try:
                normalized.append(int(dimension))
            except (TypeError, ValueError):
                normalized.append(None)
    return normalized


def _normalize_dtype(dtype: Any) -> str:
    text = str(dtype).strip().lower()
    for prefix in ("torch.", "mindspore.", "mstype.", "numpy."):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text or "unknown"


def _element_count(shape: list[int | None]) -> int | None:
    count = 1
    for dimension in shape:
        if dimension is None:
            return None
        count *= dimension
    return count


def _tensor_to_list(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "asnumpy"):
        value = value.asnumpy()
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError("tensor does not expose a supported conversion method")


def _flatten(value: Any):
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten(item)
    else:
        yield value


def _numeric_summary(values: list[Any]) -> NumericSummary | None:
    numbers = []
    for value in values:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        try:
            numbers.append(float(value))
        except (OverflowError, TypeError, ValueError):
            continue
    if not numbers:
        return None
    nan_count = sum(math.isnan(value) for value in numbers)
    inf_count = sum(math.isinf(value) for value in numbers)
    finite = [value for value in numbers if math.isfinite(value)]
    return NumericSummary(
        min=min(finite) if finite else None,
        max=max(finite) if finite else None,
        mean=sum(finite) / len(finite) if finite else None,
        nan_count=nan_count,
        inf_count=inf_count,
    )


def _json_number(value: int | float) -> int | float | str:
    if isinstance(value, int):
        return value if -(2**63) <= value <= 2**64 - 1 else str(value)
    return value if math.isfinite(value) else str(value)


def _json_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return _json_number(value)
    return str(value)[:128]


class TraceRecorder:
    """Write validated API calls as deterministic JSON Lines records."""

    def __init__(
        self,
        path: str | Path,
        *,
        framework: Framework,
        framework_version: str,
        execution_mode: ExecutionMode,
        run_id: str | None = None,
        overwrite: bool = False,
        include_traceback: bool = False,
        max_tensor_elements: int = DEFAULT_MAX_TENSOR_ELEMENTS,
        source_root: str | Path | None = None,
    ) -> None:
        if framework not in (Framework.PYTORCH, Framework.MINDSPORE):
            raise ValueError("framework must be pytorch or mindspore")
        if not framework_version.strip():
            raise ValueError("framework_version must not be empty")
        if max_tensor_elements <= 0:
            raise ValueError("max_tensor_elements must be greater than zero")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.framework = framework
        self.framework_version = framework_version
        self.execution_mode = execution_mode
        self.run_id = run_id or uuid.uuid4().hex
        self.include_traceback = include_traceback
        self.max_tensor_elements = max_tensor_elements
        self.source_root = Path(source_root or Path.cwd()).resolve()
        self._stream = self.path.open("w" if overwrite else "x", encoding="utf-8")
        self._call_index = 0
        self._lock = threading.Lock()

    def call(
        self,
        api: str,
        function: Callable[..., T],
        *args: Any,
        location: SourceLocation | None = None,
        trace_metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> T:
        """Invoke a callable, record its normalized result, and preserve exceptions."""

        if not api.strip():
            raise ValueError("api must not be empty")
        resolved_location = _normalize_location(
            location or _caller_location(self.source_root), self.source_root
        )
        arguments = [
            ApiArgument(position=index, value=self._summarize(value))
            for index, value in enumerate(args)
        ]
        arguments.extend(
            ApiArgument(
                name=name,
                position=len(args) + index,
                value=self._summarize(value),
            )
            for index, (name, value) in enumerate(kwargs.items())
        )
        started = time.perf_counter()
        try:
            output = function(*args, **kwargs)
        except Exception as error:
            runtime_error = RuntimeErrorRecord(
                error_type=type(error).__name__,
                message=_redact(str(error), self.source_root) or type(error).__name__,
                traceback=_redact(
                    "".join(traceback.format_exception(error)), self.source_root
                )
                if self.include_traceback
                else None,
            )
            self._write(
                api,
                resolved_location,
                arguments,
                None,
                runtime_error,
                started,
                trace_metadata,
            )
            raise
        self._write(
            api,
            resolved_location,
            arguments,
            self._summarize(output),
            None,
            started,
            trace_metadata,
        )
        return output

    def _summarize(self, value: Any) -> ValueSummary:
        return summarize_value(value, max_tensor_elements=self.max_tensor_elements)

    def _write(
        self, api, location, arguments, output, error, started, trace_metadata
    ) -> None:
        metadata = dict(trace_metadata or {})
        if "duration_ms" in metadata:
            raise ValueError("trace metadata must not override duration_ms")
        metadata["duration_ms"] = round((time.perf_counter() - started) * 1000, 6)
        with self._lock:
            record = ApiTraceRecord(
                schema_version=SCHEMA_VERSION,
                record_kind=RecordKind.API_TRACE,
                run_id=self.run_id,
                framework=self.framework,
                framework_version=self.framework_version,
                execution_mode=self.execution_mode,
                location=location,
                api=api,
                call_index=self._call_index,
                arguments=arguments,
                output=output,
                error=error,
                metadata=metadata,
            )
            record.validate()
            self._stream.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
            self._stream.write("\n")
            self._stream.flush()
            self._call_index += 1

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> "TraceRecorder":
        return self

    def __exit__(self, _error_type, _error, _traceback) -> None:
        self.close()


def _caller_location(source_root: Path) -> SourceLocation:
    frame = inspect.currentframe()
    try:
        caller = frame.f_back.f_back if frame and frame.f_back else None
        if caller is None:
            return SourceLocation(file="<unknown>", line=1, column=0)
        path = Path(caller.f_code.co_filename).resolve()
        try:
            file_name = str(path.relative_to(source_root))
        except ValueError:
            file_name = path.name
        return SourceLocation(file=file_name, line=caller.f_lineno, column=0)
    finally:
        del frame


def _normalize_location(location: SourceLocation, source_root: Path) -> SourceLocation:
    path = Path(location.file)
    if not path.is_absolute():
        return location
    try:
        file_name = str(path.resolve().relative_to(source_root))
    except ValueError:
        file_name = path.name
    return SourceLocation(
        file=file_name,
        line=location.line,
        column=location.column,
        end_line=location.end_line,
        end_column=location.end_column,
    )


def _redact(text: str, source_root: Path | None = None) -> str:
    redacted = _SECRET_PATTERN.sub(r"\1\2[REDACTED]", text)
    if source_root is not None:
        redacted = redacted.replace(str(source_root), "<workspace>")
    return redacted[:16_384]
