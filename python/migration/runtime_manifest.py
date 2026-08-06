"""Load and execute a bounded dual-runtime migration manifest."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"
WORKFLOW_VERSION = "dual-runtime-v1"
MAX_CAPTURE_CHARACTERS = 16_384
MAX_TRACE_BYTES = 32 * 1024 * 1024
DEFAULT_INHERITED_ENVIRONMENT = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "CUDA_VISIBLE_DEVICES",
)
_ENVIRONMENT_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_ALLOWED_PLACEHOLDERS = {"project_root", "trace_path", "run_id", "framework"}


class RuntimeManifestError(ValueError):
    """Raised when a dual-runtime manifest is invalid."""


class RuntimeExecutionError(RuntimeError):
    """Raised when a bounded runtime command fails."""

    def __init__(self, message: str, result: dict[str, Any]):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class ResourceLimits:
    cpu_seconds: int | None
    memory_mb: int | None


@dataclass(frozen=True)
class RuntimeCommand:
    framework: str
    python_env: str
    python_default: str | None
    entrypoint: str
    args: tuple[str, ...]
    trace_path: str
    timeout_seconds: float
    inherit_environment: tuple[str, ...]
    environment: dict[str, str]
    resource_limits: ResourceLimits


@dataclass(frozen=True)
class DualRuntimeManifest:
    path: Path
    project_root: Path
    manifest_id: str
    source_files: tuple[str, ...]
    source: RuntimeCommand
    target: RuntimeCommand
    manual_patch_count: int
    metadata: dict[str, Any]


def load_runtime_manifest(
    path: str | Path,
    project_root: str | Path,
) -> DualRuntimeManifest:
    """Load a versioned manifest and resolve all project-scoped paths safely."""

    manifest_path = Path(path).resolve()
    root = Path(project_root).resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeManifestError(f"failed to load runtime manifest: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeManifestError("runtime manifest root must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeManifestError("unsupported runtime manifest schema_version")
    if payload.get("workflow_version") != WORKFLOW_VERSION:
        raise RuntimeManifestError("unsupported runtime manifest workflow_version")
    manifest_id = _required_text(payload, "manifest_id")
    source_files = payload.get("source_files")
    if not isinstance(source_files, list) or not source_files or not all(
        isinstance(item, str) and item for item in source_files
    ):
        raise RuntimeManifestError("source_files must be a non-empty array of paths")
    source_files = list(dict.fromkeys(source_files))
    for relative in source_files:
        _resolve_project_path(root, relative, must_exist=True)
    manual_patch_count = payload.get("manual_patch_count", 0)
    if not isinstance(manual_patch_count, int) or manual_patch_count < 0:
        raise RuntimeManifestError("manual_patch_count must be a non-negative integer")
    source = _parse_command(payload.get("source"), "pytorch")
    target = _parse_command(payload.get("target"), "mindspore")
    for command in (source, target):
        _resolve_project_path(root, command.entrypoint, must_exist=True)
        _resolve_project_path(root, command.trace_path, allow_placeholders=True)
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise RuntimeManifestError("runtime manifest metadata must be an object")
    return DualRuntimeManifest(
        path=manifest_path,
        project_root=root,
        manifest_id=manifest_id,
        source_files=tuple(source_files),
        source=source,
        target=target,
        manual_patch_count=manual_patch_count,
        metadata=metadata,
    )


def execute_runtime(
    manifest: DualRuntimeManifest,
    phase: str,
    run_id: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run one manifest command without a shell and require a fresh bounded trace."""

    if phase not in {"source", "target"}:
        raise RuntimeManifestError("runtime phase must be source or target")
    command = manifest.source if phase == "source" else manifest.target
    process_environment = dict(os.environ if environment is None else environment)
    python = _resolve_python(command, process_environment)
    entrypoint = _resolve_project_path(
        manifest.project_root, command.entrypoint, must_exist=True
    )
    substitutions = {
        "project_root": str(manifest.project_root),
        "run_id": run_id,
        "framework": command.framework,
    }
    trace_relative = _format_template(command.trace_path, substitutions)
    trace_path = _resolve_project_path(manifest.project_root, trace_relative)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    if trace_path.exists():
        trace_path.unlink()
    substitutions["trace_path"] = str(trace_path)
    arguments = [_format_template(item, substitutions) for item in command.args]
    argv = [str(python), str(entrypoint), *arguments]
    child_environment = _build_environment(command, process_environment)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            cwd=manifest.project_root,
            env=child_environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=command.timeout_seconds,
            shell=False,
            check=False,
            preexec_fn=_resource_limiter(command.resource_limits),
        )
    except subprocess.TimeoutExpired as error:
        result = _execution_result(
            command,
            argv,
            python,
            trace_path,
            started,
            "timed_out",
            None,
            error.stdout or "",
            error.stderr or "",
        )
        raise RuntimeExecutionError(
            f"{phase} runtime exceeded {command.timeout_seconds:g} seconds", result
        ) from error
    result = _execution_result(
        command,
        argv,
        python,
        trace_path,
        started,
        "passed" if completed.returncode == 0 else "failed",
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    if completed.returncode != 0:
        raise RuntimeExecutionError(
            f"{phase} runtime exited with code {completed.returncode}", result
        )
    if not trace_path.is_file():
        result["status"] = "failed"
        raise RuntimeExecutionError(
            f"{phase} runtime did not produce trace: {trace_path}", result
        )
    trace_bytes = trace_path.stat().st_size
    result["trace_bytes"] = trace_bytes
    if trace_bytes <= 0 or trace_bytes > MAX_TRACE_BYTES:
        result["status"] = "failed"
        raise RuntimeExecutionError(
            f"{phase} trace size must be between 1 and {MAX_TRACE_BYTES} bytes",
            result,
        )
    return result


def _parse_command(payload: Any, expected_framework: str) -> RuntimeCommand:
    if not isinstance(payload, dict):
        raise RuntimeManifestError(f"{expected_framework} runtime must be an object")
    framework = _required_text(payload, "framework")
    if framework != expected_framework:
        raise RuntimeManifestError(
            f"runtime framework must be {expected_framework}, got {framework}"
        )
    python_env = _required_text(payload, "python_env")
    if not _ENVIRONMENT_NAME.fullmatch(python_env):
        raise RuntimeManifestError("python_env must be an uppercase environment name")
    python_default = payload.get("python_default")
    if python_default is not None and not isinstance(python_default, str):
        raise RuntimeManifestError("python_default must be a string or null")
    entrypoint = _required_text(payload, "entrypoint")
    trace_path = _required_text(payload, "trace_path")
    args = payload.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise RuntimeManifestError("runtime args must be an array of strings")
    for template in [trace_path, *args]:
        unknown = set(_PLACEHOLDER.findall(template)) - _ALLOWED_PLACEHOLDERS
        if unknown:
            raise RuntimeManifestError(
                f"runtime template contains unsupported placeholders: {sorted(unknown)}"
            )
    timeout = payload.get("timeout_seconds", 120.0)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise RuntimeManifestError("timeout_seconds must be greater than zero")
    environment = payload.get("environment", {})
    if not isinstance(environment, dict):
        raise RuntimeManifestError("runtime environment must be an object")
    inherit = environment.get("inherit", list(DEFAULT_INHERITED_ENVIRONMENT))
    fixed = environment.get("set", {})
    if not isinstance(inherit, list) or not all(isinstance(item, str) for item in inherit):
        raise RuntimeManifestError("environment.inherit must be an array of names")
    if not isinstance(fixed, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in fixed.items()
    ):
        raise RuntimeManifestError("environment.set must map names to string values")
    for name in [*inherit, *fixed]:
        if not _ENVIRONMENT_NAME.fullmatch(name):
            raise RuntimeManifestError(f"invalid environment variable name: {name}")
    limits = payload.get("resource_limits", {})
    if not isinstance(limits, dict):
        raise RuntimeManifestError("resource_limits must be an object")
    cpu_seconds = _optional_positive_integer(limits, "cpu_seconds")
    memory_mb = _optional_positive_integer(limits, "memory_mb")
    return RuntimeCommand(
        framework=framework,
        python_env=python_env,
        python_default=python_default,
        entrypoint=entrypoint,
        args=tuple(args),
        trace_path=trace_path,
        timeout_seconds=float(timeout),
        inherit_environment=tuple(dict.fromkeys(inherit)),
        environment=dict(fixed),
        resource_limits=ResourceLimits(cpu_seconds, memory_mb),
    )


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeManifestError(f"runtime manifest requires non-empty {key}")
    return value


def _optional_positive_integer(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeManifestError(f"{key} must be a positive integer or null")
    return value


def _resolve_project_path(
    root: Path,
    relative: str,
    *,
    must_exist: bool = False,
    allow_placeholders: bool = False,
) -> Path:
    candidate_text = relative
    if allow_placeholders:
        candidate_text = _PLACEHOLDER.sub("placeholder", candidate_text)
    candidate = Path(candidate_text)
    if candidate.is_absolute():
        raise RuntimeManifestError("runtime project paths must be relative")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise RuntimeManifestError(f"runtime path escapes project root: {relative}")
    if must_exist and not resolved.is_file():
        raise RuntimeManifestError(f"runtime entrypoint does not exist: {relative}")
    return resolved


def _format_template(template: str, substitutions: Mapping[str, str]) -> str:
    missing = set(_PLACEHOLDER.findall(template)) - set(substitutions)
    if missing:
        raise RuntimeManifestError(
            f"runtime template uses unavailable placeholders: {sorted(missing)}"
        )
    return template.format_map(dict(substitutions))


def _resolve_python(command: RuntimeCommand, environment: Mapping[str, str]) -> Path:
    configured = environment.get(command.python_env) or command.python_default
    if not configured:
        raise RuntimeManifestError(
            f"set {command.python_env} to the {command.framework} Python executable"
        )
    candidate = Path(configured).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        resolved = candidate.resolve()
        if not resolved.is_file():
            raise RuntimeManifestError(
                f"{command.python_env} does not point to a file: {configured}"
            )
        return resolved
    located = shutil.which(configured, path=environment.get("PATH"))
    if located is None:
        raise RuntimeManifestError(
            f"unable to locate {command.framework} Python executable: {configured}"
        )
    return Path(located).resolve()


def _build_environment(
    command: RuntimeCommand, environment: Mapping[str, str]
) -> dict[str, str]:
    child = {
        name: environment[name]
        for name in command.inherit_environment
        if name in environment
    }
    child.update(command.environment)
    child.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONHASHSEED": "0",
        }
    )
    return child


def _resource_limiter(limits: ResourceLimits):
    if os.name != "posix" or (limits.cpu_seconds is None and limits.memory_mb is None):
        return None

    def apply_limits() -> None:
        import resource

        if limits.cpu_seconds is not None:
            resource.setrlimit(
                resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds)
            )
        if limits.memory_mb is not None:
            memory_bytes = limits.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

    return apply_limits


def _execution_result(
    command: RuntimeCommand,
    argv: list[str],
    python: Path,
    trace_path: Path,
    started: float,
    status: str,
    return_code: int | None,
    stdout: str | bytes,
    stderr: str | bytes,
) -> dict[str, Any]:
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    return {
        "status": status,
        "framework": command.framework,
        "python": str(python),
        "python_version": _python_version(python),
        "command": argv,
        "return_code": return_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "trace_path": str(trace_path),
        "trace_bytes": trace_path.stat().st_size if trace_path.is_file() else 0,
        "timeout_seconds": command.timeout_seconds,
        "resource_limits": {
            "cpu_seconds": command.resource_limits.cpu_seconds,
            "memory_mb": command.resource_limits.memory_mb,
            "enforced": os.name == "posix",
        },
        "stdout": stdout[:MAX_CAPTURE_CHARACTERS],
        "stderr": stderr[:MAX_CAPTURE_CHARACTERS],
        "stdout_truncated": len(stdout) > MAX_CAPTURE_CHARACTERS,
        "stderr_truncated": len(stderr) > MAX_CAPTURE_CHARACTERS,
    }


def _python_version(python: Path) -> str:
    if python.resolve() == Path(sys.executable).resolve():
        return ".".join(map(str, sys.version_info[:3]))
    try:
        completed = subprocess.run(
            [str(python), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return (completed.stdout or completed.stderr).strip() or "unknown"


__all__ = [
    "DualRuntimeManifest",
    "RuntimeExecutionError",
    "RuntimeManifestError",
    "execute_runtime",
    "load_runtime_manifest",
]
