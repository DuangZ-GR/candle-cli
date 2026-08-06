use crate::context::budget::estimate_tokens_json;
use crate::context::compact::compact_session;
use crate::context::state::TaskFactKind;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use serde::Serialize;
use std::collections::HashSet;
use std::io::{Error, Result, Write};

#[derive(Debug, Serialize)]
pub struct ContextCaseResult {
    id: String,
    category: &'static str,
    original_user_turns: usize,
    max_turns: usize,
    kept_user_turns: usize,
    messages_before: usize,
    messages_after: usize,
    estimated_tokens_before: usize,
    estimated_tokens_after: usize,
    estimated_tokens_saved: usize,
    estimated_token_reduction_rate: f64,
    required_fact_count: usize,
    retained_fact_count: usize,
    fact_retention_rate: f64,
    task_answerable: bool,
    source_evidence_valid: bool,
    system_messages_preserved: bool,
    tool_pairs_preserved: bool,
    passed: bool,
}

#[derive(Debug, Serialize)]
pub struct ContextBenchmarkReport {
    schema_version: &'static str,
    benchmark_version: &'static str,
    dataset_kind: &'static str,
    estimator: &'static str,
    case_count: usize,
    required_fact_count: usize,
    retained_fact_count: usize,
    fact_retention_rate: f64,
    task_pass_count: usize,
    task_pass_rate: f64,
    source_evidence_verification_rate: f64,
    estimated_tokens_before: usize,
    estimated_tokens_after: usize,
    estimated_tokens_saved: usize,
    estimated_token_reduction_rate: f64,
    integrity_passed: bool,
    provider_cache_metrics_available: bool,
    provider_cache_hit_rate: Option<f64>,
    passed: bool,
    cases: Vec<ContextCaseResult>,
    limitations: Vec<&'static str>,
}

#[derive(Clone)]
struct ExpectedFact {
    kind: TaskFactKind,
    value: String,
}

struct FrozenCase {
    id: String,
    category: &'static str,
    session: Session,
    expected: Vec<ExpectedFact>,
    max_turns: usize,
}

pub fn run_context_harness() -> Result<()> {
    let report = benchmark_context_compaction().map_err(Error::other)?;
    let encoded = serde_json::to_vec_pretty(&report).map_err(Error::other)?;
    std::io::stdout().write_all(&encoded)?;
    std::io::stdout().write_all(b"\n")
}

pub fn benchmark_context_compaction() -> std::result::Result<ContextBenchmarkReport, String> {
    let cases = frozen_cases()
        .into_iter()
        .map(evaluate_case)
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let before: usize = cases.iter().map(|case| case.estimated_tokens_before).sum();
    let after: usize = cases.iter().map(|case| case.estimated_tokens_after).sum();
    let saved = before.saturating_sub(after);
    let required_fact_count = cases.iter().map(|case| case.required_fact_count).sum();
    let retained_fact_count = cases.iter().map(|case| case.retained_fact_count).sum();
    let task_pass_count = cases.iter().filter(|case| case.task_answerable).count();
    let evidence_pass_count = cases
        .iter()
        .filter(|case| case.source_evidence_valid)
        .count();
    let integrity_passed = cases.iter().all(|case| {
        case.system_messages_preserved
            && case.tool_pairs_preserved
            && case.source_evidence_valid
            && case.passed
    });
    let passed = cases.len() >= 20
        && retained_fact_count == required_fact_count
        && task_pass_count == cases.len()
        && integrity_passed;

    Ok(ContextBenchmarkReport {
        schema_version: "1.0",
        benchmark_version: "context-fact-retention-v2",
        dataset_kind: "frozen_deterministic_migration_conversations",
        estimator: "heuristic_cjk_1_token_latin_4_chars",
        case_count: cases.len(),
        required_fact_count,
        retained_fact_count,
        fact_retention_rate: rate(retained_fact_count, required_fact_count),
        task_pass_count,
        task_pass_rate: rate(task_pass_count, cases.len()),
        source_evidence_verification_rate: rate(evidence_pass_count, cases.len()),
        estimated_tokens_before: before,
        estimated_tokens_after: after,
        estimated_tokens_saved: saved,
        estimated_token_reduction_rate: rate(saved, before),
        integrity_passed,
        provider_cache_metrics_available: false,
        provider_cache_hit_rate: None,
        passed,
        cases,
        limitations: vec![
            "Token counts are deterministic estimates, not provider billing tokens.",
            "Fact retention and task answerability are evaluated separately even when both reach the same rate.",
            "Source digests detect accidental summary corruption; they are FNV-1a checksums, not security signatures.",
            "Provider cache hit rate is unavailable in this offline suite and is intentionally reported as null.",
        ],
    })
}

fn evaluate_case(mut case: FrozenCase) -> std::result::Result<ContextCaseResult, String> {
    let original_user_turns = user_turns(&case.session);
    let messages_before = case.session.messages.len();
    let system_before = system_messages(&case.session);
    let before_json = serde_json::to_string(&case.session.messages).map_err(|e| e.to_string())?;
    let estimated_tokens_before = estimate_tokens_json(&before_json);

    compact_session(&mut case.session, case.max_turns);

    let messages_after = case.session.messages.len();
    let kept_user_turns = user_turns(&case.session);
    let outbound_after = serde_json::json!({
        "structured_task_state": case.session.task_state.to_prompt_string(),
        "messages": case.session.messages,
    });
    let estimated_tokens_after = estimate_tokens_json(&outbound_after.to_string());
    let estimated_tokens_saved = estimated_tokens_before.saturating_sub(estimated_tokens_after);
    let retained_fact_count = case
        .expected
        .iter()
        .filter(|expected| {
            case.session
                .task_state
                .facts_of_kind(expected.kind)
                .any(|actual| actual.value == expected.value)
        })
        .count();
    let required_fact_count = case.expected.len();
    let task_answerable = required_fact_count > 0 && retained_fact_count == required_fact_count;
    let source_evidence_valid = case.session.task_state.evidence_valid();
    let system_messages_preserved = system_messages(&case.session) == system_before;
    let tool_pairs_preserved = complete_tool_pairs(&case.session);
    let kept_turns_correct = kept_user_turns == original_user_turns.min(case.max_turns);
    let passed = task_answerable
        && source_evidence_valid
        && system_messages_preserved
        && tool_pairs_preserved
        && kept_turns_correct
        && estimated_tokens_after < estimated_tokens_before;

    Ok(ContextCaseResult {
        id: case.id,
        category: case.category,
        original_user_turns,
        max_turns: case.max_turns,
        kept_user_turns,
        messages_before,
        messages_after,
        estimated_tokens_before,
        estimated_tokens_after,
        estimated_tokens_saved,
        estimated_token_reduction_rate: rate(estimated_tokens_saved, estimated_tokens_before),
        required_fact_count,
        retained_fact_count,
        fact_retention_rate: rate(retained_fact_count, required_fact_count),
        task_answerable,
        source_evidence_valid,
        system_messages_preserved,
        tool_pairs_preserved,
        passed,
    })
}

fn frozen_cases() -> Vec<FrozenCase> {
    let mut cases = Vec::new();
    let files = [
        "src/model.py",
        "configs/train.yaml",
        "tests/test_dtype.py",
        "artifacts/source_trace.jsonl",
    ];
    let commands = [
        "python -m pytest tests/test_dtype.py",
        "cargo test --test test_migration_schema",
        "python migrate.py --mode graph",
        "python -m pytest -q",
    ];
    let errors = [
        "TypeError: bool tensor received at model.py:41",
        "RuntimeError: missing operator grid_sample at decoder.py:88",
        "ValueError: shape [2,4] differs from [2,1,4] at loss.py:19",
        "Error: checkpoint optimizer state key exp_avg_sq is absent",
    ];
    let pending = [
        "compare torch.where dtype promotion",
        "verify checkpoint optimizer state",
        "run GRAPH_MODE regression",
        "inspect missing operator fallback",
    ];
    let decisions = [
        "use PYNATIVE_MODE for diagnostic replay",
        "keep the AdamW mismatch visible",
        "use float32 tolerance 1e-5",
        "preserve the rollback manifest",
    ];

    for (index, value) in files.iter().enumerate() {
        cases.push(file_case(index + 1, value));
    }
    for (index, value) in commands.iter().enumerate() {
        cases.push(command_case(index + 1, value));
    }
    for (index, value) in errors.iter().enumerate() {
        cases.push(error_case(index + 1, value));
    }
    for (index, value) in pending.iter().enumerate() {
        cases.push(marked_case(
            index + 1,
            "pending",
            "TODO",
            TaskFactKind::Pending,
            value,
            MessageRole::User,
        ));
    }
    for (index, value) in decisions.iter().enumerate() {
        cases.push(marked_case(
            index + 1,
            "decision",
            "DECISION",
            TaskFactKind::Decision,
            value,
            MessageRole::Assistant,
        ));
    }
    cases
}

fn file_case(index: usize, value: &str) -> FrozenCase {
    let mut session = historical_session(&format!("file-{index:02}"));
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::ToolCall {
            id: format!("read-{index}"),
            name: "read".into(),
            input: serde_json::json!({"file_path": value}).to_string(),
        }],
    });
    session.messages.push(Message {
        role: MessageRole::Tool,
        blocks: vec![ContentBlock::ToolResult {
            tool_call_id: format!("read-{index}"),
            output: format!("inspected {value}; dtype and shape evidence collected"),
            is_error: false,
        }],
    });
    finish_historical_session(&mut session);
    frozen_case(
        format!("file-{index:02}"),
        "file",
        session,
        TaskFactKind::File,
        value,
    )
}

fn command_case(index: usize, value: &str) -> FrozenCase {
    let mut session = historical_session(&format!("command-{index:02}"));
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::ToolCall {
            id: format!("shell-{index}"),
            name: "shell".into(),
            input: serde_json::json!({"command": value}).to_string(),
        }],
    });
    session.messages.push(Message {
        role: MessageRole::Tool,
        blocks: vec![ContentBlock::ToolResult {
            tool_call_id: format!("shell-{index}"),
            output: "status: ok\nexit_code: 0\nall checks passed".into(),
            is_error: false,
        }],
    });
    finish_historical_session(&mut session);
    frozen_case(
        format!("command-{index:02}"),
        "command",
        session,
        TaskFactKind::Command,
        value,
    )
}

fn error_case(index: usize, value: &str) -> FrozenCase {
    let mut session = historical_session(&format!("error-{index:02}"));
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::ToolCall {
            id: format!("run-{index}"),
            name: "shell".into(),
            input: serde_json::json!({"command": "python migration_case.py"}).to_string(),
        }],
    });
    session.messages.push(Message {
        role: MessageRole::Tool,
        blocks: vec![ContentBlock::ToolResult {
            tool_call_id: format!("run-{index}"),
            output: value.into(),
            is_error: true,
        }],
    });
    finish_historical_session(&mut session);
    frozen_case(
        format!("error-{index:02}"),
        "error",
        session,
        TaskFactKind::Error,
        value,
    )
}

fn marked_case(
    index: usize,
    category: &'static str,
    marker: &str,
    kind: TaskFactKind,
    value: &str,
    role: MessageRole,
) -> FrozenCase {
    let id = format!("{category}-{index:02}");
    let mut session = historical_session(&id);
    session
        .messages
        .push(text_message(role, &format!("{marker}: {value}")));
    finish_historical_session(&mut session);
    frozen_case(id, category, session, kind, value)
}

fn historical_session(id: &str) -> Session {
    let mut session = Session::new("benchmark-workspace".into());
    session.messages.push(text_message(
        MessageRole::System,
        "You are a deterministic PyTorch to MindSpore migration assistant.",
    ));
    session.messages.push(text_message(
        MessageRole::User,
        &format!("Investigate migration case {id} and retain exact evidence."),
    ));
    session.messages.push(text_message(
        MessageRole::Assistant,
        &historical_padding(id),
    ));
    session
}

fn finish_historical_session(session: &mut Session) {
    session.messages.push(text_message(
        MessageRole::Assistant,
        &historical_padding("analysis-complete"),
    ));
    session.messages.push(text_message(
        MessageRole::User,
        "Continue from the preserved task state and report the requested historical fact.",
    ));
    session.messages.push(text_message(
        MessageRole::Assistant,
        "I will use the compact structured state and verify evidence before acting.",
    ));
}

fn historical_padding(id: &str) -> String {
    (0..10)
        .map(|index| {
            format!(
                "Historical analysis {id}/{index}: compare source semantics, target defaults, dtype propagation, shape contracts, execution mode, and reproducibility evidence without assuming equivalence."
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn frozen_case(
    id: String,
    category: &'static str,
    session: Session,
    kind: TaskFactKind,
    value: &str,
) -> FrozenCase {
    FrozenCase {
        id,
        category,
        session,
        expected: vec![ExpectedFact {
            kind,
            value: value.to_string(),
        }],
        max_turns: 1,
    }
}

fn text_message(role: MessageRole, text: &str) -> Message {
    Message {
        role,
        blocks: vec![ContentBlock::Text { text: text.into() }],
    }
}

fn user_turns(session: &Session) -> usize {
    session
        .messages
        .iter()
        .filter(|message| message.role == MessageRole::User)
        .count()
}

fn system_messages(session: &Session) -> usize {
    session
        .messages
        .iter()
        .filter(|message| message.role == MessageRole::System)
        .count()
}

fn complete_tool_pairs(session: &Session) -> bool {
    let calls: HashSet<_> = session
        .messages
        .iter()
        .flat_map(|message| &message.blocks)
        .filter_map(|block| match block {
            ContentBlock::ToolCall { id, .. } => Some(id.as_str()),
            _ => None,
        })
        .collect();
    session
        .messages
        .iter()
        .flat_map(|message| &message.blocks)
        .filter_map(|block| match block {
            ContentBlock::ToolResult { tool_call_id, .. } => Some(tool_call_id.as_str()),
            _ => None,
        })
        .all(|tool_call_id| calls.contains(tool_call_id))
}

fn rate(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn context_benchmark_preserves_facts_and_keeps_metrics_separate() {
        let report = benchmark_context_compaction().unwrap();

        assert_eq!(report.case_count, 20);
        assert_eq!(report.fact_retention_rate, 1.0);
        assert_eq!(report.task_pass_rate, 1.0);
        assert_eq!(report.source_evidence_verification_rate, 1.0);
        assert!(report.estimated_tokens_saved > 0);
        assert!(report.estimated_token_reduction_rate > 0.5);
        assert!(report.integrity_passed);
        assert!(!report.provider_cache_metrics_available);
        assert_eq!(report.provider_cache_hit_rate, None);
        assert!(report.passed);
        let checked_in: serde_json::Value = serde_json::from_str(include_str!(
            "../../benchmarks/results/context_fact_retention_v2.json"
        ))
        .unwrap();
        assert_eq!(serde_json::to_value(&report).unwrap(), checked_in);
    }
}
