use crate::agent::r#loop::{run_single_turn, run_single_turn_with_trace};
use crate::agent::trace::ExecutionTrace;
use crate::context::builder::resolve_system_prompt;
use crate::model::bridge::LocalBridgeRuntime;
use crate::model::mock::MockRuntime;
use crate::permissions::mode::PermissionMode;
use crate::permissions::policy::PermissionPolicy;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::session::store::SessionStore;
use crate::tools::registry::ToolRegistry;
use std::io;
use std::path::PathBuf;

// ── REPL main loop ──────────────────────────────────────────────────────

pub fn run_repl(session_dir: PathBuf) -> io::Result<()> {
    let workspace_root = std::env::current_dir()?;
    let store = SessionStore::new(session_dir);
    let mut session = Session::new(workspace_root.display().to_string());
    let tools = ToolRegistry::workspace_write(workspace_root.clone());
    let policy = PermissionPolicy::new(resolve_permission_mode());
    let mut last_trace: Option<ExecutionTrace> = None;

    let mut rl = rustyline::DefaultEditor::new().map_err(io::Error::other)?;

    print_banner(&session);

    while let Ok(input) = rl.readline("> ") {
        if input.is_empty() {
            continue;
        }

        let _ = rl.add_history_entry(&input);

        // slash command dispatch
        if input.starts_with('/') {
            let handled = handle_slash_command(&input, &mut session, &store, &last_trace, &tools);
            if handled {
                return Ok(());
            }
            continue;
        }

        // push user message
        session.messages.push(Message {
            role: MessageRole::User,
            blocks: vec![ContentBlock::Text { text: input }],
        });

        let mut current_trace = ExecutionTrace::new();

        // run turn
        let result = match std::env::var("CANDLE_CLI_RUNTIME").ok().as_deref() {
            Some("bridge") => {
                let mut runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
                run_single_turn_with_trace(
                    &mut session,
                    &mut runtime,
                    &tools,
                    &policy,
                    &mut current_trace,
                )
            }
            _ => {
                let mut runtime = MockRuntime;
                run_single_turn_with_trace(
                    &mut session,
                    &mut runtime,
                    &tools,
                    &policy,
                    &mut current_trace,
                )
            }
        };

        match result {
            Ok(_) => {
                last_trace = Some(current_trace);
                store.save(&session)?;
                print_last_assistant(&session);
            }
            Err(msg) => {
                use std::io::Write;
                let mut stderr = io::stderr();
                let _ = writeln!(stderr, "error: {msg}");
                let _ = stderr.flush();
            }
        }
    }
    Ok(())
}

// ── prompt mode ─────────────────────────────────────────────────────────

pub fn run_prompt(session_dir: PathBuf, input: String) -> io::Result<()> {
    let workspace_root = std::env::current_dir()?;
    let store = SessionStore::new(session_dir);
    let mut session = Session::new(workspace_root.display().to_string());
    let tools = ToolRegistry::workspace_write(workspace_root.clone());
    let policy = PermissionPolicy::new(resolve_permission_mode());

    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text { text: input }],
    });

    match std::env::var("CANDLE_CLI_RUNTIME").ok().as_deref() {
        Some("bridge") => {
            let mut runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
            run_single_turn(&mut session, &mut runtime, &tools, &policy)
                .map_err(io::Error::other)?;
        }
        _ => {
            let mut runtime = MockRuntime;
            run_single_turn(&mut session, &mut runtime, &tools, &policy)
                .map_err(io::Error::other)?;
        }
    }

    store.save(&session)?;
    print_last_assistant(&session);
    Ok(())
}

fn resolve_permission_mode() -> PermissionMode {
    std::env::var("CANDLE_CLI_PERMISSION")
        .ok()
        .and_then(|value| value.parse::<PermissionMode>().ok())
        .unwrap_or(PermissionMode::WorkspaceWrite)
}

/// Returns `true` if the REPL should exit.
fn handle_slash_command(
    input: &str,
    session: &mut Session,
    store: &SessionStore,
    last_trace: &Option<ExecutionTrace>,
    tools: &ToolRegistry,
) -> bool {
    use std::io::Write;

    let body = input.strip_prefix('/').unwrap_or(input).trim().to_string();

    let (cmd, arg) = body
        .split_once(char::is_whitespace)
        .map(|(c, a)| (c.trim().to_lowercase(), a.trim().to_string()))
        .unwrap_or((body.to_lowercase(), String::new()));

    let mut stdout = io::stdout();

    match cmd.as_str() {
        "exit" | "quit" | "q" if arg.is_empty() => {
            store.save(session).ok();
            let _ = writeln!(stdout, "bye.");
            return true;
        }
        "help" | "h" => {
            let _ = writeln!(stdout, "{}", HELP_TEXT);
        }
        "name" => {
            if arg.is_empty() {
                let _ = writeln!(stdout, "usage: /name <label>");
                if let Some(ref label) = session.label {
                    let _ = writeln!(stdout, "current name: {label}");
                } else {
                    let _ = writeln!(stdout, "current name: (none)");
                }
            } else {
                session.label = Some(arg.clone());
                store.save(session).ok();
                let _ = writeln!(stdout, "session named: {arg}");
            }
        }
        "tools" => {
            let _ = writeln!(stdout, "Registered tools");
            for name in tools.tool_names() {
                let _ = writeln!(stdout, "- {name}");
            }
        }
        "status" => {
            let permission = resolve_permission_mode();
            for line in render_status_lines(session, permission) {
                let _ = writeln!(stdout, "{line}");
            }
        }
        "trace" => match last_trace {
            Some(trace) if !trace.is_empty() => {
                for line in trace.render_lines() {
                    let _ = writeln!(stdout, "{line}");
                }
            }
            _ => {
                let _ = writeln!(stdout, "no trace available");
            }
        },
        "clear" => {
            let current_id = session.session_id.clone();
            *session = Session::new(session.workspace_root.clone());
            session.session_id = current_id;
            store.save(session).ok();
            let _ = writeln!(stdout, "session cleared (id: {}).", session.session_id);
        }
        "system" => {
            let prompt = resolve_system_prompt();
            let _ = writeln!(stdout, "system prompt:\n{prompt}");
        }
        "session" | "info" => {
            let name = session
                .label
                .as_deref()
                .unwrap_or("(unnamed)");
            let _ = writeln!(
                stdout,
                "session: {} | name: {name} | messages: {} | workspace: {}",
                session.session_id,
                session.messages.len(),
                session.workspace_root,
            );
        }
        "list" | "ls" => match store.list() {
            Ok(ids) => {
                if ids.is_empty() {
                    let _ = writeln!(stdout, "no saved sessions.");
                } else {
                    let _ = writeln!(stdout, "saved sessions:");
                    for id in ids {
                        let meta = store.load(&id).map(|s| {
                            let label = s.label.as_deref().unwrap_or("-");
                            (s.messages.len(), label.to_string())
                        });
                        match meta {
                            Ok((n, label)) => {
                                let _ = writeln!(stdout, "  {id}  [{label}]  ({n} messages)");
                            }
                            Err(_) => {
                                let _ = writeln!(stdout, "  {id}");
                            }
                        }
                    }
                }
            }
            Err(e) => {
                let _ = writeln!(stdout, "error listing sessions: {e}");
            }
        },
        "resume" => {
            if arg.is_empty() {
                let _ = writeln!(stdout, "usage: /resume <session-id>");
            } else {
                match store.load(&arg) {
                    Ok(loaded) => {
                        *session = loaded;
                        let _ = writeln!(
                            stdout,
                            "resumed session: {} ({} messages).",
                            session.session_id,
                            session.messages.len()
                        );
                    }
                    Err(e) => {
                        let _ = writeln!(stdout, "error: cannot resume '{arg}' — {e}");
                    }
                }
            }
        }
        "save" => match store.save(session) {
            Ok(()) => {
                let _ = writeln!(
                    stdout,
                    "saved session: {} ({} messages).",
                    session.session_id,
                    session.messages.len()
                );
            }
            Err(e) => {
                let _ = writeln!(stdout, "error saving session: {e}");
            }
        },
        "" => {
            // bare "/" — ignore
        }
        other => {
            let _ = writeln!(stdout, "unknown command: /{other}");
        }
    }
    let _ = stdout.flush();
    false
}

// ── helpers ─────────────────────────────────────────────────────────────

fn print_banner(session: &Session) {
    use std::io::Write;
    let mut stdout = io::stdout();
    let _ = writeln!(
        stdout,
        "candle-cli REPL   session: {}   /help for commands, /exit to quit",
        session.session_id
    );
    let _ = stdout.flush();
}

fn print_last_assistant(session: &Session) {
    use std::io::Write;
    for msg in session.messages.iter().rev() {
        if msg.role == MessageRole::Assistant {
            for block in &msg.blocks {
                if let ContentBlock::Text { text } = block {
                    let mut stdout = io::stdout();
                    let _ = writeln!(stdout, "\n{}", text);
                    let _ = stdout.flush();
                }
            }
            break;
        }
    }
}

fn render_status_lines(session: &Session, permission: PermissionMode) -> Vec<String> {
    let runtime = std::env::var("CANDLE_CLI_RUNTIME").unwrap_or_else(|_| "mock".to_string());
    let model = std::env::var("CANDLE_CLI_MODEL_ID")
        .unwrap_or_else(|_| "Qwen/Qwen2-0.5B-Instruct".to_string());
    let max_turns = std::env::var("CANDLE_CLI_MAX_TURNS").unwrap_or_else(|_| "20".to_string());

    vec![
        "Session".to_string(),
        format!("- session_id: {}", session.session_id),
        format!("- messages: {}", session.messages.len()),
        format!("- workspace: {}", session.workspace_root),
        format!("- permission: {:?}", permission),
        format!("- runtime: {}", runtime),
        format!("- model: {}", model),
        format!("- max_turns: {}", max_turns),
    ]
}

const HELP_TEXT: &str = r#"
  /exit, /quit     退出 REPL
  /help            显示帮助
  /name <label>    为当前会话命名
  /system          查看当前系统提示词
  /clear           清空当前 session
  /session         查看当前 session 信息
  /status          查看当前运行状态
  /tools           查看当前可用工具列表
  /trace           查看最近一次执行链路
  /list            列出所有已保存 session
  /resume <id>     恢复指定 session
  /save            保存当前 session
"#;
