use candle_cli::agent::r#loop::run_single_turn;
use candle_cli::model::runtime::CandleTargetRuntime;
use candle_cli::model::types::{RuntimeCapabilities, RuntimeHealth, TurnRequest, TurnResult};
use candle_cli::session::model::{ContentBlock, Message, MessageRole, Session};
use candle_cli::tools::registry::ToolRegistry;
use std::fs;

struct ScriptedRuntime {
    responses: Vec<String>,
}

impl ScriptedRuntime {
    fn new(responses: Vec<&str>) -> Self {
        Self {
            responses: responses.into_iter().map(str::to_string).rev().collect(),
        }
    }
}

impl CandleTargetRuntime for ScriptedRuntime {
    fn generate_turn(&mut self, _request: TurnRequest) -> Result<TurnResult, String> {
        let final_text = self
            .responses
            .pop()
            .ok_or_else(|| "script exhausted".to_string())?;
        Ok(TurnResult {
            final_text,
            tool_calls: Vec::new(),
        })
    }

    fn healthcheck(&self) -> RuntimeHealth {
        RuntimeHealth {
            ok: true,
            message: "ok".to_string(),
        }
    }

    fn capabilities(&self) -> RuntimeCapabilities {
        RuntimeCapabilities {
            supports_tools: true,
            supports_streaming: false,
        }
    }
}

#[test]
fn agent_loop_returns_final_text() {
    let mut session = Session::new("/tmp/workspace".into());
    let mut runtime = ScriptedRuntime::new(vec!["final answer"]);
    let tools = ToolRegistry::default_workspace_write();
    let result = run_single_turn(&mut session, &mut runtime, &tools).unwrap();
    assert_eq!(result.final_text, "final answer");
}

#[test]
fn agent_loop_runs_read_edit_shell_then_final_answer() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "old text\n").unwrap();

    let read_call = format!(
        r#"<tool_call>{{"id":"call-read","name":"read","input":{{"file_path":"{}"}}}}</tool_call>"#,
        file_path.display()
    );
    let edit_call = format!(
        r#"<tool_call>{{"id":"call-edit","name":"edit","input":{{"file_path":"{}","old_string":"old text","new_string":"new text"}}}}</tool_call>"#,
        file_path.display()
    );
    let shell_call = r#"<tool_call>{"id":"call-shell","name":"shell","input":{"command":"printf checked"}}</tool_call>"#;

    let mut runtime = ScriptedRuntime::new(vec![&read_call, &edit_call, shell_call, "done"]);
    let tools = ToolRegistry::default_workspace_write();
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "update the file and check it".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools).unwrap();

    assert_eq!(result.final_text, "done");
    assert_eq!(fs::read_to_string(&file_path).unwrap(), "new text\n");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { output, is_error: false, .. } if output.contains("checked")
        ))
    }));
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| {
            matches!(
                block,
                ContentBlock::ToolCall { name, .. } if name == "read"
            )
        })
    }));
}

#[test]
fn agent_loop_records_tool_errors_and_allows_recovery() {
    let missing_read = r#"<tool_call>{"id":"call-read","name":"read","input":{"file_path":"/definitely/missing/file.txt"}}</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![missing_read, "I could not read that file."]);
    let tools = ToolRegistry::default_workspace_write();
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "read missing file".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools).unwrap();

    assert_eq!(result.final_text, "I could not read that file.");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { is_error: true, output, .. } if output.contains("not a file") || output.contains("failed to read")
        ))
    }));
}

#[test]
fn agent_loop_stops_after_max_steps() {
    let repeated = r#"<tool_call>{"id":"call-pwd","name":"pwd","input":{}}</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![
        repeated, repeated, repeated, repeated, repeated, repeated, repeated, repeated,
    ]);
    let tools = ToolRegistry::default_workspace_write();
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "loop forever".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools).unwrap();

    assert!(result.final_text.contains("maximum tool steps"));
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| {
            matches!(
                block,
                ContentBlock::Text { text } if text.contains("maximum tool steps")
            )
        })
    }));
}

#[test]
fn agent_loop_handles_malformed_tool_call_with_recovery() {
    let malformed = r#"<tool_call>{"id":"bad"</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![malformed, "recovered and answering normally"]);
    let tools = ToolRegistry::default_workspace_write();
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "do something".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools).unwrap();

    assert_eq!(result.final_text, "recovered and answering normally");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| {
            matches!(
                block,
                ContentBlock::Text { text } if text.contains("malformed")
            )
        })
    }));
}
