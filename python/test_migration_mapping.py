import copy
import json

import pytest

from migration.mapping import DEFAULT_KNOWLEDGE_BASE, MappingKnowledgeBase
from migration.mapping_benchmark import run_benchmark
from migration.schema import SchemaError


def load_payload():
    return json.loads(DEFAULT_KNOWLEDGE_BASE.read_text(encoding="utf-8"))


def test_default_mapping_snapshot_validates():
    knowledge = MappingKnowledgeBase.load()

    assert len(knowledge.entries) == 53
    assert knowledge.payload["source_framework"]["version"] == "2.1"
    assert knowledge.payload["target_framework"]["version"] == "2.9.0"


def test_exact_mapping_contains_versions_and_evidence():
    result = MappingKnowledgeBase.load().resolve("torch.sum")

    assert result.status == "exact"
    assert result.target_api == "mindspore.mint.sum"
    assert result.source_framework_version == "2.1"
    assert result.target_framework_version == "2.9.0"
    assert result.evidence_urls[0].startswith("https://www.mindspore.cn/")


def test_difference_mapping_preserves_difference_category():
    result = MappingKnowledgeBase.load().resolve("torch.arange")

    assert result.status == "difference"
    assert result.differences == ["default_value"]
    assert "默认值" in result.notes


def test_unknown_is_not_misreported_as_unsupported():
    result = MappingKnowledgeBase.load().resolve("torch.future_operator")

    assert result.status == "unknown"
    assert result.target_api is None
    assert result.evidence_urls == []
    assert "不能据此判断" in result.notes


def test_lookup_trims_surrounding_whitespace():
    result = MappingKnowledgeBase.load().resolve("  torch.sum  ")
    assert result.source_api == "torch.sum"
    assert result.status == "exact"


def test_fixed_mapping_benchmark_reports_reproducible_coverage():
    result = run_benchmark()

    assert result["unique_api_count"] == 36
    assert result["known_api_count"] == 27
    assert result["coverage"] == 0.75


@pytest.mark.parametrize(
    ("api", "target", "status", "differences"),
    [
        ("torch.randint", "mindspore.mint.randint", "exact", []),
        ("torch.nn.Conv2d", "mindspore.mint.nn.Conv2d", "exact", []),
        ("torch.nn.ConvTranspose2d", "mindspore.mint.nn.ConvTranspose2d", "exact", []),
        ("torch.nn.GroupNorm", "mindspore.mint.nn.GroupNorm", "exact", []),
        ("torch.nn.LayerNorm", "mindspore.mint.nn.LayerNorm", "exact", []),
        ("torch.nn.Dropout", "mindspore.mint.nn.Dropout", "difference", ["logic"]),
        ("torch.nn.BatchNorm2d", "mindspore.mint.nn.BatchNorm2d", "difference", ["logic"]),
        (
            "torch.nn.functional.interpolate",
            "mindspore.mint.nn.functional.interpolate",
            "difference",
            ["parameter_count"],
        ),
        (
            "torchvision.transforms.ToTensor",
            "mindspore.dataset.vision.ToTensor",
            "difference",
            ["parameter_count", "return_structure"],
        ),
        (
            "torch.utils.data.DataLoader",
            "mindspore.dataset.GeneratorDataset",
            "difference",
            ["logic"],
        ),
        ("torch.nn.Embedding", "mindspore.mint.nn.Embedding", "exact", []),
        (
            "torch.distributed.all_reduce",
            "mindspore.mint.distributed.all_reduce",
            "exact",
            [],
        ),
        ("torch.Tensor.max", "mindspore.Tensor.max", "exact", []),
        (
            "torchvision.datasets.MNIST",
            "mindspore.dataset.MnistDataset",
            "difference",
            ["logic"],
        ),
        (
            "torchvision.transforms.Compose",
            "mindspore.dataset.transforms.Compose",
            "exact",
            [],
        ),
        (
            "torchvision.transforms.Normalize",
            "mindspore.dataset.vision.Normalize",
            "difference",
            ["parameter_count", "default_value"],
        ),
    ],
)
def test_real_project_driven_entries_preserve_safety_classification(
    api, target, status, differences
):
    result = MappingKnowledgeBase.load().resolve(api)

    assert result.target_api == target
    assert result.status == status
    assert result.differences == differences
    assert result.evidence_urls


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version="2.0"), "unsupported schema"),
        (lambda data: data.update(snapshot_version=""), "snapshot_version"),
        (lambda data: data.update(source_url=""), "source_url"),
        (lambda data: data["source_framework"].update(name="other"), "must be pytorch"),
        (lambda data: data["target_framework"].update(version=""), "version"),
        (lambda data: data.update(entries={}), "entries must be an array"),
        (lambda data: data["entries"].append(copy.deepcopy(data["entries"][0])), "duplicate"),
        (lambda data: data["entries"][0].update(status="maybe"), "invalid status"),
        (lambda data: data["entries"][0].update(target_api="torch.abs"), "target_api"),
        (lambda data: data["entries"][0].update(differences=["magic"]), "differences"),
        (lambda data: data["entries"][0].update(differences=["logic"]), "must not contain"),
        (lambda data: data["entries"][2].update(differences=[]), "requires differences"),
        (lambda data: data["entries"][0].update(notes=""), "requires notes"),
        (lambda data: data["entries"][0].update(evidence_urls=[]), "evidence_urls"),
    ],
)
def test_invalid_knowledge_base_is_rejected(mutation, message):
    payload = load_payload()
    mutation(payload)

    with pytest.raises(SchemaError, match=message):
        MappingKnowledgeBase(payload)
