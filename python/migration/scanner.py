"""Deterministic Python AST scanner for PyTorch migration candidates."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import tokenize
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from migration.schema import SCHEMA_VERSION
from migration.schema import SchemaError, ensure_compatible_schema
from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase, MappingResolution
from migration.cli_io import configure_utf8_stdio

DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024
IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

TENSOR_METHODS = {
    "backward",
    "bool",
    "chunk",
    "clone",
    "contiguous",
    "cpu",
    "cuda",
    "detach",
    "dim",
    "double",
    "expand",
    "flatten",
    "float",
    "half",
    "item",
    "long",
    "masked_fill",
    "max",
    "mean",
    "min",
    "numpy",
    "permute",
    "repeat",
    "reshape",
    "requires_grad_",
    "short",
    "sigmoid",
    "size",
    "softmax",
    "split",
    "squeeze",
    "sum",
    "to",
    "transpose",
    "type",
    "unsqueeze",
    "view",
}

NON_TENSOR_API_PREFIXES = (
    "torch.nn.",
    "torch.optim.",
    "torch.utils.",
    "torch.cuda.",
    "torch.distributed.",
)


@dataclass(frozen=True)
class ScanLocation:
    file: str
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True)
class ScanFinding:
    finding_id: str
    api: str
    location: ScanLocation
    call_kind: str
    confidence: float
    risk_level: str
    mapping: MappingResolution
    expression: str
    positional_argument_count: int
    keyword_arguments: list[str]


@dataclass(frozen=True)
class ScanIssue:
    file: str
    kind: str
    message: str
    line: int | None = None
    column: int | None = None


@dataclass
class ScanReport:
    schema_version: str
    record_kind: str
    root: str
    files_discovered: int
    files_scanned: int
    findings: list[ScanFinding] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        ensure_compatible_schema(self.schema_version)
        if self.record_kind != "scan_report":
            raise SchemaError("record_kind must be scan_report")
        if not self.root.strip():
            raise SchemaError("root must not be empty")
        if self.files_scanned > self.files_discovered:
            raise SchemaError("files_scanned must not exceed files_discovered")

        api_counts = Counter()
        call_counts = Counter()
        mapping_counts = Counter()
        for finding in self.findings:
            if not finding.finding_id.strip():
                raise SchemaError("finding_id must not be empty")
            if not finding.api.strip():
                raise SchemaError("api must not be empty")
            if not finding.expression.strip():
                raise SchemaError("expression must not be empty")
            if finding.location.line < 1 or finding.location.column < 0:
                raise SchemaError("scan finding location is invalid")
            if not 0.0 <= finding.confidence <= 1.0:
                raise SchemaError("scan finding confidence must be between 0 and 1")
            api_counts[finding.api] += 1
            call_counts[finding.call_kind] += 1
            mapping_counts[finding.mapping.status] += 1
            if finding.mapping.source_api != finding.api:
                raise SchemaError("mapping source_api must match scan finding api")
            expected_risk = {
                "exact": "low",
                "difference": "medium",
                "unsupported": "high",
                "unknown": "high",
            }[finding.mapping.status]
            if finding.risk_level != expected_risk:
                raise SchemaError("risk_level does not match mapping status")

        for issue in self.issues:
            if not issue.file.strip() or not issue.kind.strip() or not issue.message.strip():
                raise SchemaError("scan issue fields must not be empty")
            if issue.line is None and issue.column is not None:
                raise SchemaError("scan issue column requires a corresponding line")

        expected = {
            "finding_count": len(self.findings),
            "unique_api_count": len(api_counts),
            "direct_call_count": call_counts["function"],
            "tensor_method_count": call_counts["tensor_method"],
            "dynamic_call_count": call_counts["dynamic"],
            "issue_count": len(self.issues),
            "api_counts": dict(sorted(api_counts.items())),
            "mapping_counts": dict(sorted(mapping_counts.items())),
        }
        if self.summary != expected:
            raise SchemaError("scan summary does not match findings and issues")


@dataclass
class _Scope:
    aliases: dict[str, str] = field(default_factory=dict)
    tensors: set[str] = field(default_factory=set)
    shadowed: set[str] = field(default_factory=set)


class TorchCallScanner(ast.NodeVisitor):
    def __init__(self, source: str, relative_file: str):
        self.source = source
        self.relative_file = relative_file
        self.findings: list[ScanFinding] = []
        self._scopes = [_Scope()]
        self._call_index = 0

    @property
    def _scope(self) -> _Scope:
        return self._scopes[-1]

    def _lookup_alias(self, name: str) -> str | None:
        for scope in reversed(self._scopes):
            if name in scope.aliases:
                return scope.aliases[name]
            if name in scope.shadowed:
                return None
        return None

    def _is_tensor_name(self, name: str) -> bool:
        for scope in reversed(self._scopes):
            if name in scope.tensors:
                return True
            if name in scope.shadowed or name in scope.aliases:
                return False
        return False

    def _bind_alias(self, name: str, canonical: str) -> None:
        self._scope.aliases[name] = canonical
        self._scope.tensors.discard(name)
        self._scope.shadowed.discard(name)

    def _bind_tensor(self, name: str) -> None:
        self._scope.aliases.pop(name, None)
        self._scope.tensors.add(name)
        self._scope.shadowed.add(name)

    def _shadow(self, name: str) -> None:
        self._scope.aliases.pop(name, None)
        self._scope.tensors.discard(name)
        self._scope.shadowed.add(name)

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            bound_name = item.asname or item.name.split(".", 1)[0]
            if not item.name.startswith("torch"):
                self._shadow(bound_name)
                continue
            canonical = item.name if item.asname else bound_name
            self._bind_alias(bound_name, canonical)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level != 0 or not node.module or not node.module.startswith("torch"):
            for item in node.names:
                if item.name != "*":
                    self._shadow(item.asname or item.name)
            return
        for item in node.names:
            if item.name == "*":
                continue
            bound_name = item.asname or item.name
            self._bind_alias(bound_name, f"{node.module}.{item.name}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        self._shadow(node.name)
        self._scopes.append(_Scope())
        arguments = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        for argument in arguments:
            if self._annotation_is_tensor(argument.annotation):
                self._bind_tensor(argument.arg)
            else:
                self._shadow(argument.arg)
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        self._shadow(node.name)
        self._scopes.append(_Scope())
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._scopes.append(_Scope())
        for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            self._shadow(argument.arg)
        self.visit(node.body)
        self._scopes.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        is_tensor = self._expression_is_tensor(node.value)
        for target in node.targets:
            self._bind_assignment_target(target, is_tensor)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        is_tensor = self._annotation_is_tensor(node.annotation) or (
            node.value is not None and self._expression_is_tensor(node.value)
        )
        self._bind_assignment_target(node.target, is_tensor)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self._bind_assignment_target(node.target, False)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_assignment_target(node.target, self._expression_is_tensor(node.value))

    def visit_Call(self, node: ast.Call) -> None:
        canonical, call_kind, confidence = self._resolve_call(node)
        if canonical is not None:
            self._record_call(node, canonical, call_kind, confidence)
        self.generic_visit(node)

    def _resolve_call(self, node: ast.Call) -> tuple[str | None, str, float]:
        direct = self._canonical_name(node.func)
        if direct is not None and direct.startswith("torch"):
            return direct, "function", 1.0

        if isinstance(node.func, ast.Attribute):
            if node.func.attr in TENSOR_METHODS and self._expression_is_tensor(node.func.value):
                return f"torch.Tensor.{node.func.attr}", "tensor_method", 0.9

        dynamic = self._resolve_getattr_call(node.func)
        if dynamic is not None:
            return dynamic, "dynamic", 0.5 if dynamic.endswith("<dynamic>") else 0.95

        return None, "unknown", 0.0

    def _resolve_getattr_call(self, function: ast.expr) -> str | None:
        if not isinstance(function, ast.Call) or not isinstance(function.func, ast.Name):
            return None
        if function.func.id != "getattr" or len(function.args) < 2:
            return None
        owner = self._canonical_name(function.args[0])
        if owner is None or not owner.startswith("torch"):
            return None
        attribute = function.args[1]
        if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
            return f"{owner}.{attribute.value}"
        return f"{owner}.<dynamic>"

    def _canonical_name(self, node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Name):
            return self._lookup_alias(node.id)
        if isinstance(node, ast.Attribute):
            parent = self._canonical_name(node.value)
            if parent is not None:
                return f"{parent}.{node.attr}"
        return None

    def _expression_is_tensor(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return self._is_tensor_name(node.id)
        if isinstance(node, ast.Attribute):
            return node.attr in {"data", "grad"} and self._expression_is_tensor(node.value)
        if isinstance(node, (ast.Subscript, ast.UnaryOp, ast.BinOp, ast.BoolOp, ast.Compare)):
            return any(self._expression_is_tensor(child) for child in ast.iter_child_nodes(node))
        if isinstance(node, ast.Call):
            canonical, call_kind, _ = self._resolve_call(node)
            if call_kind == "tensor_method":
                return node.func.attr not in {"backward", "dim", "item", "numpy", "size"}
            return canonical is not None and self._api_likely_returns_tensor(canonical)
        return False

    @staticmethod
    def _api_likely_returns_tensor(canonical: str) -> bool:
        if canonical == "torch.Tensor" or canonical == "torch.tensor":
            return True
        if canonical.startswith("torch.nn.functional."):
            return True
        if canonical.startswith(NON_TENSOR_API_PREFIXES):
            return False
        return canonical.startswith("torch.") and not canonical.endswith("<dynamic>")

    def _annotation_is_tensor(self, annotation: ast.AST | None) -> bool:
        canonical = self._canonical_name(annotation)
        return canonical in {"torch.Tensor", "torch.TensorType"}

    def _bind_assignment_target(self, target: ast.AST, is_tensor: bool) -> None:
        if isinstance(target, ast.Name):
            if is_tensor:
                self._bind_tensor(target.id)
            else:
                self._shadow(target.id)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind_assignment_target(item, is_tensor)

    def _record_call(
        self, node: ast.Call, canonical: str, call_kind: str, confidence: float
    ) -> None:
        self._call_index += 1
        expression = ast.get_source_segment(self.source, node) or canonical
        expression = " ".join(expression.split())[:512]
        location = ScanLocation(
            file=self.relative_file,
            line=node.lineno,
            column=node.col_offset,
            end_line=getattr(node, "end_lineno", None),
            end_column=getattr(node, "end_col_offset", None),
        )
        identity = (
            f"{self.relative_file}:{node.lineno}:{node.col_offset}:"
            f"{canonical}:{self._call_index}"
        )
        finding_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        keyword_arguments = [
            keyword.arg if keyword.arg is not None else "**" for keyword in node.keywords
        ]
        self.findings.append(
            ScanFinding(
                finding_id=finding_id,
                api=canonical,
                location=location,
                call_kind=call_kind,
                confidence=confidence,
                risk_level="unclassified",
                mapping=MappingResolution(
                    source_api=canonical,
                    target_api=None,
                    status="unknown",
                    differences=[],
                    notes="mapping enrichment pending",
                    evidence_urls=[],
                    source_framework_version="unknown",
                    target_framework_version="unknown",
                    knowledge_version="unknown",
                ),
                expression=expression,
                positional_argument_count=len(node.args),
                keyword_arguments=keyword_arguments,
            )
        )


def _iter_python_files(root: Path) -> Iterable[tuple[Path, str]]:
    if root.is_file():
        if root.suffix == ".py":
            yield root, root.name
        return

    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in IGNORED_DIRECTORIES)
        directory_path = Path(directory)
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            file_path = directory_path / name
            relative = file_path.relative_to(root).as_posix()
            yield file_path, relative


def _read_python_source(path: Path) -> str:
    with tokenize.open(path) as source_file:
        return source_file.read()


def scan_path(
    path: str | Path,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE,
) -> ScanReport:
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"scan path does not exist: {root}")
    if not root.is_file() and not root.is_dir():
        raise ValueError(f"scan path must be a file or directory: {root}")
    if root.is_file() and root.suffix != ".py":
        raise ValueError(f"scan file must use the .py extension: {root}")
    if max_file_bytes <= 0:
        raise ValueError("max_file_bytes must be greater than zero")
    knowledge = MappingKnowledgeBase.load(knowledge_base)

    candidates = list(_iter_python_files(root))
    findings: list[ScanFinding] = []
    issues: list[ScanIssue] = []
    files_scanned = 0

    for file_path, relative_file in candidates:
        try:
            file_size = file_path.stat().st_size
            if file_size > max_file_bytes:
                issues.append(
                    ScanIssue(
                        file=relative_file,
                        kind="file_too_large",
                        message=f"file size {file_size} exceeds limit {max_file_bytes}",
                    )
                )
                continue
            source = _read_python_source(file_path)
            tree = ast.parse(source, filename=relative_file, type_comments=True)
            scanner = TorchCallScanner(source, relative_file)
            scanner.visit(tree)
            findings.extend(scanner.findings)
            files_scanned += 1
        except SyntaxError as error:
            issues.append(
                ScanIssue(
                    file=relative_file,
                    kind="syntax_error",
                    message=error.msg,
                    line=error.lineno,
                    column=(error.offset - 1) if error.offset else None,
                )
            )
        except (OSError, UnicodeError, ValueError) as error:
            issues.append(
                ScanIssue(file=relative_file, kind="read_error", message=str(error))
            )

    findings.sort(
        key=lambda item: (
            item.location.file,
            item.location.line,
            item.location.column,
            item.api,
        )
    )
    enriched_findings = []
    for finding in findings:
        mapping = knowledge.resolve(finding.api)
        risk_level = {
            "exact": "low",
            "difference": "medium",
            "unsupported": "high",
            "unknown": "high",
        }[mapping.status]
        enriched_findings.append(
            replace(finding, mapping=mapping, risk_level=risk_level)
        )
    findings = enriched_findings
    issues.sort(key=lambda item: (item.file, item.line or 0, item.column or 0))
    api_counts = Counter(finding.api for finding in findings)
    mapping_counts = Counter(finding.mapping.status for finding in findings)
    summary = {
        "finding_count": len(findings),
        "unique_api_count": len(api_counts),
        "direct_call_count": sum(item.call_kind == "function" for item in findings),
        "tensor_method_count": sum(item.call_kind == "tensor_method" for item in findings),
        "dynamic_call_count": sum(item.call_kind == "dynamic" for item in findings),
        "issue_count": len(issues),
        "api_counts": dict(sorted(api_counts.items())),
        "mapping_counts": dict(sorted(mapping_counts.items())),
    }
    return ScanReport(
        schema_version=SCHEMA_VERSION,
        record_kind="scan_report",
        root=".",
        files_discovered=len(candidates),
        files_scanned=files_scanned,
        findings=findings,
        issues=issues,
        summary=summary,
    )


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Python file or project directory to scan")
    parser.add_argument(
        "--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    arguments = parser.parse_args(argv)

    try:
        report = scan_path(
            arguments.path, arguments.max_file_bytes, arguments.knowledge_base
        )
        report.validate()
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    indent = 2 if arguments.pretty else None
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True))
    return 0 if not report.issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
