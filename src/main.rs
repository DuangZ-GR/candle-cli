use candle_cli::cli::args::{Cli, CommandMode};
use candle_cli::cli::repl::{run_prompt, run_repl};
use candle_cli::ui::format::format_status_line;
use candle_cli::ui::render::render_line;
use clap::Parser;
use std::path::PathBuf;

fn session_dir() -> PathBuf {
    if let Ok(value) = std::env::var("CANDLE_CLI_SESSION_DIR") {
        return PathBuf::from(value);
    }

    std::env::temp_dir().join("candle-cli-sessions")
}

fn main() {
    let cli = Cli::parse();
    let session_dir = session_dir();

    match cli.command {
        Some(CommandMode::Prompt { input }) => {
            let _ = run_prompt(session_dir, input);
        }
        Some(CommandMode::Doctor) => {
            render_line(&format_status_line("runtime", "mock"));
            render_line(&format_status_line("session_dir", &session_dir.display().to_string()));
        }
        None => {
            let _ = run_repl(session_dir);
        }
    }
}
