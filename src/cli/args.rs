use clap::{Parser, Subcommand};

#[derive(Parser, Debug)]
#[command(name = "candle-cli")]
pub struct Cli {
    #[arg(long)]
    pub resume: bool,
    #[command(subcommand)]
    pub command: Option<CommandMode>,
}

#[derive(Subcommand, Debug)]
pub enum CommandMode {
    Prompt { input: String },
    Doctor,
}
