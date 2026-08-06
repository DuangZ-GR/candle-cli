use candle_cli::cli::agent_experiment::run_agent_experiment;
use candle_cli::cli::args::{Cli, CommandMode};
use candle_cli::cli::context_harness::run_context_harness;
use candle_cli::cli::doctor::run_doctor;
use candle_cli::cli::harness::run_harness;
use candle_cli::cli::migrate::run_migrate;
use candle_cli::cli::repl::{run_prompt, run_repl};
use candle_cli::cli::security_harness::run_security_harness;
use candle_cli::cli::security_heldout::run_security_heldout;
use clap::Parser;
use std::path::PathBuf;

fn session_dir() -> PathBuf {
    if let Ok(value) = std::env::var("CANDLE_CLI_SESSION_DIR") {
        return PathBuf::from(value);
    }

    std::env::temp_dir().join("candle-cli-sessions")
}

fn main() -> std::io::Result<()> {
    let cli = Cli::parse();
    let session_dir = session_dir();

    match cli.command {
        Some(CommandMode::Prompt { input }) => run_prompt(session_dir, input),
        Some(CommandMode::Harness) => run_harness(session_dir),
        Some(CommandMode::SecurityHarness) => run_security_harness(),
        Some(CommandMode::SecurityHeldout) => run_security_heldout(),
        Some(CommandMode::ContextHarness) => run_context_harness(),
        Some(CommandMode::AgentExperiment {
            config,
            output,
            smoke,
        }) => run_agent_experiment(config, output, smoke),
        Some(CommandMode::Doctor { json }) => run_doctor(json),
        Some(CommandMode::Migrate { command }) => run_migrate(command),
        None => run_repl(session_dir),
    }
}
