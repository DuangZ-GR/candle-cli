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
            "read" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let file_path = value
                    .get("file_path")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing file_path".to_string())?;
                read::run(file_path)
            }
            "glob" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let pattern = value
                    .get("pattern")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing pattern".to_string())?;
                let root = value.get("root").and_then(|v| v.as_str());
                glob::run(pattern, root)
            }
            "grep" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let pattern = value
                    .get("pattern")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing pattern".to_string())?;
                let path = value.get("path").and_then(|v| v.as_str());
                grep::run(pattern, path)
            }
            "shell" if self.allow_mutation => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let command = value
                    .get("command")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing command".to_string())?;
                shell::run(command)
            }
            "shell" => Err("shell is not allowed in read-only mode".to_string()),
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
            "write" => Err("write is not allowed in read-only mode".to_string()),
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
            "edit" => Err("edit is not allowed in read-only mode".to_string()),
            other => Err(format!("unknown tool: {other}")),
        }
    }
}
