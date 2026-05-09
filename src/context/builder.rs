use crate::context::budget::estimate_tokens_json;
use crate::context::compact::compact_session;
use crate::model::types::TurnRequest;
use crate::session::model::Session;

/// Default system prompt for the CLI assistant.
pub const DEFAULT_SYSTEM_PROMPT: &str = "\
You are a terminal-based AI assistant built with Rust. \
You help with software engineering tasks: reading and editing code, \
running shell commands, debugging, and answering technical questions. \
Be concise and direct. When asked to make changes, do so precisely \
without unnecessary refactoring. When you don't know something, say so.";

/// Maximum user-assistant turns to keep in context. Configurable via env var.
pub const DEFAULT_MAX_TURNS: usize = 20;

pub fn resolve_system_prompt() -> String {
    std::env::var("CANDLE_CLI_SYSTEM_PROMPT").unwrap_or_else(|_| DEFAULT_SYSTEM_PROMPT.to_string())
}

fn resolve_system_prompt_with_tools(tools_json: &str) -> String {
    let base = resolve_system_prompt();
    if tools_json.trim().is_empty() || tools_json.trim() == "[]" {
        return base;
    }

    format!(
        "{base}\n\nTool protocol:\n- Use tools when you need to inspect files, edit files, or run commands.\n- To call a tool, output exactly one <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call> block.\n- Do not mix final answer text with a tool call.\n- After receiving tool results, either request another tool or provide the final answer.\n- Available tools JSON: {tools_json}"
    )
}

pub fn resolve_max_turns() -> usize {
    std::env::var("CANDLE_CLI_MAX_TURNS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(DEFAULT_MAX_TURNS)
}

pub fn build_turn_request(session: &mut Session, tools_json: &str) -> Result<TurnRequest, String> {
    let max_turns = resolve_max_turns();
    let _before = session.messages.len();
    compact_session(session, max_turns);
    let _after = session.messages.len();

    let messages_json = serde_json::to_string(&session.messages).map_err(|e| e.to_string())?;
    let _token_est = estimate_tokens_json(&messages_json);

    Ok(TurnRequest {
        system_prompt: resolve_system_prompt_with_tools(tools_json),
        messages_json,
        tools_json: tools_json.to_string(),
    })
}
