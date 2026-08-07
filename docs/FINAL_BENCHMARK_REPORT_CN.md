# candle-cli 最终 Benchmark 证据索引

- 版本：`release-evidence-v1`
- 冻结日期：`2026-08-06`
- 可用于限定范围声明的证据：12
- 仅记录、不可用于收益声明的证据：1

| 证据 | 可声明 | 指标 | 来源 |
|---|---:|---|---|
| `real-project-development` | 是 | files=25; source_lines=4436; mapped_finding_coverage=0.447706; syntax_valid_rate=1.0 | `benchmarks/results/real_projects_v1_after.json` |
| `real-project-heldout` | 是 | files=17; source_lines=3052; mapped_finding_coverage=0.419811; syntax_valid_rate=1.0 | `benchmarks/results/real_projects_heldout_v1.json` |
| `runtime-parity` | 是 | case_count=5; runtime_parity_rate=1.0; classification_accuracy=1.0 | `benchmarks/results/runtime_parity_v2.json` |
| `component-parity` | 是 | case_count=7; component_parity_rate=1.0; first_divergence_top1_accuracy=1.0 | `benchmarks/results/runtime_components_v1.json` |
| `training-parity` | 是 | case_count=3; training_step_parity_rate=1.0; optimizer_defect_top1_accuracy=1.0 | `benchmarks/results/runtime_training_v1.json` |
| `workflow-e2e` | 是 | case_count=4; workflow_pass_rate=1.0; fault_rollback_rate=1.0 | `benchmarks/results/workflow_e2e_v1.json` |
| `real-model-dual-runtime` | 是 | case_count=3; pass_rate=1.0; rollback_success_rate=1.0 | `benchmarks/results/real_model_dual_runtime_v1.json` |
| `data-pipeline-randomness` | 是 | case_count=18; classification_accuracy=1.0; first_divergence_top1_accuracy=1.0 | `benchmarks/results/data_pipeline_randomness_v1.json` |
| `advanced-training` | 是 | case_count=13; classification_accuracy=1.0; diagnostic_top1_accuracy=1.0; checkpoint_restore_rate=1.0 | `benchmarks/results/advanced_training_v1.json` |
| `security-development` | 是 | attack_case_count=12; attack_interception_rate=1.0; benign_false_positive_rate=0.0 | `benchmarks/results/security_regression_v1.json` |
| `security-heldout` | 是 | attack_case_count=15; attack_evaluated_count=12; attack_not_applicable_count=3; attack_interception_rate=1.0; benign_false_positive_rate=0.0 | `benchmarks/results/security_heldout_v1.json` |
| `context-fact-retention` | 是 | case_count=20; fact_retention_rate=1.0; task_pass_rate=1.0; estimated_token_reduction_rate=0.8176358766093493; provider_cache_hit_rate=null | `benchmarks/results/context_fact_retention_v2.json` |
| `agent-ollama-smoke` | 否 | run_mode="smoke"; model="qwen2:0.5b"; claim_eligible=false | `benchmarks/results/agent_ablation_ollama_smoke_v1.json` |

## 限制

- Metrics retain the scope and limitations of their source benchmark; aggregation does not create a broader generalization claim.
- Provider cache remains null when the Provider does not report cache fields.
- The Ollama smoke result is included as rejected capability evidence and is not claim eligible.
- Security rates exclude cases explicitly reported as not_applicable and disclose that count.
- A release tag and commit must be recorded only after user-approved publication.
