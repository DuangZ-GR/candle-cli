"""Measure scanner and safe-rewrite coverage on a pinned real-project corpus."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from migration.cli_io import configure_utf8_stdio
from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase
from migration.real_corpus import DEFAULT_MANIFEST, load_manifest, verify_project
from migration.rewriter import DEFAULT_REWRITE_RULES, RewriteRuleKnowledge, plan_rewrite
from migration.scanner import scan_path


def run_benchmark(
    corpus_root: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    *,
    verify_commits: bool = True,
    knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    root = Path(corpus_root).resolve()
    knowledge_path = Path(knowledge_base)
    knowledge = MappingKnowledgeBase.load(knowledge_path)
    dtype_apis = set(RewriteRuleKnowledge.load(DEFAULT_REWRITE_RULES).dtype_constants)
    projects = []
    total = Counter()
    all_apis = Counter()
    all_unknown = Counter()
    for project in manifest.projects:
        checkout = (root / project.checkout_dir).resolve()
        files = verify_project(project, root, verify_commit=verify_commits)
        counts = Counter()
        api_counts = Counter()
        unknown_counts = Counter()
        for source_path in files:
            counts["source_lines"] += len(source_path.read_bytes().splitlines())
            report = scan_path(source_path, knowledge_base=knowledge_path)
            counts["files"] += 1
            counts["files_scanned"] += report.files_scanned
            counts["scan_issues"] += len(report.issues)
            counts["findings"] += len(report.findings)
            for finding in report.findings:
                counts[f"mapping_{finding.mapping.status}"] += 1
                counts[f"call_{finding.call_kind}"] += 1
                api_counts[finding.api] += 1
                if finding.mapping.status == "unknown":
                    unknown_counts[finding.api] += 1
            rewrite = plan_rewrite(source_path, knowledge_base=knowledge_path)
            if rewrite.files:
                counts["files_with_rewrite"] += 1
                patched = rewrite.files[0].patched_source
                ast.parse(patched, filename=str(source_path), type_comments=True)
                counts["syntax_valid_patches"] += 1
                for edit in rewrite.files[0].edits:
                    counts["text_edits"] += 1
                    if edit.source_api == "<import>":
                        counts["import_edits"] += 1
                    elif edit.source_api in dtype_apis:
                        counts["dtype_edits"] += 1
                    else:
                        counts["call_rewrites"] += 1
        project_report = _summarize(project.project_id, project.commit, counts, api_counts, unknown_counts)
        projects.append(project_report)
        total.update(counts)
        all_apis.update(api_counts)
        all_unknown.update(unknown_counts)
    summary = _summarize("all", None, total, all_apis, all_unknown)
    return {
        "schema_version": "1.0",
        "benchmark_version": manifest.benchmark_version,
        "dataset_kind": manifest.dataset_kind,
        "project_count": len(projects),
        "knowledge": {
            "snapshot_version": knowledge.payload["snapshot_version"],
            "source_framework_version": knowledge.payload["source_framework"]["version"],
            "target_framework_version": knowledge.payload["target_framework"]["version"],
            "sha256": hashlib.sha256(knowledge_path.read_bytes()).hexdigest(),
        },
        "rewrite_policy": "exact_mappings_only",
        "summary": summary,
        "projects": projects,
        "limitations": [
            "No third-party project code is executed.",
            "Mapping coverage is measured over scanner findings, not manually labelled recall.",
            "Syntax-valid previews are not equivalent to MindSpore runtime correctness.",
        ],
    }


def _summarize(
    project_id: str,
    commit: str | None,
    counts: Counter,
    api_counts: Counter,
    unknown_counts: Counter,
) -> dict[str, Any]:
    findings = counts["findings"]
    mapped = counts["mapping_exact"] + counts["mapping_difference"]
    unique_apis = len(api_counts)
    mapped_unique = sum(1 for api in api_counts if api not in unknown_counts)
    files_with_rewrite = counts["files_with_rewrite"]
    result = {
        "project_id": project_id,
        "files": counts["files"],
        "files_scanned": counts["files_scanned"],
        "source_lines": counts["source_lines"],
        "scan_issues": counts["scan_issues"],
        "scan_success_rate": round(counts["files_scanned"] / counts["files"], 6)
        if counts["files"]
        else 0.0,
        "findings": findings,
        "mapped_findings": mapped,
        "unique_apis": unique_apis,
        "mapped_unique_apis": mapped_unique,
        "mapping_counts": {
            "exact": counts["mapping_exact"],
            "difference": counts["mapping_difference"],
            "unsupported": counts["mapping_unsupported"],
            "unknown": counts["mapping_unknown"],
        },
        "mapped_finding_coverage": round(mapped / findings, 6) if findings else 0.0,
        "mapped_unique_api_coverage": round(mapped_unique / unique_apis, 6) if unique_apis else 0.0,
        "call_kinds": {
            "function": counts["call_function"],
            "tensor_method": counts["call_tensor_method"],
            "dynamic": counts["call_dynamic"],
        },
        "rewrite": {
            "files_with_rewrite": files_with_rewrite,
            "syntax_valid_files": counts["syntax_valid_patches"],
            "call_rewrites": counts["call_rewrites"],
            "dtype_edits": counts["dtype_edits"],
            "import_edits": counts["import_edits"],
            "text_edits": counts["text_edits"],
            "syntax_valid_rate": round(
                counts["syntax_valid_patches"] / files_with_rewrite, 6
            )
            if files_with_rewrite
            else 0.0,
        },
        "top_unknown_apis": [
            {"api": api, "count": count}
            for api, count in sorted(
                unknown_counts.items(), key=lambda item: (-item[1], item[0])
            )[:10]
        ],
    }
    if commit is not None:
        result["commit"] = commit
    return result


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_root")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--output")
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = run_benchmark(
            arguments.corpus_root,
            arguments.manifest,
            knowledge_base=arguments.knowledge_base,
        )
        encoded = json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if arguments.pretty or arguments.output else None,
            sort_keys=True,
        )
        if arguments.output:
            output = Path(arguments.output)
            if output.exists():
                raise ValueError("benchmark output already exists")
            output.write_text(encoded + "\n", encoding="utf-8")
        else:
            print(encoded)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
