use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::PathBuf;

/// Project-level memory stored in .candle-cli/memory.json
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct ProjectMemory {
    pub key_files: Vec<String>,
    pub common_commands: Vec<String>,
    pub notes: HashMap<String, String>,
}

impl ProjectMemory {
    fn path(workspace_root: &str) -> PathBuf {
        let mut p = PathBuf::from(workspace_root);
        p.push(".candle-cli");
        p.push("memory.json");
        p
    }

    pub fn load(workspace_root: &str) -> Self {
        let path = Self::path(workspace_root);
        match fs::read_to_string(&path) {
            Ok(body) => serde_json::from_str(&body).unwrap_or_default(),
            Err(_) => Self::default(),
        }
    }

    pub fn save(&self, workspace_root: &str) -> io::Result<()> {
        let path = Self::path(workspace_root);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let body = serde_json::to_string_pretty(self)
            .map_err(io::Error::other)?
            .into_bytes();
        fs::write(path, body)
    }

    pub fn add_key_file(&mut self, path: &str) {
        if !self.key_files.contains(&path.to_string()) {
            self.key_files.push(path.to_string());
        }
    }

    pub fn add_command(&mut self, cmd: &str) {
        if !self.common_commands.contains(&cmd.to_string()) {
            self.common_commands.push(cmd.to_string());
        }
    }

    pub fn set_note(&mut self, key: &str, value: &str) {
        self.notes.insert(key.to_string(), value.to_string());
    }

    pub fn to_context_string(&self) -> String {
        let mut lines = vec!["[Project Memory]".to_string()];
        if !self.key_files.is_empty() {
            lines.push(format!("Key files: {}", self.key_files.join(", ")));
        }
        if !self.common_commands.is_empty() {
            lines.push(format!(
                "Common commands: {}",
                self.common_commands.join(", ")
            ));
        }
        for (k, v) in &self.notes {
            lines.push(format!("{k}: {v}"));
        }
        lines.join("\n")
    }
}
