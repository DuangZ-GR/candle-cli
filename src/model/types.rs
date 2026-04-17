#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TurnRequest {
    pub system_prompt: String,
    pub messages_json: String,
    pub tools_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolCallIntent {
    pub id: String,
    pub name: String,
    pub input_json: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeEvent {
    TextDelta(String),
    ToolCall(ToolCallIntent),
    Warning(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TurnResult {
    pub final_text: String,
    pub tool_calls: Vec<ToolCallIntent>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeCapabilities {
    pub supports_tools: bool,
    pub supports_streaming: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeHealth {
    pub ok: bool,
    pub message: String,
}
