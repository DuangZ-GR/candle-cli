use candle_cli::cli::args::{Cli, CommandMode};
use candle_cli::cli::repl::{run_prompt, run_repl};
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
        Some(CommandMode::Doctor) => {}
        None => {
            let _ = run_repl(session_dir);
        }
    }
}
