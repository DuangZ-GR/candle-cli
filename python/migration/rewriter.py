"""Plan minimal deterministic PyTorch-to-MindSpore API name rewrites."""

from __future__ import annotations

import ast
import argparse
import difflib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import tokenize
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase
from migration.cli_io import configure_utf8_stdio
from migration.scanner import (
    DEFAULT_MAX_FILE_BYTES,
    TorchCallScanner,
    _iter_python_files,
)

DEFAULT_VALIDATION_TIMEOUT_SECONDS = 300.0
MAX_VALIDATION_OUTPUT_CHARACTERS = 16_384
DEFAULT_REWRITE_RULES = (
    Path(__file__).resolve().parents[2]
    / "knowledge"
    / "rewrites"
    / "mindspore-2.9.0-pytorch-2.1.json"
)


class RewriteValidationError(RuntimeError):
    """Raised after a validation command fails and the patch is rolled back."""


@dataclass(frozen=True)
class RewriteRuleKnowledge:
    """Versioned, evidence-backed semantic rules used after an API is mapped."""

    dtype_constants: dict[str, str]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_REWRITE_RULES) -> "RewriteRuleKnowledge":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema_version") != "1.0":
            raise ValueError("unsupported rewrite rule schema_version")
        constants = document.get("dtype_constants")
        if not isinstance(constants, dict) or not constants:
            raise ValueError("rewrite rules must define dtype_constants")
        validated: dict[str, str] = {}
        for source, target in constants.items():
            if not (
                isinstance(source, str)
                and source.startswith("torch.")
                and isinstance(target, str)
                and target.startswith("mindspore.")
            ):
                raise ValueError("rewrite rule contains an invalid dtype mapping")
            validated[source] = target
        return cls(dtype_constants=validated)


@dataclass(frozen=True)
class TextEdit:
    start: int
    end: int
    replacement: str
    source_api: str
    target_api: str
    mapping_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "replacement": self.replacement,
            "source_api": self.source_api,
            "target_api": self.target_api,
            "mapping_status": self.mapping_status,
        }


@dataclass
class FileRewrite:
    path: Path
    relative_path: str
    original_source: str
    patched_source: str
    edits: list[TextEdit]
    encoding: str = "utf-8"

    @property
    def original_bytes(self) -> bytes:
        return self.original_source.encode(self.encoding)

    @property
    def patched_bytes(self) -> bytes:
        return self.patched_source.encode(self.encoding)

    @property
    def original_sha256(self) -> str:
        return hashlib.sha256(self.original_bytes).hexdigest()

    @property
    def patched_sha256(self) -> str:
        return hashlib.sha256(self.patched_bytes).hexdigest()

    def unified_diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.original_source.splitlines(keepends=True),
                self.patched_source.splitlines(keepends=True),
                fromfile=f"a/{self.relative_path}",
                tofile=f"b/{self.relative_path}",
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.relative_path,
            "original_sha256": self.original_sha256,
            "patched_sha256": self.patched_sha256,
            "encoding": self.encoding,
            "edits": [edit.to_dict() for edit in self.edits],
            "diff": self.unified_diff(),
        }


@dataclass
class RewritePlan:
    root: Path
    files: list[FileRewrite] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        edits = [edit for file in self.files for edit in file.edits]
        mapping_edits = [edit for edit in edits if edit.source_api != "<import>"]
        return {
            "schema_version": "1.0",
            "record_kind": "rewrite_plan",
            "root": ".",
            "files_changed": len(self.files),
            "edit_count": len(edits),
            "mapping_counts": {
                status: sum(edit.mapping_status == status for edit in mapping_edits)
                for status in ("exact", "difference")
            },
            "files": [file.to_dict() for file in self.files],
            "issues": self.issues,
        }


class _RewriteScanner(TorchCallScanner):
    def __init__(
        self,
        source: str,
        relative_file: str,
        knowledge: MappingKnowledgeBase,
        rewrite_rules: RewriteRuleKnowledge,
        include_differences: bool,
        mindspore_name: str,
    ) -> None:
        super().__init__(source, relative_file)
        self.knowledge = knowledge
        self.rewrite_rules = rewrite_rules
        self.include_differences = include_differences
        self.mindspore_name = mindspore_name
        self.unsupported_parameters = set(
            knowledge.payload.get("common_unsupported_parameters", [])
        )
        self.edits: list[TextEdit] = []

    def _record_call(self, node, canonical, call_kind, confidence) -> None:
        if call_kind != "function" or confidence < 1.0:
            return
        mapping = self.knowledge.resolve(canonical)
        if mapping.target_api is None or mapping.status not in {"exact", "difference"}:
            return
        if mapping.status == "difference" and not self.include_differences:
            return
        if any(
            keyword.arg in self.unsupported_parameters for keyword in node.keywords
        ):
            return
        target = _target_name(mapping.target_api, self.mindspore_name)
        start = _source_offset(self.source, node.func.lineno, node.func.col_offset)
        end = _source_offset(
            self.source,
            node.func.end_lineno,
            node.func.end_col_offset,
        )
        if self.source[start:end] == target:
            return
        self.edits.append(
            TextEdit(
                start=start,
                end=end,
                replacement=target,
                source_api=canonical,
                target_api=mapping.target_api,
                mapping_status=mapping.status,
            )
        )
        for keyword in node.keywords:
            if keyword.arg != "dtype":
                continue
            source_dtype = self._canonical_name(keyword.value)
            target_dtype = self.rewrite_rules.dtype_constants.get(source_dtype or "")
            if target_dtype is None:
                continue
            dtype_start = _source_offset(
                self.source, keyword.value.lineno, keyword.value.col_offset
            )
            dtype_end = _source_offset(
                self.source,
                keyword.value.end_lineno,
                keyword.value.end_col_offset,
            )
            dtype_target = _target_name(target_dtype, self.mindspore_name)
            self.edits.append(
                TextEdit(
                    start=dtype_start,
                    end=dtype_end,
                    replacement=dtype_target,
                    source_api=source_dtype or "",
                    target_api=target_dtype,
                    mapping_status="exact",
                )
            )


def plan_rewrite(
    path: str | Path,
    *,
    knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE,
    rewrite_rules: str | Path = DEFAULT_REWRITE_RULES,
    include_differences: bool = False,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> RewritePlan:
    requested = Path(path)
    if not requested.exists():
        raise FileNotFoundError(f"rewrite path does not exist: {requested}")
    if not requested.is_file() and not requested.is_dir():
        raise ValueError("rewrite path must be a Python file or directory")
    if requested.is_file() and requested.suffix != ".py":
        raise ValueError("rewrite file must use the .py extension")
    if max_file_bytes <= 0:
        raise ValueError("max_file_bytes must be greater than zero")
    requested = requested.resolve()
    root = requested.parent if requested.is_file() else requested
    knowledge = MappingKnowledgeBase.load(knowledge_base)
    semantic_rules = RewriteRuleKnowledge.load(rewrite_rules)
    plan = RewritePlan(root=root)
    for file_path, relative_path in _iter_python_files(requested):
        try:
            resolved_file = file_path.resolve(strict=True)
            if file_path.is_symlink() or not resolved_file.is_relative_to(root):
                plan.issues.append(
                    {"file": relative_path, "kind": "unsafe_path", "message": "symbolic link or path escape rejected"}
                )
                continue
            if resolved_file.stat().st_size > max_file_bytes:
                plan.issues.append(
                    {"file": relative_path, "kind": "file_too_large", "message": f"file exceeds {max_file_bytes} byte limit"}
                )
                continue
            source, encoding = _read_source_preserving_newlines(resolved_file)
            tree = ast.parse(source, filename=relative_path, type_comments=True)
            mindspore_name = _mindspore_binding(tree)
            scanner = _RewriteScanner(
                source,
                relative_path,
                knowledge,
                semantic_rules,
                include_differences,
                mindspore_name or "mindspore",
            )
            scanner.visit(tree)
            edits = scanner.edits
            if edits and mindspore_name is None:
                insertion = _import_insertion_offset(source, tree)
                edits.append(
                    TextEdit(
                        start=insertion,
                        end=insertion,
                        replacement=f"import mindspore{_newline(source)}",
                        source_api="<import>",
                        target_api="mindspore",
                        mapping_status="exact",
                    )
                )
            if not edits:
                continue
            patched = _apply_edits(source, edits)
            ast.parse(patched, filename=relative_path, type_comments=True)
            plan.files.append(
                FileRewrite(
                    path=resolved_file,
                    relative_path=relative_path,
                    original_source=source,
                    patched_source=patched,
                    edits=sorted(edits, key=lambda edit: (edit.start, edit.end)),
                    encoding=encoding,
                )
            )
        except SyntaxError as error:
            plan.issues.append(
                {
                    "file": relative_path,
                    "kind": "syntax_error",
                    "message": error.msg,
                }
            )
        except (OSError, UnicodeError, ValueError) as error:
            plan.issues.append(
                {"file": relative_path, "kind": "read_error", "message": str(error)}
            )
    return plan


def apply_plan(
    plan: RewritePlan,
    *,
    allow_partial: bool = False,
    validation_command: list[str] | None = None,
    validation_timeout: float = DEFAULT_VALIDATION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Atomically apply a previewed plan and persist rollback material."""

    if not plan.files:
        raise ValueError("rewrite plan contains no file changes")
    if plan.issues and not allow_partial:
        raise ValueError("rewrite plan contains issues; refuse partial apply")
    if validation_timeout <= 0:
        raise ValueError("validation_timeout must be greater than zero")
    if validation_command is not None and not validation_command:
        raise ValueError("validation_command must not be empty")
    root = plan.root.resolve()
    for rewrite in plan.files:
        current = rewrite.path.read_bytes()
        if _sha256(current) != rewrite.original_sha256:
            raise RuntimeError(
                f"source changed after preview; regenerate plan: {rewrite.relative_path}"
            )

    transaction_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    transaction_dir = root / ".candle-cli" / "backups" / transaction_id
    transaction_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = transaction_dir / "manifest.json"
    files = []
    for rewrite in plan.files:
        backup_path = transaction_dir / "files" / Path(rewrite.relative_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(backup_path, rewrite.original_bytes)
        files.append(
            {
                "file": rewrite.relative_path,
                "backup": backup_path.relative_to(transaction_dir).as_posix(),
                "encoding": rewrite.encoding,
                "original_sha256": rewrite.original_sha256,
                "patched_sha256": rewrite.patched_sha256,
            }
        )
    manifest = {
        "schema_version": "1.0",
        "record_kind": "rewrite_transaction",
        "transaction_id": transaction_id,
        "status": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_root": os.path.relpath(root, transaction_dir),
        "files": files,
        "validation": {"status": "not_run"},
    }
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        ),
    )

    applied = []
    try:
        for rewrite in plan.files:
            _atomic_write(rewrite.path, rewrite.patched_bytes, mode_from=rewrite.path)
            applied.append(rewrite)
        if validation_command is not None:
            manifest["validation"] = _run_validation(
                validation_command, root, validation_timeout
            )
            if manifest["validation"]["status"] != "passed":
                raise RewriteValidationError(
                    "rewrite validation failed; all source changes were rolled back"
                )
        manifest["status"] = "applied"
        manifest["applied_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode(
                "utf-8"
            ),
        )
    except BaseException:
        for rewrite in reversed(applied):
            _atomic_write(rewrite.path, rewrite.original_bytes, mode_from=rewrite.path)
        manifest["status"] = "aborted"
        manifest["aborted_at"] = datetime.now(timezone.utc).isoformat()
        try:
            _atomic_write(
                manifest_path,
                json.dumps(
                    manifest, ensure_ascii=False, indent=2, sort_keys=True
                ).encode("utf-8"),
            )
        except OSError:
            pass
        raise
    return {
        "schema_version": "1.0",
        "record_kind": "rewrite_apply_report",
        "transaction_id": transaction_id,
        "files_changed": len(plan.files),
        "manifest": str(manifest_path),
        "status": "applied",
        "verified": manifest["validation"]["status"] == "passed",
        "validation": manifest["validation"],
    }


def rollback_transaction(
    manifest_path: str | Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Restore every file in an applied transaction after hash validation."""

    manifest_path = Path(manifest_path).resolve()
    transaction_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("record_kind") != "rewrite_transaction":
        raise ValueError("not a rewrite transaction manifest")
    if manifest.get("status") != "applied":
        raise ValueError("rewrite transaction is not in applied state")
    root = (transaction_dir / manifest.get("project_root", "")).resolve()
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("rewrite transaction has no files")
    restore = []
    for entry in entries:
        relative = entry.get("file")
        backup_relative = entry.get("backup")
        if not isinstance(relative, str) or not isinstance(backup_relative, str):
            raise ValueError("rewrite transaction contains an invalid file entry")
        target = (root / relative).resolve()
        backup = (transaction_dir / backup_relative).resolve()
        if not target.is_relative_to(root) or not backup.is_relative_to(transaction_dir):
            raise ValueError("rewrite transaction path escapes its boundary")
        backup_bytes = backup.read_bytes()
        if _sha256(backup_bytes) != entry.get("original_sha256"):
            raise RuntimeError(f"backup checksum mismatch: {relative}")
        if not force and _sha256(target.read_bytes()) != entry.get("patched_sha256"):
            raise RuntimeError(f"patched file changed after apply: {relative}")
        restore.append((target, backup_bytes))
    for target, backup_bytes in restore:
        _atomic_write(target, backup_bytes, mode_from=target)
    manifest["status"] = "rolled_back"
    manifest["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        ),
    )
    return {
        "schema_version": "1.0",
        "record_kind": "rewrite_rollback_report",
        "transaction_id": manifest.get("transaction_id"),
        "files_restored": len(restore),
        "status": "rolled_back",
    }


def _target_name(target_api: str, mindspore_name: str) -> str:
    if target_api == "mindspore":
        return mindspore_name
    return target_api.replace("mindspore.", f"{mindspore_name}.", 1)


def _read_source_preserving_newlines(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding), encoding


def _run_validation(command: list[str], root: Path, timeout: float) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
        status = "passed" if result.returncode == 0 else "failed"
        return_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as error:
        status = "timed_out"
        return_code = None
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
    duration_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    return {
        "status": status,
        "command": command,
        "return_code": return_code,
        "duration_ms": round(duration_ms, 3),
        "stdout": stdout[:MAX_VALIDATION_OUTPUT_CHARACTERS],
        "stderr": stderr[:MAX_VALIDATION_OUTPUT_CHARACTERS],
        "stdout_truncated": len(stdout) > MAX_VALIDATION_OUTPUT_CHARACTERS,
        "stderr_truncated": len(stderr) > MAX_VALIDATION_OUTPUT_CHARACTERS,
    }


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _atomic_write(path: Path, contents: bytes, mode_from: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if mode_from is not None and mode_from.exists():
            os.chmod(temporary_path, mode_from.stat().st_mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _mindspore_binding(tree: ast.Module) -> str | None:
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for item in statement.names:
                if item.name == "mindspore":
                    return item.asname or "mindspore"
    return None


def _source_offset(source: str, line_number: int, byte_column: int) -> int:
    lines = source.splitlines(keepends=True)
    if line_number < 1 or line_number > len(lines):
        raise ValueError("AST line is outside source")
    prefix = lines[line_number - 1].encode("utf-8")[:byte_column]
    try:
        character_column = len(prefix.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ValueError("AST column is not on a UTF-8 character boundary") from error
    return sum(len(line) for line in lines[: line_number - 1]) + character_column


def _import_insertion_offset(source: str, tree: ast.Module) -> int:
    protected_end_line = _encoding_header_lines(source)
    statements = tree.body
    index = 0
    if statements and isinstance(statements[0], ast.Expr):
        value = statements[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            protected_end_line = max(protected_end_line, statements[0].end_lineno or 0)
            index = 1
    while index < len(statements):
        statement = statements[index]
        if not isinstance(statement, ast.ImportFrom) or statement.module != "__future__":
            break
        protected_end_line = max(protected_end_line, statement.end_lineno or 0)
        index += 1
    lines = source.splitlines(keepends=True)
    return sum(len(line) for line in lines[:protected_end_line])


def _encoding_header_lines(source: str) -> int:
    lines = source.splitlines()
    count = 1 if lines and lines[0].startswith("#!") else 0
    for index, line in enumerate(lines[:2], start=1):
        if "coding" in line and ("#" in line):
            count = max(count, index)
    return count


def _newline(source: str) -> str:
    return "\r\n" if "\r\n" in source else "\n"


def _apply_edits(source: str, edits: list[TextEdit]) -> str:
    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    for previous, current in zip(ordered, ordered[1:]):
        if current.start < previous.end:
            raise ValueError("rewrite edits overlap")
    patched = source
    for edit in reversed(ordered):
        patched = patched[: edit.start] + edit.replacement + patched[edit.end :]
    return patched


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan", help="preview or apply deterministic rewrites")
    plan_parser.add_argument("path")
    plan_parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    plan_parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    plan_parser.add_argument("--include-differences", action="store_true")
    plan_parser.add_argument("--apply", action="store_true")
    plan_parser.add_argument("--allow-partial", action="store_true")
    plan_parser.add_argument(
        "--validation-timeout",
        type=float,
        default=DEFAULT_VALIDATION_TIMEOUT_SECONDS,
    )
    plan_parser.add_argument("--pretty", action="store_true")
    plan_parser.add_argument("--validate-command", nargs=argparse.REMAINDER)
    rollback_parser = commands.add_parser("rollback", help="restore an applied transaction")
    rollback_parser.add_argument("manifest")
    rollback_parser.add_argument("--force", action="store_true")
    rollback_parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "plan":
            if arguments.validate_command is not None and not arguments.apply:
                raise ValueError("--validate-command requires --apply")
            plan = plan_rewrite(
                arguments.path,
                knowledge_base=arguments.knowledge_base,
                include_differences=arguments.include_differences,
                max_file_bytes=arguments.max_file_bytes,
            )
            report = (
                apply_plan(
                    plan,
                    allow_partial=arguments.allow_partial,
                    validation_command=arguments.validate_command,
                    validation_timeout=arguments.validation_timeout,
                )
                if arguments.apply
                else plan.to_dict()
            )
        else:
            report = rollback_transaction(arguments.manifest, force=arguments.force)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
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
