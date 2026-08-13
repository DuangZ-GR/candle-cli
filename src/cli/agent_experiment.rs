use crate::agent::r#loop::run_single_turn_with_budget;
use crate::agent::state::AgentRunBudget;
use crate::agent::tool_call::{parse_tool_call, ToolCallParseError};
use crate::model::configured::ConfiguredRuntime;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{TokenUsage, TurnRequest, TurnResult};
use crate::permissions::mode::PermissionMode;
use crate::permissions::policy::PermissionPolicy;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{self, Error};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

#[derive(Debug, Deserialize)]
struct ExperimentManifest {
    schema_version: String,
    benchmark_version: String,
    experiment_status: String,
    provider: ProviderConfig,
    pricing: PricingConfig,
    repetitions: usize,
    budgets: BudgetConfig,
    arms: Vec<ArmConfig>,
    scenarios: Vec<ScenarioConfig>,
}

#[derive(Debug, Deserialize)]
struct ProviderConfig {
    name: String,
    model: String,
    temperature: f64,
}

#[derive(Debug, Deserialize)]
struct PricingConfig {
    price_date: String,
    input_per_million_tokens: Option<f64>,
    output_per_million_tokens: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct BudgetConfig {
    max_model_requests: usize,
    max_tool_steps: usize,
    timeout_ms: u64,
}

#[derive(Debug, Deserialize)]
struct ArmConfig {
    id: String,
    task_tool_enabled: bool,
    #[serde(default)]
    baseline_loop: bool,
}

#[derive(Debug, Deserialize)]
struct ScenarioConfig {
    id: String,
    goal: String,
    evidence_paths: Vec<PathBuf>,
    required_evidence: Vec<String>,
}

#[derive(Debug, Serialize)]
struct RawExperimentReport {
    schema_version: &'static str,
    benchmark_version: String,
    provider: String,
    model: String,
    temperature: f64,
    run_mode: &'static str,
    claim_eligible: bool,
    execution_order: &'static str,
    runs: Vec<RawRunRecord>,
}

#[derive(Debug, Serialize)]
struct RawRunRecord {
    scenario_id: String,
    arm_id: String,
    trial: usize,
    passed: bool,
    elapsed_ms: u64,
    tool_steps: usize,
    model_requests: usize,
    subagent_invocations: usize,
    human_interventions: usize,
    failure_type: Option<String>,
    missing_evidence: Vec<String>,
    final_answer_digest: String,
    usage: serde_json::Value,
}

pub fn run_agent_experiment(
    config_path: PathBuf,
    output_path: PathBuf,
    smoke: bool,
) -> io::Result<()> {
    let manifest = load_manifest(&config_path).map_err(Error::other)?;
    validate_environment(&manifest).map_err(Error::other)?;
    let workspace = std::env::current_dir()?;
    validate_evidence_anchors(&manifest, &workspace).map_err(Error::other)?;
    let tools = ToolRegistry::read_only(&workspace);
    let mut runtime = ConfiguredRuntime::from_environment();
    let mut runs = Vec::new();

    let (scenario_limit, repetitions) = execution_limits(&manifest, smoke);
    for (scenario_index, scenario) in manifest.scenarios.iter().take(scenario_limit).enumerate() {
        for trial in 1..=repetitions {
            for arm_id in balanced_arm_order(scenario_index, trial) {
                let arm = manifest
                    .arms
                    .iter()
                    .find(|arm| arm.id == arm_id)
                    .expect("validated arm");
                runs.push(execute_run(
                    &manifest,
                    scenario,
                    arm,
                    trial,
                    &workspace,
                    &tools,
                    &mut runtime,
                ));
            }
        }
    }

    let report = RawExperimentReport {
        schema_version: "1.0",
        benchmark_version: manifest.benchmark_version,
        provider: manifest.provider.name,
        model: manifest.provider.model,
        temperature: manifest.provider.temperature,
        run_mode: if smoke { "smoke" } else { "formal" },
        claim_eligible: !smoke,
        execution_order: "paired_alternating_by_scenario_and_trial",
        runs,
    };
    if let Some(parent) = output_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let encoded = serde_json::to_vec_pretty(&report).map_err(Error::other)?;
    fs::write(output_path, encoded)
}

fn execution_limits(manifest: &ExperimentManifest, smoke: bool) -> (usize, usize) {
    if smoke {
        (1, 1)
    } else {
        (manifest.scenarios.len(), manifest.repetitions)
    }
}

fn load_manifest(path: &Path) -> Result<ExperimentManifest, String> {
    let payload = fs::read(path).map_err(|error| error.to_string())?;
    let manifest: ExperimentManifest =
        serde_json::from_slice(&payload).map_err(|error| error.to_string())?;
    if manifest.schema_version != "1.0" {
        return Err("unsupported agent experiment schema_version".into());
    }
    if manifest.experiment_status != "ready" {
        return Err(format!(
            "agent experiment is not ready: status={} (select a real provider/model and price snapshot first)",
            manifest.experiment_status
        ));
    }
    if manifest.provider.name.trim().is_empty()
        || manifest.provider.model.trim().is_empty()
        || manifest.provider.name.starts_with("TO_BE_")
        || manifest.provider.model.starts_with("TO_BE_")
        || !manifest.provider.temperature.is_finite()
        || manifest.provider.temperature < 0.0
    {
        return Err("agent experiment provider/model is not frozen".into());
    }
    if manifest.pricing.price_date.trim().is_empty()
        || manifest.pricing.price_date.starts_with("TO_BE_")
        || manifest.pricing.input_per_million_tokens.is_none()
        || manifest.pricing.output_per_million_tokens.is_none()
        || manifest
            .pricing
            .input_per_million_tokens
            .is_some_and(|value| !value.is_finite() || value < 0.0)
        || manifest
            .pricing
            .output_per_million_tokens
            .is_some_and(|value| !value.is_finite() || value < 0.0)
    {
        return Err("agent experiment price snapshot is not frozen".into());
    }
    if manifest.repetitions < 3 {
        return Err("agent experiment requires at least three repetitions".into());
    }
    if manifest.budgets.max_model_requests == 0
        || manifest.budgets.max_tool_steps == 0
        || manifest.budgets.timeout_ms == 0
    {
        return Err("agent experiment budgets must be positive".into());
    }
    if manifest.scenarios.len() < 10
        || manifest.scenarios.iter().any(|scenario| {
            scenario.id.trim().is_empty()
                || scenario.goal.trim().is_empty()
                || scenario.evidence_paths.is_empty()
                || scenario.required_evidence.is_empty()
        })
    {
        return Err("agent experiment requires ten complete scenarios".into());
    }
    let arm_ids: std::collections::HashSet<_> =
        manifest.arms.iter().map(|arm| arm.id.as_str()).collect();
    if arm_ids != std::collections::HashSet::from(["baseline_loop", "single", "delegated"])
        || manifest.arms.iter().any(|arm| {
            arm.task_tool_enabled != (arm.id == "delegated")
                || arm.baseline_loop != (arm.id == "baseline_loop")
        })
    {
        return Err(
            "agent experiment arms must be baseline_loop(minimal PI), single(no task), and delegated(task)"
                .into(),
        );
    }
    Ok(manifest)
}

fn validate_evidence_anchors(
    manifest: &ExperimentManifest,
    workspace: &Path,
) -> Result<(), String> {
    let canonical_workspace = workspace
        .canonicalize()
        .map_err(|error| format!("failed to resolve experiment workspace: {error}"))?;
    for scenario in &manifest.scenarios {
        let mut evidence_corpus = String::new();
        for relative in &scenario.evidence_paths {
            if relative.is_absolute()
                || relative
                    .components()
                    .any(|component| component == std::path::Component::ParentDir)
            {
                return Err(format!(
                    "scenario {} evidence path escapes workspace: {}",
                    scenario.id,
                    relative.display()
                ));
            }
            let path = canonical_workspace
                .join(relative)
                .canonicalize()
                .map_err(|error| {
                    format!(
                        "scenario {} evidence file {} is unavailable: {error}",
                        scenario.id,
                        relative.display()
                    )
                })?;
            if !path.starts_with(&canonical_workspace) {
                return Err(format!(
                    "scenario {} evidence path escapes workspace through a link: {}",
                    scenario.id,
                    relative.display()
                ));
            }
            let content = fs::read_to_string(&path).map_err(|error| {
                format!(
                    "scenario {} evidence file {} is unavailable: {error}",
                    scenario.id,
                    relative.display()
                )
            })?;
            evidence_corpus.push_str(&content);
            evidence_corpus.push('\n');
        }
        let lower = evidence_corpus.to_ascii_lowercase();
        for required in &scenario.required_evidence {
            if !lower.contains(&required.to_ascii_lowercase()) {
                return Err(format!(
                    "scenario {} required evidence is absent from frozen files: {}",
                    scenario.id, required
                ));
            }
        }
    }
    Ok(())
}

fn validate_environment(manifest: &ExperimentManifest) -> Result<(), String> {
    if std::env::var("CANDLE_CLI_RUNTIME").ok().as_deref() != Some("bridge") {
        return Err("CANDLE_CLI_RUNTIME must be bridge for a real experiment".into());
    }
    if std::env::var("CANDLE_CLI_EXPERIMENT_PROVIDER")
        .ok()
        .as_deref()
        != Some(manifest.provider.name.as_str())
    {
        return Err("CANDLE_CLI_EXPERIMENT_PROVIDER does not match the frozen config".into());
    }
    if std::env::var("CANDLE_CLI_MODEL_ID").ok().as_deref()
        != Some(manifest.provider.model.as_str())
    {
        return Err("CANDLE_CLI_MODEL_ID does not match the frozen config".into());
    }
    let temperature = std::env::var("CANDLE_CLI_TEMPERATURE")
        .map_err(|_| "CANDLE_CLI_TEMPERATURE must be set".to_string())?
        .parse::<f64>()
        .map_err(|_| "CANDLE_CLI_TEMPERATURE is invalid".to_string())?;
    if (temperature - manifest.provider.temperature).abs() > f64::EPSILON {
        return Err("CANDLE_CLI_TEMPERATURE does not match the frozen config".into());
    }
    if std::env::var("CANDLE_CLI_INCLUDE_USAGE")
        .ok()
        .is_some_and(|value| matches!(value.as_str(), "0" | "false" | "no"))
    {
        return Err("CANDLE_CLI_INCLUDE_USAGE must remain enabled".into());
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn execute_run(
    manifest: &ExperimentManifest,
    scenario: &ScenarioConfig,
    arm: &ArmConfig,
    trial: usize,
    workspace: &Path,
    tools: &ToolRegistry,
    runtime: &mut ConfiguredRuntime,
) -> RawRunRecord {
    if arm.baseline_loop {
        return execute_baseline_loop_run(
            manifest, scenario, arm, trial, workspace, tools, runtime,
        );
    }

    let policy = PermissionPolicy::new(if arm.task_tool_enabled {
        PermissionMode::ReadOnlyWithTask
    } else {
        PermissionMode::ReadOnly
    });
    let instruction = if arm.task_tool_enabled {
        "Use the task tool at least once to delegate a focused read-only inspection. Then verify and synthesize the evidence yourself."
    } else {
        "Work as a single agent. Do not use the task tool. Inspect and synthesize the evidence yourself."
    };
    let mut session = Session::new(workspace.display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: format!(
                "{instruction}\n\nTask: {}\n\nReturn a concise answer containing exact code identifiers as evidence.",
                scenario.goal
            ),
        }],
    });
    let mut budget = AgentRunBudget::with_timeout(
        manifest.budgets.max_model_requests,
        manifest.budgets.max_tool_steps,
        Duration::from_millis(manifest.budgets.timeout_ms),
    );
    let started = Instant::now();
    let result = run_single_turn_with_budget(
        &mut session,
        runtime,
        tools,
        &policy,
        manifest.budgets.max_model_requests,
        &mut budget,
    );
    let elapsed_ms = started.elapsed().as_millis() as u64;

    match result {
        Ok(result) => {
            let missing_evidence =
                missing_evidence(&result.final_text, &scenario.required_evidence);
            let budget_exhausted = result.final_text.contains("reaching shared");
            let timed_out = budget.timed_out() || elapsed_ms > manifest.budgets.timeout_ms;
            let passed = missing_evidence.is_empty() && !budget_exhausted && !timed_out;
            let failure_type = if timed_out {
                Some("timeout".to_string())
            } else if budget_exhausted {
                Some("budget_exhausted".to_string())
            } else if !missing_evidence.is_empty() {
                Some("missing_evidence".to_string())
            } else {
                None
            };
            RawRunRecord {
                scenario_id: scenario.id.clone(),
                arm_id: arm.id.clone(),
                trial,
                passed,
                elapsed_ms,
                tool_steps: budget.tool_steps_used(),
                model_requests: budget.model_requests_used(),
                subagent_invocations: budget.subagent_invocations(),
                human_interventions: 0,
                failure_type,
                missing_evidence,
                final_answer_digest: digest(&result.final_text),
                usage: result.usage.to_json(),
            }
        }
        Err(error) => {
            let timed_out = budget.timed_out()
                || error.to_ascii_lowercase().contains("timed out")
                || elapsed_ms > manifest.budgets.timeout_ms;
            RawRunRecord {
                scenario_id: scenario.id.clone(),
                arm_id: arm.id.clone(),
                trial,
                passed: false,
                elapsed_ms,
                tool_steps: budget.tool_steps_used(),
                model_requests: budget.model_requests_used(),
                subagent_invocations: budget.subagent_invocations(),
                human_interventions: 0,
                failure_type: Some(
                    if timed_out {
                        "timeout"
                    } else {
                        "runtime_error"
                    }
                    .to_string(),
                ),
                missing_evidence: scenario.required_evidence.clone(),
                final_answer_digest: digest(&error),
                usage: serde_json::Value::Null,
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn execute_baseline_loop_run(
    manifest: &ExperimentManifest,
    scenario: &ScenarioConfig,
    arm: &ArmConfig,
    trial: usize,
    workspace: &Path,
    tools: &ToolRegistry,
    runtime: &mut ConfiguredRuntime,
) -> RawRunRecord {
    let mut session = Session::new(workspace.display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: format!(
                "Task: {}\n\nUse only read/grep/glob/pwd if needed. Return a concise answer containing exact code identifiers as evidence.",
                scenario.goal
            ),
        }],
    });
    let mut budget = AgentRunBudget::with_timeout(
        manifest.budgets.max_model_requests,
        manifest.budgets.max_tool_steps,
        Duration::from_millis(manifest.budgets.timeout_ms),
    );
    let started = Instant::now();
    let result = run_minimal_pi_loop(runtime, tools, &mut session, &mut budget);
    let elapsed_ms = started.elapsed().as_millis() as u64;

    match result {
        Ok(result) => {
            let missing_evidence =
                missing_evidence(&result.final_text, &scenario.required_evidence);
            let budget_exhausted = result.final_text.contains("minimal PI loop stopped after");
            let timed_out = budget.timed_out() || elapsed_ms > manifest.budgets.timeout_ms;
            let passed = missing_evidence.is_empty() && !budget_exhausted && !timed_out;
            let failure_type = if timed_out {
                Some("timeout".to_string())
            } else if budget_exhausted {
                Some("budget_exhausted".to_string())
            } else if !missing_evidence.is_empty() {
                Some("missing_evidence".to_string())
            } else {
                None
            };
            RawRunRecord {
                scenario_id: scenario.id.clone(),
                arm_id: arm.id.clone(),
                trial,
                passed,
                elapsed_ms,
                tool_steps: budget.tool_steps_used(),
                model_requests: budget.model_requests_used(),
                subagent_invocations: 0,
                human_interventions: 0,
                failure_type,
                missing_evidence,
                final_answer_digest: digest(&result.final_text),
                usage: result.usage.to_json(),
            }
        }
        Err(error) => {
            let timed_out = budget.timed_out()
                || error.to_ascii_lowercase().contains("timed out")
                || elapsed_ms > manifest.budgets.timeout_ms;
            RawRunRecord {
                scenario_id: scenario.id.clone(),
                arm_id: arm.id.clone(),
                trial,
                passed: false,
                elapsed_ms,
                tool_steps: budget.tool_steps_used(),
                model_requests: budget.model_requests_used(),
                subagent_invocations: 0,
                human_interventions: 0,
                failure_type: Some(
                    if timed_out {
                        "timeout"
                    } else {
                        "runtime_error"
                    }
                    .to_string(),
                ),
                missing_evidence: scenario.required_evidence.clone(),
                final_answer_digest: digest(&error),
                usage: serde_json::Value::Null,
            }
        }
    }
}

fn run_minimal_pi_loop<R: CandleTargetRuntime>(
    runtime: &mut R,
    tools: &ToolRegistry,
    session: &mut Session,
    budget: &mut AgentRunBudget,
) -> Result<TurnResult, String> {
    let mut usage = TokenUsage::default();
    while !budget.timed_out() {
        if !budget.consume_model_request() {
            let final_text = format!(
                "minimal PI loop stopped after reaching model request budget ({})",
                budget.max_model_requests()
            );
            append_baseline_text(session, final_text.clone());
            return Ok(TurnResult {
                final_text,
                tool_calls: Vec::new(),
                usage,
            });
        }
        let request = TurnRequest {
            system_prompt: baseline_system_prompt(),
            messages_json: serde_json::to_string(&session.messages).map_err(|e| e.to_string())?,
            tools_json: baseline_tools_json().to_string(),
            timeout_ms: budget.remaining_timeout_ms(),
            deadline_unix_ms: budget.deadline_unix_ms(),
        };
        let result = runtime.generate_turn(request)?;
        usage.merge(&result.usage);
        match parse_tool_call(&result.final_text) {
            Ok(Some(tool_call)) => {
                if !budget.consume_tool_step() {
                    let final_text = format!(
                        "minimal PI loop stopped after reaching tool step budget ({})",
                        budget.max_tool_steps()
                    );
                    append_baseline_text(session, final_text.clone());
                    return Ok(TurnResult {
                        final_text,
                        tool_calls: Vec::new(),
                        usage,
                    });
                }
                append_baseline_tool_call(session, &tool_call);
                let (output, is_error) = if tool_call.name == "task" {
                    (
                        "status: error\nmessage: task is disabled in baseline_loop".to_string(),
                        true,
                    )
                } else {
                    match tools.execute(&tool_call.name, &tool_call.input_json) {
                        Ok(output) => (format!("status: ok\noutput:\n{output}"), false),
                        Err(error) => (format!("status: error\nmessage: {error}"), true),
                    }
                };
                append_baseline_tool_result(session, &tool_call.id, output, is_error);
            }
            Ok(None) => {
                append_baseline_text(session, result.final_text.clone());
                return Ok(TurnResult {
                    final_text: result.final_text,
                    tool_calls: Vec::new(),
                    usage,
                });
            }
            Err(error) => {
                append_baseline_text(session, baseline_parse_error_message(&error));
            }
        }
    }
    let final_text = "minimal PI loop stopped after reaching wall-clock timeout".to_string();
    append_baseline_text(session, final_text.clone());
    Ok(TurnResult {
        final_text,
        tool_calls: Vec::new(),
        usage,
    })
}

fn baseline_system_prompt() -> String {
    format!(
        "You are a minimal PI baseline code agent. PI means a simple perceive-act loop: read the task, optionally call one tool, observe the result, and continue until a final answer.\n\
This baseline intentionally excludes candle-cli enhancements such as grep-RAG, project memory, sub-agents, migration-specific workflow orchestration, trace diagnostics, and transactional patch rollback.\n\
Allowed tools are pwd, read, glob, and grep. To call a tool, output exactly one raw <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call> block and no other text.\n\
When you have enough evidence, return the final answer directly.\n\nAvailable tools JSON: {}",
        baseline_tools_json()
    )
}

fn baseline_tools_json() -> &'static str {
    r#"[{"name":"pwd"},{"name":"read"},{"name":"glob"},{"name":"grep"}]"#
}

fn baseline_parse_error_message(error: &ToolCallParseError) -> String {
    format!(
        "Your previous tool call was malformed: {error}. Return exactly one valid <tool_call> block or a final answer."
    )
}

fn append_baseline_tool_call(
    session: &mut Session,
    tool_call: &crate::model::types::ToolCallIntent,
) {
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::ToolCall {
            id: tool_call.id.clone(),
            name: tool_call.name.clone(),
            input: tool_call.input_json.clone(),
        }],
    });
}

fn append_baseline_tool_result(
    session: &mut Session,
    tool_call_id: &str,
    output: String,
    is_error: bool,
) {
    session.messages.push(Message {
        role: MessageRole::Tool,
        blocks: vec![ContentBlock::ToolResult {
            tool_call_id: tool_call_id.to_string(),
            output,
            is_error,
        }],
    });
}

fn append_baseline_text(session: &mut Session, text: String) {
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::Text { text }],
    });
}

fn balanced_arm_order(scenario_index: usize, trial: usize) -> [&'static str; 3] {
    match (scenario_index + trial) % 3 {
        0 => ["baseline_loop", "single", "delegated"],
        1 => ["single", "delegated", "baseline_loop"],
        _ => ["delegated", "baseline_loop", "single"],
    }
}

fn missing_evidence(answer: &str, required: &[String]) -> Vec<String> {
    let lower = answer.to_ascii_lowercase();
    required
        .iter()
        .filter(|evidence| !lower.contains(&evidence.to_ascii_lowercase()))
        .cloned()
        .collect()
}

fn digest(value: &str) -> String {
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in value.bytes() {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("fnv1a64:{hash:016x}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checked_in_template_refuses_to_run_before_provider_is_frozen() {
        let error =
            load_manifest(Path::new("benchmarks/agent/agent_ablation_v1.json")).unwrap_err();
        assert!(error.contains("not ready"));
    }

    #[test]
    fn evidence_scoring_is_case_insensitive_and_exact() {
        let missing = missing_evidence(
            "The category is SHAPE_MISMATCH at first_divergence.",
            &["shape_mismatch".into(), "first_divergence".into()],
        );
        assert!(missing.is_empty());
    }

    #[test]
    fn paired_order_alternates_across_scenarios_and_trials() {
        assert_ne!(balanced_arm_order(0, 1), balanced_arm_order(0, 2));
        assert_ne!(balanced_arm_order(0, 1), balanced_arm_order(1, 1));
        assert!(balanced_arm_order(0, 1).contains(&"baseline_loop"));
        assert!(balanced_arm_order(0, 1).contains(&"single"));
        assert!(balanced_arm_order(0, 1).contains(&"delegated"));
    }

    #[test]
    fn smoke_mode_is_bounded_to_one_scenario_and_one_trial() {
        let manifest = ExperimentManifest {
            schema_version: "1.0".into(),
            benchmark_version: "fixture".into(),
            experiment_status: "ready".into(),
            provider: ProviderConfig {
                name: "fixture".into(),
                model: "fixture".into(),
                temperature: 0.0,
            },
            pricing: PricingConfig {
                price_date: "2026-08-06".into(),
                input_per_million_tokens: Some(0.0),
                output_per_million_tokens: Some(0.0),
            },
            repetitions: 3,
            budgets: BudgetConfig {
                max_model_requests: 8,
                max_tool_steps: 8,
                timeout_ms: 120_000,
            },
            arms: Vec::new(),
            scenarios: vec![
                ScenarioConfig {
                    id: "one".into(),
                    goal: "goal".into(),
                    evidence_paths: vec!["README.md".into()],
                    required_evidence: vec!["candle-cli".into()],
                },
                ScenarioConfig {
                    id: "two".into(),
                    goal: "goal".into(),
                    evidence_paths: vec!["README.md".into()],
                    required_evidence: vec!["candle-cli".into()],
                },
            ],
        };

        assert_eq!(execution_limits(&manifest, true), (1, 1));
        assert_eq!(execution_limits(&manifest, false), (2, 3));
    }

    #[test]
    fn baseline_arm_must_be_marked_as_pi_loop() {
        let manifest = ExperimentManifest {
            schema_version: "1.0".into(),
            benchmark_version: "fixture".into(),
            experiment_status: "ready".into(),
            provider: ProviderConfig {
                name: "fixture".into(),
                model: "fixture".into(),
                temperature: 0.0,
            },
            pricing: PricingConfig {
                price_date: "2026-08-06".into(),
                input_per_million_tokens: Some(0.0),
                output_per_million_tokens: Some(0.0),
            },
            repetitions: 3,
            budgets: BudgetConfig {
                max_model_requests: 8,
                max_tool_steps: 8,
                timeout_ms: 120_000,
            },
            arms: vec![
                ArmConfig {
                    id: "baseline_loop".into(),
                    task_tool_enabled: false,
                    baseline_loop: true,
                },
                ArmConfig {
                    id: "single".into(),
                    task_tool_enabled: false,
                    baseline_loop: false,
                },
                ArmConfig {
                    id: "delegated".into(),
                    task_tool_enabled: true,
                    baseline_loop: false,
                },
            ],
            scenarios: (0..10)
                .map(|index| ScenarioConfig {
                    id: format!("scenario-{index}"),
                    goal: "goal".into(),
                    evidence_paths: vec!["README.md".into()],
                    required_evidence: vec!["candle-cli".into()],
                })
                .collect(),
        };

        let arm_ids: std::collections::HashSet<_> =
            manifest.arms.iter().map(|arm| arm.id.as_str()).collect();
        assert_eq!(
            arm_ids,
            std::collections::HashSet::from(["baseline_loop", "single", "delegated"])
        );
        assert!(manifest.arms[0].baseline_loop);
        assert!(!manifest.arms[1].baseline_loop);
        assert!(manifest.arms[2].task_tool_enabled);
    }
}
