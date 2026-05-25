use crate::tools::builtin::{edit, glob, grep, pwd, read, shell, write};
use crate::tools::types::ToolResult;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub struct ToolRegistry {
    allow_mutation: bool,
    workspace_root: PathBuf,
}

impl ToolRegistry {
    pub fn default_read_only() -> Self {
        Self::read_only(std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
    }

    pub fn default_workspace_write() -> Self {
        Self::workspace_write(std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
    }

    pub fn read_only(workspace_root: impl Into<PathBuf>) -> Self {
        Self {
            allow_mutation: false,
            workspace_root: workspace_root.into(),
        }
    }

    pub fn workspace_write(workspace_root: impl Into<PathBuf>) -> Self {
        Self {
            allow_mutation: true,
            workspace_root: workspace_root.into(),
        }
    }

    pub fn tool_names(&self) -> Vec<&'static str> {
        vec!["pwd", "read", "glob", "grep", "edit", "shell"]
    }

    pub fn execute(&self, name: &str, input_json: &str) -> ToolResult {
        match name {
            "pwd" => Ok(pwd::run()),
            "glob" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let pattern = value
                    .get("pattern")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing pattern".to_string())?;
                let safe_pattern = self.resolve_glob_pattern(pattern)?;
                glob::run(&safe_pattern, Some(self.workspace_root_str()?))
            }
            "grep" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let pattern = value
                    .get("pattern")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing pattern".to_string())?;
                let path = value.get("path").and_then(|v| v.as_str()).unwrap_or(".");
                let safe_path = self.resolve_existing_path(path)?;
                grep::run(
                    pattern,
                    Some(
                        safe_path
                            .to_str()
                            .ok_or_else(|| "non-utf8 path".to_string())?,
                    ),
                )
            }
            "read" => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let file_path = value
                    .get("file_path")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing file_path".to_string())?;
                let safe_path = self.resolve_existing_path(file_path)?;
                read::run(
                    safe_path
                        .to_str()
                        .ok_or_else(|| "non-utf8 path".to_string())?,
                )
            }
            "shell" if self.allow_mutation => {
                let value: serde_json::Value =
                    serde_json::from_str(input_json).map_err(|e| e.to_string())?;
                let command = value
                    .get("command")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| "missing command".to_string())?;
                shell::run(command, &self.workspace_root, self.shell_timeout())
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
                let safe_path = self.resolve_writable_path(file_path)?;
                write::run(
                    safe_path
                        .to_str()
                        .ok_or_else(|| "non-utf8 path".to_string())?,
                    content,
                )
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
                let safe_path = self.resolve_existing_path(file_path)?;
                edit::run(
                    safe_path
                        .to_str()
                        .ok_or_else(|| "non-utf8 path".to_string())?,
                    old_string,
                    new_string,
                )
            }
            other => Err(format!("unknown tool: {other}")),
        }
    }

    fn workspace_root_str(&self) -> Result<&str, String> {
        self.workspace_root
            .to_str()
            .ok_or_else(|| "non-utf8 workspace path".to_string())
    }

    fn shell_timeout(&self) -> Duration {
        let secs = std::env::var("CANDLE_CLI_SHELL_TIMEOUT_SECS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .filter(|v| *v > 0)
            .unwrap_or(30);
        Duration::from_secs(secs)
    }

    fn resolve_existing_path(&self, raw: &str) -> Result<PathBuf, String> {
        let candidate = self.resolve_input_path(raw);
        let canonical = candidate
            .canonicalize()
            .map_err(|err| format!("failed to resolve {raw}: {err}"))?;
        self.ensure_in_workspace(raw, canonical)
    }

    fn resolve_writable_path(&self, raw: &str) -> Result<PathBuf, String> {
        let candidate = self.resolve_input_path(raw);
        let parent = candidate
            .parent()
            .ok_or_else(|| format!("invalid path: {raw}"))?;
        let canonical_parent = parent
            .canonicalize()
            .map_err(|err| format!("failed to resolve parent for {raw}: {err}"))?;
        let file_name = candidate
            .file_name()
            .ok_or_else(|| format!("invalid path: {raw}"))?;
        self.ensure_in_workspace(raw, canonical_parent.join(file_name))
    }

    fn resolve_glob_pattern(&self, raw: &str) -> Result<String, String> {
        if Path::new(raw).is_absolute() {
            let safe = self.resolve_existing_path(raw)?;
            return Ok(safe.display().to_string());
        }

        if raw.contains("..") {
            return Err(format!("path escapes workspace: {raw}"));
        }

        Ok(self.workspace_root.join(raw).display().to_string())
    }

    fn resolve_input_path(&self, raw: &str) -> PathBuf {
        let path = Path::new(raw);
        if path.is_absolute() {
            path.to_path_buf()
        } else {
            self.workspace_root.join(path)
        }
    }

    fn ensure_in_workspace(&self, raw: &str, canonical: PathBuf) -> Result<PathBuf, String> {
        let workspace = self
            .workspace_root
            .canonicalize()
            .map_err(|err| format!("failed to resolve workspace root: {err}"))?;
        if canonical.starts_with(&workspace) {
            Ok(canonical)
        } else {
            Err(format!("path escapes workspace: {raw}"))
        }
    }
}
