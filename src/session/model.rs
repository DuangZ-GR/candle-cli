use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum MessageRole {
    System,
    User,
    Assistant,
    Tool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ContentBlock {
    Text { text: String },
    ToolCall { id: String, name: String, input: String },
    ToolResult { tool_call_id: String, output: String, is_error: bool },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Message {
    pub role: MessageRole,
    pub blocks: Vec<ContentBlock>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Session {
    pub session_id: String,
    pub workspace_root: String,
    pub messages: Vec<Message>,
}

impl Session {
    pub fn new(workspace_root: String) -> Self {
        Self {
            session_id: "session-1".into(),
            workspace_root,
            messages: Vec::new(),
        }
    }
}
