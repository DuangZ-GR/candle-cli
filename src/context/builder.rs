use crate::context::budget::estimate_tokens_json;
use crate::context::compact::compact_session;
use crate::model::types::TurnRequest;
use crate::session::model::Session;

/// Default system prompt for the CLI assistant.
pub const DEFAULT_SYSTEM_PROMPT: &str = "\
You are candle-cli, a local terminal AI assistant built with Rust. \
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
        "{base}\n\nTool protocol:\n- Use tools when you need to inspect files, edit files, or run commands.\n- To call a tool, output exactly one raw <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call> block.\n- Do not output Markdown code fences.\n- Do not output read(...), shell(...), function calls, or pseudo-code.\n- Do not mix final answer text with a tool call.\n- If a tool is needed, the entire assistant response must be only the <tool_call> block.\n- After receiving a tool result, you must either request exactly one more tool or provide a non-empty final answer.\n- Do not return an empty response.\n- If the tool result already contains enough information, summarize it directly in natural language.\n\nExample 1:\nUser: 读取 README.md\nAssistant: <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call>\n\nExample 2:\nTool result: README 说明可以通过 cargo run -- prompt \"你好\" 运行，也可以通过 cargo test 运行测试。\nAssistant: 这个项目可以通过 cargo run 或 cargo test 运行。\n\nAvailable tools JSON: {tools_json}"
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
    compact_session(session, max_turns);

    let messages_json = serde_json::to_string(&session.messages).map_err(|e| e.to_string())?;
    let _token_est = estimate_tokens_json(&messages_json);

    Ok(TurnRequest {
        system_prompt: resolve_system_prompt_with_tools(tools_json),
        messages_json,
        tools_json: tools_json.to_string(),
    })
}

fn resolve_system_prompt_with_tools(tools_json: &str) -> String {
    let base = resolve_system_prompt();
    if tools_json.trim().is_empty() || tools_json.trim() == "[]" {
        return base;
    }

    format!(
        "{base}\n\n\
TOOL USE PROTOCOL (MUST FOLLOW EXACTLY):\n\
\n\
When you need to inspect files, edit code, or run commands, output a JSON tool call \
wrapped in <tool_call> and </tool_call> tags. Format:\n\
\n\
<tool_call>{{\"id\":\"<unique-id>\",\"name\":\"<tool-name>\",\"input\":{{...}}}}</tool_call>\n\
\n\
RULES:\n\
1. The content between <tool_call> and </tool_call> MUST be valid JSON.\n\
2. The JSON MUST have exactly 3 fields: \"id\" (string), \"name\" (string), \"input\" (object).\n\
3. Do NOT use XML inside the <tool_call> block. Use only JSON.\n\
4. Do NOT mix tool calls with final answer text in the same message.\n\
5. After receiving tool results, either request another tool OR give the final answer.\n\
6. When done, output your final answer as normal text without any <tool_call> tags.\n\
\n\
Available tools: {tools_json}"
    )
}
