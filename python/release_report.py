"""Aggregate traceable benchmark evidence without widening source claims."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _lookup(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"missing metric path: {dotted_path}")
        current = current[part]
    return current


def _safe_source(root: Path, raw_path: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / raw_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        raise ValueError(f"release evidence path escapes repository: {raw_path}")
    if not candidate.is_file():
        raise ValueError(f"release evidence source does not exist: {raw_path}")
    return candidate


def build_release_report(config_path: Path, repository_root: Path) -> dict[str, Any]:
    config = _read_json(config_path)
    entries = config.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("release report config requires non-empty entries")

    seen: set[str] = set()
    evidence = []
    for entry in entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id or entry_id in seen:
            raise ValueError(f"invalid or duplicate release evidence id: {entry_id}")
        seen.add(entry_id)
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            raise ValueError(f"release evidence {entry_id} has invalid path")
        source = _safe_source(repository_root, raw_path)
        source_bytes = source.read_bytes()
        payload = json.loads(source_bytes)
        required_true = entry.get("required_true")
        if required_true and _lookup(payload, required_true) is not True:
            raise ValueError(f"release evidence {entry_id} did not pass {required_true}")
        required_false = entry.get("required_false")
        if required_false and _lookup(payload, required_false) is not False:
            raise ValueError(f"release evidence {entry_id} violated {required_false}=false")

        metrics: dict[str, Any] = {}
        for metric in entry.get("metrics", []):
            if not isinstance(metric, list) or len(metric) != 2:
                raise ValueError(f"release evidence {entry_id} has invalid metric entry")
            label, dotted_path = metric
            metrics[label] = _lookup(payload, dotted_path)
        evidence.append(
            {
                "id": entry_id,
                "source": raw_path.replace("\\", "/"),
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "claim_eligible": bool(entry.get("claim_eligible", False)),
                "metrics": metrics,
            }
        )

    claim_eligible_count = sum(item["claim_eligible"] for item in evidence)
    return {
        "schema_version": config.get("schema_version"),
        "release_report_version": config.get("release_report_version"),
        "frozen_at": config.get("frozen_at"),
        "source_tree": config.get("source_tree"),
        "evidence_count": len(evidence),
        "claim_eligible_evidence_count": claim_eligible_count,
        "non_claim_evidence_count": len(evidence) - claim_eligible_count,
        "evidence": evidence,
        "limitations": config.get("limitations", []),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# candle-cli 最终 Benchmark 证据索引",
        "",
        f"- 版本：`{report['release_report_version']}`",
        f"- 冻结日期：`{report['frozen_at']}`",
        f"- 可用于限定范围声明的证据：{report['claim_eligible_evidence_count']}",
        f"- 仅记录、不可用于收益声明的证据：{report['non_claim_evidence_count']}",
        "",
        "| 证据 | 可声明 | 指标 | 来源 |",
        "|---|---:|---|---|",
    ]
    for item in report["evidence"]:
        metrics = "; ".join(
            f"{name}={json.dumps(value, ensure_ascii=False)}"
            for name, value in item["metrics"].items()
        )
        lines.append(
            f"| `{item['id']}` | {'是' if item['claim_eligible'] else '否'} | "
            f"{metrics} | `{item['source']}` |"
        )
    lines.extend(["", "## 限制", ""])
    lines.extend(f"- {value}" for value in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_release_report(args.config, args.root)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
