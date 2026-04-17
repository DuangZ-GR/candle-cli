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
            PermissionMode::ReadOnly => matches!(tool_name, "read" | "glob" | "grep" | "pwd"),
            PermissionMode::WorkspaceWrite | PermissionMode::DangerFullAccess => true,
            PermissionMode::Prompt => matches!(tool_name, "read" | "glob" | "grep" | "pwd"),
        }
    }

    pub fn requires_prompt(&self, tool_name: &str) -> bool {
        matches!(self.mode, PermissionMode::Prompt)
            && matches!(tool_name, "write" | "edit" | "shell")
    }
}
