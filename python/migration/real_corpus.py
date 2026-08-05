"""Prepare and verify pinned real-project migration benchmark sources."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio

DEFAULT_MANIFEST = (
    Path(__file__).parents[2]
    / "benchmarks"
    / "migration"
    / "real_projects_v1.json"
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class RealProject:
    project_id: str
    repository: str
    commit: str
    checkout_dir: str
    license_name: str
    license_file: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class RealCorpusManifest:
    benchmark_version: str
    dataset_kind: str
    projects: tuple[RealProject, ...]


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> RealCorpusManifest:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0":
        raise ValueError("unsupported real corpus schema_version")
    benchmark_version = document.get("benchmark_version")
    dataset_kind = document.get("dataset_kind")
    projects = document.get("projects")
    if not isinstance(benchmark_version, str) or not benchmark_version:
        raise ValueError("real corpus requires benchmark_version")
    if dataset_kind != "pinned_real_project_static_corpus":
        raise ValueError("real corpus has an unsupported dataset_kind")
    if not isinstance(projects, list) or not projects:
        raise ValueError("real corpus requires projects")
    parsed = []
    identifiers = set()
    checkout_dirs = set()
    for value in projects:
        if not isinstance(value, dict):
            raise ValueError("real corpus project must be an object")
        project_id = _required_string(value, "id")
        repository = _required_string(value, "repository")
        commit = _required_string(value, "commit")
        checkout_dir = _required_string(value, "checkout_dir")
        license_name = _required_string(value, "license")
        license_file = _safe_relative(_required_string(value, "license_file"))
        patterns = value.get("paths")
        if project_id in identifiers or checkout_dir in checkout_dirs:
            raise ValueError("real corpus project id and checkout_dir must be unique")
        if not repository.startswith("https://github.com/") or not repository.endswith(
            ".git"
        ):
            raise ValueError("real corpus repository must be an HTTPS GitHub .git URL")
        if not COMMIT_PATTERN.fullmatch(commit):
            raise ValueError("real corpus commit must be a lowercase 40-character SHA")
        _safe_relative(checkout_dir)
        if not isinstance(patterns, list) or not patterns:
            raise ValueError("real corpus project requires paths")
        safe_patterns = tuple(_safe_relative(_required_pattern(item)) for item in patterns)
        identifiers.add(project_id)
        checkout_dirs.add(checkout_dir)
        parsed.append(
            RealProject(
                project_id=project_id,
                repository=repository,
                commit=commit,
                checkout_dir=checkout_dir,
                license_name=license_name,
                license_file=license_file,
                paths=safe_patterns,
            )
        )
    return RealCorpusManifest(
        benchmark_version=benchmark_version,
        dataset_kind=dataset_kind,
        projects=tuple(parsed),
    )


def prepare_corpus(
    corpus_root: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Create missing checkouts at exact commits, then verify every project."""

    manifest = load_manifest(manifest_path)
    root = Path(corpus_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    prepared = []
    for project in manifest.projects:
        checkout = (root / project.checkout_dir).resolve()
        if not checkout.is_relative_to(root):
            raise ValueError("real corpus checkout escapes corpus root")
        if not checkout.exists():
            _run(["git", "init", str(checkout)], root)
            _run(["git", "-C", str(checkout), "remote", "add", "origin", project.repository], root)
            _run(
                ["git", "-C", str(checkout), "fetch", "--depth", "1", "origin", project.commit],
                root,
            )
            _run(["git", "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"], root)
        files = verify_project(project, root, verify_commit=True)
        prepared.append(
            {
                "id": project.project_id,
                "commit": project.commit,
                "file_count": len(files),
                "status": "ready",
            }
        )
    return {
        "benchmark_version": manifest.benchmark_version,
        "dataset_kind": manifest.dataset_kind,
        "project_count": len(prepared),
        "projects": prepared,
    }


def verify_project(
    project: RealProject,
    corpus_root: str | Path,
    *,
    verify_commit: bool,
) -> list[Path]:
    root = Path(corpus_root).resolve()
    checkout = (root / project.checkout_dir).resolve()
    if not checkout.is_relative_to(root) or not checkout.is_dir():
        raise ValueError(f"real corpus checkout is missing: {project.checkout_dir}")
    if verify_commit:
        result = _run(["git", "-C", str(checkout), "rev-parse", "HEAD"], root)
        if result.stdout.strip() != project.commit:
            raise ValueError(f"real corpus commit mismatch: {project.project_id}")
        status = _run(
            ["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"],
            root,
        )
        if status.stdout.strip():
            raise ValueError(f"real corpus checkout has tracked changes: {project.project_id}")
    license_path = (checkout / project.license_file).resolve()
    if not license_path.is_relative_to(checkout) or not license_path.is_file():
        raise ValueError(f"real corpus license is missing: {project.project_id}")
    selected: dict[str, Path] = {}
    for pattern in project.paths:
        for path in checkout.glob(pattern):
            resolved = path.resolve()
            if (
                path.is_symlink()
                or not resolved.is_relative_to(checkout)
                or not resolved.is_file()
                or resolved.suffix != ".py"
            ):
                continue
            selected[resolved.relative_to(checkout).as_posix()] = resolved
    if not selected:
        raise ValueError(f"real corpus patterns selected no Python files: {project.project_id}")
    return [selected[name] for name in sorted(selected)]


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        stderr = getattr(error, "stderr", "") or ""
        raise RuntimeError(f"real corpus command failed: {' '.join(command)}: {stderr.strip()}") from error


def _required_string(value: dict[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"real corpus project requires {name}")
    return item.strip()


def _required_pattern(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("real corpus path pattern must be a non-empty string")
    return value.strip()


def _safe_relative(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."}:
        raise ValueError("real corpus paths must be safe relative paths")
    return value


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_root")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = prepare_corpus(arguments.corpus_root, arguments.manifest)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2 if arguments.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
