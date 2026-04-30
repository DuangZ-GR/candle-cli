use crate::agent::r#loop::run_single_turn;
use crate::context::builder::resolve_system_prompt;
use crate::model::bridge::LocalBridgeRuntime;
use crate::model::mock::MockRuntime;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::session::store::SessionStore;
use crate::tools::registry::ToolRegistry;
use std::io;
use std::path::PathBuf;

// ── REPL main loop ──────────────────────────────────────────────────────

pub fn run_repl(session_dir: PathBuf) -> io::Result<()> {
    let store = SessionStore::new(session_dir);
    let mut session = Session::new(std::env::current_dir()?.display().to_string());
    let tools = ToolRegistry::default_read_only();

    print_banner();

    while let Ok(input) = read_line("> ") {
        if input.is_empty() {
            continue;
        }

        // slash command dispatch
        if input.starts_with('/') {
            let handled = handle_slash_command(&input, &mut session, &store);
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

        // run turn
        let result = match std::env::var("CANDLE_CLI_RUNTIME").ok().as_deref() {
            Some("bridge") => {
                let mut runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
                run_single_turn(&mut session, &mut runtime, &tools)
            }
            _ => {
                let mut runtime = MockRuntime;
                run_single_turn(&mut session, &mut runtime, &tools)
            }
        };

        match result {
            Ok(_) => {
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
    let store = SessionStore::new(session_dir);
    let mut session = Session::new(std::env::current_dir()?.display().to_string());
    let tools = ToolRegistry::default_read_only();

    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text { text: input }],
    });

    match std::env::var("CANDLE_CLI_RUNTIME").ok().as_deref() {
        Some("bridge") => {
            let mut runtime = LocalBridgeRuntime::new("python3 python/bridge_worker.py".into());
            run_single_turn(&mut session, &mut runtime, &tools).map_err(io::Error::other)?;
        }
        _ => {
            let mut runtime = MockRuntime;
            run_single_turn(&mut session, &mut runtime, &tools).map_err(io::Error::other)?;
        }
    }

    store.save(&session)?;
    print_last_assistant(&session);
    Ok(())
}

// ── slash commands ──────────────────────────────────────────────────────

/// Returns `true` if the REPL should exit.
fn handle_slash_command(input: &str, session: &mut Session, store: &SessionStore) -> bool {
    use std::io::Write;

    let cmd = input
        .strip_prefix('/')
        .unwrap_or(input)
        .trim()
        .to_lowercase();

    let mut stdout = io::stdout();

    match cmd.as_str() {
        "exit" | "quit" | "q" => {
            store.save(session).ok();
            let _ = writeln!(stdout, "bye.");
            return true;
        }
        "help" | "h" => {
            let _ = writeln!(stdout, "{}", HELP_TEXT);
        }
        "clear" => {
            *session = Session::new(session.workspace_root.clone());
            store.save(session).ok();
            let _ = writeln!(stdout, "session cleared.");
        }
        "system" => {
            let prompt = resolve_system_prompt();
            let _ = writeln!(stdout, "system prompt:\n{prompt}");
        }
        "session" => {
            let _ = writeln!(
                stdout,
                "session: {} | messages: {} | workspace: {}",
                session.session_id,
                session.messages.len(),
                session.workspace_root,
            );
        }
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

fn print_banner() {
    use std::io::Write;
    let mut stdout = io::stdout();
    let _ = writeln!(
        stdout,
        "candle-cli REPL   type /help for commands, /exit to quit"
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

pub fn read_line(prompt: &str) -> io::Result<String> {
    use std::io::Write;

    let mut stdout = io::stdout();
    write!(stdout, "{}", prompt)?;
    stdout.flush()?;

    let mut buffer = String::new();
    let n = io::stdin().read_line(&mut buffer)?;
    if n == 0 {
        return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "EOF"));
    }
    while matches!(buffer.chars().last(), Some('\n' | '\r')) {
        buffer.pop();
    }
    Ok(buffer)
}

const HELP_TEXT: &str = r#"
  /exit, /quit     退出 REPL
  /help            显示帮助
  /system          查看当前系统提示词
  /clear           清空当前 session
  /session         查看 session 信息
"#;
