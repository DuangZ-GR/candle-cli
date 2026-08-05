import ast
import json
import sys

import pytest

import migration.rewriter as rewriter
from migration.rewriter import (
    RewriteValidationError,
    apply_plan,
    main,
    plan_rewrite,
    rollback_transaction,
)


def write_source(tmp_path, source, name="model.py"):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8", newline="")
    return path


def patched(plan):
    assert len(plan.files) == 1
    return plan.files[0].patched_source


def test_rewrites_exact_api_and_adds_mindspore_import(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")
    result = patched(plan_rewrite(path))

    assert result == "import mindspore\nimport torch\ny = mindspore.mint.add(x, 1)\n"
    ast.parse(result)


def test_resolves_torch_alias_without_reformatting_file(tmp_path):
    path = write_source(tmp_path, "import torch as th\nresult=th.abs(x)  # keep\n")
    result = patched(plan_rewrite(path))

    assert "result=mindspore.mint.abs(x)  # keep" in result


def test_resolves_from_import_alias(tmp_path):
    path = write_source(tmp_path, "from torch import add as plus\ny = plus(x, 1)\n")
    result = patched(plan_rewrite(path))

    assert "y = mindspore.mint.add(x, 1)" in result


def test_uses_existing_mindspore_alias(tmp_path):
    path = write_source(
        tmp_path,
        "import mindspore as ms\nimport torch\ny = torch.add(x, 1)\n",
    )
    result = patched(plan_rewrite(path))

    assert result.count("import mindspore") == 1
    assert "ms.mint.add" in result


def test_rewrites_dtype_constant_inside_an_accepted_call(tmp_path):
    path = write_source(
        tmp_path,
        "import torch as th\ny = th.zeros((2, 3), dtype=th.float32)\n",
    )
    plan = plan_rewrite(path)
    result = patched(plan)

    assert "mindspore.mint.zeros((2, 3), dtype=mindspore.float32)" in result
    assert [edit.source_api for edit in plan.files[0].edits] == [
        "<import>",
        "torch.zeros",
        "torch.float32",
    ]
    assert plan.to_dict()["mapping_counts"] == {"exact": 2, "difference": 0}


def test_dtype_uses_existing_mindspore_alias(tmp_path):
    path = write_source(
        tmp_path,
        "import mindspore as ms\nimport torch\ny = torch.ones(2, dtype=torch.int64)\n",
    )

    assert "ms.mint.ones(2, dtype=ms.int64)" in patched(plan_rewrite(path))


def test_dtype_is_not_rewritten_when_enclosing_api_is_not_accepted(tmp_path):
    path = write_source(
        tmp_path,
        "import torch\na = torch.future_api(2, dtype=torch.float32)\n"
        "b = torch.arange(5, dtype=torch.float32)\n",
    )

    assert plan_rewrite(path).files == []


def test_difference_mapping_is_previewed_only_when_explicitly_enabled(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.arange(5)\n")

    default_plan = plan_rewrite(path)
    enabled_plan = plan_rewrite(path, include_differences=True)

    assert default_plan.files == []
    assert "mindspore.mint.arange" in patched(enabled_plan)
    assert enabled_plan.to_dict()["mapping_counts"]["difference"] == 1


def test_unknown_api_and_tensor_method_are_not_rewritten(tmp_path):
    path = write_source(
        tmp_path,
        "import torch\na = torch.future_api(x)\nb: torch.Tensor = x\nc = b.sum()\n",
    )

    assert plan_rewrite(path).files == []


def test_nested_calls_produce_non_overlapping_minimal_edits(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(torch.abs(x), 1)\n")
    plan = plan_rewrite(path)
    result = patched(plan)

    assert "mindspore.mint.add(mindspore.mint.abs(x), 1)" in result
    assert len(plan.files[0].edits) == 3  # two APIs plus one import


def test_utf8_columns_before_call_are_converted_to_character_offsets(tmp_path):
    path = write_source(tmp_path, "import torch\n结果 = '中文'; y = torch.add(x, 1)\n")
    result = patched(plan_rewrite(path))

    assert "结果 = '中文'; y = mindspore.mint.add(x, 1)" in result


def test_import_is_inserted_after_shebang_docstring_and_future_import(tmp_path):
    source = (
        "#!/usr/bin/env python3\n"
        '"""module docs"""\n'
        "from __future__ import annotations\n"
        "import torch\n"
        "y = torch.add(x, 1)\n"
    )
    path = write_source(tmp_path, source)
    result = patched(plan_rewrite(path))

    assert result.startswith(
        "#!/usr/bin/env python3\n"
        '"""module docs"""\n'
        "from __future__ import annotations\n"
        "import mindspore\n"
    )


def test_syntax_error_is_reported_without_a_patch(tmp_path):
    path = write_source(tmp_path, "import torch\nif:\n")
    plan = plan_rewrite(path)

    assert plan.files == []
    assert plan.issues[0]["kind"] == "syntax_error"


def test_plan_contains_hashes_and_unified_diff(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")
    report = plan_rewrite(path).to_dict()

    assert report["record_kind"] == "rewrite_plan"
    assert report["files_changed"] == 1
    assert report["edit_count"] == 2
    assert report["mapping_counts"] == {"exact": 1, "difference": 0}
    assert len(report["files"][0]["original_sha256"]) == 64
    assert "-y = torch.add" in report["files"][0]["diff"]
    assert "+y = mindspore.mint.add" in report["files"][0]["diff"]


def test_apply_creates_backup_manifest_and_rollback_restores_source(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")
    original = path.read_bytes()
    apply_report = apply_plan(plan_rewrite(path))

    assert "mindspore.mint.add" in path.read_text(encoding="utf-8")
    manifest_path = apply_report["manifest"]
    manifest = json.loads(open(manifest_path, encoding="utf-8").read())
    assert manifest["status"] == "applied"
    assert len(manifest["files"]) == 1

    rollback_report = rollback_transaction(manifest_path)

    assert rollback_report["files_restored"] == 1
    assert path.read_bytes() == original
    assert json.loads(open(manifest_path, encoding="utf-8").read())["status"] == "rolled_back"


def test_apply_rejects_stale_preview_without_changing_source(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")
    plan = plan_rewrite(path)
    path.write_text("# changed\n" + path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(RuntimeError, match="source changed after preview"):
        apply_plan(plan)

    assert path.read_text(encoding="utf-8").startswith("# changed")
    assert not (tmp_path / ".candle-cli").exists()


def test_apply_refuses_partial_plan_by_default(tmp_path):
    write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n", "good.py")
    write_source(tmp_path, "if:\n", "bad.py")
    plan = plan_rewrite(tmp_path)

    with pytest.raises(ValueError, match="refuse partial apply"):
        apply_plan(plan)

    assert "torch.add" in (tmp_path / "good.py").read_text(encoding="utf-8")


def test_rollback_rejects_user_changes_after_apply(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")
    report = apply_plan(plan_rewrite(path))
    path.write_text(path.read_text(encoding="utf-8") + "# user change\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after apply"):
        rollback_transaction(report["manifest"])

    assert path.read_text(encoding="utf-8").endswith("# user change\n")


def test_apply_and_rollback_preserve_crlf_bytes(tmp_path):
    path = write_source(tmp_path, "import torch\r\ny = torch.add(x, 1)\r\n")
    original = path.read_bytes()
    report = apply_plan(plan_rewrite(path))

    assert b"\r\n" in path.read_bytes()
    assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")
    rollback_transaction(report["manifest"])
    assert path.read_bytes() == original


def test_apply_and_rollback_preserve_declared_non_utf8_encoding(tmp_path):
    path = tmp_path / "latin.py"
    original = "# -*- coding: latin-1 -*-\n# café\nimport torch\ny = torch.add(x, 1)\n".encode(
        "latin-1"
    )
    path.write_bytes(original)
    report = apply_plan(plan_rewrite(path))

    assert "mindspore.mint.add" in path.read_bytes().decode("latin-1")
    rollback_transaction(report["manifest"])
    assert path.read_bytes() == original


def test_apply_rolls_back_if_final_manifest_update_fails(tmp_path, monkeypatch):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")
    original = path.read_bytes()
    real_atomic_write = rewriter._atomic_write
    failed = False

    def fail_applied_manifest(target, contents, mode_from=None):
        nonlocal failed
        if (
            target.name == "manifest.json"
            and b'"status": "applied"' in contents
            and not failed
        ):
            failed = True
            raise OSError("injected manifest failure")
        return real_atomic_write(target, contents, mode_from)

    monkeypatch.setattr(rewriter, "_atomic_write", fail_applied_manifest)

    with pytest.raises(OSError, match="injected manifest failure"):
        apply_plan(plan_rewrite(path))

    assert path.read_bytes() == original
    manifests = list((tmp_path / ".candle-cli" / "backups").glob("*/manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text(encoding="utf-8"))["status"] == "aborted"


def test_successful_validation_marks_apply_as_verified(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")

    report = apply_plan(
        plan_rewrite(path),
        validation_command=[sys.executable, "-c", "print('validation ok')"],
    )

    assert report["verified"] is True
    assert report["validation"]["status"] == "passed"
    assert "validation ok" in report["validation"]["stdout"]


def test_failed_validation_rolls_back_and_records_failure(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")
    original = path.read_bytes()

    with pytest.raises(RewriteValidationError, match="rolled back"):
        apply_plan(
            plan_rewrite(path),
            validation_command=[sys.executable, "-c", "raise SystemExit(7)"],
        )

    assert path.read_bytes() == original
    manifest_path = next((tmp_path / ".candle-cli" / "backups").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "aborted"
    assert manifest["validation"]["status"] == "failed"
    assert manifest["validation"]["return_code"] == 7


def test_unexpected_validation_exception_also_rolls_back(tmp_path, monkeypatch):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")
    original = path.read_bytes()

    def fail_to_start(*_args, **_kwargs):
        raise ValueError("injected invalid process arguments")

    monkeypatch.setattr(rewriter.subprocess, "run", fail_to_start)

    with pytest.raises(ValueError, match="injected invalid process arguments"):
        apply_plan(plan_rewrite(path), validation_command=[sys.executable])

    assert path.read_bytes() == original
    manifest_path = next((tmp_path / ".candle-cli" / "backups").glob("*/manifest.json"))
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "aborted"


def test_apply_without_validation_is_explicitly_unverified(tmp_path):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")

    report = apply_plan(plan_rewrite(path))

    assert report["verified"] is False
    assert report["validation"] == {"status": "not_run"}


def test_cli_preview_does_not_modify_source(tmp_path, capsys):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")

    assert main(["plan", str(path), "--pretty"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["record_kind"] == "rewrite_plan"
    assert report["files_changed"] == 1
    assert "torch.add" in path.read_text(encoding="utf-8")


def test_cli_apply_then_rollback(tmp_path, capsys):
    path = write_source(tmp_path, "import torch\ny = torch.add(x, 1)\n")

    assert main(["plan", str(path), "--apply"]) == 0
    apply_report = json.loads(capsys.readouterr().out)
    assert apply_report["record_kind"] == "rewrite_apply_report"
    assert main(["rollback", apply_report["manifest"]]) == 0
    rollback_report = json.loads(capsys.readouterr().out)

    assert rollback_report["record_kind"] == "rewrite_rollback_report"
    assert "torch.add" in path.read_text(encoding="utf-8")
