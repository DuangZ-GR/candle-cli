use candle_cli::cli::args::{Cli, CommandMode};
use clap::Parser;

fn main() {
    let cli = Cli::parse();

    match cli.command {
        Some(CommandMode::Prompt { .. }) => {}
        Some(CommandMode::Doctor) => {}
        None => {}
    }
}
