import json
import subprocess
import sys
from pathlib import Path

import pytest

from migration.scanner import TENSOR_METHODS, scan_path
from migration.scanner_benchmark import run_benchmark


def scan_source(tmp_path: Path, source: str):
    source_file = tmp_path / "case.py"
    source_file.write_text(source, encoding="utf-8")
    return scan_path(source_file)


@pytest.mark.parametrize(
    ("expression", "expected_api"),
    [
        ("torch.abs(x)", "torch.abs"),
        ("torch.add(x, y)", "torch.add"),
        ("torch.arange(10)", "torch.arange"),
        ("torch.cat([x, y])", "torch.cat"),
        ("torch.concat([x, y])", "torch.concat"),
        ("torch.einsum('ij,jk->ik', x, y)", "torch.einsum"),
        ("torch.empty(2, 3)", "torch.empty"),
        ("torch.flatten(x)", "torch.flatten"),
        ("torch.full((2, 3), 1)", "torch.full"),
        ("torch.gather(x, 0, index)", "torch.gather"),
        ("torch.linspace(0, 1, 10)", "torch.linspace"),
        ("torch.matmul(x, y)", "torch.matmul"),
        ("torch.max(x)", "torch.max"),
        ("torch.mean(x)", "torch.mean"),
        ("torch.ones(2, 3)", "torch.ones"),
        ("torch.permute(x, (1, 0))", "torch.permute"),
        ("torch.rand(2, 3)", "torch.rand"),
        ("torch.randn(2, 3)", "torch.randn"),
        ("torch.reshape(x, (3, 2))", "torch.reshape"),
        ("torch.sigmoid(x)", "torch.sigmoid"),
        ("torch.softmax(x, dim=1)", "torch.softmax"),
        ("torch.split(x, 2)", "torch.split"),
        ("torch.stack([x, y])", "torch.stack"),
        ("torch.sum(x)", "torch.sum"),
        ("torch.tensor([1, 2])", "torch.tensor"),
        ("torch.transpose(x, 0, 1)", "torch.transpose"),
        ("torch.unsqueeze(x, 0)", "torch.unsqueeze"),
        ("torch.where(mask, x, y)", "torch.where"),
        ("torch.zeros(2, 3)", "torch.zeros"),
        ("torch.nn.functional.relu(x)", "torch.nn.functional.relu"),
    ],
)
def test_direct_torch_calls_are_detected(tmp_path, expression, expected_api):
    report = scan_source(tmp_path, f"import torch\nresult = {expression}\n")

    assert expected_api in [finding.api for finding in report.findings]


@pytest.mark.parametrize(
    ("source", "expected_api"),
    [
        ("import torch as t\nt.sum(x)\n", "torch.sum"),
        ("import torch.nn.functional as F\nF.relu(x)\n", "torch.nn.functional.relu"),
        ("from torch import sum\nsum(x)\n", "torch.sum"),
        ("from torch import sum as tsum\ntsum(x)\n", "torch.sum"),
        ("from torch import nn\nnn.Linear(2, 3)\n", "torch.nn.Linear"),
        ("from torch import nn as n\nn.ReLU()\n", "torch.nn.ReLU"),
        ("from torch.nn import functional\nfunctional.relu(x)\n", "torch.nn.functional.relu"),
        ("from torch.nn import functional as F\nF.gelu(x)\n", "torch.nn.functional.gelu"),
        ("from torch.nn.functional import relu\nrelu(x)\n", "torch.nn.functional.relu"),
        ("from torch.nn.functional import relu as activate\nactivate(x)\n", "torch.nn.functional.relu"),
        ("from torch import Tensor\nTensor([1])\n", "torch.Tensor"),
        ("from torch import Tensor as T\nT([1])\n", "torch.Tensor"),
        ("import torch.linalg as la\nla.norm(x)\n", "torch.linalg.norm"),
        ("import torch.special as special\nspecial.expit(x)\n", "torch.special.expit"),
        ("import torch\ntorch.nn.Conv2d(3, 8, 3)\n", "torch.nn.Conv2d"),
    ],
)
def test_import_aliases_are_resolved(tmp_path, source, expected_api):
    report = scan_source(tmp_path, source)

    assert [finding.api for finding in report.findings] == [expected_api]


@pytest.mark.parametrize("method", sorted(TENSOR_METHODS))
def test_known_tensor_methods_are_detected_after_tensor_assignment(tmp_path, method):
    source = f"import torch\nx = torch.tensor([1.0])\nx.{method}()\n"
    report = scan_source(tmp_path, source)

    assert f"torch.Tensor.{method}" in [finding.api for finding in report.findings]


@pytest.mark.parametrize(
    "source",
    [
        "import numpy as np\nnp.sum(x)\n",
        "items = []\nitems.append(1)\n",
        "text = 'x'\ntext.split()\n",
        "class Box:\n    def sum(self): pass\nBox().sum()\n",
        "def sum(x): return x\nsum(1)\n",
        "from other import torch\ntorch.sum(x)\n",
        "import tensorflow as torch\ntorch.sum(x)\n",
        "obj.reshape(2, 3)\n",
        "mapping.get('torch')\n",
        "getattr(other, 'sum')(x)\n",
    ],
)
def test_non_torch_calls_are_not_reported(tmp_path, source):
    report = scan_source(tmp_path, source)

    assert report.findings == []


def test_alias_assignment_stops_resolution_after_shadowing(tmp_path):
    report = scan_source(
        tmp_path,
        "import torch as t\nt.sum(x)\nt = object()\nt.sum(x)\n",
    )

    assert [finding.api for finding in report.findings] == ["torch.sum"]


@pytest.mark.parametrize(
    "replacement",
    [
        "import numpy as t",
        "from numpy import sum as t",
        "from other import torch as t",
    ],
)
def test_non_torch_import_stops_resolution_after_alias_shadowing(tmp_path, replacement):
    report = scan_source(
        tmp_path,
        f"import torch as t\nt.sum(x)\n{replacement}\nt.sum(x)\n",
    )

    assert [finding.api for finding in report.findings] == ["torch.sum"]


def test_function_argument_shadows_global_torch_alias(tmp_path):
    report = scan_source(
        tmp_path,
        "import torch as t\ndef run(t):\n    return t.sum(x)\nt.sum(x)\n",
    )

    assert [finding.api for finding in report.findings] == ["torch.sum"]


def test_function_local_import_is_scoped(tmp_path):
    report = scan_source(
        tmp_path,
        "def run():\n    import torch as t\n    return t.sum(x)\n",
    )

    assert [finding.api for finding in report.findings] == ["torch.sum"]


def test_tensor_annotation_enables_method_detection(tmp_path):
    report = scan_source(
        tmp_path,
        "import torch\ndef run(x: torch.Tensor):\n    return x.reshape(2, 3)\n",
    )

    assert [finding.api for finding in report.findings] == ["torch.Tensor.reshape"]


def test_tensor_result_inference_enables_method_detection(tmp_path):
    report = scan_source(
        tmp_path,
        "import torch.nn.functional as F\ny = F.relu(x)\ny.sum()\n",
    )

    assert [finding.api for finding in report.findings] == [
        "torch.nn.functional.relu",
        "torch.Tensor.sum",
    ]


def test_chained_tensor_method_and_inner_factory_are_both_detected(tmp_path):
    report = scan_source(tmp_path, "import torch\ntorch.rand(2, 3).reshape(3, 2)\n")
    apis = [finding.api for finding in report.findings]

    assert sorted(apis) == ["torch.Tensor.reshape", "torch.rand"]


def test_literal_getattr_is_resolved(tmp_path):
    report = scan_source(tmp_path, "import torch\ngetattr(torch, 'sum')(x)\n")

    assert [finding.api for finding in report.findings] == ["torch.sum"]
    assert report.findings[0].call_kind == "dynamic"
    assert report.findings[0].confidence == 0.95


def test_dynamic_getattr_is_reported_as_high_risk(tmp_path):
    report = scan_source(tmp_path, "import torch\ngetattr(torch, name)(x)\n")

    assert [finding.api for finding in report.findings] == ["torch.<dynamic>"]
    assert report.findings[0].risk_level == "high"
    assert report.findings[0].confidence == 0.5


def test_keyword_names_and_source_location_are_recorded(tmp_path):
    report = scan_source(
        tmp_path,
        "import torch\nvalue = torch.sum(x, dim=1, keepdim=True)\n",
    )
    finding = report.findings[0]

    assert finding.location.file == "case.py"
    assert finding.location.line == 2
    assert finding.location.column == 8
    assert finding.positional_argument_count == 1
    assert finding.keyword_arguments == ["dim", "keepdim"]
    assert finding.expression == "torch.sum(x, dim=1, keepdim=True)"


def test_scan_report_summary_is_deterministic(tmp_path):
    (tmp_path / "b.py").write_text("import torch\ntorch.sum(x)\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("import torch\ntorch.mean(x)\n", encoding="utf-8")

    first = scan_path(tmp_path).to_dict()
    second = scan_path(tmp_path).to_dict()

    assert first == second
    assert [item["location"]["file"] for item in first["findings"]] == ["a.py", "b.py"]
    assert first["summary"]["api_counts"] == {"torch.mean": 1, "torch.sum": 1}


def test_ignored_directories_are_not_scanned(tmp_path):
    ignored = tmp_path / ".venv"
    ignored.mkdir()
    (ignored / "ignored.py").write_text("import torch\ntorch.sum(x)\n", encoding="utf-8")
    (tmp_path / "visible.py").write_text("import torch\ntorch.mean(x)\n", encoding="utf-8")

    report = scan_path(tmp_path)

    assert report.files_discovered == 1
    assert [finding.api for finding in report.findings] == ["torch.mean"]


def test_syntax_errors_are_structured_and_do_not_abort_directory_scan(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "good.py").write_text("import torch\ntorch.sum(x)\n", encoding="utf-8")

    report = scan_path(tmp_path)

    assert report.files_discovered == 2
    assert report.files_scanned == 1
    assert [finding.api for finding in report.findings] == ["torch.sum"]
    assert report.issues[0].kind == "syntax_error"
    assert report.issues[0].line == 1


def test_large_files_are_skipped_with_an_issue(tmp_path):
    source_file = tmp_path / "large.py"
    source_file.write_text("import torch\ntorch.sum(x)\n", encoding="utf-8")

    report = scan_path(tmp_path, max_file_bytes=10)

    assert report.files_scanned == 0
    assert report.issues[0].kind == "file_too_large"


def test_pep263_source_encoding_is_respected(tmp_path):
    source_file = tmp_path / "encoded.py"
    source_file.write_bytes(
        "# -*- coding: latin-1 -*-\n# café\nimport torch\ntorch.sum(x)\n".encode(
            "latin-1"
        )
    )

    report = scan_path(source_file)

    assert [finding.api for finding in report.findings] == ["torch.sum"]


@pytest.mark.parametrize("invalid_path", ["missing.py", "not_python.txt"])
def test_invalid_scan_paths_fail_explicitly(tmp_path, invalid_path):
    path = tmp_path / invalid_path
    if path.suffix == ".txt":
        path.write_text("content", encoding="utf-8")

    with pytest.raises((FileNotFoundError, ValueError)):
        scan_path(path)


def test_scanner_module_emits_utf8_json_and_nonzero_for_partial_report(tmp_path):
    (tmp_path / "good.py").write_text(
        "import torch\nvalue = torch.sum(x)\n", encoding="utf-8"
    )
    command = [
        sys.executable,
        "-m",
        "migration.scanner",
        str(tmp_path),
        "--pretty",
    ]

    result = subprocess.run(command, text=True, encoding="utf-8", capture_output=True)

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["record_kind"] == "scan_report"
    assert report["summary"]["finding_count"] == 1


def test_fixed_scanner_benchmark_meets_initial_precision_and_recall_target():
    result = run_benchmark()

    assert result["task_count"] == 50
    assert result["precision"] >= 0.95
    assert result["recall"] >= 0.95
