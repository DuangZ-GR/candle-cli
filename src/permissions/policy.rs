use crate::permissions::mode::PermissionMode;

pub struct PermissionPolicy {
    mode: PermissionMode,
}

impl PermissionPolicy {
    pub fn new(mode: PermissionMode) -> Self {
        Self { mode }
    }

    pub fn allows(&self, tool_name: &str) -> bool {
        match self.mode {
            PermissionMode::ReadOnly => matches!(tool_name, "pwd" | "read" | "glob" | "grep"),
            PermissionMode::WorkspaceWrite => true,
            PermissionMode::DangerFullAccess => true,
            PermissionMode::Prompt => true,
        }
    }

    pub fn requires_prompt(&self, tool_name: &str) -> bool {
        match self.mode {
            PermissionMode::WorkspaceWrite => tool_name == "shell",
            PermissionMode::Prompt => matches!(tool_name, "shell" | "edit" | "write"),
            PermissionMode::ReadOnly | PermissionMode::DangerFullAccess => false,
        }
    }
}
