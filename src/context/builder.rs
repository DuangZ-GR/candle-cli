use crate::context::budget::estimate_tokens_json;
use crate::context::compact::compact_session;
use crate::model::types::TurnRequest;
use crate::session::model::{ContentBlock, MessageRole, Session};

/// Default system prompt for the CLI assistant.
pub const DEFAULT_SYSTEM_PROMPT: &str = "\
You are candle-cli, a local terminal AI assistant built with Rust. \
You help with software engineering tasks: reading and editing code, \
running shell commands, debugging, and answering technical questions. \
Be concise and direct. When asked to make changes, do so precisely \
without unnecessary refactoring. When you don't know something, say so.";

/// Maximum user-assistant turns to keep in context. Configurable via env var.
pub const DEFAULT_MAX_TURNS: usize = 20;

/// Maximum lines of grep-RAG results to inject.
const RAG_MAX_LINES: usize = 10;

pub fn resolve_system_prompt() -> String {
    std::env::var("CANDLE_CLI_SYSTEM_PROMPT").unwrap_or_else(|_| DEFAULT_SYSTEM_PROMPT.to_string())
}

fn resolve_system_prompt_with_tools(tools_json: &str) -> String {
    let base = resolve_system_prompt();
    if tools_json.trim().is_empty() || tools_json.trim() == "[]" {
        return base;
    }

    format!(
        "{base}\n\nTool protocol:\n- Use tools when you need to inspect files, edit files, or run commands.\n- To call a tool, output exactly one raw <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call> block.\n- Do not output Markdown code fences.\n- Do not output read(...), shell(...), function calls, or pseudo-code.\n- Do not mix final answer text with a tool call.\n- If a tool is needed, the entire assistant response must be only the <tool_call> block.\n- After receiving a tool result, you must either request exactly one more tool or provide a non-empty final answer.\n- Do not return an empty response.\n- If the tool result already contains enough information, summarize it directly in natural language.\n- Use the web_search tool when you need real-time information (weather, news, current events, etc.). Just provide the search query — no URL needed.\n\nExample 1:\nUser: 读取 README.md\nAssistant: <tool_call>{{\"id\":\"call-1\",\"name\":\"read\",\"input\":{{\"file_path\":\"README.md\"}}}}</tool_call>\n\nExample 2:\nTool result: README 说明可以通过 cargo run -- prompt \"你好\" 运行，也可以通过 cargo test 运行测试。\nAssistant: 这个项目可以通过 cargo run 或 cargo test 运行。\n\nAvailable tools JSON: {tools_json}"
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

    // RAG enriches only the outbound request. The original user message stays
    // unchanged in the persisted session so repeated tool steps cannot nest
    // previously injected context or corrupt future keyword extraction.
    let mut request_session = session.clone();
    inject_rag_context(&mut request_session);

    let messages_json =
        serde_json::to_string(&request_session.messages).map_err(|e| e.to_string())?;
    let _token_est = estimate_tokens_json(&messages_json);

    let memory_ctx =
        crate::session::memory::ProjectMemory::load(&session.workspace_root).to_context_string();
    let system_prompt = if memory_ctx.lines().count() > 1 {
        format!(
            "{}\n\n{}",
            resolve_system_prompt_with_tools(tools_json),
            memory_ctx
        )
    } else {
        resolve_system_prompt_with_tools(tools_json)
    };

    Ok(TurnRequest {
        system_prompt,
        messages_json,
        tools_json: tools_json.to_string(),
    })
}

// ── grep-RAG ────────────────────────────────────────────────────────────

fn inject_rag_context(session: &mut Session) {
    let question = match last_user_text(session) {
        Some(text) => text,
        None => return,
    };

    if !is_code_related(&question) {
        return;
    }

    let keywords = extract_keywords(&question);
    if keywords.is_empty() {
        return;
    }

    // Run grep for each keyword against src/ only, take first RAG_MAX_LINES.
    let mut hits: Vec<String> = Vec::new();
    for kw in &keywords {
        if hits.len() >= RAG_MAX_LINES {
            break;
        }
        if let Ok(output) = crate::tools::builtin::grep::run(kw, Some("src")) {
            for line in output.lines().take(RAG_MAX_LINES - hits.len()) {
                hits.push(line.to_string());
            }
        }
    }

    if hits.is_empty() {
        return;
    }

    let rag_block = format!(
        "The following code may be relevant to the question:\n{}\n\nQuestion: {}",
        hits.join("\n"),
        question
    );

    // Replace the last user message text with the augmented version.
    if let Some(msg) = session
        .messages
        .iter_mut()
        .rev()
        .find(|m| m.role == MessageRole::User)
    {
        if let Some(block) = msg.blocks.first_mut() {
            if let ContentBlock::Text { text } = block {
                *text = rag_block;
            }
        }
    }
}

fn last_user_text(session: &Session) -> Option<String> {
    for msg in session.messages.iter().rev() {
        if msg.role == MessageRole::User {
            for block in &msg.blocks {
                if let ContentBlock::Text { text } = block {
                    return Some(text.clone());
                }
            }
        }
    }
    None
}

fn is_code_related(text: &str) -> bool {
    let lowered = text.to_lowercase();

    let chat_patterns = [
        "你好",
        "hi",
        "hello",
        "hey",
        "谢谢",
        "thanks",
        "thank you",
        "再见",
        "bye",
        "goodbye",
        "早上好",
        "晚上好",
        "good morning",
        "good evening",
        "ok",
        "好的",
        "嗯",
        "哦",
    ];
    let trimmed = lowered.trim();
    for pat in &chat_patterns {
        if trimmed == *pat || trimmed.starts_with(pat) && trimmed.len() <= pat.len() + 3 {
            return false;
        }
    }

    // Must have at least some substance
    trimmed.len() > 10
}

fn extract_keywords(text: &str) -> Vec<String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Vec::new();
    }

    // Use the full question as the primary search phrase (substring grep).
    // Also split on common Chinese/English delimiters for component phrases.
    let mut phrases: Vec<String> = Vec::new();
    if trimmed.len() <= 40 {
        phrases.push(trimmed.to_lowercase());
    }

    let mut seen = std::collections::HashSet::new();
    for raw in trimmed.split(|c: char| {
        c.is_whitespace() || matches!(c, '，' | '。' | '？' | '！' | '、' | '：' | '；' | '的')
    }) {
        let word = raw.trim().to_lowercase();
        if word.len() < 3 || word.len() > 40 {
            continue;
        }
        if matches!(
            word.as_str(),
            "the"
                | "and"
                | "for"
                | "with"
                | "that"
                | "this"
                | "from"
                | "what"
                | "when"
                | "where"
                | "which"
                | "how"
                | "does"
                | "can"
                | "你"
                | "我"
                | "他"
                | "是"
                | "了"
                | "在"
                | "有"
                | "不"
                | "这"
                | "那"
                | "什么"
                | "怎么"
                | "为什么"
                | "一个"
                | "一下"
                | "帮我"
                | "请"
                | "可以"
                | "哪个"
                | "哪些"
                | "多少"
        ) {
            continue;
        }
        if seen.insert(word.clone()) {
            phrases.push(word);
        }
    }

    phrases.truncate(4);
    phrases
}
