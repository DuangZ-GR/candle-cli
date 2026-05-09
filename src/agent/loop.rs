use crate::agent::tool_call::{parse_tool_call, ToolCallParseError};
use crate::agent::turn::finish_turn;
use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{ToolCallIntent, TurnResult};
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::tools::registry::ToolRegistry;

const DEFAULT_MAX_TOOL_STEPS: usize = 8;

pub fn run_single_turn<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
) -> Result<TurnResult, String> {
    run_single_turn_with_limit(session, runtime, tools, DEFAULT_MAX_TOOL_STEPS)
}

pub fn run_single_turn_with_limit<R: CandleTargetRuntime>(
    session: &mut Session,
    runtime: &mut R,
    tools: &ToolRegistry,
    max_steps: usize,
) -> Result<TurnResult, String> {
    for _ in 0..max_steps {
        let request = crate::context::builder::build_turn_request(session, tools_json())?;
        let result = runtime.generate_turn(request)?;

        match parse_tool_call(&result.final_text) {
            Ok(Some(tool_call)) => {
                append_tool_call(session, &tool_call);
                let (output, is_error) = match tools.execute(&tool_call.name, &tool_call.input_json) {
                    Ok(output) => (output, false),
                    Err(err) => (err, true),
                };
                append_tool_result(session, &tool_call.id, output, is_error);
            }
            Ok(None) => {
                let final_text = finish_turn(result.final_text.clone());
                append_assistant_text(session, final_text.clone());
                return Ok(TurnResult {
                    final_text,
                    tool_calls: Vec::new(),
                });
            }
            Err(err) => {
                let correction = malformed_tool_call_message(&err);
                append_assistant_text(session, correction);
            }
        }
    }

    let final_text = format!("stopped after reaching maximum tool steps ({max_steps})");
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
        "The previous tool call was malformed: {err}. Retry with exactly one <tool_call>{{...}}</tool_call> block or provide a final answer."
    )
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
