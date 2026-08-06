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
            PermissionMode::ReadOnlyWithTask => {
                matches!(tool_name, "pwd" | "read" | "glob" | "grep" | "task")
            }
            PermissionMode::WorkspaceWrite => true,
            PermissionMode::DangerFullAccess => true,
            PermissionMode::Prompt => true,
        }
    }

    pub fn requires_prompt(&self, tool_name: &str) -> bool {
        match self.mode {
            PermissionMode::WorkspaceWrite => matches!(tool_name, "shell" | "web_search"),
            PermissionMode::Prompt => {
                matches!(tool_name, "shell" | "edit" | "write" | "web_search")
            }
            PermissionMode::ReadOnly
            | PermissionMode::ReadOnlyWithTask
            | PermissionMode::DangerFullAccess => false,
        }
    }
}
