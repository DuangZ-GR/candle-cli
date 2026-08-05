use crate::context::{budget::estimate_tokens_json, compact::compact_session};
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use serde::Serialize;
use std::collections::HashSet;
use std::io::{Error, Result, Write};

#[derive(Debug, Serialize)]
pub struct ContextCaseResult {
    id: &'static str,
    original_user_turns: usize,
    max_turns: usize,
    kept_user_turns: usize,
    messages_before: usize,
    messages_after: usize,
    estimated_tokens_before: usize,
    estimated_tokens_after: usize,
    estimated_tokens_saved: usize,
    estimated_token_reduction_rate: f64,
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

pub fn run_context_harness() -> Result<()> {
    let report = benchmark_context_compaction().map_err(Error::other)?;
    let encoded = serde_json::to_vec_pretty(&report).map_err(Error::other)?;
    std::io::stdout().write_all(&encoded)?;
    std::io::stdout().write_all(b"\n")
}

pub fn benchmark_context_compaction() -> std::result::Result<ContextBenchmarkReport, String> {
    let cases = vec![
        evaluate_case("english-long", english_session(20), 5)?,
        evaluate_case("chinese-long", chinese_session(16), 4)?,
        evaluate_case("tool-heavy", tool_session(12), 3)?,
        evaluate_case("under-limit", english_session(4), 10)?,
    ];
    let before = cases.iter().map(|case| case.estimated_tokens_before).sum();
    let after = cases.iter().map(|case| case.estimated_tokens_after).sum();
    let saved = before - after;
    let integrity_passed = cases
        .iter()
        .all(|case| case.system_messages_preserved && case.tool_pairs_preserved && case.passed);
    Ok(ContextBenchmarkReport {
        schema_version: "1.0",
        benchmark_version: "context-compaction-v1",
        dataset_kind: "deterministic_synthetic_conversations",
        estimator: "heuristic_cjk_1_token_latin_4_chars",
        case_count: cases.len(),
        estimated_tokens_before: before,
        estimated_tokens_after: after,
        estimated_tokens_saved: saved,
        estimated_token_reduction_rate: rate(saved, before),
        integrity_passed,
        provider_cache_metrics_available: false,
        provider_cache_hit_rate: None,
        passed: integrity_passed,
        cases,
        limitations: vec![
            "Token counts are deterministic estimates, not provider billing tokens.",
            "The suite measures turn compaction, not semantic summarization quality.",
            "Provider cache hit rate is unavailable and intentionally reported as null.",
        ],
    })
}

fn evaluate_case(
    id: &'static str,
    mut session: Session,
    max_turns: usize,
) -> std::result::Result<ContextCaseResult, String> {
    let original_user_turns = user_turns(&session);
    let messages_before = session.messages.len();
    let system_before = system_messages(&session);
    let before_json =
        serde_json::to_string(&session.messages).map_err(|error| error.to_string())?;
    let estimated_tokens_before = estimate_tokens_json(&before_json);

    compact_session(&mut session, max_turns);

    let messages_after = session.messages.len();
    let kept_user_turns = user_turns(&session);
    let after_json = serde_json::to_string(&session.messages).map_err(|error| error.to_string())?;
    let estimated_tokens_after = estimate_tokens_json(&after_json);
    let estimated_tokens_saved = estimated_tokens_before.saturating_sub(estimated_tokens_after);
    let system_messages_preserved = system_messages(&session) == system_before;
    let tool_pairs_preserved = complete_tool_pairs(&session);
    let expected_turns = original_user_turns.min(max_turns);
    let reduction_expected = original_user_turns > max_turns;
    let reduction_correct = if reduction_expected {
        estimated_tokens_after < estimated_tokens_before
    } else {
        estimated_tokens_after == estimated_tokens_before
    };
    Ok(ContextCaseResult {
        id,
        original_user_turns,
        max_turns,
        kept_user_turns,
        messages_before,
        messages_after,
        estimated_tokens_before,
        estimated_tokens_after,
        estimated_tokens_saved,
        estimated_token_reduction_rate: rate(estimated_tokens_saved, estimated_tokens_before),
        system_messages_preserved,
        tool_pairs_preserved,
        passed: kept_user_turns == expected_turns
            && reduction_correct
            && system_messages_preserved
            && tool_pairs_preserved,
    })
}

fn english_session(turns: usize) -> Session {
    let mut session = base_session();
    for index in 1..=turns {
        session.messages.push(text_message(
            MessageRole::User,
            &format!(
                "Turn {index}: inspect the migration code, identify API semantics, and retain evidence."
            ),
        ));
        session.messages.push(text_message(
            MessageRole::Assistant,
            &format!(
                "Turn {index} result: compared dtype, shape, defaults, and official mapping evidence."
            ),
        ));
    }
    session
}

fn chinese_session(turns: usize) -> Session {
    let mut session = base_session();
    for index in 1..=turns {
        session.messages.push(text_message(
            MessageRole::User,
            &format!("第{index}轮：检查迁移代码中的接口、数据类型、形状和默认参数差异。"),
        ));
        session.messages.push(text_message(
            MessageRole::Assistant,
            &format!("第{index}轮结果：已保留源码位置、运行证据和官方映射依据。"),
        ));
    }
    session
}

fn tool_session(turns: usize) -> Session {
    let mut session = base_session();
    for index in 1..=turns {
        let call_id = format!("call-{index}");
        session.messages.push(text_message(
            MessageRole::User,
            &format!("Inspect migration file {index} and explain the first divergence."),
        ));
        session.messages.push(Message {
            role: MessageRole::Assistant,
            blocks: vec![ContentBlock::ToolCall {
                id: call_id.clone(),
                name: "read".into(),
                input: format!(r#"{{"file_path":"model_{index}.py"}}"#),
            }],
        });
        session.messages.push(Message {
            role: MessageRole::Tool,
            blocks: vec![ContentBlock::ToolResult {
                tool_call_id: call_id,
                output: format!(
                    "line {index}: tensor dtype=float32 shape=[2,2]; mapping evidence retained"
                ),
                is_error: false,
            }],
        });
        session.messages.push(text_message(
            MessageRole::Assistant,
            &format!("File {index} is consistent through the inspected operation."),
        ));
    }
    session
}

fn base_session() -> Session {
    let mut session = Session::new("benchmark-workspace".into());
    session.messages.push(text_message(
        MessageRole::System,
        "You are a deterministic PyTorch to MindSpore migration assistant.",
    ));
    session
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
    fn context_benchmark_reduces_estimated_tokens_and_preserves_turn_integrity() {
        let report = benchmark_context_compaction().unwrap();

        assert_eq!(report.case_count, 4);
        assert!(report.estimated_tokens_saved > 0);
        assert!(report.estimated_token_reduction_rate > 0.5);
        assert!(report.integrity_passed);
        assert!(!report.provider_cache_metrics_available);
        assert_eq!(report.provider_cache_hit_rate, None);
        assert!(report.passed);
        let checked_in: serde_json::Value = serde_json::from_str(include_str!(
            "../../benchmarks/results/context_compaction_v1.json"
        ))
        .unwrap();
        assert_eq!(serde_json::to_value(&report).unwrap(), checked_in);
    }
}
