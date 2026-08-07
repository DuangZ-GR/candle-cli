use std::str::FromStr;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PermissionMode {
    ReadOnly,
    ReadOnlyWithTask,
    WorkspaceWrite,
    DangerFullAccess,
    Prompt,
}

impl FromStr for PermissionMode {
    type Err = ();

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_ascii_lowercase().as_str() {
            "read-only" => Ok(Self::ReadOnly),
            "read-only-with-task" => Ok(Self::ReadOnlyWithTask),
            "workspace-write" => Ok(Self::WorkspaceWrite),
            "danger-full-access" => Ok(Self::DangerFullAccess),
            "prompt" => Ok(Self::Prompt),
            _ => Err(()),
        }
    }
}
