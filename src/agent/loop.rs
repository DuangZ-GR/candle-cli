use crate::agent::tool_call::{parse_tool_call, ToolCallParseError};
use crate::agent::trace::{ExecutionTrace, TraceEvent};
use crate::agent::turn::finish_turn;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{ToolCallIntent, TurnResult};
use crate::permissions::policy::PermissionPolicy;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;

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
        let result = runtime.generate_turn(request)?;

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
                } else {
                    match tools.execute(&tool_call.name, &tool_call.input_json) {
                        Ok(output) => (format_tool_success(&tool_call.name, &output), false),
                        Err(err) => (format_tool_error(&tool_call.name, &err), true),
                    }
                };
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
  {"name":"edit","description":"Replace exactly one string occurrence in an existing file","input_schema":{"type":"object","properties":{"file_path":{"type":"string"},"old_string":{"type":"string"},"new_string":{"type":"string"}},"required":["file_path","old_string","new_string"]}},
  {"name":"shell","description":"Run a shell command and return its output","input_schema":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}
]"#
}
