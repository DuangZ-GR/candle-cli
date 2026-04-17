use crate::tools::builtin::{glob, grep, pwd, read};
use crate::tools::types::ToolResult;

pub struct ToolRegistry;

impl ToolRegistry {
    pub fn default_read_only() -> Self {
        Self
    }

    pub fn execute(&self, name: &str, _input_json: &str) -> ToolResult {
        match name {
            "pwd" => Ok(pwd::run()),
            "glob" => Ok(glob::run("", None)),
            "grep" => Ok(grep::run("", None)),
            "read" => Ok(read::run("")),
            other => Err(format!("unknown tool: {other}")),
        }
    }
}
