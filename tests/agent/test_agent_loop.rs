use candle_cli::agent::r#loop::{run_single_turn, run_single_turn_with_budget};
use candle_cli::agent::state::AgentRunBudget;
use candle_cli::model::runtime::CandleTargetRuntime;
use candle_cli::model::types::{
    RuntimeCapabilities, RuntimeHealth, TokenUsage, TurnRequest, TurnResult,
};
use candle_cli::permissions::mode::PermissionMode;
use candle_cli::permissions::policy::PermissionPolicy;
use candle_cli::session::model::{ContentBlock, Message, MessageRole, Session};
use candle_cli::tools::registry::ToolRegistry;
use std::fs;
use std::sync::Mutex;

static PERMISSION_RESPONSE_LOCK: Mutex<()> = Mutex::new(());

struct ScriptedRuntime {
    responses: Vec<String>,
    requests: Vec<TurnRequest>,
}

impl ScriptedRuntime {
    fn new(responses: Vec<&str>) -> Self {
        Self {
            responses: responses.into_iter().map(str::to_string).rev().collect(),
            requests: Vec::new(),
        }
    }
}

impl CandleTargetRuntime for ScriptedRuntime {
    fn generate_turn(&mut self, request: TurnRequest) -> Result<TurnResult, String> {
        self.requests.push(request);
        let final_text = self
            .responses
            .pop()
            .ok_or_else(|| "script exhausted".to_string())?;
        Ok(TurnResult {
            final_text,
            tool_calls: Vec::new(),
            usage: TokenUsage::unreported_request(),
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

fn wrapped_tool_call(id: &str, name: &str, input: serde_json::Value) -> String {
    format!(
        "<tool_call>{}</tool_call>",
        serde_json::json!({"id": id, "name": name, "input": input})
    )
}

#[test]
fn agent_loop_runs_read_edit_shell_then_final_answer() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "old text\n").unwrap();

    let read_call = wrapped_tool_call(
        "call-read",
        "read",
        serde_json::json!({"file_path": file_path.to_string_lossy()}),
    );
    let edit_call = wrapped_tool_call(
        "call-edit",
        "edit",
        serde_json::json!({
            "file_path": file_path.to_string_lossy(),
            "old_string": "old text",
            "new_string": "new text"
        }),
    );
    let shell_call = r#"<tool_call>{"id":"call-shell","name":"shell","input":{"command":"printf checked"}}</tool_call>"#;

    let mut runtime = ScriptedRuntime::new(vec![&read_call, &edit_call, shell_call, "done"]);
    let tools = ToolRegistry::workspace_write(dir.path());
    let policy = PermissionPolicy::new(PermissionMode::DangerFullAccess);
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "update the file and check it".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();

    assert_eq!(result.final_text, "done");
    assert_eq!(result.usage.request_count, 4);
    assert_eq!(result.usage.usage_reported_request_count, 0);
    assert_eq!(result.usage.provider_cache_hit_rate(), None);
    assert_eq!(fs::read_to_string(&file_path).unwrap(), "new text\n");
}

#[test]
fn agent_loop_accepts_function_style_read_tool_call() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    fs::write(&file_path, "hello from file\n").unwrap();

    let read_call = format!(
        "read({})",
        serde_json::json!({"file_path": file_path.to_string_lossy()})
    );
    let mut runtime = ScriptedRuntime::new(vec![&read_call, "I read the file."]);
    let tools = ToolRegistry::workspace_write(dir.path());
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "read the file".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();

    assert_eq!(result.final_text, "I read the file.");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| {
            matches!(
                block,
                ContentBlock::ToolCall { name, .. } if name == "read"
            )
        })
    }));
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { is_error: false, output, .. } if output.contains("status: ok") && output.contains("tool: read") && output.contains("hello from file")
        ))
    }));
}

#[test]
fn agent_loop_blocks_shell_in_read_only_mode_and_recovers() {
    let shell_call = r#"<tool_call>{"id":"call-shell","name":"shell","input":{"command":"printf checked"}}</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![shell_call, "I could not run that command."]);
    let tools = ToolRegistry::read_only(".");
    let policy = PermissionPolicy::new(PermissionMode::ReadOnly);
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "run shell".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();

    assert_eq!(result.final_text, "I could not run that command.");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { is_error: true, output, .. } if output.contains("status: error") && output.contains("tool: shell") && output.contains("tool not allowed in read-only mode")
        ))
    }));
}

#[test]
fn agent_loop_denies_shell_in_prompt_mode_and_recovers() {
    let _guard = PERMISSION_RESPONSE_LOCK.lock().unwrap();
    std::env::set_var("CANDLE_CLI_PERMISSION_RESPONSE", "deny");
    let shell_call = r#"<tool_call>{"id":"call-shell","name":"shell","input":{"command":"printf checked"}}</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![shell_call, "Denied, so I stopped."]);
    let tools = ToolRegistry::workspace_write(".");
    let policy = PermissionPolicy::new(PermissionMode::Prompt);
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "run shell".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();
    std::env::remove_var("CANDLE_CLI_PERMISSION_RESPONSE");

    assert_eq!(result.final_text, "Denied, so I stopped.");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { is_error: true, output, .. } if output.contains("status: error") && output.contains("tool: shell") && output.contains("tool execution denied by user")
        ))
    }));
}

#[test]
fn agent_loop_allows_shell_in_prompt_mode_when_confirmed() {
    let _guard = PERMISSION_RESPONSE_LOCK.lock().unwrap();
    std::env::set_var("CANDLE_CLI_PERMISSION_RESPONSE", "allow");
    let shell_call = r#"<tool_call>{"id":"call-shell","name":"shell","input":{"command":"printf checked"}}</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![shell_call, "Allowed."]);
    let tools = ToolRegistry::workspace_write(".");
    let policy = PermissionPolicy::new(PermissionMode::Prompt);
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "run shell".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();
    std::env::remove_var("CANDLE_CLI_PERMISSION_RESPONSE");

    assert_eq!(result.final_text, "Allowed.");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| matches!(
            block,
            ContentBlock::ToolResult { is_error: false, output, .. } if output.contains("status: ok") && output.contains("tool: shell") && output.contains("exit_code: 0") && output.contains("checked") && !output.contains("output:\\nstatus: ok")
        ))
    }));
}

#[test]
fn agent_loop_appends_explicit_correction_message_for_malformed_tool_call() {
    let malformed = r#"<tool_call>{"id":"call-1"</tool_call>"#;
    let mut runtime = ScriptedRuntime::new(vec![malformed, "ok, I will stop."]);
    let tools = ToolRegistry::workspace_write(".");
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "do something".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();

    assert_eq!(result.final_text, "ok, I will stop.");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| {
            matches!(
                block,
                ContentBlock::Text { text }
                    if text.contains("The previous tool call was malformed")
                        && text.contains("<tool_call>")
                        && text.contains("retry with one valid tool call or provide a final answer")
            )
        })
    }));
}

#[test]
fn agent_loop_wraps_non_shell_tool_success_with_envelope() {
    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    std::fs::write(&file_path, "hello loop\n").unwrap();

    let read_call = wrapped_tool_call(
        "call-1",
        "read",
        serde_json::json!({"file_path": file_path.to_string_lossy()}),
    );
    let mut runtime = ScriptedRuntime::new(vec![&read_call, "done"]);
    let tools = ToolRegistry::workspace_write(dir.path());
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "read the file".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();

    assert_eq!(result.final_text, "done");
    assert!(session.messages.iter().any(|message| {
        message.blocks.iter().any(|block| {
            matches!(
                block,
                ContentBlock::ToolResult { is_error: false, output, .. }
                    if output.starts_with("status: ok\ntool: read\noutput:\n")
                        && output.contains("hello loop")
            )
        })
    }));
}

#[test]
fn agent_loop_emits_verbose_trace_lines_to_stderr_only() {
    let _guard = PERMISSION_RESPONSE_LOCK.lock().unwrap();
    std::env::set_var("CANDLE_CLI_VERBOSE", "1");

    let dir = tempfile::tempdir().unwrap();
    let file_path = dir.path().join("note.txt");
    std::fs::write(&file_path, "hi\n").unwrap();

    let read_call = wrapped_tool_call(
        "call-1",
        "read",
        serde_json::json!({"file_path": file_path.to_string_lossy()}),
    );
    let mut runtime = ScriptedRuntime::new(vec![&read_call, "done"]);
    let tools = ToolRegistry::workspace_write(dir.path());
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "read the file".to_string(),
        }],
    });

    let result = run_single_turn(&mut session, &mut runtime, &tools, &policy).unwrap();
    std::env::remove_var("CANDLE_CLI_VERBOSE");

    assert_eq!(result.final_text, "done");
    let session_dump = serde_json::to_string(&session.messages).unwrap();
    assert!(!session_dump.contains("[tool step"));
    assert!(!session_dump.contains("[tool result]"));
    assert!(!session_dump.contains("[tool parse error]"));
}

#[test]
fn task_subagent_shares_parent_workspace_and_global_budget() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("evidence.txt"), "dtype=float32\n").unwrap();
    let task_call = wrapped_tool_call(
        "call-task",
        "task",
        serde_json::json!({"description": "Read evidence.txt and report its dtype"}),
    );
    let read_call = wrapped_tool_call(
        "call-read",
        "read",
        serde_json::json!({"file_path": "evidence.txt"}),
    );
    let mut runtime = ScriptedRuntime::new(vec![
        &task_call,
        &read_call,
        "dtype=float32",
        "The delegated result is dtype=float32.",
    ]);
    let tools = ToolRegistry::read_only(dir.path());
    let policy = PermissionPolicy::new(PermissionMode::ReadOnlyWithTask);
    let mut session = Session::new(dir.path().display().to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "Delegate the evidence inspection.".to_string(),
        }],
    });
    let mut budget = AgentRunBudget::new(4, 2);

    let result =
        run_single_turn_with_budget(&mut session, &mut runtime, &tools, &policy, 8, &mut budget)
            .unwrap();

    assert_eq!(result.final_text, "The delegated result is dtype=float32.");
    assert_eq!(result.usage.request_count, 4);
    assert_eq!(budget.model_requests_used(), 4);
    assert_eq!(budget.tool_steps_used(), 2);
    assert_eq!(budget.subagent_invocations(), 1);
    assert!(runtime
        .requests
        .iter()
        .any(|request| request.messages_json.contains("dtype=float32")));
}

#[test]
fn shared_budget_stops_parent_and_subagent_at_the_same_request_limit() {
    let task_call = wrapped_tool_call(
        "call-task",
        "task",
        serde_json::json!({"description": "Inspect the workspace"}),
    );
    let read_call = wrapped_tool_call(
        "call-read",
        "read",
        serde_json::json!({"file_path": "Cargo.toml"}),
    );
    let mut runtime = ScriptedRuntime::new(vec![&task_call, &read_call, "unused"]);
    let tools = ToolRegistry::read_only(".");
    let policy = PermissionPolicy::new(PermissionMode::ReadOnlyWithTask);
    let mut session = Session::new(".".to_string());
    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text {
            text: "Delegate this task.".to_string(),
        }],
    });
    let mut budget = AgentRunBudget::new(2, 2);

    let result =
        run_single_turn_with_budget(&mut session, &mut runtime, &tools, &policy, 8, &mut budget)
            .unwrap();

    assert!(result.final_text.contains("shared model request budget"));
    assert_eq!(result.usage.request_count, 2);
    assert_eq!(budget.model_requests_used(), 2);
    assert_eq!(budget.tool_steps_used(), 2);
    assert_eq!(budget.subagent_invocations(), 1);
    assert_eq!(runtime.requests.len(), 2);
}
