use crate::agent::r#loop::run_single_turn;
use crate::model::mock::MockRuntime;
use crate::session::model::{ContentBlock, Message, MessageRole, Session};
use crate::session::store::SessionStore;
use crate::tools::registry::ToolRegistry;
use std::io;
use std::path::PathBuf;

pub fn run_repl(session_dir: PathBuf) -> io::Result<()> {
    let store = SessionStore::new(session_dir);
    let mut session = Session::new(std::env::current_dir()?.display().to_string());
    let mut runtime = MockRuntime::default();
    let tools = ToolRegistry::default_read_only();

    let input = read_line("> ")?;
    if !input.is_empty() {
        session.messages.push(Message {
            role: MessageRole::User,
            blocks: vec![ContentBlock::Text { text: input }],
        });
        run_single_turn(&mut session, &mut runtime, &tools, "sys")
            .map_err(io::Error::other)?;
        store.save(&session)?;
    }

    Ok(())
}

pub fn run_prompt(session_dir: PathBuf, input: String) -> io::Result<()> {
    let store = SessionStore::new(session_dir);
    let mut session = Session::new(std::env::current_dir()?.display().to_string());
    let mut runtime = MockRuntime::default();
    let tools = ToolRegistry::default_read_only();

    session.messages.push(Message {
        role: MessageRole::User,
        blocks: vec![ContentBlock::Text { text: input }],
    });
    run_single_turn(&mut session, &mut runtime, &tools, "sys").map_err(io::Error::other)?;
    store.save(&session)?;
    Ok(())
}

pub fn read_line(prompt: &str) -> io::Result<String> {
    use std::io::Write;

    let mut stdout = io::stdout();
    write!(stdout, "{}", prompt)?;
    stdout.flush()?;

    let mut buffer = String::new();
    io::stdin().read_line(&mut buffer)?;
    while matches!(buffer.chars().last(), Some('\n' | '\r')) {
        buffer.pop();
    }
    Ok(buffer)
}
