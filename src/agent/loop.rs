use crate::agent::tool_call::{parse_tool_call, ToolCallParseError};
use crate::agent::trace::{ExecutionTrace, TraceEvent};
use crate::agent::turn::finish_turn;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{ToolCallIntent, TurnResult};
use crate::permissions::policy::PermissionPolicy;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;
use crate::ui::spinner::Spinner;

const DEFAULT_MAX_TOOL_STEPS: usize = 8;

pub fn run_single_turn<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    policy: &PermissionPolicy,
) -> Result<TurnResult, String> {
    let mut trace = ExecutionTrace::new();
    run_single_turn_with_trace(session, runtime, tools, policy, &mut trace)
}

pub fn run_single_turn_with_trace<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    policy: &PermissionPolicy,
    trace: &mut ExecutionTrace,
) -> Result<TurnResult, String> {
    run_single_turn_with_limit_and_trace(
        session,
        runtime,
        tools,
        policy,
        DEFAULT_MAX_TOOL_STEPS,
        trace,
    )
}

pub fn run_single_turn_with_limit<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    policy: &PermissionPolicy,
    max_steps: usize,
) -> Result<TurnResult, String> {
    let mut trace = ExecutionTrace::new();
    run_single_turn_with_limit_and_trace(session, runtime, tools, policy, max_steps, &mut trace)
}

pub fn run_single_turn_with_limit_and_trace<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    policy: &PermissionPolicy,
    max_steps: usize,
    trace: &mut ExecutionTrace,
) -> Result<TurnResult, String> {
    let verbose = verbose_enabled();

    for step in 0..max_steps {
        trace.push(TraceEvent::BuildTurnRequest);
        let request = crate::context::builder::build_turn_request(session, tools_json())?;

        trace.push(TraceEvent::RuntimeGenerateTurn);
        let streaming = runtime.capabilities().supports_streaming
            && std::env::var("CANDLE_CLI_RUNTIME").ok().as_deref() == Some("bridge");
        let spinner = if streaming {
            None
        } else {
            Some(Spinner::start())
        };
        let result = runtime.generate_turn(request);
        if let Some(mut s) = spinner {
            s.stop();
        }
        let result = result?;

        trace.push(TraceEvent::ParseToolCall);
        match parse_tool_call(&result.final_text) {
            Ok(Some(tool_call)) => {
                trace.push(TraceEvent::ToolCall {
                    name: tool_call.name.clone(),
                });
                trace_tool_step(verbose, step + 1, max_steps, &tool_call);
                append_tool_call(session, &tool_call);
                let (output, is_error) = if !policy.allows(&tool_call.name) {
                    (
                        format_tool_error(
                            &tool_call.name,
                            &format!("tool not allowed in read-only mode: {}", tool_call.name),
                        ),
                        true,
                    )
                } else if policy.requires_prompt(&tool_call.name)
                    && !crate::permissions::prompt::confirm_dangerous_action(
                        &tool_call.name,
                        &tool_call.input_json,
                    )
                {
                    (
                        format_tool_error(&tool_call.name, "tool execution denied by user"),
                        true,
                    )
                } else if tool_call.name == "task" {
                    let desc: serde_json::Value =
                        serde_json::from_str(&tool_call.input_json).unwrap_or_default();
                    let desc = desc
                        .get("description")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    match crate::tools::builtin::task::run(desc, runtime, tools, policy) {
                        Ok(output) => (format_tool_success("task", &output), false),
                        Err(err) => (format_tool_error("task", &err), true),
                    }
                } else {
                    match tools.execute(&tool_call.name, &tool_call.input_json) {
                        Ok(output) => (format_tool_success(&tool_call.name, &output), false),
                        Err(err) => (format_tool_error(&tool_call.name, &err), true),
                    }
                };
                let output = bound_tool_output(output);
                trace.push(TraceEvent::ToolResult {
                    tool: tool_call.name.clone(),
                    status: if is_error { "error" } else { "ok" }.to_string(),
                });
                trace_tool_result(verbose, &output, is_error);
                append_tool_result(session, &tool_call.id, output, is_error);
            }
            Ok(None) => {
                let final_text = finish_turn(result.final_text.clone());
                trace.push(TraceEvent::FinalAnswer);
                append_assistant_text(session, final_text.clone());
                return Ok(TurnResult {
                    final_text,
                    tool_calls: Vec::new(),
                });
            }
            Err(err) => {
                trace_parse_error(verbose, &err);
                let correction = malformed_tool_call_message(&err);
                append_assistant_text(session, correction);
            }
        }
    }

    let final_text = format!("stopped after reaching maximum tool steps ({max_steps})");
    trace.push(TraceEvent::FinalAnswer);
    append_assistant_text(session, final_text.clone());
    Ok(TurnResult {
        final_text,
        tool_calls: Vec::new(),
    })
}

fn append_tool_call(session: &mut Session, tool_call: &ToolCallIntent) {
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::ToolCall {
            id: tool_call.id.clone(),
            name: tool_call.name.clone(),
            input: tool_call.input_json.clone(),
        }],
    });
}

fn append_tool_result(session: &mut Session, tool_call_id: &str, output: String, is_error: bool) {
    session.messages.push(Message {
        role: MessageRole::Tool,
        blocks: vec![ContentBlock::ToolResult {
            tool_call_id: tool_call_id.to_string(),
            output,
            is_error,
        }],
    });
}

fn append_assistant_text(session: &mut Session, text: String) {
    session.messages.push(Message {
        role: MessageRole::Assistant,
        blocks: vec![ContentBlock::Text { text }],
    });
}

fn malformed_tool_call_message(err: &ToolCallParseError) -> String {
    format!(
        "The previous tool call was malformed: {err}. Expected exactly one raw tool call block like <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call>. retry with one valid tool call or provide a final answer."
    )
}

fn format_tool_success(tool_name: &str, output: &str) -> String {
    if tool_name == "shell" && output.starts_with("status: ok") {
        return output.to_string();
    }
    format!("status: ok\ntool: {tool_name}\noutput:\n{output}")
}

fn format_tool_error(tool_name: &str, message: &str) -> String {
    if tool_name == "shell"
        && (message.starts_with("status: error") || message.starts_with("status: ok"))
    {
        return message.to_string();
    }
    format!("status: error\ntool: {tool_name}\nmessage: {message}")
}

fn bound_tool_output(output: String) -> String {
    let max_chars = std::env::var("CANDLE_CLI_MAX_TOOL_OUTPUT_CHARS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(65_536);
    truncate_tool_output(output, max_chars)
}

fn truncate_tool_output(output: String, max_chars: usize) -> String {
    let char_count = output.chars().count();
    if char_count <= max_chars {
        return output;
    }

    let byte_end = output
        .char_indices()
        .nth(max_chars)
        .map(|(index, _)| index)
        .unwrap_or(output.len());
    let omitted = char_count - max_chars;
    format!(
        "{}\n\n[tool output truncated: {omitted} characters omitted]",
        &output[..byte_end]
    )
}

fn verbose_enabled() -> bool {
    std::env::var("CANDLE_CLI_VERBOSE")
        .map(|value| matches!(value.as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(false)
}

fn trace_tool_step(verbose: bool, step: usize, max_steps: usize, tool_call: &ToolCallIntent) {
    if verbose {
        eprintln!(
            "[tool step {step}/{max_steps}] {} {}",
            tool_call.name, tool_call.input_json
        );
    }
}

fn trace_tool_result(verbose: bool, output: &str, is_error: bool) {
    if verbose {
        let detail = output
            .lines()
            .find(|line| line.starts_with("exit_code:") || line.starts_with("message:"));
        match (is_error, detail) {
            (true, Some(detail)) => eprintln!("[tool result] error: {detail}"),
            (true, None) => eprintln!("[tool result] error"),
            (false, _) => eprintln!("[tool result] ok"),
        }
    }
}

fn trace_parse_error(verbose: bool, err: &ToolCallParseError) {
    if verbose {
        eprintln!("[tool parse error] {err}");
    }
}

fn tools_json() -> &'static str {
    r#"[
  {"name":"pwd","description":"Return the current working directory","input_schema":{"type":"object","properties":{}}},
  {"name":"read","description":"Read a UTF-8 file","input_schema":{"type":"object","properties":{"file_path":{"type":"string"}},"required":["file_path"]}},
  {"name":"glob","description":"Find files matching a simple glob pattern","input_schema":{"type":"object","properties":{"pattern":{"type":"string"}},"required":["pattern"]}},
  {"name":"grep","description":"Search files for a substring","input_schema":{"type":"object","properties":{"pattern":{"type":"string"},"path":{"type":"string"}},"required":["pattern"]}},
  {"name":"web_search","description":"Search the web via DuckDuckGo and return text results","input_schema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}},
  {"name":"task","description":"Delegate a read-only subtask to a sub-agent","input_schema":{"type":"object","properties":{"description":{"type":"string"}},"required":["description"]}},
  {"name":"write","description":"Write a UTF-8 file inside the workspace","input_schema":{"type":"object","properties":{"file_path":{"type":"string"},"content":{"type":"string"}},"required":["file_path","content"]}},
  {"name":"edit","description":"Replace exactly one string occurrence in an existing file","input_schema":{"type":"object","properties":{"file_path":{"type":"string"},"old_string":{"type":"string"},"new_string":{"type":"string"}},"required":["file_path","old_string","new_string"]}},
  {"name":"shell","description":"Run a shell command and return its output","input_schema":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}
]"#
}

#[cfg(test)]
mod output_limit_tests {
    use super::truncate_tool_output;

    #[test]
    fn keeps_output_within_the_limit_unchanged() {
        assert_eq!(truncate_tool_output("hello".into(), 5), "hello");
    }

    #[test]
    fn truncates_output_and_reports_the_omitted_character_count() {
        assert_eq!(
            truncate_tool_output("abcdefgh".into(), 5),
            "abcde\n\n[tool output truncated: 3 characters omitted]"
        );
    }

    #[test]
    fn truncation_respects_utf8_character_boundaries() {
        assert_eq!(
            truncate_tool_output("迁移诊断".into(), 2),
            "迁移\n\n[tool output truncated: 2 characters omitted]"
        );
    }
}
