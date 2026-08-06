import json

import pytest

from python.agent_experiment import evaluate_runs, load_config


def _config():
    return {
        "schema_version": "1.0",
        "benchmark_version": "agent-ablation-test-v1",
        "provider": {"name": "fixture", "model": "fixture-model", "temperature": 0.0},
        "pricing": {
            "price_date": "2026-08-06",
            "input_per_million_tokens": 1.0,
            "output_per_million_tokens": 2.0,
            "cached_input_per_million_tokens": 0.1,
        },
        "repetitions": 3,
        "budgets": {"max_model_requests": 8, "max_tool_steps": 8, "timeout_ms": 1000},
        "arms": [
            {"id": "single", "task_tool_enabled": False},
            {"id": "delegated", "task_tool_enabled": True},
        ],
        "scenarios": [{"id": "case-a"}, {"id": "case-b"}],
    }


def _usage(*, cached=None):
    return {
        "usage_complete": True,
        "cache_metrics_complete": cached is not None,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "cached_prompt_tokens": cached,
        "retry_count": 1,
        "provider_latency_ms": 50,
    }


def _runs(*, cached=None, delegated_passes=True):
    records = []
    for scenario in ("case-a", "case-b"):
        for trial in range(1, 4):
            for arm in ("single", "delegated"):
                passed = arm == "delegated" and delegated_passes
                records.append(
                    {
                        "scenario_id": scenario,
                        "arm_id": arm,
                        "trial": trial,
                        "passed": passed,
                        "elapsed_ms": 100 if arm == "single" else 80,
                        "tool_steps": 4,
                        "model_requests": 5,
                        "human_interventions": 0,
                        "failure_type": None if passed else "incorrect_diagnosis",
                        "usage": _usage(cached=cached),
                    }
                )
    return {
        "schema_version": "1.0",
        "benchmark_version": "agent-ablation-test-v1",
        "provider": "fixture",
        "model": "fixture-model",
        "temperature": 0.0,
        "run_mode": "formal",
        "claim_eligible": True,
        "runs": records,
    }


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_evaluator_reports_unsupported_cache_as_null(tmp_path):
    config = _write(tmp_path, "config.json", _config())
    runs = _write(tmp_path, "runs.json", _runs())

    report = evaluate_runs(config, runs)

    assert report["budget_comparable"] is True
    assert report["provider_usage_complete"] is True
    assert report["provider_cache_status"] == "unsupported"
    assert report["provider_cache_hit_rate"] is None
    assert report["comparison"]["claim_supported"] is True
    assert report["arms"]["single"]["retry_count"] == 6
    assert report["arms"]["single"]["retry_rate"] == 0.2
    assert report["arms"]["single"]["provider_latency_ms"] == 300
    assert report["provider_retry_count"] == 12
    assert report["provider_retry_rate"] == 0.2
    assert report["passed"] is True


def test_evaluator_uses_only_provider_returned_cache_tokens(tmp_path):
    config = _write(tmp_path, "config.json", _config())
    runs = _write(tmp_path, "runs.json", _runs(cached=75))

    report = evaluate_runs(config, runs)

    assert report["provider_cache_status"] == "supported"
    assert report["provider_cache_hit_rate"] == 0.75
    assert report["arms"]["single"]["provider_cache_hit_rate"] == 0.75
    assert report["arms"]["single"]["estimated_provider_cost_usd"] is not None


def test_evaluator_rejects_incomplete_paired_coverage(tmp_path):
    config = _write(tmp_path, "config.json", _config())
    payload = _runs()
    payload["runs"].pop()
    runs = _write(tmp_path, "runs.json", payload)

    with pytest.raises(ValueError, match="coverage mismatch"):
        evaluate_runs(config, runs)


def test_evaluator_rejects_smoke_runs_even_if_metadata_matches(tmp_path):
    config = _write(tmp_path, "config.json", _config())
    payload = _runs()
    payload["run_mode"] = "smoke"
    payload["claim_eligible"] = False
    runs = _write(tmp_path, "runs.json", payload)

    with pytest.raises(ValueError, match="not eligible"):
        evaluate_runs(config, runs)


def test_budget_violation_blocks_experiment(tmp_path):
    config = _write(tmp_path, "config.json", _config())
    payload = _runs()
    payload["runs"][0]["tool_steps"] = 9
    runs = _write(tmp_path, "runs.json", payload)

    report = evaluate_runs(config, runs)

    assert report["budget_comparable"] is False
    assert report["budget_violations"]
    assert report["passed"] is False


def test_frozen_manifest_has_real_migration_scenarios_but_no_fake_provider():
    with open("benchmarks/agent/agent_ablation_v1.json", encoding="utf-8") as source:
        payload = json.load(source)

    assert len(payload["scenarios"]) == 10
    assert payload["repetitions"] == 3
    assert payload["provider"]["name"] == "TO_BE_SELECTED"
    assert payload["provider"]["model"] == "TO_BE_SELECTED"
    with pytest.raises(ValueError, match="not frozen"):
        load_config("benchmarks/agent/agent_ablation_v1.json")
