"""Run the deterministic PyTorch-to-MindSpore migration workflow end to end."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase
from migration.rewriter import (
    DEFAULT_VALIDATION_TIMEOUT_SECONDS,
    RewriteValidationError,
    apply_plan,
    plan_rewrite,
    rollback_transaction,
)
from migration.scanner import DEFAULT_MAX_FILE_BYTES, scan_path
from migration.schema import Framework
from migration.trace_compare import compare_traces, load_trace_jsonl

SCHEMA_VERSION = "1.0"
RECORD_KIND = "migration_run_report"


def run_migration(
    path: str | Path,
    *,
    knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    include_differences: bool = False,
    apply: bool = False,
    allow_partial: bool = False,
    validation_command: list[str] | None = None,
    validation_timeout: float = DEFAULT_VALIDATION_TIMEOUT_SECONDS,
    source_trace: str | Path | None = None,
    target_trace: str | Path | None = None,
    relative_tolerance: float = 1e-5,
    absolute_tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Execute scan, rewrite, validation and optional trace comparison as one run."""

    if apply and not validation_command:
        raise ValueError("--apply requires a non-empty validation command")
    if validation_command is not None and not apply:
        raise ValueError("validation command requires --apply")
    if (source_trace is None) != (target_trace is None):
        raise ValueError("source_trace and target_trace must be provided together")
    if validation_timeout <= 0:
        raise ValueError("validation_timeout must be greater than zero")
    if relative_tolerance < 0 or absolute_tolerance < 0:
        raise ValueError("numeric tolerances must be non-negative")

    requested = Path(path).resolve()
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    run_id = f"migration-{started_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid.uuid4().hex[:8]}"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "run_id": run_id,
        "project_root": str(requested),
        "mode": "apply" if apply else "preview",
        "status": "running",
        "verified": False,
        "started_at": started_at.isoformat(),
        "duration_ms": 0.0,
        "steps": [],
        "summary": {
            "files_discovered": 0,
            "files_scanned": 0,
            "finding_count": 0,
            "scan_issue_count": 0,
            "mapping_counts": {
                "exact": 0,
                "difference": 0,
                "unsupported": 0,
                "unknown": 0,
            },
            "files_changed": 0,
            "edit_count": 0,
            "rewrite_issue_count": 0,
            "validation_status": "not_run",
            "trace_equivalent": None,
            "first_divergence_category": None,
        },
        "artifacts": {"transaction_manifest": None},
        "error": None,
    }

    scan_started = time.perf_counter()
    try:
        scan = scan_path(
            requested,
            max_file_bytes=max_file_bytes,
            knowledge_base=knowledge_base,
        )
        scan.validate()
    except (OSError, ValueError) as error:
        _fail(report, "scan", error)
        _append_step(report, "scan", "failed", scan_started, {"message": str(error)})
        return _finish(report, started)
    scan_payload = scan.to_dict()
    scan_summary = scan_payload["summary"]
    report["summary"].update(
        {
            "files_discovered": scan_payload["files_discovered"],
            "files_scanned": scan_payload["files_scanned"],
            "finding_count": scan_summary["finding_count"],
            "scan_issue_count": scan_summary["issue_count"],
            "mapping_counts": scan_summary["mapping_counts"],
        }
    )
    _append_step(
        report,
        "scan",
        "partial" if scan.issues else "passed",
        scan_started,
        {
            "files_discovered": scan.files_discovered,
            "files_scanned": scan.files_scanned,
            "finding_count": scan_summary["finding_count"],
            "issue_count": scan_summary["issue_count"],
        },
    )

    preview_started = time.perf_counter()
    try:
        plan = plan_rewrite(
            requested,
            knowledge_base=knowledge_base,
            include_differences=include_differences,
            max_file_bytes=max_file_bytes,
        )
    except (OSError, ValueError) as error:
        _fail(report, "rewrite_preview", error)
        _append_step(
            report,
            "rewrite_preview",
            "failed",
            preview_started,
            {"message": str(error)},
        )
        return _finish(report, started)
    plan_payload = plan.to_dict()
    report["summary"].update(
        {
            "files_changed": plan_payload["files_changed"],
            "edit_count": plan_payload["edit_count"],
            "rewrite_issue_count": len(plan_payload["issues"]),
        }
    )
    _append_step(
        report,
        "rewrite_preview",
        "partial" if plan.issues else ("no_changes" if not plan.files else "passed"),
        preview_started,
        {
            "files_changed": plan_payload["files_changed"],
            "edit_count": plan_payload["edit_count"],
            "issue_count": len(plan_payload["issues"]),
        },
    )

    apply_report = None
    if apply:
        apply_started = time.perf_counter()
        backups_before = _transaction_manifests(plan.root)
        try:
            apply_report = apply_plan(
                plan,
                allow_partial=allow_partial,
                validation_command=validation_command,
                validation_timeout=validation_timeout,
            )
        except RewriteValidationError as error:
            manifest_path = _new_transaction_manifest(plan.root, backups_before)
            manifest = _load_json(manifest_path) if manifest_path else {}
            validation = manifest.get("validation", {"status": "failed"})
            report["summary"]["validation_status"] = validation.get(
                "status", "failed"
            )
            report["artifacts"]["transaction_manifest"] = (
                str(manifest_path) if manifest_path else None
            )
            _append_step(
                report,
                "apply_and_validate",
                "rolled_back",
                apply_started,
                {"validation": validation},
            )
            report["status"] = "rolled_back"
            _set_error(report, "validation", error)
            return _finish(report, started)
        except (OSError, ValueError, RuntimeError) as error:
            manifest_path = _new_transaction_manifest(plan.root, backups_before)
            manifest = _load_json(manifest_path) if manifest_path else {}
            rolled_back = manifest.get("status") == "aborted"
            report["artifacts"]["transaction_manifest"] = (
                str(manifest_path) if manifest_path else None
            )
            _append_step(
                report,
                "apply_and_validate",
                "rolled_back" if rolled_back else "failed",
                apply_started,
                {"message": str(error)},
            )
            report["status"] = "rolled_back" if rolled_back else "failed"
            _set_error(report, "apply_and_validate", error)
            return _finish(report, started)
        report["summary"]["validation_status"] = apply_report["validation"][
            "status"
        ]
        report["artifacts"]["transaction_manifest"] = apply_report["manifest"]
        _append_step(
            report,
            "apply_and_validate",
            "passed",
            apply_started,
            {
                "transaction_id": apply_report["transaction_id"],
                "files_changed": apply_report["files_changed"],
                "verified": apply_report["verified"],
                "validation": apply_report["validation"],
            },
        )

    if source_trace is not None and target_trace is not None:
        compare_started = time.perf_counter()
        try:
            source = load_trace_jsonl(source_trace, Framework.PYTORCH)
            target = load_trace_jsonl(target_trace, Framework.MINDSPORE)
            comparison = compare_traces(
                source,
                target,
                MappingKnowledgeBase.load(knowledge_base),
                relative_tolerance,
                absolute_tolerance,
            )
        except (OSError, ValueError) as error:
            _append_step(
                report,
                "trace_compare",
                "failed",
                compare_started,
                {"message": str(error)},
            )
            return _rollback_after_compare_failure(
                report, apply_report, "trace_compare", error, started
            )
        comparison_payload = comparison.to_dict()
        report["summary"]["trace_equivalent"] = comparison.equivalent
        if comparison.diagnostic is not None:
            report["summary"]["first_divergence_category"] = (
                comparison.diagnostic.category.value
            )
        _append_step(
            report,
            "trace_compare",
            "passed" if comparison.equivalent else "divergent",
            compare_started,
            comparison_payload,
        )
        if not comparison.equivalent:
            error = RuntimeError("source and target traces are not equivalent")
            return _rollback_after_compare_failure(
                report, apply_report, "trace_compare", error, started
            )

    if apply:
        report["verified"] = bool(apply_report and apply_report["verified"])
        report["status"] = "verified" if report["verified"] else "failed"
        if not report["verified"]:
            _set_error(
                report,
                "apply_and_validate",
                RuntimeError("applied migration was not verified"),
            )
    else:
        report["status"] = "previewed"
    return _finish(report, started)


def validate_report(report: dict[str, Any]) -> None:
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported migration run schema_version")
    if report.get("record_kind") != RECORD_KIND:
        raise ValueError("record_kind must be migration_run_report")
    if report.get("mode") not in {"preview", "apply"}:
        raise ValueError("migration run mode must be preview or apply")
    if report.get("status") not in {
        "previewed",
        "verified",
        "divergent",
        "rolled_back",
        "failed",
    }:
        raise ValueError("migration run has an invalid terminal status")
    if not isinstance(report.get("steps"), list) or not report["steps"]:
        raise ValueError("migration run must contain at least one step")
    if report["status"] == "verified" and not report.get("verified"):
        raise ValueError("verified status requires verified=true")
    if report.get("verified") and report["mode"] != "apply":
        raise ValueError("only apply mode can be verified")
    if report["status"] in {"divergent", "rolled_back", "failed"} and not report.get(
        "error"
    ):
        raise ValueError("failed migration run must include an error")


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Torch2MindSpore Migration Run",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Mode: `{report['mode']}`",
        f"- Status: `{report['status']}`",
        f"- Verified: `{str(report['verified']).lower()}`",
        f"- Duration: `{report['duration_ms']:.3f} ms`",
        "",
        "## Summary",
        "",
        f"- Files scanned: {summary['files_scanned']}/{summary['files_discovered']}",
        f"- Findings: {summary['finding_count']}",
        f"- Rewrite edits: {summary['edit_count']} in {summary['files_changed']} file(s)",
        f"- Validation: `{summary['validation_status']}`",
        f"- Trace equivalent: `{summary['trace_equivalent'] if summary['trace_equivalent'] is not None else 'not_run'}`",
        f"- First divergence: `{summary['first_divergence_category'] or 'none'}`",
        "",
        "## Steps",
        "",
        "| Step | Status | Duration (ms) |",
        "| --- | --- | ---: |",
    ]
    lines.extend(
        f"| `{step['name']}` | `{step['status']}` | {step['duration_ms']:.3f} |"
        for step in report["steps"]
    )
    if report["error"]:
        lines.extend(
            [
                "",
                "## Error",
                "",
                f"- Stage: `{report['error']['stage']}`",
                f"- Type: `{report['error']['type']}`",
                f"- Message: {report['error']['message']}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _append_step(
    report: dict[str, Any],
    name: str,
    status: str,
    started: float,
    details: dict[str, Any],
) -> None:
    report["steps"].append(
        {
            "name": name,
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "details": details,
        }
    )


def _set_error(report: dict[str, Any], stage: str, error: BaseException) -> None:
    report["error"] = {
        "stage": stage,
        "type": type(error).__name__,
        "message": str(error),
    }


def _fail(report: dict[str, Any], stage: str, error: BaseException) -> None:
    report["status"] = "failed"
    _set_error(report, stage, error)


def _finish(report: dict[str, Any], started: float) -> dict[str, Any]:
    report["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    validate_report(report)
    return report


def _transaction_manifests(root: Path) -> set[Path]:
    backup_root = root / ".candle-cli" / "backups"
    return set(backup_root.glob("*/manifest.json")) if backup_root.exists() else set()


def _new_transaction_manifest(root: Path, before: set[Path]) -> Path | None:
    created = _transaction_manifests(root) - before
    return max(created, key=lambda item: item.stat().st_mtime_ns) if created else None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rollback_after_compare_failure(
    report: dict[str, Any],
    apply_report: dict[str, Any] | None,
    stage: str,
    error: BaseException,
    started: float,
) -> dict[str, Any]:
    _set_error(report, stage, error)
    if apply_report is None:
        report["status"] = "divergent" if stage == "trace_compare" else "failed"
        return _finish(report, started)
    rollback_started = time.perf_counter()
    try:
        rollback = rollback_transaction(apply_report["manifest"])
    except (OSError, ValueError, RuntimeError) as rollback_error:
        _append_step(
            report,
            "rollback",
            "failed",
            rollback_started,
            {"message": str(rollback_error)},
        )
        report["status"] = "failed"
        report["error"]["rollback_error"] = str(rollback_error)
    else:
        _append_step(report, "rollback", "passed", rollback_started, rollback)
        report["status"] = "rolled_back"
    return _finish(report, started)


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--include-differences", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--validation-timeout", type=float, default=300.0)
    parser.add_argument("--validate-command", nargs=argparse.REMAINDER)
    parser.add_argument("--source-trace")
    parser.add_argument("--target-trace")
    parser.add_argument("--relative-tolerance", type=float, default=1e-5)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-8)
    parser.add_argument("--output")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    output = Path(arguments.output).resolve() if arguments.output else None
    if output is not None and output.exists() and not arguments.force:
        print("output already exists; pass --force to replace it", file=__import__("sys").stderr)
        return 2
    try:
        report = run_migration(
            arguments.path,
            knowledge_base=arguments.knowledge_base,
            max_file_bytes=arguments.max_file_bytes,
            include_differences=arguments.include_differences,
            apply=arguments.apply,
            allow_partial=arguments.allow_partial,
            validation_command=arguments.validate_command,
            validation_timeout=arguments.validation_timeout,
            source_trace=arguments.source_trace,
            target_trace=arguments.target_trace,
            relative_tolerance=arguments.relative_tolerance,
            absolute_tolerance=arguments.absolute_tolerance,
        )
    except (OSError, ValueError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    rendered = (
        render_markdown(report)
        if arguments.format == "markdown"
        else json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
        + "\n"
    )
    if output is None:
        print(rendered, end="")
    else:
        _atomic_write(output, rendered)
    return 0 if report["status"] in {"previewed", "verified"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
