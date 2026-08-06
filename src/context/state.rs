use crate::session::model::{ContentBlock, Message, MessageRole};
use serde::{Deserialize, Serialize};

const MAX_FACTS: usize = 64;
const MAX_FACT_VALUE_CHARS: usize = 384;
const MAX_SOURCE_EXCERPT_CHARS: usize = 512;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskFactKind {
    Objective,
    File,
    Command,
    Error,
    Pending,
    Decision,
}

impl TaskFactKind {
    fn label(self) -> &'static str {
        match self {
            Self::Objective => "objective",
            Self::File => "file",
            Self::Command => "command",
            Self::Error => "error",
            Self::Pending => "pending",
            Self::Decision => "decision",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TaskFact {
    pub kind: TaskFactKind,
    pub value: String,
    pub source_role: String,
    pub source_digest: String,
    pub source_excerpt: String,
}

impl TaskFact {
    pub fn evidence_valid(&self) -> bool {
        self.source_digest == evidence_digest(&self.source_role, &self.source_excerpt)
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct StructuredTaskState {
    #[serde(default)]
    pub summary_version: u32,
    #[serde(default)]
    pub summarized_messages: usize,
    #[serde(default)]
    pub facts: Vec<TaskFact>,
}

impl StructuredTaskState {
    pub fn is_empty(&self) -> bool {
        self.facts.is_empty() && self.summarized_messages == 0
    }

    pub fn absorb_messages(&mut self, messages: &[Message]) {
        if messages.is_empty() {
            return;
        }
        self.summary_version = 1;
        self.summarized_messages += messages.len();
        for message in messages {
            self.absorb_message(message);
        }
    }

    pub fn facts_of_kind(&self, kind: TaskFactKind) -> impl Iterator<Item = &TaskFact> {
        self.facts.iter().filter(move |fact| fact.kind == kind)
    }

    pub fn evidence_valid(&self) -> bool {
        self.facts.iter().all(TaskFact::evidence_valid)
    }

    pub fn to_prompt_string(&self) -> String {
        if self.facts.is_empty() {
            return String::new();
        }
        let mut lines = vec![
            "[Structured Task State]".to_string(),
            format!(
                "summary_version={} summarized_messages={}",
                self.summary_version, self.summarized_messages
            ),
            "Historical facts below were extracted from compacted turns. Treat them as task state, and verify against files or commands before making irreversible changes.".to_string(),
        ];
        for fact in &self.facts {
            lines.push(format!(
                "- {}: {} [evidence={}]",
                fact.kind.label(),
                fact.value,
                fact.source_digest
            ));
        }
        lines.join("\n")
    }

    fn absorb_message(&mut self, message: &Message) {
        let role = role_label(&message.role);
        for block in &message.blocks {
            match block {
                ContentBlock::Text { text } => self.absorb_text(&message.role, role, text),
                ContentBlock::ToolCall { name, input, .. } => {
                    self.absorb_tool_call(role, name, input)
                }
                ContentBlock::ToolResult {
                    output, is_error, ..
                } => {
                    if *is_error {
                        self.add_fact(TaskFactKind::Error, output, role, output);
                    } else {
                        for line in output.lines().filter(|line| looks_like_error(line)) {
                            self.add_fact(TaskFactKind::Error, line, role, output);
                        }
                    }
                }
            }
        }
    }

    fn absorb_text(&mut self, role: &MessageRole, role_label: &str, text: &str) {
        if *role == MessageRole::User
            && self
                .facts
                .iter()
                .all(|fact| fact.kind != TaskFactKind::Objective)
        {
            self.add_fact(TaskFactKind::Objective, text, role_label, text);
        }

        for line in text.lines().map(str::trim).filter(|line| !line.is_empty()) {
            if let Some((kind, value)) = parse_fact_marker(line) {
                self.add_fact(kind, value, role_label, text);
                continue;
            }
            if looks_like_error(line) {
                self.add_fact(TaskFactKind::Error, line, role_label, text);
            }
            if looks_like_pending(line) {
                self.add_fact(TaskFactKind::Pending, line, role_label, text);
            }
            if *role == MessageRole::Assistant && looks_like_decision(line) {
                self.add_fact(TaskFactKind::Decision, line, role_label, text);
            }
            for path in extract_file_paths(line) {
                self.add_fact(TaskFactKind::File, &path, role_label, text);
            }
        }
    }

    fn absorb_tool_call(&mut self, role: &str, name: &str, input: &str) {
        let Ok(value) = serde_json::from_str::<serde_json::Value>(input) else {
            return;
        };
        if name == "shell" {
            if let Some(command) = value.get("command").and_then(|item| item.as_str()) {
                self.add_fact(TaskFactKind::Command, command, role, input);
            }
        }
        if name == "task" {
            if let Some(description) = value.get("description").and_then(|item| item.as_str()) {
                self.add_fact(TaskFactKind::Pending, description, role, input);
            }
        }
        for key in [
            "file_path",
            "path",
            "manifest",
            "source_trace",
            "target_trace",
            "output_path",
            "dump_path",
        ] {
            if let Some(path) = value.get(key).and_then(|item| item.as_str()) {
                self.add_fact(TaskFactKind::File, path, role, input);
            }
        }
    }

    fn add_fact(&mut self, kind: TaskFactKind, value: &str, role: &str, source: &str) {
        let value = normalize(value, MAX_FACT_VALUE_CHARS);
        if value.is_empty()
            || self
                .facts
                .iter()
                .any(|fact| fact.kind == kind && fact.value == value)
        {
            return;
        }
        if self.facts.len() >= MAX_FACTS {
            let remove_index = self
                .facts
                .iter()
                .position(|fact| fact.kind != TaskFactKind::Objective)
                .unwrap_or(0);
            self.facts.remove(remove_index);
        }
        let source_excerpt = normalize(source, MAX_SOURCE_EXCERPT_CHARS);
        self.facts.push(TaskFact {
            kind,
            value,
            source_role: role.to_string(),
            source_digest: evidence_digest(role, &source_excerpt),
            source_excerpt,
        });
    }
}

fn parse_fact_marker(line: &str) -> Option<(TaskFactKind, &str)> {
    let (prefix, value) = line.split_once(':')?;
    let kind = match prefix.trim().to_ascii_lowercase().as_str() {
        "objective" | "目标" => TaskFactKind::Objective,
        "file" | "文件" => TaskFactKind::File,
        "command" | "命令" => TaskFactKind::Command,
        "error" | "错误" => TaskFactKind::Error,
        "todo" | "pending" | "待办" => TaskFactKind::Pending,
        "decision" | "决策" => TaskFactKind::Decision,
        _ => return None,
    };
    Some((kind, value.trim()))
}

fn looks_like_error(line: &str) -> bool {
    let lower = line.to_ascii_lowercase();
    lower.contains("error:")
        || lower.contains("failed at")
        || lower.contains("traceback")
        || line.contains("错误：")
        || line.contains("失败位置")
}

fn looks_like_pending(line: &str) -> bool {
    let lower = line.to_ascii_lowercase();
    lower.starts_with("todo:")
        || lower.starts_with("pending:")
        || lower.starts_with("next:")
        || line.starts_with("待办：")
        || line.starts_with("下一步：")
}

fn looks_like_decision(line: &str) -> bool {
    let lower = line.to_ascii_lowercase();
    lower.starts_with("decision:")
        || lower.starts_with("decided:")
        || line.starts_with("决策：")
        || line.starts_with("决定：")
}

fn extract_file_paths(line: &str) -> Vec<String> {
    line.split(|character: char| {
        character.is_whitespace()
            || matches!(
                character,
                '`' | '"' | '\'' | '(' | ')' | '[' | ']' | '{' | '}' | ',' | ';'
            )
    })
    .map(|part| part.trim_end_matches([':', '.']))
    .filter(|part| {
        let lower = part.to_ascii_lowercase();
        [
            ".py", ".rs", ".json", ".jsonl", ".md", ".toml", ".yaml", ".yml", ".txt", ".ckpt",
            ".pt", ".pth",
        ]
        .iter()
        .any(|suffix| lower.ends_with(suffix))
    })
    .map(str::to_string)
    .collect()
}

fn role_label(role: &MessageRole) -> &'static str {
    match role {
        MessageRole::System => "system",
        MessageRole::User => "user",
        MessageRole::Assistant => "assistant",
        MessageRole::Tool => "tool",
    }
}

fn normalize(value: &str, max_chars: usize) -> String {
    let collapsed = redact_sensitive(value)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    if collapsed.chars().count() <= max_chars {
        return collapsed;
    }
    let prefix: String = collapsed.chars().take(max_chars).collect();
    format!("{prefix}…")
}

fn redact_sensitive(value: &str) -> String {
    let sensitive_keys = [
        "api_key",
        "apikey",
        "password",
        "secret",
        "authorization",
        "access_token",
        "refresh_token",
    ];
    let mut output = Vec::new();
    let mut redact_next = false;
    for token in value.split_whitespace() {
        if redact_next {
            output.push("[REDACTED]".to_string());
            redact_next = false;
            continue;
        }
        let lower = token.to_ascii_lowercase();
        if lower.starts_with("sk-") || lower.contains("bearer=") {
            output.push("[REDACTED]".to_string());
            continue;
        }
        if lower == "bearer" || lower.ends_with(" bearer") {
            output.push(token.to_string());
            redact_next = true;
            continue;
        }
        if let Some((index, _)) = token.char_indices().find(|(_, c)| matches!(c, '=' | ':')) {
            let key = token[..index]
                .trim_matches(|character: char| matches!(character, '"' | '\'' | '{' | ','))
                .to_ascii_lowercase();
            if sensitive_keys.contains(&key.as_str()) {
                output.push(format!("{}[REDACTED]", &token[..=index]));
                continue;
            }
        }
        let bare = lower.trim_matches(|character: char| {
            matches!(character, '"' | '\'' | '{' | '}' | ',' | ':')
        });
        if sensitive_keys.contains(&bare) {
            output.push(token.to_string());
            redact_next = true;
            continue;
        }
        output.push(token.to_string());
    }
    output.join(" ")
}

fn evidence_digest(role: &str, excerpt: &str) -> String {
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in role
        .bytes()
        .chain(std::iter::once(0))
        .chain(excerpt.bytes())
    {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("fnv1a64:{hash:016x}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn message(role: MessageRole, text: &str) -> Message {
        Message {
            role,
            blocks: vec![ContentBlock::Text { text: text.into() }],
        }
    }

    #[test]
    fn extracts_marked_facts_and_verifies_sources() {
        let mut state = StructuredTaskState::default();
        state.absorb_messages(&[
            message(MessageRole::User, "迁移 model.py\nTODO: 对比 dtype"),
            message(MessageRole::Assistant, "DECISION: 使用 PYNATIVE_MODE"),
        ]);

        assert!(state
            .facts_of_kind(TaskFactKind::File)
            .any(|fact| fact.value == "model.py"));
        assert!(state
            .facts_of_kind(TaskFactKind::Pending)
            .any(|fact| fact.value == "对比 dtype"));
        assert!(state.evidence_valid());
        assert!(state.to_prompt_string().contains("[Structured Task State]"));
        assert!(!state.to_prompt_string().contains("source_excerpt"));
    }

    #[test]
    fn extracts_tool_inputs_without_copying_full_results_into_prompt() {
        let mut state = StructuredTaskState::default();
        state.absorb_messages(&[Message {
            role: MessageRole::Assistant,
            blocks: vec![
                ContentBlock::ToolCall {
                    id: "call-1".into(),
                    name: "read".into(),
                    input: r#"{"file_path":"src/model.py"}"#.into(),
                },
                ContentBlock::ToolCall {
                    id: "call-2".into(),
                    name: "shell".into(),
                    input: r#"{"command":"python -m pytest"}"#.into(),
                },
            ],
        }]);

        assert!(state
            .facts_of_kind(TaskFactKind::File)
            .any(|fact| fact.value == "src/model.py"));
        assert!(state
            .facts_of_kind(TaskFactKind::Command)
            .any(|fact| fact.value == "python -m pytest"));
        assert!(state.evidence_valid());
    }

    #[test]
    fn source_digest_detects_persisted_evidence_corruption() {
        let mut state = StructuredTaskState::default();
        state.absorb_messages(&[message(MessageRole::User, "Inspect model.py")]);
        assert!(state.evidence_valid());

        state.facts[0].source_excerpt.push_str(" tampered");

        assert!(!state.evidence_valid());
    }

    #[test]
    fn text_extraction_preserves_relative_path_prefixes() {
        let mut state = StructuredTaskState::default();
        state.absorb_messages(&[message(
            MessageRole::User,
            "Inspect ./src/model.py before editing.",
        )]);

        assert!(state
            .facts_of_kind(TaskFactKind::File)
            .any(|fact| fact.value == "./src/model.py"));
    }

    #[test]
    fn structured_state_redacts_common_secret_forms() {
        let mut state = StructuredTaskState::default();
        state.absorb_messages(&[message(
            MessageRole::User,
            "TODO: call provider with api_key=abc123 and Authorization: Bearer sk-secret-value",
        )]);

        let serialized = serde_json::to_string(&state).unwrap();
        assert!(!serialized.contains("abc123"));
        assert!(!serialized.contains("sk-secret-value"));
        assert!(serialized.contains("[REDACTED]"));
        assert!(state.evidence_valid());
    }
}
