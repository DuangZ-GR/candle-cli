import json

from migration import training_parity


def test_training_capture_cli_uses_frozen_manifest(monkeypatch, tmp_path, capsys):
    captured = {}

    def fake_capture(framework, output_dir, manifest_path, **options):
        captured.update(
            framework=framework,
            output_dir=output_dir,
            manifest_path=manifest_path,
            options=options,
        )
        return {"status": "captured"}

    monkeypatch.setattr(training_parity, "capture_framework", fake_capture)

    assert training_parity.main(["capture", "pytorch", str(tmp_path)]) == 0
    assert captured["framework"] == "pytorch"
    assert captured["manifest_path"] == str(training_parity.DEFAULT_TRAINING_MANIFEST)
    assert captured["options"] == {
        "overwrite": False,
        "allow_version_mismatch": False,
    }
    assert json.loads(capsys.readouterr().out) == {"status": "captured"}


def test_training_evaluate_cli_returns_failure_for_incomplete_report(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        training_parity,
        "evaluate_benchmark",
        lambda capture_root, manifest_path: {
            "capture_root": str(capture_root),
            "passed": False,
        },
    )

    assert training_parity.main(["evaluate", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False
