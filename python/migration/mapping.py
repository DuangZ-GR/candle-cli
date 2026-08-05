"""Versioned, evidence-backed PyTorch to MindSpore API mapping lookup."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from migration.schema import SCHEMA_VERSION, SchemaError, ensure_compatible_schema

DEFAULT_KNOWLEDGE_BASE = (
    Path(__file__).parents[2]
    / "knowledge"
    / "mappings"
    / "mindspore-2.9.0-pytorch-2.1.json"
)
ALLOWED_STATUSES = {"exact", "difference", "unsupported"}
ALLOWED_DIFFERENCES = {
    "parameter_name",
    "parameter_order",
    "parameter_count",
    "parameter_type",
    "default_value",
    "input_dtype",
    "output_dtype",
    "return_structure",
    "logic",
    "device",
    "graph_mode",
    "randomness",
    "other",
}


@dataclass(frozen=True)
class MappingEntry:
    source_api: str
    target_api: str | None
    status: str
    differences: list[str]
    notes: str
    evidence_urls: list[str]


@dataclass(frozen=True)
class MappingResolution:
    source_api: str
    target_api: str | None
    status: str
    differences: list[str]
    notes: str
    evidence_urls: list[str]
    source_framework_version: str
    target_framework_version: str
    knowledge_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MappingKnowledgeBase:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self._validate()
        self.entries = {
            item["source_api"]: MappingEntry(**item) for item in payload["entries"]
        }

    @classmethod
    def load(cls, path: str | Path = DEFAULT_KNOWLEDGE_BASE) -> "MappingKnowledgeBase":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SchemaError(f"failed to load mapping knowledge base: {error}") from error
        if not isinstance(payload, dict):
            raise SchemaError("mapping knowledge base root must be an object")
        return cls(payload)

    def _validate(self) -> None:
        ensure_compatible_schema(str(self.payload.get("schema_version", "")))
        for field_name in ("snapshot_version", "collected_at", "source_url"):
            value = self.payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise SchemaError(f"{field_name} must not be empty")
        for framework_field, expected_name in (
            ("source_framework", "pytorch"),
            ("target_framework", "mindspore"),
        ):
            framework = self.payload.get(framework_field)
            if not isinstance(framework, dict):
                raise SchemaError(f"{framework_field} must be an object")
            if framework.get("name") != expected_name:
                raise SchemaError(f"{framework_field}.name must be {expected_name}")
            if not str(framework.get("version", "")).strip():
                raise SchemaError(f"{framework_field}.version must not be empty")
        entries = self.payload.get("entries")
        if not isinstance(entries, list):
            raise SchemaError("entries must be an array")
        seen = set()
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                raise SchemaError(f"entry {index} must be an object")
            source_api = item.get("source_api")
            if not isinstance(source_api, str) or not source_api.startswith("torch"):
                raise SchemaError(f"entry {index} has invalid source_api")
            if source_api in seen:
                raise SchemaError(f"duplicate source_api: {source_api}")
            seen.add(source_api)
            status = item.get("status")
            if status not in ALLOWED_STATUSES:
                raise SchemaError(f"entry {source_api} has invalid status: {status}")
            target_api = item.get("target_api")
            if status != "unsupported" and (
                not isinstance(target_api, str) or not target_api.startswith("mindspore")
            ):
                raise SchemaError(f"entry {source_api} requires a MindSpore target_api")
            if status == "unsupported" and target_api is not None:
                raise SchemaError(f"unsupported entry {source_api} must not have target_api")
            differences = item.get("differences")
            if not isinstance(differences, list) or any(
                difference not in ALLOWED_DIFFERENCES for difference in differences
            ):
                raise SchemaError(f"entry {source_api} has invalid differences")
            if status == "exact" and differences:
                raise SchemaError(f"exact entry {source_api} must not contain differences")
            if status == "difference" and not differences:
                raise SchemaError(f"difference entry {source_api} requires differences")
            notes = item.get("notes")
            if not isinstance(notes, str) or not notes.strip():
                raise SchemaError(f"entry {source_api} requires notes")
            evidence_urls = item.get("evidence_urls")
            if not isinstance(evidence_urls, list) or not evidence_urls or any(
                not isinstance(url, str) or not url.startswith("https://")
                for url in evidence_urls
            ):
                raise SchemaError(f"entry {source_api} requires HTTPS evidence_urls")

    def resolve(self, source_api: str) -> MappingResolution:
        normalized = source_api.strip()
        entry = self.entries.get(normalized)
        source_version = self.payload["source_framework"]["version"]
        target_version = self.payload["target_framework"]["version"]
        knowledge_version = self.payload["snapshot_version"]
        if entry is None:
            return MappingResolution(
                source_api=normalized,
                target_api=None,
                status="unknown",
                differences=[],
                notes="当前固定知识库未收录该 API；不能据此判断 MindSpore 不支持。",
                evidence_urls=[],
                source_framework_version=source_version,
                target_framework_version=target_version,
                knowledge_version=knowledge_version,
            )
        return MappingResolution(
            **asdict(entry),
            source_framework_version=source_version,
            target_framework_version=target_version,
            knowledge_version=knowledge_version,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api")
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--pretty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        knowledge = MappingKnowledgeBase.load(arguments.knowledge_base)
        result = knowledge.resolve(arguments.api)
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
