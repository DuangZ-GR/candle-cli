"""Validate and aggregate equal-budget single/multi-agent experiment runs."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExperimentConfig:
    benchmark_version: str
    provider: str
    model: str
    temperature: float
    price_date: str
    repetitions: int
    scenario_ids: tuple[str, ...]
    arm_ids: tuple[str, ...]
    max_model_requests: int
    max_tool_steps: int
    timeout_ms: int
    input_price_per_million: float | None
    output_price_per_million: float | None
    cached_input_price_per_million: float | None


@dataclass(frozen=True)
class RunRecord:
    scenario_id: str
    arm_id: str
    trial: int
    passed: bool
    elapsed_ms: int
    tool_steps: int
    model_requests: int
    human_interventions: int
    failure_type: str | None
    usage: dict[str, Any] | None


def load_config(path: str | Path) -> ExperimentConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("unsupported agent experiment schema_version")
    provider = payload.get("provider")
    budgets = payload.get("budgets")
    pricing = payload.get("pricing")
    if not isinstance(provider, dict) or not isinstance(budgets, dict):
        raise ValueError("agent experiment requires provider and budgets objects")
    if not isinstance(pricing, dict):
        pricing = {}
    scenarios = tuple(_required_text(item, "id") for item in payload.get("scenarios", []))
    arms = tuple(_required_text(item, "id") for item in payload.get("arms", []))
    if len(scenarios) < 1 or len(set(scenarios)) != len(scenarios):
        raise ValueError("agent experiment scenarios must be non-empty and unique")
    if set(arms) != {"single", "delegated"}:
        raise ValueError("agent experiment requires single and delegated arms")
    provider_name = _required_text(provider, "name")
    model = _required_text(provider, "model")
    price_date = _required_text(pricing, "price_date")
    if provider_name.startswith("TO_BE_") or model.startswith("TO_BE_"):
        raise ValueError("agent experiment provider/model is not frozen")
    if price_date.startswith("TO_BE_"):
        raise ValueError("agent experiment price_date is not frozen")
    input_price = _optional_non_negative_number(pricing, "input_per_million_tokens")
    output_price = _optional_non_negative_number(pricing, "output_per_million_tokens")
    if input_price is None or output_price is None:
        raise ValueError("agent experiment input/output prices must be frozen")
    repetitions = _positive_int(payload, "repetitions")
    return ExperimentConfig(
        benchmark_version=_required_text(payload, "benchmark_version"),
        provider=provider_name,
        model=model,
        temperature=_non_negative_number(provider, "temperature"),
        price_date=price_date,
        repetitions=repetitions,
        scenario_ids=scenarios,
        arm_ids=arms,
        max_model_requests=_positive_int(budgets, "max_model_requests"),
        max_tool_steps=_positive_int(budgets, "max_tool_steps"),
        timeout_ms=_positive_int(budgets, "timeout_ms"),
        input_price_per_million=input_price,
        output_price_per_million=output_price,
        cached_input_price_per_million=_optional_non_negative_number(
            pricing, "cached_input_per_million_tokens"
        ),
    )


def evaluate_runs(config_path: str | Path, runs_path: str | Path) -> dict[str, Any]:
    config = load_config(config_path)
    raw = json.loads(Path(runs_path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1.0":
        raise ValueError("unsupported agent run schema_version")
    if raw.get("benchmark_version") != config.benchmark_version:
        raise ValueError("run benchmark_version does not match config")
    if raw.get("provider") != config.provider or raw.get("model") != config.model:
        raise ValueError("run provider/model does not match frozen config")
    if raw.get("temperature") != config.temperature:
        raise ValueError("run temperature does not match frozen config")
    if raw.get("run_mode") != "formal" or raw.get("claim_eligible") is not True:
        raise ValueError("smoke runs are not eligible for formal agent evaluation")

    records = [_parse_run(item) for item in raw.get("runs", [])]
    expected_keys = {
        (scenario, arm, trial)
        for scenario in config.scenario_ids
        for arm in config.arm_ids
        for trial in range(1, config.repetitions + 1)
    }
    actual_keys = {(run.scenario_id, run.arm_id, run.trial) for run in records}
    if len(actual_keys) != len(records):
        raise ValueError("agent experiment contains duplicate run keys")
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        raise ValueError(f"agent experiment coverage mismatch: missing={missing} extra={extra}")

    budget_violations = []
    for run in records:
        key = f"{run.scenario_id}/{run.arm_id}/{run.trial}"
        if run.model_requests > config.max_model_requests:
            budget_violations.append(f"{key}:model_requests")
        if run.tool_steps > config.max_tool_steps:
            budget_violations.append(f"{key}:tool_steps")
        if run.elapsed_ms > config.timeout_ms:
            budget_violations.append(f"{key}:timeout")

    usage_state = _aggregate_usage(records)
    arms = {
        arm: _summarize_arm(
            [record for record in records if record.arm_id == arm], config, usage_state
        )
        for arm in config.arm_ids
    }
    comparison = _compare_arms(records, arms, usage_state, config.repetitions)
    passed = (
        not budget_violations
        and usage_state["valid"]
        and usage_state["usage_complete"]
    )
    return {
        "schema_version": "1.0",
        "benchmark_version": config.benchmark_version,
        "dataset_kind": "paired_equal_budget_agent_ablation",
        "provider": config.provider,
        "model": config.model,
        "temperature": config.temperature,
        "price_date": config.price_date,
        "scenario_count": len(config.scenario_ids),
        "repetitions": config.repetitions,
        "run_count": len(records),
        "budgets": {
            "max_model_requests": config.max_model_requests,
            "max_tool_steps": config.max_tool_steps,
            "timeout_ms": config.timeout_ms,
        },
        "budget_comparable": not budget_violations,
        "budget_violations": budget_violations,
        "provider_usage_complete": usage_state["usage_complete"],
        "provider_cache_status": usage_state["cache_status"],
        "provider_cache_hit_rate": usage_state["cache_hit_rate"],
        "provider_retry_count": usage_state["retry_count"],
        "provider_retry_rate": (
            usage_state["retry_count"]
            / sum(record.model_requests for record in records)
        ),
        "provider_latency_ms": usage_state["provider_latency_ms"],
        "arms": arms,
        "comparison": comparison,
        "passed": passed,
        "limitations": [
            "Cache metrics use provider-returned token fields only; unsupported providers remain null.",
            "A delegated-agent resume claim is allowed only when comparison.claim_supported is true.",
            "Cost uses the frozen price snapshot and excludes network, host, and accelerator costs.",
        ],
    }


def _parse_run(item: Any) -> RunRecord:
    if not isinstance(item, dict):
        raise ValueError("agent run must be an object")
    usage = item.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("agent run usage must be an object or null")
    failure_type = item.get("failure_type")
    if failure_type is not None and not isinstance(failure_type, str):
        raise ValueError("failure_type must be a string or null")
    return RunRecord(
        scenario_id=_required_text(item, "scenario_id"),
        arm_id=_required_text(item, "arm_id"),
        trial=_positive_int(item, "trial"),
        passed=_required_bool(item, "passed"),
        elapsed_ms=_non_negative_int(item, "elapsed_ms"),
        tool_steps=_non_negative_int(item, "tool_steps"),
        model_requests=_positive_int(item, "model_requests"),
        human_interventions=_non_negative_int(item, "human_interventions"),
        failure_type=failure_type,
        usage=usage,
    )


def _aggregate_usage(records: list[RunRecord]) -> dict[str, Any]:
    usage_complete = all(
        run.usage is not None and run.usage.get("usage_complete") is True
        for run in records
    )
    valid = True
    cache_flags = []
    prompt_tokens = completion_tokens = total_tokens = cached_tokens = 0
    retry_count = provider_latency_ms = 0
    for run in records:
        if run.usage is None:
            cache_flags.append(False)
            continue
        retry_count += _optional_usage_int(run.usage, "retry_count")
        provider_latency_ms += _optional_usage_int(run.usage, "provider_latency_ms")
        complete = run.usage.get("usage_complete") is True
        cache_complete = run.usage.get("cache_metrics_complete") is True
        cache_flags.append(cache_complete)
        if not complete:
            continue
        prompt = _usage_int(run.usage, "prompt_tokens")
        completion = _usage_int(run.usage, "completion_tokens")
        total = _usage_int(run.usage, "total_tokens")
        if prompt + completion != total:
            valid = False
        prompt_tokens += prompt
        completion_tokens += completion
        total_tokens += total
        if cache_complete:
            cached = _usage_int(run.usage, "cached_prompt_tokens")
            if cached > prompt:
                valid = False
            cached_tokens += cached

    if cache_flags and all(cache_flags):
        cache_status = "supported"
        cache_hit_rate = cached_tokens / prompt_tokens if prompt_tokens else 0.0
    elif any(cache_flags):
        cache_status = "partial"
        cache_hit_rate = None
        valid = False
    else:
        cache_status = "unsupported"
        cache_hit_rate = None
    return {
        "valid": valid,
        "usage_complete": usage_complete,
        "cache_status": cache_status,
        "cache_hit_rate": cache_hit_rate,
        "prompt_tokens": prompt_tokens if usage_complete else None,
        "completion_tokens": completion_tokens if usage_complete else None,
        "total_tokens": total_tokens if usage_complete else None,
        "cached_prompt_tokens": cached_tokens if cache_status == "supported" else None,
        "retry_count": retry_count,
        "retry_rate": retry_count / sum(run.model_requests for run in records),
        "provider_latency_ms": provider_latency_ms,
    }


def _summarize_arm(
    records: list[RunRecord], config: ExperimentConfig, usage_state: dict[str, Any]
) -> dict[str, Any]:
    passed = sum(run.passed for run in records)
    prompt = completion = total = cached = 0
    retry_count = provider_latency_ms = 0
    for run in records:
        if run.usage is not None:
            retry_count += _optional_usage_int(run.usage, "retry_count")
            provider_latency_ms += _optional_usage_int(
                run.usage, "provider_latency_ms"
            )
    arm_usage_complete = all(
        run.usage is not None and run.usage.get("usage_complete") is True
        for run in records
    )
    arm_cache_complete = all(
        run.usage is not None and run.usage.get("cache_metrics_complete") is True
        for run in records
    )
    if arm_usage_complete:
        for run in records:
            assert run.usage is not None
            prompt += _usage_int(run.usage, "prompt_tokens")
            completion += _usage_int(run.usage, "completion_tokens")
            total += _usage_int(run.usage, "total_tokens")
            if arm_cache_complete:
                cached += _usage_int(run.usage, "cached_prompt_tokens")
    cost = _cost_usd(prompt, completion, cached, config) if arm_usage_complete else None
    return {
        "run_count": len(records),
        "passed": passed,
        "pass_rate": passed / len(records),
        "mean_elapsed_ms": statistics.fmean(run.elapsed_ms for run in records),
        "mean_tool_steps": statistics.fmean(run.tool_steps for run in records),
        "mean_model_requests": statistics.fmean(run.model_requests for run in records),
        "human_interventions": sum(run.human_interventions for run in records),
        "retry_count": retry_count,
        "retry_rate": retry_count / sum(run.model_requests for run in records),
        "provider_latency_ms": provider_latency_ms,
        "failure_types": dict(
            sorted(Counter(run.failure_type for run in records if run.failure_type).items())
        ),
        "usage_complete": arm_usage_complete,
        "prompt_tokens": prompt if arm_usage_complete else None,
        "completion_tokens": completion if arm_usage_complete else None,
        "total_tokens": total if arm_usage_complete else None,
        "cached_prompt_tokens": cached if arm_cache_complete else None,
        "provider_cache_hit_rate": (
            cached / prompt if arm_cache_complete and prompt else None
        ),
        "estimated_provider_cost_usd": cost,
        "cache_status": usage_state["cache_status"],
    }


def _compare_arms(
    records: list[RunRecord],
    arms: dict[str, dict[str, Any]],
    usage_state: dict[str, Any],
    repetitions: int,
) -> dict[str, Any]:
    single = arms["single"]
    delegated = arms["delegated"]
    pass_rate_delta = delegated["pass_rate"] - single["pass_rate"]
    elapsed_delta = delegated["mean_elapsed_ms"] - single["mean_elapsed_ms"]
    token_delta = None
    if usage_state["usage_complete"]:
        token_delta = delegated["total_tokens"] - single["total_tokens"]

    paired = {}
    for run in records:
        paired[(run.scenario_id, run.trial, run.arm_id)] = run
    delegated_wins = single_wins = ties = 0
    for scenario, trial, arm in list(paired):
        if arm != "single":
            continue
        left = paired[(scenario, trial, "single")]
        right = paired[(scenario, trial, "delegated")]
        if right.passed and not left.passed:
            delegated_wins += 1
        elif left.passed and not right.passed:
            single_wins += 1
        else:
            ties += 1

    success_benefit = pass_rate_delta > 0 and delegated_wins > single_wins
    efficiency_benefit = False
    if pass_rate_delta == 0 and single["pass_rate"] == 1.0:
        token_benefit = (
            token_delta is not None
            and single["total_tokens"] > 0
            and delegated["total_tokens"] <= single["total_tokens"] * 0.95
        )
        latency_benefit = delegated["mean_elapsed_ms"] <= single["mean_elapsed_ms"] * 0.95
        efficiency_benefit = token_benefit or latency_benefit
    claim_supported = repetitions >= 3 and (success_benefit or efficiency_benefit)
    return {
        "delegated_pass_rate_delta": pass_rate_delta,
        "delegated_mean_elapsed_ms_delta": elapsed_delta,
        "delegated_total_tokens_delta": token_delta,
        "paired_delegated_wins": delegated_wins,
        "paired_single_wins": single_wins,
        "paired_ties": ties,
        "success_benefit": success_benefit,
        "efficiency_benefit": efficiency_benefit,
        "claim_supported": claim_supported,
    }


def _cost_usd(
    prompt_tokens: int, completion_tokens: int, cached_tokens: int, config: ExperimentConfig
) -> float | None:
    if config.input_price_per_million is None or config.output_price_per_million is None:
        return None
    uncached = max(0, prompt_tokens - cached_tokens)
    cached_price = (
        config.cached_input_price_per_million
        if config.cached_input_price_per_million is not None
        else config.input_price_per_million
    )
    return (
        uncached * config.input_price_per_million
        + cached_tokens * cached_price
        + completion_tokens * config.output_price_per_million
    ) / 1_000_000


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return item.strip()


def _required_bool(value: dict[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} must be a boolean")
    return item


def _positive_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return item


def _non_negative_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return item


def _non_negative_number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if (
        not isinstance(item, (int, float))
        or isinstance(item, bool)
        or not math.isfinite(item)
        or item < 0
    ):
        raise ValueError(f"{key} must be a non-negative number")
    return float(item)


def _optional_non_negative_number(value: dict[str, Any], key: str) -> float | None:
    if value.get(key) is None:
        return None
    return _non_negative_number(value, key)


def _usage_int(usage: dict[str, Any], key: str) -> int:
    item = usage.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"usage.{key} must be a non-negative integer")
    return item


def _optional_usage_int(usage: dict[str, Any], key: str) -> int:
    if key not in usage:
        return 0
    return _usage_int(usage, key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = evaluate_runs(args.config, args.runs)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
