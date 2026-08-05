"""Versioned JSON schema shared by migration analysis and runtime tracing.

This module intentionally uses only the Python standard library so the bridge can
validate migration records before optional framework dependencies are installed.
Source lines are one-based and source columns are zero-based, matching Python AST.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from math import isfinite
from typing import Any, TypeVar

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_MAJOR = 1


class SchemaError(ValueError):
    """Raised when a migration record violates the shared protocol."""


class StringEnum(str, Enum):
    @classmethod
    def parse(cls, value: str):
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


class RecordKind(StringEnum):
    API_TRACE = "api_trace"
    DIAGNOSTIC = "diagnostic"
    TRACE_COMPARISON = "trace_comparison"
    MSPROBE_IMPORT_REPORT = "msprobe_import_report"
    REWRITE_PLAN = "rewrite_plan"
    REWRITE_APPLY_REPORT = "rewrite_apply_report"
    REWRITE_ROLLBACK_REPORT = "rewrite_rollback_report"
    UNKNOWN = "unknown"


class Framework(StringEnum):
    PYTORCH = "pytorch"
    MINDSPORE = "mindspore"
    FRAMEWORK_NEUTRAL = "framework_neutral"
    UNKNOWN = "unknown"


class ExecutionMode(StringEnum):
    EAGER = "eager"
    PYNATIVE = "py_native"
    GRAPH = "graph"
    STATIC_ANALYSIS = "static_analysis"
    UNKNOWN = "unknown"


class ValueKind(StringEnum):
    TENSOR = "tensor"
    SCALAR = "scalar"
    BOOLEAN = "boolean"
    STRING = "string"
    SEQUENCE = "sequence"
    MAPPING = "mapping"
    NONE = "none"
    UNKNOWN = "unknown"


class DiagnosticCategory(StringEnum):
    MISSING_OPERATOR = "missing_operator"
    UNMAPPED_API = "unmapped_api"
    PARAMETER_MISMATCH = "parameter_mismatch"
    DEFAULT_VALUE_MISMATCH = "default_value_mismatch"
    DTYPE_MISMATCH = "dtype_mismatch"
    SHAPE_MISMATCH = "shape_mismatch"
    RETURN_STRUCTURE_MISMATCH = "return_structure_mismatch"
    VALUE_MISMATCH = "value_mismatch"
    GRADIENT_MISMATCH = "gradient_mismatch"
    RANDOMNESS_MISMATCH = "randomness_mismatch"
    GRAPH_COMPILE_FAILURE = "graph_compile_failure"
    DEVICE_UNSUPPORTED = "device_unsupported"
    RUNTIME_ERROR = "runtime_error"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    UNKNOWN = "unknown"


class Severity(StringEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class EvidenceKind(StringEnum):
    STATIC_ANALYSIS = "static_analysis"
    RUNTIME_TRACE = "runtime_trace"
    MAPPING_KNOWLEDGE = "mapping_knowledge"
    EXECUTION_ERROR = "execution_error"
    DOCUMENTATION = "documentation"
    DIFF_VALIDATION = "diff_validation"
    UNKNOWN = "unknown"


def ensure_compatible_schema(version: str) -> None:
    parts = version.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise SchemaError(f"invalid schema version: {version}")
    major = int(parts[0])
    if major != SUPPORTED_SCHEMA_MAJOR:
        raise SchemaError(
            f"unsupported schema major version {major}; "
            f"supported major version is {SUPPORTED_SCHEMA_MAJOR}"
        )


def _require_non_empty(field_name: str, value: str) -> None:
    if not value.strip():
        raise SchemaError(f"{field_name} must not be empty")


@dataclass
class SourceLocation:
    file: str
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourceLocation":
        return cls(**value)

    def validate(self) -> None:
        _require_non_empty("source location file", self.file)
        if self.line < 1:
            raise SchemaError("source location line is one-based")
        if self.column < 0:
            raise SchemaError("source location column must be non-negative")
        if self.end_line is not None and self.end_line < self.line:
            raise SchemaError("source location end_line must not precede line")
        if (
            self.end_line == self.line
            and self.end_column is not None
            and self.end_column < self.column
        ):
            raise SchemaError(
                "source location end_column must not precede column on the same line"
            )
        if (self.end_line is None) != (self.end_column is None):
            raise SchemaError(
                "source location end_line and end_column must be provided together"
            )


@dataclass
class NumericSummary:
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    nan_count: int = 0
    inf_count: int = 0


@dataclass
class ValueSummary:
    kind: ValueKind
    dtype: str | None = None
    shape: list[int | None] = field(default_factory=list)
    numeric: NumericSummary | None = None
    preview: Any | None = None
    children: list["ValueSummary"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ValueSummary":
        numeric = value.get("numeric")
        return cls(
            kind=ValueKind.parse(value["kind"]),
            dtype=value.get("dtype"),
            shape=list(value.get("shape", [])),
            numeric=NumericSummary(**numeric) if numeric is not None else None,
            preview=value.get("preview"),
            children=[cls.from_dict(child) for child in value.get("children", [])],
        )

    def validate(self) -> None:
        if any(dimension is not None and dimension < 0 for dimension in self.shape):
            raise SchemaError(
                "shape dimensions must be non-negative; use null for unknown dimensions"
            )
        if self.dtype is not None:
            _require_non_empty("dtype", self.dtype)
        for child in self.children:
            child.validate()


@dataclass
class ApiArgument:
    position: int
    value: ValueSummary
    name: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ApiArgument":
        return cls(
            name=value.get("name"),
            position=value["position"],
            value=ValueSummary.from_dict(value["value"]),
        )


@dataclass
class RuntimeErrorRecord:
    error_type: str
    message: str
    traceback: str | None = None


@dataclass
class ApiTraceRecord:
    schema_version: str
    record_kind: RecordKind
    run_id: str
    framework: Framework
    framework_version: str
    execution_mode: ExecutionMode
    location: SourceLocation
    api: str
    call_index: int
    arguments: list[ApiArgument] = field(default_factory=list)
    output: ValueSummary | None = None
    error: RuntimeErrorRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ApiTraceRecord":
        output = value.get("output")
        error = value.get("error")
        return cls(
            schema_version=value["schema_version"],
            record_kind=RecordKind.parse(value["record_kind"]),
            run_id=value["run_id"],
            framework=Framework.parse(value["framework"]),
            framework_version=value["framework_version"],
            execution_mode=ExecutionMode.parse(value["execution_mode"]),
            location=SourceLocation.from_dict(value["location"]),
            api=value["api"],
            call_index=value["call_index"],
            arguments=[ApiArgument.from_dict(item) for item in value.get("arguments", [])],
            output=ValueSummary.from_dict(output) if output is not None else None,
            error=RuntimeErrorRecord(**error) if error is not None else None,
            metadata=dict(value.get("metadata", {})),
        )

    def validate(self) -> None:
        ensure_compatible_schema(self.schema_version)
        if self.record_kind != RecordKind.API_TRACE:
            raise SchemaError("record_kind must be api_trace")
        _require_non_empty("run_id", self.run_id)
        _require_non_empty("framework_version", self.framework_version)
        _require_non_empty("api", self.api)
        self.location.validate()
        for argument in self.arguments:
            argument.value.validate()
        if self.output is not None:
            self.output.validate()
        if self.output is not None and self.error is not None:
            raise SchemaError("api trace must not contain both output and error")
        if self.output is None and self.error is None:
            raise SchemaError("api trace must contain either output or error")
        if self.error is not None:
            _require_non_empty("error_type", self.error.error_type)
            _require_non_empty("error message", self.error.message)

    def to_dict(self) -> dict[str, Any]:
        return _to_json_value(self)


@dataclass
class DiagnosticEvidence:
    kind: EvidenceKind
    message: str
    location: SourceLocation | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiagnosticEvidence":
        location = value.get("location")
        return cls(
            kind=EvidenceKind.parse(value["kind"]),
            message=value["message"],
            location=SourceLocation.from_dict(location) if location is not None else None,
            data=dict(value.get("data", {})),
        )


@dataclass
class DiagnosticRecord:
    schema_version: str
    record_kind: RecordKind
    diagnostic_id: str
    run_id: str
    category: DiagnosticCategory
    severity: Severity
    confidence: float
    summary: str
    explanation: str
    location: SourceLocation | None = None
    source_api: str | None = None
    target_api: str | None = None
    evidence: list[DiagnosticEvidence] = field(default_factory=list)
    suggested_action: str | None = None
    verified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiagnosticRecord":
        location = value.get("location")
        return cls(
            schema_version=value["schema_version"],
            record_kind=RecordKind.parse(value["record_kind"]),
            diagnostic_id=value["diagnostic_id"],
            run_id=value["run_id"],
            category=DiagnosticCategory.parse(value["category"]),
            severity=Severity.parse(value["severity"]),
            confidence=value["confidence"],
            summary=value["summary"],
            explanation=value["explanation"],
            location=SourceLocation.from_dict(location) if location is not None else None,
            source_api=value.get("source_api"),
            target_api=value.get("target_api"),
            evidence=[
                DiagnosticEvidence.from_dict(item) for item in value.get("evidence", [])
            ],
            suggested_action=value.get("suggested_action"),
            verified=value.get("verified", False),
            metadata=dict(value.get("metadata", {})),
        )

    def validate(self) -> None:
        ensure_compatible_schema(self.schema_version)
        if self.record_kind != RecordKind.DIAGNOSTIC:
            raise SchemaError("record_kind must be diagnostic")
        _require_non_empty("diagnostic_id", self.diagnostic_id)
        _require_non_empty("run_id", self.run_id)
        _require_non_empty("summary", self.summary)
        _require_non_empty("explanation", self.explanation)
        if not isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise SchemaError(
                "diagnostic confidence must be a finite value between 0 and 1"
            )
        if self.location is not None:
            self.location.validate()
        if not self.evidence:
            raise SchemaError("diagnostic must contain at least one evidence item")
        for evidence in self.evidence:
            _require_non_empty("evidence message", evidence.message)
            if evidence.location is not None:
                evidence.location.validate()
        if self.verified and not any(
            evidence.kind == EvidenceKind.DIFF_VALIDATION for evidence in self.evidence
        ):
            raise SchemaError(
                "verified diagnostic must contain diff_validation evidence"
            )

    def to_dict(self) -> dict[str, Any]:
        return _to_json_value(self)


T = TypeVar("T")


def _to_json_value(value: T) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _to_json_value(item)
            for key, item in asdict(value).items()
            if item is not None
        }
    if isinstance(value, dict):
        return {key: _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    return value
