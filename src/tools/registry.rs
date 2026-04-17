use crate::tools::builtin::{edit, glob, grep, pwd, read, shell, write};
use crate::tools::types::ToolResult;

pub struct ToolRegistry {
    allow_mutation: bool,
}

impl ToolRegistry {
    pub fn default_read_only() -> Self {
        Self {
            allow_mutation: false,
        }
    }

    pub fn default_workspace_write() -> Self {
        Self {
            allow_mutation: true,
        }
    }

    pub fn execute(&self, name: &str, input_json: &str) -> ToolResult {
        match name {
            "pwd" => Ok(pwd::run()),
            "glob" => Ok(glob::run("", None)),
            "grep" => Ok(grep::run("", None)),
            "read" => Ok(read::run("")),
            "shell" if self.allow_mutation => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let command = value
                    .get("command")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing command".to_string())?;
                shell::run(command)
            }
            "write" if self.allow_mutation => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let file_path = value
                    .get("file_path")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing file_path".to_string())?;
                let content = value
                    .get("content")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing content".to_string())?;
                write::run(file_path, content)
            }
            "edit" if self.allow_mutation => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let file_path = value
                    .get("file_path")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing file_path".to_string())?;
                let old_string = value
                    .get("old_string")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing old_string".to_string())?;
                let new_string = value
                    .get("new_string")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing new_string".to_string())?;
                edit::run(file_path, old_string, new_string)
            }
            other => Err(format!("unknown tool: {other}")),
        }
    }
}
