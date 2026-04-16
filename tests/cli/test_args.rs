use candle_cli::cli::args::{Cli, CommandMode};
use clap::Parser;

#[test]
fn parses_prompt_mode() {
    let cli = Cli::parse_from(["candle-cli", "prompt", "hello"]);
    assert!(matches!(cli.command, Some(CommandMode::Prompt { .. })));
}

#[test]
fn parses_resume_flag() {
    let cli = Cli::parse_from(["candle-cli", "--resume"]);
    assert!(cli.resume);
}
